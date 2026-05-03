"""
prob.py - Probability Calculation Module

Contains all math functions related to odds conversion and vig (overround) removal.
This is the core calculation logic, used to convert bookmaker odds into fair probabilities.
"""

from typing import Tuple, List, Optional


def american_to_prob(odds: float) -> float:
    """
    Convert American Odds to Implied Probability.
    
    American odds have two forms:
    - Negative (e.g. -110): shows how much you need to bet in order to win $100
    - Positive (e.g. +150): shows how much you can win if you bet $100
    
    Conversion formulas:
    - If odds < 0 (negative, e.g. -110): p = |odds| / (|odds| + 100)
      Example: -110: p = 110 / (110 + 100) = 110 / 210 ≈ 0.5238
      
    - If odds > 0 (positive, e.g. +150): p = 100 / (odds + 100)
      Example: +150: p = 100 / (150 + 100) = 100 / 250 = 0.4
    
    Args:
        odds: American odds (can be positive or negative)
    
    Returns:
        Implied probability (float between 0 and 1)
    
    Raises:
        ValueError: when odds is 0 (invalid odds)
    """
    if odds == 0:
        raise ValueError("Odds cannot be 0")
    
    if odds < 0:
        # Negative: favorite
        # Formula: p = A / (A + 100), where A = |odds|
        return abs(odds) / (abs(odds) + 100)
    else:
        # Positive: underdog
        # Formula: p = 100 / (B + 100), where B = odds
        return 100 / (odds + 100)


def calculate_vig(p_over: float, p_under: float) -> float:
    """
    Calculate the vig (Vigorish / Juice)
    
    Vig is the bookmaker's margin. In theory, Over and Under implied probabilities should add up to 1,
    but bookmakers inflate them so their sum is greater than 1; the excess is the vig.
    
    Formula: vig = (p_over_implied + p_under_implied) - 1
    
    Example:
    - Over: -110 → p = 0.5238
    - Under: -110 → p = 0.5238
    - vig = 0.5238 + 0.5238 - 1 = 0.0476 (about 4.76%)
    
    Args:
        p_over: Implied probability for Over
        p_under: Implied probability for Under
    
    Returns:
        Vig ratio (usually positive, smaller is better)
    """
    return (p_over + p_under) - 1


def devig(p_over: float, p_under: float) -> Tuple[float, float]:
    """
    Remove vig: convert implied probabilities with vig to fair probabilities.
    
    Method: normalize Over and Under probabilities so their sum equals 1.
    
    Formula:
    - p_over_fair = p_over / (p_over + p_under)
    - p_under_fair = p_under / (p_over + p_under)
    
    This removes the overround and provides probabilities closer to reality.
    
    Example:
    - p_over = 0.5238, p_under = 0.5238
    - total = 0.5238 + 0.5238 = 1.0476
    - p_over_fair = 0.5238 / 1.0476 = 0.5 (50%)
    - p_under_fair = 0.5238 / 1.0476 = 0.5 (50%)
    
    Args:
        p_over: Implied probability for Over (with vig)
        p_under: Implied probability for Under (with vig)
    
    Returns:
        Tuple[float, float]: (p_over_fair, p_under_fair) fair probabilities after removing vig
    
    Raises:
        ValueError: if the total probability is 0 (cannot normalize)
    """
    total = p_over + p_under
    
    if total == 0:
        raise ValueError("Total probability cannot be 0")
    
    p_over_fair = p_over / total
    p_under_fair = p_under / total
    
    return (p_over_fair, p_under_fair)


# League-average vig assumption for binary single-leg props.
#
# When a bookmaker only posts the `Yes` side of a binary market (e.g. DD,
# triple-double), there is no `No` price to derive the vig from. We therefore
# assume the book applied roughly the league-average margin for binary props,
# and de-vig under that assumption.
#
# Source: 4.5% is the rough industry consensus for major-book NBA player-prop
# vig (per `docs/decisions/event-page-stat-expansion/decision_20260502_market-key-feasibility.md`
# §4.3 — DraftKings/FanDuel binary-prop overround averages 4-5%). It's a
# *prior*, not a measurement; if a `No` price is later posted, derive the
# actual vig from the leg pair instead via `devig()`.
#
# ⚠ Calling code MUST treat the resulting `over_fair_prob` as best-effort, not
# ground truth. The decision log mandates: "Do NOT publish a fair probability
# if vig cannot be estimated" — so when even this prior cannot be applied
# (e.g. extreme prices), `single_leg_devig` returns None and callers must
# leave the fair-prob field NULL in the API response.
DEFAULT_BINARY_VIG = 0.045


def single_leg_devig(
    p_implied: float,
    assumed_vig: float = DEFAULT_BINARY_VIG,
) -> Optional[float]:
    """
    De-vig a single-leg implied probability using an assumed vig prior.

    For two-leg markets we use `devig(p_over, p_under)` which derives the vig
    from the leg pair. For single-leg binary markets (only `Yes` posted) we
    have to assume a vig; the league-average (`DEFAULT_BINARY_VIG`) is the
    best available prior.

    Approach: assume the book's posted (Yes_implied + hidden_No_implied) sums
    to (1 + assumed_vig). The fair probability for Yes is then:

        p_yes_fair = p_yes_implied / (1 + assumed_vig)

    This is the simplest unbiased de-vigging assumption that matches the
    two-leg formula's behavior in the limit (where Yes_imp ≈ No_imp ≈ 0.5
    and total = 1 + vig).

    Args:
        p_implied: implied probability for the posted leg (0..1)
        assumed_vig: vig assumption (default: league average for binary props)

    Returns:
        Fair probability (0..1), or None if the assumption breaks (e.g.
        negative or > 1 result, which would indicate the input is outside
        the band where the prior is valid). Per the decision log, callers
        must surface None as a NULL `over_fair_prob` rather than fabricating.

    Example:
        >>> single_leg_devig(0.62)   # Yes posted at -163 implies ~0.62
        0.5933  # rounds vary; the actual fair prob ≈ 0.62 / 1.045
    """
    if p_implied < 0 or p_implied > 1:
        return None
    if assumed_vig <= 0:
        return None

    fair = p_implied / (1.0 + assumed_vig)
    if fair <= 0 or fair >= 1:
        # Likely caller passed something pathological; refuse to publish.
        return None
    return fair


def calculate_consensus_mean(fair_probs: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """
    Calculate market consensus (simple average).
    
    Take the simple average of fair probabilities (vig removed) from multiple bookmakers to get consensus.
    This is the MVP-stage approach; simple but effective.
    
    Args:
        fair_probs: List of fair (vig-removed) probabilities from each bookmaker, each element is (p_over_fair, p_under_fair)
    
    Returns:
        Optional[Tuple[float, float]]: (consensus_over, consensus_under), or None if the list is empty.
    
    Example:
        >>> probs = [(0.51, 0.49), (0.52, 0.48), (0.50, 0.50)]
        >>> calculate_consensus_mean(probs)
        (0.51, 0.49)
    """
    if not fair_probs:
        return None
    
    n = len(fair_probs)
    sum_over = sum(p[0] for p in fair_probs)
    sum_under = sum(p[1] for p in fair_probs)
    
    return (sum_over / n, sum_under / n)


def calculate_consensus_weighted(
    fair_probs: List[Tuple[float, float]], 
    vigs: List[float],
    eps: float = 0.001
) -> Optional[Tuple[float, float]]:
    """
    Calculate market consensus (weighted average) - Phase 2 feature.
    
    Bookmakers with a lower vig have odds closer to fair probabilities, so are given higher weight.
    
    Weight formula: w_i = 1 / max(vig_i, eps)
    - Lower vig → higher weight
    - eps prevents division by zero
    
    Weighted average: p = Σ(w_i × p_i) / Σ(w_i)
    
    Args:
        fair_probs: List of fair (vig-removed) probabilities from each bookmaker.
        vigs: Corresponding list of vigs for each bookmaker.
        eps: Minimum vig value (prevents division by zero)
    
    Returns:
        Optional[Tuple[float, float]]: Weighted consensus probabilities, or None on error.
    """
    if not fair_probs or len(fair_probs) != len(vigs):
        return None
    
    # Calculate each bookmaker's weight (lower vig = higher weight)
    weights = [1 / max(vig, eps) for vig in vigs]
    total_weight = sum(weights)
    
    if total_weight == 0:
        return None
    
    # Weighted average
    weighted_over = sum(w * p[0] for w, p in zip(weights, fair_probs))
    weighted_under = sum(w * p[1] for w, p in zip(weights, fair_probs))
    
    return (weighted_over / total_weight, weighted_under / total_weight)


def calculate_mode_threshold(lines: List[float]) -> Optional[float]:
    """
    Calculate the mode (most common value) among all bookmaker lines.
    
    The mode is the value that appears most often, and is used as the consensus threshold for the market.
    
    Calculation rules:
    1. If there is a clear mode (one value appears most), use it.
    2. If there are multiple modes (multiple values appear the same number of times), average them.
    3. If every value appears only once (no mode), use the median value.
    
    Args:
        lines: List of line values from all bookmakers,
               e.g. [24.5, 24.5, 24.5, 25.5, 25.5]
    
    Returns:
        Optional[float]: Consensus threshold, or None if input list is empty.
    
    Example:
        >>> calculate_mode_threshold([24.5, 24.5, 24.5, 25.5])
        24.5  # 24.5 appears 3 times, so it's the mode.
        
        >>> calculate_mode_threshold([24.5, 24.5, 25.5, 25.5])
        25.0  # 24.5 and 25.5 each appear twice, so take their average.
        
        >>> calculate_mode_threshold([24.5, 25.0, 25.5, 26.0])
        25.25  # Each value occurs once, so median is used.
    """
    if not lines:
        return None
    
    # Use Counter to count occurrences of each value
    from collections import Counter
    
    # Round values to 1 decimal to avoid floating point precision errors.
    # For example, 24.5000001 and 24.5 should be considered the same.
    rounded_lines = [round(line, 1) for line in lines]
    counter = Counter(rounded_lines)
    
    # Find the maximum occurrence count
    max_count = max(counter.values())
    
    # Retrieve all values that appear exactly max_count times (the modes)
    modes = [value for value, count in counter.items() if count == max_count]
    
    if max_count == 1:
        # All values appear once, no mode
        # Use the median as representative value
        sorted_lines = sorted(rounded_lines)
        n = len(sorted_lines)
        if n % 2 == 1:
            # Odd count: take the middle value
            return sorted_lines[n // 2]
        else:
            # Even count: average of the two middle values
            return (sorted_lines[n // 2 - 1] + sorted_lines[n // 2]) / 2
    
    if len(modes) == 1:
        # Only one mode
        return modes[0]
    
    # Multiple modes: take the average
    return sum(modes) / len(modes)

