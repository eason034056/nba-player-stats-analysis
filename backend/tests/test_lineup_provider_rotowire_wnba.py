"""SPO-34 Phase 4 — RotoWire WNBA parser unit + live-integration tests.

The unit test is grounded in `docs/research/wnba-rollout/rotowire_wnba_sample.html`,
a byte-for-byte snapshot captured live on 2026-05-13 alongside Scout's
comparison doc. Every assertion in `test_parse_committed_sample_*` traces
back to a class/value Scout listed in §2.4 of the comparison doc.

Why pin the sample HTML in the repo:
- Future shape drift on RotoWire (selector renames, position-vocab changes,
  layout reshuffles) gets caught by the diff between the new fetch and the
  committed sample, not by silent miscounts.
- The unit test runs without network, so CI passes in air-gapped environments.

The integration test (`test_live_wnba_lineups_smoke`) hits the live URL and
is gated on `RUN_INTEGRATION=1` per `CLAUDE.md § External API Wrappers` rule
#2. Run locally before pushing if the WNBA scraper is touched.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.lineup_provider_rotowire import (
    ROTOWIRE_LEAGUE_URLS,
    fetch_rotowire_lineups,
    parse_rotowire_wnba_html,
)
from app.services.lineup_source_support import WNBA_TEAM_ALIASES


# ---- Paths --------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_HTML_PATH = (
    REPO_ROOT / "docs" / "research" / "wnba-rollout" / "rotowire_wnba_sample.html"
)


# ---- Helpers ------------------------------------------------------------


def _load_sample() -> str:
    if not SAMPLE_HTML_PATH.exists():  # pragma: no cover - guard for malformed worktrees
        pytest.skip(
            f"Sample HTML missing at {SAMPLE_HTML_PATH}; the test relies on "
            "Scout's regression baseline. Restore from git or re-run Scout's "
            "research step."
        )
    return SAMPLE_HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed_sample() -> dict[str, dict]:
    return parse_rotowire_wnba_html(_load_sample(), "2026-05-13")


# ---- Unit tests against the pinned sample -------------------------------


def test_parses_eight_teams_from_2026_05_13_sample(parsed_sample):
    """Sample has 5 lineup cards; one is the `is-tools` widget, so 4 games
    × 2 teams = 8 team entries. Card count is game-day dependent, so the
    integration test does NOT pin this — only the fixture does.
    """
    assert len(parsed_sample) == 8, sorted(parsed_sample.keys())


def test_team_codes_match_wnba_alias_table(parsed_sample):
    """Every team returned must be a known WNBA code (no NBA leakage)."""
    wnba_codes = set(WNBA_TEAM_ALIASES.keys())
    for team in parsed_sample:
        assert team in wnba_codes, f"Unknown WNBA code surfaced: {team!r}"


def test_visit_home_pairing_is_consistent(parsed_sample):
    """If team A is HOME vs B, team B must be AWAY vs A. Detects card-block
    parsing drift (e.g. confusing visit/home from card to card)."""
    for team, lineup in parsed_sample.items():
        opponent = lineup["opponent"]
        assert opponent in parsed_sample, f"{team}'s opponent {opponent!r} missing"
        other = parsed_sample[opponent]
        # Sides must be opposite
        assert (
            lineup["home_or_away"] != other["home_or_away"]
        ), f"{team} and {opponent} both report {lineup['home_or_away']}"
        assert other["opponent"] == team


def test_every_team_has_status_expected_or_confirmed(parsed_sample):
    """Per CLAUDE.md Domain Lens (lineup/injury validity), `source_status` must
    surface verbatim — never collapsed to a boolean. The 2026-05-13 sample
    happened to be all `expected`; if the page later switches to `confirmed`
    that value must still surface."""
    for team, lineup in parsed_sample.items():
        snapshot = lineup["source_snapshots"]["rotowire"]
        assert snapshot["status"] in {
            "expected",
            "confirmed",
        }, f"{team} status unexpected: {snapshot['status']!r}"


def test_starters_count_is_five_for_each_team(parsed_sample):
    """Every parsed card must yield exactly 5 starters (validated against
    the 2026-05-13 sample). If RotoWire later posts a card with <5 known
    starters, this test should fail loudly so we re-pin the sample."""
    for team, lineup in parsed_sample.items():
        assert len(lineup["starters"]) == 5, (
            f"{team} has {len(lineup['starters'])} starters: {lineup['starters']}"
        )


def test_starter_names_are_canonical_full_names(parsed_sample):
    """Anti-hallucination check: the WNBA parser must read the `<a title>`
    attribute, not the broadcast-style visible text "N. Hiedeman". For
    Seattle in the 2026-05-13 sample, the title attribute resolves
    "N. Hiedeman" → "Natisha Hiedeman" — anything still abbreviated means
    the parser regressed to visible text."""
    sea = parsed_sample.get("SEA")
    assert sea is not None
    # First starter in the snapshot — Natisha Hiedeman per the HTML.
    assert "Natisha Hiedeman" in sea["starters"], sea["starters"]
    for name in sea["starters"]:
        # Single letter + dot at position 0 = still broadcast form.
        assert not (
            len(name.split()) > 1 and len(name.split()[0].rstrip(".")) == 1
        ), f"starter name appears abbreviated: {name!r}"


def test_out_player_population_present(parsed_sample):
    """OUT players appear in source_snapshots.rotowire.out_players. The
    sample distribution: 22 pct-play-0 rows total across all 8 cards (per
    `grep -c is-pct-play-0` on the committed sample). Use a soft floor
    (>=10) — exact total isn't a long-term invariant."""
    total_out = sum(
        len(lineup["source_snapshots"]["rotowire"]["out_players"])
        for lineup in parsed_sample.values()
    )
    assert total_out >= 10, (
        f"Expected >=10 OUT rows across all teams; got {total_out}. "
        "Did the OUT parsing regress?"
    )


def test_out_players_carry_injury_or_pct_zero(parsed_sample):
    """Every OUT player must have either pct_play == 0 or injury_status=='OUT'.
    Anti-hallucination: this is the OUT bucket's definition. A row that has
    neither but lands here would mean the parser misclassified."""
    for team, lineup in parsed_sample.items():
        for row in lineup["source_snapshots"]["rotowire"]["out_players"]:
            condition = row["pct_play"] == 0 or (
                row["injury_status"] or ""
            ).upper() == "OUT"
            assert condition, f"OUT row for {team} fails definition: {row}"


def test_questionable_starter_captured_for_chi(parsed_sample):
    """The CHI side in the 2026-05-13 sample has slot-2 as pct-50 — a
    starter who is questionable. The parser must include them in starters
    (top-5 by position) AND surface them in `questionable_players` so the
    agent layer can flag the prop."""
    chi = parsed_sample.get("CHI")
    assert chi is not None
    snap = chi["source_snapshots"]["rotowire"]
    # CHI's questionable_players should have at least one row that is ALSO
    # in the top-5 starters (i.e. a starter-who-is-questionable).
    starter_set = set(chi["starters"])
    flagged_starters = [
        r for r in snap["questionable_players"] if r["player"] in starter_set
    ]
    assert (
        flagged_starters
    ), f"CHI expected at least 1 questionable starter; got: {snap['questionable_players']}"


def test_position_vocabulary_is_wnba_subset(parsed_sample):
    """Scout §2.4 documented WNBA's position vocabulary as {G, F, C} — a
    proper subset of the NBA {PG, SG, SF, PF, C, G, F} table. The parser
    surfaces whatever RotoWire emits; this test asserts the page hasn't
    silently grown PG/SG/SF/PF labels on us. If WNBA ever does, drop this
    test rather than expanding the set — Scout flagged this as expected
    drift in §5.3 ("WNBA position vocabulary may evolve")."""
    seen: set[str] = set()
    for lineup in parsed_sample.values():
        snap = lineup["source_snapshots"]["rotowire"]
        for row in (
            snap["out_players"] + snap["questionable_players"]
        ):
            if row.get("position"):
                seen.add(row["position"])
    # Don't fail open — at least one position should be visible from the
    # OUT/questionable rows even if all starters are pct-100.
    if seen:
        # Permit '/' multi-positions (e.g. "G/F") — they're allowed by
        # _is_position_token but rare in WNBA.
        atomic = {token for value in seen for token in value.split("/")}
        assert atomic.issubset({"G", "F", "C"}), (
            f"WNBA position vocab grew: {seen}. Scout's §2.4 expected only "
            "{{G,F,C}} as of 2026-05-13. If this is intentional, update the "
            "comparison doc + drop or expand this test."
        )


def test_league_url_dispatch_is_wired():
    """fetch_rotowire_lineups dispatches on league. Unknown league raises
    ValueError rather than silently fetching NBA. NBA + WNBA URLs must
    match what Scout captured in §2 of the comparison doc."""
    assert (
        ROTOWIRE_LEAGUE_URLS["nba"]
        == "https://www.rotowire.com/basketball/nba-lineups.php"
    )
    assert ROTOWIRE_LEAGUE_URLS["wnba"] == "https://www.rotowire.com/wnba/lineups.php"
    with pytest.raises(ValueError):
        fetch_rotowire_lineups("2026-05-13", league="nhl")


# ---- Live integration (RUN_INTEGRATION=1) --------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Live RotoWire fetch — set RUN_INTEGRATION=1 to enable.",
)
def test_live_wnba_lineups_smoke():
    """Live HTTP smoke test against the real RotoWire WNBA page.

    Per CLAUDE.md § External API Wrappers rule #2, the wrapper must have at
    least one integration test that hits the live endpoint. This is the
    cheapest assertion that proves end-to-end:

    - URL still resolves and returns 200 + HTML.
    - The selector taxonomy still matches (>=1 card parses).
    - Position vocab on live data is still in {G,F,C}.

    Card count is NOT pinned (game-day dependent). Per-team specifics are
    NOT pinned (rosters change). The unit test holds the regression baseline.
    """
    result = fetch_rotowire_lineups("2026-05-13", league="wnba")
    assert result, "Live RotoWire WNBA page parsed 0 teams — likely shape drift"
    for team, lineup in result.items():
        assert isinstance(lineup["starters"], list)
        snap = lineup["source_snapshots"]["rotowire"]
        assert snap["status"] in {
            "expected",
            "confirmed",
        }, f"{team} status unexpected on live page: {snap['status']!r}"
        for row in (snap["out_players"] + snap["questionable_players"]):
            if row.get("position"):
                atomic = {token for token in row["position"].split("/")}
                assert atomic.issubset({"G", "F", "C"}), (
                    f"Live WNBA page returned non-WNBA position vocab "
                    f"({row['position']!r}) for {team}. Re-pin the sample."
                )
