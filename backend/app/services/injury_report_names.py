"""Fold an injury-report name and match it to one BDL player.

The report prints ``Last, First``. BALLDONTLIE stores ``first_name`` and
``last_name``. The steps below are fixed so that the same surname is not
enough: Jordan Miller must not become Baba Miller. A step that
finds more than one player stops the search.

Nothing here reads a PDF, calls the network, or writes a row.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

# Whole tokens only. ``viii`` stays. ``vincent`` stays. ``v`` does not.
_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

# Report nickname to the BDL spelling. Keyed by the folded first and last
# name so ``Nic`` does not rename every Nic.
_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    ("nic", "claxton"): ("nicolas", "claxton"),
    ("nate", "williams"): ("jeenathan", "williams"),
    ("sasha", "vezenkov"): ("aleksandar", "vezenkov"),
}

# rapidfuzz token_sort_ratio is 0 to 100. 88 is the floor from the
# matching order. Two players at or above the floor stop the match.
FUZZY_MIN = 88

EXACT_TEAM_SEASON = "exact_team_season"
EXACT_SEASON = "exact_season"
FUZZY_TEAM = "fuzzy_team"
SURNAME_INITIAL = "surname_initial"
EXACT_OTHER_SEASON = "exact_other_season"
UNMATCHED = "unmatched"
UNMATCHED_G_LEAGUE = "unmatched_g_league"


@dataclass(frozen=True)
class NameKey:
    """A folded first name and last name.

    ``first`` and ``last`` are already casefolded, with accents and
    suffixes removed. ``full`` is ``first`` then ``last``, which is the
    string fuzzy matching compares.
    """

    first: str
    last: str

    @property
    def full(self) -> str:
        """``first`` and ``last`` separated by one space."""
        return f"{self.first} {self.last}"


@dataclass(frozen=True)
class CatalogPlayer:
    """One BALLDONTLIE player the matcher is allowed to return.

    ``memberships`` are ``(team_id, season_start_year)`` pairs from
    ``player_game_stats``. ``current_team_id`` and ``draft_year`` come
    from a ``/v1/players`` object. They are not a made-up career.
    """

    bdl_player_id: int
    first_name: str
    last_name: str
    position: str | None
    memberships: frozenset[tuple[int, int]]
    current_team_id: int | None = None
    draft_year: int | None = None

    def name_key(self) -> NameKey | None:
        """The folded BDL name. ``None`` when either part folds away."""
        return player_name_key(self.first_name, self.last_name)


@dataclass(frozen=True)
class PlayerCatalog:
    """The name list for one match pass. Order does not matter."""

    players: tuple[CatalogPlayer, ...]


@dataclass(frozen=True)
class MatchDecision:
    """The id to store, the method name, and whether the review list wants the row.

    ``bdl_player_id`` is ``None`` for both unmatched methods.
    ``on_review_list`` is true only for a non-G-League miss.
    """

    bdl_player_id: int | None
    match_method: str
    on_review_list: bool


def is_g_league(reason: str | None, category: str | None) -> bool:
    """True when the reason or the category contains ``g league``.

    The two strings are joined and casefolded. Nothing else changes.
    A hyphen is not a space, so ``G-League`` is false. ``G League``
    and ``G League - Two-Way`` are true. Two-way and on-assignment
    rows use the spaced phrase.
    """
    text = f"{category or ''} {reason or ''}".casefold()
    return "g league" in text


def report_name_keys(player_raw: str) -> tuple[NameKey, ...]:
    """Fold ``Last, First`` and append the alias spelling when there is one.

    The split is the last comma, so ``Udeh, Jr., Ernest`` keeps Ernest
    as the given name. A string with no comma has no key. The alias, when
    one exists, is a second key and does not replace the printed name.
    """
    if "," not in player_raw:
        return ()
    last_raw, first_raw = player_raw.rsplit(",", 1)
    first = _fold(first_raw)
    last = _fold(last_raw)
    if not first or not last:
        return ()
    base = NameKey(" ".join(first), " ".join(last))
    alias = _ALIASES.get((base.first, base.last))
    if alias is None:
        return (base,)
    return (base, NameKey(alias[0], alias[1]))


def player_name_key(first_name: str, last_name: str) -> NameKey | None:
    """Fold a BDL ``first_name`` and ``last_name``. No alias is applied."""
    first = _fold(first_name)
    last = _fold(last_name)
    if not first or not last:
        return None
    return NameKey(" ".join(first), " ".join(last))


def teams_for_season(player: CatalogPlayer, season: int) -> frozenset[int]:
    """Team ids that player can be on during ``season``.

    Stat rows for that season win. When there is no stat row, the
    payload's current team counts if the season is not before
    ``draft_year``. A null ``draft_year`` does not add that gate.
    """
    from_stats = frozenset(
        team_id for team_id, year in player.memberships if year == season
    )
    if from_stats:
        return from_stats
    if player.current_team_id is None:
        return frozenset()
    if player.draft_year is not None and season < player.draft_year:
        return frozenset()
    return frozenset({player.current_team_id})


def match_report_name(
    player_raw: str,
    *,
    team_id: int | None,
    season: int | None,
    catalog: PlayerCatalog,
    g_league: bool,
) -> MatchDecision:
    """Pick one catalog player, or an unmatched method.

    The steps run in a fixed order. A step with nobody lets the next
    step run. A step with one player is that match, and later steps do
    not run. A step with two or more players is unmatched, and later
    steps do not run either. ``team_id`` or ``season`` of ``None`` skips
    the steps that need that fact.

    Args:
        player_raw: The printed ``Last, First`` string.
        team_id: Resolved BDL team id, or ``None`` when the game did not resolve.
        season: Season start year of the game, or of the game date.
        catalog: Players the id is allowed to point at.
        g_league: True when this row is a G League note. That only changes
            the unmatched method and keeps the row off the review list.

    Returns:
        A ``MatchDecision``. The id is null when nothing matched, and
        when a step found more than one player.
    """
    keys = report_name_keys(player_raw)
    if not keys:
        return _unmatched(g_league)
    exact = {(key.first, key.last) for key in keys}
    if team_id is not None and season is not None:
        decision = _decide_step(
            _exact(
                catalog,
                exact,
                lambda player: team_id in teams_for_season(player, season),
            ),
            EXACT_TEAM_SEASON,
            g_league,
        )
        if decision is not None:
            return decision
    if season is not None:
        decision = _decide_step(
            _exact(
                catalog,
                exact,
                lambda player: bool(teams_for_season(player, season)),
            ),
            EXACT_SEASON,
            g_league,
        )
        if decision is not None:
            return decision
    if team_id is not None and season is not None:
        decision = _decide_step(
            _fuzzy(catalog, keys, team_id, season),
            FUZZY_TEAM,
            g_league,
        )
        if decision is not None:
            return decision
        decision = _decide_step(
            _surname_initial(catalog, keys, team_id, season),
            SURNAME_INITIAL,
            g_league,
        )
        if decision is not None:
            return decision
    if season is not None:
        decision = _decide_step(
            _exact(
                catalog,
                exact,
                lambda player: any(year != season for _team, year in player.memberships),
            ),
            EXACT_OTHER_SEASON,
            g_league,
        )
        if decision is not None:
            return decision
    return _unmatched(g_league)


def catalog_player_from_payload(
    player: Mapping[str, Any],
    *,
    memberships: frozenset[tuple[int, int]] = frozenset(),
) -> CatalogPlayer | None:
    """Read one object from a recorded ``GET /v1/players`` ``data`` array.

    ``id``, ``first_name``, and ``last_name`` are required. ``team.id``,
    ``draft_year``, and ``position`` are kept when they are the types in
    the recorded captures. A bool is not an id. A row that cannot be
    read is ``None``.
    """
    raw_id = player.get("id")
    first = player.get("first_name")
    last = player.get("last_name")
    if type(raw_id) is not int or not isinstance(first, str) or not isinstance(last, str):
        return None
    team = player.get("team")
    team_id: int | None = None
    if isinstance(team, dict) and type(team.get("id")) is int:
        team_id = team["id"]
    draft = player.get("draft_year")
    draft_year = draft if type(draft) is int else None
    position = player.get("position")
    pos = position if isinstance(position, str) else None
    return CatalogPlayer(
        bdl_player_id=raw_id,
        first_name=first,
        last_name=last,
        position=pos,
        memberships=memberships,
        current_team_id=team_id,
        draft_year=draft_year,
    )


def catalog_from_player_pages(
    pages: Iterable[Mapping[str, Any]],
    *,
    memberships: Mapping[int, Iterable[tuple[int, int]]] | None = None,
) -> PlayerCatalog:
    """Build a catalog from ``/v1/players`` page bodies.

    Each page is the response object: ``{"data": [player, ...], "meta": ...}``.
    ``memberships`` maps a player id to stat ``(team_id, season)`` pairs.
    The same id on a later page replaces the earlier object.
    """
    extra = memberships or {}
    found: dict[int, CatalogPlayer] = {}
    for page in pages:
        data = page.get("data")
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            pairs = extra.get(raw_id, ()) if type(raw_id) is int else ()
            parsed = catalog_player_from_payload(item, memberships=frozenset(pairs))
            if parsed is not None:
                found[parsed.bdl_player_id] = parsed
    return PlayerCatalog(tuple(found.values()))


def _fold(text: str) -> list[str]:
    """Accents off, hyphens to spaces, other punctuation gone, suffixes gone."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = without_marks.casefold().replace("-", " ")
    kept = [ch if ch.isalnum() or ch.isspace() else "" for ch in lowered]
    tokens = "".join(kept).split()
    return [token for token in tokens if token not in _SUFFIXES]


def _exact(
    catalog: PlayerCatalog,
    keys: set[tuple[str, str]],
    pred,
) -> list[CatalogPlayer]:
    """Players whose folded name is in ``keys`` and ``pred`` is true."""
    found: list[CatalogPlayer] = []
    seen: set[int] = set()
    for player in catalog.players:
        name = player.name_key()
        if name is None or (name.first, name.last) not in keys:
            continue
        if player.bdl_player_id in seen or not pred(player):
            continue
        seen.add(player.bdl_player_id)
        found.append(player)
    return found


def _fuzzy(
    catalog: PlayerCatalog,
    keys: tuple[NameKey, ...],
    team_id: int,
    season: int,
) -> list[CatalogPlayer]:
    """Same-team players at or above ``FUZZY_MIN``."""
    found: list[CatalogPlayer] = []
    for player in catalog.players:
        if team_id not in teams_for_season(player, season):
            continue
        name = player.name_key()
        if name is None:
            continue
        score = max(fuzz.token_sort_ratio(key.full, name.full) for key in keys)
        if score >= FUZZY_MIN:
            found.append(player)
    return found


def _surname_initial(
    catalog: PlayerCatalog,
    keys: tuple[NameKey, ...],
    team_id: int,
    season: int,
) -> list[CatalogPlayer]:
    """Same-team players with the same surname and the same first letter.

    The first-letter compare is required. The same surname alone must
    not match, or Jordan Miller becomes Baba Miller.
    """
    found: list[CatalogPlayer] = []
    seen: set[int] = set()
    for player in catalog.players:
        if team_id not in teams_for_season(player, season):
            continue
        name = player.name_key()
        if name is None or player.bdl_player_id in seen:
            continue
        if any(_initials_match(key, name) for key in keys):
            seen.add(player.bdl_player_id)
            found.append(player)
    return found


def _decide_step(
    found: list[CatalogPlayer],
    method: str,
    g_league: bool,
) -> MatchDecision | None:
    """Turn one step's candidates into a decision.

    ``found`` is every player this step accepted. An empty list returns
    ``None``, and the caller tries the next step. One player is a hit
    for ``method``. Two or more players is unmatched. The caller returns
    that decision and does not try a later step.

    Args:
        found: Candidates from this step.
        method: The ``match_method`` stored when ``found`` has one player.
        g_league: Passed through when the step is ambiguous.

    Returns:
        ``None`` when this step found nobody. Otherwise a ``MatchDecision``.
    """
    if not found:
        return None
    if len(found) == 1:
        return _hit(found[0], method)
    return _unmatched(g_league)


def _initials_match(left: NameKey, right: NameKey) -> bool:
    """Same surname and the same first character. Surname alone is false."""
    if left.last != right.last:
        return False
    if not left.first or not right.first:
        return False
    return left.first[0] == right.first[0]


def _hit(player: CatalogPlayer, method: str) -> MatchDecision:
    return MatchDecision(player.bdl_player_id, method, False)


def _unmatched(g_league: bool) -> MatchDecision:
    if g_league:
        return MatchDecision(None, UNMATCHED_G_LEAGUE, False)
    return MatchDecision(None, UNMATCHED, True)
