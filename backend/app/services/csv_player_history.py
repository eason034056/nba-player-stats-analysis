"""
csv_player_history.py - CSV Player History Data Service

Reads player historical game data from data/nba_player_game_logs.csv
and computes empirical probabilities.

Functions:
1. Load and cache CSV data
2. Retrieve the list of all player names
3. Calculate the statistical distribution and probabilities of a specified player's historical data

CSV column mapping:
- Player -> player_name
- PTS -> points
- AST -> assists
- REB -> rebounds (ORB + DRB)
- Date -> game_date
- MIN -> minutes
"""

import csv
import os
from typing import List, Optional, Dict, Any, Set, Tuple, Callable
from datetime import datetime, date
from zoneinfo import ZoneInfo
import statistics

from app.services.game_log_hygiene import (
    CANONICAL_GAME_TYPES,
    GAME_TYPE_PLAY_IN,
    GAME_TYPE_PLAYOFFS,
    GAME_TYPE_REGULAR,
    coalesce_game_type,
)
from app.services.normalize import match_player_name


# ===========================================================================
# Metric dispatch table (SPO-16 Phase 1 expansion)
# ===========================================================================
# Maps a metric key (the snake-case identifier accepted by `get_player_stats`)
# to a callable that pulls that metric's per-game value from a game-log dict.
#
# 💡 Why a dispatch table instead of a giant if/elif: each new metric becomes
# a one-line addition, and the metric key ↔ extractor mapping stays in one
# auditable place. The standard Over/Under flow in `_extract_metric_value`
# delegates here; combos are computed on the fly from the canonical CSV
# columns (sums) and threshold-based metrics like `dd` are routed elsewhere.
#
# The keys here are what `daily_analysis.SUPPORTED_MARKETS` (right-hand
# tuple element) emits and what the frontend metric selector posts.
def _coalesce(*values: Optional[float]) -> Optional[float]:
    """Return the first non-None value, or None if all are None."""
    for v in values:
        if v is not None:
            return v
    return None


def _sum_optional(*values: Optional[float]) -> Optional[float]:
    """Sum a list of optional floats, returning None if EVERY value is None.

    Treats present-but-zero as 0 (a player can score 0 points). The "all None"
    case happens when the CSV row is missing all relevant columns — those
    rows must NOT contribute a 0 to the histogram or they'd skew probabilities.
    """
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present)


# Mapping: metric_key -> (game_log_dict -> Optional[float])
# Order is informational; lookup is O(1).
CONTINUOUS_METRIC_EXTRACTORS: Dict[str, Callable[[Dict[str, Any]], Optional[float]]] = {
    # Original 4 — unchanged behavior
    "points": lambda g: g.get("points"),
    "rebounds": lambda g: g.get("rebounds"),
    "assists": lambda g: g.get("assists"),
    "pra": lambda g: g.get("pra"),
    # New singles (SPO-16): CSV loader stores 3PM as `tpm`, FTM as `ftm`,
    # FGM as `fgm`, STL as `stl`. Frontend uses the more readable
    # `threes_made` / `steals` aliases.
    "threes_made": lambda g: g.get("tpm"),
    "steals": lambda g: g.get("stl"),
    "ftm": lambda g: g.get("ftm"),
    "fgm": lambda g: g.get("fgm"),
    # New combos (SPO-16): no double-count concern in the historical layer
    # because we are summing actual game results, not vig-laden odds.
    "ra": lambda g: _sum_optional(g.get("rebounds"), g.get("assists")),
    "pr": lambda g: _sum_optional(g.get("points"), g.get("rebounds")),
    "pa": lambda g: _sum_optional(g.get("points"), g.get("assists")),
}

# Stats that contribute to a "double" for DD computation.
# Uses canonical CSV column keys (snake_case as stored by `load_csv`).
# blocks live under "blk" in the CSV loader.
_DD_COMPONENT_KEYS = ("points", "rebounds", "assists", "stl", "blk")
_DD_THRESHOLD = 10  # ≥10 in a stat = a "double" in that stat
_DD_REQUIRED_COMPONENTS = 2  # ≥2 doubles = double-double

# CSV file path
# Prefer environment variable, otherwise use default path
# In Docker environment, data directory is mounted to /app/data
# In local development, path is relative to project root
#
# 💡 League dispatch — SPO-32 introduced WNBA. The service is parameterized
# on `league`, not duplicated. `_LEAGUE_FILE_NAMES` is the single source of
# truth for "league key → CSV file name"; adding a new league later (e.g.
# NCAA) is a one-line addition here plus a singleton at the bottom of the
# module. ⚠ The env var fallback for NBA (`CSV_DATA_PATH`) is intentionally
# kept under its legacy name to preserve existing test patches and ops
# scripts; WNBA gets its own env var (`WNBA_CSV_DATA_PATH`) so an operator
# can override one league without accidentally pointing the other at the
# wrong file.
_LEAGUE_FILE_NAMES: Dict[str, str] = {
    "nba": "nba_player_game_logs.csv",
    "wnba": "wnba_player_game_logs.csv",
}

_LEAGUE_ENV_VARS: Dict[str, str] = {
    "nba": "CSV_DATA_PATH",  # legacy name — unchanged for backward compat
    "wnba": "WNBA_CSV_DATA_PATH",
}


def _get_csv_path(league: str = "nba") -> str:
    """
    Get CSV file path for the given league.

    Search order (per league):
    1. League-specific environment variable (e.g. CSV_DATA_PATH for NBA,
       WNBA_CSV_DATA_PATH for WNBA)
    2. /app/data/<league>_player_game_logs.csv (Docker environment)
    3. data/<league>_player_game_logs.csv relative to project root

    Args:
        league: League key (e.g. "nba", "wnba"). Defaults to "nba" so
                existing callers that pre-date the league parameter
                continue to resolve to the NBA CSV unchanged.

    Returns:
        str: Absolute file path to CSV

    Raises:
        ValueError: If league is not registered in `_LEAGUE_FILE_NAMES`.
    """
    league = league.lower()
    if league not in _LEAGUE_FILE_NAMES:
        raise ValueError(
            f"Unknown league: {league!r}. "
            f"Registered: {sorted(_LEAGUE_FILE_NAMES.keys())}"
        )

    file_name = _LEAGUE_FILE_NAMES[league]
    env_var_name = _LEAGUE_ENV_VARS[league]

    # 1. Prefer league-specific environment variable
    env_path = os.environ.get(env_var_name)
    if env_path and os.path.exists(env_path):
        return env_path

    # 2. Docker environment path (/app/data/)
    docker_path = f"/app/data/{file_name}"
    if os.path.exists(docker_path):
        return docker_path

    # 3. Local development path (relative to project root)
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "data",
        file_name,
    )
    return local_path


# CSV ``Date`` values are the US game date, not the UTC calendar day of
# tip. Jayson Kent is Remix on 2026-03-15 (vs Lakers) and Trail Blazers on
# 2026-03-16. A US evening tip on the 15th is ``2026-03-16T00:30:00Z``.
# A late Pacific tip such as 7:30pm PT is already the next UTC date, and
# a 10:30pm PT tip (``2026-03-16T05:30:00Z`` in March, PDT) is also the
# next morning in America/New_York. The CSV still uses the 15th.
# America/Los_Angeles is the clock that keeps both of those tips on the
# 15th. An East-coast evening is earlier that same calendar day on the
# Pacific clock, so it does not move. Naive datetimes and date-only
# strings are already the CSV game date and are not shifted.
_US_GAME_DATE_TZ = ZoneInfo("America/Los_Angeles")


def _as_us_game_date(moment: datetime) -> date:
    """Calendar day of a timestamp on the US game-date clock.

    A naive ``datetime`` is already a CSV game date (midnight, no zone).
    An aware timestamp, including Odds API ``commence_time``, is converted
    to America/Los_Angeles before the day is taken. Pacific is the zone
    that still matches the CSV when a west-coast tip is after midnight
    UTC and after midnight in New York.
    """
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(_US_GAME_DATE_TZ).date()


def _coerce_date(value: Any) -> Optional[date]:
    """Parse a calendar day from a log field or an event timestamp.

    Accepts ``datetime`` / ``date``, ``YYYY-MM-DD``, ``M/D/YYYY``, and ISO
    timestamps (``2026-03-16T00:30:00Z``). Aware timestamps use the US game
    date (America/Los_Angeles). Year-less chart labels such as ``"02/09"`` are
    rejected so they cannot be mistaken for a real day.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _as_us_game_date(value)
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if "T" in text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return _as_us_game_date(parsed)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _log_day(log: Dict[str, Any]) -> Optional[date]:
    """Calendar day of one game log, regardless of which date field it uses.

    Raw cache rows store ``game_date`` (a ``datetime``). ``get_player_stats``
    chart rows store ``date_full`` (``YYYY-MM-DD``) plus a year-less ``date``
    label for the x-axis. Only the full day is used.
    """
    for key in ("game_date", "date_full"):
        day = _coerce_date(log.get(key))
        if day is not None:
            return day
    return None


def team_from_game_logs(
    game_logs: Optional[List[Dict[str, Any]]],
    event_day: Any = None,
) -> str:
    """Team the player belonged to on ``event_day``.

    ``get_player_stats`` returns ``game_logs`` oldest-first for charts, so
    ``game_logs[0]["team"]`` is the first club in the file, not the club
    on the slate being priced. This helper ignores list order.

    Rules:
    1. A log whose calendar day equals ``event_day`` supplies the team.
    2. Otherwise the latest log on or before ``event_day`` (the club they
       were on heading into that day, including a future slate and a
       gap day between games).
    3. When ``event_day`` is missing, use the most recent log's team.
    4. When every dated log is after ``event_day``, use the earliest
       known team. That is the first club in the file, which is the one
       they were already on when the log starts.

    Rows with no parseable day (the one-team fixtures in the daily-picks
    tests) fall back to that row's team.
    """
    if not game_logs:
        return ""

    dated: List[Tuple[date, int, str]] = []
    undated: List[str] = []
    for index, log in enumerate(game_logs):
        if not isinstance(log, dict):
            continue
        team = str(log.get("team") or "").strip()
        if not team:
            continue
        day = _log_day(log)
        if day is None:
            undated.append(team)
        else:
            dated.append((day, index, team))

    if not dated:
        return undated[0] if undated else ""

    event = _coerce_date(event_day)
    if event is not None:
        on_day = [item for item in dated if item[0] == event]
        if on_day:
            on_day.sort(key=lambda item: item[1])
            return on_day[-1][2]
        prior = [item for item in dated if item[0] <= event]
        if prior:
            prior.sort()
            return prior[-1][2]
        dated.sort()
        return dated[0][2]

    dated.sort()
    return dated[-1][2]


def _club_code(name: str, league: str = "nba") -> str:
    """League team code for a CSV nickname, a full name, or an abbreviation."""
    from app.services.daily_analysis import canonical_team_code

    return canonical_team_code(name or "", league=league)


def team_on_event(
    game_logs: Optional[List[Dict[str, Any]]],
    event_day: Any = None,
    home_team: str = "",
    away_team: str = "",
    candidate: str = "",
    league: str = "nba",
) -> str:
    """Club to label a player with for one event.

    ``team_from_game_logs`` is the club on the US game date, or the latest
    club on or before that day. The shipped game log stops on 2026-05-11,
    so for a November 2026 tip that club is last season's club. Bulls is
    the right label for Anfernee Simons on 2026-02-21 and the wrong label
    on Celtics at 76ers (2026-11-11): that game's clubs are Boston and
    Philadelphia, and the file has no later row.

    When both event clubs are known:

    1. ``candidate`` (a projection abbreviation or name) is kept when its
       code is home or away. That value is the in-season source.
    2. Otherwise the ``team_from_game_logs`` club is kept when its code is
       home or away.
    3. Otherwise return ``""``. An older stint with one of the two clubs
       is not substituted. Simons' last Celtics game is before the Bulls
       stint; labeling him Boston would put a player on the other side
       of this game onto the opponent.

    When either event club is missing, behavior matches the previous
    callers: ``candidate`` when it is non-empty, otherwise
    ``team_from_game_logs``.
    """
    home = (home_team or "").strip()
    away = (away_team or "").strip()
    proposed = (candidate or "").strip()
    if not home or not away:
        if proposed:
            return proposed
        return team_from_game_logs(game_logs, event_day)

    sides = {
        code
        for code in (_club_code(home, league), _club_code(away, league))
        if code
    }
    if proposed and _club_code(proposed, league) in sides:
        return proposed
    latest = team_from_game_logs(game_logs, event_day)
    if latest and _club_code(latest, league) in sides:
        return latest
    return ""


# ⚠ Legacy module-level constant. Kept ONLY for backward compatibility
# with tests that monkeypatch `app.services.csv_player_history.CSV_PATH`
# (e.g. `test_csv_player_history.py`'s `patch("...CSV_PATH", csv_path)`).
# New code paths MUST read `self._csv_path` on the service instance, which
# resolves per-league at construction time. Do NOT use CSV_PATH for new
# code — it always points at the NBA CSV.
CSV_PATH = _get_csv_path("nba")


def _nba_schedule_index():
    """Recorded NBA schedule, built once. An unreadable fixture is an empty index."""
    global _NBA_SCHEDULE_INDEX
    if _NBA_SCHEDULE_INDEX is not None:
        return _NBA_SCHEDULE_INDEX
    from app.services.game_log_hygiene import (
        ScheduleIndex,
        build_schedule_index,
        leagues_for_csv,
        load_schedule_events,
    )

    try:
        events = load_schedule_events(league="nba")
        _NBA_SCHEDULE_INDEX = build_schedule_index(
            events, leagues=leagues_for_csv("nba")
        )
    except (OSError, ValueError):
        _NBA_SCHEDULE_INDEX = ScheduleIndex()
    return _NBA_SCHEDULE_INDEX


_NBA_SCHEDULE_INDEX = None


class CSVPlayerHistoryService:
    """
    CSV Player History Data Service

    Uses a per-instance cache to avoid reloading the CSV on every request.
    One singleton per league lives at module bottom (`nba_csv_player_service`,
    `wnba_csv_player_service`); the league parameter selects which CSV file
    backs each instance.

    💡 Why parameterize on `league` instead of subclassing: the parsing
    logic is identical (same CSV schema), only the file path differs.
    Subclassing would add an inheritance hierarchy with no behavioral
    difference per class. Parameterization keeps one class to maintain
    and one set of tests to keep in sync.

    Attributes:
        league: League key (e.g. "nba", "wnba") — selects the CSV source
        _csv_path: Absolute CSV file path resolved at construction
        _cache: cached CSV data (keyed by player name)
        _all_players: all player names (sorted)
        _loaded: whether the data has been loaded
    """

    def __init__(self, league: str = "nba"):
        """
        Args:
            league: League key. Defaults to "nba" so legacy callers that
                    instantiated `CSVPlayerHistoryService()` with no args
                    continue to resolve to the NBA CSV unchanged.
        """
        self.league: str = league.lower()
        # Resolve path eagerly at construction so the path stays stable
        # for the lifetime of this instance.
        self._csv_path: str = _get_csv_path(self.league)
        self._cache: Dict[str, List[Dict[str, Any]]] = {}  # player_name -> game_logs
        self._all_players: List[str] = []  # all player names
        self._lineup_cache: Dict[Tuple[str, str], Set[str]] = {}  # (team, date_str) -> {player_names}
        self._loaded: bool = False  # whether data has been loaded

    def reload(self) -> None:
        """
        Force reload CSV data

        Clear all caches and reload the CSV file.
        Used for:
        - Reloading after CSV file updates
        - Refreshing data during development after code changes
        """
        print(f"🔄 Reloading CSV data [{self.league}]...")
        self._cache = {}
        self._all_players = []
        self._lineup_cache = {}
        self._loaded = False
        self.load_csv()
        print(f"✅ Reload complete [{self.league}], total {len(self._all_players)} players")

    def _parse_minutes(self, min_str: str) -> float:
        """
        Parse minutes field (format: MM:SS or numeric)

        Args:
            min_str: minute string, e.g. "32:15" or "32.5"

        Returns:
            float: total minutes

        Example:
            "32:15" -> 32.25 (32 minutes + 15 seconds = 32.25)
            "32" -> 32.0
            "" -> 0.0
        """
        if not min_str or min_str.strip() == "":
            return 0.0

        min_str = min_str.strip()

        # Handle MM:SS format
        if ":" in min_str:
            parts = min_str.split(":")
            try:
                minutes = int(parts[0])
                seconds = int(parts[1]) if len(parts) > 1 else 0
                return minutes + seconds / 60
            except ValueError:
                return 0.0

        # Handle pure numeric format
        try:
            return float(min_str)
        except ValueError:
            return 0.0

    def _parse_float(self, value: str) -> Optional[float]:
        """
        Safely convert string to float

        Args:
            value: the string to convert

        Returns:
            Optional[float]: the converted value, or None if conversion fails
        """
        if not value or value.strip() == "":
            return None
        try:
            return float(value.strip())
        except ValueError:
            return None

    def load_csv(self) -> None:
        """
        Load CSV file into memory

        Only runs the first time it is called. Subsequent calls return immediately if _loaded is True.

        Steps:
        1. Check if file exists
        2. Read the CSV file
        3. Parse each row of data
        4. Group by player name into cache
        5. Build player name list

        Raises:
            FileNotFoundError: if CSV file does not exist
        """
        if self._loaded:
            return

        # 💡 Path resolution: for the NBA service, honor any runtime patch
        # to the module-level `CSV_PATH` constant. This is the surgical fix
        # that keeps `test_csv_player_history.py` working unchanged — those
        # tests do `patch("app.services.csv_player_history.CSV_PATH", ...)`
        # AFTER instantiation, so binding to `self._csv_path` eagerly in
        # __init__ would break them. WNBA (and any future league) uses the
        # per-instance path directly because it has no legacy test surface.
        if self.league == "nba":
            csv_path = CSV_PATH
        else:
            csv_path = self._csv_path

        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file does not exist: {csv_path}")

        # Read CSV
        # Use utf-8-sig encoding to automatically handle BOM (Byte Order Mark)
        # Common when exported from Excel as UTF-8 CSV
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            for row in reader:
                # Parse player name
                player_name = row.get("Player", "").strip()
                if not player_name:
                    continue

                # Parse numeric fields
                pts = self._parse_float(row.get("PTS", ""))
                ast = self._parse_float(row.get("AST", ""))
                orb = self._parse_float(row.get("ORB", ""))
                drb = self._parse_float(row.get("DRB", ""))
                reb = self._parse_float(row.get("REB", ""))

                # If REB column is empty, use ORB + DRB
                if reb is None and orb is not None and drb is not None:
                    reb = orb + drb

                # Parse minutes
                minutes = self._parse_minutes(row.get("MIN", ""))

                # Parse date
                date_str = row.get("Date", "")
                game_date = None
                if date_str:
                    try:
                        # Try format: M/D/YYYY
                        game_date = datetime.strptime(date_str, "%m/%d/%Y")
                    except ValueError:
                        try:
                            # Try alternative format: YYYY-MM-DD
                            game_date = datetime.strptime(date_str, "%Y-%m-%d")
                        except ValueError:
                            pass

                # Parse starting status
                status = row.get("Status", "").strip()
                is_starter = status.lower() == "starter"

                # Parse all 28 CSV columns, plus GameType when the hygiene
                # pass has written it. A blank GameType is a legacy row
                # (unit-test fixtures, older files) and counts as the
                # regular season. Summer League, preseason, and G League
                # are never loaded: they are not the distribution props use.
                season = row.get("Season", "").strip()
                game_type = coalesce_game_type(row.get("GameType"))
                if game_type not in CANONICAL_GAME_TYPES:
                    continue
                wl = row.get("W/L", "").strip()
                pos = row.get("Pos", "").strip()

                fgm = self._parse_float(row.get("FGM", ""))
                fga = self._parse_float(row.get("FGA", ""))
                fg_pct = self._parse_float(row.get("FG%", ""))
                tpm = self._parse_float(row.get("3PM", ""))
                tpa = self._parse_float(row.get("3PA", ""))
                tp_pct = self._parse_float(row.get("3P%", ""))
                ftm = self._parse_float(row.get("FTM", ""))
                fta = self._parse_float(row.get("FTA", ""))
                ft_pct = self._parse_float(row.get("FT%", ""))
                stl = self._parse_float(row.get("STL", ""))
                blk = self._parse_float(row.get("BLK", ""))
                tov = self._parse_float(row.get("TOV", ""))
                pf = self._parse_float(row.get("PF", ""))
                fic = self._parse_float(row.get("FIC", ""))

                game_log = {
                    "player_name": player_name,
                    "game_date": game_date,
                    "season": season,
                    "game_type": game_type,
                    "points": pts,
                    "assists": ast,
                    "rebounds": reb,
                    "minutes": minutes,
                    "pra": (pts or 0) + (reb or 0) + (ast or 0) if pts is not None else None,
                    "team": row.get("Team", "").strip(),
                    "opponent": row.get("Opponent", "").strip(),
                    "status": status,
                    "is_starter": is_starter,
                    "wl": wl,
                    "pos": pos,
                    "fgm": fgm, "fga": fga, "fg_pct": fg_pct,
                    "tpm": tpm, "tpa": tpa, "tp_pct": tp_pct,
                    "ftm": ftm, "fta": fta, "ft_pct": ft_pct,
                    "orb": orb, "drb": drb,
                    "stl": stl, "blk": blk, "tov": tov, "pf": pf,
                    "fic": fic,
                }

                # Group by player
                if player_name not in self._cache:
                    self._cache[player_name] = []
                self._cache[player_name].append(game_log)

                # Build lineup cache: (team, date_str) -> set of players who played
                if minutes > 0 and game_date is not None:
                    team = row.get("Team", "").strip()
                    date_key = game_date.strftime("%Y-%m-%d")
                    lineup_key = (team, date_key)
                    if lineup_key not in self._lineup_cache:
                        self._lineup_cache[lineup_key] = set()
                    self._lineup_cache[lineup_key].add(player_name)

        # Build player name list (sorted)
        self._all_players = sorted(self._cache.keys())

        # Sort game logs by date (most recent first)
        for player in self._cache:
            self._cache[player].sort(
                key=lambda x: x["game_date"] or datetime.min,
                reverse=True  # most recent first
            )

        self._loaded = True
        print(f"✅ CSV loaded [{self.league}], total {len(self._all_players)} players")

    @staticmethod
    def _allowed_game_types(
        include_playoffs: bool = False,
        include_play_in: bool = False,
    ) -> Set[str]:
        """Game types that feed a stats call.

        Regular season is always included. Playoffs and the play-in stay
        in the file so a caller can opt in; they are off by default because
        a prop priced off the regular-season distribution should not mix
        in a seven-game series. ``cup_championship`` and anything
        ``load_csv`` already dropped (summer, preseason, unclassified)
        stay out of this set.
        """
        allowed = {GAME_TYPE_REGULAR}
        if include_playoffs:
            allowed.add(GAME_TYPE_PLAYOFFS)
        if include_play_in:
            allowed.add(GAME_TYPE_PLAY_IN)
        return allowed

    @staticmethod
    def _game_type_of(game: Dict[str, Any]) -> str:
        """Game type on a loaded row. Missing means regular season."""
        return coalesce_game_type(game.get("game_type"))

    def resolve_player_name(self, player_name: str) -> Optional[str]:
        """Map a query to the stored CSV spelling, or None.

        Uses ``match_player_name``: normalized exact equality (case,
        whitespace, diacritics, punctuation, initials, trailing suffixes).
        A name that only contains another name is not a match. Works for
        every league this service is constructed with.
        """
        self.load_csv()
        return match_player_name(player_name, self._all_players)

    def get_all_players(self, search: Optional[str] = None) -> List[str]:
        """
        Retrieve all player names

        Args:
            search: search keyword (optional) to filter player names

        Returns:
            List[str]: player name list (sorted)

        Example:
            get_all_players()  # returns all players
            get_all_players("curry")  # returns players whose name contains "curry"
        """
        self.load_csv()

        if not search:
            return self._all_players

        # Case-insensitive filter
        search_lower = search.lower()
        return [p for p in self._all_players if search_lower in p.lower()]

    def get_player_opponents(
        self,
        player_name: str,
        include_playoffs: bool = False,
        include_play_in: bool = False,
    ) -> List[str]:
        """
        Get all opponents the player has played against

        Args:
            player_name: player name

        Returns:
            List[str]: list of opponent team names (deduplicated and sorted)
        """
        self.load_csv()

        resolved = self.resolve_player_name(player_name)
        player_games = self._cache.get(resolved, []) if resolved else []

        allowed = self._allowed_game_types(include_playoffs, include_play_in)
        opponents = set()
        for game in player_games:
            if self._game_type_of(game) not in allowed:
                continue
            opponent = game.get("opponent", "")
            if opponent:
                opponents.add(opponent)

        return sorted(list(opponents))

    def get_players_in_game(self, team: str, date: datetime) -> Set[str]:
        """
        Get set of players who played for a team on a specific date

        Args:
            team: team name (e.g. "Bucks")
            date: game date

        Returns:
            Set[str]: set of player names who played
        """
        self.load_csv()
        date_key = date.strftime("%Y-%m-%d")
        return self._lineup_cache.get((team, date_key), set())

    def get_teammates(
        self,
        player_name: str,
        include_playoffs: bool = False,
        include_play_in: bool = False,
        only_team: str | None = None,
    ) -> List[str]:
        """
        Get teammates who have played for the same team as the player.

        Traverses the player's game logs and collects teammates from
        ``_lineup_cache``. ``only_team`` limits that walk to one club
        (CSV nickname or abbreviation; matched by league team code).
        ``only_team=""`` matches no club and returns an empty list, which
        is what an event view uses when the log club is not in the game.
        ``only_team=None`` keeps every stint. That is the player-page
        history list.

        Args:
            player_name: player name
            only_team: club to keep, or None for every club in the log

        Returns:
            List[str]: teammate names (deduplicated and sorted, excluding the player)
        """
        self.load_csv()

        resolved = self.resolve_player_name(player_name)
        if resolved:
            player_name = resolved
        player_games = self._cache.get(player_name, []) if resolved else []

        allowed = self._allowed_game_types(include_playoffs, include_play_in)
        wanted = _club_code(only_team, self.league) if only_team is not None else None
        if only_team is not None and not wanted:
            return []
        teammates: Set[str] = set()
        for game in player_games:
            if self._game_type_of(game) not in allowed:
                continue
            team = game.get("team", "")
            game_date = game.get("game_date")
            if not team or game_date is None:
                continue
            if wanted is not None and _club_code(team, self.league) != wanted:
                continue
            date_key = game_date.strftime("%Y-%m-%d")
            lineup = self._lineup_cache.get((team, date_key), set())
            teammates.update(lineup)

        teammates.discard(player_name)
        return sorted(teammates)

    def latest_position(self, player_name: str) -> Optional[str]:
        """``Pos`` on the most recent loaded game, or None.

        The game log is already newest-first. A blank ``Pos`` is skipped
        so one missing cell does not hide the last real position. This
        is the roster field already on the CSV. It does not call a
        lineup or projection API.
        """
        self.load_csv()
        resolved = self.resolve_player_name(player_name)
        if not resolved:
            return None
        for game in self._cache.get(resolved, []):
            position = str(game.get("pos") or "").strip()
            if position:
                return position
        return None

    def latest_team(self, player_name: str) -> Optional[str]:
        """Team name on the most recent loaded game, or None.

        The game log is newest-first, the same order ``latest_position``
        walks. A blank team is skipped. This is the CSV ``Team`` cell.
        It does not call a lineup or odds API.
        """
        self.load_csv()
        resolved = self.resolve_player_name(player_name)
        if not resolved:
            return None
        for game in self._cache.get(resolved, []):
            team = str(game.get("team") or "").strip()
            if team:
                return team
        return None

    def _history_season_label(self, season: Optional[str]) -> Optional[str]:
        """Season label for the season-scoped rate. NBA only.

        A blank query uses the recorded current NBA season. WNBA returns
        None so the shared response leaves the season fields null.
        """
        if self.league != "nba":
            return None
        from app.services.nba_season import (
            normalize_nba_season_label,
            recorded_nba_season_label,
        )

        if season and season.strip():
            return normalize_nba_season_label(season)
        return recorded_nba_season_label()

    @staticmethod
    def _season_matches(row_season: str, label: str) -> bool:
        from app.services.nba_season import normalize_nba_season_label

        text = (row_season or "").strip()
        if not label:
            return False
        return text == label or normalize_nba_season_label(text) == label

    def _venue_for(self, day: str, team: str, opponent: str) -> Optional[str]:
        """``home`` or ``away`` from the recorded NBA schedule. NBA only."""
        if self.league != "nba" or not day or not team or not opponent:
            return None
        return _nba_schedule_index().venue(day, team, opponent)

    def _event_id_for(self, day: str, team: str, opponent: str) -> Optional[str]:
        if self.league != "nba" or not day or not team or not opponent:
            return None
        return _nba_schedule_index().event_id_for(day, team, opponent)

    def _teammate_context(
        self,
        teammates: List[str],
        games: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Games each listed teammate missed inside ``games``.

        ``games`` is the sample behind ``n_games`` (after ``n`` and the
        other filters). A teammate is out of a game when they are not in
        the lineup cache for that team and date. ``with_mean`` /
        ``without_mean`` are the player's stat on those two splits.
        WNBA returns an empty list and keeps ``teammates`` as names.
        """
        if self.league != "nba":
            return []
        context: List[Dict[str, Any]] = []
        ordered = list(reversed(games))
        for name in teammates:
            missed: List[Dict[str, Any]] = []
            with_values: List[float] = []
            without_values: List[float] = []
            for game in ordered:
                team = game.get("team") or ""
                day = game.get("date_full") or ""
                lineup = (
                    self._lineup_cache.get((team, day), set())
                    if team and day
                    else set()
                )
                value = game.get("value")
                if name in lineup:
                    if value is not None:
                        with_values.append(float(value))
                    continue
                if value is not None:
                    without_values.append(float(value))
                missed.append(
                    {
                        "date": day,
                        "game_id": self._event_id_for(
                            day, team, game.get("opponent") or ""
                        ),
                    }
                )
            context.append(
                {
                    "name": name,
                    "games_missed": len(missed),
                    "missed_games": missed,
                    "with_n": len(with_values),
                    "without_n": len(without_values),
                    "with_mean": round(statistics.mean(with_values), 2) if with_values else None,
                    "without_mean": (
                        round(statistics.mean(without_values), 2) if without_values else None
                    ),
                }
            )
        return context

    def _season_fields(
        self,
        season_label: Optional[str],
        season_games: List[Dict[str, Any]],
        threshold: float,
    ) -> Dict[str, Any]:
        """Season hit rate beside the all-games rate. Empty for WNBA."""
        if self.league != "nba":
            return {}
        values = [float(game["value"]) for game in season_games if game.get("value") is not None]
        if not values:
            return {
                "season": season_label,
                "season_n_games": 0,
                "season_p_over": None,
                "season_p_under": None,
                "season_mean": None,
            }
        count = len(values)
        over_count = sum(1 for value in values if value > threshold)
        under_count = sum(1 for value in values if value < threshold)
        return {
            "season": season_label,
            "season_n_games": count,
            "season_p_over": round(over_count / count, 4),
            "season_p_under": round(under_count / count, 4),
            "season_mean": round(statistics.mean(values), 2),
        }

    def get_player_stats(
        self,
        player_name: str,
        metric: str,
        threshold: float,
        n: int = 0,
        bins: int = 15,
        exclude_dnp: bool = True,
        opponent: Optional[str] = None,
        is_starter: Optional[bool] = None,
        teammate_filter: Optional[List[str]] = None,
        teammate_played: Optional[bool] = None,
        include_playoffs: bool = False,
        include_play_in: bool = False,
        season: Optional[str] = None,
        home_team: Optional[str] = None,
        away_team: Optional[str] = None,
        as_of: Any = None,
    ) -> Dict[str, Any]:
        """
        Calculate player historical statistics

        This is the core functionality! Calculates historical probability distribution for a given player and metric.

        Args:
            player_name: player name
            metric: statistical metric (points/assists/rebounds/pra)
            threshold: threshold value (e.g. 24.5)
            n: last N games (0 means all)
            bins: histogram bins (default 15)
            exclude_dnp: exclude DNP (Did Not Play, games with 0 minutes)
            opponent: filter by opponent (optional, None for all)
            is_starter: filter by starting status (True=starters only, False=bench only, None=all)
            teammate_filter: star teammate name list (optional, e.g. ["Giannis Antetokounmpo"])
            teammate_played: True=only games where all teammates played, False=all did not play, None=no filter

        Returns:
            Dict containing:
            - player: player name
            - metric: metric name
            - threshold: threshold value
            - n_games: sample size
            - p_over: Over probability (value > threshold)
            - p_under: Under probability (value < threshold)
            - mean: mean value
            - std: standard deviation
            - histogram: histogram data (deprecated, kept for compatibility)
            - game_logs: per-game detailed data
            - opponents: list of opponents
            - teammates: list of teammates (for frontend multi-select)

        Example:
            get_player_stats("Stephen Curry", "points", 24.5, n=20)

            get_player_stats("A.J. Green", "points", 10.5,
                             teammate_filter=["Giannis Antetokounmpo"], teammate_played=False)
            # Returns stats of A.J. Green for games when Giannis did not play
        """
        self.load_csv()

        # Resolve to the stored spelling. Normalized exact key only —
        # "Smith" must not attach to "Aaron Nesmith" or "Jalen Smith".
        resolved = self.resolve_player_name(player_name)
        if resolved:
            player_name = resolved
        player_games = self._cache.get(player_name, []) if resolved else []

        season_label = self._history_season_label(season)

        if not player_games:
            missing = {
                "player": player_name,
                "metric": metric,
                "threshold": threshold,
                "n_games": 0,
                "p_over": None,
                "p_under": None,
                "mean": None,
                "std": None,
                "histogram": [],
                "game_logs": [],
                "opponents": [],
                "teammates": [],
                "message": f"Player '{player_name}' not found"
            }
            missing.update(self._season_fields(season_label, [], threshold))
            if self.league == "nba":
                missing["teammate_context"] = []
            return missing

        # Get all opponents (for filters)
        all_opponents = self.get_player_opponents(
            player_name,
            include_playoffs=include_playoffs,
            include_play_in=include_play_in,
        )
        # Event views pass both clubs. The selector then lists teammates
        # from the club that is actually in the game. A log club that is
        # neither home nor away contributes nobody: the Bulls names from
        # a finished stint are not this game's teammates. Omitting either
        # club keeps the full list (player page, undated tools).
        event_scoped = bool((home_team or "").strip() and (away_team or "").strip())
        event_team = (
            team_on_event(
                player_games,
                as_of,
                home_team or "",
                away_team or "",
                league=self.league,
            )
            if event_scoped
            else None
        )
        all_teammates = self.get_teammates(
            player_name,
            include_playoffs=include_playoffs,
            include_play_in=include_play_in,
            only_team=event_team if event_scoped else None,
        )
        allowed_game_types = self._allowed_game_types(include_playoffs, include_play_in)

        # Validate teammate_filter: only accept teammates from the same team, remove non-teammates
        validated_teammate_filter = None
        if teammate_filter:
            teammate_set = set(all_teammates)
            validated_teammate_filter = [t for t in teammate_filter if t in teammate_set]
            if not validated_teammate_filter and teammate_filter:
                validated_teammate_filter = None

        # Collect valid game logs
        valid_games: List[Dict[str, Any]] = []
        values: List[float] = []

        for game in player_games:
            # Regular season only, unless the caller opted into playoffs
            # or the play-in. Summer League and preseason never reach this
            # loop: load_csv drops them.
            if self._game_type_of(game) not in allowed_game_types:
                continue

            # Exclude DNP
            if exclude_dnp and game.get("minutes", 0) == 0:
                continue

            # Opponent filter
            if opponent and game.get("opponent", "") != opponent:
                continue

            # Starter status filter
            # is_starter=True: only starter games
            # is_starter=False: only bench games
            # is_starter=None: all games
            if is_starter is not None:
                if game.get("is_starter", False) != is_starter:
                    continue

            # Star teammate filter (same-team only)
            # teammate_played=True: all selected teammates played
            # teammate_played=False: all selected teammates did not play
            if validated_teammate_filter and teammate_played is not None:
                game_team = game.get("team", "")
                game_date = game.get("game_date")
                if game_team and game_date:
                    date_key = game_date.strftime("%Y-%m-%d")
                    lineup = self._lineup_cache.get((game_team, date_key), set())
                    if teammate_played:
                        if not all(t in lineup for t in validated_teammate_filter):
                            continue
                    else:
                        if any(t in lineup for t in validated_teammate_filter):
                            continue

            # Get value for the specified metric.
            # 💡 Dispatch via CONTINUOUS_METRIC_EXTRACTORS so new metrics added
            # to the dispatch table (e.g. SPO-16's threes_made/ra/pr/pa) Just
            # Work without touching this loop. Falls back to direct `game[key]`
            # lookup for any legacy callers passing a raw column name.
            extractor = CONTINUOUS_METRIC_EXTRACTORS.get(metric)
            if extractor is not None:
                value = extractor(game)
            else:
                value = game.get(metric)
            if value is not None:
                values.append(value)

                # Build game log data
                game_date = game.get("game_date")
                minutes = game.get("minutes", 0)
                game_is_starter = game.get("is_starter", False)

                day_full = game_date.strftime("%Y-%m-%d") if game_date else ""
                team_name = game.get("team", "")
                opponent_name = game.get("opponent", "")
                log_row = {
                    "date": game_date.strftime("%m/%d") if game_date else "",
                    "date_full": day_full,
                    "opponent": opponent_name,
                    "value": value,
                    "is_over": value > threshold,
                    "team": team_name,
                    "minutes": round(minutes, 1),  # minutes played
                    "is_starter": game_is_starter,  # whether started
                    "game_type": self._game_type_of(game),
                    "season": game.get("season", ""),
                }
                if self.league == "nba":
                    log_row["home_or_away"] = self._venue_for(
                        day_full, team_name, opponent_name
                    )
                valid_games.append(log_row)

        season_games = valid_games
        if season_label:
            season_games = [
                game
                for game in valid_games
                if self._season_matches(str(game.get("season") or ""), season_label)
            ]

        # Take the most recent N games
        if n > 0 and len(valid_games) > n:
            valid_games = valid_games[:n]
            values = values[:n]

        if not values:
            empty = {
                "player": player_name,
                "metric": metric,
                "threshold": threshold,
                "n_games": 0,
                "p_over": None,
                "p_under": None,
                "mean": None,
                "std": None,
                "histogram": [],
                "game_logs": [],
                "opponents": all_opponents,
                "teammates": all_teammates,
                "message": f"Player '{player_name}' has no valid {metric} stats"
            }
            empty.update(self._season_fields(season_label, season_games, threshold))
            if self.league == "nba":
                empty["teammate_context"] = self._teammate_context(all_teammates, [])
            return empty

        # Calculate Over/Under probabilities
        # Over: value > threshold
        # Under: value < threshold
        over_count = sum(1 for v in values if v > threshold)
        under_count = sum(1 for v in values if v < threshold)
        equal_count = sum(1 for v in values if v == threshold)

        n_games = len(values)
        p_over = over_count / n_games if n_games > 0 else None
        p_under = under_count / n_games if n_games > 0 else None

        # Compute mean and standard deviation
        mean_val = statistics.mean(values)
        std_val = statistics.stdev(values) if len(values) > 1 else 0.0

        # Calculate histogram (for compatibility)
        histogram = self._calculate_histogram(values, bins)

        # Reverse game_logs order so the oldest is first (for time series charts)
        game_logs_for_chart = list(reversed(valid_games))

        result = {
            "player": player_name,
            "metric": metric,
            "threshold": threshold,
            "n_games": n_games,
            "p_over": round(p_over, 4) if p_over is not None else None,
            "p_under": round(p_under, 4) if p_under is not None else None,
            "equal_count": equal_count,
            "mean": round(mean_val, 2),
            "std": round(std_val, 2),
            "histogram": histogram,
            "game_logs": game_logs_for_chart,
            "opponents": all_opponents,
            "teammates": all_teammates,
            "opponent_filter": opponent,
            "teammate_filter": validated_teammate_filter,
            "teammate_played": teammate_played,
            "message": None
        }
        result.update(self._season_fields(season_label, season_games, threshold))
        if self.league == "nba":
            result["teammate_context"] = self._teammate_context(all_teammates, valid_games)
        return result

    def player_dd_history(
        self,
        player_name: str,
        season: Optional[str] = None,
        threshold: Any = None,
        include_playoffs: bool = False,
        include_play_in: bool = False,
    ) -> Dict[str, Any]:
        """
        Historical Double-Double rate for a player.

        DD definition: a game in which the player records ≥10 in at least
        2 of {PTS, REB, AST, STL, BLK}. This is the standard NBA convention.
        Fields are pulled from the CSV's canonical columns; the loader
        normalizes them to snake_case (`points`, `rebounds`, `assists`,
        `stl`, `blk`).

        ⚠ DD is binary (0/1). A `threshold` argument makes no sense here —
        if a caller passes a non-None threshold this method REJECTS the call
        with a ValueError. This is the "reject any non-null threshold" rule
        from §2.4 of the SPO-16 ticket; silently dropping the threshold
        would mask a likely caller bug (e.g. wiring DD through the
        Over/Under flow by mistake).

        Args:
            player_name: player name. Stored spelling wins; otherwise a
                normalized exact key (case, whitespace, diacritics,
                punctuation, trailing Jr/Sr/II/III). Not a substring match.
            season: optional CSV "Season" filter (e.g. "2024-25"); None
                    means use all seasons available in the CSV
            threshold: must be None — provided so the call signature matches
                       the over/under flow's keyword name; non-None raises

        Returns:
            dict with:
              - player: stored CSV spelling after normalized exact match
              - season: the season filter actually applied (None = all)
              - games: count of games considered (post DNP exclusion)
              - dd_games: count of those games that were DDs
              - prob_dd: dd_games / games (None if games == 0)
              - n_games: alias for `games`, matches the schema other
                callers use (DailyPicksResponse etc.)
              - message: error/explanatory string, None on success

        Example:
            >>> svc.player_dd_history("Nikola Jokic", season="2024-25")
            {"player": "Nikola Jokic", "season": "2024-25",
             "games": 65, "dd_games": 50, "prob_dd": 0.769, "n_games": 65,
             "message": None}
        """
        # ⚠ Hard-reject misuse: DD is 0/1, threshold is meaningless.
        if threshold is not None:
            raise ValueError(
                "player_dd_history(): DD is a binary outcome (0/1); "
                "threshold must be None. If you wanted Over/Under semantics, "
                "you reached for the wrong method — DD has no `point` field."
            )

        self.load_csv()

        # Same normalized exact match as get_player_stats.
        resolved = self.resolve_player_name(player_name)
        if resolved:
            player_name = resolved
        player_games = self._cache.get(player_name, []) if resolved else []

        if not player_games:
            return {
                "player": player_name,
                "season": season,
                "games": 0,
                "dd_games": 0,
                "prob_dd": None,
                "n_games": 0,
                "message": f"Player '{player_name}' not found",
            }

        games_count = 0
        dd_count = 0

        allowed_game_types = self._allowed_game_types(include_playoffs, include_play_in)
        for game in player_games:
            # Exclude DNPs — a player who didn't play can't have a DD,
            # but counting those games would dilute the rate.
            if self._game_type_of(game) not in allowed_game_types:
                continue
            if game.get("minutes", 0) == 0:
                continue
            if season and game.get("season") != season:
                continue

            games_count += 1

            # Count how many of {PTS, REB, AST, STL, BLK} are ≥ 10 this game.
            # _coalesce(... or 0) so a CSV row missing one stat doesn't blow up
            # the comparison; a missing stat in this column simply doesn't
            # qualify as a "double" — equivalent to it being 0, which is the
            # right default for stat-tracking edge cases.
            doubles = sum(
                1
                for key in _DD_COMPONENT_KEYS
                if (game.get(key) or 0) >= _DD_THRESHOLD
            )
            if doubles >= _DD_REQUIRED_COMPONENTS:
                dd_count += 1

        prob_dd = round(dd_count / games_count, 4) if games_count > 0 else None

        return {
            "player": player_name,
            "season": season,
            "games": games_count,
            "dd_games": dd_count,
            "prob_dd": prob_dd,
            # Alias kept so downstream serializers (DailyPick / response
            # schemas that have `n_games`) can pick this up uniformly.
            "n_games": games_count,
            "message": None if games_count > 0 else (
                f"No qualifying games for {player_name}"
                + (f" in season {season}" if season else "")
            ),
        }

    def _calculate_histogram(
        self,
        values: List[float],
        bins: int
    ) -> List[Dict[str, Any]]:
        """
        Calculate histogram

        Divide values into `bins` intervals and count the number in each interval

        Args:
            values: list of float values
            bins: number of bins

        Returns:
            List[Dict], each element contains:
            - binStart: interval start value
            - binEnd: interval end value
            - count: count of values in this interval

        Binning strategy:
        - Calculate min and max
        - bin_width = (max - min) / bins
        - Last bin includes the max value
        """
        if not values or bins < 1:
            return []

        min_val = min(values)
        max_val = max(values)

        # Avoid division by zero if max == min
        if max_val == min_val:
            return [{
                "binStart": min_val,
                "binEnd": max_val,
                "count": len(values)
            }]

        bin_width = (max_val - min_val) / bins
        histogram = []

        for i in range(bins):
            bin_start = min_val + i * bin_width
            bin_end = min_val + (i + 1) * bin_width

            # Count number of values in this interval
            # Last bin includes values equal to max
            if i == bins - 1:
                count = sum(1 for v in values if bin_start <= v <= bin_end)
            else:
                count = sum(1 for v in values if bin_start <= v < bin_end)

            histogram.append({
                "binStart": round(bin_start, 2),
                "binEnd": round(bin_end, 2),
                "count": count
            })

        return histogram


# Create singleton instances — one per league.
# These are created when the module is imported; always use the same
# instances afterward. The legacy `csv_player_service` name is preserved
# as an alias to the NBA service so every existing call site
# (`from app.services.csv_player_history import csv_player_service`) keeps
# working without modification.
nba_csv_player_service = CSVPlayerHistoryService(league="nba")
wnba_csv_player_service = CSVPlayerHistoryService(league="wnba")

# Backward-compatible alias — DO NOT remove without updating every NBA
# call site. New code should reference `nba_csv_player_service` directly.
csv_player_service = nba_csv_player_service

