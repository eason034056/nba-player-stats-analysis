"""
health.py - 健康檢查 API 端點

提供服務健康狀態檢查功能
用途：
1. 部署時確認服務正常啟動
2. 負載均衡器（Load Balancer）定期檢查
3. 監控系統偵測服務狀態
4. 手動觸發排程任務（如 CSV 下載）
"""

from fastapi import APIRouter
from datetime import datetime, timezone
from app.models.schemas import HealthResponse
from app.services.scheduler import scheduler_service
from app.services.csv_downloader import csv_downloader_service

# 建立路由器
# APIRouter: FastAPI 的路由分組工具
# prefix: 此路由器下所有端點的共同前綴
# tags: 用於 API 文件分類（OpenAPI/Swagger）
router = APIRouter(
    prefix="/api",
    tags=["health"]
)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康檢查",
    description="檢查 API 服務是否正常運作"
)
async def health_check() -> HealthResponse:
    """
    健康檢查端點
    
    GET /api/health
    
    用於確認 API 服務正常運作
    返回服務名稱和當前伺服器時間（UTC）
    
    Returns:
        HealthResponse: 包含服務狀態的回應
        - ok: True 表示服務正常
        - service: 服務識別名稱
        - time: 伺服器當前 UTC 時間
    
    Example Response:
        {
            "ok": true,
            "service": "no-vig-nba",
            "time": "2026-01-14T18:00:00Z"
        }
    """
    return HealthResponse(
        ok=True,
        service="no-vig-nba",
        time=datetime.now(timezone.utc)
    )


@router.post(
    "/trigger-csv-download",
    summary="手動觸發 CSV 下載",
    description="從 GitHub 下載最新的 NBA 球員數據 CSV 文件"
)
async def trigger_csv_download():
    """
    手動觸發 CSV 下載
    
    POST /api/trigger-csv-download
    
    用於手動下載最新的 NBA 球員數據 CSV，不需要等待排程時間
    這個端點會立即從 GitHub 下載 CSV 並儲存到 data/ 目錄
    
    Returns:
        dict: 下載結果
        - success: bool, 是否成功
        - message: str, 結果訊息
        - last_modified: str | None, CSV 檔案的最後修改時間
    
    Example Response (成功):
        {
            "success": true,
            "message": "CSV 下載成功",
            "last_modified": "2026-01-28T15:00:00+00:00"
        }
    
    Example Response (失敗):
        {
            "success": false,
            "message": "CSV 下載失敗",
            "last_modified": null
        }
    """
    # 呼叫排程器的手動觸發方法
    success = await scheduler_service.trigger_csv_download_now()
    
    return {
        "success": success,
        "message": "CSV 下載成功" if success else "CSV 下載失敗",
        "last_modified": csv_downloader_service.get_last_modified()
    }


@router.get(
    "/scheduler-status",
    summary="查看排程器狀態",
    description="取得排程器的運行狀態和下次執行時間"
)
async def get_scheduler_status():
    """
    查看排程器狀態
    
    GET /api/scheduler-status
    
    顯示所有排程任務的狀態和下次執行時間
    
    Returns:
        dict: 排程器狀態
        - is_running: bool, 排程器是否運行中
        - next_daily_analysis: str | None, 每日分析的下次執行時間
        - next_csv_download: str | None, CSV 下載的下次執行時間
        - csv_last_modified: str | None, CSV 檔案的最後修改時間
    
    Example Response:
        {
            "is_running": true,
            "next_daily_analysis": "2026-01-28T12:00:00+00:00",
            "next_csv_download": "2026-01-28T15:00:00+00:00",
            "csv_last_modified": "2026-01-27T15:00:00+00:00"
        }
    """
    return {
        "is_running": scheduler_service.is_running,
        "next_daily_analysis": scheduler_service.get_next_run_time(),
        "next_csv_download": scheduler_service.get_csv_download_next_run_time(),
        "csv_last_modified": csv_downloader_service.get_last_modified()
    }

