"""
settings.py - 應用程式配置設定

使用 pydantic-settings 來管理環境變數
- BaseSettings: pydantic 提供的設定基底類別，自動從環境變數讀取值
- 每個屬性都對應一個環境變數（大小寫不敏感）
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """
    應用程式設定類別
    
    屬性名稱會自動對應到同名的環境變數
    例如: odds_api_key 對應 ODDS_API_KEY 環境變數
    """
    
    # The Odds API 設定
    odds_api_key: str = ""  # The Odds API 的 API 金鑰
    odds_api_base_url: str = "https://api.the-odds-api.com"  # API 基礎 URL
    
    # SportsDataIO 設定（球員投影數據）
    sportsdata_api_key: str = ""  # SportsDataIO API 金鑰
    sportsdata_base_url: str = "https://api.sportsdata.io"  # SportsDataIO API 基礎 URL
    
    # PostgreSQL 設定
    database_url: str = "postgresql://novig:novig@localhost:5432/novig_nba"  # PostgreSQL 連線 URL
    
    # Redis 設定
    redis_url: str = "redis://localhost:6379"  # Redis 連線 URL
    
    # 快取 TTL（Time To Live）設定，單位：秒
    cache_ttl_events: int = 300  # 賽事列表快取時間（5分鐘）
    cache_ttl_props: int = 60    # Props 資料快取時間（1分鐘）
    cache_ttl_players: int = 300 # 球員建議快取時間（5分鐘）
    cache_ttl_projections: int = 7200  # 投影資料快取時間（2小時）
    cache_ttl_lineups: int = 3600
    cache_ttl_market_fresh: int = 600
    cache_ttl_market_stale: int = 900
    odds_refresh_lock_ttl: int = 10
    odds_wait_for_refresh_ms: int = 300
    odds_quota_protect_percent: int = 15
    odds_hot_keys_limit: int = 10
    lineup_stale_minutes: int = 20
    lineup_refresh_lock_ttl: int = 60
    lineup_active_refresh_interval_minutes: int = 15
    lineup_pre_tipoff_refresh_interval_minutes: int = 5
    
    # CORS 設定
    allowed_origins: str = "http://localhost:3000"  # 允許的前端來源，逗號分隔
    
    # 日誌等級
    log_level: str = "info"
    
    @property
    def allowed_origins_list(self) -> List[str]:
        """
        將 allowed_origins 字串轉換為列表
        支援多個來源用逗號分隔
        """
        return [origin.strip() for origin in self.allowed_origins.split(",")]
    
    class Config:
        """
        pydantic-settings 配置
        - env_file: 指定 .env 檔案路徑
        - case_sensitive: 環境變數名稱是否區分大小寫
        """
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


# 建立全域設定實例，供其他模組引用
settings = Settings()
