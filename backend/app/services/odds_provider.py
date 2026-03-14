"""
odds_provider.py - 賠率提供者抽象介面

定義與外部賠率 API 互動的抽象介面（Abstract Base Class）
使用介面設計可以：
1. 方便替換不同的賠率 API 供應商
2. 方便進行單元測試（mock）
3. 符合依賴反轉原則（DIP）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime


class OddsProvider(ABC):
    """
    賠率提供者抽象基底類別
    
    定義所有賠率 API 必須實作的方法
    ABC (Abstract Base Class): Python 的抽象類別裝飾器
    abstractmethod: 標記必須由子類別實作的方法
    """
    
    @abstractmethod
    async def get_events(
        self, 
        sport: str, 
        regions: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        取得賽事列表
        
        Args:
            sport: 運動類型（如 "basketball_nba"）
            regions: 地區代碼（如 "us"）
            date_from: 開始日期（可選）
            date_to: 結束日期（可選）
        
        Returns:
            賽事列表，每個賽事為一個字典
        
        Raises:
            OddsAPIError: 當 API 呼叫失敗時
        """
        pass


@dataclass(frozen=True)
class QuotaUsage:
    """
    The Odds API 配額使用情況。

    - remaining: 剩餘可用請求數
    - used: 已使用請求數
    - last: 本次請求消耗量
    """

    remaining: Optional[int] = None
    used: Optional[int] = None
    last: Optional[int] = None

    @property
    def total(self) -> Optional[int]:
        if self.remaining is None or self.used is None:
            return None
        return self.remaining + self.used

    @property
    def remaining_ratio(self) -> Optional[float]:
        total = self.total
        if total in (None, 0) or self.remaining is None:
            return None
        return self.remaining / total
    
    @abstractmethod
    async def get_event_odds(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str = "american",
        bookmakers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        取得單場賽事的賠率資料
        
        Args:
            sport: 運動類型
            event_id: 賽事 ID
            regions: 地區代碼
            markets: 投注市場類型（如 "player_points"）
            odds_format: 賠率格式（"american" 或 "decimal"）
            bookmakers: 指定博彩公司列表（可選，None 表示全部）
        
        Returns:
            賠率資料字典
        
        Raises:
            OddsAPIError: 當 API 呼叫失敗時
        """
        pass


class OddsAPIError(Exception):
    """
    賠率 API 錯誤例外類別
    
    用於封裝所有與外部賠率 API 相關的錯誤
    包含狀態碼和訊息，方便除錯和錯誤處理
    
    Attributes:
        status_code: HTTP 狀態碼（如 401, 404, 500）
        message: 錯誤訊息
    """
    
    def __init__(self, message: str, status_code: Optional[int] = None):
        """
        初始化 OddsAPIError
        
        Args:
            message: 錯誤訊息
            status_code: HTTP 狀態碼（可選）
        """
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """
        字串表示
        
        如果有狀態碼，會一併顯示
        """
        if self.status_code:
            return f"[{self.status_code}] {self.message}"
        return self.message
