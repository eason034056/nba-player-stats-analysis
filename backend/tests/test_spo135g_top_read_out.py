"""SPO-135g: top_read skips a player the fresh snapshot marks Out.

The cached analysis is built by the daily-analysis service from the
recorded player_points bookmakers. Prices, points, and book keys stay
recorded. Only ``description`` changes, and only when the candidate
has to wear a name the capture does not list. The snapshot rows are
normalized recorded injury entries. Gary Trent Jr. is that Out row
with only ``player`` changed. The injury page has no Gary Trent row.

Historical rates come from the CSV double so the Out name is the
higher probability. The lines do not. A missing or stale snapshot is
not a reason to skip, and this path does not log that fact again.
"""

from __future__ import annotations

import asyncio
import copy
import logging

import pytest

from app.models.schemas import DailyPicksResponse, EventsResponse, NBAEvent
from app.services.cache import CacheService, cache_service
from app.services.daily_analysis import (
    DailyAnalysisService,
    best_top_reads,
    daily_picks_cache_key,
    load_stored_top_reads,
)
from app.services.nba_injuries import NBA_INJURIES_CACHE_KEY
from tests.test_spo111_read_data import (
    _EMPTY_EVENT_ID,
    _EVENT_ID,
    _RECORDED_EVENTS,
    _RECORDED_ODDS,
    _player_names,
)
from tests.test_spo135c_bdl_injury_status import _entry
from tests.test_spo135e_event_reads_injuries import _fresh
from tests.test_spo135e_injury_name_match import _renamed

_DATE = "2026-11-10"
_OFFSET = 480


class _Rates:
    """Historical rates keyed by the name stored on the candidate.

    ``get_player_stats`` is the method ``_analyze_single_event`` calls.
    The name is the argument the CSV service already takes. The rate is
    how this test makes one candidate strictly better than another.
    """

    def __init__(self, rates: dict[str, float]) -> None:
        self._rates = rates

    def get_player_stats(self, player_name: str, **_kwargs):
        rate = self._rates[player_name]
        return {
            "p_over": rate,
            "p_under": 0.2,
            "n_games": 20,
            "game_logs": [{"team": "Hawks", "value": 18}],
        }

    def latest_position(self, _name: str) -> str:
        return "G"


def _books(remap: dict[str, str]) -> list[dict]:
    """Recorded player_points bookmakers, limited to ``remap``.

    Keys are descriptions in the capture. Values are the names stored
    on the candidates. A description that is not a key is dropped.
    Only ``description`` is written, and only when the value differs.
    """
    books = copy.deepcopy(_RECORDED_ODDS["bookmakers"])
    kept_books = []
    for book in books:
        markets = []
        for market in book.get("markets") or []:
            outcomes = []
            for outcome in market.get("outcomes") or []:
                source = outcome.get("description")
                if source not in remap:
                    continue
                row = copy.deepcopy(outcome)
                row["description"] = remap[source]
                outcomes.append(row)
            if outcomes:
                market = dict(market)
                market["outcomes"] = outcomes
                markets.append(market)
        if markets:
            book = dict(book)
            book["markets"] = markets
            kept_books.append(book)
    return kept_books


def _recorded_event(event_id: str) -> dict:
    return next(event for event in _RECORDED_EVENTS if event["id"] == event_id)


def _sources(out_name: str) -> tuple[str, str, str]:
    """Three recorded descriptions that are not the Out name, plus a source to relabel.

    The first recorded description is the one that will wear ``out_name``
    when it is not already that person. The other two stay themselves
    and are not the Out player.
    """
    names = _player_names(_RECORDED_ODDS)
    best_source = names[0]
    others = [name for name in names[1:] if name != out_name]
    assert len(others) >= 2
    return best_source, others[0], others[1]


def _props_for(books: list[dict]):
    """Return the recorded books only for the market they actually contain."""

    async def _inner(_event_id, market, league="nba"):
        if market != "player_points":
            return []
        return books

    return _inner


def _analyze(event: dict, books: list[dict], rates: dict[str, float]):
    service = DailyAnalysisService()
    service._get_props_for_market = _props_for(books)
    service.csv_service = _Rates(rates)
    picks, _players, _props = asyncio.run(
        service._analyze_single_event(
            event_id=event["id"],
            home_team=event["home_team"],
            away_team=event["away_team"],
            commence_time=event["commence_time"],
            league="nba",
        )
    )
    return picks


def _cache(picks) -> dict:
    """The daily-picks cache document ``best_top_reads`` reads.

    ``analyzed_at`` is the cache envelope, not an Odds API field. The
    pick rows are the analysis of the recorded bookmakers.
    """
    return DailyPicksResponse(
        date=_DATE,
        analyzed_at="2026-11-10T17:00:00+00:00",
        total_picks=len(picks),
        picks=list(picks),
    ).model_dump(mode="json")


def _pair(out_name: str):
    """One game whose best candidate wears ``out_name``, plus a healthy game.

    The healthy game is the next recorded event on the same slate. Its
    only candidate is a recorded player who is not ``out_name``.
    """
    best_source, nxt, healthy = _sources(out_name)
    game = _recorded_event(_EVENT_ID)
    other = _recorded_event(_EMPTY_EVENT_ID)
    best_picks = _analyze(
        game,
        _books({best_source: out_name, nxt: nxt}),
        {out_name: 0.91, nxt: 0.72},
    )
    healthy_picks = _analyze(
        other,
        _books({healthy: healthy}),
        {healthy: 0.8},
    )
    picks = best_picks + healthy_picks
    by_name = {pick.player_name: pick for pick in picks}
    assert set(by_name) == {out_name, nxt, healthy}
    assert by_name[out_name].probability > by_name[nxt].probability
    return _cache(picks), nxt, healthy


def test_out_best_candidate_yields_the_next_and_keeps_another_game() -> None:
    """The best stored pick is Out, so the next one on that game is chosen.

    A different game whose player is not Out keeps its own top read.
    """
    out = _entry("Out")
    cached, nxt, healthy = _pair(out["player"])
    reads = best_top_reads(cached, injury_entries=[out])
    assert reads[_EVENT_ID].player == nxt
    assert reads[_EVENT_ID].line == next(
        pick["threshold"]
        for pick in cached["picks"]
        if pick["player_name"] == nxt
    )
    assert reads[_EVENT_ID].market == "player_points"
    assert reads[_EMPTY_EVENT_ID].player == healthy


def test_only_out_candidate_leaves_no_top_read() -> None:
    """When every candidate on the game is Out, that game has no top_read."""
    out = _entry("Out")
    best_source, _nxt, _healthy = _sources(out["player"])
    game = _recorded_event(_EVENT_ID)
    picks = _analyze(
        game,
        _books({best_source: out["player"]}),
        {out["player"]: 0.91},
    )
    assert [pick.player_name for pick in picks] == [out["player"]]
    assert best_top_reads(_cache(picks), injury_entries=[out]) == {}


def test_missing_or_stale_snapshot_keeps_the_out_player(monkeypatch, caplog) -> None:
    """No snapshot, a stale one, and a malformed one do not skip and do not warn."""
    out = _entry("Out")
    cached, _nxt, _healthy = _pair(out["player"])
    assert best_top_reads(cached)[_EVENT_ID].player == out["player"]
    assert best_top_reads(cached, injury_entries=None)[_EVENT_ID].player == out["player"]
    assert best_top_reads(cached, injury_entries=[])[_EVENT_ID].player == out["player"]

    store = {
        daily_picks_cache_key("nba", _DATE, _OFFSET): cached,
    }

    async def fake_get(key):
        return store.get(key)

    monkeypatch.setattr(cache_service, "get", fake_get)
    bodies = [
        None,
        {
            "fetched_at": "2020-01-01T00:00:00+00:00",
            "entries": [out],
        },
        {"fetched_at": "2026-11-11T18:00:00+00:00", "entries": "nope"},
    ]
    with caplog.at_level(logging.WARNING):
        for body in bodies:
            if body is None:
                store.pop(NBA_INJURIES_CACHE_KEY, None)
            else:
                store[NBA_INJURIES_CACHE_KEY] = body
            reads = asyncio.run(load_stored_top_reads(_DATE, _OFFSET))
            assert reads[_EVENT_ID].player == out["player"]
    warnings = [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and "injur" in record.getMessage().lower()
    ]
    assert warnings == []


def test_gary_trent_jr_out_does_not_skip_gary_trent() -> None:
    """A Jr row does not skip the name with the suffix removed.

    The same row does skip the folded full name. Only ``player`` on the
    recorded Out entry is changed.
    """
    junior = _renamed(_entry("Out"), "Gary Trent Jr.")
    best_source, nxt, _healthy = _sources("Gary Trent")
    game = _recorded_event(_EVENT_ID)
    kept = _analyze(
        game,
        _books({best_source: "Gary Trent", nxt: nxt}),
        {"Gary Trent": 0.91, nxt: 0.72},
    )
    reads = best_top_reads(_cache(kept), injury_entries=[junior])
    assert reads[_EVENT_ID].player == "Gary Trent"

    folded = _analyze(
        game,
        _books({best_source: "gary trent jr", nxt: nxt}),
        {"gary trent jr": 0.91, nxt: 0.72},
    )
    reads = best_top_reads(_cache(folded), injury_entries=[junior])
    assert reads[_EVENT_ID].player == nxt


def test_raw_doubtful_stays_the_top_read() -> None:
    """Doubtful is still Questionable on the row. top_read does not add a new block."""
    doubtful = _entry("Questionable", raw="Doubtful")
    assert doubtful["status"] == "Questionable"
    assert doubtful["raw_status"] == "Doubtful"
    cached, _nxt, _healthy = _pair(doubtful["player"])
    reads = best_top_reads(cached, injury_entries=[doubtful])
    assert reads[_EVENT_ID].player == doubtful["player"]


def test_events_route_skips_out_without_calling_balldontlie(monkeypatch) -> None:
    """GET /api/nba/events reads Redis and does not construct a BDL client."""

    class _Boom:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("BDL client constructed on the events path")

    monkeypatch.setattr("app.services.bdl_client.BdlClient", _Boom)
    out = _entry("Out")
    cached, nxt, healthy = _pair(out["player"])
    events = []
    for event_id in (_EVENT_ID, _EMPTY_EVENT_ID):
        raw = _recorded_event(event_id)
        events.append(
            NBAEvent(
                event_id=raw["id"],
                sport_key=raw["sport_key"],
                home_team=raw["home_team"],
                away_team=raw["away_team"],
                commence_time=raw["commence_time"],
            )
        )
    store = {
        f"{CacheService.build_events_key(_DATE, 'us')}:tz{_OFFSET}": EventsResponse(
            date=_DATE,
            events=events,
        ).model_dump(mode="json"),
        daily_picks_cache_key("nba", _DATE, _OFFSET): cached,
        NBA_INJURIES_CACHE_KEY: _fresh([out]),
    }

    async def fake_get(key):
        return store.get(key)

    async def fake_set(key, value, ttl):
        store[key] = value
        return True

    monkeypatch.setattr(cache_service, "get", fake_get)
    monkeypatch.setattr(cache_service, "set", fake_set)

    from app.api.nba import get_events

    response = asyncio.run(get_events(date=_DATE, regions="us", tz_offset=_OFFSET))
    by_id = {event.event_id: event for event in response.events}
    assert by_id[_EVENT_ID].top_read is not None
    assert by_id[_EVENT_ID].top_read.player == nxt
    assert by_id[_EMPTY_EVENT_ID].top_read is not None
    assert by_id[_EMPTY_EVENT_ID].top_read.player == healthy
    assert by_id[_EVENT_ID].top_read.player != out["player"]
