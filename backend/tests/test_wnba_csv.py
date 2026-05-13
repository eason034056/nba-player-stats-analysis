"""
Tests for the WNBA CSV pipeline (SPO-32 Phase 1).

These tests deliberately load the **real** `data/wnba_player_game_logs.csv`
that landed in `dev` at commit `efa285c` — no mocks, no synthetic rows.
Why: the whole point of Phase 1 is to verify that the parameterized
`CSVPlayerHistoryService(league="wnba")` + `wnba_csv_player_service`
singleton + `/api/wnba/*` routes hold up against actual production data
shapes. A mocked test would only prove our assumptions, not reality
(CLAUDE.md § External API Wrappers, item 2: "A pure-mock test suite for
an API wrapper is NOT acceptable").

Anchor player: A'ja Wilson (3x WNBA MVP, Las Vegas Aces).
She has 55 games in the shipped CSV — verified before writing this test
via `grep -c "A'ja Wilson" data/wnba_player_game_logs.csv`.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.csv_player_history import (
    CSVPlayerHistoryService,
    wnba_csv_player_service,
    nba_csv_player_service,
    csv_player_service,
    CONTINUOUS_METRIC_EXTRACTORS,
)


# Known anchor — verified in CSV before checking in this test.
ANCHOR_PLAYER = "A'ja Wilson"


# ---------------------------------------------------------------------------
# Module-level wiring — verify the singletons are wired correctly
# ---------------------------------------------------------------------------


class TestSingletonWiring:
    """Sanity checks for the module-level singleton wiring."""

    def test_wnba_singleton_is_wnba_league(self):
        # ⚠ If this breaks, somebody changed the singleton's league —
        # the rest of the test file is meaningless.
        assert wnba_csv_player_service.league == "wnba"

    def test_nba_singleton_is_nba_league(self):
        assert nba_csv_player_service.league == "nba"

    def test_legacy_csv_player_service_alias_points_to_nba(self):
        # Backward-compat guarantee: the legacy import name must still
        # resolve to the NBA service so old call sites stay green.
        assert csv_player_service is nba_csv_player_service

    def test_singletons_are_distinct_instances(self):
        # Two separate service instances with separate caches — sharing
        # one would conflate leagues.
        assert wnba_csv_player_service is not nba_csv_player_service

    def test_wnba_csv_path_points_at_wnba_file(self):
        # We don't pin the absolute path (Docker vs local differs), but
        # the resolved path MUST end with the WNBA CSV file name.
        assert wnba_csv_player_service._csv_path.endswith(
            "wnba_player_game_logs.csv"
        )


# ---------------------------------------------------------------------------
# Real CSV load — touches the actual file on disk
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def loaded_wnba_service():
    """
    Return a freshly-loaded WNBA service.

    Using a module-scoped fixture (not the module-level singleton) so this
    test file is hermetic: it doesn't depend on import-order side effects,
    and a prior test that mutates the singleton can't break us.
    """
    svc = CSVPlayerHistoryService(league="wnba")
    svc.load_csv()
    return svc


class TestRealWNBACSVLoad:
    """End-to-end: the real WNBA CSV parses cleanly into the service."""

    def test_csv_loads_without_error(self, loaded_wnba_service):
        assert loaded_wnba_service._loaded is True

    def test_csv_has_players(self, loaded_wnba_service):
        # 184 players at commit efa285c. We assert ≥ 100 rather than the
        # exact count so a future CSV refresh adding new players doesn't
        # spuriously break this test — but a regression to "empty CSV"
        # or "schema parse failure dropped most rows" would still trip.
        players = loaded_wnba_service.get_all_players()
        assert len(players) >= 100, (
            f"WNBA CSV produced only {len(players)} players — "
            "possible parse failure or empty file"
        )

    def test_anchor_player_present(self, loaded_wnba_service):
        # ⚠ Verified by grep before writing this test. If A'ja Wilson
        # ever disappears from the CSV, the data layer has regressed
        # before any logic could be tested.
        assert ANCHOR_PLAYER in loaded_wnba_service.get_all_players()

    def test_player_list_sorted(self, loaded_wnba_service):
        players = loaded_wnba_service.get_all_players()
        assert players == sorted(players)


# ---------------------------------------------------------------------------
# Anchor-player stats — the smoke test the issue asked for
# ---------------------------------------------------------------------------


class TestAnchorPlayerStats:
    """A'ja Wilson historical stats from the real CSV."""

    def test_anchor_has_game_log_entries(self, loaded_wnba_service):
        # 55 games in CSV today. Asserting ≥ 30 so a partial-season
        # refresh doesn't break us, but a regression to "zero games"
        # would surface immediately.
        games = loaded_wnba_service._cache.get(ANCHOR_PLAYER, [])
        assert len(games) >= 30, (
            f"Expected ≥30 games for {ANCHOR_PLAYER}, got {len(games)}"
        )

    def test_anchor_points_stats_are_well_formed(self, loaded_wnba_service):
        # Use a low threshold (10.5) that essentially any active starter
        # clears — keeps the test robust to season-to-season variance.
        stats = loaded_wnba_service.get_player_stats(
            player_name=ANCHOR_PLAYER,
            metric="points",
            threshold=10.5,
        )

        assert stats["player"] == ANCHOR_PLAYER
        assert stats["metric"] == "points"
        assert stats["threshold"] == 10.5
        assert stats["n_games"] > 0, "anchor player has zero valid games"

        # All probabilities must be in [0, 1]
        assert 0.0 <= stats["p_over"] <= 1.0
        assert 0.0 <= stats["p_under"] <= 1.0

        # Probabilities sum to ≤ 1 (equal-to-threshold games sit outside
        # both buckets — see CSV service docstring: Over is strictly >,
        # Under is strictly <).
        assert stats["p_over"] + stats["p_under"] <= 1.0 + 1e-9

        # Mean PTS for a WNBA MVP must be well above the 10.5 line.
        assert stats["mean"] > 10.5, (
            f"Anchor mean PTS {stats['mean']} ≤ 10.5 — suspicious"
        )

        # Histogram and game_logs populated
        assert len(stats["histogram"]) > 0
        assert len(stats["game_logs"]) > 0

    def test_anchor_opponents_populated(self, loaded_wnba_service):
        # Should have faced multiple WNBA franchises. We check ≥ 3 rather
        # than naming specific teams (franchise relocations have happened
        # in the WNBA's history and this test should outlive them).
        opponents = loaded_wnba_service.get_player_opponents(ANCHOR_PLAYER)
        assert len(opponents) >= 3

    def test_anchor_supports_combo_metric_pra(self, loaded_wnba_service):
        # SPO-16 combos must work on WNBA too — points+rebounds+assists
        # is computed from the canonical columns, not stored separately.
        stats = loaded_wnba_service.get_player_stats(
            player_name=ANCHOR_PLAYER,
            metric="pra",
            threshold=20.5,
        )
        assert stats["n_games"] > 0
        # PRA is unambiguously larger than PTS alone for any starter.
        assert stats["mean"] > 10.0


# ---------------------------------------------------------------------------
# League isolation — WNBA service must not leak into NBA, and vice versa
# ---------------------------------------------------------------------------


class TestLeagueIsolation:
    """Both league services must hold their own data; no cross-contamination."""

    def test_wnba_service_does_not_have_nba_players(self):
        """
        A'ja Wilson should be in WNBA but not NBA, and LeBron James the
        reverse. This protects against the most catastrophic refactor
        bug: accidentally pointing both singletons at the same CSV.
        """
        # Avoid loading the real NBA CSV here — keep this test fast and
        # independent of NBA's bigger dataset. The singletons resolve
        # their paths in __init__, so just compare paths.
        assert wnba_csv_player_service._csv_path != nba_csv_player_service._csv_path
        assert "wnba" in wnba_csv_player_service._csv_path.lower()
        assert "wnba" not in os.path.basename(
            nba_csv_player_service._csv_path
        ).lower()


# ---------------------------------------------------------------------------
# DD endpoint smoke test (binary metric path)
# ---------------------------------------------------------------------------


class TestAnchorPlayerDD:
    """DD history for the anchor player — DD is binary, no threshold."""

    def test_dd_returns_well_formed_result(self, loaded_wnba_service):
        result = loaded_wnba_service.player_dd_history(player_name=ANCHOR_PLAYER)
        assert result["player"] == ANCHOR_PLAYER
        assert result["n_games"] > 0
        assert result["dd_games"] >= 0
        assert result["dd_games"] <= result["n_games"]
        # prob_dd must be in [0, 1] (None only when n_games == 0)
        assert result["prob_dd"] is not None
        assert 0.0 <= result["prob_dd"] <= 1.0

    def test_dd_rejects_threshold_argument(self, loaded_wnba_service):
        # The services layer hard-rejects non-None threshold — DD is 0/1,
        # threshold is meaningless. This catches callers that wire DD
        # through the Over/Under flow by mistake.
        with pytest.raises(ValueError):
            loaded_wnba_service.player_dd_history(
                player_name=ANCHOR_PLAYER,
                threshold=10.5,
            )
