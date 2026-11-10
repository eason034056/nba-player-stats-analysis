"""Proxy lines used when the repo has no historical sportsbook number.

MED20 is the default. It is the x.5 line that splits the player's previous
20 games closest to 50/50, which is what a book targeting a coin-flip would
post if it only knew those 20 results. L10 is the supported alternative:
``floor(mean of the previous 10 games) + 0.5``. L5 and ALL are the same
mean rule on a shorter window and on the whole prior sample. They exist so
a reader can see that the hit rate moves when the proxy moves.
"""

from __future__ import annotations

import math

import numpy as np

PROXY_KINDS = ("MED20", "L10", "L5", "ALL")
DEFAULT_PROXIES = ("MED20", "L10", "L5", "ALL")
# The agent scorecard is replayed on these two. L5 and ALL stay daily-only
# sensitivity checks; they do not change the agent path's published tables.
AGENT_PROXIES = ("MED20", "L10")


def proxy_line(
    prior_vals_newest_first: list[float] | np.ndarray, kind: str
) -> float | None:
    """Return an x.5 proxy line, or None when ``kind`` has no values to use.

    Args:
        prior_vals_newest_first: Stat values from games strictly before the
            target, newest game first. The order matters for L10, L5, and
            MED20, which look at a prefix of this list. It does not matter
            for ALL.
        kind: One of ``MED20``, ``L10``, ``L5``, ``ALL``.

    Returns:
        The proxy line. MED20 breaks ties toward the lower line. A window
        whose only positive candidate set is empty (every value is 0 or
        negative) returns 0.5, matching a book that still has to post a
        half-point number.
    """
    if kind == "MED20":
        window = np.asarray(prior_vals_newest_first[:20], dtype=float)
        if window.size == 0:
            return None
        start = math.floor(float(window.min())) - 0.5
        stop = math.floor(float(window.max())) + 1.0
        candidates = np.arange(start, stop, 1.0)
        candidates = candidates[candidates > 0]
        if candidates.size == 0:
            return 0.5
        # First minimum wins, and candidates ascend, so a tie takes the
        # lower line.
        deviation = [
            abs(float((window > candidate).mean()) - 0.5) for candidate in candidates
        ]
        return float(candidates[int(np.argmin(deviation))])

    if kind == "L10":
        window_list = list(prior_vals_newest_first[:10])
    elif kind == "L5":
        window_list = list(prior_vals_newest_first[:5])
    elif kind == "ALL":
        window_list = list(prior_vals_newest_first)
    else:
        raise ValueError(f"Unknown proxy kind: {kind!r}. Known: {PROXY_KINDS}")
    if not window_list:
        return None
    return math.floor(float(np.mean(np.asarray(window_list, dtype=float)))) + 0.5
