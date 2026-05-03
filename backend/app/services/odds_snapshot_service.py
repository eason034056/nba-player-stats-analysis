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
from app.services.prob import (
    american_to_prob,
    calculate_vig,
    devig,
    single_leg_devig,
    DEFAULT_BINARY_VIG,
)
from app.services.db import db_service


# Supported market types for the periodic odds snapshot job.
#
# Phase 1 expansion (SPO-10) — see docs/decisions/event-page-stat-expansion/
# decision_20260502_market-key-feasibility.md (§ Addendum 1) — adds 8 markets
# on top of the 4 baseline:
#   Tier A (populated today): player_threes, player_steals, player_double_double
#       and the three native combo lines.
#   Tier B (schema-valid + currently empty inventory, free until populated):
#       player_frees_made (FTM), player_field_goals (FGM by working hypothesis).
#
# Per-market billing: each populated market in this list costs 1 unit per event
# per call. Empty markets (Tier B today) cost 0. SPO-15 audits the resulting
# burn separately; merge of this list is not gated on that audit per
# Override 2 of the decision log Addendum 1.
#
# DD note: `player_double_double` is included so the snapshot fetches the data,
# but its outcome shape (Yes/No, no `point` field) means the standard Over/Under
# parser in `_process_event` silently drops it. DD lines are written via the
# dedicated binary path in `_process_event_dd` instead — see §4 of the decision
# log for the contract.
SNAPSHOT_MARKETS = (
    # Single Over/Under markets — original 4 plus 3PM and STL
    "player_points,"
    "player_rebounds,"
    "player_assists,"
    "player_threes,"
    "player_steals,"
    # Tier B (graceful-degrade — empty inventory is rendered as "no line", not
    # a fake number; see §3 of the SPO-16 ticket and §3 of the Phase-0 decision)
    "player_frees_made,"
    "player_field_goals,"
    # Native combo Over/Under markets — no derive math, the bookmaker posts the
    # combined line directly (kills v1's vig-double-count concern)
    "player_points_rebounds_assists,"
    "player_rebounds_assists,"
    "player_points_rebounds,"
    "player_points_assists,"
    # Binary Yes/No market — separate parser path (DD binary contract §4)
    "player_double_double"
)

# Markets that follow the standard Over/Under outcome shape (`name=Over|Under`,
# `point=<line>`). Used by `_process_event` to filter what the standard parser
# touches — DD is excluded because its outcomes use `name=Yes` and have no
# `point` field, which would silently produce `point=None` rows if forced
# through the Over/Under parser.
OVER_UNDER_MARKET_KEYS = frozenset({
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_steals",
    "player_frees_made",
    "player_field_goals",
    "player_points_rebounds_assists",
    "player_rebounds_assists",
    "player_points_rebounds",
    "player_points_assists",
})

# Binary Yes/No markets — handled by the DD-style parser path. Listed as a set
# to make adding future binary markets (e.g. triple-double) a one-line change.
BINARY_MARKET_KEYS = frozenset({
    "player_double_double",
})

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

                # 💡 Dispatch by market type. Binary markets (DD) have a
                # different outcome shape (`name=Yes|No`, no `point`) and
                # MUST NOT go through the Over/Under parser — the decision
                # log §4 mandates a separate code path. Anything else is
                # treated as Over/Under (the standard 11-market case).
                if market_key in BINARY_MARKET_KEYS:
                    rows.extend(self._parse_binary_market(
                        market=market,
                        market_key=market_key,
                        bookmaker_key=bookmaker_key,
                        snapshot_at=snapshot_at,
                        date_obj=date_obj,
                        event_id=event_id,
                        home_team=home_team,
                        away_team=away_team,
                    ))
                    continue

                # Standard Over/Under flow.
                # outcomes structure:
                #   description = "Stephen Curry"
                #   name = "Over" or "Under"
                #   point = 24.5 (line)
                #   price = -110 (American odds)
                player_outcomes: Dict[str, Dict[str, Any]] = {}

                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description", "")
                    direction = outcome.get("name", "").lower()

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

    def _parse_binary_market(
        self,
        market: Dict[str, Any],
        market_key: str,
        bookmaker_key: str,
        snapshot_at: datetime,
        date_obj,
        event_id: str,
        home_team: str,
        away_team: str,
    ) -> List[tuple]:
        """
        Parse a binary Yes/No market (DD) into snapshot rows.

        Binary markets differ from Over/Under in three ways (see decision
        log §4):
          1. `outcome.name` is `Yes` or `No`, not `Over` / `Under`.
          2. There is NO `point` field (the bet is 0/1, not threshold-based).
          3. The book often only posts the `Yes` side; the `No` is implicit.
             We single-leg-devig in that case using a league-average vig prior.
             When BOTH legs are posted, derive vig from the leg pair as usual.

        Storage: we write a row per (player, bookmaker) that fits the
        existing `odds_line_snapshots` schema. To avoid an ALTER TABLE we
        encode the binary nature as:
          - line = 0.5  (sentinel — DD is "≥ 1 occurrence", line=0.5 is the
                         conventional binary marker; downstream readers can
                         detect DD by `market='player_double_double'`)
          - over_odds = Yes price  (semantic: "bet that DD happens")
          - under_odds = No price if posted else None
          - over_fair_prob = single-leg devigged Yes prob, or None when even
                             the prior cannot be applied (decision §4 step 3:
                             do NOT publish fair-prob if vig cannot be
                             estimated).
          - under_fair_prob = the (1 - over_fair_prob) complement when known.

        ⚠ The line=0.5 sentinel is a workaround for the existing schema, NOT
        a bookmaker-published value. Frontend/API consumers must dispatch on
        `market` and ignore `line` for binary markets. Documented here and in
        the docstring of the `OddsLineSnapshot` schema.

        Returns:
            List of row tuples ready for `executemany(UPSERT_LINE_SQL, ...)`.
        """
        rows: List[tuple] = []

        # Group outcomes by player. For DD each player has either {Yes}
        # alone or {Yes, No}; we never see Over/Under here.
        player_outcomes: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for outcome in market.get("outcomes", []):
            player_name = outcome.get("description", "")
            direction = outcome.get("name", "").lower()  # "yes" or "no"
            if not player_name or direction not in ("yes", "no"):
                continue
            player_outcomes.setdefault(player_name, {})[direction] = outcome

        for player_name, directions in player_outcomes.items():
            yes_out = directions.get("yes")
            if not yes_out:
                # No `Yes` price posted means we have nothing to anchor
                # the de-vig on; skip rather than fabricate.
                continue

            yes_price = yes_out.get("price", 0)
            if yes_price == 0:
                continue

            no_out = directions.get("no")
            no_price = no_out.get("price", 0) if no_out else 0

            try:
                p_yes_imp = american_to_prob(yes_price)

                if no_price != 0:
                    # Both legs posted — derive vig from the pair, same as
                    # Over/Under. This is the higher-fidelity path and
                    # what we want to use whenever it's available.
                    p_no_imp = american_to_prob(no_price)
                    vig = calculate_vig(p_yes_imp, p_no_imp)
                    p_yes_fair, p_no_fair = devig(p_yes_imp, p_no_imp)
                else:
                    # Only `Yes` posted — apply the league-average prior.
                    # `single_leg_devig` returns None when the prior can't
                    # be safely applied (per decision §4 step 3).
                    p_yes_fair = single_leg_devig(
                        p_yes_imp, DEFAULT_BINARY_VIG
                    )
                    if p_yes_fair is None:
                        # Refuse to publish fair-prob — store the implied
                        # values only, downstream callers see NULL.
                        rows.append((
                            snapshot_at, date_obj, event_id,
                            home_team, away_team, player_name,
                            market_key, bookmaker_key,
                            0.5,                       # line sentinel
                            int(yes_price),            # over_odds = Yes
                            None,                      # under_odds
                            round(DEFAULT_BINARY_VIG, 6),  # vig (assumed)
                            None,                      # over_fair_prob
                            None,                      # under_fair_prob
                        ))
                        continue
                    p_no_fair = 1.0 - p_yes_fair
                    vig = DEFAULT_BINARY_VIG

                rows.append((
                    snapshot_at,
                    date_obj,
                    event_id,
                    home_team,
                    away_team,
                    player_name,
                    market_key,
                    bookmaker_key,
                    0.5,                                # line sentinel — see docstring
                    int(yes_price),                     # over_odds = Yes price
                    int(no_price) if no_price != 0 else None,  # under_odds = No price (nullable)
                    round(vig, 6),
                    round(p_yes_fair, 6),
                    round(p_no_fair, 6),
                ))

            except (ValueError, ZeroDivisionError):
                # american_to_prob rejects 0 odds; defensive fallthrough.
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
