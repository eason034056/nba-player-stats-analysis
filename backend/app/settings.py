"""
settings.py - 應用程式配置設定

使用 pydantic-settings 來管理環境變數
- BaseSettings: pydantic 提供的設定基底類別，自動從環境變數讀取值
- 每個屬性都對應一個環境變數（大小寫不敏感）
"""

import re
from typing import Any

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    應用程式設定類別
    
    屬性名稱會自動對應到同名的環境變數
    例如: odds_api_key 對應 ODDS_API_KEY 環境變數
    """
    
    # The Odds API 設定
    odds_api_key: str = ""  # The Odds API 的 API 金鑰
    odds_api_base_url: str = "https://api.the-odds-api.com"  # API 基礎 URL

    # BALLDONTLIE 設定。client 讀這兩個欄位，這張票還沒把 client 接到路由或排程。
    # balldontlie_api_key 對應 BALLDONTLIE_API_KEY。SecretStr 讓 Settings 的 repr
    # 不印出金鑰。client 用 get_secret_value() 取出 str，放進 Authorization，不要寫進日誌。
    balldontlie_api_key: SecretStr = SecretStr("")
    # bdl_rate_limit_per_min 對應 BDL_RATE_LIMIT_PER_MIN。試用 key 是 5，付費 GOAT 是 600。
    # 真正送出請求後，如果回應帶 x-ratelimit-limit，共用預算改跟那個標頭。
    bdl_rate_limit_per_min: int = 5
    
    # SportsDataIO 設定（球員投影數據）
    sportsdata_api_key: str = ""  # SportsDataIO API 金鑰
    sportsdata_base_url: str = "https://api.sportsdata.io"  # SportsDataIO API 基礎 URL
    
    # PostgreSQL 設定
    database_url: str = "postgresql://novig:novig@localhost:5432/novig_nba"  # PostgreSQL 連線 URL
    # False locally so tests and dev without Postgres still boot.
    # Set DATABASE_REQUIRED=true in production so a bad URL fails startup.
    database_required: bool = False
    
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
    
    # CORS. CORS_ALLOWED_ORIGINS wins when it is set. ALLOWED_ORIGINS stays
    # as the alias so local compose keeps working. Neither may contain '*'.
    allowed_origins: str = "http://localhost:3000"
    cors_allowed_origins: str | None = None
    cors_allowed_origin_regex: str = ""

    # Shared with the Vercel rewrite. Empty means x-real-ip and
    # x-forwarded-for are never trusted. Loaded on EC2 from SSM.
    vercel_proxy_secret: SecretStr = SecretStr("")
    # False locally and in tests. deploy/docker-compose.prod.yml sets true,
    # which wins over the env file. When true, every route except the health
    # checks requires x-sportslab-proxy-secret.
    proxy_secret_required: bool = False

    # Whole agent-chat request, including a slip or board of several graphs.
    # Must finish before Vercel's 120s rewrite limit. 100s leaves room for
    # the proxy. The validator refuses a value above 105.
    agent_chat_timeout_seconds: float = 100

    # 日誌等級
    log_level: str = "info"

    # Rate limiting (requests per window, slowapi format)
    rate_limit_default: str = "60/minute"
    rate_limit_props: str = "20/minute"

    # Odds API quota alert thresholds (percent remaining)
    odds_quota_warn_percent: int = 30
    odds_quota_critical_percent: int = 10

    # Bot API keys (comma-separated)
    bot_api_keys: str = ""          # Free-tier bot API keys
    bot_api_keys_premium: str = ""  # Premium-tier bot API keys
    bot_picks_free_delay_minutes: int = 60  # Delay for free-tier picks (minutes)
    rate_limit_bot_picks: str = "12/minute"  # Rate limit for bot picks endpoint

    @field_validator("allowed_origins", "cors_allowed_origins")
    @classmethod
    def reject_wildcard_origin(cls, value: str | None) -> str | None:
        """Refuse '*' in the allow-list. A star is not a valid origin."""
        if value is None:
            return None
        for part in value.split(","):
            token = part.strip()
            if "*" in token:
                raise ValueError(
                    "CORS allow-list must not include '*'. "
                    "Use exact origins or CORS_ALLOWED_ORIGIN_REGEX."
                )
        return value

    @field_validator("cors_allowed_origin_regex")
    @classmethod
    def reject_open_origin_regex(cls, value: str) -> str:
        """Refuse a regex that matches an arbitrary origin, including '*'."""
        text = value.strip()
        if text == "":
            return ""
        if text == "*":
            raise ValueError("CORS_ALLOWED_ORIGIN_REGEX must not be '*'")
        try:
            compiled = re.compile(text)
        except re.error as exc:
            raise ValueError(
                f"CORS_ALLOWED_ORIGIN_REGEX is not a valid regular expression ({exc})"
            ) from exc
        probes = ("https://evil.example", "http://evil.example")
        if any(compiled.fullmatch(probe) for probe in probes):
            raise ValueError(
                "CORS_ALLOWED_ORIGIN_REGEX must not match an arbitrary origin"
            )
        return text

    @field_validator("agent_chat_timeout_seconds")
    @classmethod
    def bound_agent_chat_timeout(cls, value: float) -> float:
        """Keep the deadline under the 120s proxy limit."""
        if value <= 0 or value > 105:
            raise ValueError(
                "agent_chat_timeout_seconds must be greater than 0 and at most 105"
            )
        return value

    @property
    def allowed_origins_list(self) -> list[str]:
        """Comma-separated browser origins.

        A non-empty CORS_ALLOWED_ORIGINS wins. Blank or unset falls back to
        ALLOWED_ORIGINS so local compose can pass an empty override.
        """
        chosen = self.cors_allowed_origins
        if chosen is None or chosen.strip() == "":
            chosen = self.allowed_origins
        return [origin.strip() for origin in chosen.split(",") if origin.strip()]

    @property
    def cors_origin_regex(self) -> str | None:
        """Regex for CORSMiddleware.allow_origin_regex. None when unset."""
        text = self.cors_allowed_origin_regex.strip()
        return text or None

    def cors_middleware_kwargs(self) -> dict[str, Any]:
        """Arguments for CORSMiddleware. allow_origin_regex is omitted when empty."""
        return {
            "allow_origins": self.allowed_origins_list,
            "allow_origin_regex": self.cors_origin_regex,
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }

    @property
    def bot_api_keys_set(self) -> set:
        """All valid bot API keys (free + premium)."""
        keys = set()
        if self.bot_api_keys:
            keys.update(k.strip() for k in self.bot_api_keys.split(",") if k.strip())
        if self.bot_api_keys_premium:
            keys.update(k.strip() for k in self.bot_api_keys_premium.split(",") if k.strip())
        return keys

    @property
    def bot_api_keys_premium_set(self) -> set:
        """Premium-tier bot API keys only."""
        if not self.bot_api_keys_premium:
            return set()
        return {k.strip() for k in self.bot_api_keys_premium.split(",") if k.strip()}

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
