"""
odds_snapshot_service.py - 盤口快照服務

定期擷取 The Odds API 的賠率資料，計算 no-vig，並寫入 PostgreSQL。
用於 Line Movement Tracking（盤口變動追蹤）。

架構：
    排程器 → take_snapshot(date)
            → odds_provider.get_events()           (1 API call)
            → odds_provider.get_event_odds(...)     (N API calls, 4 markets batched)
            → prob.py 計算 no-vig
            → db_service.executemany()              (bulk write to PostgreSQL)
            → _log_snapshot()                       (寫入 odds_snapshot_logs)

每次快照會：
1. 取得當天所有 NBA 賽事
2. 對每場賽事，用一次 API call 同時取得 4 個 market 的賠率
3. 對每個 bookmaker / player / market 組合計算 no-vig
4. 批量寫入 odds_line_snapshots 表
5. 記錄快照日誌

使用方式：
    from app.services.odds_snapshot_service import odds_snapshot_service

    # 排程器呼叫
    result = await odds_snapshot_service.take_snapshot("2026-02-08")

    # 手動觸發
    result = await odds_snapshot_service.take_snapshot()
"""

import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

from app.services.odds_theoddsapi import odds_provider
from app.services.odds_provider import OddsAPIError
from app.services.prob import american_to_prob, calculate_vig, devig
from app.services.db import db_service


# 支援的市場類型（逗號分隔，用於一次 API call 取得多個 market）
# The Odds API v4 支援 comma-separated markets 參數
SNAPSHOT_MARKETS = "player_points,player_rebounds,player_assists,player_points_rebounds_assists"

# UPSERT SQL：插入新資料，若已存在則更新
# ON CONFLICT 使用 unique constraint (snapshot_at, event_id, player_name, market, bookmaker)
# 確保同一次快照不會重複寫入相同的 bookmaker/player/market
UPSERT_LINE_SQL = """
INSERT INTO odds_line_snapshots (
    snapshot_at, date, event_id, home_team, away_team,
    player_name, market, bookmaker,
    line, over_odds, under_odds,
    vig, over_fair_prob, under_fair_prob
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8,
    $9, $10, $11,
    $12, $13, $14
)
ON CONFLICT (snapshot_at, event_id, player_name, market, bookmaker)
DO UPDATE SET
    line = EXCLUDED.line,
    over_odds = EXCLUDED.over_odds,
    under_odds = EXCLUDED.under_odds,
    vig = EXCLUDED.vig,
    over_fair_prob = EXCLUDED.over_fair_prob,
    under_fair_prob = EXCLUDED.under_fair_prob
"""

# 快照日誌 INSERT SQL
INSERT_LOG_SQL = """
INSERT INTO odds_snapshot_logs (
    date, snapshot_at, event_count, total_lines, status, error_message, duration_ms
) VALUES ($1, $2, $3, $4, $5, $6, $7)
"""


class OddsSnapshotService:
    """
    盤口快照服務

    負責定期擷取所有賽事的賠率資料、計算 no-vig、寫入 PostgreSQL。
    每天排程 3 次快照（UTC 16:00, 22:00, 23:30），
    分別對應美東 11AM、5PM、6:30PM，涵蓋開盤 → 封盤的時段。

    使用方式：
        service = OddsSnapshotService()
        result = await service.take_snapshot("2026-02-08")
    """

    async def take_snapshot(
        self,
        date: Optional[str] = None,
        tz_offset_minutes: int = 480
    ) -> Dict[str, Any]:
        """
        執行一次完整的盤口快照

        主流程：
        1. 取得該日期的所有 NBA 賽事
        2. 對每場賽事取得所有 market 的賠率（4 markets in 1 call）
        3. 計算每個 bookmaker/player/market 的 no-vig
        4. 批量寫入 PostgreSQL
        5. 記錄快照日誌

        叫 "take_snapshot" 因為就像相機「拍攝快照」—
        記錄某一瞬間所有賠率的狀態。

        Args:
            date: 比賽日期（YYYY-MM-DD），None 則使用 UTC 今天
            tz_offset_minutes: 時區偏移量（分鐘），用於取得正確的當地日期賽事，
                               預設 480（UTC+8 台北時間）

        Returns:
            dict 包含：
            - date: 快照日期
            - event_count: 處理的賽事數
            - total_lines: 寫入的 odds line 總筆數
            - duration_ms: 耗時（毫秒）
        """
        start_time = time.time()

        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        snapshot_at = datetime.now(timezone.utc)
        total_lines = 0
        event_count = 0
        all_rows: List[tuple] = []

        try:
            # 1. 取得當天所有賽事
            events = await self._get_events(date, tz_offset_minutes)
            event_count = len(events)

            if not events:
                print(f"⚠️ [OddsSnapshot] {date} 無賽事")
                await self._log_snapshot(
                    date, snapshot_at, 0, 0, "success", "無賽事", 0
                )
                return {
                    "date": date,
                    "event_count": 0,
                    "total_lines": 0,
                    "duration_ms": 0,
                }

            print(f"📸 [OddsSnapshot] 開始快照 {date}，{event_count} 場賽事")

            # 2. 對每場賽事取得賠率 & 計算 no-vig
            for event in events:
                event_id = event.get("id", "")
                home_team = event.get("home_team", "")
                away_team = event.get("away_team", "")

                try:
                    rows = await self._process_event(
                        event_id=event_id,
                        home_team=home_team,
                        away_team=away_team,
                        date=date,
                        snapshot_at=snapshot_at,
                    )
                    all_rows.extend(rows)
                except OddsAPIError as e:
                    if e.status_code == 404:
                        # 該賽事無 props 資料，跳過
                        continue
                    print(f"⚠️ [OddsSnapshot] 賽事 {event_id} API 錯誤: {e}")
                    continue
                except Exception as e:
                    print(f"⚠️ [OddsSnapshot] 賽事 {event_id} 處理失敗: {e}")
                    continue

            # 3. 批量寫入 PostgreSQL
            total_lines = len(all_rows)
            if all_rows and db_service.is_connected:
                try:
                    await db_service.executemany(UPSERT_LINE_SQL, all_rows)
                    print(
                        f"✅ [OddsSnapshot] 寫入 {total_lines} 筆 odds lines "
                        f"({event_count} 場賽事)"
                    )
                except Exception as e:
                    print(f"❌ [OddsSnapshot] PostgreSQL 寫入失敗: {e}")
            elif not db_service.is_connected:
                print("⚠️ [OddsSnapshot] PostgreSQL 未連線，跳過寫入")

            duration_ms = int((time.time() - start_time) * 1000)

            # 4. 記錄快照日誌
            await self._log_snapshot(
                date, snapshot_at, event_count, total_lines, "success", None, duration_ms
            )

            return {
                "date": date,
                "event_count": event_count,
                "total_lines": total_lines,
                "duration_ms": duration_ms,
            }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            print(f"❌ [OddsSnapshot] 快照失敗: {e}")
            await self._log_snapshot(
                date, snapshot_at, event_count, total_lines, "error", str(e), duration_ms
            )
            raise

    async def _get_events(
        self, date: str, tz_offset_minutes: int = 480
    ) -> List[Dict[str, Any]]:
        """
        取得指定日期的 NBA 賽事

        叫 "_get_events" 因為它是 take_snapshot 的內部方法（_ 前綴），
        負責「取得賽事」這一步。
        與 daily_analysis._get_events_for_date 邏輯一致，
        考慮時區偏移量以正確過濾本地日期的比賽。

        Args:
            date: 比賽日期（YYYY-MM-DD）
            tz_offset_minutes: 時區偏移量（分鐘）

        Returns:
            賽事列表
        """
        date_obj = datetime.strptime(date, "%Y-%m-%d")

        local_start = datetime.combine(date_obj.date(), datetime.min.time())
        utc_start = local_start - timedelta(minutes=tz_offset_minutes)

        from datetime import time as dt_time
        local_end = datetime.combine(date_obj.date(), dt_time(23, 59, 59))
        utc_end = local_end - timedelta(minutes=tz_offset_minutes)

        date_from = utc_start - timedelta(hours=1)
        date_to = utc_end + timedelta(hours=1)

        raw_events = await odds_provider.get_events(
            sport="basketball_nba",
            regions="us",
            date_from=date_from,
            date_to=date_to,
        )

        # 過濾：只保留本地日期內的比賽
        filtered = []
        for event in raw_events:
            commence_str = event.get("commence_time", "")
            if commence_str:
                try:
                    commence_utc = datetime.fromisoformat(
                        commence_str.replace("Z", "+00:00")
                    )
                    commence_local = commence_utc + timedelta(minutes=tz_offset_minutes)
                    if commence_local.strftime("%Y-%m-%d") == date:
                        filtered.append(event)
                except ValueError:
                    continue

        return filtered

    async def _process_event(
        self,
        event_id: str,
        home_team: str,
        away_team: str,
        date: str,
        snapshot_at: datetime,
    ) -> List[tuple]:
        """
        處理單場賽事：取得賠率、計算 no-vig、回傳待寫入的 rows

        叫 "_process_event" 因為它「處理」一場「賽事」——
        從取得 raw odds 到計算 no-vig 到準備 DB rows 的完整流程。

        關鍵優化：用一次 API call 取得 4 個 market 的賠率
        （player_points,player_rebounds,player_assists,player_points_rebounds_assists），
        減少 API call 數量從 4 降到 1。

        Args:
            event_id: The Odds API 賽事 ID
            home_team: 主場球隊名稱
            away_team: 客場球隊名稱
            date: 比賽日期字串（YYYY-MM-DD）
            snapshot_at: 快照時間戳

        Returns:
            待寫入的 row tuples 列表，每個 tuple 對應 UPSERT_LINE_SQL 的 $1-$14
        """
        # 一次取得 4 個 market 的賠率（減少 API call）
        raw_odds = await odds_provider.get_event_odds(
            sport="basketball_nba",
            event_id=event_id,
            regions="us",
            markets=SNAPSHOT_MARKETS,
            odds_format="american",
        )

        bookmakers_data = raw_odds.get("bookmakers", [])
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        rows: List[tuple] = []

        for bookmaker in bookmakers_data:
            bookmaker_key = bookmaker.get("key", "unknown")

            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")

                # 按球員分組 outcomes（Over/Under 成對出現）
                # outcomes 結構：
                #   description = "Stephen Curry"
                #   name = "Over" 或 "Under"
                #   point = 24.5（盤口線）
                #   price = -110（美式賠率）
                player_outcomes: Dict[str, Dict[str, Any]] = {}

                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description", "")
                    direction = outcome.get("name", "").lower()  # "over" or "under"

                    if not player_name or direction not in ("over", "under"):
                        continue

                    if player_name not in player_outcomes:
                        player_outcomes[player_name] = {}

                    player_outcomes[player_name][direction] = outcome

                # 對每個有完整 Over + Under 的球員計算 no-vig
                for player_name, directions in player_outcomes.items():
                    over_out = directions.get("over")
                    under_out = directions.get("under")

                    if not over_out or not under_out:
                        continue

                    line = over_out.get("point")
                    over_price = over_out.get("price", 0)
                    under_price = under_out.get("price", 0)

                    if line is None or over_price == 0 or under_price == 0:
                        continue

                    try:
                        # 計算 no-vig
                        p_over_imp = american_to_prob(over_price)
                        p_under_imp = american_to_prob(under_price)
                        vig = calculate_vig(p_over_imp, p_under_imp)
                        p_over_fair, p_under_fair = devig(p_over_imp, p_under_imp)

                        rows.append((
                            snapshot_at,             # $1  snapshot_at
                            date_obj,                # $2  date
                            event_id,                # $3  event_id
                            home_team,               # $4  home_team
                            away_team,               # $5  away_team
                            player_name,             # $6  player_name
                            market_key,              # $7  market
                            bookmaker_key,           # $8  bookmaker
                            float(line),             # $9  line
                            int(over_price),         # $10 over_odds
                            int(under_price),        # $11 under_odds
                            round(vig, 6),           # $12 vig
                            round(p_over_fair, 6),   # $13 over_fair_prob
                            round(p_under_fair, 6),  # $14 under_fair_prob
                        ))

                    except (ValueError, ZeroDivisionError):
                        # 賠率為 0 或其他計算錯誤，跳過
                        continue

        return rows

    async def _log_snapshot(
        self,
        date: str,
        snapshot_at: datetime,
        event_count: int,
        total_lines: int,
        status: str,
        error_message: Optional[str],
        duration_ms: int,
    ) -> None:
        """
        記錄快照日誌到 odds_snapshot_logs 表

        叫 "_log_snapshot" 因為它「記錄」一次「快照」的執行結果。
        即使寫入失敗也不會拋出例外（non-blocking）。

        Args:
            date: 快照日期
            snapshot_at: 快照時間戳
            event_count: 處理的賽事數
            total_lines: 寫入的 odds line 總筆數
            status: "success" 或 "error"
            error_message: 錯誤訊息（成功時為 None）
            duration_ms: 耗時毫秒
        """
        if not db_service.is_connected:
            return

        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d").date()
            await db_service.execute(
                INSERT_LOG_SQL,
                date_obj,
                snapshot_at,
                event_count,
                total_lines,
                status,
                error_message,
                duration_ms,
            )
        except Exception as e:
            print(f"⚠️ [OddsSnapshot] 寫入日誌失敗: {e}")


# 建立全域服務實例
odds_snapshot_service = OddsSnapshotService()
