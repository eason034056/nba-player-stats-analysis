"""
projection_provider.py - SportsDataIO 投影資料 API 客戶端

封裝 SportsDataIO 的 Projected Player Game Stats API 呼叫。

API Endpoint:
    GET https://api.sportsdata.io/v3/nba/projections/json/PlayerGameProjectionStatsByDate/{date}

特點：
- 一次呼叫回傳該日期「所有球員」的投影數據（bulk endpoint）
- 每日呼叫 1-3 次即可覆蓋所有需求
- Free Trial 版本的 InjuryStatus / LineupStatus 會被 scrambled

主要功能：
- fetch_projections_by_date(): 呼叫 API 取得投影數據
- normalize_projection(): 將 API 欄位名稱轉為內部格式（snake_case）

依賴：
- httpx: 異步 HTTP 客戶端（已在 requirements.txt 中）
- settings: 讀取 API key 和 base URL

使用方式：
    from app.services.projection_provider import projection_provider
    
    projections = await projection_provider.fetch_projections_by_date("2026-02-08")
    # projections = [{ "player_name": "Stephen Curry", "points": 29.3, ... }, ...]
"""

import asyncio
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from app.settings import settings


class SportsDataProjectionError(Exception):
    """
    SportsDataIO API 呼叫錯誤
    
    用於封裝所有 SportsDataIO API 相關的錯誤，
    讓上層呼叫者可以統一 catch 處理
    
    Attributes:
        status_code: HTTP 狀態碼（0 表示網路錯誤）
        message: 錯誤描述
    """
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"SportsDataIO Error {status_code}: {message}")


# ==================== 欄位名稱映射 ====================

# SportsDataIO API 回傳的欄位名稱（PascalCase）→ 內部使用的欄位名稱（snake_case）
# 只映射我們需要的欄位，忽略不需要的
FIELD_MAPPING: Dict[str, str] = {
    # 基本資訊
    "PlayerID": "player_id",
    "Name": "player_name",
    "Team": "team",
    "Position": "position",
    "GameID": "game_id",
    
    # 對戰資訊
    "Opponent": "opponent",
    "HomeOrAway": "home_or_away",
    "Day": "day",
    "DateTime": "date_time",
    
    # 核心投影數據
    "Minutes": "minutes",
    "Points": "points",
    "Rebounds": "rebounds",
    "OffensiveRebounds": "offensive_rebounds",
    "DefensiveRebounds": "defensive_rebounds",
    "Assists": "assists",
    "Steals": "steals",
    "BlockedShots": "blocked_shots",
    "Turnovers": "turnovers",
    "PersonalFouls": "personal_fouls",
    "PlusMinus": "plus_minus",
    
    # 投籃數據
    "FieldGoalsMade": "field_goals_made",
    "FieldGoalsAttempted": "field_goals_attempted",
    "FieldGoalsPercentage": "field_goals_percentage",
    "TwoPointersMade": "two_pointers_made",
    "TwoPointersAttempted": "two_pointers_attempted",
    "ThreePointersMade": "three_pointers_made",
    "ThreePointersAttempted": "three_pointers_attempted",
    "FreeThrowsMade": "free_throws_made",
    "FreeThrowsAttempted": "free_throws_attempted",
    
    # 先發與傷病
    "Started": "started",
    "LineupConfirmed": "lineup_confirmed",
    "LineupStatus": "lineup_status",
    "InjuryStatus": "injury_status",
    "InjuryBodyPart": "injury_body_part",
    "InjuryStartDate": "injury_start_date",
    "InjuryNotes": "injury_notes",
    
    # 對位難度
    "OpponentRank": "opponent_rank",
    "OpponentPositionRank": "opponent_position_rank",
    
    # DFS 薪資
    "DraftKingsSalary": "draftkings_salary",
    "FanDuelSalary": "fanduel_salary",
    "YahooSalary": "yahoo_salary",
    "FantasyDataSalary": "fantasydata_salary",
    
    # Fantasy 分數
    "FantasyPointsDraftKings": "fantasy_points_dk",
    "FantasyPointsFanDuel": "fantasy_points_fd",
    "FantasyPointsYahoo": "fantasy_points_yahoo",
    "FantasyPoints": "fantasy_points",
    
    # 進階指標
    "UsageRatePercentage": "usage_rate_percentage",
    "PlayerEfficiencyRating": "player_efficiency_rating",
    "TrueShootingPercentage": "true_shooting_percentage",
    "AssistsPercentage": "assists_percentage",
    "StealsPercentage": "steals_percentage",
    "BlocksPercentage": "blocks_percentage",
    
    # 中繼資料
    "Updated": "api_updated_at",
    "IsGameOver": "is_game_over",
    "SeasonType": "season_type",
    "Season": "season",
}


def _is_scrambled(value: Any) -> bool:
    """
    偵測 Free Trial 的 scrambled 欄位
    
    SportsDataIO Free Trial 會將某些欄位（如 InjuryStatus）
    替換成隨機的 scrambled 字串（看起來像亂碼）。
    
    判斷規則：
    - 字串長度 > 20 且包含數字+字母混合 → 可能是 scrambled
    - 常見的有效值（如 "Questionable", "Out", "Probable"）→ 不是 scrambled
    
    Args:
        value: 要檢查的值
    
    Returns:
        True 如果判定為 scrambled
    """
    if not isinstance(value, str):
        return False
    
    # 常見有效值白名單
    valid_values = {
        "questionable", "out", "doubtful", "probable", "day-to-day",
        "scrambled", "active", "inactive",
        "confirmed", "not confirmed",
    }
    if value.lower().strip() in valid_values:
        return False
    
    # Scrambled 值通常是長字串，包含混合字母和數字
    if len(value) > 15:
        has_digit = any(c.isdigit() for c in value)
        has_alpha = any(c.isalpha() for c in value)
        if has_digit and has_alpha:
            return True
    
    return False


class SportsDataProjectionProvider:
    """
    SportsDataIO 投影資料 API 客戶端
    
    負責呼叫 SportsDataIO 的 Projected Player Game Stats API，
    並將回傳的 PascalCase 欄位名稱正規化為 snake_case。
    
    特點：
    - 使用 httpx 異步 HTTP 客戶端
    - 內建重試邏輯（max_retries=2，指數退避）
    - 自動偵測並處理 Free Trial 的 scrambled 欄位
    
    使用方式：
        provider = SportsDataProjectionProvider()
        projections = await provider.fetch_projections_by_date("2026-02-08")
    """
    
    def __init__(self):
        """
        初始化 API 客戶端
        
        從 settings 讀取 API key 和 base URL
        max_retries: 最大重試次數（不含首次嘗試）
        timeout: HTTP 請求逾時時間（秒）
        """
        self.api_key = settings.sportsdata_api_key
        self.base_url = settings.sportsdata_base_url
        self.max_retries = 2
        self.timeout = 30.0  # 秒
    
    async def fetch_projections_by_date(self, date: str) -> List[Dict[str, Any]]:
        """
        呼叫 SportsDataIO API 取得指定日期的所有球員投影
        
        API Endpoint:
            GET {base_url}/v3/nba/projections/json/PlayerGameProjectionStatsByDate/{date}
        
        認證方式：
            Header: Ocp-Apim-Subscription-Key: {api_key}
        
        Args:
            date: 比賽日期（EST 時區），格式 YYYY-MM-DD
                  例如 "2026-02-08"
        
        Returns:
            正規化後的投影資料列表，每個元素是一個 dict
            [
                {
                    "player_id": 20000441,
                    "player_name": "Stephen Curry",
                    "team": "GS",
                    "points": 29.3,
                    "minutes": 34.5,
                    ...
                },
                ...
            ]
        
        Raises:
            SportsDataProjectionError: API 呼叫失敗（包含重試後仍失敗）
        """
        if not self.api_key:
            raise SportsDataProjectionError(
                0, 
                "SPORTSDATA_API_KEY 未設定。請在 .env 中設定 SPORTSDATA_API_KEY。"
            )
        
        url = (
            f"{self.base_url}/v3/nba/projections/json/"
            f"PlayerGameProjectionStatsByDate/{date}"
        )
        
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
        }
        
        # 重試邏輯：指數退避（1s, 2s, 4s...）
        last_error: Optional[Exception] = None
        
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, headers=headers)
                
                # 檢查 HTTP 狀態碼
                if response.status_code == 200:
                    raw_data = response.json()
                    
                    # API 回傳空列表表示該日無投影資料
                    if not raw_data:
                        print(f"ℹ️ SportsDataIO: {date} 無投影資料")
                        return []
                    
                    # 正規化每筆投影資料
                    normalized = [
                        self.normalize_projection(raw)
                        for raw in raw_data
                        if raw.get("Name")  # 過濾掉沒有名字的無效紀錄
                    ]
                    
                    print(f"✅ SportsDataIO: 取得 {len(normalized)} 筆投影資料 ({date})")
                    return normalized
                
                elif response.status_code == 401:
                    raise SportsDataProjectionError(
                        401,
                        "API Key 無效或已過期。請檢查 SPORTSDATA_API_KEY 設定。"
                    )
                
                elif response.status_code == 403:
                    raise SportsDataProjectionError(
                        403,
                        "無權限存取此 API。可能需要升級 subscription。"
                    )
                
                elif response.status_code == 429:
                    # Rate limit，等待後重試
                    wait_time = 2 ** (attempt + 1)
                    print(f"⚠️ SportsDataIO Rate Limit，等待 {wait_time}s 後重試...")
                    await asyncio.sleep(wait_time)
                    last_error = SportsDataProjectionError(
                        429, "API 呼叫次數超過限制"
                    )
                    continue
                
                else:
                    last_error = SportsDataProjectionError(
                        response.status_code,
                        f"API 回傳非預期狀態碼: {response.status_code}"
                    )
            
            except httpx.TimeoutException:
                last_error = SportsDataProjectionError(
                    0, f"API 請求逾時（{self.timeout}s）"
                )
            except httpx.HTTPError as e:
                last_error = SportsDataProjectionError(
                    0, f"HTTP 連線錯誤: {str(e)}"
                )
            except SportsDataProjectionError:
                raise  # 401, 403 等不可重試的錯誤直接拋出
            except Exception as e:
                last_error = SportsDataProjectionError(
                    0, f"未預期的錯誤: {str(e)}"
                )
            
            # 重試前等待（指數退避）
            if attempt < self.max_retries:
                wait_time = 2 ** attempt  # 1s, 2s
                print(f"⚠️ SportsDataIO API 呼叫失敗（嘗試 {attempt + 1}/{self.max_retries + 1}），"
                      f"等待 {wait_time}s 後重試...")
                await asyncio.sleep(wait_time)
        
        # 所有重試都失敗
        raise last_error or SportsDataProjectionError(0, "未知錯誤")
    
    def normalize_projection(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        將 SportsDataIO API 回傳的 PascalCase 欄位正規化為 snake_case
        
        處理邏輯：
        1. 遍歷 FIELD_MAPPING 中定義的欄位
        2. 如果 API 回傳中有該欄位，轉換名稱後加入結果
        3. 對 scrambled 的字串欄位（Free Trial）設為 None
        4. 計算衍生欄位（如 PRA = points + rebounds + assists）
        
        Args:
            raw: API 回傳的原始 dict（PascalCase 欄位名稱）
        
        Returns:
            正規化後的 dict（snake_case 欄位名稱）
        
        Example:
            >>> raw = {"Name": "Stephen Curry", "Points": 29.3, "Minutes": 34}
            >>> normalize_projection(raw)
            {"player_name": "Stephen Curry", "points": 29.3, "minutes": 34, ...}
        """
        result: Dict[str, Any] = {}
        
        for api_field, internal_field in FIELD_MAPPING.items():
            value = raw.get(api_field)
            
            if value is not None:
                # 檢查是否為 Free Trial scrambled 值
                if isinstance(value, str) and _is_scrambled(value):
                    result[internal_field] = None
                else:
                    result[internal_field] = value
            else:
                result[internal_field] = None
        
        # 計算衍生欄位：PRA（Points + Rebounds + Assists）
        points = result.get("points") or 0
        rebounds = result.get("rebounds") or 0
        assists = result.get("assists") or 0
        result["pra"] = round(points + rebounds + assists, 2) if any([
            result.get("points"), result.get("rebounds"), result.get("assists")
        ]) else None
        
        # 解析比賽日期（從 Day 欄位提取 YYYY-MM-DD）
        day_value = result.get("day")
        if day_value and isinstance(day_value, str):
            # API 回傳格式：2026-02-08T00:00:00
            result["date"] = day_value[:10]
        else:
            result["date"] = None
        
        return result


# 建立全域 API 客戶端實例
projection_provider = SportsDataProjectionProvider()
