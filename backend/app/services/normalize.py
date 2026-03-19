"""
normalize.py - Player Name Normalization and Matching Module

Handles name discrepancies across different data sources, such as:
- "Cody Williams" vs "Cody Williams Jr."
- "Steph Curry" vs "Stephen Curry"
- "P J Washington" vs "P.J. Washington"
- "Karl Towns" vs "Karl-Anthony Towns"
"""

from difflib import SequenceMatcher
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

_SUFFIX_TOKENS = {"jr", "sr", "ii", "iii", "iv", "v", "vi"}
_FIRST_NAME_GROUPS = (
    {"steph", "stephen"},
    {"mike", "michael"},
    {"pat", "patrick"},
    {"cam", "cameron"},
    {"ant", "anthony", "tony"},
    {"drew", "andrew"},
    {"nick", "nicholas", "nicolas", "nic"},
    {"matt", "matthew"},
    {"josh", "joshua"},
    {"gabe", "gabriel"},
    {"santi", "santiago"},
)
_FIRST_NAME_ALIAS_MAP: Dict[str, Set[str]] = {}
_CANONICAL_FIRST_NAME: Dict[str, str] = {}
for group in _FIRST_NAME_GROUPS:
    canonical = sorted(group, key=lambda item: (-len(item), item))[0]
    for name in group:
        _FIRST_NAME_ALIAS_MAP[name] = set(group)
        _CANONICAL_FIRST_NAME[name] = canonical


def normalize_name(name: str) -> str:
    """
    Normalize player name.

    Rules:
    1. Strip leading/trailing spaces
    2. Convert to lower case
    3. Remove diacritics
    4. Remove periods/apostrophes directly, convert hyphens to spaces
    5. Other non-alphanumeric characters to space
    6. Merge multiple spaces into one
    """
    normalized = unicodedata.normalize("NFKD", name.strip())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"[.'’`]", "", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _tokenize_name(name: str) -> List[str]:
    normalized = normalize_name(name)
    return normalized.split() if normalized else []


def _collapse_initial_tokens(tokens: Sequence[str]) -> List[str]:
    """
    Merge consecutive single-letter tokens.

    For example:
    - ["p", "j", "washington"] -> ["pj", "washington"]
    - ["s", "curry"] -> ["s", "curry"]
    """
    collapsed: List[str] = []
    idx = 0
    while idx < len(tokens):
        if len(tokens[idx]) != 1:
            collapsed.append(tokens[idx])
            idx += 1
            continue

        end = idx
        initials: List[str] = []
        while end < len(tokens) and len(tokens[end]) == 1:
            initials.append(tokens[end])
            end += 1

        collapsed.append("".join(initials))
        idx = end

    return collapsed


def _strip_suffix_tokens(tokens: Sequence[str]) -> List[str]:
    stripped = list(tokens)
    while stripped and stripped[-1] in _SUFFIX_TOKENS:
        stripped.pop()
    return stripped


def _canonicalize_first_name(token: str) -> str:
    return _CANONICAL_FIRST_NAME.get(token, token)


def _canonical_tokens(name: str) -> List[str]:
    tokens = _strip_suffix_tokens(_collapse_initial_tokens(_tokenize_name(name)))
    if not tokens:
        return []
    canonical = list(tokens)
    canonical[0] = _canonicalize_first_name(canonical[0])
    return canonical


def canonical_name(name: str) -> str:
    """
    Generate a stable canonical key for cross data source alignment.

    Removes common suffixes and maps some common first-name nicknames to a canonical form.
    """
    return " ".join(_canonical_tokens(name))


def _expand_first_name_aliases(tokens: Sequence[str]) -> Iterable[List[str]]:
    if not tokens:
        return []

    first = tokens[0]
    aliases = _FIRST_NAME_ALIAS_MAP.get(first, {first})
    return [[alias, *tokens[1:]] for alias in aliases]


def _name_variants(name: str, include_weak: bool = True) -> Set[str]:
    tokens = _collapse_initial_tokens(_tokenize_name(name))
    if not tokens:
        return set()

    variants: Set[str] = set()
    seen_token_variants = set()

    def add_variant_tokens(candidate_tokens: Sequence[str]) -> None:
        cleaned = [token for token in candidate_tokens if token]
        if not cleaned:
            return

        key = tuple(cleaned)
        if key in seen_token_variants:
            return
        seen_token_variants.add(key)

        variants.add(" ".join(cleaned))

        core = _strip_suffix_tokens(cleaned)
        if core:
            variants.add(" ".join(core))
            if len(core) >= 3:
                variants.add("".join(token[0] for token in core))

        if include_weak and len(core) >= 2:
            variants.add(f"{core[0][0]} {' '.join(core[1:])}")

        if len(core) >= 3:
            variants.add(f"{core[0]} {core[-1]}")

    for token_variant in [tokens, _strip_suffix_tokens(tokens)]:
        add_variant_tokens(token_variant)
        for alias_tokens in _expand_first_name_aliases(token_variant):
            add_variant_tokens(alias_tokens)

    canonical = canonical_name(name)
    if canonical:
        variants.add(canonical)

    return {variant.strip() for variant in variants if variant.strip()}


def _name_record(name: str) -> Dict[str, object]:
    core_tokens = _canonical_tokens(name)
    last_name = core_tokens[-1] if core_tokens else ""
    first_name = core_tokens[0] if core_tokens else ""
    strong_variants = _name_variants(name, include_weak=False)
    return {
        "original": name,
        "variants": strong_variants,
        "all_variants": _name_variants(name, include_weak=True),
        "core_tokens": core_tokens,
        "core_name": " ".join(core_tokens),
        "first_name": first_name,
        "last_name": last_name,
        "initial": first_name[:1] if first_name else "",
    }


def _string_similarity(left: str, right: str) -> float:
    try:
        from rapidfuzz import fuzz

        return float(
            max(
                fuzz.WRatio(left, right),
                fuzz.token_sort_ratio(left, right),
                fuzz.ratio(left.replace(" ", ""), right.replace(" ", "")),
            )
        )
    except ImportError:
        return max(
            SequenceMatcher(None, left, right).ratio() * 100,
            SequenceMatcher(None, left.replace(" ", ""), right.replace(" ", "")).ratio() * 100,
        )


def _common_prefix_len(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    count = 0
    for idx in range(limit):
        if left[idx] != right[idx]:
            break
        count += 1
    return count


def _score_records(query_record: Dict[str, object], candidate_record: Dict[str, object]) -> int:
    query_variants = query_record["variants"]
    candidate_variants = candidate_record["variants"]

    if not query_variants or not candidate_variants:
        return 0

    if query_variants & candidate_variants:
        return 100

    score = max(
        _string_similarity(query_variant, candidate_variant)
        for query_variant in query_variants
        for candidate_variant in candidate_variants
    )

    query_last = str(query_record["last_name"])
    candidate_last = str(candidate_record["last_name"])
    query_first = str(query_record["first_name"])
    candidate_first = str(candidate_record["first_name"])
    query_initial = str(query_record["initial"])
    candidate_initial = str(candidate_record["initial"])

    if query_last and candidate_last:
        if query_last == candidate_last:
            score += 6
            if query_first and candidate_first:
                if query_first == candidate_first:
                    score += 4
                elif _common_prefix_len(query_first, candidate_first) >= 3:
                    score += 4
                elif query_initial and query_initial == candidate_initial:
                    score += 2
        elif len(query_record["core_tokens"]) >= 2 and len(candidate_record["core_tokens"]) >= 2:
            score -= 18

    return max(0, min(int(round(score)), 100))


def _rank_candidates(query: str, candidates: List[str]) -> List[Tuple[str, int]]:
    if not candidates:
        return []

    query_record = _name_record(query)
    scored: List[Tuple[str, int]] = []
    for candidate in candidates:
        candidate_record = _name_record(candidate)
        score = _score_records(query_record, candidate_record)
        scored.append((candidate, score))

    scored.sort(key=lambda item: (-item[1], normalize_name(item[0])))
    return scored


def _is_ambiguous_initial_query(query: str, candidates: List[str]) -> bool:
    query_tokens = _canonical_tokens(query)
    if len(query_tokens) < 2 or len(query_tokens[0]) != 1:
        return False

    query_initial = query_tokens[0]
    query_last = query_tokens[-1]
    matches = 0

    for candidate in candidates:
        candidate_tokens = _canonical_tokens(candidate)
        if len(candidate_tokens) < 2:
            continue
        if candidate_tokens[-1] != query_last:
            continue
        if candidate_tokens[0].startswith(query_initial):
            matches += 1
            if matches > 1:
                return True

    return False


def exact_match(query: str, candidates: List[str]) -> Optional[str]:
    """
    Exact match: Uses canonical/alias key for unique matching.

    Only returns a match when the alias key is unique among candidates, avoiding ambiguous input
    such as "S Curry" matching both Stephen and Seth.
    """
    query_keys = _name_variants(query)
    if not query_keys:
        return None

    direct_matches = [candidate for candidate in candidates if normalize_name(candidate) == normalize_name(query)]
    if len(direct_matches) == 1:
        return direct_matches[0]

    alias_index: Dict[str, Set[str]] = {}
    for candidate in candidates:
        for key in _name_record(candidate)["all_variants"]:
            alias_index.setdefault(key, set()).add(candidate)

    unique_matches = set()
    for key in query_keys:
        matched_candidates = alias_index.get(key, set())
        if len(matched_candidates) == 1:
            unique_matches.update(matched_candidates)

    if len(unique_matches) == 1:
        return next(iter(unique_matches))

    return None


def fuzzy_match(
    query: str,
    candidates: List[str],
    threshold: int = 90
) -> Optional[Tuple[str, int]]:
    """
    Fuzzy match: Falls back to similarity matching when there is no exact/canonical match.

    Adds extra weight to last-name consistency, and penalty for different last names,
    to reduce risks like matching "Nikola Jokic" as "Nikola Jovic".
    """
    ranked = _rank_candidates(query, candidates)
    if not ranked:
        return None

    if _is_ambiguous_initial_query(query, candidates):
        return None

    best_name, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else -1

    if best_score < threshold:
        return None

    if second_score >= threshold and best_score < 97 and best_score - second_score < 4:
        return None

    return (best_name, best_score)


def suggest_players(
    query: str,
    candidates: List[str],
    limit: int = 5,
    threshold: int = 60
) -> List[Tuple[str, int]]:
    """
    Returns similar candidates, for UI or user suggestion on no match.
    """
    ranked = _rank_candidates(query, candidates)
    suggestions: List[Tuple[str, int]] = []
    seen = set()
    for candidate, score in ranked:
        if score < threshold or candidate in seen:
            continue
        suggestions.append((candidate, score))
        seen.add(candidate)
        if len(suggestions) >= limit:
            break
    return suggestions


def find_player(query: str, candidates: List[str], threshold: int = 90) -> Optional[str]:
    """
    The main player name matching function.

    Strategy:
    1. exact/canonical unique match
    2. fuzzy fallback
    """
    exact = exact_match(query, candidates)
    if exact:
        return exact

    fuzzy = fuzzy_match(query, candidates, threshold)
    if fuzzy:
        return fuzzy[0]

    return None


def extract_player_names(outcomes: List[dict]) -> List[str]:
    """
    Extracts all player names from the Odds API outcomes data.

    Outcomes is a list of betting options returned by The Odds API.
    Each outcome usually has a "description" or "name" field that contains a player name.

    Args:
        outcomes: List of outcomes returned by the Odds API

    Returns:
        List of unique player names

    Example:
        >>> outcomes = [
        ...     {"name": "Over", "description": "Stephen Curry"},
        ...     {"name": "Under", "description": "Stephen Curry"},
        ...     {"name": "Over", "description": "LeBron James"}
        ... ]
        >>> extract_player_names(outcomes)
        ["Stephen Curry", "LeBron James"]
    """
    players = set()
    
    for outcome in outcomes:
        # Try to get player name from the description field
        if "description" in outcome and outcome["description"]:
            players.add(outcome["description"])
        # Some APIs may use other field names
        elif "player" in outcome and outcome["player"]:
            players.add(outcome["player"])
    
    return list(players)
