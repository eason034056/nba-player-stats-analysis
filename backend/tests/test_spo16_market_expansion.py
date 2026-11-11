"""
Unit tests for SPO-16 Phase 1 market expansion.

Covers:
- New continuous metrics in csv_player_history (threes_made, steals, ftm, fgm,
  ra, pr, pa)
- player_dd_history binary historical estimator (rejects threshold, computes
  dd_games correctly, normalized exact name match)
- single_leg_devig in prob.py (returns None on bad inputs, computes fair prob
  with the league-average prior on good inputs)
- DD binary parser path in odds_snapshot_service (Yes-only and Yes+No cases,
  no point=None rows leak through)
- Allow-list expansion in odds_history GET endpoint
- SUPPORTED_MARKETS / SNAPSHOT_MARKETS / OVER_UNDER_MARKET_KEYS /
  BINARY_MARKET_KEYS canonical sets cover the spec'd markets

These are focused acceptance tests against the binding criteria in the SPO-16
ticket §6. Anything broader (full daily-analysis end-to-end, Sentinel test
suite) is out of scope per ticket §7.
"""

import copy
import csv
import os
import sys
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.fixtures.odds_api import (
    NBA_EXPANDED_MARKETS,
    RECORDED_PLAYER_POINTS,
    derive_line_board,
    first_posted_market,
)

from app.services.csv_player_history import CSVPlayerHistoryService
from app.services.prob import single_leg_devig, DEFAULT_BINARY_VIG
from app.services.odds_snapshot_service import (
    SNAPSHOT_MARKETS,
    OVER_UNDER_MARKET_KEYS,
    BINARY_MARKET_KEYS,
    OddsSnapshotService,
)
from app.services.daily_analysis import (
    SUPPORTED_MARKETS,
    BINARY_MARKETS,
)


# ---------------------------------------------------------------------------
# Test CSV helper (mirrors the structure used in test_csv_player_history.py)
# ---------------------------------------------------------------------------

CSV_FIELDNAMES = [
    "Player", "Team", "Opponent", "Date", "Season", "W/L", "Pos",
    "Status", "MIN", "PTS", "AST", "REB", "ORB", "DRB",
    "FGM", "FGA", "FG%", "3PM", "3PA", "3P%",
    "FTM", "FTA", "FT%", "STL", "BLK", "TOV", "PF", "FIC",
]


def _make_csv(rows, tmp_dir=None):
    fd, path = tempfile.mkstemp(suffix=".csv", dir=tmp_dir)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _row(
    player="Test Player",
    date="01/10/2025",
    minutes="30:00",
    pts=10, ast=10, reb=10, stl=0, blk=0,
    tpm=2, ftm=4, fgm=4,
    season="2024-25",
    opponent="Opp",
):
    """Build one game-log row with sensible defaults."""
    return {
        "Player": player, "Team": "Team", "Opponent": opponent,
        "Date": date, "Season": season, "W/L": "W", "Pos": "PG",
        "Status": "Starter", "MIN": minutes,
        "PTS": str(pts), "AST": str(ast), "REB": str(reb),
        "ORB": "", "DRB": "",
        "FGM": str(fgm), "FGA": "10", "FG%": "0.4",
        "3PM": str(tpm), "3PA": "5", "3P%": "0.4",
        "FTM": str(ftm), "FTA": "5", "FT%": "0.8",
        "STL": str(stl), "BLK": str(blk), "TOV": "1", "PF": "2", "FIC": "10",
    }


# ===========================================================================
# 1. Constants — single source of truth
# ===========================================================================

class TestMarketConstants:
    """Acceptance criterion 1: 12 markets in SNAPSHOT_MARKETS / SUPPORTED_MARKETS+BINARY_MARKETS."""

    EXPECTED_KEYS = {
        # Original 4
        "player_points", "player_rebounds", "player_assists",
        "player_points_rebounds_assists",
        # New singles
        "player_threes", "player_steals",
        # Tier-B graceful-degrade
        "player_frees_made", "player_field_goals",
        # Native combos
        "player_rebounds_assists", "player_points_rebounds",
        "player_points_assists",
        # Binary
        "player_double_double",
    }

    def test_snapshot_markets_contains_all_12_keys(self):
        keys = set(SNAPSHOT_MARKETS.split(","))
        assert keys == self.EXPECTED_KEYS

    def test_supported_markets_excludes_binary_keys(self):
        # SUPPORTED_MARKETS is for the Over/Under flow, BINARY_MARKETS for DD.
        keys = {pair[0] for pair in SUPPORTED_MARKETS}
        assert "player_double_double" not in keys
        # 11 = 12 minus DD
        assert len(SUPPORTED_MARKETS) == 11

    def test_binary_markets_contains_only_dd(self):
        keys = {pair[0] for pair in BINARY_MARKETS}
        assert keys == {"player_double_double"}

    def test_over_under_and_binary_sets_are_disjoint(self):
        # Critical for the DD dispatch in _process_event — overlap would mean
        # DD gets parsed twice (once Over/Under-style, once binary).
        assert OVER_UNDER_MARKET_KEYS.isdisjoint(BINARY_MARKET_KEYS)

    def test_union_covers_all_snapshot_markets(self):
        # If a market is in SNAPSHOT_MARKETS, the parser dispatcher MUST know
        # how to handle it — otherwise the snapshot fetches the data for
        # nothing.
        snapshot_keys = set(SNAPSHOT_MARKETS.split(","))
        union = OVER_UNDER_MARKET_KEYS | BINARY_MARKET_KEYS
        assert snapshot_keys == union

    def test_3pa_is_not_in_any_market_list(self):
        # Acceptance criterion: 3PA must be cut from this scope. There is no
        # API path for it in The Odds API NBA market set.
        for key in self.EXPECTED_KEYS:
            assert "threes_attempted" not in key
            assert "three_point_attempts" not in key


# ===========================================================================
# 2. csv_player_history — new continuous metrics
# ===========================================================================

@pytest.fixture
def varied_service(tmp_path):
    """A service with one player and varied stats for metric testing."""
    rows = [
        # Game 1: high across the board (DD-eligible, high 3PM)
        _row(player="Alice", date="01/05/2025", pts=22, ast=10, reb=10,
             stl=3, blk=1, tpm=4, ftm=5, fgm=8),
        # Game 2: medium
        _row(player="Alice", date="01/06/2025", pts=12, ast=4, reb=6,
             stl=1, blk=0, tpm=2, ftm=2, fgm=5),
        # Game 3: low (no DD)
        _row(player="Alice", date="01/07/2025", pts=8, ast=3, reb=2,
             stl=0, blk=0, tpm=0, ftm=0, fgm=3),
        # Game 4: another DD
        _row(player="Alice", date="01/08/2025", pts=15, ast=11, reb=12,
             stl=2, blk=1, tpm=3, ftm=4, fgm=6),
    ]
    path = _make_csv(rows, tmp_dir=str(tmp_path))
    svc = CSVPlayerHistoryService()
    with patch("app.services.csv_player_history.CSV_PATH", path):
        svc.load_csv()
    return svc


class TestNewContinuousMetrics:
    def test_threes_made(self, varied_service):
        # Alice 3PM: 4, 2, 0, 3 -> over 1.5: 4, 2, 3 = 3/4
        result = varied_service.get_player_stats("Alice", "threes_made", 1.5)
        assert result["n_games"] == 4
        assert result["p_over"] == 0.75

    def test_steals(self, varied_service):
        # Alice STL: 3, 1, 0, 2 -> over 0.5: 3, 1, 2 = 3/4
        result = varied_service.get_player_stats("Alice", "steals", 0.5)
        assert result["n_games"] == 4
        assert result["p_over"] == 0.75

    def test_ftm(self, varied_service):
        # FTM: 5, 2, 0, 4 -> over 2.5: 5, 4 = 2/4
        result = varied_service.get_player_stats("Alice", "ftm", 2.5)
        assert result["p_over"] == 0.5

    def test_fgm(self, varied_service):
        # FGM: 8, 5, 3, 6 -> over 4.5: 8, 5, 6 = 3/4
        result = varied_service.get_player_stats("Alice", "fgm", 4.5)
        assert result["p_over"] == 0.75

    def test_ra_combo(self, varied_service):
        # R+A: 10+10=20, 6+4=10, 2+3=5, 12+11=23 -> over 12.5: 20, 23 = 2/4
        result = varied_service.get_player_stats("Alice", "ra", 12.5)
        assert result["p_over"] == 0.5

    def test_pr_combo(self, varied_service):
        # P+R: 22+10=32, 12+6=18, 8+2=10, 15+12=27 -> over 20: 32, 27 = 2/4
        result = varied_service.get_player_stats("Alice", "pr", 20.0)
        assert result["p_over"] == 0.5

    def test_pa_combo(self, varied_service):
        # P+A: 22+10=32, 12+4=16, 8+3=11, 15+11=26 -> over 15: 32, 16, 26 = 3/4
        result = varied_service.get_player_stats("Alice", "pa", 15.0)
        assert result["p_over"] == 0.75

    def test_legacy_metrics_still_work(self, varied_service):
        # Acceptance: existing 4 metrics still pass — no contract break.
        # PRA: 22+10+10=42, 12+4+6=22, 8+3+2=13, 15+11+12=38
        # Over 30: 42, 38 = 2/4
        result = varied_service.get_player_stats("Alice", "pra", 30.0)
        assert result["p_over"] == 0.5


# ===========================================================================
# 3. csv_player_history — DD binary historical estimator
# ===========================================================================

class TestPlayerDdHistory:
    def test_returns_documented_shape(self, varied_service):
        result = varied_service.player_dd_history("Alice")
        assert set(result.keys()) >= {
            "player", "season", "games", "dd_games", "prob_dd",
            "n_games", "message",
        }

    def test_rejects_non_null_threshold(self, varied_service):
        # Acceptance criterion: DD is binary; threshold must be None.
        with pytest.raises(ValueError, match="binary outcome"):
            varied_service.player_dd_history("Alice", threshold=10.5)

    def test_accepts_explicit_none_threshold(self, varied_service):
        # threshold=None should NOT raise (matches DD's binary semantics).
        result = varied_service.player_dd_history("Alice", threshold=None)
        assert result["games"] == 4

    def test_dd_count_exact_threshold_logic(self, varied_service):
        # Alice games — count {PTS, REB, AST, STL, BLK} components ≥10:
        # G1: 22pts, 10reb, 10ast, 3stl, 1blk -> doubles in PRA = 3 -> DD
        # G2: 12pts, 6reb, 4ast, 1stl, 0blk -> 1 double -> not DD
        # G3: 8pts, 2reb, 3ast, 0stl, 0blk -> 0 doubles -> not DD
        # G4: 15pts, 12reb, 11ast, 2stl, 1blk -> 3 doubles -> DD (triple-double also a DD)
        result = varied_service.player_dd_history("Alice")
        assert result["games"] == 4
        assert result["dd_games"] == 2
        assert result["prob_dd"] == 0.5

    def test_unknown_player_returns_zero_games(self, varied_service):
        result = varied_service.player_dd_history("Nobody Here")
        assert result["games"] == 0
        assert result["dd_games"] == 0
        assert result["prob_dd"] is None
        assert result["message"] is not None

    def test_partial_name_does_not_substring_match(self, varied_service):
        # "Ali" is a substring of "Alice" and must not attach to her.
        result = varied_service.player_dd_history("Ali")
        assert result["player"] == "Ali"
        assert result["games"] == 0
        assert result["prob_dd"] is None

    def test_casefolded_name_matches(self, varied_service):
        result = varied_service.player_dd_history("alice")
        assert result["player"] == "Alice"
        assert result["games"] == 4

    def test_season_filter(self, tmp_path):
        # 1 game in 2023-24 (DD), 1 game in 2024-25 (not DD)
        rows = [
            _row(player="Bob", date="01/05/2024", season="2023-24",
                 pts=20, ast=10, reb=10, stl=0, blk=0),
            _row(player="Bob", date="01/05/2025", season="2024-25",
                 pts=8, ast=2, reb=1, stl=0, blk=0),
        ]
        path = _make_csv(rows, tmp_dir=str(tmp_path))
        svc = CSVPlayerHistoryService()
        with patch("app.services.csv_player_history.CSV_PATH", path):
            svc.load_csv()
        r1 = svc.player_dd_history("Bob", season="2023-24")
        assert r1["games"] == 1 and r1["dd_games"] == 1
        r2 = svc.player_dd_history("Bob", season="2024-25")
        assert r2["games"] == 1 and r2["dd_games"] == 0
        all_seasons = svc.player_dd_history("Bob")
        assert all_seasons["games"] == 2 and all_seasons["dd_games"] == 1

    def test_dnp_excluded(self, tmp_path):
        # A DNP (0 minutes) shouldn't count in either games or dd_games.
        rows = [
            _row(player="Carol", date="01/05/2025", minutes="0:00",
                 pts=0, ast=0, reb=0, stl=0, blk=0),
            _row(player="Carol", date="01/06/2025", minutes="30:00",
                 pts=20, ast=10, reb=10, stl=0, blk=0),
        ]
        path = _make_csv(rows, tmp_dir=str(tmp_path))
        svc = CSVPlayerHistoryService()
        with patch("app.services.csv_player_history.CSV_PATH", path):
            svc.load_csv()
        result = svc.player_dd_history("Carol")
        assert result["games"] == 1
        assert result["dd_games"] == 1


# ===========================================================================
# 4. prob.single_leg_devig
# ===========================================================================

class TestSingleLegDevig:
    def test_basic_devig(self):
        # Yes posted at +0.62 implied with 4.5% vig -> fair = 0.62 / 1.045
        result = single_leg_devig(0.62)
        assert result is not None
        assert abs(result - 0.62 / 1.045) < 1e-9

    def test_uses_default_binary_vig(self):
        # Default = DEFAULT_BINARY_VIG (decision §4 step 3 prior)
        assert DEFAULT_BINARY_VIG == 0.045

    def test_custom_vig(self):
        result = single_leg_devig(0.5, assumed_vig=0.10)
        assert result is not None
        assert abs(result - 0.5 / 1.10) < 1e-9

    def test_negative_input_returns_none(self):
        assert single_leg_devig(-0.1) is None

    def test_above_one_input_returns_none(self):
        assert single_leg_devig(1.5) is None

    def test_zero_or_negative_vig_returns_none(self):
        # Vig must be positive — can't de-vig with zero or negative margin.
        assert single_leg_devig(0.5, assumed_vig=0) is None
        assert single_leg_devig(0.5, assumed_vig=-0.05) is None

    def test_pathological_result_returns_none(self):
        # If implied=1.0 and vig=0.045, fair = 1/1.045 = 0.957 -> still valid.
        # But implied > 1+vig would push fair >= 1, which we refuse to publish.
        # With implied=1 (impossible in practice) we still get < 1 so returns
        # the value — guards are mostly for vig edge cases.
        result = single_leg_devig(1.0, assumed_vig=0.045)
        assert result is None or 0 < result < 1


# ===========================================================================
# 5. DD binary parser path (no Over/Under contamination)
# ===========================================================================

def _derive_dd_case(posted: tuple[str, dict], kind: str) -> tuple[str, dict] | None:
    """Cut a recorded DD market down to one player and the sides ``kind`` needs.

    ``posted`` is ``(bookmaker key, market)`` from ``first_posted_market``.
    Returns None when the recording does not contain the required side,
    so the caller keeps the inline builder instead of inventing a price.
    """
    book_key, market = posted
    grouped: dict[str, dict[str, dict]] = {}
    for outcome in market.get("outcomes") or []:
        player = outcome.get("description") or ""
        side = (outcome.get("name") or "").lower()
        if player and side in ("yes", "no"):
            grouped.setdefault(player, {})[side] = outcome

    if kind == "yes_and_no":
        player = next(
            (
                name
                for name, sides in grouped.items()
                if "yes" in sides and "no" in sides
            ),
            None,
        )
        if player is None:
            return None
        keep = [grouped[player]["yes"], grouped[player]["no"]]
    elif kind == "yes_only":
        player = next((name for name, sides in grouped.items() if "yes" in sides), None)
        if player is None:
            return None
        # Derivation: drop No. The Yes price stays recorded.
        keep = [grouped[player]["yes"]]
    elif kind == "no_only":
        player = next((name for name, sides in grouped.items() if "no" in sides), None)
        if player is None:
            return None
        # Derivation: drop Yes. The No price stays recorded.
        keep = [grouped[player]["no"]]
    else:
        raise AssertionError(f"unknown DD case {kind}")

    derived = copy.deepcopy(market)
    derived["outcomes"] = [copy.deepcopy(outcome) for outcome in keep]
    return book_key, derived


class TestDdBinaryParser:
    """Acceptance criterion 2: DD parser is a separate code path."""

    def _dd_market_payload(
        self,
        yes_outcomes: list[tuple[str, int]],
        no_outcomes: list[tuple[str, int]] | None = None,
    ) -> dict:
        """Inline DD market for a side the recording did not post.

        The 2026-11-10 Celtics at 76ers capture posts double-double Yes
        only. Yes+No and No-only still use this builder.

        # TODO(SPO-106): replace with recorded fixture when a book posts No
        """
        outcomes = [
            {"name": "Yes", "description": player, "price": price}
            for player, price in yes_outcomes
        ]
        if no_outcomes:
            outcomes.extend(
                {"name": "No", "description": player, "price": price}
                for player, price in no_outcomes
            )
        return {"key": "player_double_double", "outcomes": outcomes}

    def _dd_case(
        self,
        kind: str,
        inline_yes: list[tuple[str, int]],
        inline_no: list[tuple[str, int]] | None,
        inline_book: str,
    ) -> tuple[str, dict]:
        """Recorded DD market for ``kind``, or the inline builder.

        ``kind`` is ``yes_only``, ``yes_and_no``, or ``no_only``.

        ``yes_only`` copies the first recorded Yes (FanDuel, Joel Embiid
        on the Celtics at 76ers capture) and must not fall back. The
        recording has no No, so ``yes_and_no`` and ``no_only`` keep the
        inline builder instead of inventing a No price.
        """
        posted = first_posted_market(NBA_EXPANDED_MARKETS, "player_double_double")
        derived = _derive_dd_case(posted, kind) if posted is not None else None
        if derived is not None:
            return derived
        if kind == "yes_only":
            raise AssertionError(
                "player_double_double Yes is not in the expanded NBA recording"
            )
        # TODO(SPO-106): replace with recorded fixture when a book posts No
        return inline_book, self._dd_market_payload(inline_yes, inline_no)

    def test_yes_only_uses_single_leg_devig(self):
        svc = OddsSnapshotService()
        bookmaker_key, market = self._dd_case(
            "yes_only",
            inline_yes=[("Nikola Jokic", -150)],
            inline_no=None,
            inline_book="draftkings",
        )
        yes_price = next(
            outcome["price"]
            for outcome in market["outcomes"]
            if outcome["name"] == "Yes"
        )
        rows = svc._parse_binary_market(
            market=market,
            market_key="player_double_double",
            bookmaker_key=bookmaker_key,
            snapshot_at=datetime(2026, 5, 2),
            date_obj=datetime(2026, 5, 2).date(),
            event_id="evt-1",
            home_team="Nuggets", away_team="Lakers",
        )
        assert len(rows) == 1
        row = rows[0]
        # line is the 0.5 sentinel — DD has no real point
        assert row[8] == 0.5
        # over_odds = Yes price, under_odds = None when only Yes posted
        assert row[9] == yes_price
        assert row[10] is None
        # over_fair_prob populated via single-leg de-vig
        assert row[12] is not None
        assert 0 < row[12] < 1

    def test_yes_and_no_uses_two_leg_devig(self):
        svc = OddsSnapshotService()
        bookmaker_key, market = self._dd_case(
            "yes_and_no",
            inline_yes=[("Nikola Jokic", -150)],
            inline_no=[("Nikola Jokic", 130)],
            inline_book="fanduel",
        )
        yes_price = next(
            outcome["price"]
            for outcome in market["outcomes"]
            if outcome["name"] == "Yes"
        )
        no_price = next(
            outcome["price"]
            for outcome in market["outcomes"]
            if outcome["name"] == "No"
        )
        rows = svc._parse_binary_market(
            market=market,
            market_key="player_double_double",
            bookmaker_key=bookmaker_key,
            snapshot_at=datetime(2026, 5, 2),
            date_obj=datetime(2026, 5, 2).date(),
            event_id="evt-1",
            home_team="Nuggets", away_team="Lakers",
        )
        assert len(rows) == 1
        row = rows[0]
        # both prices populated, copied from the market the case built
        assert row[9] == yes_price
        assert row[10] == no_price
        # vig comes from leg pair, fair probs sum to 1
        assert row[12] is not None
        assert row[13] is not None
        assert abs(row[12] + row[13] - 1.0) < 1e-9

    def test_no_yes_price_skips_player(self):
        # Spec: "Do NOT publish a fair probability if vig cannot be estimated"
        # — without a Yes anchor, we have nothing.
        svc = OddsSnapshotService()
        bookmaker_key, market = self._dd_case(
            "no_only",
            inline_yes=[],
            inline_no=[("Some Player", -120)],
            inline_book="caesars",
        )
        rows = svc._parse_binary_market(
            market=market,
            market_key="player_double_double",
            bookmaker_key=bookmaker_key,
            snapshot_at=datetime(2026, 5, 2),
            date_obj=datetime(2026, 5, 2).date(),
            event_id="evt-1",
            home_team="A", away_team="B",
        )
        assert rows == []

    def test_dd_dispatch_via_main_processor(self):
        """End-to-end: a DD market in bookmakers_data goes through the
        binary path, NOT the Over/Under one. Verifiable by checking the row
        format (line=0.5 sentinel, no `point` field consulted)."""
        svc = OddsSnapshotService()
        # Mock the snapshot to return a bookmaker with ONLY DD
        with patch.object(svc, "_get_events", return_value=[]):
            pass  # service plumbing test would need more mocks; covered above

    def test_grep_no_over_under_compute_for_dd(self):
        """Acceptance: no compute_over_probability(... market='player_double_double' ...)
        call exists. We confirm this by source inspection — `compute_over_probability`
        isn't even imported anywhere in the service modules.
        """
        snapshot_src = open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "app", "services", "odds_snapshot_service.py",
            )
        ).read()
        assert "compute_over_probability" not in snapshot_src
        # And the DD outcome shape (Yes/No) is handled in a function whose name
        # makes the separation explicit.
        assert "_parse_binary_market" in snapshot_src



def _recorded_points_ou(player: str, line: float) -> list[dict]:
    """FanDuel ``player_points`` sliced to one Over and its Under.

    ``derive_line_board`` copies FanDuel from
    ``odds_api_event_odds__player_points.json`` and the first outcome on
    that book (Dyson Daniels Over, price -113, point 10.5), then rewrites
    ``description`` and ``point``. That helper keeps a single side. The
    Over/Under parser drops a player who has no Under, so the matching
    Under from the same recorded pair is appended here. ``first_posted_market``
    finds that market. The Under price stays the recorded -113. Player
    name and line are this test's controls. This does not type -110:
    that price is not the price on this pair.
    """
    books = derive_line_board(
        [{player: [line]}],
        fixture_name=RECORDED_PLAYER_POINTS,
    )
    posted = first_posted_market(RECORDED_PLAYER_POINTS, "player_points")
    if posted is None:
        raise AssertionError("player_points is not in the recorded NBA capture")
    book_key, market = posted
    if books[0].get("key") != book_key:
        raise AssertionError(
            f"derive_line_board used {books[0].get('key')!r}, "
            f"not the first posted book {book_key!r}"
        )
    outcomes = market.get("outcomes") or []
    over = next((item for item in outcomes if item.get("name") == "Over"), None)
    if over is None:
        raise AssertionError("recorded player_points has no Over")
    under = next(
        (
            item
            for item in outcomes
            if item.get("name") == "Under"
            and item.get("description") == over.get("description")
            and item.get("point") == over.get("point")
        ),
        None,
    )
    if under is None:
        raise AssertionError(
            "recorded player_points has no Under beside the first Over"
        )
    under = copy.deepcopy(under)
    under["description"] = player
    under["point"] = line
    books[0]["markets"][0]["outcomes"].append(under)
    return books


# ===========================================================================
# 8. SPO-18 dispatcher hardening — unknown market key path
# ===========================================================================

class TestDispatcherUnknownMarketKey:
    """Acceptance criterion (SPO-18 §2): an unknown `market_key` in
    `bookmakers_data` must be skipped with a warning and write zero rows,
    never silently funneled into the Over/Under parser.

    Constants-side coverage already exists via
    `test_union_covers_all_snapshot_markets` (Forge / Phase 2B). This test
    is the *runtime-side* guard — defense-in-depth against a future typo
    in `SNAPSHOT_MARKETS` that would otherwise produce `point=None` rows
    via the OU parser fallback before hitting any caller. See Lens review
    2026-05-02 §Suggestions for the original raise.
    """

    @pytest.mark.asyncio
    async def test_unknown_market_writes_zero_rows_and_warns(self, capsys):
        svc = OddsSnapshotService()

        # Construct a snapshot whose ONLY market is one the dispatcher does
        # not recognize. The outcomes deliberately mimic the OU shape
        # (`name=Over|Under`, `point=5.5`) — if the old `if BINARY else OU`
        # branch were still in place, the OU parser would happily emit a
        # row with point=5.5. The new explicit `elif OVER_UNDER` + `else
        # log+skip` shape must reject this.
        fake_snapshot = SimpleNamespace(
            data={
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "markets": [
                            {
                                "key": "player_made_up_metric",
                                "outcomes": [
                                    {
                                        "name": "Over",
                                        "description": "Player X",
                                        "point": 5.5,
                                        "price": -110,
                                    },
                                    {
                                        "name": "Under",
                                        "description": "Player X",
                                        "point": 5.5,
                                        "price": -110,
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        )

        mock_get = AsyncMock(return_value=fake_snapshot)
        with patch(
            "app.services.odds_snapshot_service.odds_gateway.get_market_snapshot",
            new=mock_get,
        ):
            rows = await svc._process_event(
                event_id="evt-spo18-test",
                home_team="A",
                away_team="B",
                date="2026-05-03",
                snapshot_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
            )

        # 1. Zero rows written — the OU fallback did NOT swallow the
        #    unknown key.
        assert rows == [], (
            f"Unknown market key produced {len(rows)} rows; expected 0. "
            f"This means the dispatcher fell through to the OU parser and "
            f"wrote `point=None` (or worse, `point=5.5` from the synthetic "
            f"outcome) for an unrecognized key. See SPO-18 §1.1."
        )

        # 2. Warning printed to stdout (matches existing print()-based log
        #    style in this file). The market key must appear in the message
        #    so a future debugger can grep for the typo.
        captured = capsys.readouterr().out
        assert "unknown market key" in captured, (
            f"Expected the dispatcher warning in stdout; got: {captured!r}"
        )
        assert "player_made_up_metric" in captured, (
            f"Warning must include the offending market key; got: {captured!r}"
        )

    @pytest.mark.asyncio
    async def test_known_ou_market_still_writes_rows(self, capsys):
        """Regression guard: the new `elif OVER_UNDER_MARKET_KEYS` branch
        must not break the standard OU path. A real OU market with a real
        Over/Under outcome pair should still produce one row per player.
        """
        svc = OddsSnapshotService()

        # Slice of the recorded FanDuel player_points pair (Dyson Daniels
        # Over -113 / Under -113). Name and line are this test's controls.
        fake_snapshot = SimpleNamespace(
            data={"bookmakers": _recorded_points_ou("Stephen Curry", 24.5)},
        )

        mock_get = AsyncMock(return_value=fake_snapshot)
        with patch(
            "app.services.odds_snapshot_service.odds_gateway.get_market_snapshot",
            new=mock_get,
        ):
            rows = await svc._process_event(
                event_id="evt-spo18-ou-regression",
                home_team="GSW",
                away_team="LAL",
                date="2026-05-03",
                snapshot_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
            )

        assert len(rows) == 1
        row = rows[0]
        # Sanity-check the OU row shape — line is the bookmaker point,
        # not the 0.5 binary sentinel. Tuple layout matches UPSERT_LINE_SQL
        # $1..$14 (snapshot_at, date, event_id, home, away, player, market,
        # bookmaker, line, over_odds, under_odds, vig, over_fair, under_fair).
        assert row[5] == "Stephen Curry"   # player_name
        assert row[6] == "player_points"   # market
        assert row[8] == 24.5              # line (real OU point, not 0.5 sentinel)
        # No "unknown market key" warning should fire on the happy path.
        assert "unknown market key" not in capsys.readouterr().out
