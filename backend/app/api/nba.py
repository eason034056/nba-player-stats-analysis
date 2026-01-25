"""
nba.py - NBA 相關 API 端點

包含：
1. 賽事列表 API（GET /api/nba/events）
2. 去水機率計算 API（POST /api/nba/props/no-vig）
3. 球員建議 API（GET /api/nba/players/suggest）

這是整個應用的核心功能模組
"""

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone, timedelta, time
from typing import List, Optional
from zoneinfo import ZoneInfo
from app.models.schemas import (
    EventsResponse,
    NBAEvent,
    NoVigRequest,
    NoVigResponse,
    BookmakerResult,
    Consensus,
    PlayerSuggestResponse,
    CSVPlayersResponse,
    PlayerHistoryResponse,
    HistogramBin,
    GameLog
)
from app.services.odds_theoddsapi import odds_provider
from app.services.odds_provider import OddsAPIError
from app.services.cache import cache_service, CacheService
from app.services.prob import (
    american_to_prob,
    calculate_vig,
    devig,
    calculate_consensus_mean
)
from app.services.normalize import find_player, extract_player_names
from app.services.csv_player_history import csv_player_service
from app.settings import settings

# 建立路由器
router = APIRouter(
    prefix="/api/nba",
    tags=["nba"]
)


@router.get(
    "/events",
    response_model=EventsResponse,
    summary="取得 NBA 賽事列表",
    description="取得指定日期的 NBA 賽事列表"
)
async def get_events(
    date: Optional[str] = Query(
        default=None,
        description="查詢日期（YYYY-MM-DD），預設今天",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    ),
    regions: str = Query(
        default="us",
        description="地區代碼（us, uk, eu, au）"
    ),
    tz_offset: Optional[int] = Query(
        default=None,
        description="時區偏移量（分鐘），例如 UTC-6 傳 -360，UTC+8 傳 480。用於過濾本地日期的比賽。"
    )
) -> EventsResponse:
    """
    取得 NBA 賽事列表
    
    GET /api/nba/events?date=YYYY-MM-DD&regions=us
    
    流程：
    1. 檢查 Redis 快取
    2. 若快取命中（cache hit），直接返回
    3. 若快取未命中（cache miss），呼叫 The Odds API
    4. 將結果存入快取
    5. 返回結果
    
    Args:
        date: 查詢日期（YYYY-MM-DD），預設今天
        regions: 地區代碼，影響可用的博彩公司
    
    Returns:
        EventsResponse: 賽事列表
    
    Raises:
        HTTPException: 當 API 呼叫失敗時返回對應的錯誤
    
    Example Response:
        {
            "date": "2026-01-14",
            "events": [
                {
                    "event_id": "abc123",
                    "sport_key": "basketball_nba",
                    "home_team": "Los Angeles Lakers",
                    "away_team": "Golden State Warriors",
                    "commence_time": "2026-01-15T01:00:00Z"
                }
            ]
        }
    """
    # 處理日期參數：預設今天
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # 處理時區偏移量：預設 UTC（0 分鐘）
    # 注意：JavaScript 的 getTimezoneOffset() 返回的是「UTC - 本地時間」的分鐘數
    # 例如：UTC-6 返回 360（正數），UTC+8 返回 -480（負數）
    # 但前端傳來的是正常的偏移量（UTC-6 傳 -360，UTC+8 傳 480）
    offset_minutes = tz_offset if tz_offset is not None else 0
    
    # 1. 檢查快取（包含時區偏移量以區分不同時區的請求）
    cache_key = f"{CacheService.build_events_key(date, regions)}:tz{offset_minutes}"
    cached_data = await cache_service.get(cache_key)
    
    if cached_data:
        # 快取命中
        return EventsResponse(**cached_data)
    
    # 2. 快取未命中，呼叫外部 API
    try:
        # 計算用戶本地日期對應的 UTC 時間範圍
        # 例如：用戶在 UTC-6 選擇 "2026-01-17"
        # 本地 2026-01-17 00:00:00 = UTC 2026-01-17 06:00:00
        # 本地 2026-01-17 23:59:59 = UTC 2026-01-18 05:59:59
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        
        # 本地時間 00:00:00 轉換為 UTC
        local_start = datetime.combine(date_obj.date(), datetime.min.time())
        utc_start = local_start - timedelta(minutes=offset_minutes)
        
        # 本地時間 23:59:59 轉換為 UTC（不使用 datetime.max.time() 以避免微秒）
        local_end = datetime.combine(date_obj.date(), time(23, 59, 59))
        utc_end = local_end - timedelta(minutes=offset_minutes)
        
        # 查詢範圍擴大一點以確保涵蓋邊界情況
        date_from = utc_start - timedelta(hours=1)
        date_to = utc_end + timedelta(hours=1)
        
        raw_events = await odds_provider.get_events(
            sport="basketball_nba",
            regions=regions,
            date_from=date_from,
            date_to=date_to
        )
        
        # 3. 轉換資料格式並過濾日期
        # 過濾邏輯：只返回比賽開始時間在用戶本地日期範圍內的比賽
        events = []
        for raw_event in raw_events:
            commence_time_str = raw_event.get("commence_time", "")
            
            if commence_time_str:
                # 解析 UTC 時間（格式：2026-01-17T00:10:00Z）
                try:
                    commence_utc = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    # 轉換為用戶本地時間
                    commence_local = commence_utc + timedelta(minutes=offset_minutes)
                    # 取得本地日期
                    commence_local_date = commence_local.strftime("%Y-%m-%d")
                    
                    # 只返回本地日期等於用戶選擇日期的比賽
                    if commence_local_date != date:
                        continue
                except ValueError:
                    # 無法解析時間，跳過過濾
                    pass
            
            events.append(NBAEvent(
                event_id=raw_event.get("id", ""),
                sport_key=raw_event.get("sport_key", "basketball_nba"),
                home_team=raw_event.get("home_team", ""),
                away_team=raw_event.get("away_team", ""),
                commence_time=commence_time_str
            ))
        
        # 4. 建構回應
        response = EventsResponse(
            date=date,
            events=events
        )
        
        # 5. 存入快取
        await cache_service.set(
            cache_key,
            response.model_dump(mode='json'),
            ttl=settings.cache_ttl_events
        )
        
        return response
        
    except OddsAPIError as e:
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )


@router.post(
    "/props/no-vig",
    response_model=NoVigResponse,
    summary="計算去水機率",
    description="查詢指定球員的 props 並計算去水機率"
)
async def calculate_no_vig(request: NoVigRequest) -> NoVigResponse:
    """
    計算球員 props 的去水機率
    
    POST /api/nba/props/no-vig
    
    這是整個應用的核心功能！
    
    流程：
    1. 檢查快取（以 event_id + market + regions + bookmakers 為 key）
    2. 若快取未命中，呼叫 The Odds API 取得 props 資料
    3. 在 outcomes 中搜尋指定球員（使用模糊匹配）
    4. 對每個博彩公司：
       a. 取得 line（門檻）、over_odds、under_odds
       b. 計算隱含機率（implied probability）
       c. 計算水錢（vig）
       d. 計算去水機率（fair probability）
    5. 計算市場共識（多家博彩公司的平均）
    6. 存入快取並返回
    
    Args:
        request: NoVigRequest 包含：
            - event_id: 賽事 ID
            - player_name: 球員名稱
            - market: 市場類型（預設 player_points）
            - regions: 地區代碼
            - bookmakers: 指定博彩公司（可選）
            - odds_format: 賠率格式
    
    Returns:
        NoVigResponse: 包含各博彩公司結果和市場共識
    
    Example Request:
        {
            "event_id": "abc123",
            "player_name": "Stephen Curry",
            "market": "player_points",
            "regions": "us",
            "bookmakers": ["draftkings", "fanduel"]
        }
    """
    try:
        # 1. 呼叫 The Odds API 取得 props 資料
        raw_odds = await odds_provider.get_event_odds(
            sport="basketball_nba",
            event_id=request.event_id,
            regions=request.regions,
            markets=request.market,
            odds_format=request.odds_format,
            bookmakers=request.bookmakers
        )
        
        # 2. 解析並收集所有球員名稱（用於匹配）
        all_player_names = set()
        bookmakers_data = raw_odds.get("bookmakers", [])
        
        for bookmaker in bookmakers_data:
            for market in bookmaker.get("markets", []):
                if market.get("key") == request.market:
                    for outcome in market.get("outcomes", []):
                        # outcomes 的 description 欄位包含球員名稱
                        if "description" in outcome:
                            all_player_names.add(outcome["description"])
        
        # 3. 匹配球員名稱
        matched_player = find_player(
            request.player_name,
            list(all_player_names)
        )
        
        if not matched_player:
            return NoVigResponse(
                event_id=request.event_id,
                player_name=request.player_name,
                market=request.market,
                results=[],
                consensus=None,
                message=f"找不到球員 '{request.player_name}'。可用球員：{list(all_player_names)[:10]}"
            )
        
        # 4. 對每個博彩公司計算去水機率
        results: List[BookmakerResult] = []
        fair_probs_for_consensus = []
        
        now = datetime.now(timezone.utc)
        
        for bookmaker in bookmakers_data:
            bookmaker_key = bookmaker.get("key", "unknown")
            
            for market in bookmaker.get("markets", []):
                if market.get("key") != request.market:
                    continue
                
                # 找出該球員的 Over 和 Under
                over_outcome = None
                under_outcome = None
                line = None
                
                for outcome in market.get("outcomes", []):
                    if outcome.get("description") == matched_player:
                        outcome_name = outcome.get("name", "").lower()
                        
                        if outcome_name == "over":
                            over_outcome = outcome
                            line = outcome.get("point")
                        elif outcome_name == "under":
                            under_outcome = outcome
                            if line is None:
                                line = outcome.get("point")
                
                # 需要同時有 Over 和 Under 才能計算
                if over_outcome is None or under_outcome is None or line is None:
                    continue
                
                over_odds = over_outcome.get("price", 0)
                under_odds = under_outcome.get("price", 0)
                
                if over_odds == 0 or under_odds == 0:
                    continue
                
                # 5. 計算機率
                try:
                    # 隱含機率（含水）
                    p_over_imp = american_to_prob(over_odds)
                    p_under_imp = american_to_prob(under_odds)
                    
                    # 水錢
                    vig = calculate_vig(p_over_imp, p_under_imp)
                    
                    # 去水機率
                    p_over_fair, p_under_fair = devig(p_over_imp, p_under_imp)
                    
                    # 建構結果
                    result = BookmakerResult(
                        bookmaker=bookmaker_key,
                        line=line,
                        over_odds=over_odds,
                        under_odds=under_odds,
                        p_over_imp=round(p_over_imp, 4),
                        p_under_imp=round(p_under_imp, 4),
                        vig=round(vig, 4),
                        p_over_fair=round(p_over_fair, 4),
                        p_under_fair=round(p_under_fair, 4),
                        fetched_at=now
                    )
                    results.append(result)
                    fair_probs_for_consensus.append((p_over_fair, p_under_fair))
                    
                except (ValueError, ZeroDivisionError):
                    # 計算錯誤，跳過此博彩公司
                    continue
        
        # 6. 計算市場共識
        consensus = None
        if fair_probs_for_consensus:
            consensus_probs = calculate_consensus_mean(fair_probs_for_consensus)
            if consensus_probs:
                consensus = Consensus(
                    method="mean",
                    p_over_fair=round(consensus_probs[0], 4),
                    p_under_fair=round(consensus_probs[1], 4)
                )
        
        # 7. 建構回應
        return NoVigResponse(
            event_id=request.event_id,
            player_name=matched_player,  # 使用匹配後的正確名稱
            market=request.market,
            results=results,
            consensus=consensus,
            message=None if results else "此球員在選定的博彩公司中沒有 props 資料"
        )
        
    except OddsAPIError as e:
        raise HTTPException(
            status_code=e.status_code or 500,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )


@router.get(
    "/players/suggest",
    response_model=PlayerSuggestResponse,
    summary="球員名稱建議",
    description="取得指定賽事中可用的球員列表（用於 autocomplete）"
)
async def suggest_players(
    event_id: str = Query(..., description="賽事 ID"),
    q: str = Query(default="", description="搜尋關鍵字（可選）"),
    market: str = Query(default="player_points", description="市場類型")
) -> PlayerSuggestResponse:
    """
    取得球員名稱建議（用於 Autocomplete）
    
    GET /api/nba/players/suggest?event_id=abc123&q=cur
    
    流程：
    1. 檢查快取
    2. 若快取未命中，呼叫 The Odds API 取得該場比賽的 props
    3. 從 outcomes 中提取所有球員名稱
    4. 若有搜尋關鍵字，進行過濾
    5. 存入快取並返回
    
    Args:
        event_id: 賽事 ID
        q: 搜尋關鍵字（用於過濾）
        market: 市場類型
    
    Returns:
        PlayerSuggestResponse: 球員名稱列表
    
    Example Response:
        {
            "players": ["Stephen Curry", "Seth Curry", "LeBron James"]
        }
    """
    # 1. 檢查快取
    cache_key = CacheService.build_players_key(event_id)
    cached_data = await cache_service.get(cache_key)
    
    all_players: List[str] = []
    
    if cached_data:
        all_players = cached_data.get("players", [])
    else:
        # 2. 快取未命中，呼叫 API
        try:
            raw_odds = await odds_provider.get_event_odds(
                sport="basketball_nba",
                event_id=event_id,
                regions="us",
                markets=market,
                odds_format="american"
            )
            
            # 3. 提取球員名稱
            player_set = set()
            for bookmaker in raw_odds.get("bookmakers", []):
                for mkt in bookmaker.get("markets", []):
                    if mkt.get("key") == market:
                        for outcome in mkt.get("outcomes", []):
                            if "description" in outcome:
                                player_set.add(outcome["description"])
            
            all_players = sorted(list(player_set))
            
            # 4. 存入快取
            await cache_service.set(
                cache_key,
                {"players": all_players},
                ttl=settings.cache_ttl_players
            )
            
        except OddsAPIError as e:
            raise HTTPException(
                status_code=e.status_code or 500,
                detail=str(e)
            )
    
    # 5. 過濾（如果有搜尋關鍵字）
    if q:
        q_lower = q.lower()
        all_players = [p for p in all_players if q_lower in p.lower()]
    
    return PlayerSuggestResponse(players=all_players)


# ==================== CSV 球員歷史數據 API ====================

@router.get(
    "/csv/players",
    response_model=CSVPlayersResponse,
    summary="取得 CSV 球員名單",
    description="從 CSV 檔案中取得所有球員名單（用於 autocomplete）"
)
async def get_csv_players(
    q: str = Query(default="", description="搜尋關鍵字（可選）")
) -> CSVPlayersResponse:
    """
    取得 CSV 檔案中的球員名單
    
    GET /api/nba/csv/players?q=curry
    
    此端點從 data/nba_player_game_logs.csv 讀取球員名單
    用於前端球員選擇器的 autocomplete 功能
    
    Args:
        q: 搜尋關鍵字（不區分大小寫）
    
    Returns:
        CSVPlayersResponse: 球員名稱列表
    
    Example Response:
        {
            "players": ["Stephen Curry", "Seth Curry"],
            "total": 2
        }
    """
    try:
        players = csv_player_service.get_all_players(search=q if q else None)
        return CSVPlayersResponse(
            players=players,
            total=len(players)
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"讀取 CSV 失敗: {str(e)}"
        )


@router.post(
    "/csv/reload",
    summary="重新載入 CSV 資料",
    description="強制清除快取並重新讀取 CSV 檔案"
)
async def reload_csv():
    """
    強制重新載入 CSV 資料
    
    用於：
    - CSV 檔案更新後刷新數據
    - 修改程式碼後清除快取
    
    POST /api/nba/csv/reload
    
    Returns:
        dict: 重新載入結果，包含球員數量
    """
    try:
        csv_player_service.reload()
        return {
            "success": True,
            "message": "CSV 資料已重新載入",
            "total_players": len(csv_player_service.get_all_players())
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"重新載入失敗: {str(e)}"
        )


@router.get(
    "/player-history",
    response_model=PlayerHistoryResponse,
    summary="取得球員歷史數據統計",
    description="計算球員在指定指標上的歷史經驗機率和分佈"
)
async def get_player_history(
    player: str = Query(..., description="球員名稱"),
    metric: str = Query(
        default="points",
        description="統計指標：points（得分）、assists（助攻）、rebounds（籃板）、pra（得分+籃板+助攻）"
    ),
    threshold: float = Query(..., description="閾值（例如 24.5）"),
    n: int = Query(
        default=0,
        ge=0,
        description="最近 N 場比賽，0 表示全部"
    ),
    bins: int = Query(
        default=15,
        ge=5,
        le=50,
        description="直方圖分箱數（5-50）"
    ),
    exclude_dnp: bool = Query(
        default=True,
        description="是否排除 DNP（Did Not Play，分鐘數為 0 的場次）"
    ),
    opponent: Optional[str] = Query(
        default=None,
        description="對手篩選（球隊名稱），None 表示全部對手"
    )
) -> PlayerHistoryResponse:
    """
    取得球員歷史數據統計
    
    GET /api/nba/player-history?player=Stephen+Curry&metric=points&threshold=24.5
    GET /api/nba/player-history?player=Stephen+Curry&metric=points&threshold=24.5&opponent=Lakers
    
    此端點計算球員在指定指標上的「經驗機率」（empirical probability）
    這是基於歷史數據的統計，不是模型預測！
    
    機率定義（符合運彩 props 直覺）：
    - Over: value > threshold（嚴格大於）
    - Under: value < threshold（嚴格小於）
    - 若 value == threshold，則不計入 Over 也不計入 Under
    
    Args:
        player: 球員名稱
        metric: 統計指標（points/assists/rebounds/pra）
        threshold: 閾值（可以是小數，如 24.5）
        n: 最近 N 場比賽（0 表示使用全部歷史資料）
        bins: 直方圖分箱數
        exclude_dnp: 是否排除 DNP 場次
        opponent: 對手篩選（可選）
    
    Returns:
        PlayerHistoryResponse: 包含機率、平均值、標準差、game_logs、對手列表
    
    Example Response:
        {
            "player": "Stephen Curry",
            "metric": "points",
            "threshold": 24.5,
            "n_games": 68,
            "p_over": 0.47,
            "p_under": 0.53,
            "mean": 25.1,
            "std": 5.7,
            "game_logs": [
                {"date": "01/15", "opponent": "Lakers", "value": 28, "is_over": true},
                ...
            ],
            "opponents": ["Lakers", "Celtics", ...],
            "histogram": [...]
        }
    """
    # 驗證 metric 參數
    valid_metrics = ["points", "assists", "rebounds", "pra"]
    if metric not in valid_metrics:
        raise HTTPException(
            status_code=400,
            detail=f"無效的 metric: {metric}。有效值: {valid_metrics}"
        )
    
    try:
        # 呼叫 CSV 服務計算統計
        stats = csv_player_service.get_player_stats(
            player_name=player,
            metric=metric,
            threshold=threshold,
            n=n,
            bins=bins,
            exclude_dnp=exclude_dnp,
            opponent=opponent
        )
        
        # 轉換 histogram 為 Pydantic 模型
        histogram_bins = [
            HistogramBin(
                binStart=bin_data["binStart"],
                binEnd=bin_data["binEnd"],
                count=bin_data["count"]
            )
            for bin_data in stats.get("histogram", [])
        ]
        
        # 轉換 game_logs 為 Pydantic 模型
        game_logs = [
            GameLog(
                date=log["date"],
                date_full=log["date_full"],
                opponent=log["opponent"],
                value=log["value"],
                is_over=log["is_over"],
                team=log.get("team", ""),
                minutes=log.get("minutes", 0.0),  # 上場時間
                is_starter=log.get("is_starter", False)  # 是否先發
            )
            for log in stats.get("game_logs", [])
        ]
        
        return PlayerHistoryResponse(
            player=stats["player"],
            metric=stats["metric"],
            threshold=stats["threshold"],
            n_games=stats["n_games"],
            p_over=stats["p_over"],
            p_under=stats["p_under"],
            equal_count=stats.get("equal_count", 0),
            mean=stats["mean"],
            std=stats["std"],
            histogram=histogram_bins,
            game_logs=game_logs,
            opponents=stats.get("opponents", []),
            opponent_filter=stats.get("opponent_filter"),
            message=stats.get("message")
        )
        
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"計算失敗: {str(e)}"
        )

