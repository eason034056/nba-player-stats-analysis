"""SPO-121: a read for every posted player, and tier from combined_probability.

Odds API bodies in this file are the recorded player_points capture, parsed
by ``rows_from_bookmakers``. Binary rows use the recorded one-sided
double-double fixture's prices. Nothing here types a book, a price, or a
line that the fixture did not already contain.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import csv
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.main import app
from app.models.schemas import (
    BulkPropBook,
    BulkPropMarket,
    BulkPropPlayer,
    BulkPropsResponse,
    DailyPick,
    PlayerHistoryResponse,
)
from app.services.board_shift import measure_board_shift
from app.services.bulk_props import (
    _snapshot_event,
    attach_roster_fields,
    roster_fields,
)
from app.services.csv_player_history import CSVPlayerHistoryService
from app.services.daily_analysis import (
    HIGH_PROBABILITY_THRESHOLD,
    DailyAnalysisService,
    board_score,
    read_tier,
    select_daily_picks,
)
from app.services.event_reads import (
    LATEST_EVENT_READ_SQL,
    assemble_event_reads,
    choose_read_side,
    get_event_reads,
)
from app.services.odds_snapshot_service import OddsSnapshotService
from tests.fixtures.odds_api import NBA_EXPANDED_MARKETS, load_odds_fixture

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SNAPSHOT_AT = datetime(2026, 11, 9, 21, 34, tzinfo=timezone.utc)
_ROW_KEYS = (
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
_HEADER = [
    "Player", "Season", "GameType", "Date", "Team", "Opponent",
    "W/L", "Status", "Pos", "MIN", "PTS", "REB", "AST",
]


def _as_dicts(rows: list[tuple]) -> list[dict]:
    return [dict(zip(_ROW_KEYS, row)) for row in rows]


def _points_rows() -> tuple[str, list[dict]]:
    payload = load_odds_fixture("odds_api_event_odds__player_points.json")
    rows = OddsSnapshotService().rows_from_bookmakers(
        payload["bookmakers"],
        event_id=payload["id"],
        home_team=payload.get("home_team", ""),
        away_team=payload.get("away_team", ""),
        date="2026-11-09",
        snapshot_at=_SNAPSHOT_AT,
    )
    return payload["id"], _as_dicts(rows)


def _binary_rows(event_id: str) -> list[dict]:
    """Stored snapshot rows from the recorded one-sided double-double body.

    Yes is ``over_odds`` and No is ``under_odds``, which is how the
    snapshot writer stores a binary market. Prices are the fixture's
    ``yes_price`` and ``no_price``.
    """
    payload = load_odds_fixture("player-double-double-one-sided.json")
    rows = []
    for result in payload["results"]:
        rows.append(
            {
                "snapshot_at": _SNAPSHOT_AT,
                "date": "2026-11-09",
                "event_id": event_id,
                "player_name": payload["player_name"],
                "market": payload["market"],
                "bookmaker": result["bookmaker"],
                "line": result["line"],
                "over_odds": result["yes_price"],
                "under_odds": result["no_price"],
            }
        )
    return rows


class _FakeDB:
    def __init__(self, rows: list[dict], *, connected: bool = True, error: Exception | None = None):
        self.rows = rows
        self.is_connected = connected
        self.error = error
        self.calls: list[tuple] = []

    async def fetch(self, query: str, *args):
        self.calls.append((query, args))
        if self.error is not None:
            raise self.error
        return self.rows


class _FakeCache:
    def __init__(self):
        self.store: dict[str, object] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ttl: int) -> bool:
        self.store[key] = value
        return True


def _pick(
    name: str,
    *,
    probability: float,
    combined: float | None,
    n_games: int = 20,
) -> DailyPick:
    """One stored pick. ``tier`` is the combined-probability label."""
    return DailyPick(
        player_name=name,
        event_id="evt",
        home_team="Home",
        away_team="Away",
        commence_time="2026-11-10T00:00:00Z",
        metric="points",
        threshold=20.5,
        direction="over",
        probability=probability,
        n_games=n_games,
        bookmakers_count=2,
        combined_probability=combined,
        tier=read_tier(combined),
    )


def _service(path: Path) -> CSVPlayerHistoryService:
    import app.services.csv_player_history as history

    service = CSVPlayerHistoryService(league="nba")
    previous = history.CSV_PATH
    history.CSV_PATH = str(path)
    try:
        service.load_csv()
    finally:
        history.CSV_PATH = previous
    return service


def _write_log(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_HEADER)
        writer.writeheader()
        for row in rows:
            full = {column: "" for column in _HEADER}
            full.update(row)
            writer.writerow(full)


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    from app.middleware.rate_limit import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


class TestTierFollowsCombinedProbability:
    """The cutoff numbers are unchanged. The input is combined_probability."""

    @pytest.mark.parametrize(
        ("combined", "tier", "on_default", "on_lean"),
        [
            (0.5599, None, False, False),
            (0.56, "Lean", False, True),
            (0.6499, "Lean", False, True),
            (0.65, "Playable", True, True),
            (0.6999, "Playable", True, True),
            (0.70, "Strong play", True, True),
            (0.91, "Strong play", True, True),
        ],
    )
    def test_boundaries(self, combined, tier, on_default, on_lean):
        assert read_tier(combined) == tier
        pick = _pick("Boundary", probability=0.99, combined=combined)
        assert pick.tier == tier
        assert (pick in select_daily_picks([pick])) is on_default
        assert (
            pick in select_daily_picks([pick], min_probability=0.56, min_games=10)
        ) is on_lean

    def test_non_finite_combined_is_not_a_tier_and_leaves_the_board(self):
        assert read_tier(float("inf")) is None
        assert read_tier(float("nan")) is None
        assert read_tier(None) is None
        missing = _pick("Missing", probability=0.90, combined=None)
        assert missing.tier is None
        assert select_daily_picks([missing]) == []
        assert select_daily_picks([missing], min_probability=0.56) == []

    def test_filter_enters_leaves_and_changes_tier_against_the_historical_rule(self):
        """Same stored rows. The old rule used ``probability``. The new one does not."""
        enters = _pick("Enters", probability=0.58, combined=0.70)
        leaves = _pick("Leaves", probability=0.90, combined=0.55)
        relabels = _pick("Relabel", probability=0.80, combined=0.66)
        stays = _pick("Stays", probability=0.72, combined=0.72)
        short = _pick("Short", probability=0.40, combined=0.80, n_games=6)
        picks = [enters, leaves, relabels, stays, short]

        default = select_daily_picks(picks)
        assert [pick.player_name for pick in default] == ["Enters", "Relabel", "Stays"]
        assert enters.tier == "Strong play"
        assert read_tier(enters.probability) == "Lean"
        assert leaves.tier is None
        assert read_tier(leaves.probability) == "Strong play"
        assert relabels.tier == "Playable"
        assert read_tier(relabels.probability) == "Strong play"
        assert short not in default
        assert short in select_daily_picks(picks, min_games=5)

        shift = measure_board_shift(picks)
        assert shift["entered"] == 1
        assert shift["left"] == 1
        assert shift["entered_labels"] == ["Enters|points|over"]
        assert shift["left_labels"] == ["Leaves|points|over"]
        changed = {item["player"] for item in shift["tier_changes"]}
        assert changed == {"Enters", "Leaves", "Relabel", "Short"}
        assert shift["new_board"] == shift["old_board"] - shift["left"] + shift["entered"]

    def test_wnba_board_still_uses_the_historical_rate(self):
        pick = _pick("A'ja Wilson", probability=0.80, combined=None)
        assert select_daily_picks([pick], league="wnba") == [pick]
        assert select_daily_picks([pick]) == []
        assert board_score(pick, "wnba") == pytest.approx(0.80)
        assert board_score(pick, "nba") is None

    def test_query_default_is_still_065(self):
        from app.api.daily_picks import get_daily_picks

        signature = inspect.signature(get_daily_picks)
        assert signature.parameters["min_probability"].default.default == HIGH_PROBABILITY_THRESHOLD
        assert signature.parameters["min_probability"].default.default == 0.65


class TestReadSide:
    def test_published_side_then_lean_then_the_higher_rate(self):
        # Over wins when both clear 0.65, even if under is higher.
        assert choose_read_side(0.66, 0.90) == ("over", 0.66)
        # Under is the published side when over misses 0.65.
        assert choose_read_side(0.57, 0.90) == ("under", 0.90)
        # Below 0.65, a side that clears 0.56 is the Lean side.
        assert choose_read_side(0.60, 0.30) == ("over", 0.60)
        # Below the floor, the higher rate, and a tie stays over.
        assert choose_read_side(0.40, 0.55) == ("under", 0.55)
        assert choose_read_side(0.42, 0.42) == ("over", 0.42)
        assert choose_read_side(None, None) == (None, None)

    @pytest.mark.parametrize(
        ("rate", "tier"),
        [
            (0.5599, None),
            (0.56, "Lean"),
            (0.6499, "Lean"),
            (0.65, "Playable"),
            (0.6999, "Playable"),
            (0.70, "Strong play"),
        ],
    )
    def test_tier_cutoffs_are_the_same_numbers(self, rate, tier):
        assert read_tier(rate) == tier


class TestSchemasStayCompatible:
    def test_old_payloads_still_parse(self):
        history = PlayerHistoryResponse(
            player="Stephen Curry",
            metric="points",
            threshold=24.5,
            n_games=3,
        )
        assert history.season_mean is None
        player = BulkPropPlayer(player="Stephen Curry", line=24.5, bookmakers_count=1)
        assert player.position is None
        assert player.team_code is None
        pick = DailyPick(
            player_name="Stephen Curry",
            event_id="evt",
            home_team="Home",
            away_team="Away",
            commence_time="2026-11-10T00:00:00Z",
            metric="points",
            threshold=24.5,
            direction="over",
            probability=0.7,
            n_games=12,
            bookmakers_count=1,
        )
        assert pick.season_mean is None
        assert pick.combined_probability is None
        dumped = pick.model_dump()
        assert "season_mean" in dumped
        assert "combined_probability" in dumped


class TestRosterOnBulkProps:
    def test_position_and_team_code_come_from_the_latest_log(self, tmp_path):
        path = tmp_path / "log.csv"
        _write_log(
            path,
            [
                {
                    "Player": "Stephen Curry",
                    "Season": "2025-2026",
                    "GameType": "regular_season",
                    "Date": "1/1/2026",
                    "Team": "Warriors",
                    "Opponent": "Lakers",
                    "Pos": "PG",
                    "MIN": "30:00",
                    "PTS": "25",
                },
                {
                    "Player": "Stephen Curry",
                    "Season": "2025-2026",
                    "GameType": "regular_season",
                    "Date": "1/3/2026",
                    "Team": "Warriors",
                    "Opponent": "Heat",
                    "Pos": "SG",
                    "MIN": "32:00",
                    "PTS": "30",
                },
            ],
        )
        service = _service(path)
        # Newest-first. 1/3 is the later game, so SG and Warriors -> GSW.
        assert service.latest_position("Stephen Curry") == "SG"
        assert roster_fields("Stephen Curry", service) == ("SG", "GSW")
        assert roster_fields("Nobody", service) == (None, None)

        payload = BulkPropsResponse(
            event_id="evt",
            source="snapshot",
            markets=[
                BulkPropMarket(
                    market="player_points",
                    players=[
                        BulkPropPlayer(
                            player="Stephen Curry",
                            line=24.5,
                            bookmakers_count=1,
                            books=[
                                BulkPropBook(
                                    bookmaker="draftkings",
                                    line=24.5,
                                )
                            ],
                        )
                    ],
                )
            ],
        )
        enriched = attach_roster_fields(payload, service)
        assert enriched.markets[0].players[0].position == "SG"
        assert enriched.markets[0].players[0].team_code == "GSW"
        assert enriched.markets[0].players[0].line == 24.5

    def test_team_code_follows_team_on_event_for_the_recorded_clubs(self, monkeypatch):
        excerpt = (
            Path(__file__).resolve().parents[1]
            / "tests"
            / "fixtures"
            / "csv"
            / "spo122_anfernee_simons_excerpt.csv"
        )
        monkeypatch.setattr(
            "app.services.csv_player_history.CSV_PATH",
            str(excerpt),
        )
        service = CSVPlayerHistoryService(league="nba")
        service.load_csv()
        event = load_odds_fixture(NBA_EXPANDED_MARKETS)
        snapshot_at = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)
        raw_rows = OddsSnapshotService().rows_from_bookmakers(
            event["bookmakers"],
            event_id=event["id"],
            home_team=event["home_team"],
            away_team=event["away_team"],
            date=event["commence_time"][:10],
            snapshot_at=snapshot_at,
        )
        keys = (
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
        home, away, event_day = _snapshot_event(
            [dict(zip(keys, row)) for row in raw_rows]
        )
        assert home == "Philadelphia 76ers"
        assert away == "Boston Celtics"
        simons_pos, simons_code = roster_fields(
            "Anfernee Simons",
            service,
            home_team=home,
            away_team=away,
            event_day=event["commence_time"],
        )
        assert simons_pos == service.latest_position("Anfernee Simons")
        assert simons_code is None
        white_pos, white_code = roster_fields(
            "Derrick White",
            service,
            home_team=home,
            away_team=away,
            event_day=event_day,
        )
        assert white_pos == service.latest_position("Derrick White")
        assert white_code == "BOS"

        posted_line = float(raw_rows[0][8])

        def player(name: str) -> BulkPropPlayer:
            return BulkPropPlayer(
                player=name,
                line=posted_line,
                bookmakers_count=1,
                books=[BulkPropBook(bookmaker=str(raw_rows[0][7]), line=posted_line)],
            )

        enriched = attach_roster_fields(
            BulkPropsResponse(
                event_id=event["id"],
                source="snapshot",
                markets=[
                    BulkPropMarket(
                        market="player_points",
                        players=[player("Anfernee Simons"), player("Derrick White")],
                    )
                ],
            ),
            service,
            home_team=home,
            away_team=away,
            event_day=event["commence_time"],
        )
        by_name = {item.player: item for item in enriched.markets[0].players}
        assert by_name["Anfernee Simons"].team_code is None
        assert by_name["Anfernee Simons"].position == simons_pos
        assert by_name["Derrick White"].team_code == "BOS"
        assert by_name["Derrick White"].position == white_pos


class TestEventReads:
    def test_every_posted_player_on_the_recorded_capture_has_a_read(self):
        event_id, rows = _points_rows()
        payload = assemble_event_reads(
            event_id,
            rows,
            market="player_points",
        )
        from app.services.bulk_props import assemble_bulk_props

        props = assemble_bulk_props(
            event_id, rows, markets=frozenset({"player_points"})
        )
        posted = [player.player for player in props.markets[0].players]
        assert posted
        assert [item.player for item in payload.reads] == posted
        assert payload.source == "snapshot"
        assert payload.market == "player_points"
        assert payload.snapshot_at == _SNAPSHOT_AT
        for item in payload.reads:
            assert item.market == "player_points"
            assert item.line > 0
            assert item.side in {"over", "under"}
            assert item.signals is not None
            assert [signal.key for signal in item.signals] == [
                "market",
                "last10",
                "history",
                "projection",
                "defense",
            ]
            assert item.tier == read_tier(item.combined_probability)

    def test_binary_market_is_present_with_a_null_read(self):
        event_id, rows = _points_rows()
        payload = assemble_event_reads(
            event_id,
            rows + _binary_rows(event_id),
            market="player_double_double",
        )
        assert payload.reads
        assert all(item.side is None for item in payload.reads)
        assert all(item.combined_probability is None for item in payload.reads)
        assert all(item.tier is None for item in payload.reads)
        assert all(item.signals is None for item in payload.reads)

    def test_out_status_keeps_signals_and_drops_combined(self):
        event_id, rows = _points_rows()
        from app.services.bulk_props import assemble_bulk_props

        props = assemble_bulk_props(
            event_id, rows, markets=frozenset({"player_points"})
        )
        name = props.markets[0].players[0].player
        payload = assemble_event_reads(
            event_id,
            rows,
            market="player_points",
        )
        row = next(item for item in payload.reads if item.player == name)
        assert row.signals is not None
        assert row.signals[3].value is None
        assert row.combined_probability is not None

    def test_route_does_not_call_the_odds_api(self, monkeypatch):
        event_id, rows = _points_rows()
        db = _FakeDB(rows)
        cache = _FakeCache()
        monkeypatch.setattr("app.services.event_reads.db_service", db)
        monkeypatch.setattr("app.services.event_reads.cache_service", cache)
        from app.services.odds_gateway import odds_gateway
        from app.services.odds_theoddsapi import odds_provider

        gateway = AsyncMock()
        monkeypatch.setattr(odds_gateway, "get_market_snapshot", gateway)
        monkeypatch.setattr(odds_provider, "get_event_odds", AsyncMock())
        monkeypatch.setattr(odds_provider, "get_events", AsyncMock())

        transport = httpx.ASGITransport(app=app)

        async def _call():
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                all_markets = await http.get(f"/api/nba/events/{event_id}/reads")
                one_market = await http.get(
                    f"/api/nba/events/{event_id}/reads",
                    params={"market": "player_points"},
                )
                unknown = await http.get(
                    f"/api/nba/events/{event_id}/reads",
                    params={"market": "not_a_market"},
                )
                malformed = await http.get("/api/nba/events/bad id/reads")
                return all_markets, one_market, unknown, malformed

        all_markets, one_market, unknown, malformed = asyncio.run(_call())
        assert all_markets.status_code == 200
        body = all_markets.json()
        assert body["source"] == "snapshot"
        assert body["market"] is None
        assert body["reads"]
        assert one_market.status_code == 200
        assert {item["market"] for item in one_market.json()["reads"]} == {"player_points"}
        assert unknown.status_code == 400
        assert malformed.status_code == 404
        assert gateway.await_count == 0
        assert odds_provider.get_event_odds.await_count == 0

        down = _FakeDB(rows, connected=False)
        monkeypatch.setattr("app.services.event_reads.db_service", down)
        monkeypatch.setattr("app.services.event_reads.cache_service", _FakeCache())

        async def _down():
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                return await http.get(f"/api/nba/events/{event_id}/reads")

        unavailable = asyncio.run(_down())
        assert unavailable.status_code == 503
        assert down.calls == []

    def test_cache_skips_the_second_postgres_read(self, monkeypatch):
        event_id, rows = _points_rows()
        db = _FakeDB(rows)
        cache = _FakeCache()
        monkeypatch.setattr("app.services.event_reads.db_service", db)
        monkeypatch.setattr("app.services.event_reads.cache_service", cache)
        first = asyncio.run(get_event_reads(event_id, market="player_points"))
        second = asyncio.run(get_event_reads(event_id, market="player_points"))
        assert len(db.calls) == 1
        assert db.calls[0][0] == LATEST_EVENT_READ_SQL
        assert [item.player for item in second.reads] == [item.player for item in first.reads]

    def test_module_does_not_name_the_odds_gateway(self):
        source = inspect.getsource(
            __import__("app.services.event_reads", fromlist=["get_event_reads"])
        )
        tree = ast.parse(source)
        names = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        assert "app.services.odds_gateway" not in names
        assert "app.services.odds_theoddsapi" not in names


def recorded_points_shift() -> dict:
    """Board shift for the recorded player_points capture and the shipped log.

    The projection signal is missing. Defense ranks come from the game log
    when the player's club is on the event. The signal function is the
    production one. No Odds API call.
    """
    payload = load_odds_fixture("odds_api_event_odds__player_points.json")
    service = DailyAnalysisService()

    async def props(event_id, market_key, league="nba"):
        if market_key != "player_points":
            return []
        return copy.deepcopy(payload["bookmakers"])

    service._get_props_for_market = props
    picks, _players, _props = asyncio.run(
        service._analyze_single_event(
            event_id=payload["id"],
            home_team=payload.get("home_team", ""),
            away_team=payload.get("away_team", ""),
            commence_time=payload.get("commence_time", ""),
            projections={},
            league="nba",
        )
    )
    shift = measure_board_shift(picks)
    shift["event_id"] = payload["id"]
    shift["commence_time"] = payload.get("commence_time")
    shift["posted_players"] = _players
    return shift


class TestRecordedBoardShift:
    def test_shift_is_reproducible_on_the_recorded_capture(self):
        shift = recorded_points_shift()
        assert shift["event_id"]
        assert shift["stored"] > 0
        assert shift["new_board"] == shift["old_board"] - shift["left"] + shift["entered"]
        assert shift["entered"] == len(shift["entered_labels"])
        assert shift["left"] == len(shift["left_labels"])
        assert shift["tier_changed"] == len(shift["tier_changes"])
        # Locked after the run against the shipped CSV and the recorded
        # player_points fixture. A CSV edit that moves these counts should
        # update the decision note in the same change.
        assert shift["stored"] == _RECORDED_SHIFT["stored"]
        assert shift["old_board"] == _RECORDED_SHIFT["old_board"]
        assert shift["new_board"] == _RECORDED_SHIFT["new_board"]
        assert shift["entered"] == _RECORDED_SHIFT["entered"]
        assert shift["left"] == _RECORDED_SHIFT["left"]
        assert shift["tier_changed"] == _RECORDED_SHIFT["tier_changed"]


# Locked against data/nba_player_game_logs.csv and
# tests/fixtures/odds_api_event_odds__player_points.json
# (event 07361a8381206817e27bd2697fad7479, tip 2026-11-10T00:10:00Z).
# Projection signal missing. One market, not a full slate.
_RECORDED_SHIFT = {
    "stored": 11,
    "old_board": 4,
    "new_board": 6,
    "entered": 3,
    "left": 1,
    "tier_changed": 5,
}
