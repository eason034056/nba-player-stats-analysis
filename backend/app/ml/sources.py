"""Allow-list of dataset sources and the visibility rule for each one.

A feature query and the label loader are different readers. Feature queries
in this export may use ``games``, ``player_game_stats``, and opening
``game_odds_snapshots``. Stats and games are limited to a game whose date
is strictly before the target game's date. Opening game odds are limited to
rows whose ``snapshot_at`` is at or before T. The label loader may read the
target game's final result from ``prop_actuals``. That result is never a
feature.

``player_prop_snapshots`` is rejected by name. The model does not read the
betting line. Only a later betting decision or evaluation may use that table.
Closing and live game odds are not a feature source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

PRIOR_DATE = "prior_date"
TIMESTAMP = "timestamp"
FEATURE = "feature"
LABEL = "label"


class SourceError(ValueError):
    """A query named a source this dataset does not allow."""


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """One registered reader.

    ``role`` is ``feature`` or ``label``. ``visibility`` is ``prior_date``
    (game date strictly before the target) or ``timestamp`` (observed at or
    before T). ``game_odds_snapshots`` uses the timestamp rule, and only
    when the row is also ``snapshot_kind = 'opening'``.
    """

    name: str
    role: str
    visibility: str


FEATURE_SOURCES: dict[str, SourceSpec] = {
    "games": SourceSpec("games", FEATURE, PRIOR_DATE),
    "player_game_stats": SourceSpec("player_game_stats", FEATURE, PRIOR_DATE),
    "game_odds_snapshots": SourceSpec("game_odds_snapshots", FEATURE, TIMESTAMP),
}

OPENING_KIND = "opening"

LABEL_SOURCES: dict[str, SourceSpec] = {
    "prop_actuals": SourceSpec("prop_actuals", LABEL, "target_result"),
}

# Injury and lineup reads for SPO-138l. They are not part of
# ``feature_source_names``: that tuple is the 138j/138k allow-list, and the
# dataset metadata still reports it unchanged. ``game_lineups`` is a
# post-tip stand-in. The other three are visible only at or before T.
ABSENCE_SOURCES: dict[str, SourceSpec] = {
    "injury_snapshots": SourceSpec("injury_snapshots", FEATURE, TIMESTAMP),
    "game_lineups": SourceSpec("game_lineups", FEATURE, "standin"),
    "projected_lineups": SourceSpec("projected_lineups", FEATURE, TIMESTAMP),
    "projected_lineup_players": SourceSpec(
        "projected_lineup_players", FEATURE, TIMESTAMP
    ),
}

# Named rejection, not a generic "unknown", so a props query cannot be
# mistaken for a source we merely forgot to register.
REJECTED_SOURCES: dict[str, str] = {
    "player_prop_snapshots": (
        "player_prop_snapshots is not a model feature. "
        "The model never reads it. Only a betting decision or evaluation may."
    ),
}


def feature_source_names() -> tuple[str, ...]:
    """Return the feature sources registered by this export, in order."""
    return tuple(FEATURE_SOURCES)


def absence_source_names() -> tuple[str, ...]:
    """Return injury and lineup sources, in registry order.

    These names are not included in :func:`feature_source_names`.
    """
    return tuple(ABSENCE_SOURCES)


def require_absence_source(name: str) -> SourceSpec:
    """Return the injury or lineup rule for ``name``.

    Raises:
        SourceError: ``name`` is ``player_prop_snapshots`` or is not an
            injury or lineup source.
    """
    rejected = REJECTED_SOURCES.get(name)
    if rejected is not None:
        raise SourceError(rejected)
    spec = ABSENCE_SOURCES.get(name)
    if spec is None:
        raise SourceError(f"{name} is not an injury or lineup source")
    return spec


def require_feature_source(name: str) -> SourceSpec:
    """Return the feature rule for ``name``.

    Raises:
        SourceError: ``name`` is ``player_prop_snapshots``, a label source,
            or anything else that is not a registered feature source.
    """
    rejected = REJECTED_SOURCES.get(name)
    if rejected is not None:
        raise SourceError(rejected)
    if name in LABEL_SOURCES:
        raise SourceError(
            f"{name} is a label source, not a feature. "
            "The target game's final result is never a feature."
        )
    spec = FEATURE_SOURCES.get(name)
    if spec is None:
        raise SourceError(
            f"{name} is not on the feature allow-list "
            "(this export registers games, player_game_stats, and game_odds_snapshots)"
        )
    return spec


def require_label_source(name: str) -> SourceSpec:
    """Return the label rule for ``name``.

    A feature table is not accepted here, so a stat query cannot be run
    through the label loader by mistake, and a label cannot be read as a
    feature by calling :func:`require_feature_source` on it.

    Raises:
        SourceError: ``name`` is not a label source.
    """
    rejected = REJECTED_SOURCES.get(name)
    if rejected is not None:
        raise SourceError(rejected)
    if name in FEATURE_SOURCES:
        raise SourceError(
            f"{name} is a feature source, not a label. "
            "Labels are the target game's final result and are not features."
        )
    spec = LABEL_SOURCES.get(name)
    if spec is None:
        raise SourceError(f"{name} is not a label source")
    return spec


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise SourceError("timestamps must be timezone-aware")


def row_is_visible(
    visibility: str,
    *,
    observed_at: datetime | None,
    row_date: date | None,
    target_date: date | None,
    as_of: datetime | None,
) -> bool:
    """Return whether one source row may be used as a feature.

    ``timestamp``: visible when ``observed_at <= as_of``. Exactly T is
    included. One second after T is excluded. A missing timestamp is not
    visible.

    ``prior_date``: the row's game date is strictly before ``target_date``.
    The target game, a later game, and an earlier game on the same date are
    all excluded. This is the rule for ``games`` and ``player_game_stats``,
    and it is stricter than the timestamp rule.

    Raises:
        SourceError: ``visibility`` is not one of those two rules, or a
            timestamp is missing its timezone.
    """
    if visibility == TIMESTAMP:
        if observed_at is None or as_of is None:
            return False
        _require_aware(observed_at)
        _require_aware(as_of)
        return observed_at <= as_of
    if visibility == PRIOR_DATE:
        if row_date is None or target_date is None:
            return False
        return row_date < target_date
    raise SourceError(f"unknown visibility rule {visibility!r}")


def opening_game_odds_visible(
    *,
    snapshot_kind: str,
    snapshot_at: datetime | None,
    as_of: datetime | None,
) -> bool:
    """Return whether one ``game_odds_snapshots`` row may be a feature at T.

    The table must be on the feature allow-list. A row is visible only when
    ``snapshot_kind`` is ``opening`` and ``snapshot_at <= as_of``. Exactly T
    is included. One second after T is not. A NULL ``snapshot_at`` is not
    visible and is not filled in. Live and closing rows are not visible,
    even when their timestamp is before T.

    ``as_of`` is the same T as the rest of the row (tip minus
    ``hours_before_tip``, or 00:00 America/New_York on the game date when
    the tip is NULL). This function does not subtract hours and does not
    build a second cutoff.

    Raises:
        SourceError: a present timestamp has no timezone, or the table is
            no longer a timestamped feature source.
    """
    spec = require_feature_source("game_odds_snapshots")
    if spec.visibility != TIMESTAMP:
        raise SourceError("game_odds_snapshots must use the timestamp rule")
    if snapshot_kind != OPENING_KIND:
        return False
    return row_is_visible(
        spec.visibility,
        observed_at=snapshot_at,
        row_date=None,
        target_date=None,
        as_of=as_of,
    )
