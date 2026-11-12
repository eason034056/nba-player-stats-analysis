"""SPO-137a: BDL status words fold before they are stored.

The recorded injury page is the only row shape. A test copies one real
row and rewrites ``status``. The stored word is the canonical
capitalization. ``raw_status`` and ``injury_status_raw`` keep the
rewritten string, including case and surrounding whitespace.
"""

from __future__ import annotations

import copy
import logging

import pytest

from app.services.nba_injuries import (
    matched_injury_words,
    normalize_bdl_injuries,
    team_id_to_code_from_standings,
)
from app.services.pick_signals import injury_blocks_combined
from tests.test_spo131_bdl_injuries import INJURY_PAGE, STANDINGS
from tests.test_spo135c_bdl_injury_status import _named, _picks_for

_FETCHED_AT = "2026-11-11T18:00:00+00:00"
_MAPPING = team_id_to_code_from_standings(STANDINGS)

# (rewritten status, stored status, logged as unrecognized)
_KEPT = (
    ("out", "Out", False),
    ("OUT", "Out", False),
    (" Out ", "Out", False),
    ("out for season", "Out", True),
    ("OUT FOR SEASON", "Out", True),
    ("out  for   season", "Out", True),
    ("doubtful", "Questionable", False),
    ("DOUBTFUL", "Questionable", False),
    ("questionable", "Questionable", False),
    ("day-to-day", "Day-To-Day", False),
    ("probable", "Probable", False),
    ("shout", "Questionable", True),
)
_DROPPED = ("available", "AVAILABLE", " Available ")


def _recorded_row() -> dict:
    """One real page row. Only the caller changes ``status``."""
    source = next(
        row
        for row in INJURY_PAGE["data"]
        if row["player"]["first_name"] == "Dominick"
        and row["player"]["last_name"] == "Barlow"
    )
    return copy.deepcopy(source)


def _normalize(status: str) -> list[dict]:
    row = _recorded_row()
    row["status"] = status
    return normalize_bdl_injuries([row], _MAPPING, fetched_at=_FETCHED_AT)


@pytest.mark.parametrize(("variant", "stored", "unrecognized"), _KEPT)
def test_status_variant_stores_the_canonical_word(
    variant: str,
    stored: str,
    unrecognized: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Case and whitespace fold. The original string stays on both raw fields."""
    with caplog.at_level(logging.WARNING):
        entries = _normalize(variant)
    assert len(entries) == 1
    assert entries[0]["status"] == stored
    assert entries[0]["raw_status"] == variant
    injury_status, injury_status_raw = matched_injury_words(entries[0])
    assert injury_status == stored
    assert injury_status_raw == variant
    logged = "unrecognized BDL injury status" in caplog.text
    assert logged is unrecognized


@pytest.mark.parametrize("variant", _DROPPED)
def test_available_variant_is_dropped(variant: str) -> None:
    """Available is not an injury, in any case, with or without padding."""
    assert _normalize(variant) == []


def test_lowercase_out_blocks_the_pick_like_canonical_out() -> None:
    """A source word ``out`` stores Out and nulls the blend, as ``Out`` does."""
    folded = _normalize("out")
    assert len(folded) == 1
    canonical = _normalize("Out")
    assert canonical[0]["status"] == "Out"
    player = folded[0]["player"]
    assert player == canonical[0]["player"]
    picks = _picks_for([player], folded)
    row = next(pick for pick in _named(picks, player) if pick.metric == "points")
    plain = next(
        pick
        for pick in _named(_picks_for([player], canonical), player)
        if pick.metric == "points"
    )
    assert row.injury_status == "Out"
    assert row.injury_status_raw == "out"
    assert injury_blocks_combined(row.injury_status) is True
    assert row.combined_probability is None
    assert plain.combined_probability is None
    assert injury_blocks_combined(plain.injury_status) is True
