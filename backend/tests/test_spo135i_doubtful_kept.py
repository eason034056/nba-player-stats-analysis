"""SPO-135i: the NBA injury cache keeps Doubtful, and the agents still read it as unresolved.

Before SPO-135i the cache stored Doubtful as Questionable, so readers that
compare against an exact list never saw the word. Now they must treat
Doubtful the way they treat Questionable, or a Doubtful player reads as healthy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.services.injury_status import is_out_or_unresolved, is_unresolved_injury
from app.services.nba_injuries import normalize_bdl_injuries
from scripts.agents.scoring import compute_scorecard
from tests.test_role_conditioned_scoring import _historical_signals, _market_signals
from tests.test_spo131_qa import _MAPPING, _agent_path, _now_iso, _row, _seed


@pytest.mark.parametrize(
    ("status", "unresolved", "out_or_unresolved"),
    [
        ("Doubtful", True, True),
        ("Questionable", True, True),
        ("Day-To-Day", True, True),
        ("Out", False, True),
        ("Probable", False, False),
        ("Healthy", False, False),
        ("doubtful", False, False),
        (None, False, False),
    ],
)
def test_status_buckets(status: str | None, unresolved: bool, out_or_unresolved: bool) -> None:
    assert is_unresolved_injury(status) is unresolved
    assert is_out_or_unresolved(status) is out_or_unresolved


def test_a_doubtful_player_reads_as_caution(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row("Jackson Jr.")
    row["status"] = "Doubtful"
    entries = normalize_bdl_injuries([row], _MAPPING, fetched_at=_now_iso())
    assert [entry["status"] for entry in entries] == ["Doubtful"]

    historical = _agent_path(monkeypatch, _seed({"fetched_at": _now_iso(), "entries": entries}))
    availability = historical.get_availability_context("Jaren Jackson Jr", league="nba")

    assert availability["signal"] == "caution"
    assert availability["details"]["status"] == "Doubtful"


def _scorecard_with_injured_teammate(status: str) -> dict:
    signals = _historical_signals()
    signals["auto_teammate_impact"] = {
        "details": {
            "teammate_chemistry": [
                {
                    "star": "Star Teammate",
                    "injury_status": status,
                    "chemistry_delta": 0.06,
                    "with": {"n": 12},
                    "without": {"n": 6},
                }
            ]
        }
    }
    signals["get_own_team_injury_report"] = {
        "details": {"injuries": [{"player": "Bench Teammate", "status": status}]}
    }
    return compute_scorecard(signals, {}, _market_signals())


def test_the_scorecard_treats_doubtful_like_questionable() -> None:
    doubtful = _scorecard_with_injured_teammate("Doubtful")
    questionable = _scorecard_with_injured_teammate("Questionable")
    healthy = _scorecard_with_injured_teammate("Healthy")

    assert "unresolved_teammate_injury" in doubtful["data_quality_flags"]
    assert doubtful["data_quality_flags"] == questionable["data_quality_flags"]
    assert doubtful["query_aligned_context"]["injuries"] == {
        "unresolved": True,
        "questionable_players": ["Bench Teammate", "Star Teammate"],
        "out_players": [],
    }
    assert doubtful["query_aligned_context"]["injuries"] == questionable["query_aligned_context"]["injuries"]
    assert doubtful["adjustments"]["teammate_adj"] == questionable["adjustments"]["teammate_adj"] != 0
    assert healthy["query_aligned_context"]["injuries"]["unresolved"] is False
