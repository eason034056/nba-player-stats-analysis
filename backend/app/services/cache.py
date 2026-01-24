"""
cache.py - Redis 快取服務

封裝 Redis 操作，提供快取存取功能
快取可以減少對外部 Odds API 的呼叫次數，降低成本並提升回應速度
"""

import json
import redis.asyncio as redis
from typing import Optional, Any
from app.settings import settings


class CacheService:
    """
    Redis 快取服務類別
    
    使用單例模式（透過模組層級實例）確保整個應用程式共用同一個連線
    
    主要功能：
    - get: 取得快取資料
    - set: 設定快取資料（含 TTL）
    - delete: 刪除快取資料
    - build_key: 建構快取鍵名
    """
    
    def __init__(self):
        """
        初始化快取服務
        
        注意：實際的 Redis 連線是延遲建立的（lazy initialization）
        在第一次呼叫時才會真正連線
        """
        self._client: Optional[redis.Redis] = None
    
    async def get_client(self) -> redis.Redis:
        """
        取得 Redis 客戶端連線
        
        使用延遲初始化（lazy initialization）：
        只有在第一次需要時才建立連線
        
        redis.from_url: 從 URL 字串建立 Redis 連線
        - decode_responses=True: 自動將 bytes 解碼為字串
        
        Returns:
            Redis 客戶端實例
        """
        if self._client is None:
            self._client = redis.from_url(
                settings.redis_url,
                decode_responses=True  # 自動解碼為字串
            )
        return self._client
    
    async def get(self, key: str) -> Optional[Any]:
        """
        從快取取得資料
        
        流程：
        1. 從 Redis 取得字串
        2. 如果存在，解析 JSON 為 Python 物件
        3. 如果不存在，返回 None
        
        Args:
            key: 快取鍵名
        
        Returns:
            快取的資料（已解析為 Python 物件），或 None
        
        Example:
            >>> data = await cache.get("events:nba:2026-01-14:us")
            >>> if data:
            ...     print(f"Cache hit: {len(data['events'])} events")
        """
        try:
            client = await self.get_client()
            value = await client.get(key)
            
            if value:
                return json.loads(value)
            return None
            
        except Exception as e:
            # 快取失敗不應該影響主要功能，記錄錯誤後返回 None
            print(f"Cache get error: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int) -> bool:
        """
        設定快取資料
        
        Args:
            key: 快取鍵名
            value: 要快取的資料（會被序列化為 JSON）
            ttl: Time To Live（存活時間），單位為秒
                 過了這個時間後，Redis 會自動刪除這個 key
        
        Returns:
            是否設定成功
        
        Example:
            >>> await cache.set(
            ...     "events:nba:2026-01-14:us",
            ...     {"events": [...]},
            ...     ttl=300  # 5 分鐘
            ... )
        """
        try:
            client = await self.get_client()
            # 將 Python 物件序列化為 JSON 字串
            json_value = json.dumps(value, default=str)
            # ex=ttl: 設定過期時間（秒）
            await client.set(key, json_value, ex=ttl)
            return True
            
        except Exception as e:
            print(f"Cache set error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """
        刪除快取資料
        
        Args:
            key: 快取鍵名
        
        Returns:
            是否刪除成功
        """
        try:
            client = await self.get_client()
            await client.delete(key)
            return True
            
        except Exception as e:
            print(f"Cache delete error: {e}")
            return False
    
    async def close(self):
        """
        關閉 Redis 連線
        
        在應用程式結束時應該呼叫此方法釋放資源
        """
        if self._client:
            await self._client.close()
            self._client = None
    
    @staticmethod
    def build_events_key(date: str, regions: str) -> str:
        """
        建構賽事列表的快取鍵名
        
        格式：events:nba:{date}:{regions}
        
        Args:
            date: 日期字串（YYYY-MM-DD）
            regions: 地區代碼（如 "us"）
        
        Returns:
            快取鍵名
        
        Example:
            >>> CacheService.build_events_key("2026-01-14", "us")
            "events:nba:2026-01-14:us"
        """
        return f"events:nba:{date}:{regions}"
    
    @staticmethod
    def build_props_key(
        event_id: str, 
        market: str, 
        regions: str, 
        bookmakers: Optional[list], 
        odds_format: str
    ) -> str:
        """
        建構 Props 資料的快取鍵名
        
        格式：props:nba:{event_id}:{market}:{regions}:{bookmakers}:{odds_format}
        
        Args:
            event_id: 賽事 ID
            market: 市場類型（如 "player_points"）
            regions: 地區代碼
            bookmakers: 博彩公司列表（None 表示全部）
            odds_format: 賠率格式
        
        Returns:
            快取鍵名
        """
        # 將 bookmakers 列表排序後轉為字串，確保相同內容產生相同 key
        books_str = ",".join(sorted(bookmakers)) if bookmakers else "all"
        return f"props:nba:{event_id}:{market}:{regions}:{books_str}:{odds_format}"
    
    @staticmethod
    def build_players_key(event_id: str) -> str:
        """
        建構球員列表的快取鍵名
        
        格式：players:nba:{event_id}
        
        Args:
            event_id: 賽事 ID
        
        Returns:
            快取鍵名
        """
        return f"players:nba:{event_id}"


# 建立全域快取服務實例
cache_service = CacheService()

