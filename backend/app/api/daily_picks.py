"""
daily_picks.py - 每日高機率球員 API 端點

提供以下端點：
1. GET /api/nba/daily-picks - 獲取當日高機率球員列表
2. POST /api/nba/daily-picks/trigger - 手動觸發分析（開發/管理用）

這些端點讓前端可以：
- 獲取已分析的高機率球員數據
- 在需要時手動觸發重新分析
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from datetime import datetime, timezone
from typing import Optional

from app.models.schemas import DailyPicksResponse
from app.services.daily_analysis import daily_analysis_service
from app.services.cache import cache_service


# 建立路由器
# prefix: 所有路由都會加上 /api/nba 前綴
# tags: 用於 API 文檔分類
router = APIRouter(
    prefix="/api/nba",
    tags=["daily-picks"]
)


@router.get(
    "/daily-picks",
    response_model=DailyPicksResponse,
    summary="取得每日高機率球員",
    description="取得指定日期發生機率超過 65% 的球員投注選擇"
)
async def get_daily_picks(
    date: Optional[str] = Query(
        default=None,
        description="查詢日期（YYYY-MM-DD），預設今天",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description="時區偏移量（分鐘），例如 UTC+8 傳 480，UTC-6 傳 -360"
    ),
    refresh: bool = Query(
        default=False,
        description="是否強制重新分析（忽略快取）"
    ),
    min_probability: float = Query(
        default=0.65,
        ge=0.5,
        le=0.95,
        description="最低機率門檻（0.5-0.95）"
    ),
    min_games: int = Query(
        default=10,
        ge=5,
        le=100,
        description="最少樣本場次（5-100）"
    )
) -> DailyPicksResponse:
    """
    取得每日高機率球員
    
    GET /api/nba/daily-picks?date=2026-01-24
    GET /api/nba/daily-picks?refresh=true  # 強制重新分析
    
    此端點返回當日所有發生機率超過門檻的球員投注選擇。
    分析流程：
    1. 獲取當日所有 NBA 賽事
    2. 對每場賽事，獲取所有球員的 props（得分、籃板、助攻、PRA）
    3. 計算博彩公司 line 的眾數作為門檻
    4. 從歷史數據計算 over/under 機率
    5. 篩選機率超過門檻的結果
    
    Args:
        date: 查詢日期（YYYY-MM-DD），預設今天
        refresh: 是否強制重新分析
        min_probability: 最低機率門檻
        min_games: 最少樣本場次
    
    Returns:
        DailyPicksResponse: 高機率球員列表
    
    Example Response:
        {
            "date": "2026-01-24",
            "analyzed_at": "2026-01-24T12:00:00Z",
            "total_picks": 15,
            "picks": [
                {
                    "player_name": "Stephen Curry",
                    "event_id": "abc123",
                    "home_team": "Warriors",
                    "away_team": "Lakers",
                    "metric": "points",
                    "threshold": 24.5,
                    "direction": "over",
                    "probability": 0.73,
                    "n_games": 68
                }
            ],
            "stats": {...}
        }
    """
    # 確定查詢日期
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # 時區偏移量預設為 UTC+8（台北時間）
    offset_minutes = tz_offset if tz_offset is not None else 480
    
    try:
        # 執行分析（會自動使用快取，除非 refresh=True）
        result = await daily_analysis_service.run_daily_analysis(
            date=date,
            use_cache=not refresh,
            tz_offset_minutes=offset_minutes
        )
        
        # 根據參數過濾結果
        if result.picks:
            filtered_picks = [
                pick for pick in result.picks
                if pick.probability >= min_probability
                and pick.n_games >= min_games
            ]
            result.picks = filtered_picks
            result.total_picks = len(filtered_picks)
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"分析失敗: {str(e)}"
        )


@router.post(
    "/daily-picks/trigger",
    response_model=DailyPicksResponse,
    summary="手動觸發每日分析",
    description="手動觸發重新分析（開發/管理用途）"
)
async def trigger_daily_analysis(
    date: Optional[str] = Query(
        default=None,
        description="分析日期（YYYY-MM-DD），預設今天",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description="時區偏移量（分鐘），例如 UTC+8 傳 480"
    )
) -> DailyPicksResponse:
    """
    手動觸發每日分析
    
    POST /api/nba/daily-picks/trigger?date=2026-01-24
    
    此端點用於手動觸發重新分析，會忽略快取。
    主要用於：
    - 開發測試
    - 管理員需要強制更新數據
    - 定時任務呼叫
    
    Args:
        date: 分析日期（YYYY-MM-DD），預設今天
        tz_offset: 時區偏移量（分鐘）
    
    Returns:
        DailyPicksResponse: 新的分析結果
    """
    # 確定分析日期
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # 時區偏移量預設為 UTC+8（台北時間）
    offset_minutes = tz_offset if tz_offset is not None else 480
    
    try:
        # 強制重新分析（不使用快取）
        result = await daily_analysis_service.run_daily_analysis(
            date=date,
            use_cache=False,
            tz_offset_minutes=offset_minutes
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"分析失敗: {str(e)}"
        )


@router.delete(
    "/daily-picks/cache",
    summary="清除分析快取",
    description="清除指定日期的分析快取"
)
async def clear_daily_picks_cache(
    date: Optional[str] = Query(
        default=None,
        description="要清除的日期（YYYY-MM-DD），預設今天",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description="時區偏移量（分鐘），例如 UTC+8 傳 480"
    )
) -> dict:
    """
    清除每日分析快取
    
    DELETE /api/nba/daily-picks/cache?date=2026-01-24
    
    Args:
        date: 要清除的日期
        tz_offset: 時區偏移量
    
    Returns:
        {"success": True, "message": "..."}
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # 時區偏移量預設為 UTC+8
    offset_minutes = tz_offset if tz_offset is not None else 480
    
    # 清除新格式的快取 key
    cache_key_new = f"daily_picks:{date}:tz{offset_minutes}"
    # 也清除舊格式的快取 key（向下兼容）
    cache_key_old = f"daily_picks:{date}"
    
    try:
        await cache_service.delete(cache_key_new)
        await cache_service.delete(cache_key_old)
        return {
            "success": True,
            "message": f"已清除 {date} 的分析快取"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"清除快取失敗: {str(e)}"
        )

