"""QA checks for the SPO-104 no-vig contract and the Pacific game date.

``player-double-double-one-sided.json`` is copied from
``origin/feature/SPO-105-frontend-review-fixes`` at ``bce6f30``
(``frontend/test/fixtures/props-no-vig/player-double-double-one-sided.json``).
The backend tree did not have this file. Posted ``yes_price`` / ``no_price``
values from that file are the gateway input. The HTTP body is the route
response after FastAPI serializes it.

Over/Under prices come from the recorded Odds API body
``backend/tests/fixtures/odds_api_event_odds__player_points.json``.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
for _path in (_BACKEND, _REPO, _REPO / "scripts" / "agents"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.api import nba as nba_api  # noqa: E402
from app.api import wnba as wnba_api  # noqa: E402
from app.middleware.rate_limit import limiter  # noqa: E402
from app.services.cache import CacheService  # noqa: E402
from app.services.csv_player_history import (  # noqa: E402
    _as_us_game_date,
    _coerce_date,
    team_from_game_logs,
)
from app.services.game_log_hygiene import _local_dates  # noqa: E402
from app.services.odds_gateway import MarketSnapshotResult  # noqa: E402
from app.services.odds_snapshot_service import OddsSnapshotService  # noqa: E402
from app.services.prob import (  # noqa: E402
    DEFAULT_BINARY_VIG,
    american_to_prob,
    devig,
    single_leg_devig,
)

_ONE_SIDED = _BACKEND / "tests" / "fixtures" / "player-double-double-one-sided.json"
_PLAYER_POINTS = _BACKEND / "tests" / "fixtures" / "odds_api_event_odds__player_points.json"
_NULL_NO_FIELDS = ("under_odds", "p_under_imp", "no_price", "p_no_imp")
_ROUTES = (
    ("/api/nba/props/no-vig", nba_api),
    ("/api/wnba/props/no-vig", wnba_api),
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bookmakers_from_posted_prices(payload: dict) -> list[dict]:
    """Odds API bookmakers from the posted Yes/No prices on a response fixture.

    A null ``no_price`` is a side the book did not post, so that outcome is
    left off the list. ``under_odds`` on the fixture is a response field and
    is not copied into the gateway payload.
    """
    player = payload["player_name"]
    market = payload["market"]
    books = []
    for row in payload["results"]:
        outcomes = []
        if row.get("yes_price") is not None:
            outcomes.append(
                {"name": "Yes", "description": player, "price": row["yes_price"]}
            )
        if row.get("no_price") is not None:
            outcomes.append(
                {"name": "No", "description": player, "price": row["no_price"]}
            )
        books.append(
            {"key": row["bookmaker"], "markets": [{"key": market, "outcomes": outcomes}]}
        )
    return books


def _snapshot(data: dict, fetched_at: str = "2026-05-08T12:00:00Z") -> MarketSnapshotResult:
    return MarketSnapshotResult(
        data=data,
        fetched_at=datetime.fromisoformat(fetched_at.replace("Z", "+00:00")),
        data_age_seconds=12,
        cache_state="fresh",
        source="snapshot_cache",
    )


@pytest.fixture
def client():
    """HTTP client for the NBA and WNBA routers, with the rate limiter off.

    Redis is not running in this environment. The limiter is not what these
    tests cover.
    """
    limiter.enabled = False
    app = FastAPI()
    app.include_router(nba_api.router)
    app.include_router(wnba_api.router)
    try:
        with TestClient(app) as http:
            yield http
    finally:
        limiter.enabled = True


def _post(http: TestClient, module, path: str, odds: dict, body: dict):
    snapshot = _snapshot(odds, body.get("_fetched_at", "2026-05-08T12:00:00Z"))

    async def _return_snapshot(**kwargs):
        return snapshot

    with patch.object(module.odds_gateway, "get_market_snapshot", new=_return_snapshot):
        return http.post(path, json=body)


@pytest.fixture(scope="module")
def one_sided() -> dict:
    return _load(_ONE_SIDED)


@pytest.fixture(scope="module")
def player_points() -> dict:
    return _load(_PLAYER_POINTS)


@pytest.mark.parametrize(("path", "module"), _ROUTES)
def test_one_sided_dd_http_response_nulls_the_four_no_fields(client, one_sided, path, module):
    """Gateway snapshot through the route JSON for the bce6f30 contract.

    FanDuel posts Yes only. The serialized row must contain the four No-side
    keys, each null. Flags live on the row. Prior flags live on consensus.
    """
    response = _post(
        client,
        module,
        path,
        {"bookmakers": _bookmakers_from_posted_prices(one_sided)},
        {
            "event_id": one_sided["event_id"],
            "player_name": one_sided["player_name"],
            "market": one_sided["market"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    by_book = {row["bookmaker"]: row for row in body["results"]}

    fanduel = by_book["fanduel"]
    for key in _NULL_NO_FIELDS:
        assert key in fanduel
        assert fanduel[key] is None
    assert fanduel["line_is_synthetic"] is True
    assert fanduel["market_kind"] == "binary"
    assert fanduel["uses_prior"] is True
    assert fanduel["vig"] == DEFAULT_BINARY_VIG
    assert fanduel["yes_price"] == one_sided["results"][1]["yes_price"]
    implied = american_to_prob(fanduel["yes_price"])
    assert fanduel["p_under_imp"] != round(1.0 - implied, 4)
    fair_yes = single_leg_devig(implied, DEFAULT_BINARY_VIG)
    assert fanduel["yes_fair_prob"] == round(fair_yes, 4)
    assert fanduel["p_over_fair"] == fanduel["yes_fair_prob"]
    assert fanduel["no_fair_prob"] == round(1.0 - fair_yes, 4)
    assert fanduel["p_under_fair"] == fanduel["no_fair_prob"]

    draftkings = by_book["draftkings"]
    assert draftkings["uses_prior"] is False
    assert draftkings["line_is_synthetic"] is True
    assert draftkings["market_kind"] == "binary"
    assert draftkings["under_odds"] == one_sided["results"][0]["no_price"]
    assert draftkings["no_price"] == one_sided["results"][0]["no_price"]
    assert draftkings["p_under_imp"] == one_sided["results"][0]["p_no_imp"]
    assert draftkings["p_no_imp"] == one_sided["results"][0]["p_no_imp"]
    pair = devig(
        american_to_prob(draftkings["yes_price"]),
        american_to_prob(draftkings["no_price"]),
    )
    assert draftkings["yes_fair_prob"] == round(pair[0], 4)
    assert draftkings["vig"] != DEFAULT_BINARY_VIG

    consensus = body["consensus"]
    assert consensus["consensus_uses_prior"] is True
    assert consensus["consensus_prior_book_count"] == 1
    assert consensus["p_yes_fair"] == one_sided["consensus"]["p_yes_fair"]
    assert consensus["p_no_fair"] == one_sided["consensus"]["p_no_fair"]
    assert "consensus_uses_prior" not in body
    assert "consensus_prior_book_count" not in body
    assert "line_is_synthetic" not in body
    assert "uses_prior" not in body


@pytest.mark.parametrize(("path", "module"), _ROUTES)
def test_yes_only_book_is_its_own_consensus(client, one_sided, path, module):
    fanduel = next(row for row in one_sided["results"] if row["bookmaker"] == "fanduel")
    payload = {
        "event_id": one_sided["event_id"],
        "player_name": one_sided["player_name"],
        "market": one_sided["market"],
        "results": [fanduel],
    }
    response = _post(
        client,
        module,
        path,
        {"bookmakers": _bookmakers_from_posted_prices(payload)},
        {
            "event_id": payload["event_id"],
            "player_name": payload["player_name"],
            "market": payload["market"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 1
    row = body["results"][0]
    for key in _NULL_NO_FIELDS:
        assert key in row and row[key] is None
    assert row["uses_prior"] is True
    assert body["consensus"]["consensus_uses_prior"] is True
    assert body["consensus"]["consensus_prior_book_count"] == 1


@pytest.mark.parametrize(("path", "module"), _ROUTES)
def test_over_under_emits_explicit_false_prior_flags(client, player_points, path, module):
    response = _post(
        client,
        module,
        path,
        player_points,
        {
            "event_id": player_points["id"],
            "player_name": "Jalen Johnson",
            "market": "player_points",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results"]
    for row in body["results"]:
        assert "line_is_synthetic" in row and row["line_is_synthetic"] is False
        assert row["market_kind"] == "over_under"
        assert "uses_prior" in row and row["uses_prior"] is False
        assert row["under_odds"] is not None
        assert row["p_under_imp"] is not None
        assert row["no_price"] is None
        assert row["p_no_imp"] is None
    assert body["consensus"]["consensus_uses_prior"] is False
    assert body["consensus"]["consensus_prior_book_count"] == 0
    assert "consensus_uses_prior" not in body


@pytest.mark.parametrize(("path", "module"), _ROUTES)
def test_missing_consensus_is_json_null(client, one_sided, path, module):
    response = _post(
        client,
        module,
        path,
        {"bookmakers": []},
        {
            "event_id": one_sided["event_id"],
            "player_name": one_sided["player_name"],
            "market": one_sided["market"],
        },
    )
    assert response.status_code == 200, response.text
    raw = response.content.decode().replace(" ", "")
    body = response.json()
    assert '"consensus":null' in raw
    assert "consensus" in body and body["consensus"] is None
    assert body["results"] == []
    assert "consensus_uses_prior" not in body
    assert "consensus_prior_book_count" not in body


@pytest.mark.parametrize(("path", "module"), _ROUTES)
@pytest.mark.xfail(
    strict=True,
    reason="SPO-104 QA: a No outcome with price null raises instead of the one-sided prior",
)
def test_null_no_price_outcome_stays_one_sided(client, one_sided, path, module):
    yes = next(row for row in one_sided["results"] if row["no_price"] is None)
    odds = {
        "bookmakers": [
            {
                "key": yes["bookmaker"],
                "markets": [
                    {
                        "key": one_sided["market"],
                        "outcomes": [
                            {
                                "name": "Yes",
                                "description": one_sided["player_name"],
                                "price": yes["yes_price"],
                            },
                            {
                                "name": "No",
                                "description": one_sided["player_name"],
                                "price": None,
                            },
                        ],
                    }
                ],
            }
        ]
    }
    response = _post(
        client,
        module,
        path,
        odds,
        {
            "event_id": one_sided["event_id"],
            "player_name": one_sided["player_name"],
            "market": one_sided["market"],
        },
    )
    assert response.status_code == 200, response.text
    row = response.json()["results"][0]
    for key in _NULL_NO_FIELDS:
        assert row[key] is None
    assert row["uses_prior"] is True


@pytest.mark.xfail(
    strict=True,
    reason="SPO-104 QA: a null No price crashes the snapshot binary parser",
)
def test_snapshot_parser_treats_null_no_price_as_missing(one_sided):
    yes = next(row for row in one_sided["results"] if row["no_price"] is None)
    market = {
        "key": "player_double_double",
        "outcomes": [
            {
                "name": "Yes",
                "description": one_sided["player_name"],
                "price": yes["yes_price"],
            },
            {
                "name": "No",
                "description": one_sided["player_name"],
                "price": None,
            },
        ],
    }
    rows = OddsSnapshotService()._parse_binary_market(
        market=market,
        market_key="player_double_double",
        bookmaker_key=yes["bookmaker"],
        snapshot_at=datetime(2026, 5, 8, tzinfo=timezone.utc),
        date_obj=date(2026, 5, 8),
        event_id=one_sided["event_id"],
        home_team="Nuggets",
        away_team="Lakers",
    )
    assert len(rows) == 1
    assert rows[0][10] is None


def test_market_quote_skips_a_missing_under_price(player_points):
    from scripts.agents.scoring import compute_scorecard
    from scripts.agents.tools.market import (
        _build_market_quote_for_line,
        _extract_player_lines,
    )

    lines, matched, _candidates, _suggestions = _extract_player_lines(
        player_points, "Jalen Johnson"
    )
    assert matched == "Jalen Johnson"
    same = [dict(row) for row in lines if abs(row["line"] - 20.5) < 1e-9]
    assert len(same) >= 2
    posted = [row["under_odds"] for row in same]
    one_sided = dict(same[0])
    one_sided["under_odds"] = None
    quote = _build_market_quote_for_line([one_sided, same[1]], 20.5, "under")
    assert quote["signal"] == "neutral"
    assert quote["details"]["best_odds"] == same[1]["under_odds"]
    assert quote["details"]["best_book"] == same[1]["bookmaker"]
    assert quote["details"]["best_book"] != one_sided["bookmaker"]

    for row in same:
        row["under_odds"] = None
    missing = _build_market_quote_for_line(same, 20.5, "under")
    assert missing["signal"] == "unavailable"
    assert missing["details"]["pricing_mode"] == "unavailable"
    card = compute_scorecard(
        {},
        {},
        {
            "get_current_market": {"signal": "unavailable", "details": {"n_books": 0}},
            "get_market_quote_for_line": missing,
        },
        direction="under",
    )
    assert card["expected_value_pct"] is None
    assert card["market_implied_probability"] is None
    assert card["best_odds"] is None
    assert posted


@pytest.mark.xfail(
    strict=True,
    reason="SPO-104 QA: a null fair_under crashes the under-side probability average",
)
def test_market_quote_ignores_a_null_fair_under(player_points):
    from scripts.agents.tools.market import (
        _build_market_quote_for_line,
        _extract_player_lines,
    )

    lines, _matched, _candidates, _suggestions = _extract_player_lines(
        player_points, "Jalen Johnson"
    )
    same = [dict(row) for row in lines if abs(row["line"] - 20.5) < 1e-9]
    blank = dict(same[0])
    blank["under_odds"] = None
    blank["fair_under"] = None
    quote = _build_market_quote_for_line([blank, same[1]], 20.5, "under")
    assert quote["signal"] == "neutral"
    assert quote["details"]["best_odds"] == same[1]["under_odds"]
    assert quote["details"]["market_implied_for_query"] == round(same[1]["fair_under"], 4)


def test_open_close_skips_a_null_under_without_raising(player_points):
    from evaluation.odds_history import open_close_from_snapshots
    from scripts.agents.tools.market import _extract_player_lines

    lines, _matched, _candidates, _suggestions = _extract_player_lines(
        player_points, "Jalen Johnson"
    )
    posted = next(row for row in lines if abs(row["line"] - 20.5) < 1e-9)
    kept = {
        "player_name": "Jalen Johnson",
        "date": "2026-11-09",
        "market": "player_points",
        "line": posted["line"],
        "over_odds": posted["over_odds"],
        "under_odds": posted["under_odds"],
        "snapshot_at": "2026-11-09T20:00:00Z",
        "bookmaker": posted["bookmaker"],
    }
    dropped = dict(kept)
    dropped["under_odds"] = None
    dropped["bookmaker"] = "one-sided"
    history = open_close_from_snapshots([kept, dropped], league="nba")
    assert history.skipped_rows == 1
    assert history.active
    quote = history.lookup("nba", "Jalen Johnson", "2026-11-09", "points")
    assert quote is not None
    assert quote.open_under_price == posted["under_odds"]


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@pytest.mark.parametrize(
    ("text", "pacific_day"),
    [
        ("2026-03-16T05:30:00Z", date(2026, 3, 15)),
        ("2026-03-16T06:30:00Z", date(2026, 3, 15)),
        ("2026-01-16T06:30:00Z", date(2026, 1, 15)),
        ("2026-03-16T00:30:00Z", date(2026, 3, 15)),
        ("2026-03-08T09:30:00Z", date(2026, 3, 8)),
        ("2026-03-08T10:30:00Z", date(2026, 3, 8)),
        ("2026-03-09T05:30:00Z", date(2026, 3, 8)),
        ("2026-11-01T08:30:00Z", date(2026, 11, 1)),
        ("2026-11-01T09:30:00Z", date(2026, 11, 1)),
        ("2026-11-02T06:30:00Z", date(2026, 11, 1)),
        ("2026-07-15T05:30:00Z", date(2026, 7, 14)),
        ("2026-11-10T00:10:00Z", date(2026, 11, 9)),
    ],
)
def test_aware_timestamps_use_the_pacific_game_date(text, pacific_day):
    moment = _instant(text)
    assert _as_us_game_date(moment) == pacific_day
    assert _coerce_date(text) == pacific_day
    late_winter_or_summer = text in {
        "2026-03-16T05:30:00Z",
        "2026-01-16T06:30:00Z",
        "2026-11-02T06:30:00Z",
        "2026-07-15T05:30:00Z",
        "2026-03-09T05:30:00Z",
    }
    if late_winter_or_summer:
        eastern = moment.astimezone(ZoneInfo("America/New_York")).date()
        assert eastern == pacific_day + timedelta(days=1)


def test_naive_and_date_only_values_are_not_shifted():
    assert _as_us_game_date(datetime(2026, 3, 16, 5, 30)) == date(2026, 3, 16)
    assert _coerce_date("2026-03-16") == date(2026, 3, 16)
    assert _coerce_date("03/16/2026") == date(2026, 3, 16)
    assert _coerce_date(date(2026, 11, 1)) == date(2026, 11, 1)


def test_wnba_late_tip_uses_the_same_pacific_day():
    logs = [
        {"team": "Aces", "game_date": datetime(2026, 7, 14)},
        {"team": "Mercury", "game_date": datetime(2026, 7, 15)},
    ]
    assert team_from_game_logs(logs, "2026-07-15T05:30:00Z") == "Aces"
    assert team_from_game_logs(logs, "2026-07-15") == "Mercury"


def test_recorded_lakers_hawks_tip_is_the_pacific_date(player_points):
    day = _coerce_date(player_points["commence_time"])
    assert day == date(2026, 11, 9)
    assert CacheService.build_events_key(day.isoformat(), "us") == "events:nba:2026-11-09:us"
    assert (
        CacheService.build_events_key(day.isoformat(), "us", league="wnba")
        == "events:wnba:2026-11-09:us"
    )
    utc_day = player_points["commence_time"][:10]
    assert utc_day == "2026-11-10"
    assert CacheService.build_events_key(utc_day, "us") != CacheService.build_events_key(
        day.isoformat(), "us"
    )


def test_pacific_offset_matches_the_game_date_helper():
    """The events filter uses a caller offset. The matching Pacific offset agrees."""
    cases = (
        ("2026-03-16T05:30:00Z", -420),
        ("2026-01-16T06:30:00Z", -480),
        ("2026-11-02T06:30:00Z", -480),
        ("2026-07-15T05:30:00Z", -420),
    )
    for text, offset in cases:
        moment = _instant(text)
        local = moment + timedelta(minutes=offset)
        assert local.strftime("%Y-%m-%d") == _as_us_game_date(moment).isoformat()


@pytest.mark.xfail(
    strict=True,
    reason="SPO-104 QA: schedule join still indexes the Eastern morning of a late Pacific tip",
)
def test_late_pacific_tip_is_indexed_only_on_the_pacific_date():
    assert _local_dates(_instant("2026-03-16T05:30:00Z")) == {"2026-03-15"}


@pytest.mark.xfail(
    strict=True,
    reason="SPO-104 QA: agent today uses UTC, so 10:30pm Pacific is already the next date",
)
def test_agent_today_matches_the_pacific_game_date(monkeypatch):
    import date_utils
    import tools.historical as historical

    fixed = datetime(2026, 3, 16, 5, 30, tzinfo=timezone.utc)

    class _UTCNow(datetime):
        def astimezone(self, tz=None):
            if tz is None:
                return fixed
            return datetime.astimezone(self, tz)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return _UTCNow(2026, 3, 16, 5, 30, tzinfo=timezone.utc)
            return fixed.astimezone(tz)

    monkeypatch.setattr(date_utils, "datetime", _Clock)
    monkeypatch.setattr(historical, "datetime", _Clock)
    assert date_utils.normalize_date("today") == "2026-03-15"
    assert historical._today_date_string() == "2026-03-15"
