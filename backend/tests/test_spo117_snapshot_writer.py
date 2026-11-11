"""SPO-117: the snapshot writer stores the US slate, including alt lines.

The Odds API bodies are the recorded fixtures. A second bookmaker id on a
copied stored row is a column we set so a mode can tie. It is not a new
odds payload. Prices stay the prices the recording posted.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.services.bulk_props import assemble_bulk_props
from app.services.daily_analysis import (
    DailyAnalysisService,
    _even_money_distance,
    _main_book_line,
)
from app.services.db import SCHEMA_SQL, db_service
from app.services.odds_provider import OddsAPIError
from app.services.odds_snapshot_service import (
    UPSERT_LINE_SQL,
    OddsSnapshotService,
    nba_slate_date,
    offset_for_us_game_date,
)
from app.services.prob import calculate_mode_threshold
from tests.fixtures.odds_api import load_odds_fixture

_EASTERN = ZoneInfo("America/New_York")
_COLUMNS = (
    "snapshot_at",
    "date",
    "event_id",
    "home_team",
    "away_team",
    "player_name",
    "market",
    "bookmaker",
    "line",
    "over_odds",
    "under_odds",
    "vig",
    "over_fair_prob",
    "under_fair_prob",
)
_STAMP = datetime(2026, 11, 9, 22, 5, tzinfo=timezone.utc)
_MIGRATION_EVENT = "spo117-migration"


def _as_dict(row: tuple) -> dict:
    return dict(zip(_COLUMNS, row))


def _with_event(row: tuple, event_id: str) -> tuple:
    values = list(row)
    values[2] = event_id
    return tuple(values)


def _events() -> list[dict]:
    payload = load_odds_fixture("odds_api_events__basketball_nba.json")
    assert isinstance(payload, list) and payload
    return payload


def _points() -> dict:
    payload = load_odds_fixture("odds_api_event_odds__player_points.json")
    assert isinstance(payload, dict) and payload.get("bookmakers")
    return payload


def _hawks(events: list[dict], points: dict) -> dict:
    event = next(
        item
        for item in events
        if item["home_team"] == points["home_team"]
        and item["away_team"] == points["away_team"]
        and item["id"] == points["id"]
    )
    return event


def _tip(event: dict) -> datetime:
    return datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))


def _eastern_ids(events: list[dict], game_date: str) -> list[str]:
    matched = []
    for event in events:
        local = _tip(event).astimezone(_EASTERN).date().isoformat()
        if local == game_date:
            matched.append(event["id"])
    return matched


def _ladder_player(book: dict) -> str:
    counts: Counter[str] = Counter()
    for outcome in book["markets"][0]["outcomes"]:
        if outcome.get("name") != "Over" or outcome.get("point") is None:
            continue
        name = outcome.get("description")
        if isinstance(name, str) and name:
            counts[name] += 1
    player, n_points = counts.most_common(1)[0]
    assert n_points > 1
    return player


def _two_sided_points(book: dict, player: str) -> dict[float, dict[str, dict]]:
    sides: dict[float, dict[str, dict]] = {}
    for outcome in book["markets"][0]["outcomes"]:
        if outcome.get("description") != player or outcome.get("point") is None:
            continue
        point = round(float(outcome["point"]), 1)
        sides.setdefault(point, {})[outcome["name"]] = outcome
    return {
        point: pair
        for point, pair in sides.items()
        if "Over" in pair and "Under" in pair
    }


async def _connect_or_skip() -> None:
    """Open the pool, or skip when this machine has no Postgres.

    ``init`` catches a refused connection and leaves the pool unset.
    CI runs these tests. A checkout without a database skips them.
    """
    await db_service.init()
    if not db_service.is_connected:
        pytest.skip("Postgres is not available")


def _window_contains(call: dict, tip: datetime) -> bool:
    start = call["date_from"].replace(tzinfo=timezone.utc)
    end = call["date_to"].replace(tzinfo=timezone.utc)
    return start <= tip <= end


def test_us_slate_clock_matches_the_recorded_evening():
    mid_job = datetime(2026, 11, 9, 22, 5, tzinfo=timezone.utc)
    assert nba_slate_date(mid_job) == ("2026-11-09", -300)
    # 03:00 UTC is still the previous evening in New York.
    assert nba_slate_date(datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)) == (
        "2026-11-09",
        -300,
    )
    # July is Eastern Daylight Time. Noon on that date picks -240.
    assert nba_slate_date(datetime(2026, 7, 15, 22, 5, tzinfo=timezone.utc)) == (
        "2026-07-15",
        -240,
    )
    assert offset_for_us_game_date("2026-11-09") == -300
    assert offset_for_us_game_date("2026-07-15") == -240


@pytest.mark.asyncio
async def test_taipei_offset_drops_the_recorded_slate_and_eastern_keeps_it(monkeypatch):
    events = _events()
    points = _points()
    hawks = _hawks(events, points)
    tip = _tip(hawks)
    calls: list[dict] = []

    async def fake_get_events(**kwargs):
        calls.append(kwargs)
        return events

    monkeypatch.setattr(
        "app.services.odds_snapshot_service.odds_provider.get_events",
        fake_get_events,
    )
    service = OddsSnapshotService()

    dropped = await service._get_events("2026-11-09", 480)
    assert dropped == []
    assert not _window_contains(calls[-1], tip)

    game_date, offset = nba_slate_date(datetime(2026, 11, 9, 22, 5, tzinfo=timezone.utc))
    kept = await service._get_events(game_date, offset)
    assert _window_contains(calls[-1], tip)
    expected = _eastern_ids(events, game_date)
    assert [event["id"] for event in kept] == expected
    assert hawks["id"] in expected
    assert len(expected) > 1
    later = [
        event["id"]
        for event in events
        if _tip(event).astimezone(_EASTERN).date().isoformat() != game_date
    ]
    assert later
    assert set(later).isdisjoint(expected)


def test_upsert_conflict_target_includes_the_line():
    assert "ON CONFLICT (snapshot_at, event_id, player_name, market, bookmaker, line)" in UPSERT_LINE_SQL
    assert "line = EXCLUDED.line" not in UPSERT_LINE_SQL
    assert "odds_line_snapshots_book_line_key" in SCHEMA_SQL


def test_mode_tie_keeps_a_posted_line_from_the_recorded_ladder():
    points = _points()
    book = next(item for item in points["bookmakers"] if item["key"] == "bovada")
    player = _ladder_player(book)
    posted = sorted(_two_sided_points(book, player))
    assert len(posted) >= 3
    low, mid, high = posted[0], posted[len(posted) // 2], posted[-1]
    assert low < mid < high

    # Every total once. The old even-count path averaged the two central
    # values. Three values used the median. Both stay on the lower posted
    # total now.
    assert calculate_mode_threshold([low, high]) == low
    assert calculate_mode_threshold([low, high]) != pytest.approx((low + high) / 2)
    assert calculate_mode_threshold([low, mid, high]) == low
    assert calculate_mode_threshold([low, mid, high]) != mid

    # A unique mode still wins, even when a neighbor is closer to even money.
    pair = _two_sided_points(book, player)[low]
    distance = _even_money_distance(float(pair["Over"]["price"]), float(pair["Under"]["price"]))
    assert calculate_mode_threshold([low, low, high], [distance, distance, 0.0]) == low

    # Equal distances keep the lower line. A strictly closer higher line wins.
    # A recorded coin-flip rung has distance 0, so the farther vote is then
    # a small positive distance rather than half of zero.
    assert calculate_mode_threshold([low, high], [distance, distance]) == low
    farther = distance if distance > 0 else 0.1
    closer = distance / 2 if distance > 0 else 0.0
    assert calculate_mode_threshold([low, high], [farther, closer]) == high
    assert calculate_mode_threshold([]) is None
    with pytest.raises(ValueError):
        calculate_mode_threshold([low, high], [distance])


def test_bulk_props_votes_the_main_line_then_breaks_a_tie_toward_even_money():
    points = _points()
    service = OddsSnapshotService()
    rows = [
        _as_dict(row)
        for row in service.rows_from_bookmakers(
            points["bookmakers"],
            event_id=points["id"],
            home_team=points["home_team"],
            away_team=points["away_team"],
            date="2026-11-09",
            snapshot_at=_STAMP,
        )
    ]
    book = next(item for item in points["bookmakers"] if item["key"] == "bovada")
    player = _ladder_player(book)
    main_point = _main_book_line(
        [
            outcome
            for outcome in book["markets"][0]["outcomes"]
            if outcome.get("description") == player
        ]
    )
    player_rows = [row for row in rows if row["player_name"] == player]
    bovada_rows = [row for row in player_rows if row["bookmaker"] == "bovada"]
    assert len(bovada_rows) > 1
    assert any(row["line"] == pytest.approx(main_point) for row in bovada_rows)
    assert any(row["line"] != pytest.approx(main_point) for row in bovada_rows)

    payload = assemble_bulk_props(points["id"], rows, now=_STAMP)
    market = next(item for item in payload.markets if item.market == "player_points")
    assembled = next(item for item in market.players if item.player == player)
    bovada_vote = next(item for item in assembled.books if item.bookmaker == "bovada")
    assert bovada_vote.line == pytest.approx(main_point)
    votes = DailyAnalysisService()._group_main_votes(points["bookmakers"])[player]
    assert assembled.bookmakers_count == len(votes) == len(assembled.books)
    assert assembled.line == pytest.approx(
        calculate_mode_threshold(
            [line for line, _distance in votes],
            [distance for _line, distance in votes],
        )
    )
    # The alt ladder is in the stored rows and is not a vote.
    assert len(player_rows) > assembled.bookmakers_count

    # Rebuild the tie from recorded rows: two books on the main total, and
    # the recorded higher total stored twice so the counts match. The second
    # copy keeps that rung's prices and uses another recorded bookmaker key.
    # The higher rung's own book is not one of the two main-line votes, so
    # each book still casts one line.
    higher_rows = [row for row in player_rows if float(row["line"]) > float(main_point) + 0.05]
    assert higher_rows
    higher = min(
        higher_rows,
        key=lambda row: _even_money_distance(row["over_odds"], row["under_odds"]),
    )
    main_rows = [
        row
        for row in player_rows
        if row["line"] == pytest.approx(main_point)
        and row["bookmaker"] != higher["bookmaker"]
    ]
    main_rows = sorted(
        main_rows,
        key=lambda row: _even_money_distance(row["over_odds"], row["under_odds"]),
        reverse=True,
    )[:2]
    assert len(main_rows) == 2
    other_key = next(
        item["key"]
        for item in points["bookmakers"]
        if item["key"] not in {higher["bookmaker"], main_rows[0]["bookmaker"], main_rows[1]["bookmaker"]}
    )
    copied = dict(higher)
    copied["bookmaker"] = other_key
    tied_rows = [main_rows[0], main_rows[1], higher, copied]
    low_distance = min(
        _even_money_distance(row["over_odds"], row["under_odds"]) for row in tied_rows[:2]
    )
    high_distance = _even_money_distance(higher["over_odds"], higher["under_odds"])
    assert high_distance < low_distance
    tied = assemble_bulk_props(points["id"], tied_rows, now=_STAMP)
    tied_player = next(
        item
        for market_item in tied.markets
        for item in market_item.players
        if item.player == player
    )
    assert tied_player.bookmakers_count == 4
    assert tied_player.line == pytest.approx(float(higher["line"]))
    assert tied_player.line != pytest.approx((float(main_point) + float(higher["line"])) / 2)


@pytest.mark.asyncio
async def test_a_failed_write_is_logged_as_an_error(monkeypatch):
    points = _points()
    events = _events()
    hawks = _hawks(events, points)
    service = OddsSnapshotService()
    monkeypatch.setattr(service, "_get_events", AsyncMock(return_value=[hawks]))

    async def fake_snapshot(**kwargs):
        assert kwargs["event_id"] == hawks["id"]
        return SimpleNamespace(data=points)

    monkeypatch.setattr(
        "app.services.odds_snapshot_service.odds_gateway.get_market_snapshot",
        fake_snapshot,
    )

    class RecordingDB:
        def __init__(self):
            self.logs: list[tuple] = []
            self.is_connected = True

        async def executemany(self, query, rows):
            assert rows
            raise RuntimeError("write failed")

        async def execute(self, query, *args):
            self.logs.append(args)

    recording = RecordingDB()
    monkeypatch.setattr("app.services.odds_snapshot_service.db_service", recording)

    with pytest.raises(RuntimeError, match="write failed"):
        await service.take_snapshot("2026-11-09")

    statuses = [args[4] for args in recording.logs]
    assert statuses == ["error"]
    assert "write failed" in recording.logs[0][5]


@pytest.mark.asyncio
async def test_take_snapshot_commits_the_recorded_ladder(monkeypatch):
    events = _events()
    points = _points()
    hawks = _hawks(events, points)
    await _connect_or_skip()
    started = datetime.now(timezone.utc)

    async def fake_get_events(**kwargs):
        assert _window_contains(kwargs, _tip(hawks))
        return events

    async def fake_snapshot(**kwargs):
        if kwargs["event_id"] != hawks["id"]:
            raise OddsAPIError("no recorded odds for this event", 404)
        return SimpleNamespace(data=points)

    monkeypatch.setattr(
        "app.services.odds_snapshot_service.odds_provider.get_events",
        fake_get_events,
    )
    monkeypatch.setattr(
        "app.services.odds_snapshot_service.odds_gateway.get_market_snapshot",
        fake_snapshot,
    )

    try:
        await db_service.execute(
            "DELETE FROM odds_line_snapshots WHERE event_id = $1",
            hawks["id"],
        )
        service = OddsSnapshotService()
        parsed = service.rows_from_bookmakers(
            points["bookmakers"],
            event_id=hawks["id"],
            home_team=hawks["home_team"],
            away_team=hawks["away_team"],
            date="2026-11-09",
            snapshot_at=_STAMP,
        )
        result = await service.take_snapshot("2026-11-09")
        assert result["date"] == "2026-11-09"
        assert result["event_count"] == len(_eastern_ids(events, "2026-11-09"))
        assert result["total_lines"] == len(parsed) > 0

        stored = await db_service.fetch(
            """
            SELECT player_name, bookmaker, line, over_odds, under_odds
            FROM odds_line_snapshots
            WHERE event_id = $1 AND snapshot_at >= $2
            """,
            hawks["id"],
            started,
        )
        assert len(stored) == len(parsed)
        book = next(item for item in points["bookmakers"] if item["key"] == "bovada")
        player = _ladder_player(book)
        posted = _two_sided_points(book, player)
        bovada = [
            row
            for row in stored
            if row["bookmaker"] == "bovada" and row["player_name"] == player
        ]
        assert {round(float(row["line"]), 1) for row in bovada} == set(posted)
        main_point = _main_book_line(
            [
                outcome
                for outcome in book["markets"][0]["outcomes"]
                if outcome.get("description") == player
            ]
        )
        main = next(row for row in bovada if round(float(row["line"]), 1) == main_point)
        assert int(main["over_odds"]) == int(posted[main_point]["Over"]["price"])
        assert int(main["under_odds"]) == int(posted[main_point]["Under"]["price"])
    finally:
        if db_service.is_connected:
            await db_service.execute(
                "DELETE FROM odds_line_snapshots WHERE event_id = $1 AND snapshot_at >= $2",
                hawks["id"],
                started,
            )
            await db_service.execute(
                "DELETE FROM odds_snapshot_logs WHERE snapshot_at >= $1",
                started,
            )
            await db_service.close()


@pytest.mark.asyncio
async def test_line_migration_keeps_existing_rows_and_both_totals():
    points = _points()
    service = OddsSnapshotService()
    parsed = service.rows_from_bookmakers(
        points["bookmakers"],
        event_id=points["id"],
        home_team=points["home_team"],
        away_team=points["away_team"],
        date="2026-11-09",
        snapshot_at=_STAMP,
    )
    book = next(item for item in points["bookmakers"] if item["key"] == "bovada")
    player = _ladder_player(book)
    main_point = _main_book_line(
        [
            outcome
            for outcome in book["markets"][0]["outcomes"]
            if outcome.get("description") == player
        ]
    )
    player_rows = [
        row for row in parsed if row[5] == player and row[7] == "bovada"
    ]
    main = next(row for row in player_rows if round(float(row[8]), 1) == main_point)
    alt = max(
        (row for row in player_rows if round(float(row[8]), 1) != main_point),
        key=lambda row: float(row[8]),
    )
    main = _with_event(main, _MIGRATION_EVENT)
    alt = _with_event(alt, _MIGRATION_EVENT)
    old_upsert = UPSERT_LINE_SQL.replace(
        "ON CONFLICT (snapshot_at, event_id, player_name, market, bookmaker, line)",
        "ON CONFLICT (snapshot_at, event_id, player_name, market, bookmaker)",
    ).replace(
        "DO UPDATE SET\n    over_odds = EXCLUDED.over_odds,",
        "DO UPDATE SET\n    line = EXCLUDED.line,\n    over_odds = EXCLUDED.over_odds,",
    )

    await _connect_or_skip()
    try:
        await db_service.execute(
            "DELETE FROM odds_line_snapshots WHERE event_id = $1",
            _MIGRATION_EVENT,
        )
        await db_service.execute(
            "ALTER TABLE odds_line_snapshots DROP CONSTRAINT IF EXISTS odds_line_snapshots_book_line_key"
        )
        await db_service.execute(
            "ALTER TABLE odds_line_snapshots DROP CONSTRAINT IF EXISTS spo117_old_book_key"
        )
        await db_service.execute(
            """
            ALTER TABLE odds_line_snapshots
            ADD CONSTRAINT spo117_old_book_key
            UNIQUE (snapshot_at, event_id, player_name, market, bookmaker)
            """
        )
        await db_service.executemany(old_upsert, [main])
        await db_service.executemany(old_upsert, [alt])
        overwritten = await db_service.fetch(
            "SELECT line FROM odds_line_snapshots WHERE event_id = $1",
            _MIGRATION_EVENT,
        )
        assert len(overwritten) == 1
        assert float(overwritten[0]["line"]) == pytest.approx(float(alt[8]))

        await db_service.execute(
            "DELETE FROM odds_line_snapshots WHERE event_id = $1",
            _MIGRATION_EVENT,
        )
        await db_service.executemany(old_upsert, [main])
        await db_service.execute(
            """
            CREATE UNIQUE INDEX spo117_old_book_idx
            ON odds_line_snapshots (snapshot_at, event_id, player_name, market, bookmaker)
            """
        )
        await db_service.execute(SCHEMA_SQL)
        index_names = {
            row["index_name"]
            for row in await db_service.fetch(
                """
                SELECT ic.relname AS index_name
                FROM pg_index ix
                JOIN pg_class ic ON ic.oid = ix.indexrelid
                WHERE ix.indrelid = 'odds_line_snapshots'::regclass
                  AND ix.indisunique
                """
            )
        }
        assert "spo117_old_book_idx" not in index_names
        assert "odds_line_snapshots_pkey" in index_names

        names = {
            row["conname"]
            for row in await db_service.fetch(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'odds_line_snapshots'::regclass
                  AND contype = 'u'
                """
            )
        }
        assert names == {"odds_line_snapshots_book_line_key"}
        await db_service.executemany(UPSERT_LINE_SQL, [main, alt])
        kept = await db_service.fetch(
            "SELECT line FROM odds_line_snapshots WHERE event_id = $1 ORDER BY line",
            _MIGRATION_EVENT,
        )
        assert [float(row["line"]) for row in kept] == pytest.approx(
            sorted([float(main[8]), float(alt[8])])
        )
        await db_service.execute(SCHEMA_SQL)
        kept_again = await db_service.fetch(
            "SELECT line FROM odds_line_snapshots WHERE event_id = $1",
            _MIGRATION_EVENT,
        )
        assert len(kept_again) == 2
    finally:
        if db_service.is_connected:
            await db_service.execute(
                "DELETE FROM odds_line_snapshots WHERE event_id = $1",
                _MIGRATION_EVENT,
            )
            await db_service.execute(
                "ALTER TABLE odds_line_snapshots DROP CONSTRAINT IF EXISTS spo117_old_book_key"
            )
            await db_service.execute("DROP INDEX IF EXISTS spo117_old_book_idx")
            await db_service.execute(SCHEMA_SQL)
            await db_service.close()


def _history_rows(player: str) -> list[dict]:
    """Stored rows for one player from the recorded points body."""
    points = _points()
    parsed = OddsSnapshotService().rows_from_bookmakers(
        points["bookmakers"],
        event_id=points["id"],
        home_team=points["home_team"],
        away_team=points["away_team"],
        date="2026-11-09",
        snapshot_at=_STAMP,
    )
    return [
        _as_dict(row)
        for row in parsed
        if row[5] == player and row[6] == "player_points"
    ]


@pytest.mark.asyncio
async def test_history_consensus_averages_one_main_line_per_book(monkeypatch):
    from app.api.odds_history import get_odds_history
    from app.services.bulk_props import _main_book_line as stored_main_line

    # Recorded points ladder: six books, and Bovada posts the alternate rungs.
    player = "Nickeil Alexander-Walker"
    rows = _history_rows(player)
    assert rows
    books: dict[str, list[dict]] = {}
    for row in rows:
        books.setdefault(row["bookmaker"], []).append(row)
    mains = [stored_main_line(group) for group in books.values()]
    main_lines = [float(row["line"]) for row in mains]
    ladder_lines = [float(row["line"]) for row in rows]

    class FakeDB:
        is_connected = True

        async def fetch(self, query, *args):
            return rows

    monkeypatch.setattr("app.api.odds_history.db_service", FakeDB())
    result = await get_odds_history(player, "player_points", "2026-11-09")
    assert result.date == "2026-11-09"
    assert len(result.snapshots) == 1
    snapshot = result.snapshots[0]
    assert len(snapshot.lines) == len(rows) > len(books)
    assert sum(1 for line in snapshot.lines if line.is_main) == len(books)
    consensus = snapshot.consensus
    assert consensus is not None
    assert consensus.bookmaker_count == len(books)
    assert consensus.avg_line == pytest.approx(round(sum(main_lines) / len(main_lines), 2))
    assert consensus.avg_line != pytest.approx(round(sum(ladder_lines) / len(ladder_lines), 2))
    posted = {round(float(row["line"]), 1) for row in rows}
    for line in snapshot.lines:
        if line.is_main:
            assert round(line.line, 1) in posted
    main_over = sum(float(row["over_fair_prob"]) for row in mains) / len(mains)
    assert consensus.over_fair_prob == pytest.approx(round(main_over, 4))


@pytest.mark.asyncio
async def test_omitted_history_date_follows_the_eastern_slate(monkeypatch):
    import app.services.odds_snapshot_service as snap
    from app.api.odds_history import get_odds_history

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            moment = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)
            if tz is not None:
                return moment.astimezone(tz)
            return moment

    monkeypatch.setattr(snap, "datetime", FrozenDateTime)
    seen: dict[str, object] = {}

    class FakeDB:
        is_connected = True

        async def fetch(self, query, *args):
            seen["date"] = args[2]
            return []

    monkeypatch.setattr("app.api.odds_history.db_service", FakeDB())
    result = await get_odds_history("Nickeil Alexander-Walker", "player_points", None)
    assert seen["date"] == datetime(2026, 11, 9).date()
    assert result.date == "2026-11-09"
    assert result.snapshot_count == 0


def test_open_close_uses_the_main_line_not_the_bovada_ladder():
    import sys
    from pathlib import Path

    agents = Path(__file__).resolve().parents[2] / "scripts" / "agents"
    if str(agents) not in sys.path:
        sys.path.insert(0, str(agents))
    from evaluation.odds_history import open_close_from_snapshots

    from app.services.bulk_props import _main_book_line as stored_main_line

    player = "Nickeil Alexander-Walker"
    rows = [row for row in _history_rows(player) if row["bookmaker"] == "bovada"]
    assert len(rows) > 1
    main = stored_main_line(rows)
    snapshots = []
    for stamp in ("2026-11-09T16:05:00Z", "2026-11-09T23:35:00Z"):
        for row in rows:
            snapshots.append(
                {
                    "player_name": player,
                    "date": "2026-11-09",
                    "market": "player_points",
                    "bookmaker": "bovada",
                    "line": row["line"],
                    "over_odds": row["over_odds"],
                    "under_odds": row["under_odds"],
                    "snapshot_at": stamp,
                }
            )
    history = open_close_from_snapshots(snapshots, league="nba", book="bovada")
    quote = history.lookup("nba", player, "2026-11-09", "points")
    assert quote is not None
    assert quote.open_line == pytest.approx(float(main["line"]))
    assert quote.close_line == pytest.approx(float(main["line"]))
    assert quote.open_over_price == int(main["over_odds"])
    assert quote.close_over_price == int(main["over_odds"])
    ends = {round(float(row["line"]), 1) for row in rows}
    low, high = min(ends), max(ends)
    assert low < float(main["line"]) < high
    assert quote.open_line != pytest.approx(low)
    assert quote.close_line != pytest.approx(high)
