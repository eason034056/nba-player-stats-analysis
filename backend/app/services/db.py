"""
db.py - PostgreSQL 資料庫服務

使用 asyncpg 提供異步 PostgreSQL 連線池和查詢功能。
負責：
1. 管理資料庫連線池（connection pool）
2. 應用啟動時自動建立資料表（schema migration）
3. 提供查詢輔助方法（execute, fetch, fetchrow）

asyncpg 是高效能的異步 PostgreSQL 驅動，不依賴 ORM，
直接使用 SQL 查詢，與專案現有風格一致（輕量、直接）。

使用方式：
    from app.services.db import db_service
    
    # 啟動時初始化
    await db_service.init()
    
    # 查詢
    rows = await db_service.fetch("SELECT * FROM player_projections WHERE date = $1", date)
    
    # 關閉時清理
    await db_service.close()
"""

import asyncpg
from typing import Optional, Any, List
from app.settings import settings


# ==================== 資料表建立 SQL ====================

SCHEMA_SQL = """
-- 球員投影資料表
-- 儲存 SportsDataIO 的每日球員比賽投影數據
-- 每個球員每場比賽一筆紀錄，用 (date, player_name, game_id) 作為唯一約束
CREATE TABLE IF NOT EXISTS player_projections (
    id SERIAL PRIMARY KEY,
    
    -- 比賽日期（EST 時區）
    date DATE NOT NULL,
    
    -- 球員基本資訊
    player_id INTEGER,               -- SportsDataIO 球員 ID
    player_name TEXT NOT NULL,       -- 球員姓名
    team TEXT,                       -- 球隊縮寫（如 GS, LAL）
    position TEXT,                   -- 場上位置（PG/SG/SF/PF/C）
    
    -- 對戰資訊
    opponent TEXT,                   -- 對手球隊縮寫
    home_or_away TEXT,               -- HOME 或 AWAY
    game_id INTEGER,                 -- SportsDataIO 比賽 ID
    
    -- 核心投影數據（Free Trial 可用）
    minutes REAL,                    -- 預計上場分鐘數
    points REAL,                     -- 預計得分
    rebounds REAL,                   -- 預計籃板
    assists REAL,                    -- 預計助攻
    steals REAL,                     -- 預計抄截
    blocked_shots REAL,              -- 預計阻攻
    turnovers REAL,                  -- 預計失誤
    field_goals_made REAL,           -- 投籃命中數
    field_goals_attempted REAL,      -- 投籃出手數
    three_pointers_made REAL,        -- 三分命中數
    three_pointers_attempted REAL,   -- 三分出手數
    free_throws_made REAL,           -- 罰球命中數
    free_throws_attempted REAL,      -- 罰球出手數
    
    -- 先發與傷病（Free Trial 會被 scrambled）
    started INTEGER,                 -- 是否先發（1=Yes, 0=No）
    lineup_confirmed BOOLEAN,        -- 先發是否已確認
    injury_status TEXT,              -- 傷病狀態
    injury_body_part TEXT,           -- 傷病部位
    
    -- 對位難度
    opponent_rank INTEGER,           -- 對手整體防守排名（1-30）
    opponent_position_rank INTEGER,  -- 對手對該位置防守排名
    
    -- DFS 薪資
    draftkings_salary REAL,          -- DraftKings DFS 薪資
    fanduel_salary REAL,             -- FanDuel DFS 薪資
    
    -- Fantasy 分數
    fantasy_points_dk REAL,          -- DraftKings Fantasy 分數
    fantasy_points_fd REAL,          -- FanDuel Fantasy 分數
    
    -- 進階指標
    usage_rate_percentage REAL,      -- 球權使用率
    player_efficiency_rating REAL,   -- 球員效率值（PER）
    
    -- 中繼資料
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- 資料抓取時間
    api_updated_at TIMESTAMPTZ,      -- API 回傳的最後更新時間
    
    -- 唯一約束：同一天 + 同一球員 + 同一場比賽 只能有一筆
    UNIQUE(date, player_name, game_id)
);

-- 索引：加速常用查詢
CREATE INDEX IF NOT EXISTS idx_proj_date ON player_projections(date);
CREATE INDEX IF NOT EXISTS idx_proj_player ON player_projections(player_name);
CREATE INDEX IF NOT EXISTS idx_proj_date_player ON player_projections(date, player_name);

-- 投影抓取日誌表
-- 記錄每次 API 呼叫的狀態，用於監控和除錯
CREATE TABLE IF NOT EXISTS projection_fetch_logs (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,                              -- 查詢的比賽日期
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- 抓取時間
    player_count INTEGER,                            -- 回傳的球員數
    status TEXT,                                     -- 狀態（success / error）
    error_message TEXT,                              -- 錯誤訊息（如果有）
    duration_ms INTEGER                              -- 耗時（毫秒）
);


-- ==================== 盤口快照（Line Movement Tracking）====================

-- 盤口快照資料表
-- 儲存每次排程快照時各博彩公司的 no-vig 計算結果
-- 一筆 = 一個 snapshot 時間 + 一場比賽 + 一個球員 + 一個 market + 一個 bookmaker
-- 用於追蹤盤口隨時間變動（opening → closing lines）
CREATE TABLE IF NOT EXISTS odds_line_snapshots (
    id SERIAL PRIMARY KEY,

    -- 快照時間：記錄這筆資料是何時擷取的
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 比賽日期（EST 時區，與 player_projections 一致）
    date DATE NOT NULL,

    -- 賽事資訊（來自 The Odds API）
    event_id TEXT NOT NULL,              -- The Odds API event ID
    home_team TEXT,                      -- 主場球隊
    away_team TEXT,                      -- 客場球隊

    -- 球員 & 市場
    player_name TEXT NOT NULL,           -- 球員姓名（如 "Stephen Curry"）
    market TEXT NOT NULL,                -- 市場類型（player_points, player_rebounds 等）

    -- 博彩公司
    bookmaker TEXT NOT NULL,             -- 博彩公司 key（如 "draftkings"）

    -- 盤口 & 原始賠率
    line NUMERIC,                        -- 門檻值（如 24.5），這是「會移動」的數字
    over_odds INTEGER,                   -- Over 美式賠率（如 -110）
    under_odds INTEGER,                  -- Under 美式賠率（如 -110）

    -- No-Vig 計算結果
    vig NUMERIC,                         -- 水錢（如 0.0476 表示 4.76%）
    over_fair_prob NUMERIC,              -- Over 去水機率（如 0.5000）
    under_fair_prob NUMERIC,             -- Under 去水機率（如 0.5000）

    -- 唯一約束：同一快照時間 + 同一場 + 同一球員 + 同一 market + 同一 bookmaker
    UNIQUE(snapshot_at, event_id, player_name, market, bookmaker)
);

-- 索引：加速常用查詢模式
-- 查詢某球員某 market 在某天的所有快照（line movement）
CREATE INDEX IF NOT EXISTS idx_ols_player_market ON odds_line_snapshots(player_name, market, date);
-- 查詢某場比賽某 market 的所有快照
CREATE INDEX IF NOT EXISTS idx_ols_event ON odds_line_snapshots(event_id, market);
-- 按日期查詢
CREATE INDEX IF NOT EXISTS idx_ols_date ON odds_line_snapshots(date);
-- 按快照時間查詢
CREATE INDEX IF NOT EXISTS idx_ols_snapshot ON odds_line_snapshots(snapshot_at);


-- 盤口快照日誌表
-- 記錄每次快照執行的摘要（成功/失敗、耗時、筆數）
CREATE TABLE IF NOT EXISTS odds_snapshot_logs (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,                              -- 快照的比賽日期
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- 快照執行時間
    event_count INTEGER,                             -- 處理的賽事數
    total_lines INTEGER,                             -- 寫入的 odds line 總筆數
    status TEXT,                                     -- 狀態（success / error）
    error_message TEXT,                              -- 錯誤訊息（如果有）
    duration_ms INTEGER                              -- 耗時（毫秒）
);
"""


class DatabaseService:
    """
    PostgreSQL 資料庫服務類別
    
    使用 asyncpg 連線池（connection pool）管理資料庫連線。
    連線池的好處：
    - 避免每次查詢都建立新連線（建立連線很昂貴）
    - 自動管理連線的復用和回收
    - 限制最大同時連線數，避免資料庫過載
    
    使用方式：
        db = DatabaseService()
        await db.init()          # 建立連線池 + 建表
        rows = await db.fetch("SELECT * FROM table WHERE id = $1", 123)
        await db.close()         # 關閉連線池
    """
    
    def __init__(self):
        """
        初始化資料庫服務
        
        _pool 是 asyncpg 的連線池，延遲初始化（在 init() 中建立）
        """
        self._pool: Optional[asyncpg.Pool] = None
    
    async def init(self):
        """
        初始化資料庫連線池並建立資料表
        
        asyncpg.create_pool: 建立連線池
        - dsn: 資料庫連線字串（PostgreSQL URI 格式）
        - min_size: 連線池最小連線數（預設 2）
        - max_size: 連線池最大連線數（預設 10）
        
        建立後立刻執行 SCHEMA_SQL 確保資料表存在
        使用 IF NOT EXISTS 確保冪等性（重複執行不會出錯）
        """
        try:
            self._pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=2,
                max_size=10
            )
            
            # 執行 schema migration（建立資料表）
            async with self._pool.acquire() as conn:
                await conn.execute(SCHEMA_SQL)
            
            print("✅ PostgreSQL 連線池已建立，資料表已就緒")
            
        except Exception as e:
            print(f"⚠️ PostgreSQL 初始化失敗: {e}")
            print("   投影功能將在沒有持久化儲存的情況下運行（僅使用 Redis）")
            self._pool = None
    
    async def close(self):
        """
        關閉資料庫連線池
        
        在應用程式結束時呼叫，釋放所有資料庫連線
        """
        if self._pool:
            await self._pool.close()
            self._pool = None
            print("✅ PostgreSQL 連線池已關閉")
    
    @property
    def is_connected(self) -> bool:
        """檢查連線池是否已建立且可用"""
        return self._pool is not None
    
    async def execute(self, query: str, *args) -> str:
        """
        執行不返回結果的 SQL（INSERT, UPDATE, DELETE）
        
        Args:
            query: SQL 查詢字串，使用 $1, $2 等作為參數佔位符
            *args: 查詢參數，按順序對應 $1, $2 等
        
        Returns:
            執行結果狀態字串（如 "INSERT 0 1"）
        
        Example:
            await db.execute(
                "INSERT INTO logs (date, status) VALUES ($1, $2)",
                "2026-02-08", "success"
            )
        """
        if not self._pool:
            raise RuntimeError("資料庫未初始化，請先呼叫 init()")
        
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query: str, *args) -> List[dict]:
        """
        執行查詢並返回多筆結果
        
        asyncpg 返回 Record 物件，這裡轉換為 dict 方便使用
        
        Args:
            query: SQL 查詢字串
            *args: 查詢參數
        
        Returns:
            查詢結果列表（每筆是 dict）
        
        Example:
            rows = await db.fetch(
                "SELECT * FROM player_projections WHERE date = $1",
                datetime.date(2026, 2, 8)
            )
        """
        if not self._pool:
            raise RuntimeError("資料庫未初始化，請先呼叫 init()")
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def fetchrow(self, query: str, *args) -> Optional[dict]:
        """
        執行查詢並返回單筆結果
        
        Args:
            query: SQL 查詢字串
            *args: 查詢參數
        
        Returns:
            單筆結果（dict），或 None（無結果時）
        
        Example:
            row = await db.fetchrow(
                "SELECT * FROM player_projections WHERE date = $1 AND player_name = $2",
                datetime.date(2026, 2, 8), "Stephen Curry"
            )
        """
        if not self._pool:
            raise RuntimeError("資料庫未初始化，請先呼叫 init()")
        
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    async def executemany(self, query: str, args_list: List[tuple]) -> None:
        """
        批量執行 SQL（用於批量 INSERT/UPDATE）
        
        executemany 比逐筆 execute 高效許多，
        因為只需要一次 prepare + 多次 bind/execute
        
        Args:
            query: SQL 查詢字串
            args_list: 參數列表，每個元素是一組參數 tuple
        
        Example:
            await db.executemany(
                "INSERT INTO table (col1, col2) VALUES ($1, $2)",
                [("a", 1), ("b", 2), ("c", 3)]
            )
        """
        if not self._pool:
            raise RuntimeError("資料庫未初始化，請先呼叫 init()")
        
        async with self._pool.acquire() as conn:
            await conn.executemany(query, args_list)


# 建立全域資料庫服務實例
db_service = DatabaseService()
