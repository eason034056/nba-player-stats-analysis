"""
odds_history.py - 盤口歷史 API 端點

提供盤口快照資料的查詢和手動觸發功能，用於 Line Movement Tracking。

端點：
- GET  /api/nba/odds-history          - 查詢球員/market 的盤口歷史快照
- POST /api/nba/odds-history/snapshot  - 手動觸發一次盤口快照

資料來源：
    odds_line_snapshots 表（由 odds_snapshot_service 定期寫入）

使用方式：
    # 查詢 Stephen Curry 在 2026-02-08 的 player_points 盤口變動
    GET /api/nba/odds-history?player_name=Stephen Curry&market=player_points&date=2026-02-08

    # 手動觸發今日快照
    POST /api/nba/odds-history/snapshot?date=2026-02-08
"""

from datetime import datetime, timezone
from typing import Optional, Dict, List
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query

from app.services.db import db_service
from app.services.odds_snapshot_service import odds_snapshot_service
from app.models.schemas import (
    OddsLineSnapshot,
    OddsConsensus,
    OddsSnapshotGroup,
    OddsHistoryResponse,
    OddsSnapshotTriggerResponse,
)


# 建立路由器
# prefix: 所有端點都以 /api/nba/odds-history 開頭
# tags: 在 Swagger 文件中的分組標籤
router = APIRouter(
    prefix="/api/nba/odds-history",
    tags=["odds-history"],
)


# 查詢 SQL：取得指定球員/market/日期的所有快照資料
# 按 snapshot_at 和 bookmaker 排序，方便後續按時間分組
QUERY_HISTORY_SQL = """
SELECT
    snapshot_at,
    bookmaker,
    line,
    over_odds,
    under_odds,
    vig,
    over_fair_prob,
    under_fair_prob
FROM odds_line_snapshots
WHERE player_name = $1
  AND market = $2
  AND date = $3
ORDER BY snapshot_at ASC, bookmaker ASC
"""


@router.get(
    "",
    response_model=OddsHistoryResponse,
    summary="查詢盤口歷史",
    description="""
    查詢指定球員在指定 market 和日期的所有盤口快照。

    回傳按時間排序的快照列表，每個快照包含：
    - 各博彩公司的盤口線、賠率、no-vig 機率
    - 市場共識（所有博彩公司的去水機率平均）

    用於 Line Movement Tracking：觀察盤口從開盤到封盤的變化。
    """
)
async def get_odds_history(
    player_name: str = Query(
        ...,
        description="球員名稱（如 Stephen Curry）"
    ),
    market: str = Query(
        ...,
        description="市場類型（player_points, player_rebounds, player_assists, player_points_rebounds_assists）"
    ),
    date: Optional[str] = Query(
        default=None,
        description="比賽日期（YYYY-MM-DD），預設今天"
    ),
):
    """
    查詢盤口歷史快照

    從 odds_line_snapshots 表查詢指定球員/market/日期的所有快照，
    按 snapshot_at 分組，每組內包含各 bookmaker 的 no-vig 結果。
    Consensus 在查詢時即時計算（AVG），不另外儲存。

    Args:
        player_name: 球員名稱（必填）
        market: 市場類型（必填）
        date: 比賽日期，預設 UTC 今天

    Returns:
        OddsHistoryResponse: 包含按時間排序的快照列表

    Example:
        GET /api/nba/odds-history?player_name=Stephen Curry&market=player_points&date=2026-02-08
    """
    if not db_service.is_connected:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL 未連線，無法查詢盤口歷史"
        )

    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 驗證 market
    valid_markets = [
        "player_points", "player_rebounds",
        "player_assists", "player_points_rebounds_assists",
    ]
    if market not in valid_markets:
        raise HTTPException(
            status_code=400,
            detail=f"無效的 market: {market}。有效值: {valid_markets}"
        )

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        rows = await db_service.fetch(QUERY_HISTORY_SQL, player_name, market, date_obj)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"查詢盤口歷史失敗: {str(e)}"
        )

    # 按 snapshot_at 分組
    # defaultdict(list): 自動為新 key 建立空 list
    # 把同一時間的所有 bookmaker rows 分在同一組
    groups: Dict[str, list] = defaultdict(list)
    for row in rows:
        # snapshot_at 可能是 datetime 物件，轉為 ISO 字串作為 key
        snap_time = row["snapshot_at"]
        if isinstance(snap_time, datetime):
            snap_key = snap_time.isoformat()
        else:
            snap_key = str(snap_time)

        groups[snap_key].append(row)

    # 建構回應
    snapshots: List[OddsSnapshotGroup] = []

    for snap_key, group_rows in groups.items():
        # 各 bookmaker 的盤口資料
        lines = [
            OddsLineSnapshot(
                bookmaker=r["bookmaker"],
                line=float(r["line"]) if r["line"] is not None else None,
                over_odds=int(r["over_odds"]) if r["over_odds"] is not None else None,
                under_odds=int(r["under_odds"]) if r["under_odds"] is not None else None,
                vig=float(r["vig"]) if r["vig"] is not None else None,
                over_fair_prob=float(r["over_fair_prob"]) if r["over_fair_prob"] is not None else None,
                under_fair_prob=float(r["under_fair_prob"]) if r["under_fair_prob"] is not None else None,
            )
            for r in group_rows
        ]

        # 計算 consensus（去水機率平均值）
        # 只納入有 over_fair_prob 和 under_fair_prob 的 rows
        valid_probs = [
            r for r in group_rows
            if r["over_fair_prob"] is not None and r["under_fair_prob"] is not None
        ]

        consensus = None
        if valid_probs:
            n = len(valid_probs)
            avg_over = sum(float(r["over_fair_prob"]) for r in valid_probs) / n
            avg_under = sum(float(r["under_fair_prob"]) for r in valid_probs) / n

            # 平均盤口線
            valid_lines = [float(r["line"]) for r in valid_probs if r["line"] is not None]
            avg_line = sum(valid_lines) / len(valid_lines) if valid_lines else None

            consensus = OddsConsensus(
                over_fair_prob=round(avg_over, 4),
                under_fair_prob=round(avg_under, 4),
                avg_line=round(avg_line, 2) if avg_line is not None else None,
                bookmaker_count=n,
            )

        snapshots.append(
            OddsSnapshotGroup(
                snapshot_at=snap_key,
                lines=lines,
                consensus=consensus,
            )
        )

    return OddsHistoryResponse(
        date=date,
        player_name=player_name,
        market=market,
        snapshot_count=len(snapshots),
        snapshots=snapshots,
    )


@router.post(
    "/snapshot",
    response_model=OddsSnapshotTriggerResponse,
    summary="手動觸發盤口快照",
    description="""
    手動觸發一次盤口快照，立即擷取所有賽事的盤口資料並寫入 PostgreSQL。

    通常用於：
    - 排程器之外的手動更新
    - 測試快照功能
    - 在特定時間點（如大傷病消息後）捕捉盤口變化
    """
)
async def trigger_snapshot(
    date: Optional[str] = Query(
        default=None,
        description="快照日期（YYYY-MM-DD），預設今天"
    ),
):
    """
    手動觸發盤口快照

    直接呼叫 odds_snapshot_service.take_snapshot()，
    擷取所有賽事的賠率、計算 no-vig、寫入 PostgreSQL。

    Args:
        date: 快照日期，預設 UTC 今天

    Returns:
        OddsSnapshotTriggerResponse: 快照執行結果摘要
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        result = await odds_snapshot_service.take_snapshot(date)

        return OddsSnapshotTriggerResponse(
            date=result["date"],
            event_count=result["event_count"],
            total_lines=result["total_lines"],
            duration_ms=result["duration_ms"],
            message=(
                f"成功擷取 {result['total_lines']} 筆盤口資料 "
                f"（{result['event_count']} 場賽事，耗時 {result['duration_ms']}ms）"
            ),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"盤口快照失敗: {str(e)}"
        )
