"""
odds_theoddsapi.py - The Odds API 實作

實作 OddsProvider 介面，與 The Odds API v4 互動
API 文件：https://the-odds-api.com/liveapi/guides/v4/

The Odds API 是一個專門提供運動賽事賠率的第三方服務
支援多種運動和博彩公司
"""

import httpx
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.settings import settings
from app.services.odds_provider import OddsProvider, OddsAPIError


class TheOddsAPIProvider(OddsProvider):
    """
    The Odds API v4 實作
    
    負責與 The Odds API 進行 HTTP 通訊
    包含重試機制和錯誤處理
    
    API 端點：
    - GET /v4/sports/{sport}/events - 取得賽事列表
    - GET /v4/sports/{sport}/events/{eventId}/odds - 取得單場賠率
    """
    
    def __init__(self):
        """
        初始化 The Odds API Provider
        
        從 settings 取得：
        - base_url: API 基礎 URL
        - api_key: API 金鑰（用於認證）
        """
        self.base_url = settings.odds_api_base_url
        self.api_key = settings.odds_api_key
    
    async def _make_request(
        self, 
        endpoint: str, 
        params: Dict[str, Any],
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        發送 HTTP GET 請求到 The Odds API
        
        包含重試機制（retry with backoff）：
        當請求失敗時，會重試最多 max_retries 次
        
        httpx: 現代化的 Python HTTP 客戶端
        - 支援 async/await
        - 比 requests 更適合用於非同步應用
        
        Args:
            endpoint: API 端點路徑（如 "/v4/sports/basketball_nba/events"）
            params: 查詢參數字典
            max_retries: 最大重試次數
        
        Returns:
            API 回應的 JSON 資料
        
        Raises:
            OddsAPIError: 當所有重試都失敗時
        """
        # 加入 API key 到參數中
        params["apiKey"] = self.api_key
        
        url = f"{self.base_url}{endpoint}"
        
        last_error = None
        
        # 重試迴圈
        for attempt in range(max_retries):
            try:
                # 使用 async with 確保連線正確關閉
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, params=params)
                    
                    # 檢查回應狀態碼
                    if response.status_code == 200:
                        return response.json()
                    
                    # 處理各種錯誤狀態碼
                    if response.status_code == 401:
                        raise OddsAPIError("Invalid API key", 401)
                    elif response.status_code == 404:
                        raise OddsAPIError("Resource not found", 404)
                    elif response.status_code == 422:
                        raise OddsAPIError(
                            f"Invalid parameters: {response.text}", 
                            422
                        )
                    elif response.status_code == 429:
                        # Rate limit exceeded，需要等待後重試
                        raise OddsAPIError("Rate limit exceeded", 429)
                    else:
                        raise OddsAPIError(
                            f"API error: {response.text}", 
                            response.status_code
                        )
                        
            except httpx.TimeoutException:
                last_error = OddsAPIError("Request timeout")
            except httpx.RequestError as e:
                last_error = OddsAPIError(f"Request error: {str(e)}")
            except OddsAPIError as e:
                # 對於 401（認證錯誤）和 422（參數錯誤），不需要重試
                if e.status_code in [401, 422]:
                    raise
                last_error = e
        
        # 所有重試都失敗
        raise last_error or OddsAPIError("Unknown error after retries")
    
    async def get_events(
        self,
        sport: str = "basketball_nba",
        regions: str = "us",
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        取得 NBA 賽事列表
        
        呼叫 The Odds API 的 events 端點
        API 端點：GET /v4/sports/{sport}/events
        
        API 文件：https://the-odds-api.com/liveapi/guides/v4/#get-events
        
        Args:
            sport: 運動類型，預設 "basketball_nba"
            regions: 地區代碼，預設 "us"
            date_from: 開始日期篩選（可選）
            date_to: 結束日期篩選（可選）
        
        Returns:
            賽事列表，每個賽事包含：
            - id: 賽事 ID
            - sport_key: 運動類型
            - home_team: 主場球隊
            - away_team: 客場球隊
            - commence_time: 開始時間（ISO 8601）
        
        Example:
            >>> provider = TheOddsAPIProvider()
            >>> events = await provider.get_events()
            >>> for event in events:
            ...     print(f"{event['away_team']} @ {event['home_team']}")
        """
        endpoint = f"/v4/sports/{sport}/events"
        
        params = {}
        
        # 日期篩選（如果提供）
        # The Odds API 只接受 YYYY-MM-DDTHH:MM:SSZ 格式，不能有微秒
        if date_from:
            params["commenceTimeFrom"] = date_from.strftime("%Y-%m-%dT%H:%M:%SZ")
        if date_to:
            params["commenceTimeTo"] = date_to.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # 發送請求
        data = await self._make_request(endpoint, params)
        
        # API 回傳的是賽事列表（陣列）
        return data if isinstance(data, list) else []
    
    async def get_event_odds(
        self,
        sport: str = "basketball_nba",
        event_id: str = "",
        regions: str = "us",
        markets: str = "player_points",
        odds_format: str = "american",
        bookmakers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        取得單場賽事的球員 props 賠率
        
        呼叫 The Odds API 的 event odds 端點
        API 端點：GET /v4/sports/{sport}/events/{eventId}/odds
        
        API 文件：https://the-odds-api.com/liveapi/guides/v4/#get-event-odds
        
        注意：球員 props（如 player_points）屬於「非精選市場」，
        需要使用 event-specific 端點而非 odds 端點
        
        Args:
            sport: 運動類型
            event_id: 賽事 ID（從 get_events 取得）
            regions: 地區代碼（影響可用的博彩公司）
            markets: 市場類型（player_points, player_rebounds 等）
            odds_format: 賠率格式
                - "american": 美式（-110, +150）
                - "decimal": 小數（1.91, 2.50）
            bookmakers: 指定博彩公司（可選）
        
        Returns:
            賠率資料，包含：
            - id: 賽事 ID
            - sport_key: 運動類型
            - bookmakers: 博彩公司列表，每個包含 markets 和 outcomes
        
        Example:
            >>> odds = await provider.get_event_odds(
            ...     event_id="abc123",
            ...     markets="player_points"
            ... )
            >>> for bookmaker in odds['bookmakers']:
            ...     print(f"{bookmaker['key']}: {len(bookmaker['markets'])} markets")
        """
        endpoint = f"/v4/sports/{sport}/events/{event_id}/odds"
        
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format
        }
        
        # 如果指定了博彩公司
        if bookmakers:
            params["bookmakers"] = ",".join(bookmakers)
        
        # 發送請求
        data = await self._make_request(endpoint, params)
        
        return data


# 建立全域實例
odds_provider = TheOddsAPIProvider()

