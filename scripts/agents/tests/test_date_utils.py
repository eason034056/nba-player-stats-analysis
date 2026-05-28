"""SPO-67 — unit tests for scripts/agents/date_utils.py.

`date_utils.py` sits on a critical path: the LangGraph planner emits colloquial
dates ("today"/"tomorrow") → ``normalize_date()`` → YYYY-MM-DD →
``date_to_utc_range()`` → the UTC window sent to The Odds API. A silent bug here
queries the wrong day → wrong/empty props, so this is pure deterministic logic
worth locking down.

Anti-flake policy (per ticket): both functions read ``datetime.now().astimezone()``
(machine-local tz), so we never hard-code an absolute date or UTC string. Expected
values for the relative-date cases are derived from the same local clock at test
time, and ``date_to_utc_range`` is checked against structural invariants
(tz-aware UTC, ordering, ~24h span) rather than absolute strings — so the suite
passes in any CI timezone.
"""

from datetime import datetime, timedelta, timezone

import pytest

from date_utils import date_to_utc_range, normalize_date


def _local_today() -> "datetime.date":
    """Today's date in the machine-local tz — the exact source the SUT uses."""
    return datetime.now().astimezone().date()


# ---------------------------------------------------------------------------
# normalize_date — relative keywords
# ---------------------------------------------------------------------------

def test_today_returns_local_today():
    assert normalize_date("today") == _local_today().strftime("%Y-%m-%d")


@pytest.mark.parametrize("word", ["tomorrow", "tomorow", "tommorow"])
def test_tomorrow_and_misspellings_return_today_plus_one(word):
    expected = (_local_today() + timedelta(days=1)).strftime("%Y-%m-%d")
    assert normalize_date(word) == expected


def test_keywords_are_case_insensitive_and_trimmed():
    expected = _local_today().strftime("%Y-%m-%d")
    assert normalize_date("  TODAY  ") == expected
    assert normalize_date("ToMoRrOw") == (
        _local_today() + timedelta(days=1)
    ).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# normalize_date — already-formatted dates pass through
# ---------------------------------------------------------------------------

def test_iso_date_returned_unchanged():
    assert normalize_date("2025-03-13") == "2025-03-13"


def test_iso_date_with_surrounding_whitespace():
    # strip() runs before the regex, so padded ISO dates still match.
    assert normalize_date("  2025-03-13  ") == "2025-03-13"


# ---------------------------------------------------------------------------
# normalize_date — invalid input → ""
# ---------------------------------------------------------------------------

def test_invalid_calendar_date_returns_empty():
    # Matches the YYYY-MM-DD regex but Feb 30 is not a real day.
    assert normalize_date("2025-02-30") == ""


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "next week",
        "yesterday",
        "garbage",
        "03/13/2025",  # wrong separator
        "2025-3-13",   # not zero-padded → regex miss
        "20250313",    # no separators
    ],
)
def test_garbage_strings_return_empty(bad):
    assert normalize_date(bad) == ""


@pytest.mark.parametrize("bad", [None, 12345, [], {}, object()])
def test_non_string_input_returns_empty(bad):
    assert normalize_date(bad) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# date_to_utc_range — valid input: structural invariants only
# ---------------------------------------------------------------------------

def test_valid_date_returns_tz_aware_utc_tuple():
    result = date_to_utc_range("2025-03-13")
    assert result is not None
    start_utc, end_utc = result

    # Both ends are timezone-aware and normalized to UTC.
    assert start_utc.tzinfo is not None
    assert end_utc.tzinfo is not None
    assert start_utc.utcoffset() == timedelta(0)
    assert end_utc.utcoffset() == timedelta(0)


def test_valid_date_start_before_end():
    start_utc, end_utc = date_to_utc_range("2025-03-13")
    assert start_utc < end_utc


def test_valid_date_span_is_about_24h():
    start_utc, end_utc = date_to_utc_range("2025-03-13")
    # The window is 00:00:00 → 23:59:59 local, i.e. 86399s, regardless of tz
    # (a fixed local offset cancels out in the difference).
    span = (end_utc - start_utc).total_seconds()
    assert span == pytest.approx(86399, abs=2)


# ---------------------------------------------------------------------------
# date_to_utc_range — invalid input → None
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad",
    [
        "",
        "today",          # colloquial, not pre-normalized
        "2025-3-13",      # not zero-padded
        "03/13/2025",     # wrong separator
        "garbage",
        "2025-13-01",     # month 13 → ValueError inside the try
        "2025-02-30",     # impossible calendar date → ValueError
    ],
)
def test_malformed_input_returns_none(bad):
    assert date_to_utc_range(bad) is None
