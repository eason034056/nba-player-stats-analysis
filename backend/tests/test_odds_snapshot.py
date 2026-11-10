"""
Tests for OddsSnapshotService (app/services/odds_snapshot_service.py)
"""

import copy
import os
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.odds_snapshot_service import OddsSnapshotService, UPSERT_LINE_SQL, INSERT_LOG_SQL
from app.services.odds_provider import OddsAPIError
from tests.fixtures.odds_api import (
    NBA_EXPANDED_MARKETS,
    RECORDED_NBA_EVENTS,
    RECORDED_PLAYER_POINTS,
    first_posted_market,
    load_odds_fixture,
)


# ---------------------------------------------------------------------------
# Helpers — every body starts from a recorded Odds API file.
# ---------------------------------------------------------------------------

def _derive_listed_event(event_id, home, away, commence_time):
    """Copy the first recorded NBA event and override identity and tip time.

    Source: ``odds_api_events__basketball_nba.json[0]`` (Lakers @ Hawks,
    ``2026-11-10T00:10:00Z``). ``sport_key`` and ``sport_title`` stay
    recorded. The four arguments are what ``_get_events`` and
    ``take_snapshot`` read. ``not-a-date`` replaces the recorded
    ``commence_time`` so the parse-skip test has an unparseable clock;
    the rest of the object is still the recorded event.
    """
    recorded = load_odds_fixture(RECORDED_NBA_EVENTS)
    event = copy.deepcopy(recorded[0])
    event["id"] = event_id
    event["home_team"] = home
    event["away_team"] = away
    event["commence_time"] = commence_time
    return event


def _points_snapshot(book_keys: list[str], players: list[str]) -> dict[str, Any]:
    """Recorded ``player_points`` restricted to the named books and players.

    Starts at ``odds_api_event_odds__player_points.json``. Drops every
    other bookmaker and every outcome whose ``description`` is not in
    ``players``. Prices, lines, and the market key stay recorded.
    Book order follows ``book_keys``.
    """
    event = load_odds_fixture(RECORDED_PLAYER_POINTS)
    wanted_players = set(players)
    by_key: dict[str, dict[str, Any]] = {}
    for book in event["bookmakers"]:
        if book.get("key") not in book_keys:
            continue
        kept = copy.deepcopy(book)
        markets = []
        for market in kept.get("markets") or []:
            if market.get("key") != "player_points":
                continue
            market["outcomes"] = [
                outcome
                for outcome in market.get("outcomes") or []
                if outcome.get("description") in wanted_players
            ]
            markets.append(market)
        kept["markets"] = markets
        by_key[kept["key"]] = kept
    missing = [key for key in book_keys if key not in by_key]
    if missing:
        raise AssertionError(f"recorded player_points is missing bookmakers {missing}")
    return {"bookmakers": [by_key[key] for key in book_keys]}


def _drop_outcome_name(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    """Drop outcomes whose ``name`` equals ``name`` (Over or Under)."""
    snapshot = copy.deepcopy(snapshot)
    for book in snapshot["bookmakers"]:
        for market in book["markets"]:
            market["outcomes"] = [
                outcome for outcome in market["outcomes"] if outcome.get("name") != name
            ]
    return snapshot


def _set_outcome_price(snapshot: dict[str, Any], name: str, price: int) -> dict[str, Any]:
    """Set ``price`` on every outcome whose ``name`` equals ``name``."""
    snapshot = copy.deepcopy(snapshot)
    for book in snapshot["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                if outcome.get("name") == name:
                    outcome["price"] = price
    return snapshot


def _clear_points(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Set every outcome ``point`` to None. The rest of the quote stays."""
    snapshot = copy.deepcopy(snapshot)
    for book in snapshot["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                outcome["point"] = None
    return snapshot


def _drop_all_bookmakers(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Derivation: the recorded event with an empty bookmaker list."""
    snapshot = copy.deepcopy(snapshot)
    snapshot["bookmakers"] = []
    return snapshot


def _rebounds_under_only() -> dict[str, Any]:
    """Recorded ``player_rebounds`` with every Over removed.

    Source: ``odds_api_event_odds__nba_expanded_markets.json``, the first
    bookmaker that posts ``player_rebounds`` (FanDuel on the Celtics at
    76ers capture). Under prices, lines, and player names stay recorded.
    Dropping Over is the case ``test_process_event_missing_over`` skips.
    """
    posted = first_posted_market(NBA_EXPANDED_MARKETS, "player_rebounds")
    if posted is None:
        raise AssertionError("player_rebounds is not in the expanded NBA recording")
    book_key, market = posted
    market["outcomes"] = [
        outcome for outcome in market["outcomes"] if outcome.get("name") != "Over"
    ]
    if not market["outcomes"] or any(
        outcome.get("name") != "Under" for outcome in market["outcomes"]
    ):
        raise AssertionError("recorded player_rebounds did not leave an Under")
    return {"bookmakers": [{"key": book_key, "markets": [market]}]}


def _snapshot_result(data):
    """Wrap data in a MarketSnapshotResult-like object."""
    return SimpleNamespace(data=data)


# ---------------------------------------------------------------------------
# 1. take_snapshot with no events returns early with zero counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_take_snapshot_no_events(monkeypatch):
    service = OddsSnapshotService()

    mock_get_events = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "_get_events", mock_get_events)

    mock_log = AsyncMock()
    monkeypatch.setattr(service, "_log_snapshot", mock_log)

    result = await service.take_snapshot("2026-03-01")

    assert result["event_count"] == 0
    assert result["total_lines"] == 0
    assert result["date"] == "2026-03-01"
    mock_log.assert_called_once()
    log_args = mock_log.call_args[0]
    assert log_args[0] == "2026-03-01"  # date
    assert log_args[2] == 0             # event_count
    assert log_args[3] == 0             # total_lines
    assert log_args[4] == "success"


# ---------------------------------------------------------------------------
# 2. take_snapshot with events processes them and writes to DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_take_snapshot_with_events(monkeypatch):
    service = OddsSnapshotService()

    events = [
        _derive_listed_event("evt1", "Lakers", "Celtics", "2026-03-01T02:00:00Z"),
        _derive_listed_event("evt2", "Warriors", "Nets", "2026-03-01T04:00:00Z"),
    ]

    mock_get_events = AsyncMock(return_value=events)
    monkeypatch.setattr(service, "_get_events", mock_get_events)

    # Each _process_event returns 2 fake row tuples
    fake_row = ("snap", "date", "eid", "home", "away", "player", "mkt", "bk",
                24.5, -110, -110, 0.0476, 0.5, 0.5)
    mock_process = AsyncMock(return_value=[fake_row, fake_row])
    monkeypatch.setattr(service, "_process_event", mock_process)

    mock_db = MagicMock()
    mock_db.is_connected = True
    mock_db.executemany = AsyncMock()
    monkeypatch.setattr("app.services.odds_snapshot_service.db_service", mock_db)

    mock_log = AsyncMock()
    monkeypatch.setattr(service, "_log_snapshot", mock_log)

    result = await service.take_snapshot("2026-03-01")

    assert result["event_count"] == 2
    assert result["total_lines"] == 4  # 2 events x 2 rows each
    assert mock_process.call_count == 2
    mock_db.executemany.assert_called_once()
    call_args = mock_db.executemany.call_args
    assert call_args[0][0] == UPSERT_LINE_SQL
    assert len(call_args[0][1]) == 4


# ---------------------------------------------------------------------------
# 3. take_snapshot with DB not connected skips write
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_take_snapshot_db_not_connected(monkeypatch):
    service = OddsSnapshotService()

    events = [_derive_listed_event("evt1", "Lakers", "Celtics", "2026-03-01T02:00:00Z")]
    monkeypatch.setattr(service, "_get_events", AsyncMock(return_value=events))

    fake_row = ("snap", "date", "eid", "home", "away", "player", "mkt", "bk",
                24.5, -110, -110, 0.0476, 0.5, 0.5)
    monkeypatch.setattr(service, "_process_event", AsyncMock(return_value=[fake_row]))

    mock_db = MagicMock()
    mock_db.is_connected = False
    mock_db.executemany = AsyncMock()
    monkeypatch.setattr("app.services.odds_snapshot_service.db_service", mock_db)

    mock_log = AsyncMock()
    monkeypatch.setattr(service, "_log_snapshot", mock_log)

    result = await service.take_snapshot("2026-03-01")

    # DB write should be skipped
    mock_db.executemany.assert_not_called()
    assert result["total_lines"] == 1
    assert result["event_count"] == 1


# ---------------------------------------------------------------------------
# 4. take_snapshot handles event processing errors gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_take_snapshot_event_processing_error(monkeypatch):
    service = OddsSnapshotService()

    events = [
        _derive_listed_event("evt1", "Lakers", "Celtics", "2026-03-01T02:00:00Z"),
        _derive_listed_event("evt2", "Warriors", "Nets", "2026-03-01T04:00:00Z"),
    ]
    monkeypatch.setattr(service, "_get_events", AsyncMock(return_value=events))

    # First event raises, second succeeds
    fake_row = ("snap", "date", "eid", "home", "away", "player", "mkt", "bk",
                24.5, -110, -110, 0.0476, 0.5, 0.5)
    call_count = 0

    async def _process_side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Some error")
        return [fake_row]

    monkeypatch.setattr(service, "_process_event", _process_side_effect)

    mock_db = MagicMock()
    mock_db.is_connected = True
    mock_db.executemany = AsyncMock()
    monkeypatch.setattr("app.services.odds_snapshot_service.db_service", mock_db)

    mock_log = AsyncMock()
    monkeypatch.setattr(service, "_log_snapshot", mock_log)

    result = await service.take_snapshot("2026-03-01")

    # Only second event's row should be written
    assert result["total_lines"] == 1
    assert result["event_count"] == 2


@pytest.mark.asyncio
async def test_take_snapshot_event_404_skipped(monkeypatch):
    """OddsAPIError with 404 is silently skipped (no props data)."""
    service = OddsSnapshotService()

    events = [_derive_listed_event("evt1", "Lakers", "Celtics", "2026-03-01T02:00:00Z")]
    monkeypatch.setattr(service, "_get_events", AsyncMock(return_value=events))

    async def _process_404(**kwargs):
        raise OddsAPIError("Not found", 404)

    monkeypatch.setattr(service, "_process_event", _process_404)

    mock_db = MagicMock()
    mock_db.is_connected = True
    mock_db.executemany = AsyncMock()
    monkeypatch.setattr("app.services.odds_snapshot_service.db_service", mock_db)
    monkeypatch.setattr(service, "_log_snapshot", AsyncMock())

    result = await service.take_snapshot("2026-03-01")

    assert result["total_lines"] == 0
    mock_db.executemany.assert_not_called()


# ---------------------------------------------------------------------------
# 5. _get_events filters events by local date correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_events_filters_by_local_date(monkeypatch):
    service = OddsSnapshotService()

    # UTC+8: 2026-03-01 00:00 local = 2026-02-28 16:00 UTC
    # event at 2026-02-28T17:00Z => local 03-01 01:00 => should be included
    # event at 2026-02-28T15:00Z => local 02-28 23:00 => should be excluded
    raw_events = [
        _derive_listed_event("in_range", "A", "B", "2026-02-28T17:00:00Z"),
        _derive_listed_event("out_range", "C", "D", "2026-02-28T15:00:00Z"),
    ]

    mock_provider = MagicMock()
    mock_provider.get_events = AsyncMock(return_value=raw_events)
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_provider", mock_provider)

    result = await service._get_events("2026-03-01", tz_offset_minutes=480)

    assert len(result) == 1
    assert result[0]["id"] == "in_range"


@pytest.mark.asyncio
async def test_get_events_empty_when_no_events(monkeypatch):
    service = OddsSnapshotService()

    mock_provider = MagicMock()
    mock_provider.get_events = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_provider", mock_provider)

    result = await service._get_events("2026-03-01", tz_offset_minutes=480)

    assert result == []


@pytest.mark.asyncio
async def test_get_events_skips_invalid_commence_time(monkeypatch):
    """Events with unparseable commence_time are silently dropped."""
    service = OddsSnapshotService()

    raw_events = [
        _derive_listed_event("bad", "A", "B", "not-a-date"),
        _derive_listed_event("good", "C", "D", "2026-02-28T18:00:00Z"),
    ]

    mock_provider = MagicMock()
    mock_provider.get_events = AsyncMock(return_value=raw_events)
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_provider", mock_provider)

    result = await service._get_events("2026-03-01", tz_offset_minutes=480)

    assert len(result) == 1
    assert result[0]["id"] == "good"


# ---------------------------------------------------------------------------
# 6. _process_event builds correct row tuples from bookmaker/market/outcome data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_event_builds_correct_rows(monkeypatch):
    service = OddsSnapshotService()

    # DraftKings Luka Doncic in the capture is -113/-113 at 36.5, a
    # symmetric pair, so the fair probabilities are 0.5/0.5.
    snapshot_data = _points_snapshot(["draftkings"], ["Luka Doncic"])
    outcomes = snapshot_data["bookmakers"][0]["markets"][0]["outcomes"]
    over = next(outcome for outcome in outcomes if outcome["name"] == "Over")
    under = next(outcome for outcome in outcomes if outcome["name"] == "Under")
    mock_gateway = MagicMock()
    mock_gateway.get_market_snapshot = AsyncMock(
        return_value=_snapshot_result(snapshot_data)
    )
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway", mock_gateway)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = await service._process_event(
        event_id="evt1",
        home_team="Warriors",
        away_team="Lakers",
        date="2026-03-01",
        snapshot_at=snapshot_at,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row[0] == snapshot_at             # snapshot_at
    assert str(row[1]) == "2026-03-01"       # date (date obj)
    assert row[2] == "evt1"                  # event_id
    assert row[3] == "Warriors"              # home_team
    assert row[4] == "Lakers"                # away_team
    assert row[5] == "Luka Doncic"           # player_name
    assert row[6] == "player_points"         # market
    assert row[7] == "draftkings"            # bookmaker
    assert row[8] == over["point"]           # line, recorded
    assert row[9] == over["price"]           # over_odds, recorded
    assert row[10] == under["price"]         # under_odds, recorded
    assert isinstance(row[11], float)        # vig
    assert isinstance(row[12], float)        # over_fair_prob
    assert isinstance(row[13], float)        # under_fair_prob
    # Symmetric American prices de-vig to 0.5/0.5.
    assert abs(row[12] - 0.5) < 0.01
    assert abs(row[13] - 0.5) < 0.01


@pytest.mark.asyncio
async def test_process_event_multiple_bookmakers_and_players(monkeypatch):
    service = OddsSnapshotService()

    # Both names are on DraftKings and FanDuel in the player_points capture.
    # Other bookmakers in that file are dropped.
    snapshot_data = _points_snapshot(
        ["draftkings", "fanduel"],
        ["Luka Doncic", "Jalen Johnson"],
    )
    mock_gateway = MagicMock()
    mock_gateway.get_market_snapshot = AsyncMock(
        return_value=_snapshot_result(snapshot_data)
    )
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway", mock_gateway)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = await service._process_event(
        event_id="evt1",
        home_team="Warriors",
        away_team="Lakers",
        date="2026-03-01",
        snapshot_at=snapshot_at,
    )

    # Two books, two recorded players, one complete pair each.
    assert len(rows) == 4
    bookmaker_player_pairs = [(r[7], r[5]) for r in rows]
    assert ("draftkings", "Luka Doncic") in bookmaker_player_pairs
    assert ("draftkings", "Jalen Johnson") in bookmaker_player_pairs
    assert ("fanduel", "Luka Doncic") in bookmaker_player_pairs
    assert ("fanduel", "Jalen Johnson") in bookmaker_player_pairs


# ---------------------------------------------------------------------------
# 7. _process_event handles missing over/under pairs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_event_missing_under(monkeypatch):
    """Player with only Over but no Under should be skipped."""
    service = OddsSnapshotService()

    # Derivation: recorded DraftKings Luka Doncic pair, Under removed.
    snapshot_data = _drop_outcome_name(
        _points_snapshot(["draftkings"], ["Luka Doncic"]),
        "Under",
    )
    mock_gateway = MagicMock()
    mock_gateway.get_market_snapshot = AsyncMock(
        return_value=_snapshot_result(snapshot_data)
    )
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway", mock_gateway)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = await service._process_event(
        event_id="evt1",
        home_team="Warriors",
        away_team="Lakers",
        date="2026-03-01",
        snapshot_at=snapshot_at,
    )

    assert len(rows) == 0


@pytest.mark.asyncio
async def test_process_event_missing_over(monkeypatch):
    """Player with only Under but no Over should be skipped."""
    service = OddsSnapshotService()

    # Derivation: recorded FanDuel player_rebounds, Over removed.
    snapshot_data = _rebounds_under_only()
    mock_gateway = MagicMock()
    mock_gateway.get_market_snapshot = AsyncMock(
        return_value=_snapshot_result(snapshot_data)
    )
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway", mock_gateway)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = await service._process_event(
        event_id="evt1",
        home_team="W",
        away_team="L",
        date="2026-03-01",
        snapshot_at=snapshot_at,
    )

    assert len(rows) == 0


# ---------------------------------------------------------------------------
# 8. _process_event skips invalid odds (zero price)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_event_zero_price_skipped(monkeypatch):
    service = OddsSnapshotService()

    # Derivation: recorded DraftKings Luka pair, Over price set to 0.
    snapshot_data = _set_outcome_price(
        _points_snapshot(["draftkings"], ["Luka Doncic"]),
        "Over",
        0,
    )
    mock_gateway = MagicMock()
    mock_gateway.get_market_snapshot = AsyncMock(
        return_value=_snapshot_result(snapshot_data)
    )
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway", mock_gateway)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = await service._process_event(
        event_id="evt1",
        home_team="W",
        away_team="L",
        date="2026-03-01",
        snapshot_at=snapshot_at,
    )

    assert len(rows) == 0


@pytest.mark.asyncio
async def test_process_event_none_line_skipped(monkeypatch):
    """If line (point) is None the row should be skipped."""
    service = OddsSnapshotService()

    # Derivation: recorded DraftKings Luka pair, both points cleared.
    snapshot_data = _clear_points(_points_snapshot(["draftkings"], ["Luka Doncic"]))
    mock_gateway = MagicMock()
    mock_gateway.get_market_snapshot = AsyncMock(
        return_value=_snapshot_result(snapshot_data)
    )
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway", mock_gateway)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = await service._process_event(
        event_id="evt1",
        home_team="W",
        away_team="L",
        date="2026-03-01",
        snapshot_at=snapshot_at,
    )

    assert len(rows) == 0


@pytest.mark.asyncio
async def test_process_event_empty_bookmakers(monkeypatch):
    """No bookmakers in snapshot should produce zero rows."""
    service = OddsSnapshotService()

    # Derivation: recorded DraftKings Luka board with every bookmaker dropped.
    snapshot_data = _drop_all_bookmakers(
        _points_snapshot(["draftkings"], ["Luka Doncic"])
    )
    mock_gateway = MagicMock()
    mock_gateway.get_market_snapshot = AsyncMock(
        return_value=_snapshot_result(snapshot_data)
    )
    monkeypatch.setattr("app.services.odds_snapshot_service.odds_gateway", mock_gateway)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = await service._process_event(
        event_id="evt1",
        home_team="W",
        away_team="L",
        date="2026-03-01",
        snapshot_at=snapshot_at,
    )

    assert rows == []


# ---------------------------------------------------------------------------
# 9. _log_snapshot writes to DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_snapshot_writes_to_db(monkeypatch):
    service = OddsSnapshotService()

    mock_db = MagicMock()
    mock_db.is_connected = True
    mock_db.execute = AsyncMock()
    monkeypatch.setattr("app.services.odds_snapshot_service.db_service", mock_db)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    await service._log_snapshot(
        date="2026-03-01",
        snapshot_at=snapshot_at,
        event_count=5,
        total_lines=100,
        status="success",
        error_message=None,
        duration_ms=1500,
    )

    mock_db.execute.assert_called_once()
    call_args = mock_db.execute.call_args[0]
    assert call_args[0] == INSERT_LOG_SQL
    assert str(call_args[1]) == "2026-03-01"  # date_obj
    assert call_args[2] == snapshot_at
    assert call_args[3] == 5
    assert call_args[4] == 100
    assert call_args[5] == "success"
    assert call_args[6] is None
    assert call_args[7] == 1500


@pytest.mark.asyncio
async def test_log_snapshot_with_error_message(monkeypatch):
    service = OddsSnapshotService()

    mock_db = MagicMock()
    mock_db.is_connected = True
    mock_db.execute = AsyncMock()
    monkeypatch.setattr("app.services.odds_snapshot_service.db_service", mock_db)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    await service._log_snapshot(
        date="2026-03-01",
        snapshot_at=snapshot_at,
        event_count=0,
        total_lines=0,
        status="error",
        error_message="Something went wrong",
        duration_ms=200,
    )

    call_args = mock_db.execute.call_args[0]
    assert call_args[5] == "error"
    assert call_args[6] == "Something went wrong"


@pytest.mark.asyncio
async def test_log_snapshot_db_write_failure_does_not_raise(monkeypatch):
    """_log_snapshot swallows exceptions from db_service.execute."""
    service = OddsSnapshotService()

    mock_db = MagicMock()
    mock_db.is_connected = True
    mock_db.execute = AsyncMock(side_effect=RuntimeError("DB error"))
    monkeypatch.setattr("app.services.odds_snapshot_service.db_service", mock_db)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Should not raise
    await service._log_snapshot(
        date="2026-03-01",
        snapshot_at=snapshot_at,
        event_count=0,
        total_lines=0,
        status="error",
        error_message="test",
        duration_ms=0,
    )


# ---------------------------------------------------------------------------
# 10. _log_snapshot handles DB not connected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_snapshot_db_not_connected(monkeypatch):
    service = OddsSnapshotService()

    mock_db = MagicMock()
    mock_db.is_connected = False
    mock_db.execute = AsyncMock()
    monkeypatch.setattr("app.services.odds_snapshot_service.db_service", mock_db)

    snapshot_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    await service._log_snapshot(
        date="2026-03-01",
        snapshot_at=snapshot_at,
        event_count=0,
        total_lines=0,
        status="success",
        error_message=None,
        duration_ms=0,
    )

    mock_db.execute.assert_not_called()
