"""
projections.py - 投影資料 API 端點

提供球員投影資料的 REST API，供前端查詢和手動操作。

端點：
- GET  /api/nba/projections          - 取得指定日期所有球員投影
- GET  /api/nba/projections/{player} - 取得單一球員投影
- POST /api/nba/projections/refresh  - 手動刷新投影資料

資料來源：
    SportsDataIO Projected Player Game Stats API
    透過 projection_service 的混合取得策略（Redis + PostgreSQL）

使用方式：
    # 取得今日所有球員投影
    GET /api/nba/projections?date=2026-02-08
    
    # 取得特定球員投影
    GET /api/nba/projections/Stephen Curry?date=2026-02-08
    
    # 手動刷新（強制重新呼叫 API）
    POST /api/nba/projections/refresh?date=2026-02-08
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.projection_service import projection_service
from app.services.projection_provider import SportsDataProjectionError
from app.models.schemas import (
    PlayerProjection,
    ProjectionsResponse,
    ProjectionRefreshResponse,
)


# 建立路由器
# prefix: 所有端點都以 /api/nba/projections 開頭
# tags: 在 Swagger 文件中的分組標籤
router = APIRouter(
    prefix="/api/nba/projections",
    tags=["projections"],
)


@router.get(
    "",
    response_model=ProjectionsResponse,
    summary="取得投影資料",
    description="""
    取得指定日期所有球員的投影資料。
    
    使用混合取得策略：
    1. 優先從 Redis 快取讀取
    2. 快取過期時觸發背景刷新
    3. 快取未命中時同步呼叫 SportsDataIO API
    
    **注意**：Free Trial 版本的 InjuryStatus / LineupStatus 會是 null。
    """
)
async def get_projections(
    date: Optional[str] = Query(
        default=None,
        description="查詢日期（YYYY-MM-DD），預設今天"
    ),
):
    """
    取得指定日期的所有球員投影資料
    
    Args:
        date: 比賽日期，格式 YYYY-MM-DD。
              不提供時使用 UTC 當天日期。
    
    Returns:
        ProjectionsResponse: 包含所有球員投影的回應
    
    Example:
        GET /api/nba/projections?date=2026-02-08
    """
    # 預設使用 UTC 當天
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    try:
        projections_dict = await projection_service.get_projections(date)
    except SportsDataProjectionError as e:
        raise HTTPException(
            status_code=502,
            detail=f"SportsDataIO API 錯誤: {e.message}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"取得投影資料失敗: {str(e)}"
        )
    
    # 將 dict 轉為 PlayerProjection 列表
    projections_list = []
    for player_name, proj_data in projections_dict.items():
        try:
            projection = PlayerProjection(
                player_id=proj_data.get("player_id"),
                player_name=player_name,
                team=proj_data.get("team"),
                position=proj_data.get("position"),
                opponent=proj_data.get("opponent"),
                home_or_away=proj_data.get("home_or_away"),
                minutes=proj_data.get("minutes"),
                points=proj_data.get("points"),
                rebounds=proj_data.get("rebounds"),
                assists=proj_data.get("assists"),
                steals=proj_data.get("steals"),
                blocked_shots=proj_data.get("blocked_shots"),
                turnovers=proj_data.get("turnovers"),
                pra=proj_data.get("pra"),
                field_goals_made=proj_data.get("field_goals_made"),
                field_goals_attempted=proj_data.get("field_goals_attempted"),
                three_pointers_made=proj_data.get("three_pointers_made"),
                three_pointers_attempted=proj_data.get("three_pointers_attempted"),
                free_throws_made=proj_data.get("free_throws_made"),
                free_throws_attempted=proj_data.get("free_throws_attempted"),
                started=proj_data.get("started"),
                lineup_confirmed=proj_data.get("lineup_confirmed"),
                injury_status=proj_data.get("injury_status"),
                injury_body_part=proj_data.get("injury_body_part"),
                opponent_rank=proj_data.get("opponent_rank"),
                opponent_position_rank=proj_data.get("opponent_position_rank"),
                draftkings_salary=proj_data.get("draftkings_salary"),
                fanduel_salary=proj_data.get("fanduel_salary"),
                fantasy_points_dk=proj_data.get("fantasy_points_dk"),
                fantasy_points_fd=proj_data.get("fantasy_points_fd"),
                usage_rate_percentage=proj_data.get("usage_rate_percentage"),
                player_efficiency_rating=proj_data.get("player_efficiency_rating"),
            )
            projections_list.append(projection)
        except Exception as e:
            # 單個球員資料格式有問題不影響整體
            print(f"⚠️ 球員投影資料格式錯誤 ({player_name}): {e}")
            continue
    
    # 按球員名稱排序
    projections_list.sort(key=lambda p: p.player_name)
    
    return ProjectionsResponse(
        date=date,
        player_count=len(projections_list),
        fetched_at=datetime.now(timezone.utc).isoformat(),
        projections=projections_list,
    )


@router.get(
    "/{player_name}",
    response_model=PlayerProjection,
    summary="取得單一球員投影",
    description="取得指定球員在指定日期的投影資料。"
)
async def get_player_projection(
    player_name: str,
    date: Optional[str] = Query(
        default=None,
        description="查詢日期（YYYY-MM-DD），預設今天"
    ),
):
    """
    取得單一球員的投影資料
    
    Args:
        player_name: 球員名稱（URL path 參數）
        date: 比賽日期
    
    Returns:
        PlayerProjection: 球員投影資料
    
    Raises:
        404: 找不到該球員的投影資料
    
    Example:
        GET /api/nba/projections/Stephen%20Curry?date=2026-02-08
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    try:
        proj = await projection_service.get_player_projection(date, player_name)
    except SportsDataProjectionError as e:
        raise HTTPException(
            status_code=502,
            detail=f"SportsDataIO API 錯誤: {e.message}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"取得投影資料失敗: {str(e)}"
        )
    
    if proj is None:
        raise HTTPException(
            status_code=404,
            detail=f"找不到 {player_name} 在 {date} 的投影資料"
        )
    
    return PlayerProjection(
        player_id=proj.get("player_id"),
        player_name=player_name,
        team=proj.get("team"),
        position=proj.get("position"),
        opponent=proj.get("opponent"),
        home_or_away=proj.get("home_or_away"),
        minutes=proj.get("minutes"),
        points=proj.get("points"),
        rebounds=proj.get("rebounds"),
        assists=proj.get("assists"),
        steals=proj.get("steals"),
        blocked_shots=proj.get("blocked_shots"),
        turnovers=proj.get("turnovers"),
        pra=proj.get("pra"),
        field_goals_made=proj.get("field_goals_made"),
        field_goals_attempted=proj.get("field_goals_attempted"),
        three_pointers_made=proj.get("three_pointers_made"),
        three_pointers_attempted=proj.get("three_pointers_attempted"),
        free_throws_made=proj.get("free_throws_made"),
        free_throws_attempted=proj.get("free_throws_attempted"),
        started=proj.get("started"),
        lineup_confirmed=proj.get("lineup_confirmed"),
        injury_status=proj.get("injury_status"),
        injury_body_part=proj.get("injury_body_part"),
        opponent_rank=proj.get("opponent_rank"),
        opponent_position_rank=proj.get("opponent_position_rank"),
        draftkings_salary=proj.get("draftkings_salary"),
        fanduel_salary=proj.get("fanduel_salary"),
        fantasy_points_dk=proj.get("fantasy_points_dk"),
        fantasy_points_fd=proj.get("fantasy_points_fd"),
        usage_rate_percentage=proj.get("usage_rate_percentage"),
        player_efficiency_rating=proj.get("player_efficiency_rating"),
    )


@router.post(
    "/refresh",
    response_model=ProjectionRefreshResponse,
    summary="手動刷新投影資料",
    description="""
    強制重新呼叫 SportsDataIO API 並更新快取和資料庫。
    
    通常用於：
    - 排程器之外的手動更新
    - 確認最新的陣容變化
    - 除錯
    """
)
async def refresh_projections(
    date: Optional[str] = Query(
        default=None,
        description="刷新日期（YYYY-MM-DD），預設今天"
    ),
):
    """
    手動觸發投影資料刷新
    
    直接呼叫 SportsDataIO API，更新 Redis 和 PostgreSQL。
    
    Args:
        date: 比賽日期
    
    Returns:
        ProjectionRefreshResponse: 刷新結果
    
    Example:
        POST /api/nba/projections/refresh?date=2026-02-08
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    try:
        projections = await projection_service.fetch_and_store(date)
        
        return ProjectionRefreshResponse(
            date=date,
            player_count=len(projections),
            message=f"成功刷新 {len(projections)} 筆投影資料"
        )
    
    except SportsDataProjectionError as e:
        raise HTTPException(
            status_code=502,
            detail=f"SportsDataIO API 錯誤: {e.message}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"刷新投影資料失敗: {str(e)}"
        )
