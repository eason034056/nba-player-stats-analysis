"""QA review for SPO-117: US slate clock, per-line rows, and the posted tie.

Every Odds API body is a recorded fixture from ``tests/fixtures``. Nothing
here types a response shape. A copied event keeps its recorded fields; only
the case being proved is named in each test.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.services.bulk_props import assemble_bulk_props
from app.services.daily_analysis import DailyAnalysisService, _main_line_vote
from app.services.db import SCHEMA_SQL, db_service
from app.services.odds_snapshot_service import (
    OddsSnapshotService,
    nba_slate_date,
    offset_for_us_game_date,
)
from app.services.prob import american_to_prob, calculate_mode_threshold, devig
from tests.fixtures.odds_api import load_odds_fixture

_STAMP = datetime(2026, 11, 9, 22, 5, tzinfo=timezone.utc)
_COLUMNS = (
    "snapshot_at", "date", "event_id", "home_team", "away_team", "player_name",
    "market", "bookmaker", "line", "over_odds", "under_odds", "vig",
    "over_fair_prob", "under_fair_prob",
)
_ODDS_FIXTURES = (
    "odds_api_event_odds__player_points.json",
    "odds_api_event_odds__nba_expanded_markets.json",
)


def _payloads() -> list[dict]:
    return [load_odds_fixture(name) for name in _ODDS_FIXTURES]


def _rows(payload: dict) -> list[dict]:
    return [
        dict(zip(_COLUMNS, row))
        for row in OddsSnapshotService().rows_from_bookmakers(
            payload["bookmakers"],
            event_id=payload["id"],
            home_team=payload["home_team"],
            away_team=payload["away_team"],
            date="2026-11-09",
            snapshot_at=_STAMP,
        )
    ]


def _two_sided_rungs(payload: dict) -> set[tuple[str, str, str, float]]:
    """(player, market, book, point) where the recording priced both sides."""
    sides: dict[tuple[str, str, str, float], set[str]] = defaultdict(set)
    for book in payload["bookmakers"]:
        for market in book.get("markets") or []:
            if market.get("key") == "player_double_double":
                continue
            for outcome in market.get("outcomes") or []:
                if outcome.get("point") is None or not outcome.get("price"):
                    continue
                key = (
                    outcome["description"],
                    market["key"],
                    book["key"],
                    round(float(outcome["point"]), 1),
                )
                sides[key].add(outcome["name"])
    return {key for key, names in sides.items() if {"Over", "Under"} <= names}


# --------------------------------------------------------------- slate clock


@pytest.mark.parametrize(
    ("game_date", "offset"),
    [
        ("2026-10-31", -240),  # last EDT Saturday
        ("2026-11-01", -300),  # fall-back Sunday, noon is EST
        ("2027-03-13", -300),  # last EST Saturday
        ("2027-03-14", -240),  # spring-forward Sunday, noon is EDT
    ],
)
def test_offset_for_us_game_date_across_dst(game_date, offset):
    assert offset_for_us_game_date(game_date) == offset


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        # 00:30 EDT on the fall-back day.
        (datetime(2026, 11, 1, 4, 30, tzinfo=timezone.utc), ("2026-11-01", -240)),
        # 01:30 EST, the repeated hour after the fold.
        (datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc), ("2026-11-01", -300)),
        # 03:30 EDT, after the spring-forward gap.
        (datetime(2027, 3, 14, 7, 30, tzinfo=timezone.utc), ("2027-03-14", -240)),
        # 23:30 EST on the previous Eastern evening, already the next UTC day.
        (datetime(2027, 3, 14, 4, 30, tzinfo=timezone.utc), ("2027-03-13", -300)),
        # A naive datetime is read as UTC.
        (datetime(2026, 11, 10, 3, 0), ("2026-11-09", -300)),
    ],
)
def test_nba_slate_date_at_dst_edges(instant, expected):
    assert nba_slate_date(instant) == expected


@pytest.mark.parametrize("hour", [16, 22])
def test_every_scheduled_job_lands_on_the_same_eastern_day(hour):
    # 16:05 / 22:05 / 23:35 UTC are the three snapshot jobs. In both EST and
    # EDT they are the same Eastern calendar day as the UTC day.
    for day in (datetime(2026, 11, 9), datetime(2027, 3, 15), datetime(2026, 7, 15)):
        for minute in (5, 35):
            instant = day.replace(hour=hour if minute == 5 else 23, minute=minute, tzinfo=timezone.utc)
            assert nba_slate_date(instant)[0] == day.date().isoformat()


@pytest.mark.asyncio
async def test_late_recorded_tip_stays_on_its_eastern_slate(monkeypatch):
    # The recording has a 2026-12-26T03:30:00Z tip: 22:30 EST on 12-25.
    events = load_odds_fixture("odds_api_events__basketball_nba.json")
    late = next(e for e in events if e["commence_time"] == "2026-12-26T03:30:00Z")
    christmas = [
        e["id"]
        for e in events
        if datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        .astimezone(timezone(timedelta(hours=-5)))
        .date()
        .isoformat()
        == "2026-12-25"
    ]
    monkeypatch.setattr(
        "app.services.odds_snapshot_service.odds_provider.get_events",
        AsyncMock(return_value=events),
    )
    service = OddsSnapshotService()
    kept = await service._get_events("2026-12-25", offset_for_us_game_date("2026-12-25"))
    assert late["id"] in [e["id"] for e in kept]
    assert [e["id"] for e in kept] == christmas
    # The next Eastern day does not pick it up again.
    nxt = await service._get_events("2026-12-26", offset_for_us_game_date("2026-12-26"))
    assert late["id"] not in [e["id"] for e in nxt]


@pytest.mark.asyncio
async def test_snapshot_window_matches_daily_analysis_sign_convention(monkeypatch):
    events = load_odds_fixture("odds_api_events__basketball_nba.json")
    calls: list[dict] = []

    async def fake_get_events(**kwargs):
        calls.append(kwargs)
        return events

    monkeypatch.setattr(
        "app.services.odds_snapshot_service.odds_provider.get_events", fake_get_events
    )
    monkeypatch.setattr(
        "app.services.daily_analysis.odds_provider.get_events", fake_get_events
    )
    date, offset = nba_slate_date(_STAMP)
    snap = await OddsSnapshotService()._get_events(date, offset)
    daily = await DailyAnalysisService()._get_events_for_date(date, offset)
    assert [e["id"] for e in snap] == [e["id"] for e in daily]
    assert calls[0]["date_from"] == calls[1]["date_from"]
    assert calls[0]["date_to"] == calls[1]["date_to"]
    # -300 means local midnight is 05:00 UTC; the query widens one hour.
    assert calls[0]["date_from"] == datetime(2026, 11, 9, 4, 0)


@pytest.mark.asyncio
async def test_no_events_is_logged_as_success_on_the_eastern_date(monkeypatch):
    service = OddsSnapshotService()
    get_events = AsyncMock(return_value=[])
    log = AsyncMock()
    monkeypatch.setattr(service, "_get_events", get_events)
    monkeypatch.setattr(service, "_log_snapshot", log)
    monkeypatch.setattr(
        "app.services.odds_snapshot_service.nba_slate_date",
        lambda now=None: ("2026-11-09", -300),
    )
    result = await service.take_snapshot()
    assert result == {"date": "2026-11-09", "event_count": 0, "total_lines": 0, "duration_ms": 0}
    get_events.assert_awaited_once_with("2026-11-09", -300)
    args = log.await_args.args
    assert args[0] == "2026-11-09"
    assert args[4:6] == ("success", "No events")


@pytest.mark.asyncio
async def test_explicit_offset_still_wins_over_the_eastern_default(monkeypatch):
    service = OddsSnapshotService()
    get_events = AsyncMock(return_value=[])
    monkeypatch.setattr(service, "_get_events", get_events)
    monkeypatch.setattr(service, "_log_snapshot", AsyncMock())
    await service.take_snapshot("2026-11-09", tz_offset_minutes=-360)
    get_events.assert_awaited_once_with("2026-11-09", -360)
    get_events.reset_mock()
    await service.take_snapshot("2027-03-14")
    get_events.assert_awaited_once_with("2027-03-14", -240)


# ----------------------------------------------------------------- the rows


@pytest.mark.parametrize("fixture_name", _ODDS_FIXTURES)
def test_one_row_per_two_sided_rung_and_no_duplicate_key(fixture_name):
    payload = load_odds_fixture(fixture_name)
    rows = [r for r in _rows(payload) if r["market"] != "player_double_double"]
    keys = [(r["player_name"], r["market"], r["bookmaker"], r["line"]) for r in rows]
    assert keys
    assert not [k for k, n in Counter(keys).items() if n > 1]
    # Exactly the rungs the recording priced on both sides. One-sided rungs
    # are absent; nothing is invented.
    assert set(keys) == _two_sided_rungs(payload)


@pytest.mark.parametrize("fixture_name", _ODDS_FIXTURES)
def test_each_row_devigs_its_own_rung(fixture_name):
    payload = load_odds_fixture(fixture_name)
    prices: dict[tuple, dict[str, int]] = defaultdict(dict)
    for book in payload["bookmakers"]:
        for market in book.get("markets") or []:
            for outcome in market.get("outcomes") or []:
                if outcome.get("point") is None:
                    continue
                prices[(outcome["description"], market["key"], book["key"], round(float(outcome["point"]), 1))][outcome["name"]] = outcome["price"]
    for row in _rows(payload):
        if row["market"] == "player_double_double":
            continue
        posted = prices[(row["player_name"], row["market"], row["bookmaker"], row["line"])]
        assert row["over_odds"] == posted["Over"]
        assert row["under_odds"] == posted["Under"]
        p_over, p_under = american_to_prob(posted["Over"]), american_to_prob(posted["Under"])
        fair_over, fair_under = devig(p_over, p_under)
        assert row["vig"] == pytest.approx(p_over + p_under - 1, abs=1e-6)
        assert row["over_fair_prob"] == pytest.approx(fair_over, abs=1e-4)
        assert row["under_fair_prob"] == pytest.approx(fair_under, abs=1e-4)
        assert row["over_fair_prob"] + row["under_fair_prob"] == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize("fixture_name", _ODDS_FIXTURES)
def test_stored_ladder_collapses_to_the_same_vote_and_line_as_daily(fixture_name):
    # bulk props reads stored rows; daily analysis reads the live body. With
    # every rung stored, both must still pick the same main line per book
    # and the same consensus for every player on every market.
    payload = load_odds_fixture(fixture_name)
    bulk = assemble_bulk_props(payload["id"], _rows(payload), now=_STAMP)
    service = DailyAnalysisService()
    checked = 0
    for market in bulk.markets:
        if market.market == "player_double_double":
            continue
        books = [
            {**b, "markets": [m for m in b.get("markets") or [] if m.get("key") == market.market]}
            for b in payload["bookmakers"]
        ]
        votes = service._group_main_votes(books)
        for player in market.players:
            per_book = {}
            for b in books:
                outcomes = [
                    o
                    for m in b["markets"]
                    for o in m.get("outcomes") or []
                    if o.get("description") == player.player
                ]
                if outcomes:
                    vote = _main_line_vote(outcomes)
                    if vote is not None:
                        per_book[b["key"]] = vote[0]
            for book in player.books:
                assert book.line == pytest.approx(per_book[book.bookmaker])
            daily_votes = votes[player.player]
            assert player.line == pytest.approx(
                calculate_mode_threshold(
                    [line for line, _ in daily_votes], [d for _, d in daily_votes]
                )
            )
            checked += 1
    assert checked > 10


def test_consensus_is_always_a_posted_vote_and_order_free():
    service = DailyAnalysisService()
    seen = 0
    for payload in _payloads():
        keys = {m["key"] for b in payload["bookmakers"] for m in b.get("markets") or []}
        for key in keys - {"player_double_double"}:
            books = [
                {**b, "markets": [m for m in b.get("markets") or [] if m.get("key") == key]}
                for b in payload["bookmakers"]
            ]
            for player, votes in service._group_main_votes(books).items():
                lines = [line for line, _ in votes]
                dists = [d for _, d in votes]
                mode = calculate_mode_threshold(lines, dists)
                assert mode in {round(x, 1) for x in lines}, (player, key, lines)
                assert calculate_mode_threshold(lines[::-1], dists[::-1]) == mode
                assert calculate_mode_threshold(lines) in {round(x, 1) for x in lines}
                seen += 1
    assert seen > 50


def test_two_book_split_no_longer_averages_to_an_unposted_whole_number():
    # On the expanded recording a two-book split used to average to a whole
    # number (for example Derrick White steals 0.5 / 1.5 -> 1.0).
    payload = load_odds_fixture("odds_api_event_odds__nba_expanded_markets.json")
    books = [
        {**b, "markets": [m for m in b.get("markets") or [] if m.get("key") == "player_steals"]}
        for b in payload["bookmakers"]
    ]
    votes = DailyAnalysisService()._group_main_votes(books)["Derrick White"]
    lines = sorted(line for line, _ in votes)
    assert lines == [0.5, 1.5]
    mode = calculate_mode_threshold([l for l, _ in votes], [d for _, d in votes])
    assert mode in (0.5, 1.5)
    assert mode != 1.0
    best = min(votes, key=lambda v: (v[1], v[0]))
    assert mode == best[0]


# ---------------------------------------------------------------- scheduler


@pytest.mark.asyncio
async def test_manual_trigger_passes_no_utc_date(monkeypatch):
    from app.services import scheduler as sched

    take = AsyncMock(return_value={"date": "2026-11-09", "event_count": 0, "total_lines": 0, "duration_ms": 0})
    monkeypatch.setattr(sched.odds_snapshot_service, "take_snapshot", take)
    svc = sched.SchedulerService()
    await svc.trigger_odds_snapshot_now()
    take.assert_awaited_once_with()
    take.reset_mock()
    await svc.trigger_odds_snapshot_now("2026-11-09")
    take.assert_awaited_once_with("2026-11-09")


@pytest.mark.asyncio
async def test_job_survives_a_re_raised_write_error(monkeypatch):
    from app.services import scheduler as sched

    take = AsyncMock(side_effect=RuntimeError("write failed"))
    monkeypatch.setattr(sched.odds_snapshot_service, "take_snapshot", take)
    await sched.SchedulerService()._run_odds_snapshot_job()
    take.assert_awaited_once_with()


# ---------------------------------------------------------------- migration


@pytest.mark.asyncio
async def test_migration_leaves_pk_and_other_schemas_alone():
    await db_service.init()
    assert db_service.is_connected, "Postgres is required to prove the migration scope"
    try:
        await db_service.execute("DROP SCHEMA IF EXISTS qa_spo117 CASCADE")
        await db_service.execute(
            """
            CREATE SCHEMA qa_spo117;
            CREATE TABLE qa_spo117.odds_line_snapshots (
                id SERIAL PRIMARY KEY,
                snapshot_at TIMESTAMPTZ, event_id TEXT, player_name TEXT,
                market TEXT, bookmaker TEXT,
                UNIQUE (snapshot_at, event_id, player_name, market, bookmaker)
            );
            """
        )
        await db_service.execute(SCHEMA_SQL)
        await db_service.execute(SCHEMA_SQL)
        public = {
            (r["conname"], r["contype"], r["def"])
            for r in await db_service.fetch(
                """
                SELECT conname, contype::text AS contype, pg_get_constraintdef(oid) AS def
                FROM pg_constraint
                WHERE conrelid = 'public.odds_line_snapshots'::regclass
                  AND contype IN ('p', 'u')
                """
            )
        }
        assert {c[1] for c in public} == {"p", "u"}
        assert (
            "odds_line_snapshots_book_line_key",
            "u",
            "UNIQUE (snapshot_at, event_id, player_name, market, bookmaker, line)",
        ) in public
        assert any(c[1] == "p" and c[2] == "PRIMARY KEY (id)" for c in public)
        assert len([c for c in public if c[1] == "u"]) == 1
        other = await db_service.fetch(
            """
            SELECT contype::text AS contype FROM pg_constraint
            WHERE conrelid = 'qa_spo117.odds_line_snapshots'::regclass
            """
        )
        assert sorted(r["contype"] for r in other) == ["p", "u"]
    finally:
        if db_service.is_connected:
            await db_service.execute("DROP SCHEMA IF EXISTS qa_spo117 CASCADE")
            await db_service.close()
