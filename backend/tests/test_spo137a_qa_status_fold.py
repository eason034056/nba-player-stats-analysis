"""SPO-137a QA: fold edge cases on a recorded injury row.

The only row shape is the recorded Dominick Barlow page row. Tests
rewrite ``status`` and leave the rest of the row alone. Stored
``raw_status`` and ``injury_status_raw`` must equal that rewritten
string. top_read checks use a recorded Out entry with only the
already-normalized ``status`` rewritten.
"""

from __future__ import annotations

import pytest

from app.services.daily_analysis import best_top_reads
from app.services.nba_injuries import matched_injury_words
from app.services.pick_signals import injury_blocks_combined
from tests.test_spo135c_bdl_injury_status import _entry
from tests.test_spo135g_top_read_out import (
    _EVENT_ID,
    _analyze,
    _books,
    _cache,
    _recorded_event,
    _sources,
)
from tests.test_spo137a_status_case import _normalize


# A blank status is missing data. The row stays, stored as Questionable.
# Only Available is dropped. The original string stays on raw_status.
_BLANK = ("", "   ", "\t\n", "\xa0")

# (rewritten status, stored canonical word)
_PHRASES = (
    ("Out (Season)", "Out"),
    ("Out - Personal", "Out"),
    ("out\xa0for\u00a0season", "Out"),
    ("Doubtful ", "Questionable"),
    ("Day To Day", "Day-To-Day"),
    ("OFS", "Questionable"),
    ("Questionable (out last game)", "Questionable"),
    ("Out of rotation", "Questionable"),
)

_TOP_READ_OUT = ("out", " OUT ")


def _assert_raw_kept(entries: list[dict], variant: str, stored: str) -> None:
    assert len(entries) == 1
    assert entries[0]["status"] == stored
    assert entries[0]["raw_status"] == variant
    injury_status, injury_status_raw = matched_injury_words(entries[0])
    assert injury_status == stored
    assert injury_status_raw == variant


@pytest.mark.parametrize("variant", _BLANK)
def test_blank_status_on_a_recorded_row_is_questionable(variant: str) -> None:
    """A recorded injury row with an empty or whitespace status stays on the report."""
    _assert_raw_kept(_normalize(variant), variant, "Questionable")
    assert injury_blocks_combined("Questionable") is False


@pytest.mark.parametrize(("variant", "stored"), _PHRASES)
def test_folded_phrase_keeps_the_rewritten_raw_string(
    variant: str, stored: str
) -> None:
    """Fold maps the phrase; the original string stays on both raw fields."""
    entries = _normalize(variant)
    _assert_raw_kept(entries, variant, stored)
    assert injury_blocks_combined(entries[0]["status"]) is (stored == "Out")


@pytest.mark.parametrize("status", _TOP_READ_OUT)
def test_top_read_skips_a_recorded_out_row_with_folded_status(
    status: str,
) -> None:
    """top_read uses the same Out check as the blend, not an exact 'Out'."""
    out = dict(_entry("Out"))
    out["status"] = status
    next_row = _entry("Questionable", raw="Doubtful")
    assert out["player"] != next_row["player"]
    best_source, nxt, _healthy = _sources(out["player"])
    picks = _analyze(
        _recorded_event(_EVENT_ID),
        _books({best_source: out["player"], nxt: next_row["player"]}),
        {out["player"]: 0.91, next_row["player"]: 0.72},
    )
    reads = best_top_reads(_cache(picks), injury_entries=[out, next_row])
    assert reads[_EVENT_ID].player == next_row["player"]
    assert out["player"] not in {read.player for read in reads.values()}
    assert injury_blocks_combined(status) is True
