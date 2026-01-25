"""
main.py - FastAPI 應用程式主入口點

這是整個後端應用的入口
負責：
1. 建立 FastAPI 應用實例
2. 配置 CORS（跨來源資源共享）
3. 註冊所有路由（routers）
4. 定義生命週期事件（啟動/關閉）
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import health, nba, daily_picks
from app.services.cache import cache_service
from app.services.scheduler import scheduler_service
from app.settings import settings


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
    print("🚀 Starting No-Vig NBA API...")
    print(f"📊 Odds API Base URL: {settings.odds_api_base_url}")
    print(f"🔴 Redis URL: {settings.redis_url}")
    
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
    
    await cache_service.close()
    print("✅ Cache service closed")


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,  # 從設定讀取允許的來源
    allow_credentials=True,
    allow_methods=["*"],  # 允許所有 HTTP 方法（GET, POST, PUT, DELETE 等）
    allow_headers=["*"],  # 允許所有標頭
)

# 註冊路由器（Routers）
# include_router: 將路由器的所有端點加入應用
# 這樣組織代碼可以讓不同功能模組分開管理
app.include_router(health.router)
app.include_router(nba.router)
app.include_router(daily_picks.router)  # 每日高機率球員分析


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

