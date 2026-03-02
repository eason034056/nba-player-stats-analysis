"""
schemas.py - Pydantic 資料模型定義

定義所有 API 請求與回應的資料結構
- BaseModel: pydantic 的基底模型類別，提供資料驗證功能
- Field: 用於定義欄位的額外資訊（描述、預設值等）
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# ==================== 健康檢查 ====================

class HealthResponse(BaseModel):
    """
    健康檢查 API 回應模型
    用於 GET /api/health 端點
    """
    ok: bool = Field(..., description="服務是否正常運作")
    service: str = Field(..., description="服務名稱")
    time: datetime = Field(..., description="伺服器目前時間（UTC）")


# ==================== NBA 賽事 ====================

class NBAEvent(BaseModel):
    """
    單場 NBA 賽事資訊
    
    - event_id: 賽事唯一識別碼，用於後續查詢 props
    - sport_key: 運動類型識別碼，NBA 為 "basketball_nba"
    - home_team: 主場球隊名稱
    - away_team: 客場球隊名稱
    - commence_time: 比賽開始時間（UTC ISO 8601 格式）
    """
    event_id: str = Field(..., description="賽事 ID")
    sport_key: str = Field(..., description="運動類型 key")
    home_team: str = Field(..., description="主場球隊")
    away_team: str = Field(..., description="客場球隊")
    commence_time: datetime = Field(..., description="比賽開始時間（UTC）")


class EventsResponse(BaseModel):
    """
    賽事列表 API 回應模型
    用於 GET /api/nba/events 端點
    """
    date: str = Field(..., description="查詢日期 YYYY-MM-DD")
    events: List[NBAEvent] = Field(default_factory=list, description="賽事列表")


# ==================== Props 計算 ====================

class NoVigRequest(BaseModel):
    """
    去水機率計算 API 請求模型
    用於 POST /api/nba/props/no-vig 端點
    
    - event_id: 要查詢的賽事 ID
    - player_name: 球員名稱（會進行模糊匹配）
    - market: 投注市場類型，預設為 "player_points"（球員得分）
    - regions: 地區代碼，影響可用的博彩公司
    - bookmakers: 要查詢的博彩公司列表，空列表表示全部
    - odds_format: 賠率格式，"american"（美式）或 "decimal"（小數）
    """
    event_id: str = Field(..., description="賽事 ID")
    player_name: str = Field(..., description="球員名稱")
    market: str = Field(default="player_points", description="投注市場類型")
    regions: str = Field(default="us", description="地區")
    bookmakers: Optional[List[str]] = Field(default=None, description="博彩公司列表，None 表示全部")
    odds_format: str = Field(default="american", description="賠率格式")


class BookmakerResult(BaseModel):
    """
    單一博彩公司的計算結果
    
    - bookmaker: 博彩公司名稱
    - line: 門檻值（例如 28.5 分）
    - over_odds / under_odds: 原始賠率（美式）
    - p_over_imp / p_under_imp: 隱含機率（含水）
    - vig: 水錢比例（博彩公司利潤）
    - p_over_fair / p_under_fair: 去水後的公平機率
    - fetched_at: 資料取得時間
    """
    bookmaker: str = Field(..., description="博彩公司名稱")
    line: float = Field(..., description="門檻值")
    over_odds: float = Field(..., description="Over 賠率")
    under_odds: float = Field(..., description="Under 賠率")
    p_over_imp: float = Field(..., description="Over 隱含機率")
    p_under_imp: float = Field(..., description="Under 隱含機率")
    vig: float = Field(..., description="水錢（vig）")
    p_over_fair: float = Field(..., description="Over 去水機率")
    p_under_fair: float = Field(..., description="Under 去水機率")
    fetched_at: datetime = Field(..., description="資料取得時間")


class Consensus(BaseModel):
    """
    市場共識計算結果
    
    將多家博彩公司的去水機率取平均，得出市場共識
    - method: 計算方法（"mean" 平均 或 "weighted" 加權）
    - p_over_fair / p_under_fair: 共識機率
    """
    method: str = Field(..., description="計算方法")
    p_over_fair: float = Field(..., description="共識 Over 機率")
    p_under_fair: float = Field(..., description="共識 Under 機率")


class NoVigResponse(BaseModel):
    """
    去水機率計算 API 回應模型
    """
    event_id: str = Field(..., description="賽事 ID")
    player_name: str = Field(..., description="球員名稱")
    market: str = Field(..., description="投注市場類型")
    results: List[BookmakerResult] = Field(default_factory=list, description="各博彩公司結果")
    consensus: Optional[Consensus] = Field(default=None, description="市場共識")
    message: Optional[str] = Field(default=None, description="額外訊息（如找不到球員）")


# ==================== 球員建議 ====================

class PlayerSuggestResponse(BaseModel):
    """
    球員名稱建議 API 回應模型
    用於前端 autocomplete 功能
    """
    players: List[str] = Field(default_factory=list, description="球員名稱列表")


# ==================== 錯誤回應 ====================

class ErrorResponse(BaseModel):
    """
    錯誤回應模型
    統一的錯誤回應格式
    """
    error: str = Field(..., description="錯誤類型")
    message: str = Field(..., description="錯誤訊息")
    detail: Optional[str] = Field(default=None, description="詳細資訊")


# ==================== CSV 球員歷史數據 ====================

class CSVPlayersResponse(BaseModel):
    """
    CSV 球員列表 API 回應模型
    用於 GET /api/nba/csv/players 端點
    
    返回從 CSV 檔案中讀取的所有球員名單
    """
    players: List[str] = Field(default_factory=list, description="球員名稱列表")
    total: int = Field(..., description="球員總數")


class HistogramBin(BaseModel):
    """
    直方圖單一區間（bin）資料
    
    - binStart: 區間起始值
    - binEnd: 區間結束值
    - count: 該區間內的資料點數量
    """
    binStart: float = Field(..., description="區間起始值")
    binEnd: float = Field(..., description="區間結束值")
    count: int = Field(..., description="該區間的數量")


class GameLog(BaseModel):
    """
    單場比賽記錄
    
    用於時間序列圖表，顯示每場比賽的詳細資料
    """
    date: str = Field(..., description="比賽日期（MM/DD 格式）")
    date_full: str = Field(..., description="完整日期（YYYY-MM-DD 格式）")
    opponent: str = Field(..., description="對手球隊")
    value: float = Field(..., description="該指標的數值")
    is_over: bool = Field(..., description="是否超過閾值")
    team: str = Field(default="", description="球員所屬球隊")
    minutes: float = Field(default=0.0, description="上場時間（分鐘）")
    is_starter: bool = Field(default=False, description="是否先發")


class PlayerHistoryResponse(BaseModel):
    """
    球員歷史數據統計 API 回應模型
    用於 GET /api/nba/player-history 端點
    
    計算球員在指定指標（如得分）上的歷史經驗機率
    這是「經驗機率」（empirical probability），不是模型預測
    
    - player: 球員名稱
    - metric: 統計指標（points/assists/rebounds/pra）
    - threshold: 用戶設定的閾值（例如 24.5）
    - n_games: 樣本場次數
    - p_over: Over 機率（value > threshold 的比例）
    - p_under: Under 機率（value < threshold 的比例）
    - mean: 該指標的平均值
    - std: 該指標的標準差
    - histogram: 直方圖資料（用於視覺化，保留兼容性）
    - game_logs: 每場比賽詳細資料（用於時間序列圖表）
    - opponents: 對手列表（用於篩選器）
    """
    player: str = Field(..., description="球員名稱")
    metric: str = Field(..., description="統計指標")
    threshold: float = Field(..., description="閾值")
    n_games: int = Field(..., description="樣本場次")
    p_over: Optional[float] = Field(default=None, description="Over 機率")
    p_under: Optional[float] = Field(default=None, description="Under 機率")
    equal_count: Optional[int] = Field(default=0, description="等於閾值的場次數")
    mean: Optional[float] = Field(default=None, description="平均值")
    std: Optional[float] = Field(default=None, description="標準差")
    histogram: List[HistogramBin] = Field(default_factory=list, description="直方圖資料")
    game_logs: List[GameLog] = Field(default_factory=list, description="每場比賽詳細資料")
    opponents: List[str] = Field(default_factory=list, description="對手列表")
    teammates: List[str] = Field(default_factory=list, description="隊友列表（用於星級隊友選擇器）")
    opponent_filter: Optional[str] = Field(default=None, description="當前篩選的對手")
    teammate_filter: Optional[List[str]] = Field(default=None, description="當前篩選的星級隊友")
    teammate_played: Optional[bool] = Field(default=None, description="星級隊友出賽篩選")
    message: Optional[str] = Field(default=None, description="額外訊息")


# ==================== 球員投影資料 ====================

class PlayerProjection(BaseModel):
    """
    單一球員的投影資料
    
    對應 SportsDataIO Projected Player Game Stats API 的資料。
    這是「預測值」，不是實際比賽結果。
    
    欄位分類：
    - 基本資訊：球員名稱、球隊、位置
    - 核心投影：預計得分、籃板、助攻等（Free Trial 可用）
    - 對位難度：對手防守排名
    - 先發/傷病：先發狀態、傷病資訊（Free Trial 會被 scrambled）
    - DFS 相關：DraftKings / FanDuel 薪資和 Fantasy 分數
    """
    # 基本資訊
    player_id: Optional[int] = Field(default=None, description="SportsDataIO 球員 ID")
    player_name: str = Field(..., description="球員姓名")
    team: Optional[str] = Field(default=None, description="球隊縮寫（如 GS, LAL）")
    position: Optional[str] = Field(default=None, description="場上位置（PG/SG/SF/PF/C）")
    opponent: Optional[str] = Field(default=None, description="對手球隊縮寫")
    home_or_away: Optional[str] = Field(default=None, description="HOME 或 AWAY")
    
    # 核心投影數據（Free Trial 可用）
    minutes: Optional[float] = Field(default=None, description="預計上場分鐘數")
    points: Optional[float] = Field(default=None, description="預計得分")
    rebounds: Optional[float] = Field(default=None, description="預計籃板")
    assists: Optional[float] = Field(default=None, description="預計助攻")
    steals: Optional[float] = Field(default=None, description="預計抄截")
    blocked_shots: Optional[float] = Field(default=None, description="預計阻攻")
    turnovers: Optional[float] = Field(default=None, description="預計失誤")
    pra: Optional[float] = Field(default=None, description="預計 PRA（Points + Rebounds + Assists）")
    
    # 投籃數據
    field_goals_made: Optional[float] = Field(default=None, description="投籃命中數")
    field_goals_attempted: Optional[float] = Field(default=None, description="投籃出手數")
    three_pointers_made: Optional[float] = Field(default=None, description="三分命中數")
    three_pointers_attempted: Optional[float] = Field(default=None, description="三分出手數")
    free_throws_made: Optional[float] = Field(default=None, description="罰球命中數")
    free_throws_attempted: Optional[float] = Field(default=None, description="罰球出手數")
    
    # 先發與傷病（Free Trial 會 scrambled，顯示為 None）
    started: Optional[int] = Field(default=None, description="是否先發（1=Yes, 0=No）")
    lineup_confirmed: Optional[bool] = Field(default=None, description="先發是否已確認")
    injury_status: Optional[str] = Field(default=None, description="傷病狀態（Free Trial 為 None）")
    injury_body_part: Optional[str] = Field(default=None, description="傷病部位")
    
    # 對位難度
    opponent_rank: Optional[int] = Field(default=None, description="對手整體防守排名（1-30）")
    opponent_position_rank: Optional[int] = Field(default=None, description="對手對該位置防守排名")
    
    # DFS 相關
    draftkings_salary: Optional[float] = Field(default=None, description="DraftKings DFS 薪資")
    fanduel_salary: Optional[float] = Field(default=None, description="FanDuel DFS 薪資")
    fantasy_points_dk: Optional[float] = Field(default=None, description="DraftKings Fantasy 分數")
    fantasy_points_fd: Optional[float] = Field(default=None, description="FanDuel Fantasy 分數")
    
    # 進階指標
    usage_rate_percentage: Optional[float] = Field(default=None, description="球權使用率 %")
    player_efficiency_rating: Optional[float] = Field(default=None, description="球員效率值（PER）")


class ProjectionsResponse(BaseModel):
    """
    投影資料 API 回應模型
    
    用於 GET /api/nba/projections 端點
    返回指定日期所有球員的投影資料
    """
    date: str = Field(..., description="查詢日期（YYYY-MM-DD）")
    player_count: int = Field(..., description="球員數量")
    fetched_at: Optional[str] = Field(default=None, description="資料抓取時間")
    projections: List[PlayerProjection] = Field(default_factory=list, description="球員投影列表")


class ProjectionRefreshResponse(BaseModel):
    """
    投影資料刷新 API 回應模型
    
    用於 POST /api/nba/projections/refresh 端點
    """
    date: str = Field(..., description="刷新日期")
    player_count: int = Field(..., description="取得的球員數量")
    message: str = Field(..., description="操作結果訊息")


# ==================== 每日高機率球員分析 ====================

class DailyPick(BaseModel):
    """
    單一高機率球員選擇
    
    當某球員在某 metric 上的歷史機率 > 65% 時，會被加入精選名單
    
    欄位說明：
    - player_name: 球員名稱（例如 "Stephen Curry"）
    - player_team: 球員所屬球隊（簡短名稱，如 "Lakers", "Warriors"）
    - event_id: 賽事 ID，用於連結到詳細頁面
    - home_team / away_team: 主客場球隊
    - commence_time: 比賽開始時間（ISO 8601 格式）
    - metric: 統計指標（points/assists/rebounds/pra）
    - threshold: 眾數門檻（所有博彩公司 line 的眾數）
    - direction: "over" 或 "under"，表示機率較高的方向
    - probability: 歷史機率（>= 0.65）
    - n_games: 用於計算的歷史場次數
    - bookmakers_count: 提供此 line 的博彩公司數量
    - all_lines: 所有博彩公司的 line 列表（用於顯示分佈）
    """
    player_name: str = Field(..., description="球員名稱")
    player_team: str = Field(default="", description="球員所屬球隊（簡短名稱）")
    event_id: str = Field(..., description="賽事 ID")
    home_team: str = Field(..., description="主場球隊")
    away_team: str = Field(..., description="客場球隊")
    commence_time: str = Field(..., description="比賽開始時間")
    metric: str = Field(..., description="統計指標 (points/assists/rebounds/pra)")
    threshold: float = Field(..., description="眾數門檻")
    direction: str = Field(..., description="方向 (over/under)")
    probability: float = Field(..., description="歷史機率")
    n_games: int = Field(..., description="樣本場次數")
    bookmakers_count: int = Field(..., description="博彩公司數量")
    all_lines: List[float] = Field(default_factory=list, description="所有博彩公司的 line")
    
    # === 投影資料欄位（來自 SportsDataIO Projection API）===
    has_projection: bool = Field(default=False, description="是否有投影資料")
    projected_value: Optional[float] = Field(
        default=None, 
        description="投影值（如 projected points = 29.3）"
    )
    projected_minutes: Optional[float] = Field(
        default=None, 
        description="預計上場分鐘數"
    )
    edge: Optional[float] = Field(
        default=None, 
        description="投影值與盤口的差距（projected_value - threshold），正數 = 有利 Over"
    )
    opponent_rank: Optional[int] = Field(
        default=None, 
        description="對手整體防守排名（1-30，1=最弱防守）"
    )
    opponent_position_rank: Optional[int] = Field(
        default=None, 
        description="對手對該位置防守排名（1-30）"
    )
    injury_status: Optional[str] = Field(
        default=None, 
        description="傷病狀態（Free Trial 為 None）"
    )
    lineup_confirmed: Optional[bool] = Field(
        default=None, 
        description="先發是否已確認"
    )


class AnalysisStats(BaseModel):
    """
    分析統計資訊
    
    提供整體分析的摘要統計
    """
    total_events: int = Field(..., description="分析的賽事總數")
    total_players: int = Field(..., description="分析的球員總數")
    total_props: int = Field(..., description="分析的 prop 總數")
    high_prob_count: int = Field(..., description="高機率選擇數量")
    analysis_duration_seconds: float = Field(..., description="分析耗時（秒）")


class DailyPicksResponse(BaseModel):
    """
    每日高機率球員 API 回應模型
    用於 GET /api/nba/daily-picks 端點
    
    返回當日所有發生機率 > 65% 的球員投注選擇
    """
    date: str = Field(..., description="分析日期 YYYY-MM-DD")
    analyzed_at: str = Field(..., description="分析執行時間（ISO 8601）")
    total_picks: int = Field(..., description="符合條件的選擇總數")
    picks: List[DailyPick] = Field(default_factory=list, description="高機率球員列表")
    stats: Optional[AnalysisStats] = Field(default=None, description="分析統計")
    message: Optional[str] = Field(default=None, description="額外訊息")


# ==================== 盤口快照（Line Movement Tracking）====================

class OddsLineSnapshot(BaseModel):
    """
    單筆盤口快照資料

    代表某一時刻、某一博彩公司、某一球員、某一 market 的 no-vig 計算結果。
    一次快照 run 會產生多筆 OddsLineSnapshot。

    欄位說明：
    - bookmaker: 博彩公司 key（如 "draftkings"）
    - line: 盤口門檻值（如 24.5），這是「會移動」的核心數據
    - over_odds / under_odds: 原始美式賠率（如 -110）
    - vig: 水錢比例（如 0.0476 = 4.76%）
    - over_fair_prob / under_fair_prob: 去水後的公平機率
    """
    bookmaker: str = Field(..., description="博彩公司 key")
    line: Optional[float] = Field(default=None, description="盤口門檻值")
    over_odds: Optional[int] = Field(default=None, description="Over 美式賠率")
    under_odds: Optional[int] = Field(default=None, description="Under 美式賠率")
    vig: Optional[float] = Field(default=None, description="水錢比例")
    over_fair_prob: Optional[float] = Field(default=None, description="Over 去水機率")
    under_fair_prob: Optional[float] = Field(default=None, description="Under 去水機率")


class OddsConsensus(BaseModel):
    """
    盤口共識（Consensus）

    多家博彩公司去水機率的平均值，代表市場共識。
    在 API 回應中，consensus 是從 odds_line_snapshots 表
    按 (snapshot_at, player_name, market) 分組後
    用 SQL AVG() 即時計算而來，不另外儲存。
    """
    over_fair_prob: float = Field(..., description="共識 Over 去水機率")
    under_fair_prob: float = Field(..., description="共識 Under 去水機率")
    avg_line: Optional[float] = Field(default=None, description="平均盤口線")
    bookmaker_count: int = Field(default=0, description="博彩公司數量")


class OddsSnapshotGroup(BaseModel):
    """
    一次快照的分組資料

    代表某一時刻的所有博彩公司盤口資料。
    例如 UTC 16:00 的快照，包含 DraftKings、FanDuel 等各家的 line + no-vig。
    用於 line movement 視覺化：每個 group 是時間軸上的一個資料點。

    欄位說明：
    - snapshot_at: 快照時間（ISO 8601 格式）
    - lines: 各博彩公司的 no-vig 計算結果列表
    - consensus: 所有博彩公司的去水機率平均值
    """
    snapshot_at: str = Field(..., description="快照時間（ISO 8601）")
    lines: List[OddsLineSnapshot] = Field(
        default_factory=list, description="各博彩公司的盤口資料"
    )
    consensus: Optional[OddsConsensus] = Field(
        default=None, description="市場共識（去水機率平均）"
    )


class OddsHistoryResponse(BaseModel):
    """
    盤口歷史 API 回應模型

    用於 GET /api/nba/odds-history 端點。
    回傳某球員某 market 在指定日期的所有快照，
    每個快照包含各博彩公司的 no-vig 結果和市場共識。

    使用場景：前端 Line Movement Chart 的資料來源。
    """
    date: str = Field(..., description="比賽日期 YYYY-MM-DD")
    player_name: str = Field(..., description="球員名稱")
    market: str = Field(..., description="市場類型")
    snapshot_count: int = Field(default=0, description="快照數量")
    snapshots: List[OddsSnapshotGroup] = Field(
        default_factory=list, description="快照列表（按時間排序）"
    )


class OddsSnapshotTriggerResponse(BaseModel):
    """
    手動觸發盤口快照的回應模型

    用於 POST /api/nba/odds-history/snapshot 端點。
    回傳快照執行結果的摘要。
    """
    date: str = Field(..., description="快照日期")
    event_count: int = Field(default=0, description="處理的賽事數")
    total_lines: int = Field(default=0, description="寫入的 odds line 總筆數")
    duration_ms: int = Field(default=0, description="耗時（毫秒）")
    message: str = Field(default="", description="操作結果訊息")

