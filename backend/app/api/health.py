"""
health.py - 健康檢查 API 端點

提供服務健康狀態檢查功能
用途：
1. 部署時確認服務正常啟動
2. 負載均衡器（Load Balancer）定期檢查
3. 監控系統偵測服務狀態
"""

from fastapi import APIRouter
from datetime import datetime, timezone
from app.models.schemas import HealthResponse

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

