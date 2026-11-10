"""Rewrite game-log season labels from a recorded ESPN schedule.

RealGM's scraper stamps one season string on every row and selects
"All Games", so Summer League, preseason, the regular season, playoffs,
and G League share a file. This module joins each row to a recorded
schedule event on local date plus both team names, then:

- replaces ``Season`` with the label derived from that event
- writes ``GameType`` (``regular_season``, ``playoffs``, ``play_in``,
  ``preseason``, ``summer_league``, ``g_league``, ``nba_cup_championship``,
  ``cup_championship``, ``unclassified``)
- drops Summer League, preseason, and G League
- keeps rows that do not join any event, labeled ``unclassified``, so a
  schedule that does not list a date cannot delete that game
- collapses duplicate rows of the same game (the WNBA file recorded
  Maria Conde's 2026-05-08 game once per season dropdown)

The schedule file is produced by ``scripts/explore_espn_schedule_api.py``.
Raw team-schedule responses recorded with curl are folded in at load
time from ``tests/fixtures/espn/`` and ``tests/fixtures/espn/recorded/``.
Nothing here invents a season boundary from a calendar constant.
A blank ``GameType`` is regular season; that rule lives in
:func:`coalesce_game_type`.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Game-type tokens stored in the CSV and read by the history service.
GAME_TYPE_REGULAR = "regular_season"
GAME_TYPE_PLAYOFFS = "playoffs"
GAME_TYPE_PLAY_IN = "play_in"
GAME_TYPE_PRESEASON = "preseason"
GAME_TYPE_SUMMER = "summer_league"
GAME_TYPE_GLEAGUE = "g_league"
GAME_TYPE_NBA_CUP = "nba_cup_championship"
# WNBA Commissioner's Cup final. Distinct from the NBA Cup token so a
# reader can tell the leagues apart. It is not regular season.
GAME_TYPE_CUP = "cup_championship"
GAME_TYPE_UNCLASSIFIED = "unclassified"
GAME_TYPE_AMBIGUOUS = "ambiguous"

# Kept in the canonical file and loaded into the stats cache.
# The default sample is ``regular_season`` only. Playoffs and the
# play-in are opt-in. The NBA Cup championship is its own token, so it
# stays out of that default sample.
CANONICAL_GAME_TYPES = frozenset(
    {
        GAME_TYPE_REGULAR,
        GAME_TYPE_PLAYOFFS,
        GAME_TYPE_PLAY_IN,
        GAME_TYPE_NBA_CUP,
        GAME_TYPE_CUP,
    }
)

# Written to the file. Unclassified and ambiguous rows are not deleted:
# a miss is not evidence the game was Summer League. ``load_csv`` still
# skips any token outside ``CANONICAL_GAME_TYPES``, so they do not feed
# props. Summer League, preseason, and G League are classified and dropped.
_RETAINED_GAME_TYPES = CANONICAL_GAME_TYPES | {
    GAME_TYPE_UNCLASSIFIED,
    GAME_TYPE_AMBIGUOUS,
}

# ESPN seasonType.abbreviation values, copied from the recorded payloads
# (pre / reg / post / playin). Unknown abbreviations stay unclassified.
_SEASON_TYPE_ABBREV = {
    "pre": GAME_TYPE_PRESEASON,
    "reg": GAME_TYPE_REGULAR,
    "post": GAME_TYPE_PLAYOFFS,
    "playin": GAME_TYPE_PLAY_IN,
}

# Files named ``{league}_team_{id}_schedule_{season}_type_{n}.json``.
_TEAM_SCHEDULE_GLOB = "*_team_*_schedule_*_type_*.json"


def coalesce_game_type(value: Any) -> str:
    """Game type for a cell that may be blank.

    None, a missing cell, ``""``, and whitespace are regular season.
    That is the one rule for a row that never named a type: older CSV
    files have no ``GameType`` column, and a scraped cell can be empty.
    Any other token is returned stripped, including ``playoffs`` and
    ``unclassified``. Call this instead of ``value or "regular_season"``.
    """
    if value is None:
        return GAME_TYPE_REGULAR
    text = str(value).strip()
    if not text:
        return GAME_TYPE_REGULAR
    return text

# RealGM writes "Sixers". ESPN's recorded shortDisplayName for that
# franchise is "76ers" (tests/fixtures/espn/team_directory.json).
_CSV_TEAM_ALIASES = {
    "sixers": "76ers",
}

_EASTERN = ZoneInfo("America/New_York")
_PACIFIC = ZoneInfo("America/Los_Angeles")
_DISPLAY_NAME_SHORT = re.compile(r"^(\d{4})-(\d{2})$")
_STAT_COLUMNS = (
    "MIN",
    "PTS",
    "FGM",
    "FGA",
    "FG%",
    "3PM",
    "3PA",
    "3P%",
    "FTM",
    "FTA",
    "FT%",
    "ORB",
    "DRB",
    "REB",
    "AST",
    "STL",
    "BLK",
    "TOV",
    "PF",
    "FIC",
)


def _repo_root() -> Path:
    """Project root (the directory that contains ``backend/`` and ``data/``)."""
    return Path(__file__).resolve().parents[3]


def default_schedule_path() -> Path:
    """Recorded ESPN events written by the explore script."""
    return _repo_root() / "tests" / "fixtures" / "espn" / "schedule_events.json"


def _norm(value: str | None) -> str:
    """Lowercase team text with punctuation collapsed to single spaces."""
    if not value:
        return ""
    text = value.strip().lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


# Tokens that show up in exhibition names ("Japan National Team") and are
# not themselves a club. Kept out of the lookup so they cannot join a
# random event.
_GENERIC_TEAM_TOKENS = frozenset({"team", "national", "club"})


def csv_team_keys(name: str) -> set[str]:
    """Normalized lookup keys for a team cell in our CSV.

    The full cell is always a key (after the Sixers → 76ers alias).
    Exhibition labels such as ``Japan National Team`` also contribute the
    club token ``japan``, which is the ``shortDisplayName`` on the
    recorded preseason event.
    """
    base = _norm(name)
    if not base:
        return set()
    aliased = _norm(_CSV_TEAM_ALIASES.get(base, base))
    keys = {aliased}
    for token in aliased.split():
        if len(token) >= 4 and token not in _GENERIC_TEAM_TOKENS:
            keys.add(token)
    return keys


def season_label_for_event(event: dict[str, Any]) -> str:
    """Season string for one recorded event.

    WNBA payloads use a single calendar year (``displayName`` ``"2025"``).
    NBA payloads use ``"2025-26"``, which we expand to ``"2025-2026"`` so
    the column stays in the form the scraper already writes.
    """
    season = event.get("season") or {}
    display = str(season.get("displayName") or "").strip()
    league = str(event.get("league") or "")
    if league == "wnba" or display.isdigit():
        if display:
            return display
        year = season.get("year")
        return str(year) if year is not None else ""
    match = _DISPLAY_NAME_SHORT.fullmatch(display)
    if match:
        start, end_two = match.group(1), match.group(2)
        return f"{start}-{start[:2]}{end_two}"
    if re.fullmatch(r"\d{4}-\d{4}", display):
        return display
    year = season.get("year")
    if year is None:
        return display
    return f"{int(year) - 1}-{int(year)}"


def _is_nba_cup_championship(event: dict[str, Any]) -> bool:
    """True when the recorded competition is the NBA Cup final.

    Group play, quarterfinals, and semifinals stay regular season: ESPN
    gives them ``seasonType.abbreviation`` ``reg`` and a Standard
    competition type. The championship uses the same season type, and
    the recorded competition type is ``CC`` / ``commissioners-cup``,
    with notes headline ``NBA Cup Championship``. Both signals are read
    off the payload. Event ids are not a list in this module.
    """
    competition = event.get("competition") or {}
    comp_type = competition.get("type") or {}
    abbreviation = str(comp_type.get("abbreviation") or "").upper()
    slug = str(comp_type.get("slug") or "")
    if abbreviation == "CC" or slug == "commissioners-cup":
        return True
    for note in competition.get("notes") or []:
        headline = str((note or {}).get("headline") or "").strip()
        if headline == "NBA Cup Championship":
            return True
    return False


def game_type_for_event(event: dict[str, Any]) -> str:
    """Map a recorded event to our game-type token.

    Summer League and the G League reuse ESPN's own ``reg`` / ``pre``
    abbreviations for *their* seasons. The league slug on the fixture
    (the endpoint that returned the event) distinguishes them from the
    NBA regular season. The NBA Cup championship also reuses ``reg``;
    :func:`_is_nba_cup_championship` reads the recorded competition.
    """
    league = str(event.get("league") or "")
    if "summer" in league:
        return GAME_TYPE_SUMMER
    if league == "nba-development":
        return GAME_TYPE_GLEAGUE
    if _is_nba_cup_championship(event):
        # Both leagues reuse seasonType "reg" and competition type CC.
        # The NBA final keeps its own token. The WNBA Commissioner's Cup
        # final is cup_championship. Group play is Standard, not CC, so
        # it stays on the season-type map below.
        if league == "wnba":
            return GAME_TYPE_CUP
        if league == "nba":
            return GAME_TYPE_NBA_CUP
    abbrev = str((event.get("seasonType") or {}).get("abbreviation") or "").lower()
    return coalesce_game_type(_SEASON_TYPE_ABBREV.get(abbrev, GAME_TYPE_UNCLASSIFIED))


def _parse_event_instant(value: str) -> datetime | None:
    """Parse an ESPN UTC timestamp (``2025-10-22T02:00Z``)."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _local_dates(instant: datetime) -> set[str]:
    """Calendar dates to try when joining to a RealGM date cell.

    RealGM prints the arena-local date. East-coast and west-coast
    conversions of the same UTC kickoff cover that without treating the
    UTC date itself as a third candidate (that extra day collides with
    the next day's back-to-back).
    """
    return {
        instant.astimezone(_EASTERN).date().isoformat(),
        instant.astimezone(_PACIFIC).date().isoformat(),
    }


def _competitor_names(competitor: dict[str, Any]) -> set[str]:
    """Every normalized name recorded on one competitor."""
    team = competitor.get("team") or {}
    names = {
        _norm(team.get("shortDisplayName")),
        _norm(team.get("displayName")),
        _norm(team.get("name")),
        _norm(team.get("location")),
    }
    names.discard("")
    return names


@dataclass
class ScheduleIndex:
    """Join index: ``(local date, normalized name)`` → events."""

    events_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_date_and_name: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def add(self, event: dict[str, Any]) -> None:
        """Index one recorded event under each local date and team name."""
        event_id = str(event.get("id") or "")
        instant = _parse_event_instant(str(event.get("date") or ""))
        if not event_id or instant is None:
            return
        names_by_side: list[set[str]] = []
        for competitor in event.get("competitors") or []:
            names_by_side.append(_competitor_names(competitor))
        if len(names_by_side) < 2:
            return
        stored = {
            "id": event_id,
            "league": event.get("league"),
            "season_label": season_label_for_event(event),
            "game_type": game_type_for_event(event),
            "sides": names_by_side,
        }
        self.events_by_id[event_id] = stored
        for local_date in _local_dates(instant):
            for side in names_by_side:
                for name in side:
                    key = (local_date, name)
                    bucket = self.by_date_and_name.setdefault(key, [])
                    if event_id not in bucket:
                        bucket.append(event_id)

    def match(self, game_date: str, team: str, opponent: str) -> list[dict[str, Any]]:
        """Events where ``team`` and ``opponent`` are the two sides.

        ``game_date`` is ``YYYY-MM-DD``. A hit has to name both clubs, so
        a G League row whose opponent nickname collides with an NBA club
        still needs its own team to sit on that same event.
        """
        team_keys = csv_team_keys(team)
        opponent_keys = csv_team_keys(opponent)
        if not team_keys or not opponent_keys:
            return []
        candidate_ids: list[str] = []
        seen: set[str] = set()
        for team_key in team_keys:
            for event_id in self.by_date_and_name.get((game_date, team_key), []):
                if event_id not in seen:
                    seen.add(event_id)
                    candidate_ids.append(event_id)
        matched: list[dict[str, Any]] = []
        for event_id in candidate_ids:
            event = self.events_by_id[event_id]
            sides: list[set[str]] = event["sides"]
            team_side = None
            for index, side in enumerate(sides):
                if team_keys & side:
                    team_side = index
                    break
            if team_side is None:
                continue
            other = sides[1 - team_side]
            if opponent_keys & other:
                matched.append(event)
        return matched


_SCHEDULE_CACHE: dict[str, list[dict[str, Any]]] = {}


def _recorded_team_schedule_paths(schedule_path: Path) -> list[Path]:
    """Team-schedule recordings next to the compact index and under ``recorded/``.

    ``Path.glob`` does not walk into directories. The Commissioner's Cup
    final is only in ``tests/fixtures/espn/recorded/``, so a glob of the
    parent directory never sees it.
    """
    parent = schedule_path.parent
    found: dict[Path, Path] = {}
    for root in (parent, parent / "recorded"):
        if not root.is_dir():
            continue
        for path in root.glob(_TEAM_SCHEDULE_GLOB):
            found[path.resolve()] = path
    return [found[key] for key in sorted(found)]


def _league_slug_from_schedule_filename(path: Path) -> str:
    """League prefix of ``{league}_team_{id}_schedule_...json``.

    This is the documented fallback when a caller did not pass ``league``.
    A name with no ``_team_`` marker, or an empty prefix, raises. The
    site-API body does not carry the league slug.
    """
    marker = "_team_"
    if marker not in path.name:
        raise ValueError(
            f"Cannot read a league from {path.name}. "
            "Expected {league}_team_{id}_schedule_{season}_type_{n}.json, "
            "or pass league= explicitly."
        )
    league = path.name.split(marker, 1)[0].strip()
    if not league:
        raise ValueError(
            f"Schedule file {path.name} has no league prefix. Pass league= explicitly."
        )
    return league


def _overlay_recorded_team_schedules(
    schedule_path: Path,
    events: list[dict[str, Any]],
    *,
    league: str | None = None,
) -> list[dict[str, Any]]:
    """Fold curl-recorded team schedules onto the compact index.

    Files named ``{league}_team_{id}_schedule_{season}_type_{n}.json``
    are unmodified site-API responses, in the fixture directory or in
    its ``recorded/`` subdirectory. Compacted events replace the same
    id (so a championship gains its competition notes) and new ids are
    added.

    ``league`` is the ESPN slug the caller already knows. When it is
    missing or blank, each file's slug is taken from its name and a
    warning is logged. The filename is not read when ``league`` is set.
    """
    from app.services.espn_schedule import compact_event

    by_id = {str(event.get("id")): event for event in events}
    explicit = (league or "").strip()
    for raw_path in _recorded_team_schedule_paths(schedule_path):
        if explicit:
            file_league = explicit
        else:
            file_league = _league_slug_from_schedule_filename(raw_path)
            logger.warning(
                "No league was passed for %s; using %r from the filename",
                raw_path.name,
                file_league,
            )
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        for event in payload.get("events") or []:
            if not isinstance(event, dict) or not event.get("id"):
                continue
            compact = compact_event(file_league, event)
            by_id[compact["id"]] = compact
    return list(by_id.values())


def load_schedule_events(
    path: Path | None = None,
    *,
    league: str | None = None,
) -> list[dict[str, Any]]:
    """Load the recorded event list. ``path`` overrides the default fixture.

    ``league`` is forwarded to the recorded-schedule overlay. Omit it
    only when the files encode the slug in their names; that path logs
    a warning. See :func:`_overlay_recorded_team_schedules`.
    """
    schedule_path = (path or default_schedule_path()).resolve()
    cache_key = f"{schedule_path}|{(league or '').strip()}"
    cached = _SCHEDULE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    payload = json.loads(schedule_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Schedule fixture must be a list of events: {schedule_path}")
    merged = _overlay_recorded_team_schedules(schedule_path, payload, league=league)
    _SCHEDULE_CACHE[cache_key] = merged
    return merged


def build_schedule_index(
    events: Iterable[dict[str, Any]],
    *,
    leagues: set[str] | None = None,
) -> ScheduleIndex:
    """Index ``events``, optionally restricted to fixture league slugs."""
    index = ScheduleIndex()
    for event in events:
        league = str(event.get("league") or "")
        if leagues is not None and league not in leagues:
            continue
        index.add(event)
    return index


def leagues_for_csv(league: str) -> set[str]:
    """Fixture league slugs that may appear in one of our CSVs.

    The NBA file is where Summer League and G League rows leaked in.
    The WNBA file only joins WNBA events, so an NBA game on the same
    date cannot relabel a WNBA row.
    """
    key = league.lower()
    if key == "wnba":
        return {"wnba"}
    if key == "nba":
        return {
            "nba",
            "nba-development",
            "nba-summer-las-vegas",
            "nba-summer-california",
            "nba-summer-utah",
            "nba-summer-sacramento",
        }
    raise ValueError(f"Unknown league: {league!r}")


def parse_csv_date(value: str) -> str | None:
    """Normalize a CSV date cell to ``YYYY-MM-DD``."""
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _stat_signature(row: dict[str, str]) -> tuple[str, ...]:
    """Box-score cells used to decide whether two rows are the same game."""
    return tuple((row.get(column) or "").strip() for column in _STAT_COLUMNS)


def _resolve_matches(matches: list[dict[str, Any]]) -> tuple[str, str]:
    """Collapse several matching events into one season and game type.

    Duplicate listings of the same game agree on both fields and resolve.
    An NBA game and a G League game that share nicknames on the same night
    disagree. The parent-league event (``nba`` / ``wnba``) is the one the
    CSV row is about when the other hits are only G League or Summer
    League: those affiliate clubs reuse the parent nickname
    (``Lakers``, ``Suns``) while the scraped NBA rows use that same
    nickname for the NBA club.
    """
    labels = {(event["season_label"], event["game_type"]) for event in matches}
    if len(labels) == 1:
        return labels.pop()
    parent = [event for event in matches if event.get("league") in {"nba", "wnba"}]
    others = [event for event in matches if event.get("league") not in {"nba", "wnba"}]
    parent_labels = {(event["season_label"], event["game_type"]) for event in parent}
    others_are_affiliates = bool(others) and all(
        event.get("league") == "nba-development" or "summer" in str(event.get("league") or "")
        for event in others
    )
    if parent_labels and others_are_affiliates and len(parent_labels) == 1:
        return parent_labels.pop()
    return "", GAME_TYPE_AMBIGUOUS


@dataclass
class HygieneReport:
    """Counts from one hygiene pass. ``rows`` is the canonical output."""

    input_rows: int
    output_rows: int
    rows: list[dict[str, str]]
    fieldnames: list[str]
    classified: dict[str, int] = field(default_factory=dict)
    kept: dict[str, int] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)
    seasons_kept: dict[str, int] = field(default_factory=dict)
    duplicates_removed: int = 0
    ambiguous: int = 0
    unclassified: int = 0


def _output_fieldnames(fieldnames: list[str]) -> list[str]:
    """Insert ``GameType`` immediately after ``Season``."""
    names = [name for name in fieldnames if name != "GameType"]
    if "Season" in names:
        names.insert(names.index("Season") + 1, "GameType")
    else:
        names.append("GameType")
    return names


def _stamp_and_classify(
    rows: list[dict[str, str]],
    index: ScheduleIndex,
) -> tuple[list[dict[str, str]], dict[str, int], int, int]:
    """Attach schedule season / game type. Returns rows plus counters."""
    classified_counts: dict[str, int] = defaultdict(int)
    prepared: list[dict[str, str]] = []
    ambiguous = 0
    unclassified = 0
    for row in rows:
        scraped_season = (row.get("Season") or "").strip()
        game_date = parse_csv_date(row.get("Date", ""))
        if game_date is None:
            game_type = GAME_TYPE_UNCLASSIFIED
            season = scraped_season
            unclassified += 1
        else:
            matches = index.match(game_date, row.get("Team", ""), row.get("Opponent", ""))
            if not matches:
                game_type = GAME_TYPE_UNCLASSIFIED
                season = scraped_season
                unclassified += 1
            else:
                season, game_type = _resolve_matches(matches)
                if game_type == GAME_TYPE_AMBIGUOUS:
                    ambiguous += 1
                    season = scraped_season
        classified_counts[game_type] += 1
        updated = dict(row)
        updated["_scraped_season"] = scraped_season
        updated["_game_date"] = game_date or ""
        updated["Season"] = season
        updated["GameType"] = coalesce_game_type(game_type)
        prepared.append(updated)
    return prepared, classified_counts, ambiguous, unclassified


def _finish_hygiene(
    *,
    rows: list[dict[str, str]],
    prepared: tuple[list[dict[str, str]], dict[str, int], int, int],
) -> HygieneReport:
    """Dedupe ``prepared`` and drop game types that must not feed props."""
    prepared_rows, classified_counts, ambiguous, unclassified = prepared
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    order: list[tuple[str, str, str, str]] = []
    for row in prepared_rows:
        key = (
            (row.get("Player") or "").strip().lower(),
            row["_game_date"],
            _norm(row.get("Team")),
            _norm(row.get("Opponent")),
        )
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)

    kept_rows: list[dict[str, str]] = []
    duplicates_removed = 0
    for key in order:
        group = grouped[key]
        chosen = _choose_duplicate_group(group)
        duplicates_removed += len(group) - len(chosen)
        for row in chosen:
            if row.get("GameType") not in _RETAINED_GAME_TYPES:
                continue
            clean = {
                column: value
                for column, value in row.items()
                if not column.startswith("_")
            }
            kept_rows.append(clean)

    dropped: dict[str, int] = {}
    kept_counts: dict[str, int] = defaultdict(int)
    seasons: dict[str, int] = defaultdict(int)
    for game_type, count in classified_counts.items():
        if game_type not in _RETAINED_GAME_TYPES:
            dropped[game_type] = count
    for row in kept_rows:
        kept_counts[row["GameType"]] += 1
        seasons[row["Season"]] += 1
    input_fieldnames = list(rows[0].keys()) if rows else ["Player", "Season", "Date"]
    if unclassified:
        logger.warning(
            "Game-log hygiene left %s row(s) unclassified; kept as %s",
            unclassified,
            GAME_TYPE_UNCLASSIFIED,
        )
    if ambiguous:
        logger.warning(
            "Game-log hygiene left %s row(s) ambiguous; kept as %s",
            ambiguous,
            GAME_TYPE_AMBIGUOUS,
        )
    return HygieneReport(
        input_rows=len(rows),
        output_rows=len(kept_rows),
        rows=kept_rows,
        fieldnames=_output_fieldnames(input_fieldnames),
        classified=dict(classified_counts),
        kept=dict(kept_counts),
        dropped=dict(dropped),
        seasons_kept=dict(seasons),
        duplicates_removed=duplicates_removed,
        ambiguous=ambiguous,
        unclassified=unclassified,
    )


def _choose_duplicate_group(group: list[dict[str, str]]) -> list[dict[str, str]]:
    """Pick which copies of one player-game survive dedupe.

    Identical box scores collapse to one row. The survivor is the copy
    whose scraped season equals the schedule season when that copy
    exists. Different box scores are all kept so a real doubleheader
    is not thrown away.
    """
    if len(group) == 1:
        return group
    signatures = {_stat_signature(row) for row in group}
    seasoned = [
        row
        for row in group
        if row.get("_scraped_season") == row.get("Season")
        and row.get("GameType") in CANONICAL_GAME_TYPES
    ]
    if len(signatures) == 1:
        if seasoned:
            return [seasoned[0]]
        canonical = [row for row in group if row.get("GameType") in CANONICAL_GAME_TYPES]
        return [canonical[0]] if canonical else [group[0]]
    pool = seasoned or group
    chosen: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for row in pool:
        signature = _stat_signature(row)
        if signature in seen:
            continue
        seen.add(signature)
        chosen.append(row)
    return chosen


def hygiene_rows(
    rows: list[dict[str, str]],
    events: Iterable[dict[str, Any]],
    *,
    league: str,
) -> HygieneReport:
    """Classify ``rows`` against ``events`` and return the canonical file."""
    index = build_schedule_index(events, leagues=leagues_for_csv(league))
    return _finish_hygiene(
        rows=rows,
        prepared=_stamp_and_classify(rows, index),
    )


def looks_like_game_log(header: list[str]) -> bool:
    """True when a CSV header is one of our player game-log files."""
    required = {"Player", "Season", "Date", "Team", "Opponent"}
    return required.issubset(set(header))


def hygiene_csv_text(text: str, *, league: str, events: list[dict[str, Any]] | None = None) -> str:
    """Return cleaned CSV text. Non-game-log files pass through unchanged."""
    if not text.strip():
        return text
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames is None or not looks_like_game_log(list(reader.fieldnames)):
        return text
    source_rows = list(reader)
    schedule = events if events is not None else load_schedule_events()
    report = hygiene_rows(source_rows, schedule, league=league)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=report.fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in report.rows:
        writer.writerow({name: row.get(name, "") for name in report.fieldnames})
    return buffer.getvalue()


def hygiene_csv_file(
    path: Path,
    *,
    league: str,
    events: list[dict[str, Any]] | None = None,
) -> HygieneReport | None:
    """Rewrite ``path`` in place. Returns None when the file is not a game log."""
    raw = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None or not looks_like_game_log(list(reader.fieldnames)):
        logger.info("Skipping hygiene for %s (not a game log)", path)
        return None
    source_rows = list(reader)
    schedule = events if events is not None else load_schedule_events()
    report = hygiene_rows(source_rows, schedule, league=league)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=report.fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in report.rows:
            writer.writerow({name: row.get(name, "") for name in report.fieldnames})
    logger.info(
        "Hygiened %s league=%s in=%s out=%s dropped=%s dupes=%s",
        path,
        league,
        report.input_rows,
        report.output_rows,
        report.dropped,
        report.duplicates_removed,
    )
    return report
