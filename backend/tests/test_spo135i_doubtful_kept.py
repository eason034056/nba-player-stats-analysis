"""SPO-135i: Doubtful stays its own injury status.

Before SPO-135i the cache stored Doubtful as Questionable. A reader that
compares against an exact list must treat Doubtful as unresolved, the same
way it treats Questionable.
"""

from __future__ import annotations

import pytest

from app.services.injury_status import is_out_or_unresolved, is_unresolved_injury


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
