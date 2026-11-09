"""Hit rate, ROI, Brier score, Wilson intervals, and calibration buckets.

The naive baseline is the hit rate of the picked mix of directions if those
directions had been applied at the group's base rates, with no selection:

    naive = (over_picks * P(over) + under_picks * P(under)) / picks

``P(over)`` and ``P(under)`` are measured on every prop in the group, not
only on the picks. Lift is the pick hit rate minus that baseline.

ROI at assumed -110 is a monotone function of the hit rate, because every
winning bet pays ``100/110`` and every losing bet costs 1, and an x.5 line
does not push on an integer stat:

    roi = hit_rate * (210/110) - 1

The 95% interval on that ROI is the Wilson interval on the hit rate passed
through the same function. When a pick carries a real American price, that
identity no longer holds, and the ROI interval is a normal approximation on
the mean profit instead. Brier intervals are normal approximations on the
mean squared error. All three intervals treat picks as independent, so they
are too narrow: many props share a game.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

from evaluation.odds_history import ASSUMED_AMERICAN_ODDS, unit_profit

# Frontend `getProbabilityLevel`: high at or above 0.70, otherwise medium.
# The picks page only shows rows that already cleared 0.65, so "medium" is
# the band [0.65, 0.70).
HIGH_TIER_PROBABILITY = 0.70

PICK_EDGES = (0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.0001)
P_OVER_EDGES = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0001)
AGENT_P_OVER_EDGES = (0.0, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 1.0001)
CONFIDENCE_EDGES = (0.0, 0.3, 0.5, 0.6, 0.7, 0.76)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for ``k`` successes in ``n`` trials.

    Args:
        k: Number of hits.
        n: Number of picks. Zero returns a pair of NaNs.
        z: Normal quantile. 1.96 is the two-sided 95% point.

    Returns:
        ``(low, high)`` on the probability scale, not in percent.
    """
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    z2 = z * z
    den = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / den
    margin = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / den
    return center - margin, center + margin


def roi_from_hit_rate(hit_rate: float) -> float:
    """ROI at -110 as a fraction of stake, given a hit rate."""
    return hit_rate * (210.0 / 110.0) - 1.0


def _normal_ci(
    total: float, total_sq: float, n: int, z: float = 1.96
) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    mean = total / n
    if n == 1:
        return mean, mean
    var = (total_sq - (total * total) / n) / (n - 1)
    se = math.sqrt(max(var, 0.0) / n)
    return mean - z * se, mean + z * se


@dataclass
class Summary:
    """Aggregated pick quality for one group of props."""

    props: int
    picks: int
    hits: int
    hit_rate: float
    hit_lo: float
    hit_hi: float
    roi: float
    roi_lo: float
    roi_hi: float
    roi_method: str
    avg_pred: float
    naive: float
    lift: float
    brier: float
    brier_lo: float
    brier_hi: float
    p_over_brier: float
    actual_over_rate: float
    mean_p_over: float
    base_rate_brier: float
    clv_prob: float | None
    clv_line: float | None
    clv_n: int
    priced_picks: int

    @property
    def calibration_gap(self) -> float:
        """Absolute gap between the mean predicted pick probability and the hit rate.

        This is the headline calibration gap the CI guard watches. It is
        ``|mean(prob) - hit rate|`` on the picks in the group.
        """
        if self.picks <= 0 or math.isnan(self.avg_pred) or math.isnan(self.hit_rate):
            return float("nan")
        return abs(self.avg_pred - self.hit_rate)


@dataclass
class Accumulator:
    """One-pass counters for a group of prop rows."""

    props: int = 0
    picks: int = 0
    hits: int = 0
    prob_sum: float = 0.0
    brier_sum: float = 0.0
    brier_sq: float = 0.0
    over_hits: int = 0
    under_hits: int = 0
    over_picks: int = 0
    profit_sum: float = 0.0
    profit_sq: float = 0.0
    priced_picks: int = 0
    clv_prob_sum: float = 0.0
    clv_line_sum: float = 0.0
    clv_n: int = 0
    p_over_sum: float = 0.0
    p_over_brier_sum: float = 0.0
    assumed_profit_picks: int = 0

    def add(self, row: object) -> None:
        """Add one daily or agent row. Missing prices fall back to -110."""
        over_hit = int(row.over_hit)  # type: ignore[attr-defined]
        actual = float(row.actual)  # type: ignore[attr-defined]
        line = float(row.line)  # type: ignore[attr-defined]
        p_over = float(row.p_over)  # type: ignore[attr-defined]
        self.props += 1
        self.over_hits += over_hit
        self.under_hits += int(actual < line)
        self.p_over_sum += p_over
        err_over = p_over - over_hit
        self.p_over_brier_sum += err_over * err_over

        pick = row.pick  # type: ignore[attr-defined]
        if pick is None:
            return
        hit = int(row.hit)  # type: ignore[attr-defined]
        prob = float(row.prob)  # type: ignore[attr-defined]
        price = row.price  # type: ignore[attr-defined]
        odds = ASSUMED_AMERICAN_ODDS if price is None else int(price)
        profit = unit_profit(odds, bool(hit))
        se = prob - hit
        self.picks += 1
        self.hits += hit
        self.prob_sum += prob
        self.brier_sum += se * se
        self.brier_sq += (se * se) * (se * se)
        self.over_picks += int(pick == "over")
        self.profit_sum += profit
        self.profit_sq += profit * profit
        if price is None:
            self.assumed_profit_picks += 1
        else:
            self.priced_picks += 1
        clv_prob = row.clv_prob  # type: ignore[attr-defined]
        clv_line = row.clv_line  # type: ignore[attr-defined]
        if clv_prob is not None and clv_line is not None:
            self.clv_prob_sum += float(clv_prob)
            self.clv_line_sum += float(clv_line)
            self.clv_n += 1

    def finish(self) -> Summary:
        """Collapse the counters into rates, ROI, and intervals."""
        props = self.props
        picks = self.picks
        hits = self.hits
        hit_rate = hits / picks if picks else float("nan")
        hit_lo, hit_hi = wilson(hits, picks)
        avg_pred = self.prob_sum / picks if picks else float("nan")
        brier = self.brier_sum / picks if picks else float("nan")
        brier_lo, brier_hi = _normal_ci(self.brier_sum, self.brier_sq, picks)
        if props:
            p_over = self.over_hits / props
            p_under = self.under_hits / props
            mean_p_over = self.p_over_sum / props
            p_over_brier = self.p_over_brier_sum / props
            base_rate_brier = p_over * (1.0 - p_over)
        else:
            p_over = p_under = mean_p_over = p_over_brier = base_rate_brier = float(
                "nan"
            )
        if picks:
            naive = (
                self.over_picks * p_over + (picks - self.over_picks) * p_under
            ) / picks
            lift = hit_rate - naive
        else:
            naive = lift = float("nan")
        if picks and self.priced_picks == 0:
            roi = roi_from_hit_rate(hit_rate)
            roi_lo = roi_from_hit_rate(hit_lo)
            roi_hi = roi_from_hit_rate(hit_hi)
            # Wilson endpoints can arrive unordered if a caller passes a
            # decreasing transform. -110 ROI increases with the hit rate.
            roi_method = "wilson"
        elif picks:
            roi = self.profit_sum / picks
            roi_lo, roi_hi = _normal_ci(self.profit_sum, self.profit_sq, picks)
            roi_method = "normal"
        else:
            roi = roi_lo = roi_hi = float("nan")
            roi_method = "none"
        clv_prob = self.clv_prob_sum / self.clv_n if self.clv_n else None
        clv_line = self.clv_line_sum / self.clv_n if self.clv_n else None
        return Summary(
            props=props,
            picks=picks,
            hits=hits,
            hit_rate=hit_rate,
            hit_lo=hit_lo,
            hit_hi=hit_hi,
            roi=roi,
            roi_lo=roi_lo,
            roi_hi=roi_hi,
            roi_method=roi_method,
            avg_pred=avg_pred,
            naive=naive,
            lift=lift,
            brier=brier,
            brier_lo=brier_lo,
            brier_hi=brier_hi,
            p_over_brier=p_over_brier,
            actual_over_rate=p_over,
            mean_p_over=mean_p_over,
            base_rate_brier=base_rate_brier,
            clv_prob=clv_prob,
            clv_line=clv_line,
            clv_n=self.clv_n,
            priced_picks=self.priced_picks,
        )


def summarize(rows: Sequence[object]) -> Summary:
    """Summarize one flat collection of prop rows."""
    acc = Accumulator()
    for row in rows:
        acc.add(row)
    return acc.finish()


def grouped(
    rows: Sequence[object], key_fn: Callable[[object], object]
) -> list[tuple[object, Summary]]:
    """Group rows by ``key_fn``, skipping keys that are None, and sort the keys."""
    buckets: dict[object, Accumulator] = {}
    for row in rows:
        key = key_fn(row)
        if key is None:
            continue
        acc = buckets.get(key)
        if acc is None:
            acc = Accumulator()
            buckets[key] = acc
        acc.add(row)
    return [(key, buckets[key].finish()) for key in sorted(buckets, key=_sort_key)]


def _sort_key(value: object) -> tuple:
    if isinstance(value, tuple):
        return tuple(_sort_key(part) for part in value)
    return (str(value),)


@dataclass
class ReliabilityBin:
    """One probability bucket."""

    lo: float
    hi: float
    n: int
    avg_pred: float
    actual: float

    @property
    def gap(self) -> float:
        return self.avg_pred - self.actual


def reliability(
    rows: Sequence[object],
    value_fn: Callable[[object], float | None],
    outcome_fn: Callable[[object], float | None],
    edges: Sequence[float],
) -> list[ReliabilityBin]:
    """Bin ``value_fn`` on ``[lo, hi)`` and compare the mean prediction to the outcome.

    Empty bins are omitted. ``edges`` must be strictly increasing. A value
    that falls on the last edge is excluded, so the final edge should sit
    just above the largest probability that can occur (the tables use
    1.0001 for that reason).
    """
    counts = [0 for _ in range(len(edges) - 1)]
    pred_sum = [0.0 for _ in counts]
    out_sum = [0.0 for _ in counts]
    for row in rows:
        value = value_fn(row)
        outcome = outcome_fn(row)
        if value is None or outcome is None:
            continue
        for index in range(len(edges) - 1):
            if edges[index] <= value < edges[index + 1]:
                counts[index] += 1
                pred_sum[index] += value
                out_sum[index] += outcome
                break
    bins: list[ReliabilityBin] = []
    for index, n in enumerate(counts):
        if n == 0:
            continue
        bins.append(
            ReliabilityBin(
                lo=edges[index],
                hi=edges[index + 1],
                n=n,
                avg_pred=pred_sum[index] / n,
                actual=out_sum[index] / n,
            )
        )
    return bins


def tier_name(prob: float | None) -> str | None:
    """Frontend confidence tier. None when the row was not a pick."""
    if prob is None:
        return None
    if prob >= HIGH_TIER_PROBABILITY:
        return "high (>=0.70)"
    return "medium [0.65, 0.70)"


def confidence_bucket(confidence: float) -> str | None:
    """Scorecard confidence bin, right edge excluded. None if it falls outside."""
    labels = ("[0.0, 0.3)", "[0.3, 0.5)", "[0.5, 0.6)", "[0.6, 0.7)", "[0.7, 0.76)")
    for index, label in enumerate(labels):
        if CONFIDENCE_EDGES[index] <= confidence < CONFIDENCE_EDGES[index + 1]:
            return label
    return None


def is_postable(row: object) -> bool:
    """True for props a book is more likely to post a real number on.

    Keeps players whose previous 10 games averaged at least 20 minutes,
    drops free-throws and field-goals made (empty inventory in the odds
    client), and drops threes or steals priced at 0.5 when the under was
    already a near certainty (``p_under >= 0.95``).
    """
    if float(row.l10_min) < 20:  # type: ignore[attr-defined]
        return False
    market = row.market  # type: ignore[attr-defined]
    if market in ("ftm", "fgm"):
        return False
    p_under = getattr(row, "p_under", None)
    if (
        row.line == 0.5  # type: ignore[attr-defined]
        and market in ("threes_made", "steals")
        and p_under is not None
        and float(p_under) >= 0.95
    ):
        return False
    return True


@dataclass
class Composition:
    """How the selected picks are distributed."""

    picks: int
    under_share: float
    line_half_share: float
    hot_share: float


def composition(rows: Sequence[object]) -> Composition:
    """Under share, 0.5-line share, and share with probability >= 0.95.

    Computed on picks only. A row with ``pick is None`` is ignored.
    """
    picks = [row for row in rows if row.pick is not None]  # type: ignore[attr-defined]
    n = len(picks)
    if n == 0:
        return Composition(0, float("nan"), float("nan"), float("nan"))
    unders = sum(1 for row in picks if row.pick == "under")  # type: ignore[attr-defined]
    halves = sum(1 for row in picks if row.line == 0.5)  # type: ignore[attr-defined]
    hot = sum(1 for row in picks if row.prob is not None and float(row.prob) >= 0.95)  # type: ignore[attr-defined]
    return Composition(n, unders / n, halves / n, hot / n)


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation. NaN when either side has no variance."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return float("nan")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0.0 or den_y == 0.0:
        return float("nan")
    return num / (den_x * den_y)
