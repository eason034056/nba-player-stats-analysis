"""Allow-list of dataset sources and the visibility rule for each one.

A feature query and the label loader are different readers. Feature queries
in this export may use ``games`` and ``player_game_stats`` only, and only a
game whose date is strictly before the target game's date. The label loader
may read the target game's final result from ``prop_actuals``. That result
is never a feature.

``player_prop_snapshots`` is rejected by name. The model does not read the
betting line. Only a later betting decision or evaluation may use that table.
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
    before T). This export registers no timestamped feature source; the
    timestamp rule is here so a later source can use the same boundary.
    """

    name: str
    role: str
    visibility: str


FEATURE_SOURCES: dict[str, SourceSpec] = {
    "games": SourceSpec("games", FEATURE, PRIOR_DATE),
    "player_game_stats": SourceSpec("player_game_stats", FEATURE, PRIOR_DATE),
}

LABEL_SOURCES: dict[str, SourceSpec] = {
    "prop_actuals": SourceSpec("prop_actuals", LABEL, "target_result"),
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
            "(this export registers games and player_game_stats only)"
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
