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
    
    async def delete_pattern(self, pattern: str) -> int:
        """
        刪除符合 pattern 的所有快取資料
        
        使用 Redis SCAN + DELETE 刪除符合模式的所有 key
        比 KEYS 命令更安全，不會阻塞 Redis
        
        Args:
            pattern: 匹配模式（支援 * 萬用字元）
                     例如: "daily_picks:*" 會刪除所有以 daily_picks: 開頭的 key
        
        Returns:
            int: 刪除的 key 數量
        
        Example:
            >>> await cache.delete_pattern("daily_picks:*")
            3  # 刪除了 3 個 key
        """
        try:
            client = await self.get_client()
            deleted_count = 0
            
            # 使用 SCAN 迭代找出符合 pattern 的 key
            # scan_iter: 異步迭代器，每次返回一批符合的 key
            # match=pattern: 匹配模式
            # count=100: 每次掃描的數量（建議值）
            async for key in client.scan_iter(match=pattern, count=100):
                await client.delete(key)
                deleted_count += 1
            
            if deleted_count > 0:
                print(f"🗑️ 已刪除 {deleted_count} 個快取 (pattern: {pattern})")
            
            return deleted_count
            
        except Exception as e:
            print(f"Cache delete_pattern error: {e}")
            return 0
    
    async def clear_daily_picks_cache(self) -> int:
        """
        清除所有每日精選的快取
        
        當 CSV 資料更新後，需要清除每日精選的快取
        這樣下次請求會重新分析並使用最新的資料
        
        Returns:
            int: 刪除的 key 數量
        """
        return await self.delete_pattern("daily_picks:*")
    
    async def close(self):
        """
        關閉 Redis 連線
        
        在應用程式結束時應該呼叫此方法釋放資源
        """
        if self._client:
            await self._client.close()
            self._client = None

    async def acquire_lock(self, key: str, ttl: int) -> bool:
        """
        取得簡單分散式鎖。

        使用 SET key value NX EX ttl，成功表示本次請求取得鎖。
        """
        try:
            client = await self.get_client()
            acquired = await client.set(key, "1", ex=ttl, nx=True)
            return bool(acquired)
        except Exception as e:
            print(f"Cache acquire_lock error: {e}")
            return False

    async def release_lock(self, key: str) -> bool:
        """
        釋放分散式鎖。
        """
        try:
            client = await self.get_client()
            await client.delete(key)
            return True
        except Exception as e:
            print(f"Cache release_lock error: {e}")
            return False

    async def increment_sorted_set(self, key: str, member: str, amount: float = 1.0) -> float:
        """
        對 sorted set 的 member 做加權累計。
        """
        try:
            client = await self.get_client()
            return await client.zincrby(key, amount, member)
        except Exception as e:
            print(f"Cache increment_sorted_set error: {e}")
            return 0.0

    async def get_top_sorted_set_members(self, key: str, limit: int) -> list[str]:
        """
        取得 sorted set 分數最高的前 N 個 member。
        """
        try:
            client = await self.get_client()
            members = await client.zrevrange(key, 0, max(limit - 1, 0))
            return list(members)
        except Exception as e:
            print(f"Cache get_top_sorted_set_members error: {e}")
            return []

    async def remove_sorted_set_member(self, key: str, member: str) -> bool:
        """
        從 sorted set 移除指定 member。
        """
        try:
            client = await self.get_client()
            await client.zrem(key, member)
            return True
        except Exception as e:
            print(f"Cache remove_sorted_set_member error: {e}")
            return False
    
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
