"""
main.py - FastAPI 應用程式主入口點

這是整個後端應用的入口
負責：
1. 建立 FastAPI 應用實例
2. 配置 CORS（跨來源資源共享）
3. 註冊所有路由（routers）
4. 定義生命週期事件（啟動/關閉）
"""

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import agent, health, metrics, nba, wnba, wnba_agent, daily_picks, picks, projections, odds_history, lineups
from app.middleware.event_stream import EventStreamCacheControlMiddleware
from app.middleware.logging_config import RequestLoggingMiddleware, setup_logging
from app.middleware.rate_limit import install_rate_limiter
from app.dsn import mask_database_url, redact_secrets
from app.services.cache import cache_service
from app.services.db import db_service
from app.services.scheduler import scheduler_service
from app.settings import settings

logger = logging.getLogger(__name__)


def _startup_secrets() -> tuple[str, ...]:
    """Passwords from the configured URLs, kept out of startup logs."""
    secrets: list[str] = []
    for url in (settings.database_url, settings.redis_url):
        password = urlsplit(url).password or ""
        if len(password) >= 4:
            secrets.append(password)
    return tuple(secrets)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    應用程式生命週期管理器
    
    asynccontextmanager: 用於建立非同步上下文管理器
    使用 async with 語法時：
    - yield 之前的代碼在啟動時執行
    - yield 之後的代碼在關閉時執行
    
    這裡用於：
    - 啟動時：初始化資源（如 Redis 連線）
    - 關閉時：清理資源（關閉 Redis 連線）
    
    Args:
        app: FastAPI 應用實例
    
    Usage:
        app = FastAPI(lifespan=lifespan)
    """
    # 啟動時執行
    setup_logging()
    print("🚀 Starting No-Vig NBA API...")
    print(f"📊 Odds API Base URL: {settings.odds_api_base_url}")
    print(f"🔴 Redis URL: {mask_database_url(settings.redis_url)}")
    print(f"🐘 Database URL: {mask_database_url(settings.database_url)}")
    print(f"📈 SportsDataIO: {'已設定' if settings.sportsdata_api_key else '未設定（投影功能停用）'}")
    
    # 初始化 PostgreSQL 連線池。
    # init() 自己吞掉連線錯誤並把 pool 設成 None，所以這裡還要看 is_connected。
    # DATABASE_REQUIRED=true 時啟動必須失敗；預設 false，本機沒有 Postgres 仍可啟動。
    secrets = _startup_secrets()
    try:
        await db_service.init()
    except Exception as exc:
        safe = redact_secrets(str(exc), secrets)
        logger.error("PostgreSQL startup failed: %s", safe)
        if settings.database_required:
            raise RuntimeError(
                "DATABASE_REQUIRED is true but PostgreSQL initialization failed. "
                f"Detail: {safe}"
            ) from None
        print("⚠️ PostgreSQL 初始化失敗（連線字串已遮罩，詳見 error log）")
        print("   投影功能的持久化儲存將不可用（仍可使用 Redis 快取）")
    else:
        if not db_service.is_connected:
            if settings.database_required:
                logger.error(
                    "DATABASE_REQUIRED is true but PostgreSQL initialization did not open a pool"
                )
                raise RuntimeError(
                    "DATABASE_REQUIRED is true but PostgreSQL initialization did not open a pool"
                )
            print("⚠️ PostgreSQL 初始化失敗（連線字串已遮罩，詳見 error log）")
            print("   投影功能的持久化儲存將不可用（仍可使用 Redis 快取）")
    
    # 啟動定時任務排程器
    try:
        scheduler_service.start()
        print(f"📅 下次分析時間: {scheduler_service.get_next_run_time()}")
    except Exception as e:
        print(f"⚠️ 排程器啟動失敗: {e}")
    
    yield  # 應用運行中...
    
    # 關閉時執行
    print("👋 Shutting down...")
    
    # 停止定時任務排程器
    scheduler_service.stop()
    
    # 關閉 PostgreSQL 連線池
    await db_service.close()
    
    await cache_service.close()
    print("✅ All services closed")


# 建立 FastAPI 應用實例
# title: API 標題（顯示在 Swagger 文件）
# description: API 描述
# version: API 版本號
# lifespan: 生命週期管理器
app = FastAPI(
    title="No-Vig NBA API",
    description="""
    NBA 球員得分 Props「去水機率」計算 API
    
    ## 功能
    
    - **賽事列表**: 取得 NBA 當日賽事
    - **去水機率**: 計算球員 props 的公平機率
    - **球員建議**: Autocomplete 用的球員列表
    - **每日精選**: 自動分析高機率（>65%）球員選擇
    
    ## 什麼是「去水機率」？
    
    博彩公司的賠率包含「水錢」（vig/juice），使得 Over + Under 的隱含機率總和超過 100%。
    本 API 將隱含機率「去水」，得出更接近真實的公平機率。
    """,
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS（跨來源資源共享）
# 這是讓前端（不同網域）能夠呼叫此 API 的必要設定
# 
# CORSMiddleware: FastAPI 提供的 CORS 中間件
# - allow_origins: 允許的來源網域列表
# - allow_credentials: 是否允許攜帶 cookies
# - allow_methods: 允許的 HTTP 方法
# - allow_headers: 允許的 HTTP 標頭
app.add_middleware(CORSMiddleware, **settings.cors_middleware_kwargs())
app.add_middleware(EventStreamCacheControlMiddleware)

# Request logging middleware (structured JSON logs + in-process metrics)
app.add_middleware(RequestLoggingMiddleware)

# Rate limiting (slowapi)
install_rate_limiter(app)

# 註冊路由器（Routers）
# include_router: 將路由器的所有端點加入應用
# 這樣組織代碼可以讓不同功能模組分開管理
app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(nba.router)
app.include_router(wnba.router)  # SPO-32 Phase 1: WNBA CSV + read-only stats
app.include_router(agent.router)
app.include_router(wnba_agent.router)  # SPO-58 Phase 5c: WNBA agent chat
app.include_router(daily_picks.router)  # 每日高機率球員分析
app.include_router(picks.router)  # Discord bot AI picks API
app.include_router(projections.router)  # 球員投影資料（SportsDataIO）
app.include_router(odds_history.router)  # 盤口歷史快照（Line Movement Tracking）
app.include_router(lineups.router)  # 免費先發預測共識


# 根路徑重導向到 API 文件
@app.get("/", include_in_schema=False)
async def root():
    """
    根路徑處理
    
    返回歡迎訊息和 API 文件連結
    include_in_schema=False: 不在 Swagger 文件中顯示此端點
    """
    return {
        "message": "Welcome to No-Vig NBA API",
        "docs": "/docs",
        "redoc": "/redoc"
    }


# 當直接執行此檔案時啟動伺服器
# （通常用於開發環境，生產環境會用 uvicorn 指令）
if __name__ == "__main__":
    import uvicorn
    
    # uvicorn.run: 啟動 ASGI 伺服器
    # - "app.main:app": 應用程式位置（module:variable）
    # - host: 監聽的 IP 位址（0.0.0.0 表示所有介面）
    # - port: 監聽的連接埠
    # - reload: 自動重載（開發時使用）
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
