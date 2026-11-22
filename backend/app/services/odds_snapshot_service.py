"""
odds_snapshot_service.py - Odds Snapshot Service

Periodically capture odds data from The Odds API, calculate no-vig, and write to PostgreSQL.
Used for Line Movement Tracking.

Architecture:
    Scheduler → take_snapshot(date)
            → events for the NBA provider           (1 list call)
            → odds_gateway.get_market_snapshot(...) (N calls, markets batched)
            → prob.py calculates no-vig
            → db_service.executemany()              (bulk write to odds_line_snapshots)
            → 002 live rows when the provider is balldontlie and parents exist
            → _log_snapshot()                       (write to odds_snapshot_logs)

    The pre-tip job calls take_closing_snapshot. That path always uses
    BALLDONTLIE. It does not read nba_odds_provider. It writes the same
    002 tables with snapshot_kind 'closing', and it writes odds_line_snapshots.

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

import logging
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple

from app.services.odds_gateway import (
    PROVIDERS,
    active_nba_provider_name,
    balldontlie_nba_provider,
    odds_gateway,
)
from app.services.odds_theoddsapi import odds_provider
from app.services.odds_provider import OddsAPIError, ProviderEvent
from app.services.prob import (
    american_to_prob,
    posted_american_odds,
    calculate_vig,
    devig,
    single_leg_devig,
    DEFAULT_BINARY_VIG,
)
from app.services.db import db_service
from app.services.slate_date import nba_slate_date, offset_for_us_game_date

logger = logging.getLogger(__name__)


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

# nba_slate_date and offset_for_us_game_date live in slate_date and are
# imported above. This module re-exports them so existing
# ``from app.services.odds_snapshot_service import nba_slate_date``
# imports keep working. There is one implementation.

# UPSERT SQL: insert a posted total, or refresh that same total.
# The conflict target matches odds_line_snapshots_book_line_key, which
# includes the line. A different total is a new row, not an update.
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
ON CONFLICT (snapshot_at, event_id, player_name, market, bookmaker, line)
DO UPDATE SET
    over_odds = EXCLUDED.over_odds,
    under_odds = EXCLUDED.under_odds,
    vig = EXCLUDED.vig,
    over_fair_prob = EXCLUDED.over_fair_prob,
    under_fair_prob = EXCLUDED.under_fair_prob
"""

# Snapshot log INSERT SQL
INSERT_LOG_SQL = """
INSERT INTO odds_snapshot_logs (
    date, snapshot_at, event_count, total_lines, status, error_message, duration_ms, league
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""

# One live or closing prop row. ``$1`` through ``$11`` are the live tuple
# (game, player, book, market, and the prices). ``$12`` is
# ``snapshot_kind`` (``live`` or ``closing``), appended so the book stays
# the third value. A retry at the same snapshot_at updates that row
# instead of adding a second tick. The WHERE clause matches the partial
# unique index in 002_bdl_core.sql. Opening rows use a different conflict
# target and are not written here.
UPSERT_LIVE_PROP_SQL = """
INSERT INTO player_prop_snapshots (
    league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, market_type,
    line, over_odds, under_odds, milestone_odds, snapshot_at, source_updated_at
) VALUES (
    'nba', $12, $1, $2, $3, $4, $5, $6,
    $7, $8, $9, $10, $11
)
ON CONFLICT (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, snapshot_at)
WHERE snapshot_kind IN ('live', 'closing')
DO UPDATE SET
    market_type = EXCLUDED.market_type,
    line = EXCLUDED.line,
    over_odds = EXCLUDED.over_odds,
    under_odds = EXCLUDED.under_odds,
    milestone_odds = EXCLUDED.milestone_odds,
    source_updated_at = EXCLUDED.source_updated_at
"""

# One live or closing game line per book. ``$1`` through ``$13`` are the
# live tuple. ``$14`` is ``snapshot_kind``, appended the same way as the
# prop row. Same retry rule as the prop tick key.
UPSERT_LIVE_GAME_ODDS_SQL = """
INSERT INTO game_odds_snapshots (
    league, snapshot_kind, bdl_game_id, book_key, snapshot_at, source_updated_at,
    spread_home_value, spread_home_odds, spread_away_value, spread_away_odds,
    moneyline_home_odds, moneyline_away_odds,
    total_value, total_over_odds, total_under_odds
) VALUES (
    'nba', $14, $1, $2, $3, $4,
    $5, $6, $7, $8,
    $9, $10,
    $11, $12, $13
)
ON CONFLICT (league, snapshot_kind, bdl_game_id, book_key, snapshot_at)
WHERE snapshot_kind IN ('live', 'closing')
DO UPDATE SET
    source_updated_at = EXCLUDED.source_updated_at,
    spread_home_value = EXCLUDED.spread_home_value,
    spread_home_odds = EXCLUDED.spread_home_odds,
    spread_away_value = EXCLUDED.spread_away_value,
    spread_away_odds = EXCLUDED.spread_away_odds,
    moneyline_home_odds = EXCLUDED.moneyline_home_odds,
    moneyline_away_odds = EXCLUDED.moneyline_away_odds,
    total_value = EXCLUDED.total_value,
    total_over_odds = EXCLUDED.total_over_odds,
    total_under_odds = EXCLUDED.total_under_odds
"""


def _parse_commence(value: Any) -> datetime | None:
    """Parse one ISO timestamp. ``Z`` means UTC. Unusable values are None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _as_utc_now(now: datetime | None) -> datetime:
    """``None`` is the current UTC time. A naive datetime is UTC."""
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _local_date_of(commence: datetime, tz_offset_minutes: int) -> str:
    """Calendar date after adding a fixed minute offset to a UTC instant.

    This is the same shift ``_get_events`` uses for The Odds API. It is
    not a named-timezone conversion. ``-300`` turns 04:00Z into 23:00 on
    the previous calendar date.
    """
    shifted = commence + timedelta(minutes=tz_offset_minutes)
    return shifted.strftime("%Y-%m-%d")


def _utc_window(date: str, tz_offset_minutes: int) -> tuple[datetime, datetime]:
    """UTC search window for one local calendar date, widened by one hour.

    The datetimes are naive. Callers that talk to BALLDONTLIE treat a
    naive value as UTC, which is the same assumption ``get_events`` uses.
    """
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    local_start = datetime.combine(date_obj.date(), datetime.min.time())
    utc_start = local_start - timedelta(minutes=tz_offset_minutes)
    from datetime import time as dt_time
    local_end = datetime.combine(date_obj.date(), dt_time(23, 59, 59))
    utc_end = local_end - timedelta(minutes=tz_offset_minutes)
    return utc_start - timedelta(hours=1), utc_end + timedelta(hours=1)


def bdl_event_is_open(
    event: ProviderEvent,
    *,
    date: str,
    tz_offset_minutes: int,
    now: datetime,
) -> bool:
    """True when this BALLDONTLIE game is still a pre-tip scheduled game on ``date``.

    ``in_progress`` and ``final`` are skipped. A tip at or before ``now``
    is skipped. A tip on another local date is skipped. ``now`` must be
    timezone-aware.
    """
    if event.status != "scheduled":
        return False
    commence = _parse_commence(event.commence_time)
    if commence is None or commence <= now:
        return False
    return _local_date_of(commence, tz_offset_minutes) == date


async def list_bdl_events_for_local_date(
    date: str,
    tz_offset_minutes: int = 480,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """NBA games for one local date from ``odds_gateway.list_events``.

    Use this when ``nba_odds_provider`` is ``balldontlie``. The Odds API
    path stays on ``odds_provider.get_events`` so the existing snapshot
    and daily-analysis tests still intercept that call.

    Args:
        date: Local game date, ``YYYY-MM-DD``.
        tz_offset_minutes: Minutes east of UTC for that local date.
        now: Instant used for the pre-tip check. None means the current
            UTC time. Tests pass a fixed instant.

    Returns:
        Event dicts with ``id``, ``commence_time``, ``home_team``,
        ``away_team``, and ``status``. ``id`` is the decimal game id.
    """
    date_from, date_to = _utc_window(date, tz_offset_minutes)
    moment = _as_utc_now(now)
    listed = await odds_gateway.list_events(
        league="nba",
        start_utc=date_from,
        end_utc=date_to,
    )
    kept: list[dict[str, Any]] = []
    for event in listed:
        if not bdl_event_is_open(
            event,
            date=date,
            tz_offset_minutes=tz_offset_minutes,
            now=moment,
        ):
            continue
        kept.append(
            {
                "id": event.event_id,
                "sport_key": "basketball_nba",
                "commence_time": event.commence_time,
                "home_team": event.home_team,
                "away_team": event.away_team,
                "status": event.status,
            }
        )
    return kept


def _optional_int(value: Any) -> int | None:
    """A whole-number price, or None when the field is missing or not an int."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _optional_decimal(value: Any) -> Decimal | None:
    """A numeric line from a recorded string or number, or None."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str, Decimal)):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _live_prop_args(
    game_id: int,
    bookmakers: list[dict[str, Any]],
    player_ids: dict[str, int],
    snapshot_at: datetime,
) -> list[tuple]:
    """Main-line live prop tuples for one game.

    Over/under rows carry both prices and no milestone price.
    ``player_double_double`` is a milestone: the Yes price is
    ``milestone_odds``, and both sides of an over/under are null. The
    line on that row is ``0.5``, which is the line on the recorded
    double-double rows. One tuple per player, book, and market. A
    player with no id is kept here with ``player_id`` None so the
    writer can count the miss instead of guessing an id.
    """
    from app.services.daily_analysis import _main_line_vote

    by_key: dict[tuple[int, int | None, str, str], tuple] = {}
    for book in bookmakers:
        if not isinstance(book, dict):
            continue
        book_key = book.get("key")
        if not isinstance(book_key, str) or not book_key:
            continue
        for market in book.get("markets") or []:
            if not isinstance(market, dict):
                continue
            market_key = market.get("key")
            if not isinstance(market_key, str):
                continue
            updated = _parse_commence(market.get("last_update")) if isinstance(market.get("last_update"), str) else None
            outcomes = [item for item in (market.get("outcomes") or []) if isinstance(item, dict)]
            if market_key == "player_double_double":
                yes_price: dict[str, int] = {}
                for outcome in outcomes:
                    if str(outcome.get("name") or "").strip().lower() != "yes":
                        continue
                    name = outcome.get("description")
                    price = _optional_int(outcome.get("price"))
                    if isinstance(name, str) and name and price is not None and price != 0:
                        yes_price[name] = price
                for name, price in yes_price.items():
                    player_id = player_ids.get(name)
                    identity = player_id if isinstance(player_id, int) else name
                    by_key[(game_id, identity, book_key, market_key)] = (
                        game_id,
                        player_id,
                        book_key,
                        market_key,
                        "milestone",
                        Decimal("0.5"),
                        None,
                        None,
                        price,
                        snapshot_at,
                        updated,
                    )
                continue
            if market_key not in OVER_UNDER_MARKET_KEYS:
                continue
            grouped: dict[str, list[dict[str, Any]]] = {}
            for outcome in outcomes:
                name = outcome.get("description")
                if isinstance(name, str) and name:
                    grouped.setdefault(name, []).append(outcome)
            for name, player_outcomes in grouped.items():
                vote = _main_line_vote(player_outcomes)
                if vote is None:
                    continue
                point = vote[0]
                over_price = None
                under_price = None
                for outcome in player_outcomes:
                    try:
                        posted = round(float(outcome.get("point")), 1)
                    except (TypeError, ValueError):
                        continue
                    if posted != point:
                        continue
                    side = str(outcome.get("name") or "").strip().lower()
                    price = _optional_int(outcome.get("price"))
                    if price is None or price == 0:
                        continue
                    if side == "over":
                        over_price = price
                    elif side == "under":
                        under_price = price
                if over_price is None or under_price is None:
                    continue
                player_id = player_ids.get(name)
                identity = player_id if isinstance(player_id, int) else name
                by_key[(game_id, identity, book_key, market_key)] = (
                    game_id,
                    player_id,
                    book_key,
                    market_key,
                    "over_under",
                    Decimal(str(point)),
                    over_price,
                    under_price,
                    None,
                    snapshot_at,
                    updated,
                )
    return list(by_key.values())


def closing_game_fate(
    game: object,
    *,
    slate_date: str,
    hhmm: str,
    now: datetime,
) -> str:
    """Decide what the closing job does with one ``list_games`` row.

    ``closing_game_fate`` returns ``keep`` when the row is still scheduled,
    it belongs to this UTC minute and this slate date, and ``now`` is
    before its tip. ``other`` is a different minute or a different date.
    The caller ignores ``other``. ``postponed``, ``not_scheduled``, and
    ``tip_passed`` are skips the caller logs and does not fetch.

    ``hhmm`` is the four-character UTC minute of the job. The game's
    minute uses ``pretip_hhmm``, the same function as the job id.

    Args:
        game: One element of a games payload ``data`` list.
        slate_date: Eastern game date the job was given.
        hhmm: UTC hour and minute of this job, such as ``0000``.
        now: Clock for the pre-tip check. Naive values are UTC.

    Returns:
        ``keep``, ``other``, ``postponed``, ``not_scheduled``, or ``tip_passed``.
    """
    from app.services.scheduler import pretip_hhmm

    if not isinstance(game, dict):
        return "other"
    raw_tip = game.get("datetime")
    game_tip = _parse_commence(raw_tip) if isinstance(raw_tip, str) else None
    if game_tip is None or pretip_hhmm(game_tip) != hhmm:
        return "other"
    game_date = game.get("date")
    if isinstance(game_date, str) and game_date != slate_date:
        return "other"
    if game.get("postponed") is True:
        return "postponed"
    if game.get("status_state") != "scheduled":
        return "not_scheduled"
    if game_tip <= _as_utc_now(now):
        return "tip_passed"
    return "keep"


def _with_snapshot_kind(kind: str, rows: list[tuple]) -> list[tuple]:
    """Append ``snapshot_kind`` to each live row for the shared upsert.

    ``_live_prop_args`` and ``_game_odds_with_parents`` build the value
    tuple without the kind. ``live`` and ``closing`` use the same SQL.
    The kind is the last bound value. A prop row's third value stays the
    book key.
    """
    return [(*row, kind) for row in rows]


def _player_id_map(data: dict[str, Any]) -> dict[str, int]:
    """Description to player id from a cached BALLDONTLIE odds body."""
    raw = data.get("player_ids")
    if not isinstance(raw, dict):
        return {}
    found: dict[str, int] = {}
    for name, player_id in raw.items():
        if isinstance(name, str) and isinstance(player_id, int):
            found[name] = player_id
    return found


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
        tz_offset_minutes: Optional[int] = None,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Execute a complete odds snapshot

        Main flow:
        1. Get all NBA events on the given US game date
        2. Retrieve odds for all markets for each event (markets batched)
        3. Calculate no-vig for each bookmaker/player/market/line
        4. Bulk write to PostgreSQL
        5. Log the snapshot

        Called "take_snapshot" because it's like a camera "taking a snapshot" —
        capturing the state of all odds at one moment.

        The date is an America/New_York game date. When ``date`` is omitted,
        that is today's date in New York, not the UTC date. When
        ``tz_offset_minutes`` is omitted, it is the Eastern offset for that
        date. Passing the UTC calendar date with the old default of 480
        (UTC+8) selected no NBA games: a tip at 2026-11-10T00:10:00Z is
        19:10 on 2026-11-09 in New York and 08:10 on 2026-11-10 in Taipei.

        Args:
            date: US game date (YYYY-MM-DD). None means today in New York.
            tz_offset_minutes: Minutes east of UTC used to turn ``date`` into
                a UTC window. None means the Eastern offset for ``date``.
            now: Instant used to drop BALLDONTLIE games whose tip has
                passed. None means the current UTC time. The Odds API
                path does not read it. Tests pass a fixed instant.

        Returns:
            dict containing:
            - date: snapshot date
            - event_count: number of events processed
            - total_lines: total odds lines written
            - duration_ms: duration in milliseconds
        """
        start_time = time.time()

        if date is None:
            date, eastern_offset = nba_slate_date()
        else:
            eastern_offset = offset_for_us_game_date(date)
        if tz_offset_minutes is None:
            tz_offset_minutes = eastern_offset

        snapshot_at = datetime.now(timezone.utc)
        total_lines = 0
        event_count = 0
        all_rows: List[tuple] = []
        # Boards captured during _process_event when the NBA provider is
        # balldontlie. The live-table write reads these instead of
        # fetching props a second time.
        self._bdl_boards: list[tuple[str, dict[str, Any]]] = []

        try:
            # 1. Get all events for the day
            # Omit ``now`` when the caller did not pass one. Existing
            # snapshot tests assert this exact two-argument call. The
            # method's own default is the current UTC time, which is
            # what a missing ``now`` means.
            if now is None:
                events = await self._get_events(date, tz_offset_minutes)
            else:
                events = await self._get_events(date, tz_offset_minutes, now=now)
            event_count = len(events)

            if not events:
                print(f"⚠️ [OddsSnapshot] {date} no events")
                await self._log_snapshot(
                    date, snapshot_at, 0, 0, "success", "No events", 0
                )
                return self._with_bdl_misses({
                    "date": date,
                    "event_count": 0,
                    "total_lines": 0,
                    "duration_ms": 0,
                }, 0)

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
                # A write error is not swallowed. The handler below logs
                # status "error" and re-raises, so a failed insert is not
                # recorded as a successful capture with these rows.
                await db_service.executemany(UPSERT_LINE_SQL, all_rows)
                print(
                    f"✅ [OddsSnapshot] Wrote {total_lines} odds lines "
                    f"({event_count} events)"
                )
            elif not db_service.is_connected:
                print("⚠️ [OddsSnapshot] PostgreSQL not connected, skipping write")

            # 3b. 002 live rows. A missing parent is a counted miss.
            # It must not undo the odds_line_snapshots write above and
            # must not fail this snapshot.
            parent_misses = 0
            if active_nba_provider_name() == "balldontlie" and events:
                try:
                    if db_service.is_connected:
                        parent_misses = await self._write_bdl_live(
                            events=events,
                            date=date,
                            snapshot_at=snapshot_at,
                        )
                    else:
                        # The props call already happened. Count the game-odds
                        # call here too, so a disconnected database does not
                        # hide it. There is nothing to insert.
                        kept_ids = {
                            int(event["id"])
                            for event in events
                            if str(event.get("id") or "").isdigit()
                        }
                        await self._slate_game_odds(date, kept_ids)
                except Exception as exc:
                    parent_misses += 1
                    logger.warning(
                        "bdl live dual-write skipped (%s)",
                        type(exc).__name__,
                    )

            duration_ms = int((time.time() - start_time) * 1000)

            # 4. Log the snapshot
            await self._log_snapshot(
                date, snapshot_at, event_count, total_lines, "success", None, duration_ms
            )

            return self._with_bdl_misses({
                "date": date,
                "event_count": event_count,
                "total_lines": total_lines,
                "duration_ms": duration_ms,
            }, parent_misses)

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            print(f"❌ [OddsSnapshot] Snapshot failed: {e}")
            await self._log_snapshot(
                date, snapshot_at, event_count, total_lines, "error", str(e), duration_ms
            )
            raise

    @staticmethod
    def _with_bdl_misses(result: Dict[str, Any], misses: int) -> Dict[str, Any]:
        """Add the miss count only when the NBA provider is BALLDONTLIE.

        The Odds API return shape stays the four keys callers already
        read. ``misses`` is how many 002 inserts were skipped because a
        parent row was missing, or because that insert raised.
        """
        if active_nba_provider_name() != "balldontlie":
            return result
        result["bdl_parent_misses"] = misses
        return result

    async def _get_events(
        self,
        date: str,
        tz_offset_minutes: int = 480,
        *,
        now: datetime | None = None,
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
            now: Pre-tip cutoff for BALLDONTLIE. Ignored for The Odds API.

        Returns:
            List of events
        """
        if active_nba_provider_name() == "balldontlie":
            return await list_bdl_events_for_local_date(
                date, tz_offset_minutes, now=now
            )

        date_obj = datetime.strptime(date, "%Y-%m-%d")

        local_start = datetime.combine(date_obj.date(), datetime.min.time())
        utc_start = local_start - timedelta(minutes=tz_offset_minutes)

        from datetime import time as dt_time
        local_end = datetime.combine(date_obj.date(), dt_time(23, 59, 59))
        utc_end = local_end - timedelta(minutes=tz_offset_minutes)

        date_from = utc_start - timedelta(hours=1)
        date_to = utc_end + timedelta(hours=1)

        raw_events = await odds_provider.get_events(
            league="nba",
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
            league="nba",
            event_id=event_id,
            regions="us",
            markets=SNAPSHOT_MARKETS,
            odds_format="american",
            priority="background",
            record_hot_key=False,
        )

        bookmakers_data = snapshot.data.get("bookmakers", [])
        boards = getattr(self, "_bdl_boards", None)
        if active_nba_provider_name() == "balldontlie" and isinstance(boards, list):
            payload = snapshot.data if isinstance(snapshot.data, dict) else {}
            boards.append((event_id, payload))
        return self.rows_from_bookmakers(
            bookmakers_data,
            event_id=event_id,
            home_team=home_team,
            away_team=away_team,
            date=date,
            snapshot_at=snapshot_at,
        )

    def rows_from_bookmakers(
        self,
        bookmakers_data: List[Dict[str, Any]],
        *,
        event_id: str,
        home_team: str,
        away_team: str,
        date: str,
        snapshot_at: datetime,
    ) -> List[tuple]:
        """Turn already-fetched bookmaker payloads into snapshot rows.

        This is the pure parser ``_process_event`` uses after the gateway
        returns. It does not call the Odds API, Redis, or Postgres. Tests
        build ``odds_line_snapshots`` rows by calling it with recorded
        fixtures. Each two-sided total is its own row. Over and Under are
        paired only when they share a point, so an alternate ladder is
        stored beside the main total. A later quote at the same point
        replaces that side. Read-side ``_main_book_line`` still collapses
        those rows to one vote per book.

        Args:
            bookmakers_data: Odds API ``bookmakers`` array, already fetched.
            event_id: Event id written onto every row.
            home_team: Home team name written onto every row.
            away_team: Away team name written onto every row.
            date: Game date, ``YYYY-MM-DD``.
            snapshot_at: Timestamp shared by every row from this capture.

        Returns:
            Row tuples matching ``UPSERT_LINE_SQL`` parameters ``$1`` through
            ``$14``.
        """
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        rows: List[tuple] = []

        for bookmaker in bookmakers_data:
            bookmaker_key = bookmaker.get("key", "unknown")

            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")

                # 💡 Explicit dispatch by market type (SPO-18 hardening).
                # Binary markets (DD) have a different outcome shape
                # (`name=Yes|No`, no `point`) and MUST NOT go through the
                # Over/Under parser — the decision log §4 mandates a
                # separate code path. Unknown keys are explicitly skipped
                # rather than silently fed into the OU parser, which would
                # produce `point=None` rows on a typo'd future addition to
                # SNAPSHOT_MARKETS. Defense-in-depth: today the constants-
                # side invariant `test_union_covers_all_snapshot_markets`
                # guards the call site, this guards the runtime side.
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

                if market_key not in OVER_UNDER_MARKET_KEYS:
                    # ⚠ Reached only if SNAPSHOT_MARKETS picks up a key that
                    # neither set knows how to parse — i.e. a typo or an
                    # un-classified addition. Skip rather than corrupt.
                    print(
                        f"⚠️ [OddsSnapshot] unknown market key "
                        f"{market_key!r}; skipping"
                    )
                    continue

                # Standard Over/Under flow.
                # outcomes structure:
                #   description = "Stephen Curry"
                #   name = "Over" or "Under"
                #   point = 24.5 (line)
                #   price = -110 (American odds)
                #
                # Pair by (player, point). The last Over and the last Under
                # in file order are not a pair when they sit on different
                # totals. A rung with only one side is skipped, same as a
                # player who has no Under at all.
                rungs: Dict[Tuple[str, float], Dict[str, Any]] = {}
                rung_order: List[Tuple[str, float]] = []

                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description", "")
                    direction = outcome.get("name", "").lower()
                    raw_point = outcome.get("point")

                    if not player_name or direction not in ("over", "under"):
                        continue
                    if raw_point is None:
                        continue
                    try:
                        point = round(float(raw_point), 1)
                    except (TypeError, ValueError):
                        continue

                    slot = (player_name, point)
                    if slot not in rungs:
                        rungs[slot] = {}
                        rung_order.append(slot)
                    rungs[slot][direction] = outcome

                for player_name, point in rung_order:
                    directions = rungs[(player_name, point)]
                    over_out = directions.get("over")
                    under_out = directions.get("under")

                    if not over_out or not under_out:
                        continue

                    over_price = over_out.get("price", 0)
                    under_price = under_out.get("price", 0)

                    if over_price == 0 or under_price == 0:
                        continue

                    try:
                        # Calculate no-vig for this total only.
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
                            float(point),            # $9  line
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

            yes_price = posted_american_odds(yes_out.get("price"))
            if yes_price is None:
                continue

            no_out = directions.get("no")
            no_price = posted_american_odds(no_out.get("price")) if no_out else None

            try:
                p_yes_imp = american_to_prob(yes_price)

                if no_price is not None:
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
                        # pragma: SPO-18 follow-up — replace 0.5 sentinel with explicit line_kind column.
                        # Frontend/API consumers MUST dispatch on `market` and ignore `line` for binary markets.
                        # See task-summaries/SPO-16-backend-stat-expansion.md Trade-offs §1.
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

                # pragma: SPO-18 follow-up — replace 0.5 sentinel with explicit line_kind column.
                # Frontend/API consumers MUST dispatch on `market` and ignore `line` for binary markets.
                # See task-summaries/SPO-16-backend-stat-expansion.md Trade-offs §1.
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
                    int(no_price) if no_price is not None else None,  # under_odds = No price (nullable)
                    round(vig, 6),
                    round(p_yes_fair, 6),
                    round(p_no_fair, 6),
                ))

            except (ValueError, ZeroDivisionError):
                # american_to_prob rejects 0 odds; defensive fallthrough.
                continue

        return rows

    async def _write_bdl_live(
        self,
        events: List[Dict[str, Any]],
        date: str,
        snapshot_at: datetime,
        *,
        snapshot_kind: str = "live",
        odds_client: Any = None,
        odds_rows: list[dict[str, Any]] | None = None,
        boards: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> int:
        """Write 002 tick rows for this capture. Return the miss count.

        ``odds_line_snapshots`` has already been written. This method
        inserts ``player_prop_snapshots`` and ``game_odds_snapshots``
        only when the parent ``games``, ``players``, ``books``, and
        ``prop_markets`` rows exist. A missing parent is counted and
        logged. It is not raised. A second call with the same
        ``snapshot_kind`` and ``snapshot_at`` updates that tick instead
        of adding a row.

        ``snapshot_kind`` is ``live`` for the scheduled snapshot and
        ``closing`` for the pre-tip job. Both use the same SQL and the
        same parent check. Opening rows are not written here.

        Args:
            events: Games this snapshot kept. ``id`` is the decimal game id.
            date: US game date passed to ``list_odds`` as ``dates[]``.
            snapshot_at: Job time stored on every row of this tick.
            snapshot_kind: ``live`` or ``closing``.
            odds_client: BALLDONTLIE client for ``list_odds``. None uses
                the active NBA provider, which is the live snapshot path.
            odds_rows: Game-line rows already fetched. None fetches them.
            boards: ``(event_id, props body)`` pairs already fetched.
                None reads ``self._bdl_boards``, which the live snapshot
                fills while it writes ``odds_line_snapshots``.

        Returns:
            How many candidate inserts were skipped.

        Raises:
            ValueError: ``snapshot_kind`` is not ``live`` or ``closing``.
        """
        if snapshot_kind not in {"live", "closing"}:
            raise ValueError(
                f"snapshot_kind must be live or closing, not {snapshot_kind!r}"
            )
        kept_ids: set[int] = set()
        for event in events:
            text = str(event.get("id") or "")
            if text.isdigit():
                kept_ids.add(int(text))

        source = boards if boards is not None else getattr(self, "_bdl_boards", [])
        prop_args: list[tuple] = []
        for event_id, payload in source:
            if not str(event_id).isdigit():
                continue
            game_id = int(event_id)
            if game_id not in kept_ids:
                continue
            bookmakers = payload.get("bookmakers") if isinstance(payload, dict) else None
            if not isinstance(bookmakers, list):
                bookmakers = []
            prop_args.extend(
                _live_prop_args(
                    game_id,
                    bookmakers,
                    _player_id_map(payload if isinstance(payload, dict) else {}),
                    snapshot_at,
                )
            )

        if odds_rows is None:
            odds_rows = await self._slate_game_odds(date, kept_ids, client=odds_client)
        misses = 0
        prop_ready, prop_misses = await self._props_with_parents(prop_args)
        misses += prop_misses
        odds_ready, odds_misses = await self._game_odds_with_parents(odds_rows, snapshot_at)
        misses += odds_misses
        prop_failed = await self._write_each(
            UPSERT_LIVE_PROP_SQL,
            _with_snapshot_kind(snapshot_kind, prop_ready),
            "props",
        )
        odds_failed = await self._write_each(
            UPSERT_LIVE_GAME_ODDS_SQL,
            _with_snapshot_kind(snapshot_kind, odds_ready),
            "game_odds",
        )
        misses += prop_failed + odds_failed
        logger.info(
            "bdl_live_dual_write snapshot_kind=%s props_written=%s game_odds_written=%s misses=%s",
            snapshot_kind,
            len(prop_ready) - prop_failed,
            len(odds_ready) - odds_failed,
            misses,
        )
        return misses

    async def _slate_game_odds(
        self,
        date: str,
        kept_ids: set[int],
        client: Any = None,
    ) -> list[dict[str, Any]]:
        """Recorded game lines for the kept games, one row per book.

        ``list_odds`` is the BALLDONTLIE ``/v2/odds`` call. A failure
        here returns no rows. The prop write still runs. Pages follow
        ``meta.next_cursor`` when that value is an int.

        Args:
            date: US game date passed as ``dates[]``.
            kept_ids: Decimal game ids this capture is still writing.
            client: BALLDONTLIE client. None uses the active NBA provider.
        """
        if not kept_ids:
            return []
        if client is None:
            try:
                provider = PROVIDERS["nba"]
                client = provider._require_client()
            except Exception as exc:
                logger.warning("bdl live game odds skipped (%s)", type(exc).__name__)
                return []

        raw_rows: list[dict[str, Any]] = []
        cursor: int | None = None
        seen: set[int] = set()
        try:
            while True:
                payload = await client.list_odds(dates=[date], cursor=cursor)
                data = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(data, list):
                    raw_rows.extend(item for item in data if isinstance(item, dict))
                meta = payload.get("meta") if isinstance(payload, dict) else None
                nxt = meta.get("next_cursor") if isinstance(meta, dict) else None
                if not isinstance(nxt, int) or nxt in seen:
                    break
                seen.add(nxt)
                cursor = nxt
        except Exception as exc:
            logger.warning("bdl live game odds skipped (%s)", type(exc).__name__)
            return []

        newest: dict[tuple[int, str], dict[str, Any]] = {}
        for row in raw_rows:
            game_id = row.get("game_id")
            vendor = row.get("vendor")
            if not isinstance(game_id, int) or game_id not in kept_ids:
                continue
            if not isinstance(vendor, str) or not vendor:
                continue
            key = (game_id, vendor)
            previous = newest.get(key)
            updated = row.get("updated_at") if isinstance(row.get("updated_at"), str) else ""
            previous_updated = ""
            if previous is not None and isinstance(previous.get("updated_at"), str):
                previous_updated = previous["updated_at"]
            if previous is None or updated >= previous_updated:
                newest[key] = row
        return list(newest.values())

    async def _props_with_parents(self, args: list[tuple]) -> tuple[list[tuple], int]:
        """Drop prop rows whose game, player, book, or market is missing."""
        if not args:
            return [], 0
        games = await self._present_ids(
            "SELECT bdl_game_id FROM games WHERE league = 'nba' AND bdl_game_id = ANY($1::bigint[])",
            sorted({row[0] for row in args}),
            "bdl_game_id",
        )
        player_values = sorted({row[1] for row in args if isinstance(row[1], int)})
        players = await self._present_ids(
            "SELECT bdl_player_id FROM players WHERE league = 'nba' AND bdl_player_id = ANY($1::int[])",
            player_values,
            "bdl_player_id",
        )
        books = await self._present_ids(
            "SELECT book_key FROM books WHERE league = 'nba' AND book_key = ANY($1::text[])",
            sorted({row[2] for row in args}),
            "book_key",
        )
        markets = await self._present_ids(
            "SELECT market FROM prop_markets WHERE league = 'nba' AND market = ANY($1::text[])",
            sorted({row[3] for row in args}),
            "market",
        )
        ready: list[tuple] = []
        misses = 0
        for row in args:
            game_id, player_id, book_key, market = row[0], row[1], row[2], row[3]
            if (
                game_id not in games
                or not isinstance(player_id, int)
                or player_id not in players
                or book_key not in books
                or market not in markets
            ):
                misses += 1
                continue
            ready.append(row)
        if misses:
            logger.info("bdl_live_parent_miss kind=props count=%s", misses)
        return ready, misses

    async def _game_odds_with_parents(
        self,
        rows: list[dict[str, Any]],
        snapshot_at: datetime,
    ) -> tuple[list[tuple], int]:
        """Drop game lines whose game or book parent is missing."""
        if not rows:
            return [], 0
        games = await self._present_ids(
            "SELECT bdl_game_id FROM games WHERE league = 'nba' AND bdl_game_id = ANY($1::bigint[])",
            sorted({row["game_id"] for row in rows if isinstance(row.get("game_id"), int)}),
            "bdl_game_id",
        )
        books = await self._present_ids(
            "SELECT book_key FROM books WHERE league = 'nba' AND book_key = ANY($1::text[])",
            sorted({row["vendor"] for row in rows if isinstance(row.get("vendor"), str)}),
            "book_key",
        )
        ready: list[tuple] = []
        misses = 0
        for row in rows:
            game_id = row.get("game_id")
            vendor = row.get("vendor")
            if not isinstance(game_id, int) or not isinstance(vendor, str):
                misses += 1
                continue
            if game_id not in games or vendor not in books:
                misses += 1
                continue
            ready.append(
                (
                    game_id,
                    vendor,
                    snapshot_at,
                    _parse_commence(row.get("updated_at")) if isinstance(row.get("updated_at"), str) else None,
                    _optional_decimal(row.get("spread_home_value")),
                    _optional_int(row.get("spread_home_odds")),
                    _optional_decimal(row.get("spread_away_value")),
                    _optional_int(row.get("spread_away_odds")),
                    _optional_int(row.get("moneyline_home_odds")),
                    _optional_int(row.get("moneyline_away_odds")),
                    _optional_decimal(row.get("total_value")),
                    _optional_int(row.get("total_over_odds")),
                    _optional_int(row.get("total_under_odds")),
                )
            )
        if misses:
            logger.info("bdl_live_parent_miss kind=game_odds count=%s", misses)
        return ready, misses

    @staticmethod
    async def _present_ids(sql: str, values: list, column: str) -> set:
        """Ids that already exist. An empty request does not query."""
        if not values:
            return set()
        found = await db_service.fetch(sql, values)
        return {row[column] for row in found}

    @staticmethod
    async def _write_each(sql: str, args: list[tuple], label: str) -> int:
        """Insert every row. Return how many rows raised.

        One ``executemany`` is the normal path. The conflict target is
        the live tick, so a retry updates the same row. If the batch
        raises, each row is tried alone. A bad row is a counted miss.
        It does not escape this method.
        """
        if not args:
            return 0
        try:
            await db_service.executemany(sql, args)
            return 0
        except Exception as exc:
            logger.warning(
                "bdl live %s batch skipped (%s); retrying per row",
                label,
                type(exc).__name__,
            )
        missed = 0
        for row in args:
            try:
                await db_service.execute(sql, *row)
            except Exception as row_exc:
                missed += 1
                logger.info(
                    "bdl live %s row skipped (%s)",
                    label,
                    type(row_exc).__name__,
                )
        return missed

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
                "nba",
            )
        except Exception as e:
            print(f"⚠️ [OddsSnapshot] Failed writing snapshot log: {e}")

    async def _closing_game_ids_already_stored(
        self,
        game_ids: list[int],
        snapshot_at: datetime,
    ) -> set[int]:
        """Game ids that already have this closing stamp.

        ``_closing_game_ids_already_stored`` looks at
        ``player_prop_snapshots`` and ``game_odds_snapshots`` where
        ``snapshot_kind`` is ``closing``, and at ``odds_line_snapshots``
        for the same instant. The line table has no kind column. This
        stamp is tip minus 10 minutes, so a line row there is this close.
        Call it with the games this minute would fetch. An empty list,
        or a database that is not connected, returns an empty set. A
        read error is logged by exception type and also returns an empty
        set, so the caller still attempts the write.

        Args:
            game_ids: Decimal BALLDONTLIE game ids still in this minute.
            snapshot_at: The shared close time for the minute.

        Returns:
            The subset of ``game_ids`` that already have a stored close.
        """
        if not game_ids or not db_service.is_connected:
            return set()
        text_ids = [str(game_id) for game_id in game_ids]
        try:
            rows = await db_service.fetch(
                """
                SELECT bdl_game_id AS game_id
                FROM player_prop_snapshots
                WHERE league = 'nba'
                  AND snapshot_kind = 'closing'
                  AND snapshot_at = $1
                  AND bdl_game_id = ANY($2::bigint[])
                UNION
                SELECT bdl_game_id AS game_id
                FROM game_odds_snapshots
                WHERE league = 'nba'
                  AND snapshot_kind = 'closing'
                  AND snapshot_at = $1
                  AND bdl_game_id = ANY($2::bigint[])
                UNION
                SELECT event_id::bigint AS game_id
                FROM odds_line_snapshots
                WHERE snapshot_at = $1
                  AND event_id = ANY($3::text[])
                """,
                snapshot_at,
                game_ids,
                text_ids,
            )
        except Exception as exc:
            logger.warning("odds_pretip stored close unread (%s)", type(exc).__name__)
            return set()
        found: set[int] = set()
        for row in rows:
            raw = row["game_id"]
            if isinstance(raw, bool) or raw is None:
                continue
            try:
                found.add(int(raw))
            except (TypeError, ValueError):
                continue
        return found

    async def take_closing_snapshot(
        self,
        slate_date: str,
        tip: datetime,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Save one pre-tip closing line for every game in this tip minute.

        ``take_closing_snapshot`` is the DateTrigger job. It talks to
        BALLDONTLIE only. It does not read ``nba_odds_provider``, so it
        can store a close while the default provider is still The Odds API.

        The Redis lock is ``pretip_lock_key``. A second replica that
        cannot take the lock returns without fetching or writing.
        ``snapshot_at`` is ``tip`` minus 10 minutes for every row in the
        minute. A game that already has a row at that stamp is not
        fetched again, so a later pass does not overwrite the close.

        A game is fetched only when ``closing_game_fate`` returns
        ``keep``: still scheduled, not postponed, and ``now`` is before
        its tip. Props are fetched once per remaining game.
        ``BdlPropsAdapter`` drops a prop whose ``updated_at`` is after
        the tip. Game odds are one ``list_odds`` call for the slate date,
        then filtered to the remaining games. ``odds_line_snapshots``
        is written first. ``player_prop_snapshots`` and
        ``game_odds_snapshots`` use ``_write_bdl_live`` with
        ``snapshot_kind='closing'``. A missing parent is a counted miss.
        It does not raise and it does not undo the line-table write.

        Args:
            slate_date: Eastern game date, ``YYYY-MM-DD``.
            tip: Canonical tip for this minute. The earliest tip in the
                minute is what the planner stores.
            now: Clock for the pre-tip check. None is the current UTC time.
                Tests pass a fixed instant. A naive datetime is UTC.

        Returns:
            ``date``, ``event_count``, ``total_lines``, ``snapshot_at``,
            ``bdl_parent_misses``, ``locked``, and the three skip counts.
        """
        from app.services.cache import cache_service
        from app.services.scheduler import (
            ODDS_PRETIP_LEAD,
            ODDS_PRETIP_LOCK_TTL_SECONDS,
            pretip_hhmm,
            pretip_lock_key,
        )

        moment = _as_utc_now(now)
        stamp = _as_utc_now(tip) - ODDS_PRETIP_LEAD
        hhmm = pretip_hhmm(tip)

        def _result(
            *,
            event_count: int = 0,
            total_lines: int = 0,
            misses: int = 0,
            locked: bool = False,
            skipped_postponed: int = 0,
            skipped_not_scheduled: int = 0,
            skipped_tip_passed: int = 0,
        ) -> dict[str, Any]:
            return {
                "date": slate_date,
                "event_count": event_count,
                "total_lines": total_lines,
                "snapshot_at": stamp.isoformat(),
                "bdl_parent_misses": misses,
                "locked": locked,
                "skipped_postponed": skipped_postponed,
                "skipped_not_scheduled": skipped_not_scheduled,
                "skipped_tip_passed": skipped_tip_passed,
            }

        lock_key = pretip_lock_key(slate_date, tip)
        acquired = await cache_service.acquire_lock(lock_key, ODDS_PRETIP_LOCK_TTL_SECONDS)
        if not acquired:
            logger.info("odds_pretip_locked slate=%s hhmm=%s", slate_date, hhmm)
            return _result(locked=True)

        skipped_postponed = 0
        skipped_not_scheduled = 0
        skipped_tip_passed = 0
        try:
            provider = balldontlie_nba_provider()
            client = provider._require_client()
            try:
                payload = await client.list_games(dates=[slate_date], per_page=100)
            except Exception as exc:
                logger.warning("odds_pretip games skipped (%s)", type(exc).__name__)
                return _result()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                logger.warning("odds_pretip games unreadable")
                return _result()

            pending: list[dict[str, Any]] = []
            for game in data:
                fate = closing_game_fate(game, slate_date=slate_date, hhmm=hhmm, now=moment)
                if fate == "other":
                    continue
                game_id = game.get("id") if isinstance(game, dict) else None
                if fate == "postponed":
                    skipped_postponed += 1
                    logger.info("odds_pretip_skip game_id=%s reason=postponed", game_id)
                    continue
                if fate == "not_scheduled":
                    skipped_not_scheduled += 1
                    status_state = game.get("status_state") if isinstance(game, dict) else None
                    logger.info(
                        "odds_pretip_skip game_id=%s reason=not_scheduled status=%s",
                        game_id,
                        status_state,
                    )
                    continue
                if fate == "tip_passed":
                    skipped_tip_passed += 1
                    logger.info("odds_pretip_skip game_id=%s reason=tip_passed", game_id)
                    continue
                if not isinstance(game_id, int):
                    continue
                pending.append(game)
            stored = await self._closing_game_ids_already_stored(
                [game["id"] for game in pending if isinstance(game.get("id"), int)],
                stamp,
            )
            kept: list[dict[str, Any]] = []
            boards: list[tuple[str, dict[str, Any]]] = []
            all_rows: list[tuple] = []
            for game in pending:
                game_id = game["id"]
                if game_id in stored:
                    logger.info("odds_pretip_skip game_id=%s reason=already_stored", game_id)
                    continue
                kept.append(game)
                provider._games[str(game_id)] = game
                try:
                    body = await provider.get_event_odds(
                        event_id=str(game_id),
                        markets=SNAPSHOT_MARKETS,
                    )
                except Exception as exc:
                    logger.warning(
                        "odds_pretip props skipped game_id=%s (%s)",
                        game_id,
                        type(exc).__name__,
                    )
                    continue
                described = provider._provider_event(game)
                home = described.home_team if described is not None else ""
                away = described.away_team if described is not None else ""
                bookmakers = body.get("bookmakers") if isinstance(body, dict) else None
                if not isinstance(bookmakers, list):
                    bookmakers = []
                payload_body = body if isinstance(body, dict) else {}
                boards.append((str(game_id), payload_body))
                all_rows.extend(
                    self.rows_from_bookmakers(
                        bookmakers,
                        event_id=str(game_id),
                        home_team=home,
                        away_team=away,
                        date=slate_date,
                        snapshot_at=stamp,
                    )
                )

            odds_rows: list[dict[str, Any]] = []
            if kept:
                odds_rows = await self._slate_game_odds(
                    slate_date,
                    {game["id"] for game in kept if isinstance(game.get("id"), int)},
                    client=client,
                )
            misses = 0
            if kept and db_service.is_connected and all_rows:
                await db_service.executemany(UPSERT_LINE_SQL, all_rows)
            if kept and db_service.is_connected:
                try:
                    misses = await self._write_bdl_live(
                        [{"id": str(game["id"])} for game in kept if isinstance(game.get("id"), int)],
                        slate_date,
                        stamp,
                        snapshot_kind="closing",
                        odds_rows=odds_rows,
                        boards=boards,
                    )
                except Exception as exc:
                    misses += 1
                    logger.warning(
                        "odds_pretip closing rows skipped (%s)",
                        type(exc).__name__,
                    )
            return _result(
                event_count=len(kept),
                total_lines=len(all_rows),
                misses=misses,
                skipped_postponed=skipped_postponed,
                skipped_not_scheduled=skipped_not_scheduled,
                skipped_tip_passed=skipped_tip_passed,
            )
        finally:
            await cache_service.release_lock(lock_key)


# Create global service instance
odds_snapshot_service = OddsSnapshotService()
