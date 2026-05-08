"""
Tests for OddsSnapshotService (app/services/odds_snapshot_service.py)
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.odds_snapshot_service import OddsSnapshotService, UPSERT_LINE_SQL, INSERT_LOG_SQL
from app.services.odds_provider import OddsAPIError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(event_id, home, away, commence_time):
    """Build a minimal event dict matching The Odds API shape."""
    return {
        "id": event_id,
        "home_team": home,
        "away_team": away,
        "commence_time": commence_time,
    }


def _make_bookmaker(key, markets):
    """Build a bookmaker dict with nested markets/outcomes."""
    return {"key": key, "markets": markets}


def _make_market(key, outcomes):
    return {"key": key, "outcomes": outcomes}


def _make_outcome(description, name, point, price):
    return {
        "description": description,
        "name": name,
        "point": point,
        "price": price,
    }


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
        _make_event("evt1", "Lakers", "Celtics", "2026-03-01T02:00:00Z"),
        _make_event("evt2", "Warriors", "Nets", "2026-03-01T04:00:00Z"),
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

    events = [_make_event("evt1", "Lakers", "Celtics", "2026-03-01T02:00:00Z")]
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
        _make_event("evt1", "Lakers", "Celtics", "2026-03-01T02:00:00Z"),
        _make_event("evt2", "Warriors", "Nets", "2026-03-01T04:00:00Z"),
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

    events = [_make_event("evt1", "Lakers", "Celtics", "2026-03-01T02:00:00Z")]
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
        _make_event("in_range", "A", "B", "2026-02-28T17:00:00Z"),
        _make_event("out_range", "C", "D", "2026-02-28T15:00:00Z"),
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
        _make_event("bad", "A", "B", "not-a-date"),
        _make_event("good", "C", "D", "2026-02-28T18:00:00Z"),
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

    bookmakers_data = [
        _make_bookmaker("draftkings", [
            _make_market("player_points", [
                _make_outcome("Stephen Curry", "Over", 24.5, -110),
                _make_outcome("Stephen Curry", "Under", 24.5, -110),
            ]),
        ]),
    ]

    snapshot_data = {"bookmakers": bookmakers_data}
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
    assert row[5] == "Stephen Curry"         # player_name
    assert row[6] == "player_points"         # market
    assert row[7] == "draftkings"            # bookmaker
    assert row[8] == 24.5                    # line
    assert row[9] == -110                    # over_odds
    assert row[10] == -110                   # under_odds
    # vig & fair probs should be valid floats
    assert isinstance(row[11], float)        # vig
    assert isinstance(row[12], float)        # over_fair_prob
    assert isinstance(row[13], float)        # under_fair_prob
    # For -110/-110, fair probs should each be ~0.5
    assert abs(row[12] - 0.5) < 0.01
    assert abs(row[13] - 0.5) < 0.01


@pytest.mark.asyncio
async def test_process_event_multiple_bookmakers_and_players(monkeypatch):
    service = OddsSnapshotService()

    bookmakers_data = [
        _make_bookmaker("draftkings", [
            _make_market("player_points", [
                _make_outcome("Stephen Curry", "Over", 24.5, -110),
                _make_outcome("Stephen Curry", "Under", 24.5, -110),
                _make_outcome("LeBron James", "Over", 27.5, -115),
                _make_outcome("LeBron James", "Under", 27.5, -105),
            ]),
        ]),
        _make_bookmaker("fanduel", [
            _make_market("player_points", [
                _make_outcome("Stephen Curry", "Over", 24.5, -108),
                _make_outcome("Stephen Curry", "Under", 24.5, -112),
            ]),
        ]),
    ]

    snapshot_data = {"bookmakers": bookmakers_data}
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

    # draftkings: Curry + LeBron = 2, fanduel: Curry = 1 => 3 total
    assert len(rows) == 3
    bookmaker_player_pairs = [(r[7], r[5]) for r in rows]
    assert ("draftkings", "Stephen Curry") in bookmaker_player_pairs
    assert ("draftkings", "LeBron James") in bookmaker_player_pairs
    assert ("fanduel", "Stephen Curry") in bookmaker_player_pairs


# ---------------------------------------------------------------------------
# 7. _process_event handles missing over/under pairs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_event_missing_under(monkeypatch):
    """Player with only Over but no Under should be skipped."""
    service = OddsSnapshotService()

    bookmakers_data = [
        _make_bookmaker("draftkings", [
            _make_market("player_points", [
                _make_outcome("Stephen Curry", "Over", 24.5, -110),
                # No Under for Curry
            ]),
        ]),
    ]

    snapshot_data = {"bookmakers": bookmakers_data}
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

    bookmakers_data = [
        _make_bookmaker("draftkings", [
            _make_market("player_rebounds", [
                _make_outcome("Stephen Curry", "Under", 5.5, -110),
                # No Over for Curry
            ]),
        ]),
    ]

    snapshot_data = {"bookmakers": bookmakers_data}
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

    bookmakers_data = [
        _make_bookmaker("draftkings", [
            _make_market("player_points", [
                _make_outcome("Stephen Curry", "Over", 24.5, 0),
                _make_outcome("Stephen Curry", "Under", 24.5, -110),
            ]),
        ]),
    ]

    snapshot_data = {"bookmakers": bookmakers_data}
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

    bookmakers_data = [
        _make_bookmaker("draftkings", [
            _make_market("player_points", [
                _make_outcome("Stephen Curry", "Over", None, -110),
                _make_outcome("Stephen Curry", "Under", None, -110),
            ]),
        ]),
    ]

    snapshot_data = {"bookmakers": bookmakers_data}
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

    snapshot_data = {"bookmakers": []}
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
