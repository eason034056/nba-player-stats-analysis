"""
projection_service.py - 投影資料混合取得 + 儲存服務（方案 C + D）

這是整個投影功能的核心模組，負責：
1. 統一的投影資料取得入口（get_projections）
2. 混合取得策略（Hybrid Fetch）：
   - Redis 命中 + 新鮮 → 直接返回
   - Redis 命中 + 過期 → 返回舊資料 + 背景刷新
   - Redis 未命中 → 同步取得 + 快取
3. 雙重儲存：Redis（快速讀取）+ PostgreSQL（持久化歷史）
4. 提供歷史投影查詢（未來回測用）

策略說明：
    SportsDataIO 的 Projection API 是 bulk endpoint，
    一次 call 返回該日期所有球員的投影。
    這意味著：
    - 排程預取（每天 3 次）是最高效的方式
    - On-demand 呼叫只在 cache miss 時作為 fallback
    - 背景刷新用於資料過期但用戶不需要等待的場景

依賴：
    - projection_provider: SportsDataIO API 客戶端
    - cache_service: Redis 快取
    - db_service: PostgreSQL 資料庫

使用方式：
    from app.services.projection_service import projection_service
    
    # 取得今日所有球員投影（自動處理快取邏輯）
    projections = await projection_service.get_projections("2026-02-08")
    # projections = {"Stephen Curry": {...}, "LeBron James": {...}, ...}
    
    # 強制刷新（由排程器呼叫）
    projections = await projection_service.fetch_and_store("2026-02-08")
"""

import asyncio
import json
import time
from datetime import datetime, timezone, date as date_type
from typing import Dict, Any, Optional, List

from app.services.projection_provider import (
    projection_provider,
    SportsDataProjectionError,
)
from app.services.cache import cache_service
from app.services.db import db_service
from app.settings import settings


# ==================== Redis Key 設計 ====================

def _build_projections_key(date: str) -> str:
    """
    建構投影資料的 Redis 快取 key
    
    格式：projections:nba:{date}
    例如：projections:nba:2026-02-08
    
    存的是一個 dict，key 為 player_name，value 為投影資料
    """
    return f"projections:nba:{date}"


def _build_projections_meta_key(date: str) -> str:
    """
    建構投影資料中繼資訊的 Redis 快取 key
    
    格式：projections:nba:{date}:meta
    
    存的是一個 dict：
    {
        "fetched_at": "2026-02-08T22:00:00Z",  # 抓取時間
        "player_count": 250                       # 球員數量
    }
    
    用於判斷資料是否過期（stale check）
    """
    return f"projections:nba:{date}:meta"


# ==================== PostgreSQL UPSERT SQL ====================

# ON CONFLICT ... DO UPDATE：如果已存在相同 (date, player_name, game_id) 的紀錄，
# 就更新它而不是插入新的。這確保排程器多次呼叫不會產生重複資料。
UPSERT_PROJECTION_SQL = """
INSERT INTO player_projections (
    date, player_id, player_name, team, position,
    opponent, home_or_away, game_id,
    minutes, points, rebounds, assists, steals, blocked_shots, turnovers,
    field_goals_made, field_goals_attempted,
    three_pointers_made, three_pointers_attempted,
    free_throws_made, free_throws_attempted,
    started, lineup_confirmed, injury_status, injury_body_part,
    opponent_rank, opponent_position_rank,
    draftkings_salary, fanduel_salary,
    fantasy_points_dk, fantasy_points_fd,
    usage_rate_percentage, player_efficiency_rating,
    fetched_at, api_updated_at
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8,
    $9, $10, $11, $12, $13, $14, $15,
    $16, $17,
    $18, $19,
    $20, $21,
    $22, $23, $24, $25,
    $26, $27,
    $28, $29,
    $30, $31,
    $32, $33,
    $34, $35
)
ON CONFLICT (date, player_name, game_id)
DO UPDATE SET
    team = EXCLUDED.team,
    position = EXCLUDED.position,
    opponent = EXCLUDED.opponent,
    home_or_away = EXCLUDED.home_or_away,
    minutes = EXCLUDED.minutes,
    points = EXCLUDED.points,
    rebounds = EXCLUDED.rebounds,
    assists = EXCLUDED.assists,
    steals = EXCLUDED.steals,
    blocked_shots = EXCLUDED.blocked_shots,
    turnovers = EXCLUDED.turnovers,
    field_goals_made = EXCLUDED.field_goals_made,
    field_goals_attempted = EXCLUDED.field_goals_attempted,
    three_pointers_made = EXCLUDED.three_pointers_made,
    three_pointers_attempted = EXCLUDED.three_pointers_attempted,
    free_throws_made = EXCLUDED.free_throws_made,
    free_throws_attempted = EXCLUDED.free_throws_attempted,
    started = EXCLUDED.started,
    lineup_confirmed = EXCLUDED.lineup_confirmed,
    injury_status = EXCLUDED.injury_status,
    injury_body_part = EXCLUDED.injury_body_part,
    opponent_rank = EXCLUDED.opponent_rank,
    opponent_position_rank = EXCLUDED.opponent_position_rank,
    draftkings_salary = EXCLUDED.draftkings_salary,
    fanduel_salary = EXCLUDED.fanduel_salary,
    fantasy_points_dk = EXCLUDED.fantasy_points_dk,
    fantasy_points_fd = EXCLUDED.fantasy_points_fd,
    usage_rate_percentage = EXCLUDED.usage_rate_percentage,
    player_efficiency_rating = EXCLUDED.player_efficiency_rating,
    fetched_at = EXCLUDED.fetched_at,
    api_updated_at = EXCLUDED.api_updated_at
"""

# 插入抓取日誌
INSERT_FETCH_LOG_SQL = """
INSERT INTO projection_fetch_logs (date, fetched_at, player_count, status, error_message, duration_ms)
VALUES ($1, $2, $3, $4, $5, $6)
"""


class ProjectionService:
    """
    投影資料混合取得 + 儲存服務
    
    實作三條讀取路徑：
    1. Redis 命中 + 新鮮（< max_stale_minutes）→ 直接返回
    2. Redis 命中 + 過期（> max_stale_minutes）→ 返回舊資料 + 背景非同步刷新
    3. Redis 未命中 → 同步呼叫 API + 存入 Redis 和 PostgreSQL + 返回
    
    寫入路徑：
    - 每次從 API 取得資料後，同時寫入 Redis 和 PostgreSQL
    - Redis: 快速讀取，有 TTL（預設 2 小時）
    - PostgreSQL: 持久化儲存，用於歷史回測
    """
    
    def __init__(self, max_stale_minutes: int = 120):
        """
        初始化服務
        
        Args:
            max_stale_minutes: 資料過期閾值（分鐘）
                超過此時間的快取資料會觸發背景刷新
                預設 120 分鐘（2 小時），與 Redis TTL 一致
        """
        self.max_stale_minutes = max_stale_minutes
        self._refresh_locks: Dict[str, bool] = {}  # 防止同一日期重複刷新
    
    async def get_projections(self, date: str) -> Dict[str, Dict[str, Any]]:
        """
        統一的投影資料取得入口
        
        這是最常被呼叫的方法，daily_analysis 和 API endpoint 都用它。
        返回一個 dict，key 是球員名稱，value 是投影資料，
        方便用 player_name 快速查找。
        
        混合策略流程：
        1. 查 Redis → 有資料 → 檢查新鮮度
           - 新鮮 → 直接返回
           - 過期 → 返回舊資料 + 背景刷新
        2. 查 Redis → 無資料 → 同步呼叫 API → 存入雙層儲存 → 返回
        3. API 也失敗 → 嘗試從 PostgreSQL 回讀 → 還是沒有 → 返回空 dict
        
        Args:
            date: 比賽日期（YYYY-MM-DD）
        
        Returns:
            Dict[player_name, projection_dict]
            例如: {"Stephen Curry": {"points": 29.3, "minutes": 34.5, ...}}
        """
        cache_key = _build_projections_key(date)
        meta_key = _build_projections_meta_key(date)
        
        # 1. 嘗試從 Redis 讀取
        cached_data = await cache_service.get(cache_key)
        cached_meta = await cache_service.get(meta_key)
        
        if cached_data and isinstance(cached_data, dict):
            # Cache hit! 檢查新鮮度
            if cached_meta and self._is_stale(cached_meta):
                # 資料過期 → 返回舊資料，同時背景刷新
                self._trigger_background_refresh(date)
                print(f"📦 投影資料 cache hit (stale, 背景刷新中): {date}")
            else:
                print(f"📦 投影資料 cache hit (fresh): {date}")
            
            return cached_data
        
        # 2. Cache miss → 同步取得
        print(f"📭 投影資料 cache miss: {date}，同步取得中...")
        try:
            return await self.fetch_and_store(date)
        except SportsDataProjectionError as e:
            print(f"⚠️ SportsDataIO API 呼叫失敗: {e}")
            
            # 3. Fallback: 嘗試從 PostgreSQL 讀取
            pg_data = await self._read_from_postgres(date)
            if pg_data:
                print(f"📀 從 PostgreSQL 回讀投影資料: {date} ({len(pg_data)} 筆)")
                # 回填 Redis
                await self._write_to_redis(date, pg_data)
                return pg_data
            
            print(f"❌ 無法取得投影資料: {date}")
            return {}
        except Exception as e:
            print(f"❌ 取得投影資料時發生未預期錯誤: {e}")
            return {}
    
    async def get_player_projection(
        self, date: str, player_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        取得單一球員的投影資料
        
        內部呼叫 get_projections() 取得所有球員資料後，
        用 player_name 做 key lookup（O(1)）
        
        Args:
            date: 比賽日期（YYYY-MM-DD）
            player_name: 球員名稱
        
        Returns:
            投影資料 dict，或 None（找不到）
        """
        projections = await self.get_projections(date)
        return projections.get(player_name)
    
    async def fetch_and_store(self, date: str) -> Dict[str, Dict[str, Any]]:
        """
        強制從 API 取得投影資料並存入雙層儲存
        
        這個方法用於：
        1. 排程器的定時預取
        2. cache miss 的同步 fallback
        3. 手動觸發刷新
        
        流程：
        1. 呼叫 SportsDataIO API
        2. 將列表轉為 dict（以 player_name 為 key）
        3. 寫入 Redis（快取）
        4. 寫入 PostgreSQL（持久化）
        5. 記錄抓取日誌
        
        Args:
            date: 比賽日期（YYYY-MM-DD）
        
        Returns:
            Dict[player_name, projection_dict]
        
        Raises:
            SportsDataProjectionError: API 呼叫失敗
        """
        start_time = time.time()
        error_message = None
        status = "success"
        player_count = 0
        
        try:
            # 1. 呼叫 API
            raw_projections = await projection_provider.fetch_projections_by_date(date)
            player_count = len(raw_projections)
            
            # 2. 轉為 dict（以 player_name 為 key）
            # 如果同一球員有多筆（不同比賽），使用最後一筆
            projections_dict: Dict[str, Dict[str, Any]] = {}
            for proj in raw_projections:
                name = proj.get("player_name")
                if name:
                    projections_dict[name] = proj
            
            # 3. 寫入 Redis
            await self._write_to_redis(date, projections_dict)
            
            # 4. 寫入 PostgreSQL（非阻塞，失敗不影響主流程）
            try:
                await self._write_to_postgres(date, raw_projections)
            except Exception as e:
                print(f"⚠️ 寫入 PostgreSQL 失敗（不影響主流程）: {e}")
            
            print(f"✅ 投影資料已取得並儲存: {date} ({player_count} 球員)")
            return projections_dict
        
        except SportsDataProjectionError as e:
            status = "error"
            error_message = str(e)
            raise
        
        except Exception as e:
            status = "error"
            error_message = str(e)
            raise SportsDataProjectionError(0, f"未預期錯誤: {e}")
        
        finally:
            # 5. 記錄抓取日誌（無論成功或失敗）
            duration_ms = int((time.time() - start_time) * 1000)
            await self._log_fetch(date, player_count, status, error_message, duration_ms)
    
    async def get_historical_projections(
        self, player_name: str, n_days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        從 PostgreSQL 讀取球員的歷史投影資料
        
        用於未來的回測功能：比較投影值 vs 實際表現
        
        Args:
            player_name: 球員名稱
            n_days: 回溯天數（預設 30 天）
        
        Returns:
            歷史投影列表，按日期降序排列
        """
        if not db_service.is_connected:
            return []
        
        try:
            rows = await db_service.fetch(
                """
                SELECT * FROM player_projections
                WHERE player_name = $1
                  AND date >= CURRENT_DATE - $2
                ORDER BY date DESC
                """,
                player_name,
                n_days,
            )
            return rows
        except Exception as e:
            print(f"⚠️ 讀取歷史投影失敗: {e}")
            return []
    
    # ==================== 內部方法 ====================
    
    def _is_stale(self, meta: Dict[str, Any]) -> bool:
        """
        判斷快取資料是否過期
        
        比較 meta 中的 fetched_at 時間與現在的差距，
        如果超過 max_stale_minutes 就判定為過期。
        
        Args:
            meta: 快取中繼資訊 {"fetched_at": "...", "player_count": N}
        
        Returns:
            True 如果資料已過期
        """
        fetched_at_str = meta.get("fetched_at")
        if not fetched_at_str:
            return True
        
        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
            # 確保有時區資訊
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            
            age_minutes = (
                datetime.now(timezone.utc) - fetched_at
            ).total_seconds() / 60
            
            return age_minutes > self.max_stale_minutes
        
        except (ValueError, TypeError):
            return True
    
    def _trigger_background_refresh(self, date: str):
        """
        觸發背景非同步刷新
        
        使用 asyncio.create_task() 在背景執行 API 呼叫，
        不阻塞當前請求。
        
        使用 _refresh_locks 防止同一日期的重複刷新：
        如果已經有一個刷新任務在跑，就不再啟動新的。
        
        Args:
            date: 比賽日期（YYYY-MM-DD）
        """
        # 防止重複刷新
        if self._refresh_locks.get(date):
            return
        
        self._refresh_locks[date] = True
        
        async def _do_refresh():
            try:
                await self.fetch_and_store(date)
                print(f"🔄 背景刷新完成: {date}")
            except Exception as e:
                print(f"⚠️ 背景刷新失敗: {date} - {e}")
            finally:
                self._refresh_locks.pop(date, None)
        
        # 建立背景任務
        asyncio.create_task(_do_refresh())
        print(f"🔄 已觸發背景刷新: {date}")
    
    async def _write_to_redis(
        self, date: str, projections_dict: Dict[str, Dict[str, Any]]
    ):
        """
        將投影資料寫入 Redis
        
        寫入兩個 key：
        1. projections:nba:{date} → 完整投影資料（dict）
        2. projections:nba:{date}:meta → 中繼資訊（fetched_at, player_count）
        
        TTL 使用 settings.cache_ttl_projections（預設 7200 秒 = 2 小時）
        
        Args:
            date: 比賽日期
            projections_dict: 投影資料（以 player_name 為 key）
        """
        cache_key = _build_projections_key(date)
        meta_key = _build_projections_meta_key(date)
        ttl = settings.cache_ttl_projections
        
        # 寫入投影資料
        await cache_service.set(cache_key, projections_dict, ttl=ttl)
        
        # 寫入中繼資訊
        meta = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "player_count": len(projections_dict),
        }
        await cache_service.set(meta_key, meta, ttl=ttl)
    
    async def _write_to_postgres(self, date: str, projections: List[Dict[str, Any]]):
        """
        將投影資料寫入 PostgreSQL
        
        使用 UPSERT（INSERT ... ON CONFLICT DO UPDATE）確保冪等性：
        - 如果該 (date, player_name, game_id) 不存在 → 插入
        - 如果已存在 → 更新所有欄位
        
        Args:
            date: 比賽日期
            projections: 正規化後的投影資料列表
        """
        if not db_service.is_connected:
            return
        
        now = datetime.now(timezone.utc)
        
        # 準備批量 upsert 的參數
        args_list = []
        for proj in projections:
            # 解析日期
            proj_date = proj.get("date")
            if proj_date:
                try:
                    parsed_date = date_type.fromisoformat(proj_date)
                except (ValueError, TypeError):
                    parsed_date = date_type.fromisoformat(date)
            else:
                parsed_date = date_type.fromisoformat(date)
            
            # 解析 API updated_at 時間
            api_updated = proj.get("api_updated_at")
            parsed_api_updated = None
            if api_updated and isinstance(api_updated, str):
                try:
                    parsed_api_updated = datetime.fromisoformat(
                        api_updated.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass
            
            args_list.append((
                parsed_date,                           # $1 date
                proj.get("player_id"),                 # $2 player_id
                proj.get("player_name", ""),            # $3 player_name
                proj.get("team"),                       # $4 team
                proj.get("position"),                   # $5 position
                proj.get("opponent"),                   # $6 opponent
                proj.get("home_or_away"),               # $7 home_or_away
                proj.get("game_id"),                    # $8 game_id
                proj.get("minutes"),                    # $9 minutes
                proj.get("points"),                     # $10 points
                proj.get("rebounds"),                    # $11 rebounds
                proj.get("assists"),                     # $12 assists
                proj.get("steals"),                      # $13 steals
                proj.get("blocked_shots"),               # $14 blocked_shots
                proj.get("turnovers"),                   # $15 turnovers
                proj.get("field_goals_made"),            # $16
                proj.get("field_goals_attempted"),       # $17
                proj.get("three_pointers_made"),         # $18
                proj.get("three_pointers_attempted"),    # $19
                proj.get("free_throws_made"),            # $20
                proj.get("free_throws_attempted"),       # $21
                proj.get("started"),                     # $22
                proj.get("lineup_confirmed"),            # $23
                proj.get("injury_status"),               # $24
                proj.get("injury_body_part"),            # $25
                proj.get("opponent_rank"),               # $26
                proj.get("opponent_position_rank"),      # $27
                proj.get("draftkings_salary"),           # $28
                proj.get("fanduel_salary"),              # $29
                proj.get("fantasy_points_dk"),           # $30
                proj.get("fantasy_points_fd"),           # $31
                proj.get("usage_rate_percentage"),       # $32
                proj.get("player_efficiency_rating"),    # $33
                now,                                     # $34 fetched_at
                parsed_api_updated,                      # $35 api_updated_at
            ))
        
        if args_list:
            try:
                await db_service.executemany(UPSERT_PROJECTION_SQL, args_list)
                print(f"💾 已寫入 PostgreSQL: {len(args_list)} 筆投影資料 ({date})")
            except Exception as e:
                print(f"⚠️ PostgreSQL 批量寫入失敗: {e}")
    
    async def _read_from_postgres(self, date: str) -> Dict[str, Dict[str, Any]]:
        """
        從 PostgreSQL 讀取投影資料（Redis cache miss 的 fallback）
        
        Args:
            date: 比賽日期
        
        Returns:
            Dict[player_name, projection_dict]
        """
        if not db_service.is_connected:
            return {}
        
        try:
            parsed_date = date_type.fromisoformat(date)
            rows = await db_service.fetch(
                "SELECT * FROM player_projections WHERE date = $1",
                parsed_date,
            )
            
            result: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                name = row.get("player_name")
                if name:
                    # 將 asyncpg Record dict 轉為普通 dict
                    # 處理 date/datetime 物件的序列化
                    cleaned = {}
                    for k, v in row.items():
                        if isinstance(v, (datetime, date_type)):
                            cleaned[k] = v.isoformat()
                        else:
                            cleaned[k] = v
                    result[name] = cleaned
            
            return result
        
        except Exception as e:
            print(f"⚠️ PostgreSQL 讀取失敗: {e}")
            return {}
    
    async def _log_fetch(
        self,
        date: str,
        player_count: int,
        status: str,
        error_message: Optional[str],
        duration_ms: int,
    ):
        """
        記錄抓取日誌到 PostgreSQL
        
        Args:
            date: 查詢日期
            player_count: 球員數量
            status: 狀態（success / error）
            error_message: 錯誤訊息
            duration_ms: 耗時（毫秒）
        """
        if not db_service.is_connected:
            return
        
        try:
            parsed_date = date_type.fromisoformat(date)
            await db_service.execute(
                INSERT_FETCH_LOG_SQL,
                parsed_date,
                datetime.now(timezone.utc),
                player_count,
                status,
                error_message,
                duration_ms,
            )
        except Exception as e:
            # 日誌寫入失敗不應該影響主流程
            print(f"⚠️ 抓取日誌寫入失敗: {e}")


# 建立全域服務實例
projection_service = ProjectionService()
