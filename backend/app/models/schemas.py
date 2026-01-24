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
    opponent_filter: Optional[str] = Field(default=None, description="當前篩選的對手")
    message: Optional[str] = Field(default=None, description="額外訊息")

