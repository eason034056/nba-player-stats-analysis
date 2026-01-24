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
    
    # Redis 設定
    redis_url: str = "redis://localhost:6379"  # Redis 連線 URL
    
    # 快取 TTL（Time To Live）設定，單位：秒
    cache_ttl_events: int = 300  # 賽事列表快取時間（5分鐘）
    cache_ttl_props: int = 60    # Props 資料快取時間（1分鐘）
    cache_ttl_players: int = 300 # 球員建議快取時間（5分鐘）
    
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


# 建立全域設定實例，供其他模組引用
settings = Settings()

