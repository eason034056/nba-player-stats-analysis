"""SPO-137a: NBA picks return BALLDONTLIE's status word as injury_status_raw.

The recorded injury page stores Doubtful as status Questionable and
keeps raw_status Doubtful. The pick copies that raw_status with no
case change and no trimming. injury_status stays the normalized word.
Out still nulls the blend. Doubtful does not. WNBA stays null on both
fields. A stored pick that omits injury_status_raw still validates.

Odds shells are the recorded player_points capture. Only description
changes, and only so a recorded injury name is the posted player.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.api.picks import BotPick
from app.main import app
from app.middleware.rate_limit import limiter
from app.models.schemas import (
    BulkPropPlayer,
    DailyPick,
    DailyPicksResponse,
    NBAEvent,
    PropRead,
    TeamLineup,
    TopRead,
)
from app.services.daily_analysis import (
    daily_analysis_service,
    select_daily_picks,
)
from app.services.nba_injuries import (
    NBA_INJURIES_CACHE_KEY,
    NBA_INJURIES_CACHE_TTL_SECONDS,
    load_nba_pick_injuries,
)
from app.services.pick_signals import build_nba_signals, injury_blocks_combined
from tests.fixtures.odds_api import load_odds_fixture
from tests.test_spo131_bdl_injuries import INJURY_PAGE
from tests.test_spo135c_bdl_injury_status import (
    _board_for,
    _cache,
    _entry,
    _named,
    _picks_for,
)


def _page_status(entry: dict) -> str:
    """The recorded BALLDONTLIE status for this normalized row's player id."""
    wanted = entry["bdl_player_id"]
    for row in INJURY_PAGE["data"]:
        player = row.get("player") or {}
        if isinstance(player, dict) and player.get("id") == wanted:
            status = row.get("status")
            assert isinstance(status, str)
            return status
    raise AssertionError(f"recorded page has no player id {wanted!r}")


def _points(picks, name: str):
    rows = [pick for pick in _named(picks, name) if pick.metric == "points"]
    assert len(rows) == 1
    return rows[0]


def _renamed(entry: dict, player: str) -> dict:
    """Fixture row. Only the stored player name changes."""
    row = dict(entry)
    row["player"] = player
    return row


def test_recorded_doubtful_exposes_the_source_word_and_keeps_the_blend() -> None:
    """A cache Doubtful row is Questionable, and the raw word is Doubtful.

    The blend matches a plain Questionable row. The signal builder does
    not take raw_status. Out is still the only block.
    """
    assert "raw_status" not in inspect.signature(build_nba_signals).parameters
    questionable = _entry("Questionable")
    doubtful = _entry("Questionable", raw="Doubtful")
    assert _page_status(doubtful) == doubtful["raw_status"]
    picks = _picks_for(
        [questionable["player"], doubtful["player"]],
        [questionable, doubtful],
    )
    plain = _points(picks, questionable["player"])
    raw = _points(picks, doubtful["player"])
    assert raw.injury_status == "Questionable"
    assert raw.injury_status == doubtful["status"]
    assert raw.injury_status_raw == doubtful["raw_status"]
    assert raw.injury_status_raw == _page_status(doubtful)
    assert raw.injury_status_raw != raw.injury_status
    assert plain.injury_status == "Questionable"
    assert plain.injury_status_raw == questionable["raw_status"]
    assert plain.injury_status_raw == _page_status(questionable)
    assert raw.combined_probability is not None
    assert raw.combined_probability == plain.combined_probability
    assert injury_blocks_combined(raw.injury_status) is False
    kept = select_daily_picks(
        [raw], min_probability=raw.combined_probability, min_games=10
    )
    assert kept == [raw]
    assert kept[0].injury_status_raw == doubtful["raw_status"]


def test_recorded_passthrough_words_are_copied_verbatim() -> None:
    """Out, Probable, and Day-To-Day keep the recorded spelling.

    Out still nulls the blend and still stays on the board. The other
    two keep a number. None of the words is stripped or recased.
    """
    out = _entry("Out")
    probable = _entry("Probable")
    day = _entry("Day-To-Day")
    picks = _picks_for(
        [out["player"], probable["player"], day["player"]],
        [out, probable, day],
    )
    blocked = _points(picks, out["player"])
    likely = _points(picks, probable["player"])
    listed = _points(picks, day["player"])
    assert blocked.injury_status == "Out"
    assert blocked.injury_status_raw == out["raw_status"]
    assert blocked.injury_status_raw == _page_status(out)
    assert blocked.combined_probability is None
    assert select_daily_picks([blocked]) == [blocked]
    for row, entry in ((likely, probable), (listed, day)):
        assert row.injury_status == entry["status"]
        assert row.injury_status_raw == entry["raw_status"]
        assert row.injury_status_raw == _page_status(entry)
        assert row.injury_status_raw == row.injury_status
        assert row.combined_probability is not None
        assert injury_blocks_combined(row.injury_status) is False


def test_unmatched_and_ambiguous_names_leave_both_fields_null() -> None:
    """A missing name and two ids for one name set neither field.

    The blend stays, because a null status is not Out.
    """
    out = _entry("Out")
    other = _renamed(_entry("Questionable"), out["player"])
    assert out["bdl_player_id"] != other["bdl_player_id"]
    picks = _picks_for([out["player"], "Dyson Daniels"], [out, other])
    ambiguous = _points(picks, out["player"])
    missing = _points(picks, "Dyson Daniels")
    assert ambiguous.injury_status is None
    assert ambiguous.injury_status_raw is None
    assert ambiguous.combined_probability is not None
    assert missing.injury_status is None
    assert missing.injury_status_raw is None
    assert missing.combined_probability is not None


def test_missing_and_stale_snapshots_leave_both_fields_null() -> None:
    """A loader that returns None is the missing, stale, and malformed path."""
    out = _entry("Out")
    absent = _points(_picks_for([out["player"]], None), out["player"])
    assert absent.injury_status is None
    assert absent.injury_status_raw is None

    service, _fake = _cache()
    stale_at = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    asyncio.run(
        service.set(
            NBA_INJURIES_CACHE_KEY,
            {"fetched_at": stale_at, "entries": [out]},
            ttl=NBA_INJURIES_CACHE_TTL_SECONDS,
        )
    )
    loaded = asyncio.run(load_nba_pick_injuries(cache=service))
    assert loaded is None
    stale = _points(_picks_for([out["player"]], loaded), out["player"])
    assert stale.injury_status is None
    assert stale.injury_status_raw is None
    assert stale.combined_probability is not None


def test_wnba_leaves_both_fields_null() -> None:
    """WNBA does not copy the NBA snapshot, including a Doubtful row."""
    doubtful = _entry("Questionable", raw="Doubtful")
    from app.services.daily_analysis import DailyAnalysisService
    import app.services.daily_analysis as daily_analysis
    from tests.test_spo135c_bdl_injury_status import _async_return

    service = DailyAnalysisService()
    service._get_props_for_market = _async_return(_board_for(doubtful["player"]))

    class _WnbaCsv:
        def get_player_stats(self, **_kwargs):
            return {
                "p_over": 0.7,
                "p_under": 0.2,
                "n_games": 20,
                "game_logs": [{"team": "Liberty", "value": 18}],
            }

    original = daily_analysis._resolve_csv_service
    daily_analysis._resolve_csv_service = lambda league: _WnbaCsv()
    try:
        picks, _players, _props = asyncio.run(
            service._analyze_single_event(
                event_id="evt-w",
                home_team="New York Liberty",
                away_team="Connecticut Sun",
                commence_time="2026-06-01T23:00:00Z",
                league="wnba",
                injury_entries=[doubtful],
            )
        )
    finally:
        daily_analysis._resolve_csv_service = original

    assert picks
    row = _points(picks, doubtful["player"])
    assert row.injury_status is None
    assert row.injury_status_raw is None
    assert row.combined_probability is None
    assert row.signals is None
    assert select_daily_picks([row], league="wnba") == [row]


def test_legacy_payload_without_the_field_validates_as_null() -> None:
    """A stored pick from before this field still loads. The raw word is null."""
    payload = {
        "player_name": "Dyson Daniels",
        "event_id": "evt",
        "home_team": "Atlanta Hawks",
        "away_team": "Los Angeles Lakers",
        "commence_time": "2026-11-10T00:10:00Z",
        "metric": "points",
        "threshold": 10.5,
        "direction": "over",
        "probability": 0.72,
        "n_games": 20,
        "bookmakers_count": 1,
        "injury_status": "Questionable",
    }
    parsed = DailyPick.model_validate(payload)
    assert parsed.injury_status == "Questionable"
    assert parsed.injury_status_raw is None
    wrapped = DailyPicksResponse.model_validate(
        {
            "date": "2026-11-10",
            "analyzed_at": "2026-11-11T18:00:00+00:00",
            "total_picks": 1,
            "picks": [payload],
        }
    )
    assert wrapped.picks[0].injury_status_raw is None


def test_cache_document_round_trips_the_raw_word() -> None:
    """The daily-picks cache write is model_dump, and the read validates it."""
    doubtful = _entry("Questionable", raw="Doubtful")
    row = _points(_picks_for([doubtful["player"]], [doubtful]), doubtful["player"])
    document = DailyPicksResponse(
        date="2026-11-10",
        analyzed_at="2026-11-11T18:00:00+00:00",
        total_picks=1,
        picks=[row],
    ).model_dump(mode="json")
    assert document["picks"][0]["injury_status"] == "Questionable"
    assert document["picks"][0]["injury_status_raw"] == doubtful["raw_status"]
    again = DailyPicksResponse.model_validate(document)
    assert again.picks[0].injury_status_raw == doubtful["raw_status"]
    assert again.picks[0].injury_status == "Questionable"


def test_a_row_without_a_source_string_keeps_the_normalized_status() -> None:
    """injury_status stays. A missing raw_status does not invent a source word."""
    from app.services.nba_injuries import matched_injury_words

    out = dict(_entry("Out"))
    recorded = out["raw_status"]
    out["status"] = None
    assert matched_injury_words(out) == (None, None)
    kept = dict(_entry("Out"))
    del kept["raw_status"]
    assert matched_injury_words(kept) == ("Out", None)
    assert recorded == _page_status(_entry("Out"))


def test_nba_cache_keys_are_versioned_and_wnba_keys_are_not() -> None:
    """Old NBA payloads are not read. WNBA key names stay put."""
    from app.services.daily_analysis import daily_picks_cache_key
    from app.services.event_reads import event_reads_cache_key

    assert (
        daily_picks_cache_key("nba", "2026-11-10", 480)
        == "daily_picks:nba:v2:2026-11-10:tz480"
    )
    assert (
        daily_picks_cache_key("NBA", "2026-11-10", -300)
        == "daily_picks:nba:v2:2026-11-10:tz-300"
    )
    assert (
        daily_picks_cache_key("wnba", "2026-11-10", 480)
        == "daily_picks:wnba:2026-11-10:tz480"
    )
    assert "v2" not in daily_picks_cache_key("wnba", "2026-05-14", 0)
    assert (
        event_reads_cache_key("evt-1", "player_points")
        == "nba:event-reads:v2:evt-1:m=player_points"
    )
    assert event_reads_cache_key("evt-1", None) == "nba:event-reads:v2:evt-1:m=*"
    assert "v1" not in event_reads_cache_key("evt-1", None)


def test_nba_flush_clears_versioned_keys_and_leaves_wnba() -> None:
    """``daily_picks:nba:*`` drops v2 and the previous NBA key. WNBA stays."""
    import fnmatch

    from app.services.cache import CacheService

    class _Fake:
        def __init__(self) -> None:
            self.store = {
                "daily_picks:nba:v2:2026-11-10:tz480": "new",
                "daily_picks:nba:2026-11-10:tz480": "old",
                "daily_picks:wnba:2026-11-10:tz480": "wnba",
            }

        async def scan_iter(self, match=None, count=100):
            for key in list(self.store):
                if match is None or fnmatch.fnmatch(key, match):
                    yield key

        async def delete(self, key):
            self.store.pop(key, None)

    service = CacheService()
    fake = _Fake()
    service._client = fake
    deleted = asyncio.run(service.clear_daily_picks_cache(league="nba"))
    assert deleted == 2
    assert fake.store == {"daily_picks:wnba:2026-11-10:tz480": "wnba"}
    wnba_deleted = asyncio.run(service.clear_daily_picks_cache(league="wnba"))
    assert wnba_deleted == 1
    assert fake.store == {}


def test_nba_cache_route_deletes_the_versioned_key(monkeypatch, _open_limiter) -> None:
    """DELETE /api/nba/daily-picks/cache drops the key readers use."""
    deleted: list[str] = []

    async def fake_delete(key):
        deleted.append(key)
        return True

    monkeypatch.setattr("app.api.daily_picks.cache_service.delete", fake_delete)
    result = _delete(
        "/api/nba/daily-picks/cache",
        {"date": "2026-11-10", "tz_offset": 480},
    )
    assert result.status_code == 200
    assert "daily_picks:nba:v2:2026-11-10:tz480" in deleted
    assert "daily_picks:wnba:2026-11-10:tz480" not in deleted


def test_other_response_models_do_not_carry_injury_status() -> None:
    """/reads, top_read, lineups, and the bot pick have no injury field to extend."""
    for model in (PropRead, TopRead, TeamLineup, NBAEvent, BulkPropPlayer, BotPick):
        assert "injury_status" not in model.model_fields
        assert "injury_status_raw" not in model.model_fields


class _Snap:
    def __init__(self, bookmakers):
        self.data = {"bookmakers": bookmakers}


class _Csv:
    def get_player_stats(self, **_kwargs):
        return {
            "p_over": 0.72,
            "p_under": 0.21,
            "n_games": 20,
            "game_logs": [{"team": "Hawks", "value": 18}],
        }

    def latest_position(self, _name: str) -> str:
        return "G"


class _Cache:
    def __init__(self, entries):
        self.store = {
            NBA_INJURIES_CACHE_KEY: {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "entries": entries,
            }
        }

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl):
        self.store[key] = value
        return True


def _books_for(player: str) -> tuple[dict, list]:
    """Recorded event, with one recorded description replaced by ``player``."""
    points = load_odds_fixture("odds_api_event_odds__player_points.json")
    events = load_odds_fixture("odds_api_events__basketball_nba.json")
    event = next(item for item in events if item["id"] == points["id"])
    books = copy.deepcopy(points["bookmakers"])
    source = None
    for book in books:
        for market in book.get("markets") or []:
            for outcome in market.get("outcomes") or []:
                if outcome.get("description"):
                    source = outcome["description"]
                    break
            if source:
                break
        if source:
            break
    assert isinstance(source, str)
    for book in books:
        for market in book.get("markets") or []:
            for outcome in market.get("outcomes") or []:
                if outcome.get("description") == source:
                    outcome["description"] = player
    return event, books


def _install_route(monkeypatch, player: str, entries: list[dict]) -> None:
    event, books = _books_for(player)

    async def get_events(**_kwargs):
        return [event]

    async def snapshot(**kwargs):
        if kwargs.get("markets") == "player_points":
            return _Snap(books)
        return _Snap([])

    monkeypatch.setattr("app.services.daily_analysis.odds_provider.get_events", get_events)
    monkeypatch.setattr(
        "app.services.daily_analysis.odds_gateway.get_market_snapshot", snapshot
    )
    monkeypatch.setattr(
        "app.services.daily_analysis.cache_service", _Cache(entries)
    )
    monkeypatch.setattr(daily_analysis_service, "csv_service", _Csv())


@pytest.fixture
def _open_limiter():
    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


def _request(method: str, path: str, params: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)

    async def _call():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await http.request(method, path, params=params)

    return asyncio.run(_call())


def _get(path: str, params: dict) -> httpx.Response:
    return _request("GET", path, params)


def _delete(path: str, params: dict) -> httpx.Response:
    return _request("DELETE", path, params)


def test_nba_daily_picks_route_returns_both_fields(monkeypatch, _open_limiter) -> None:
    """GET /api/nba/daily-picks returns the normalized word and the source word."""
    doubtful = _entry("Questionable", raw="Doubtful")
    _install_route(monkeypatch, doubtful["player"], [doubtful])
    response = _get(
        "/api/nba/daily-picks",
        {
            "date": "2026-11-10",
            "tz_offset": 480,
            "min_probability": 0.5,
            "min_games": 5,
        },
    )
    assert response.status_code == 200
    body = response.json()
    matched = [row for row in body["picks"] if row["player_name"] == doubtful["player"]]
    assert matched
    assert {row["injury_status"] for row in matched} == {"Questionable"}
    assert {row["injury_status_raw"] for row in matched} == {doubtful["raw_status"]}
    assert all(row["combined_probability"] is not None for row in matched)
    others = [row for row in body["picks"] if row["player_name"] != doubtful["player"]]
    assert others
    assert all(row["injury_status"] is None for row in others)
    assert all(row["injury_status_raw"] is None for row in others)


def test_wnba_daily_picks_route_returns_both_fields_null(monkeypatch, _open_limiter) -> None:
    """GET /api/wnba/daily-picks leaves both fields null beside a Doubtful row."""
    doubtful = _entry("Questionable", raw="Doubtful")
    _install_route(monkeypatch, doubtful["player"], [doubtful])
    import app.services.daily_analysis as daily_analysis

    monkeypatch.setattr(
        daily_analysis, "_resolve_csv_service", lambda _league: _Csv()
    )
    response = _get(
        "/api/wnba/daily-picks",
        {
            "date": "2026-11-10",
            "tz_offset": 480,
            "min_probability": 0.5,
            "min_games": 5,
        },
    )
    assert response.status_code == 200
    body = response.json()
    matched = [row for row in body["picks"] if row["player_name"] == doubtful["player"]]
    assert matched
    assert all(row["injury_status"] is None for row in matched)
    assert all(row["injury_status_raw"] is None for row in matched)
    assert all(row["combined_probability"] is None for row in matched)
