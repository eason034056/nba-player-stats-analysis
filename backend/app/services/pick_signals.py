"""Per-prop signal verdicts and the combined probability for one Daily Pick.

NBA picks receive four signals, in a fixed order. A missing input for
one of those signals sets ``value`` and ``verdict`` to None. It is not
neutral, and it adds nothing to the log-odds blend.

There is no projection source until the ML model ships, so the
projection slot is omitted. It is not serialized as null. A market,
last-10, history, or defense input that exists and fails at runtime
still serializes as null. ``combined_probability`` already treats a
missing projection as zero, and dropping the slot does not change it.

Every rule is relative to the pick's side (over or under).

* ``market`` — no-vig consensus of books posted at the pick's line.
* ``last10`` — strict hits in the last 10 non-DNP games, shown as ``k/10``.
* ``history`` — the published historical ``probability`` for the side.
* ``defense`` — ``opponent_position_rank``, then ``opponent_rank``.
  Rank 1 is the weakest defense. The game log fills that number.

``combined_probability`` starts from the market no-vig log-odds, adds
bounded adjustments from the other four signals, and applies Platt scaling
to the adjustment total only. No market price, or an injury status of Out
or Doubtful, returns None. Doubtful from the BALLDONTLIE cache is stored
as Questionable; that block reads ``raw_status``. WNBA does not call
this module.
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from app.models.schemas import PickSignal
from app.services.pick_signal_constants import (
    ADJUSTMENT_CAP,
    DEFENSE_RANK_MIDPOINT,
    DEFENSE_RANK_SCALE,
    DEFENSE_STRONG_AT,
    DEFENSE_WEAK_AT,
    DEFENSE_WEIGHT,
    HISTORY_AGAINST_AT,
    HISTORY_LOGIT_WEIGHT,
    HISTORY_SUPPORTS_AT,
    LAST10_AGAINST_AT,
    LAST10_GAMES,
    LAST10_LOGIT_WEIGHT,
    LAST10_SUPPORTS_AT,
    MARKET_AGAINST_AT,
    MARKET_SUPPORTS_AT,
    PLATT_A,
    PLATT_B,
    PROJECTION_AGAINST_AT,
    PROJECTION_EDGE_WEIGHT,
    PROJECTION_SUPPORTS_AT,
    TOTAL_ADJUSTMENT_CAP,
)
from app.services.prob import american_to_prob, calculate_consensus_mean, devig

SUPPORTS = "supports"
NEUTRAL = "neutral"
AGAINST = "against"

SIGNAL_SPECS: tuple[tuple[str, str], ...] = (
    ("market", "Market price"),
    ("last10", "Last 10 games"),
    ("history", "All-game hit rate"),
    ("defense", "Opponent defense"),
)
# Kept for the model that will put this slot back on the list.
PROJECTION_SIGNAL_SPEC: tuple[str, str] = ("projection", "Projection")

_INJURY_BLOCK = frozenset({"out", "doubtful"})


def _finite(value: object) -> float | None:
    """Return ``value`` as a float, or None when it is missing or not finite."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _round_half_away(value: float, digits: int) -> float:
    """Round half away from zero, matching the client's percent display."""
    quant = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def format_percent(probability: float) -> str:
    """One-decimal percent, half away from zero. ``0.655`` → ``65.5%``."""
    return f"{_round_half_away(probability * 100.0, 1):.1f}%"


def format_projection(value: float) -> str:
    """One-decimal projected stat. ``29.34`` → ``29.3``."""
    return f"{_round_half_away(value, 1):.1f}"


def format_rank(rank: float) -> str:
    """Rank as the client prints it. ``8`` → ``#8``."""
    if float(rank).is_integer():
        return f"#{int(rank)}"
    return f"#{rank}"


def _clip(value: float, limit: float) -> float:
    """Clip a finite adjustment. A non-finite value is missing and contributes 0.

    ``min(limit, nan)`` returns ``limit``, so a NaN must not reach that call.
    """
    number = _finite(value)
    if number is None:
        return 0.0
    return max(-limit, min(limit, number))


def _logit(probability: float) -> float:
    clipped = min(max(probability, 1e-6), 1.0 - 1e-6)
    return math.log(clipped / (1.0 - clipped))


def _sigmoid(value: float) -> float:
    clipped = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-clipped))


def rate_verdict(
    rate: float | None, *, support_at: float, against_at: float
) -> str | None:
    """Supports at or above ``support_at``, against at or below ``against_at``.

    None stays None. A rate strictly between the two cuts is neutral.
    """
    if rate is None:
        return None
    if rate >= support_at:
        return SUPPORTS
    if rate <= against_at:
        return AGAINST
    return NEUTRAL


def _injury_word_blocks(status: str | None) -> bool:
    """True when this one word is Out or Doubtful, ignoring case and whitespace."""
    if not isinstance(status, str):
        return False
    return status.strip().casefold() in _INJURY_BLOCK


def injury_blocks_combined(
    status: str | None,
    raw_status: str | None = None,
) -> bool:
    """True when the player is Out or Doubtful, ignoring case and whitespace.

    ``status`` is the normalized word on the pick. The BALLDONTLIE cache
    stores Doubtful as Questionable and keeps the source word on
    ``raw_status``. A later pick path passes that source word so the
    block still fires. Either word is enough.
    """
    return _injury_word_blocks(status) or _injury_word_blocks(raw_status)


def american_pairs_at_line(
    bookmakers: Sequence[dict] | None,
    player_name: str,
    line: float,
) -> list[tuple[float, float]]:
    """One ``(over, under)`` American pair per book posted at ``line``.

    A book that posts several points contributes only the pair at ``line``.
    A book missing either side at that point is left out. Alternate lines
    are not averaged in.

    Args:
        bookmakers: Odds API ``bookmakers`` list (the snapshot ``data`` field).
        player_name: Outcome ``description``. Matched exactly.
        line: The pick's modal line.

    Returns:
        Pairs in book order. Empty when no book has both sides at ``line``.
    """
    if not bookmakers or not player_name:
        return []
    target = float(line)
    pairs: list[tuple[float, float]] = []
    for book in bookmakers:
        over_price: float | None = None
        under_price: float | None = None
        for market in book.get("markets") or []:
            for outcome in market.get("outcomes") or []:
                if outcome.get("description") != player_name:
                    continue
                point = _finite(outcome.get("point"))
                if point is None or abs(point - target) > 1e-9:
                    continue
                price = _finite(outcome.get("price"))
                if price is None or price == 0:
                    continue
                name = str(outcome.get("name") or "").strip().casefold()
                if name == "over" and over_price is None:
                    over_price = price
                elif name == "under" and under_price is None:
                    under_price = price
        if over_price is not None and under_price is not None:
            pairs.append((over_price, under_price))
    return pairs


def no_vig_consensus(
    pairs: Sequence[tuple[float, float]],
) -> tuple[float, float] | None:
    """Mean no-vig ``(over, under)`` across books. None when nothing de-vigs.

    Each book is normalized with ``prob.devig``. The books are then averaged
    with ``calculate_consensus_mean``. A pair that cannot be de-vigged is
    skipped rather than failing the whole consensus.
    """
    fair: list[tuple[float, float]] = []
    for over_price, under_price in pairs:
        try:
            over_implied = american_to_prob(over_price)
            under_implied = american_to_prob(under_price)
            fair.append(devig(over_implied, under_implied))
        except (ValueError, ZeroDivisionError):
            continue
    return calculate_consensus_mean(fair)


def side_probability(consensus: tuple[float, float] | None, side: str) -> float | None:
    """The fair probability of ``side`` from a no-vig ``(over, under)`` pair."""
    if consensus is None:
        return None
    if side == "over":
        return consensus[0]
    if side == "under":
        return consensus[1]
    return None


def strict_hits(values: Sequence[float], line: float, side: str) -> int | None:
    """Count strict hits. Over is ``value > line``. Under is ``value < line``.

    A push (``value == line``) is not a hit for either side. A non-finite
    value is dropped before the comparison, so it is not a miss. Returns
    None unless ``side`` is over or under.
    """
    finite = [number for value in values if (number := _finite(value)) is not None]
    if side == "over":
        return sum(1 for value in finite if value > line)
    if side == "under":
        return sum(1 for value in finite if value < line)
    return None


def directional_edge(
    projected_value: float | None, line: float | None, side: str
) -> float | None:
    """Projection minus line for an over, line minus projection for an under.

    Positive means the projection favors the pick's side. The stored
    ``DailyPick.edge`` is always projection minus line; this flips it for
    an under.
    """
    projected = _finite(projected_value)
    threshold = _finite(line)
    if projected is None or threshold is None:
        return None
    raw = projected - threshold
    if side == "over":
        return raw
    if side == "under":
        return -raw
    return None


def defense_rank(
    opponent_position_rank: float | None, opponent_rank: float | None
) -> float | None:
    """Position rank when it is present, otherwise the overall rank."""
    position = _finite(opponent_position_rank)
    if position is not None:
        return position
    return _finite(opponent_rank)


def defense_verdict(rank: float | None, side: str) -> str | None:
    """Verdict for a rank where 1 is the weakest defense.

    An over is supported by a weak defense (rank <= 10) and opposed by a
    strong one (rank > 20). An under is the mirror. None when the rank or
    the side is missing.
    """
    if rank is None or side not in ("over", "under"):
        return None
    weak = rank <= DEFENSE_WEAK_AT
    strong = rank > DEFENSE_STRONG_AT
    if side == "over":
        if weak:
            return SUPPORTS
        if strong:
            return AGAINST
        return NEUTRAL
    if strong:
        return SUPPORTS
    if weak:
        return AGAINST
    return NEUTRAL


def _signal(key: str, label: str, value: str | None, verdict: str | None) -> PickSignal:
    return PickSignal(key=key, label=label, value=value, verdict=verdict)


def market_signal(side_probability_value: float | None) -> PickSignal:
    """No-vig probability of the pick's side. None when the price is missing."""
    key, label = SIGNAL_SPECS[0]
    rate = _finite(side_probability_value)
    if rate is None:
        return _signal(key, label, None, None)
    return _signal(
        key,
        label,
        format_percent(rate),
        rate_verdict(
            rate, support_at=MARKET_SUPPORTS_AT, against_at=MARKET_AGAINST_AT
        ),
    )


def last10_signal(hits: int | None) -> PickSignal:
    """``k/10`` strict hits. Fewer than 10 games is missing, not a short sample."""
    key, label = SIGNAL_SPECS[1]
    if hits is None:
        return _signal(key, label, None, None)
    verdict = rate_verdict(
        float(hits), support_at=LAST10_SUPPORTS_AT, against_at=LAST10_AGAINST_AT
    )
    # rate_verdict compares the count, because the cuts are 6 and 4 of 10.
    return _signal(key, label, f"{hits}/{LAST10_GAMES}", verdict)


def history_signal(history_rate: float | None) -> PickSignal:
    """The side's all-game rate. Supports at 0.55 and against at 0.45.

    The cuts apply to the rate that was passed in. A rate of 0.65 supports,
    and so does a rate near 0.56. This function does not assume every stored
    pick clears 0.65.
    """
    key, label = SIGNAL_SPECS[2]
    rate = _finite(history_rate)
    if rate is None:
        return _signal(key, label, None, None)
    return _signal(
        key,
        label,
        format_percent(rate),
        rate_verdict(
            rate, support_at=HISTORY_SUPPORTS_AT, against_at=HISTORY_AGAINST_AT
        ),
    )


def projection_signal(
    projected_value: float | None, edge_for_side: float | None
) -> PickSignal:
    """Show the projection. Judge the edge in the side's direction.

    The ±0.5 cut is the same number of points for every metric. It should
    eventually be scaled by that metric's spread.
    """
    key, label = PROJECTION_SIGNAL_SPEC
    projected = _finite(projected_value)
    edge = _finite(edge_for_side)
    if projected is None or edge is None:
        return _signal(key, label, None, None)
    return _signal(
        key,
        label,
        format_projection(projected),
        rate_verdict(
            edge,
            support_at=PROJECTION_SUPPORTS_AT,
            against_at=PROJECTION_AGAINST_AT,
        ),
    )


def defense_signal(rank: float | None, side: str) -> PickSignal:
    """``#rank`` using position rank first. None when neither rank was loaded."""
    key, label = SIGNAL_SPECS[3]
    if rank is None:
        return _signal(key, label, None, None)
    return _signal(key, label, format_rank(rank), defense_verdict(rank, side))


def last10_adjustment(hits: int | None) -> float:
    """Log-odds from ``hits/10``. Missing or non-finite counts contribute 0."""
    count = _finite(hits)
    if count is None:
        return 0.0
    rate = count / LAST10_GAMES
    return _clip(LAST10_LOGIT_WEIGHT * _logit(rate), ADJUSTMENT_CAP)


def history_adjustment(history_rate: float | None) -> float:
    """Log-odds from the all-game side rate. Missing contributes 0."""
    rate = _finite(history_rate)
    if rate is None:
        return 0.0
    return _clip(HISTORY_LOGIT_WEIGHT * _logit(rate), ADJUSTMENT_CAP)


def defense_adjustment(rank: float | None, side: str) -> float:
    """Log-odds from rank. 1 favors the over. Missing contributes 0."""
    rank_value = _finite(rank)
    if rank_value is None or side not in ("over", "under"):
        return 0.0
    favor_over = (DEFENSE_RANK_MIDPOINT - rank_value) / DEFENSE_RANK_SCALE
    favor = favor_over if side == "over" else -favor_over
    return _clip(DEFENSE_WEIGHT * favor, ADJUSTMENT_CAP)


def projection_adjustment(edge_for_side: float | None) -> float:
    """Small fixed log-odds per point of directional edge. Missing is 0."""
    edge = _finite(edge_for_side)
    if edge is None:
        return 0.0
    return _clip(PROJECTION_EDGE_WEIGHT * edge, ADJUSTMENT_CAP)


def adjustment_total(
    *,
    last10_hits: int | None,
    history_rate: float | None,
    defense_rank_value: float | None,
    edge_for_side: float | None,
    side: str,
) -> float:
    """Sum of the four clipped adjustments, itself clipped to ±0.35.

    A missing input adds 0. That is "no information", which is not the
    same thing as a neutral verdict.
    """
    total = (
        last10_adjustment(last10_hits)
        + history_adjustment(history_rate)
        + defense_adjustment(defense_rank_value, side)
        + projection_adjustment(edge_for_side)
    )
    return _clip(total, TOTAL_ADJUSTMENT_CAP)


def calibrated_adjustment(total: float) -> float:
    """Platt map of the clipped adjustment total. The market is not inside this."""
    return PLATT_A + PLATT_B * total


def combined_probability(
    *,
    side: str,
    market_probability: float | None,
    adjustment: float,
    injury_status: str | None = None,
    raw_status: str | None = None,
) -> float | None:
    """Calibrated probability of ``side``.

    ``logit(market)`` is added with coefficient 1. Platt has already been
    applied to ``adjustment``. None when the market is missing, the side
    is not over or under, or the player is Out or Doubtful.
    ``raw_status`` is the source word when ``injury_status`` was normalized
    (Doubtful stored as Questionable).

    The result is rounded to 4 decimals and kept inside ``[0.0001, 0.9999]``
    so a later log loss stays finite.
    """
    if injury_blocks_combined(injury_status, raw_status):
        return None
    if side not in ("over", "under"):
        return None
    market = _finite(market_probability)
    total = _finite(adjustment)
    if market is None or total is None:
        return None
    probability = _sigmoid(_logit(market) + calibrated_adjustment(total))
    probability = min(max(probability, 1e-4), 1.0 - 1e-4)
    return round(probability, 4)


def resolve_market_probability(
    *,
    side: str,
    line: float | None,
    player_name: str,
    bookmakers: Sequence[dict] | None,
    market_probability: float | None,
) -> float | None:
    """Use an explicit probability, otherwise the modal-line no-vig consensus.

    An explicit value is how walk-forward passes the 0.5 prior or a quote.
    Production leaves it None and reads the books already fetched for the pick.
    """
    explicit = _finite(market_probability)
    if explicit is not None:
        return explicit
    threshold = _finite(line)
    if threshold is None or not player_name:
        return None
    pairs = american_pairs_at_line(bookmakers, player_name, threshold)
    return side_probability(no_vig_consensus(pairs), side)


def build_nba_signals(
    *,
    side: str,
    line: float | None,
    player_name: str,
    bookmakers: Sequence[dict] | None = None,
    market_probability: float | None = None,
    last10_values: Sequence[float] | None = None,
    history_rate: float | None = None,
    projected_value: float | None = None,
    opponent_rank: float | None = None,
    opponent_position_rank: float | None = None,
    injury_status: str | None = None,
    raw_status: str | None = None,
) -> tuple[list[PickSignal], float | None, float | None]:
    """Build the four emitted signals, the calibrated probability, and the pre-Platt total.

    The projection slot is not in the list. ``projected_value`` still
    feeds ``projection_adjustment`` when a caller passes one, which is
    what keeps ``combined_probability`` on the same formula. Production
    passes None, and that term is zero. The third value is the clipped
    adjustment total before Platt. Walk-forward stores it so Platt can
    be refit without another pass over the features. It is None when
    the side is not over or under.

    Args:
        side: ``over`` or ``under``.
        line: Modal line. Required for last-10 hits and the projection edge.
        player_name: Used to find this player's prices in ``bookmakers``.
        bookmakers: Odds API bookmakers already fetched for the market.
        market_probability: Side probability to use instead of the books.
            None means "read the books". The offline prior is passed here
            explicitly; this function never substitutes 0.5 on its own.
        last10_values: Exactly 10 non-DNP values, or None when 10 are not available.
        history_rate: Published side rate (``DailyPick.probability``).
        projected_value: Model projection for this metric. None when no model has written one.
        opponent_rank: Overall defense rank. Used only when the position rank is missing.
        opponent_position_rank: Defense rank versus the player's position. Preferred.
        injury_status: Out or Doubtful forces the combined probability to None.
            The four emitted signals are still returned.
        raw_status: Source word from the injury cache. Doubtful is normalized
            to Questionable on ``injury_status`` and still blocks when this
            argument is Doubtful.

    Returns:
        ``(signals, combined_probability, adjustment_total)``. ``signals``
        has the keys in ``SIGNAL_SPECS`` order. ``projection`` is absent.
    """
    threshold = _finite(line)
    market = resolve_market_probability(
        side=side,
        line=threshold,
        player_name=player_name,
        bookmakers=bookmakers,
        market_probability=market_probability,
    )
    hits: int | None = None
    finite_window: list[float] | None = None
    if last10_values is not None:
        finite_window = [
            number
            for value in last10_values
            if (number := _finite(value)) is not None
        ]
    if (
        finite_window is not None
        and len(finite_window) == LAST10_GAMES
        and threshold is not None
    ):
        hits = strict_hits(finite_window, threshold, side)
    edge = directional_edge(projected_value, threshold, side)
    rank = defense_rank(opponent_position_rank, opponent_rank)
    signals = [
        market_signal(market),
        last10_signal(hits),
        history_signal(history_rate),
        defense_signal(rank, side),
    ]
    if side not in ("over", "under"):
        return signals, None, None
    total = adjustment_total(
        last10_hits=hits,
        history_rate=history_rate,
        defense_rank_value=rank,
        edge_for_side=edge,
        side=side,
    )
    combined = combined_probability(
        side=side,
        market_probability=market,
        adjustment=total,
        injury_status=injury_status,
        raw_status=raw_status,
    )
    return signals, combined, total
