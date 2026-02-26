"""
daily_analysis.py - 每日高機率球員分析服務

這是自動化分析的核心模組，負責：
1. 獲取當日所有賽事
2. 對每場賽事獲取所有球員的 props（4種 metric）
3. 計算博彩公司 line 的眾數作為 threshold
4. 從 CSV 歷史數據計算 over/under 機率
5. 篩選出機率 > 65% 的高價值選擇

主要函數：
- run_daily_analysis(): 執行完整的每日分析
- analyze_single_event(): 分析單場賽事
- get_player_props_for_event(): 獲取賽事中所有球員的 props

依賴：
- odds_theoddsapi: 獲取博彩數據
- csv_player_history: 計算歷史機率
- prob: 計算眾數
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from app.services.odds_theoddsapi import odds_provider
from app.services.odds_provider import OddsAPIError
from app.services.csv_player_history import csv_player_service
from app.services.prob import calculate_mode_threshold
from app.services.cache import cache_service
from app.services.projection_service import projection_service
from app.models.schemas import DailyPick, DailyPicksResponse, AnalysisStats


# 支援的市場類型（metric）
# 對應 The Odds API 的 market key
SUPPORTED_MARKETS = [
    ("player_points", "points"),      # 得分
    ("player_rebounds", "rebounds"),  # 籃板
    ("player_assists", "assists"),    # 助攻
    ("player_points_rebounds_assists", "pra"),  # PRA
]

# 高機率門檻
HIGH_PROBABILITY_THRESHOLD = 0.65

# 快取 key 前綴
DAILY_PICKS_CACHE_KEY = "daily_picks"

# 快取 TTL（6 小時）
DAILY_PICKS_CACHE_TTL = 6 * 60 * 60


class DailyAnalysisService:
    """
    每日分析服務
    
    負責執行完整的每日高機率球員分析流程
    
    使用方式：
        service = DailyAnalysisService()
        result = await service.run_daily_analysis()
    
    分析流程：
    1. 獲取今日所有 NBA 賽事
    2. 對每場賽事，獲取 4 種 metric 的所有球員 props
    3. 對每個球員-metric 組合：
       a. 收集所有博彩公司的 line
       b. 計算眾數作為 threshold
       c. 查詢 CSV 歷史數據計算機率
    4. 篩選 p_over > 0.65 或 p_under > 0.65 的結果
    5. 按機率排序返回
    """
    
    def __init__(self, probability_threshold: float = HIGH_PROBABILITY_THRESHOLD):
        """
        初始化分析服務
        
        Args:
            probability_threshold: 高機率門檻，預設 0.65（65%）
        """
        self.probability_threshold = probability_threshold
        self.csv_service = csv_player_service
    
    async def run_daily_analysis(
        self,
        date: Optional[str] = None,
        use_cache: bool = True,
        tz_offset_minutes: int = 480
    ) -> DailyPicksResponse:
        """
        執行完整的每日分析
        
        這是主要的入口函數，會執行以下步驟：
        1. 檢查快取（如果啟用）
        2. 獲取當日所有賽事
        3. 對每場賽事執行分析
        4. 篩選高機率結果
        5. 存入快取並返回
        
        Args:
            date: 分析日期（YYYY-MM-DD），None 表示今天
            use_cache: 是否使用快取，預設 True
            tz_offset_minutes: 時區偏移量（分鐘），預設 480（UTC+8 台北時間）
        
        Returns:
            DailyPicksResponse: 包含所有高機率球員的分析結果
        
        Example:
            >>> service = DailyAnalysisService()
            >>> result = await service.run_daily_analysis()
            >>> print(f"找到 {result.total_picks} 個高機率選擇")
        """
        start_time = time.time()
        
        # 確定分析日期
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        # 1. 檢查快取（包含時區偏移量，確保不同時區的結果分開快取）
        if use_cache:
            cache_key = f"{DAILY_PICKS_CACHE_KEY}:{date}:tz{tz_offset_minutes}"
            cached_data = await cache_service.get(cache_key)
            if cached_data:
                print(f"✅ 使用快取的分析結果: {date} (tz={tz_offset_minutes})")
                return DailyPicksResponse(**cached_data)
        
        print(f"🚀 開始每日分析: {date}")
        
        # 2. 獲取當日所有賽事
        try:
            events = await self._get_events_for_date(date, tz_offset_minutes)
        except Exception as e:
            print(f"❌ 獲取賽事失敗: {e}")
            return DailyPicksResponse(
                date=date,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                total_picks=0,
                picks=[],
                stats=None,
                message=f"獲取賽事失敗: {str(e)}"
            )
        
        if not events:
            print(f"⚠️ 今日無賽事: {date}")
            return DailyPicksResponse(
                date=date,
                analyzed_at=datetime.now(timezone.utc).isoformat(),
                total_picks=0,
                picks=[],
                stats=None,
                message="今日無賽事"
            )
        
        print(f"📅 找到 {len(events)} 場賽事")
        
        # 2.5. 預取投影資料（SportsDataIO）
        # 一次 API call 取得該日期所有球員的投影，
        # 之後在每場比賽分析中重複使用（不需要額外 API call）
        projections: Dict[str, Dict] = {}
        try:
            projections = await projection_service.get_projections(date)
            if projections:
                print(f"📊 取得 {len(projections)} 筆投影資料")
            else:
                print(f"ℹ️ 無投影資料可用，將只使用歷史機率分析")
        except Exception as e:
            print(f"⚠️ 取得投影資料失敗（不影響主分析流程）: {e}")
        
        # 3. 分析每場賽事
        all_picks: List[DailyPick] = []
        total_players = 0
        total_props = 0
        
        for event in events:
            event_id = event.get("id", "")
            home_team = event.get("home_team", "")
            away_team = event.get("away_team", "")
            commence_time = event.get("commence_time", "")
            
            print(f"\n🏀 分析賽事: {away_team} @ {home_team}")
            
            try:
                event_picks, players_count, props_count = await self._analyze_single_event(
                    event_id=event_id,
                    home_team=home_team,
                    away_team=away_team,
                    commence_time=commence_time,
                    projections=projections
                )
                all_picks.extend(event_picks)
                total_players += players_count
                total_props += props_count
            except Exception as e:
                print(f"⚠️ 分析賽事失敗 {event_id}: {e}")
                continue
        
        # 4. 按機率排序（高到低）
        all_picks.sort(key=lambda x: x.probability, reverse=True)
        
        # 5. 計算統計
        duration = time.time() - start_time
        stats = AnalysisStats(
            total_events=len(events),
            total_players=total_players,
            total_props=total_props,
            high_prob_count=len(all_picks),
            analysis_duration_seconds=round(duration, 2)
        )
        
        # 6. 建構回應
        response = DailyPicksResponse(
            date=date,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            total_picks=len(all_picks),
            picks=all_picks,
            stats=stats,
            message=None
        )
        
        # 7. 存入快取（包含時區偏移量）
        # 注意：即使 use_cache=False（強制重新分析），也要存入快取
        # 這樣下一次 GET 請求就能獲取最新的分析結果
        cache_key = f"{DAILY_PICKS_CACHE_KEY}:{date}:tz{tz_offset_minutes}"
        await cache_service.set(
            cache_key,
            response.model_dump(mode='json'),
            ttl=DAILY_PICKS_CACHE_TTL
        )
        
        print(f"\n✅ 分析完成！找到 {len(all_picks)} 個高機率選擇，耗時 {duration:.2f} 秒")
        
        return response
    
    async def _get_events_for_date(self, date: str, tz_offset_minutes: int = 480) -> List[Dict[str, Any]]:
        """
        獲取指定日期的所有 NBA 賽事
        
        考慮時區偏移量來正確獲取用戶本地日期的比賽
        
        Args:
            date: 日期字串（YYYY-MM-DD）
            tz_offset_minutes: 時區偏移量（分鐘），預設 480（UTC+8 台北時間）
                              正數表示東邊（如 UTC+8 = 480）
                              負數表示西邊（如 UTC-6 = -360）
        
        Returns:
            賽事列表
        """
        # 解析日期
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        
        # 計算用戶本地日期對應的 UTC 時間範圍
        # 例如：用戶在 UTC+8（台北）選擇 "2026-01-24"
        # 本地 2026-01-24 00:00:00 = UTC 2026-01-23 16:00:00
        # 本地 2026-01-24 23:59:59 = UTC 2026-01-24 15:59:59
        
        # 本地時間 00:00:00 轉換為 UTC
        local_start = datetime.combine(date_obj.date(), datetime.min.time())
        utc_start = local_start - timedelta(minutes=tz_offset_minutes)
        
        # 本地時間 23:59:59 轉換為 UTC
        from datetime import time as dt_time
        local_end = datetime.combine(date_obj.date(), dt_time(23, 59, 59))
        utc_end = local_end - timedelta(minutes=tz_offset_minutes)
        
        # 查詢範圍擴大一點以確保涵蓋邊界情況
        date_from = utc_start - timedelta(hours=1)
        date_to = utc_end + timedelta(hours=1)
        
        print(f"📅 查詢時間範圍: {date_from.isoformat()} ~ {date_to.isoformat()} (UTC)")
        
        # 呼叫 Odds API
        raw_events = await odds_provider.get_events(
            sport="basketball_nba",
            regions="us",
            date_from=date_from,
            date_to=date_to
        )
        
        # 過濾：只返回在用戶本地日期範圍內的比賽
        filtered_events = []
        for event in raw_events:
            commence_time_str = event.get("commence_time", "")
            if commence_time_str:
                try:
                    # 解析 UTC 時間（格式：2026-01-17T00:10:00Z）
                    commence_utc = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    # 轉換為用戶本地時間
                    commence_local = commence_utc + timedelta(minutes=tz_offset_minutes)
                    # 取得本地日期
                    commence_local_date = commence_local.strftime("%Y-%m-%d")
                    
                    # 只返回本地日期等於用戶選擇日期的比賽
                    if commence_local_date == date:
                        filtered_events.append(event)
                except ValueError as e:
                    print(f"⚠️ 無法解析時間 {commence_time_str}: {e}")
                    continue
        
        print(f"📊 找到 {len(raw_events)} 場賽事，過濾後 {len(filtered_events)} 場")
        
        return filtered_events
    
    async def _analyze_single_event(
        self,
        event_id: str,
        home_team: str,
        away_team: str,
        commence_time: str,
        projections: Optional[Dict[str, Dict]] = None
    ) -> Tuple[List[DailyPick], int, int]:
        """
        分析單場賽事
        
        對該場賽事的所有球員，分析 4 種 metric 的機率，
        並結合投影資料計算 Value Edge。
        
        Args:
            event_id: 賽事 ID
            home_team: 主場球隊
            away_team: 客場球隊
            commence_time: 比賽時間
            projections: 投影資料 dict（以 player_name 為 key），
                         由 run_daily_analysis 預先取得後傳入
        
        Returns:
            Tuple[List[DailyPick], int, int]: (高機率選擇列表, 球員數, prop 數)
        """
        picks: List[DailyPick] = []
        all_players: set = set()
        total_props = 0
        
        if projections is None:
            projections = {}
        
        # 對每種 metric 進行分析
        for market_key, metric_key in SUPPORTED_MARKETS:
            try:
                # 獲取該 market 的所有 props
                props_data = await self._get_props_for_market(event_id, market_key)
                
                if not props_data:
                    continue
                
                # 按球員分組
                player_props = self._group_props_by_player(props_data)
                
                for player_name, lines in player_props.items():
                    all_players.add(player_name)
                    total_props += 1
                    
                    # 計算眾數門檻
                    mode_threshold = calculate_mode_threshold(lines)
                    
                    if mode_threshold is None:
                        continue
                    
                    # 從 CSV 計算歷史機率
                    history_stats = self.csv_service.get_player_stats(
                        player_name=player_name,
                        metric=metric_key,
                        threshold=mode_threshold,
                        n=0,  # 使用全部歷史數據
                        exclude_dnp=True
                    )
                    
                    # 檢查是否有有效的機率數據
                    p_over = history_stats.get("p_over")
                    p_under = history_stats.get("p_under")
                    n_games = history_stats.get("n_games", 0)
                    
                    # 需要至少 10 場比賽的樣本
                    if n_games < 10:
                        continue
                    
                    # === 投影資料整合（Value Edge Detection）===
                    # 從預取的投影資料中查找該球員的投影
                    proj = projections.get(player_name, {})
                    has_projection = bool(proj)
                    
                    # 從投影資料優先取得球員當前球隊
                    # SportsDataIO 投影 API 的 team 欄位會即時反映季中交易，
                    # 比 CSV 歷史記錄更可靠（CSV 只記錄最近一場比賽的球隊）
                    # 投影 API 回傳縮寫格式（如 "GS", "MIL"），CSV 回傳簡短名稱（如 "Warriors", "Bucks"）
                    player_team = ""
                    if proj and proj.get("team"):
                        player_team = proj.get("team")  # 來自 SportsDataIO（縮寫如 "GS"）
                    else:
                        # Fallback: 從 CSV 歷史數據取最近一場比賽的球隊
                        game_logs = history_stats.get("game_logs", [])
                        if game_logs and len(game_logs) > 0:
                            player_team = game_logs[0].get("team", "")
                    
                    # 取得該 metric 對應的投影值
                    # metric_key 與投影欄位名稱一致（points, rebounds, assists, pra）
                    projected_value = proj.get(metric_key) if proj else None
                    projected_minutes = proj.get("minutes") if proj else None
                    opponent_rank = proj.get("opponent_rank") if proj else None
                    opponent_position_rank = proj.get("opponent_position_rank") if proj else None
                    injury_status = proj.get("injury_status") if proj else None
                    lineup_confirmed = proj.get("lineup_confirmed") if proj else None
                    
                    # 計算 Edge（投影值與盤口的差距）
                    # 正數 = 投影值高於盤口（有利 Over）
                    # 負數 = 投影值低於盤口（有利 Under）
                    edge = None
                    if projected_value is not None and mode_threshold is not None:
                        edge = round(projected_value - mode_threshold, 2)
                    
                    # 檢查是否超過機率門檻
                    if p_over is not None and p_over >= self.probability_threshold:
                        pick = DailyPick(
                            player_name=player_name,
                            player_team=player_team,
                            event_id=event_id,
                            home_team=home_team,
                            away_team=away_team,
                            commence_time=commence_time,
                            metric=metric_key,
                            threshold=mode_threshold,
                            direction="over",
                            probability=round(p_over, 4),
                            n_games=n_games,
                            bookmakers_count=len(lines),
                            all_lines=sorted(lines),
                            # 投影資料
                            has_projection=has_projection,
                            projected_value=round(projected_value, 2) if projected_value is not None else None,
                            projected_minutes=round(projected_minutes, 1) if projected_minutes is not None else None,
                            edge=edge,
                            opponent_rank=opponent_rank,
                            opponent_position_rank=opponent_position_rank,
                            injury_status=injury_status,
                            lineup_confirmed=lineup_confirmed,
                        )
                        picks.append(pick)
                        
                        # 打印包含 edge 資訊的日誌
                        edge_str = f" (edge: {edge:+.1f})" if edge is not None else ""
                        min_str = f" [{projected_minutes:.0f}min]" if projected_minutes is not None else ""
                        print(f"  ✨ {player_name} ({player_team}) {metric_key} OVER {mode_threshold}: {p_over:.1%}{edge_str}{min_str}")
                    
                    elif p_under is not None and p_under >= self.probability_threshold:
                        pick = DailyPick(
                            player_name=player_name,
                            player_team=player_team,
                            event_id=event_id,
                            home_team=home_team,
                            away_team=away_team,
                            commence_time=commence_time,
                            metric=metric_key,
                            threshold=mode_threshold,
                            direction="under",
                            probability=round(p_under, 4),
                            n_games=n_games,
                            bookmakers_count=len(lines),
                            all_lines=sorted(lines),
                            # 投影資料
                            has_projection=has_projection,
                            projected_value=round(projected_value, 2) if projected_value is not None else None,
                            projected_minutes=round(projected_minutes, 1) if projected_minutes is not None else None,
                            edge=edge,
                            opponent_rank=opponent_rank,
                            opponent_position_rank=opponent_position_rank,
                            injury_status=injury_status,
                            lineup_confirmed=lineup_confirmed,
                        )
                        picks.append(pick)
                        
                        edge_str = f" (edge: {edge:+.1f})" if edge is not None else ""
                        min_str = f" [{projected_minutes:.0f}min]" if projected_minutes is not None else ""
                        print(f"  ✨ {player_name} ({player_team}) {metric_key} UNDER {mode_threshold}: {p_under:.1%}{edge_str}{min_str}")
            
            except OddsAPIError as e:
                print(f"  ⚠️ 獲取 {market_key} 失敗: {e}")
                continue
            except Exception as e:
                print(f"  ⚠️ 分析 {market_key} 失敗: {e}")
                continue
        
        return picks, len(all_players), total_props
    
    async def _get_props_for_market(
        self,
        event_id: str,
        market: str
    ) -> List[Dict[str, Any]]:
        """
        獲取指定賽事和市場的所有 props
        
        Args:
            event_id: 賽事 ID
            market: 市場類型（如 player_points）
        
        Returns:
            博彩公司數據列表
        """
        try:
            raw_odds = await odds_provider.get_event_odds(
                sport="basketball_nba",
                event_id=event_id,
                regions="us",
                markets=market,
                odds_format="american"
            )
            
            return raw_odds.get("bookmakers", [])
        
        except OddsAPIError as e:
            if e.status_code == 404:
                # 沒有該市場的數據，不是錯誤
                return []
            raise
    
    def _group_props_by_player(
        self,
        bookmakers_data: List[Dict[str, Any]]
    ) -> Dict[str, List[float]]:
        """
        將 props 數據按球員分組
        
        從所有博彩公司的數據中，提取每個球員的 line 值
        
        Args:
            bookmakers_data: 博彩公司數據列表
        
        Returns:
            Dict[player_name, List[lines]]: 球員名稱到 line 列表的映射
        
        Example:
            輸入：
            [
                {"key": "draftkings", "markets": [{"outcomes": [...]}]},
                {"key": "fanduel", "markets": [{"outcomes": [...]}]}
            ]
            
            輸出：
            {
                "Stephen Curry": [24.5, 24.5, 25.5],
                "LeBron James": [27.5, 27.5, 28.5]
            }
        """
        player_lines: Dict[str, List[float]] = defaultdict(list)
        
        for bookmaker in bookmakers_data:
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    # description 欄位包含球員名稱
                    player_name = outcome.get("description", "")
                    # point 欄位包含 line 值
                    line = outcome.get("point")
                    
                    if player_name and line is not None:
                        player_lines[player_name].append(float(line))
        
        return dict(player_lines)


# 建立全域服務實例
daily_analysis_service = DailyAnalysisService()

