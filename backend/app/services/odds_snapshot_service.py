"""
odds_snapshot_service.py - Odds Snapshot Service

Periodically capture odds data from The Odds API, calculate no-vig, and write to PostgreSQL.
Used for Line Movement Tracking.

Architecture:
    Scheduler → take_snapshot(date)
            → odds_provider.get_events()           (1 API call)
            → odds_provider.get_event_odds(...)     (N API calls, 4 markets batched)
            → prob.py calculates no-vig
            → db_service.executemany()              (bulk write to PostgreSQL)
            → _log_snapshot()                       (write to odds_snapshot_logs)

Each snapshot will:
1. Retrieve all NBA games for the day
2. For each game, fetch odds for 4 markets in a single API call
3. Calculate no-vig for each bookmaker / player / market combination
4. Bulk write to odds_line_snapshots table
5. Log the snapshot

Usage:
    from app.services.odds_snapshot_service import odds_snapshot_service

    # Scheduled call
    result = await odds_snapshot_service.take_snapshot("2026-02-08")

    # Manual trigger
    result = await odds_snapshot_service.take_snapshot()
"""

import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

from app.services.odds_gateway import odds_gateway
from app.services.odds_theoddsapi import odds_provider
from app.services.odds_provider import OddsAPIError
from app.services.prob import american_to_prob, calculate_vig, devig
from app.services.db import db_service


# Supported market types (comma-separated, for fetching multiple markets in one API call)
# The Odds API v4 supports the comma-separated 'markets' parameter
SNAPSHOT_MARKETS = "player_points,player_rebounds,player_assists,player_points_rebounds_assists"

# UPSERT SQL: Insert new data or update if exists
# ON CONFLICT uses unique constraint (snapshot_at, event_id, player_name, market, bookmaker)
# Ensures the same bookmaker/player/market isn't written twice in the same snapshot
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

# Snapshot log INSERT SQL
INSERT_LOG_SQL = """
INSERT INTO odds_snapshot_logs (
    date, snapshot_at, event_count, total_lines, status, error_message, duration_ms
) VALUES ($1, $2, $3, $4, $5, $6, $7)
"""


class OddsSnapshotService:
    """
    Odds Snapshot Service

    Responsible for periodically capturing odds data for all events, calculating no-vig, and writing to PostgreSQL.
    Three daily snapshots are scheduled (UTC 16:00, 22:00, 23:30),
    corresponding to US Eastern 11AM, 5PM, 6:30PM, to cover the open-to-close period.

    Usage:
        service = OddsSnapshotService()
        result = await service.take_snapshot("2026-02-08")
    """

    async def take_snapshot(
        self,
        date: Optional[str] = None,
        tz_offset_minutes: int = 480
    ) -> Dict[str, Any]:
        """
        Execute a complete odds snapshot

        Main flow:
        1. Get all NBA events on the given date
        2. Retrieve odds for all markets for each event (4 markets in 1 call)
        3. Calculate no-vig for each bookmaker/player/market
        4. Bulk write to PostgreSQL
        5. Log the snapshot

        Called "take_snapshot" because it's like a camera "taking a snapshot" —
        capturing the state of all odds at one moment.

        Args:
            date: event date (YYYY-MM-DD). If None, use today's UTC date
            tz_offset_minutes: timezone offset in minutes for correct local date events.
                               Default 480 (UTC+8, Taipei time)

        Returns:
            dict containing:
            - date: snapshot date
            - event_count: number of events processed
            - total_lines: total odds lines written
            - duration_ms: duration in milliseconds
        """
        start_time = time.time()

        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        snapshot_at = datetime.now(timezone.utc)
        total_lines = 0
        event_count = 0
        all_rows: List[tuple] = []

        try:
            # 1. Get all events for the day
            events = await self._get_events(date, tz_offset_minutes)
            event_count = len(events)

            if not events:
                print(f"⚠️ [OddsSnapshot] {date} no events")
                await self._log_snapshot(
                    date, snapshot_at, 0, 0, "success", "No events", 0
                )
                return {
                    "date": date,
                    "event_count": 0,
                    "total_lines": 0,
                    "duration_ms": 0,
                }

            print(f"📸 [OddsSnapshot] Starting snapshot for {date}, {event_count} events")

            # 2. For each event, retrieve odds & calculate no-vig
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
                        # No props data for the event, skip
                        continue
                    print(f"⚠️ [OddsSnapshot] Event {event_id} API error: {e}")
                    continue
                except Exception as e:
                    print(f"⚠️ [OddsSnapshot] Event {event_id} handling failed: {e}")
                    continue

            # 3. Bulk write to PostgreSQL
            total_lines = len(all_rows)
            if all_rows and db_service.is_connected:
                try:
                    await db_service.executemany(UPSERT_LINE_SQL, all_rows)
                    print(
                        f"✅ [OddsSnapshot] Wrote {total_lines} odds lines "
                        f"({event_count} events)"
                    )
                except Exception as e:
                    print(f"❌ [OddsSnapshot] PostgreSQL write failed: {e}")
            elif not db_service.is_connected:
                print("⚠️ [OddsSnapshot] PostgreSQL not connected, skipping write")

            duration_ms = int((time.time() - start_time) * 1000)

            # 4. Log the snapshot
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
            print(f"❌ [OddsSnapshot] Snapshot failed: {e}")
            await self._log_snapshot(
                date, snapshot_at, event_count, total_lines, "error", str(e), duration_ms
            )
            raise

    async def _get_events(
        self, date: str, tz_offset_minutes: int = 480
    ) -> List[Dict[str, Any]]:
        """
        Get NBA events for the specified date

        Called "_get_events" because it's an internal method of take_snapshot (_ prefix),
        responsible for "getting events".
        Logic is consistent with daily_analysis._get_events_for_date,
        considering timezone offset to correctly filter local date events.

        Args:
            date: event date (YYYY-MM-DD)
            tz_offset_minutes: timezone offset in minutes

        Returns:
            List of events
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

        # Filter: keep only events that occur on the local date
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
        Process a single event: fetch odds, calculate no-vig, and return rows to insert

        Named "_process_event" because it "processes" one "event" —
        from fetching raw odds to calculating no-vig to preparing DB rows.

        Key optimization: batch fetch odds for 4 markets in a single API call
        (player_points, player_rebounds, player_assists, player_points_rebounds_assists),
        reducing number of API calls from 4 down to 1.

        Args:
            event_id: The Odds API event ID
            home_team: Home team name
            away_team: Away team name
            date: Event date string (YYYY-MM-DD)
            snapshot_at: Snapshot timestamp

        Returns:
            List of row tuples for insertion, each tuple matching UPSERT_LINE_SQL $1-$14
        """
        # Fetch odds for 4 markets in one call (reducing API calls)
        snapshot = await odds_gateway.get_market_snapshot(
            sport="basketball_nba",
            event_id=event_id,
            regions="us",
            markets=SNAPSHOT_MARKETS,
            odds_format="american",
            priority="background",
            record_hot_key=False,
        )

        bookmakers_data = snapshot.data.get("bookmakers", [])
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        rows: List[tuple] = []

        for bookmaker in bookmakers_data:
            bookmaker_key = bookmaker.get("key", "unknown")

            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")

                # Group outcomes by player (Over/Under must both exist)
                # outcomes structure:
                #   description = "Stephen Curry"
                #   name = "Over" or "Under"
                #   point = 24.5 (line)
                #   price = -110 (American odds)
                player_outcomes: Dict[str, Dict[str, Any]] = {}

                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description", "")
                    direction = outcome.get("name", "").lower()  # "over" or "under"

                    if not player_name or direction not in ("over", "under"):
                        continue

                    if player_name not in player_outcomes:
                        player_outcomes[player_name] = {}

                    player_outcomes[player_name][direction] = outcome

                # For each player with both Over & Under, calculate no-vig
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
                        # Calculate no-vig
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
                        # Odds are 0 or some error occurred in calculation, skip
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
        Log a snapshot entry to the odds_snapshot_logs table

        Named "_log_snapshot" because it "logs" the result of a "snapshot".
        Will not raise exceptions if writing fails (non-blocking).

        Args:
            date: Snapshot date
            snapshot_at: Snapshot timestamp
            event_count: Number of events processed
            total_lines: Total odds lines written
            status: "success" or "error"
            error_message: Error message (None if successful)
            duration_ms: Duration in milliseconds
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
            print(f"⚠️ [OddsSnapshot] Failed writing snapshot log: {e}")


# Create global service instance
odds_snapshot_service = OddsSnapshotService()
