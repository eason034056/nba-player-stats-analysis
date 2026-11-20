"""SPO-130d: BALLDONTLIE odds provider, not wired into NBA by default.

Bodies are the recorded files under tests/fixtures/bdl/. A test that needs
a capture which is not in the tree skips. Nothing here types a BALLDONTLIE
response. One case relabels ``vendor`` on a copy of a recorded row, the
same way other tests relabel a player on a recorded odds body.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fakeredis.aioredis

from app.services.bdl_odds_provider import (
    BdlOddsProvider,
    games_match,
)
from app.services.bdl_player_directory import BdlPlayerDirectory, bdl_player_name
from app.services.bdl_props_adapter import BdlPropsAdapter
from app.services.daily_analysis import DailyAnalysisService
from app.services.odds_gateway import PROVIDERS
from app.services.odds_snapshot_service import SNAPSHOT_MARKETS, OddsSnapshotService
from app.services.odds_theoddsapi import TheOddsAPIProvider
from app.settings import settings

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "bdl"
SAME_SLATE_DIR = Path(__file__).resolve().parent / "fixtures" / "same_slate"
REPO_ROOT = Path(__file__).resolve().parents[2]
RECORD_SCRIPT = REPO_ROOT / "scripts" / "record_bdl_odds_fixtures.py"
BACKEND_APP = Path(__file__).resolve().parents[1] / "app"

# A 429 file exists only after a live 429. The same-slate pair needs ODDS_API_KEY.
MISSING_FIXTURES = (
    "player_props_429.json",
)

SHAI_ID = 175
CLINGAN_ID = 1028025344
OKC_GAME_ID = 21718080
BOS_PHI_GAME_ID = 21718075


def _load(name: str) -> dict:
    """One recorded capture. The file is ``{request, status, response}``."""
    return json.loads((FIXTURE_DIR / name).read_text())


def _rows(name: str) -> list[dict]:
    return list(_load(name)["response"]["data"])


def _names() -> dict[int, str]:
    """Display names from the recorded players page. No alias overrides."""
    names: dict[int, str] = {}
    for player in _load("backend_players_batch45.json")["response"]["data"]:
        names[player["id"]] = bdl_player_name(player)
    return names


def _game(game_id: int, filename: str = "games_2026-11-10.json") -> dict:
    for game in _load(filename)["response"]["data"]:
        if game["id"] == game_id:
            return game
    raise AssertionError(f"{game_id} not in {filename}")


def _tip(game_id: int) -> datetime:
    text = _game(game_id)["datetime"].replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _adapt(
    rows: list[dict] | None = None,
    *,
    tip: datetime | None = None,
    markets: tuple[str, ...] | None = None,
    bookmakers: list[str] | None = None,
) -> tuple[BdlPropsAdapter, list[dict]]:
    adapter = BdlPropsAdapter()
    books = adapter.to_bookmakers(
        _rows("props_live_21718080_OKC@POR_pregame.json") if rows is None else rows,
        _names(),
        game_datetime=tip if tip is not None else _tip(OKC_GAME_ID),
        markets=markets,
        bookmakers=bookmakers,
    )
    return adapter, books


def _only(books: list[dict], market: str) -> list[dict]:
    """One market, so the main-line vote is not mixing points with rebounds."""
    sliced: list[dict] = []
    for book in books:
        markets = [item for item in book["markets"] if item["key"] == market]
        if markets:
            sliced.append({**book, "markets": markets})
    return sliced


def _points_for(books: list[dict], player: str, market: str = "player_points") -> list[float]:
    found: list[float] = []
    for book in _only(books, market):
        for outcome in book["markets"][0]["outcomes"]:
            if outcome["description"] == player and outcome.get("name") == "Over":
                found.append(outcome["point"])
    return found


def _book(books: list[dict], key: str) -> dict | None:
    for book in books:
        if book["key"] == key:
            return book
    return None


class _FixtureClient:
    """Returns recorded ``response`` objects. It does not build a body."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.games = _load("games_2026-11-10.json")["response"]
        self.props = _load("props_live_21718080_OKC@POR_pregame.json")["response"]
        self.players = _load("backend_players_batch45.json")["response"]
        self.limit: int | None = None
        self.remaining: int | None = None
        self.reset: int | None = None

    def rate_status(self) -> dict[str, int | None]:
        return {"limit": self.limit, "remaining": self.remaining, "reset": self.reset}

    async def list_games(self, *, dates: list[str], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_games", list(dates)))
        return self.games

    async def get_player_props(self, *, game_id: int):
        self.calls.append(("get_player_props", game_id))
        return self.props

    async def list_players(self, *, player_ids: list[int], per_page: int = 100, cursor: int | None = None):
        self.calls.append(("list_players", list(player_ids)))
        wanted = set(player_ids)
        data = [player for player in self.players["data"] if player["id"] in wanted]
        return {"data": data, "meta": dict(self.players.get("meta") or {})}


def _provider(client: _FixtureClient | None = None) -> tuple[BdlOddsProvider, _FixtureClient]:
    fixture = client or _FixtureClient()
    directory = BdlPlayerDirectory(fixture, aliases={})
    return BdlOddsProvider(fixture, directory=directory), fixture


class TestAdapterRules:
    """Dedupe, drops, and the bookmaker shape the existing parsers read."""

    def test_output_passes_the_existing_parsers(self):
        names = _names()
        shai = names[SHAI_ID]
        _adapter, books = _adapt()
        points = _only(books, "player_points")
        votes = DailyAnalysisService()._group_props_by_player(points)
        assert shai in votes
        assert 10.5 not in votes[shai]
        assert 33.5 in votes[shai]

        rows = OddsSnapshotService().rows_from_bookmakers(
            points,
            event_id="21718080",
            home_team="Portland Trail Blazers",
            away_team="Oklahoma City Thunder",
            date="2026-11-10",
            snapshot_at=datetime(2026, 11, 11, 3, 55, tzinfo=timezone.utc),
        )
        shai_lines = [row[8] for row in rows if row[5] == shai]
        assert shai_lines
        assert 10.5 not in shai_lines
        assert 33.5 in shai_lines
        # Over and under are the recorded prices, not a made-up pair.
        source = next(
            row
            for row in _rows("props_live_21718080_OKC@POR_pregame.json")
            if row["player_id"] == SHAI_ID
            and row["vendor"] == "draftkings"
            and row["prop_type"] == "points"
            and row["market"]["type"] == "over_under"
        )
        draftkings = next(
            row for row in rows if row[5] == shai and row[7] == "draftkings" and row[6] == "player_points"
        )
        assert draftkings[8] == float(source["line_value"])
        assert draftkings[9] == source["market"]["over_odds"]
        assert draftkings[10] == source["market"]["under_odds"]

    def test_bally_bet_fake_line_is_dropped_and_betparx_keeps_the_real_line(self):
        names = _names()
        shai = names[SHAI_ID]
        clingan = names[CLINGAN_ID]
        adapter, books = _adapt(markets=("player_points",))
        assert adapter.fake_points_dropped > 0
        assert _book(books, "ballybet") is None
        betparx = _book(books, "betparx")
        assert betparx is not None
        shai_points = _points_for([betparx], shai)
        assert shai_points == [33.5]
        clingan_points = _points_for([betparx], clingan)
        assert clingan_points == [10.5]
        assert 2.5 not in clingan_points
        # One source: the pair does not cast two votes.
        votes = DailyAnalysisService()._group_props_by_player(books)
        assert 10.5 not in votes[shai]
        assert 33.5 in votes[shai]
        assert "ballybet" not in {book["key"] for book in books}

    def test_bally_bet_filter_uses_the_paired_book_and_the_real_line(self):
        names = _names()
        _adapter, books = _adapt(
            markets=("player_points",),
            bookmakers=["bally_bet"],
        )
        assert [book["key"] for book in books] == ["betparx"]
        assert _points_for(books, names[SHAI_ID]) == [33.5]

    def test_betway_milestones_contribute_no_vote(self):
        _adapter, books = _adapt()
        assert _book(books, "betway") is None
        points = _only(books, "player_points")
        votes = DailyAnalysisService()._group_main_votes(points)
        assert votes
        for book in books:
            assert book["key"] != "betway"

    def test_double_double_is_yes_only(self):
        names = _names()
        source = next(
            row
            for row in _rows("props_live_21718080_OKC@POR_pregame.json")
            if row["prop_type"] == "double_double" and row["vendor"] == "caesars"
        )
        player = names[source["player_id"]]
        _adapter, books = _adapt(markets=("player_double_double",))
        caesars = _book(books, "caesars")
        assert caesars is not None
        matched = [
            outcome
            for outcome in caesars["markets"][0]["outcomes"]
            if outcome["description"] == player
        ]
        assert len(matched) == 1
        assert matched[0]["name"] == "Yes"
        assert matched[0]["price"] == source["market"]["odds"]
        assert "point" not in matched[0]
        assert all(outcome["name"] == "Yes" for outcome in caesars["markets"][0]["outcomes"])

        rows = OddsSnapshotService().rows_from_bookmakers(
            books,
            event_id="21718080",
            home_team="Portland Trail Blazers",
            away_team="Oklahoma City Thunder",
            date="2026-11-10",
            snapshot_at=datetime(2026, 11, 11, 3, 55, tzinfo=timezone.utc),
        )
        stored = next(row for row in rows if row[5] == player and row[7] == "caesars")
        assert stored[6] == "player_double_double"
        assert stored[8] == 0.5
        assert stored[9] == source["market"]["odds"]

    def test_milestones_blocks_and_quarter_props_are_dropped(self):
        _adapter, books = _adapt()
        keys = {market["key"] for book in books for market in book["markets"]}
        assert "player_points" in keys
        assert "player_threes" in keys
        assert "player_blocks" not in keys
        assert "player_triple_double" not in keys
        assert not any("1q" in key or "first3min" in key for key in keys)
        names = _names()
        # Milestone points (25, 30, ...) are not totals.
        assert set(_points_for(books, names[SHAI_ID])) <= {32.5, 33.5}

    def test_rows_updated_after_tip_are_dropped(self):
        rows = _rows("props_live_21718080_OKC@POR_pregame.json")
        adapter, books = _adapt(rows, tip=_tip(OKC_GAME_ID))
        assert adapter.post_tip_dropped == 0
        assert books

        stamps = []
        for row in rows:
            text = row["updated_at"].replace("Z", "+00:00")
            stamps.append(datetime.fromisoformat(text))
        latest = max(stamps)
        cutoff = latest - timedelta(microseconds=1)
        adapter, books = _adapt(rows, tip=cutoff)
        assert adapter.post_tip_dropped > 0
        kept_updates = [
            market.get("last_update")
            for book in books
            for market in book["markets"]
        ]
        # The recorded stamp uses millisecond precision and a Z suffix.
        latest_prefix = latest.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23]
        assert all(
            not (isinstance(stamp, str) and stamp.startswith(latest_prefix))
            for stamp in kept_updates
        )

    def test_unknown_vendor_is_dropped_and_counted(self):
        rows = _rows("props_live_21718080_OKC@POR_pregame.json")
        copied = dict(rows[0])
        copied["vendor"] = "bovada"
        copied["id"] = rows[0]["id"]
        adapter, books = _adapt([copied, *rows])
        assert adapter.dropped_vendor_rows["bovada"] == 1
        assert _book(books, "bovada") is None
        assert _book(books, "betonlineag") is None

    def test_a_single_real_points_total_is_kept(self):
        """A BetParx player with one points total is not treated as fake."""
        names = _names()
        _adapter, books = _adapt(markets=("player_points",))
        # Robert Williams III, id 476, has one BetParx points total in the file.
        player = names[476]
        assert _points_for([_book(books, "betparx")], player) == [5.5]


class TestPlayerDirectory:
    """Unknown ids use the recorded BALLDONTLIE name and count a log line."""

    @pytest.mark.asyncio
    async def test_unknown_id_gets_the_bdl_name_and_a_counted_log(self, caplog):
        client = _FixtureClient()
        directory = BdlPlayerDirectory(client, aliases={})
        with caplog.at_level(logging.INFO):
            names = await directory.names_for([SHAI_ID, SHAI_ID])
        assert names == {SHAI_ID: "Shai Gilgeous-Alexander"}
        assert directory.unaliased_count == 1
        assert any(
            "bdl_player_unaliased" in record.message and "Shai Gilgeous-Alexander" in record.message
            for record in caplog.records
        )
        _adapter, books = _adapt(markets=("player_points",))
        assert _points_for(books, names[SHAI_ID])

    @pytest.mark.asyncio
    async def test_alias_is_used_without_a_players_call(self):
        client = _FixtureClient()
        directory = BdlPlayerDirectory(client, aliases={SHAI_ID: "SGA"})
        names = await directory.names_for([SHAI_ID])
        assert names == {SHAI_ID: "SGA"}
        assert directory.unaliased_count == 0
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_id_absent_from_the_recorded_page_is_counted_and_not_invented(self, caplog):
        client = _FixtureClient()
        directory = BdlPlayerDirectory(client, aliases={})
        with caplog.at_level(logging.INFO):
            names = await directory.names_for([999999999])
        assert names == {}
        assert directory.missing_count == 1
        assert any("bdl_player_unknown" in record.message and "999999999" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_redis_caches_the_name_for_one_day(self):
        client = _FixtureClient()
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        directory = BdlPlayerDirectory(client, redis=redis, aliases={})
        first = await directory.names_for([SHAI_ID])
        second = await directory.names_for([SHAI_ID])
        assert first == second == {SHAI_ID: "Shai Gilgeous-Alexander"}
        assert [call[0] for call in client.calls] == ["list_players"]
        ttl = await redis.ttl("bdl:player:v1:175")
        assert 86300 <= ttl <= 86400


class TestProvider:
    """list_events matches on the Eastern date. The Clippers code is LAC."""

    @pytest.mark.asyncio
    async def test_clippers_code_is_lac_and_slate_date_is_the_et_date(self):
        provider, client = _provider()
        start = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)
        end = datetime(2026, 11, 11, 4, 59, 59, tzinfo=timezone.utc)
        events = await provider.list_events("nba", start, end)
        assert client.calls == [("list_games", ["2026-11-10"])]
        clippers = next(event for event in events if event.event_id == "21718076")
        assert clippers.away_code == "LAC"
        assert clippers.away_team == "Los Angeles Clippers"
        assert clippers.status == "in_progress"
        okc = next(event for event in events if event.event_id == "21718080")
        assert okc.slate_date == "2026-11-10"
        assert okc.commence_time == "2026-11-11T04:00:00.000Z"
        assert okc.status == "scheduled"
        assert okc.away_code == "OKC"
        assert okc.home_code == "POR"
        finals = next(event for event in events if event.event_id == "21718074")
        assert finals.status == "final"

    def test_same_game_matches_et_date_and_codes_not_commence_time(self):
        odds = json.loads(
            (FIXTURE_DIR.parents[0] / "odds_api_event_odds__nba_expanded_markets.json").read_text()
        )
        bos = _game(BOS_PHI_GAME_ID)
        assert odds["commence_time"] != bos["datetime"]
        assert games_match(
            odds_home=odds["home_team"],
            odds_away=odds["away_team"],
            odds_commence=odds["commence_time"],
            bdl_game=bos,
        )
        okc = _game(OKC_GAME_ID)
        assert not games_match(
            odds_home=odds["home_team"],
            odds_away=odds["away_team"],
            odds_commence=odds["commence_time"],
            bdl_game=okc,
        )

    @pytest.mark.asyncio
    async def test_get_event_props_uses_one_props_call_and_the_real_line(self):
        provider, client = _provider()
        start = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)
        end = datetime(2026, 11, 11, 4, 59, 59, tzinfo=timezone.utc)
        await provider.list_events("nba", start, end)
        board = await provider.get_event_props("nba", "21718080", ("player_points",))
        assert [call[0] for call in client.calls].count("get_player_props") == 1
        assert board.provider == "balldontlie"
        assert board.fetched_at.tzinfo is timezone.utc
        assert board.player_ids["Shai Gilgeous-Alexander"] == SHAI_ID
        assert _points_for(board.bookmakers, "Shai Gilgeous-Alexander")
        assert 10.5 not in _points_for(board.bookmakers, "Shai Gilgeous-Alexander")
        assert _book(board.bookmakers, "ballybet") is None

    @pytest.mark.asyncio
    async def test_non_digit_id_and_wnba_do_not_call(self):
        provider, client = _provider()
        with pytest.raises(ValueError, match="digits"):
            await provider.get_event_props("nba", "07361a8381206817e27bd2697fad7479", ("player_points",))
        with pytest.raises(ValueError, match="only serves nba"):
            await provider.list_events("wnba", datetime.now(timezone.utc), datetime.now(timezone.utc))
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_rate_status_reads_the_client_headers(self):
        provider, client = _provider()
        quiet = await provider.rate_status()
        assert quiet.provider == "balldontlie"
        assert quiet.recorded is False
        client.limit = 600
        client.remaining = 599
        status = await provider.rate_status()
        assert status.recorded is True
        assert status.remaining == 599
        assert status.used == 1


class TestRegistry:
    """The setting accepts balldontlie. The default path stays The Odds API."""

    def test_default_is_the_odds_api_for_both_leagues(self):
        assert settings.nba_odds_provider == "theoddsapi"
        assert isinstance(PROVIDERS["nba"], TheOddsAPIProvider)
        assert isinstance(PROVIDERS["wnba"], TheOddsAPIProvider)
        assert PROVIDERS["nba"].name == "theoddsapi"

    def test_balldontlie_is_accepted_and_wnba_does_not_switch(self, monkeypatch):
        monkeypatch.setattr(settings, "nba_odds_provider", "balldontlie")
        provider = PROVIDERS["nba"]
        assert provider.name == "balldontlie"
        assert type(provider).__name__ == "BdlOddsProvider"
        assert isinstance(PROVIDERS["wnba"], TheOddsAPIProvider)
        monkeypatch.setattr(settings, "nba_odds_provider", "BallDontLie")
        assert PROVIDERS["nba"].name == "balldontlie"

    def test_an_unknown_nba_provider_still_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "nba_odds_provider", "other")
        with pytest.raises(ValueError, match="nba_odds_provider"):
            PROVIDERS["nba"]
        assert PROVIDERS["wnba"].name == "theoddsapi"

    def test_routes_and_jobs_do_not_import_the_new_modules(self):
        forbidden = ("bdl_odds_provider", "bdl_props_adapter", "bdl_player_directory")
        roots = [BACKEND_APP / "api"]
        extra = [
            BACKEND_APP / "services" / "scheduler.py",
            BACKEND_APP / "services" / "daily_analysis.py",
            BACKEND_APP / "services" / "odds_snapshot_service.py",
            BACKEND_APP / "services" / "nba_injuries.py",
        ]
        files = [path for root in roots for path in root.rglob("*.py")] + extra
        offenders: list[str] = []
        for path in files:
            text = path.read_text()
            if any(name in text for name in forbidden):
                offenders.append(str(path))
        assert offenders == []

        gateway = (BACKEND_APP / "services" / "odds_gateway.py").read_text()
        tree = ast.parse(gateway)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                dumped = ast.dump(node)
                assert "bdl_odds_provider" not in dumped
        assert "get_bdl_odds_provider" in gateway


class TestRecordedSamples:
    """The four copied captures. Each file is used as recorded."""

    def test_okc_post_tip_capture_drops_every_row(self):
        """Every t2 row is timestamped after the OKC at Portland tip."""
        rows = _rows("props_live_21718080_OKC@POR_t2.json")
        adapter, books = _adapt(rows, tip=_tip(OKC_GAME_ID))
        assert adapter.post_tip_dropped == len(rows)
        assert books == []

    def test_in_progress_orlando_rows_are_after_tip(self):
        """Orlando at Sacramento props in this file were updated after tip."""
        game_id = 21718079
        rows = _rows("props_live_21718079_ORL@SAC_inprogress.json")
        adapter, books = _adapt(rows, tip=_tip(game_id))
        assert adapter.post_tip_dropped == len(rows)
        assert books == []

    def test_final_milwaukee_rows_are_after_tip(self):
        """The three remaining Milwaukee at New York rows are after tip."""
        game_id = 21718074
        rows = _rows("props_live_21718074_MIL@NYK_final.json")
        adapter, books = _adapt(rows, tip=_tip(game_id))
        assert adapter.post_tip_dropped == len(rows)
        assert books == []

    @pytest.mark.asyncio
    async def test_player_ids_page_returns_the_recorded_names(self, caplog):
        """``/v1/players?player_ids[]=`` names come from the copied page."""
        client = _FixtureClient()
        client.players = _load("players_ids_v2.json")["response"]
        directory = BdlPlayerDirectory(client, aliases={})
        with caplog.at_level(logging.INFO):
            names = await directory.names_for([175, 416, 38017507])
        assert names == {
            175: "Shai Gilgeous-Alexander",
            416: "Pascal Siakam",
            38017507: "Andrew Nembhard",
        }
        assert directory.unaliased_count == 3
        assert directory.missing_count == 0


class TestMissingFixtures:
    """Live captures that are not in the tree yet. Each skip names the file."""

    def test_empty_players_page_has_no_rows(self):
        """Recorded 2026-11-13 with --bdl-only: ``/v1/players?player_ids[]=0``."""
        payload = _load("players_empty.json")
        assert payload["status"] == 200
        assert payload["response"]["data"] == []
        assert "player_ids" in payload["request"]

    def test_empty_props_page_emits_no_books(self):
        """Recorded 2026-11-13 with --bdl-only for game 21718193."""
        payload = _load("props_empty.json")
        assert payload["status"] == 200
        assert "game_id=21718193" in payload["request"]
        body = payload["response"]
        assert body["data"] == []
        adapter = BdlPropsAdapter()
        assert adapter.to_bookmakers(body["data"], {}) == []

    def test_props_429_when_present(self):
        path = FIXTURE_DIR / "player_props_429.json"
        if not path.exists():
            pytest.skip("player_props_429.json is not recorded; the script saves a 429 only if one happens")
        text = path.read_text()
        assert "apiKey=" not in text
        assert "Authorization" not in text
        payload = json.loads(text)
        assert payload.get("status") == 429

    def test_same_slate_consensus_agrees_within_half_a_point(self):
        metas = sorted(SAME_SLATE_DIR.glob("*__meta.json")) if SAME_SLATE_DIR.exists() else []
        if not metas:
            pytest.skip(
                "same-slate pair is not recorded. "
                "ODDS_API_KEY is not available, so the pair stays skipped."
            )
        meta_path = metas[0]
        meta = json.loads(meta_path.read_text())
        prefix = meta_path.name[: -len("__meta.json")]
        odds_path = SAME_SLATE_DIR / f"{prefix}__odds_api_odds.json"
        props_path = SAME_SLATE_DIR / f"{prefix}__bdl_props.json"
        players_paths = sorted(SAME_SLATE_DIR.glob(f"{prefix}__bdl_players*.json"))
        games_path = SAME_SLATE_DIR / f"{prefix}__bdl_games.json"
        for path in (odds_path, props_path, games_path):
            if not path.exists():
                pytest.skip(f"same-slate file missing: {path.name}")
        if not players_paths:
            pytest.skip(f"same-slate players file missing for {prefix}")

        odds_body = _unwrap(json.loads(odds_path.read_text()))
        props_body = _unwrap(json.loads(props_path.read_text()))
        games_body = _unwrap(json.loads(games_path.read_text()))
        names: dict[int, str] = {}
        for path in players_paths:
            page = _unwrap(json.loads(path.read_text()))
            for player in page.get("data") or []:
                if isinstance(player, dict) and isinstance(player.get("id"), int):
                    names[player["id"]] = bdl_player_name(player)

        game = next(
            (
                item
                for item in games_body.get("data") or []
                if games_match(
                    odds_home=str(odds_body.get("home_team") or ""),
                    odds_away=str(odds_body.get("away_team") or ""),
                    odds_commence=str(odds_body.get("commence_time") or meta.get("odds_api_commence_time") or ""),
                    bdl_game=item,
                )
            ),
            None,
        )
        if game is None:
            pytest.skip("same-slate files do not contain a date-and-code match")
        tip_text = str(game.get("datetime") or "")
        tip = datetime.fromisoformat(tip_text.replace("Z", "+00:00")) if tip_text else None
        books = BdlPropsAdapter().to_bookmakers(
            list(props_body.get("data") or []),
            names,
            game_datetime=tip,
        )
        odds_books = list(odds_body.get("bookmakers") or [])
        bdl_lines = _consensus(books)
        odds_lines = _consensus(odds_books)
        shared = sorted(set(bdl_lines) & set(odds_lines))
        if not shared:
            pytest.skip("same-slate pair has no shared player and market")
        agreed = [
            key
            for key in shared
            if abs(bdl_lines[key] - odds_lines[key]) <= 0.5 + 1e-9
        ]
        rate = len(agreed) / len(shared)
        print(
            f"same-slate consensus agreement {len(agreed)}/{len(shared)} = {rate:.1%} "
            f"capture={meta.get('captured_at')}"
        )
        assert rate >= 0.90, (
            f"agreement {rate:.1%} is below 90% ({len(agreed)}/{len(shared)})"
        )


def _unwrap(payload: dict | list) -> dict:
    """Recorded wrapper or a raw JSON object."""
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        return payload["response"]
    if isinstance(payload, dict):
        return payload
    raise AssertionError("same-slate file is not an object")


def _consensus(books: list[dict]) -> dict[tuple[str, str], float]:
    """One consensus total per player and market, using the existing vote."""
    from app.services.prob import calculate_mode_threshold

    service = DailyAnalysisService()
    keys: list[str] = []
    for book in books:
        for market in book.get("markets") or []:
            key = market.get("key")
            if isinstance(key, str) and key not in keys and key != "player_double_double":
                keys.append(key)
    found: dict[tuple[str, str], float] = {}
    for key in keys:
        votes = service._group_main_votes(_only(books, key))
        for player, pairs in votes.items():
            lines = [line for line, _distance in pairs]
            distances = [distance for _line, distance in pairs]
            mode = calculate_mode_threshold(lines, distances)
            if mode is not None:
                found[(player, key)] = float(mode)
    return found


def test_record_script_strips_the_key_and_uses_snapshot_markets():
    """The recorder's market list is SNAPSHOT_MARKETS, and saved URLs drop apiKey."""
    text = RECORD_SCRIPT.read_text()
    assert "BALLDONTLIE_API_KEY" in text
    assert "ODDS_API_KEY" in text
    tree = ast.parse(text)
    markets = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "SNAPSHOT_MARKETS" and isinstance(node.value, ast.Constant):
                markets = node.value.value
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SNAPSHOT_MARKETS":
                    if isinstance(node.value, ast.Constant):
                        markets = node.value.value
    assert markets == SNAPSHOT_MARKETS
    # Importing the script must not print a key. The helper is pure.
    import importlib.util

    spec = importlib.util.spec_from_file_location("record_bdl_odds_fixtures", RECORD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cleaned = module.public_url(
        "https://api.the-odds-api.com/v4/sports/basketball_nba/events?apiKey=secret-value&regions=us"
    )
    assert "secret-value" not in cleaned
    assert "apiKey" not in cleaned
    assert "regions=us" in cleaned
    saved = module.public_headers(
        {"Authorization": "secret-value", "X-RateLimit-Remaining": "4"}
    )
    assert "Authorization" not in saved
    assert saved.get("x-ratelimit-remaining") == "4" or saved.get("X-RateLimit-Remaining") == "4"
    assert "--bdl-only" in text


def test_bdl_only_skips_the_odds_api(monkeypatch):
    """``--bdl-only`` records BALLDONTLIE fixtures and does not call The Odds API."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("record_bdl_odds_fixtures", RECORD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setenv("BALLDONTLIE_API_KEY", "bdl-test-key")
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    calls: list[str] = []
    monkeypatch.setattr(module, "_record_same_slate", lambda *_args: calls.append("slate"))
    monkeypatch.setattr(module, "_record_empty_players", lambda *_args: calls.append("players"))
    monkeypatch.setattr(module, "_record_empty_props", lambda *_args: calls.append("props"))
    module.main(["--bdl-only"])
    assert calls == ["players", "props"]

    calls.clear()
    with pytest.raises(SystemExit, match="must both be set"):
        module.main([])
    assert calls == []
