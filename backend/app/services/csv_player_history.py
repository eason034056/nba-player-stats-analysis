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
from typing import List, Optional, Dict, Any, Set, Tuple
from datetime import datetime
import statistics

# CSV file path
# Prefer environment variable, otherwise use default path
# In Docker environment, data directory is mounted to /app/data
# In local development, path is relative to project root
def _get_csv_path() -> str:
    """
    Get CSV file path

    Search order:
    1. Environment variable CSV_DATA_PATH
    2. /app/data/nba_player_game_logs.csv (Docker environment)
    3. data/nba_player_game_logs.csv relative to project root

    Returns:
        str: Absolute file path to CSV
    """
    # 1. Prefer environment variable
    env_path = os.environ.get("CSV_DATA_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # 2. Docker environment path (/app/data/)
    docker_path = "/app/data/nba_player_game_logs.csv"
    if os.path.exists(docker_path):
        return docker_path

    # 3. Local development path (relative to project root)
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "data",
        "nba_player_game_logs.csv"
    )
    return local_path


CSV_PATH = _get_csv_path()


class CSVPlayerHistoryService:
    """
    CSV Player History Data Service

    Uses a module-level cache to avoid reloading the CSV on every request
    This is a singleton pattern implementation

    Attributes:
        _cache: cached CSV data (keyed by player name)
        _all_players: all player names (sorted)
        _loaded: whether the data has been loaded
    """

    def __init__(self):
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
        print("🔄 Reloading CSV data...")
        self._cache = {}
        self._all_players = []
        self._lineup_cache = {}
        self._loaded = False
        self.load_csv()
        print(f"✅ Reload complete, total {len(self._all_players)} players")

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

        if not os.path.exists(CSV_PATH):
            raise FileNotFoundError(f"CSV file does not exist: {CSV_PATH}")

        # Read CSV
        # Use utf-8-sig encoding to automatically handle BOM (Byte Order Mark)
        # Common when exported from Excel as UTF-8 CSV
        with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
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

                # Parse all 28 CSV columns
                season = row.get("Season", "").strip()
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
        print(f"✅ CSV loaded, total {len(self._all_players)} players")

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

    def get_player_opponents(self, player_name: str) -> List[str]:
        """
        Get all opponents the player has played against

        Args:
            player_name: player name

        Returns:
            List[str]: list of opponent team names (deduplicated and sorted)
        """
        self.load_csv()

        player_games = self._cache.get(player_name, [])
        if not player_games:
            # Try fuzzy match
            player_lower = player_name.lower()
            for p in self._all_players:
                if player_lower in p.lower() or p.lower() in player_lower:
                    player_games = self._cache.get(p, [])
                    break

        opponents = set()
        for game in player_games:
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

    def get_teammates(self, player_name: str) -> List[str]:
        """
        Get all teammates who have played for the same team as the player

        Traverses all game logs of the player and collects teammates from _lineup_cache.

        Args:
            player_name: player name

        Returns:
            List[str]: list of teammate names (deduplicated and sorted, excluding the player themself)
        """
        self.load_csv()

        player_games = self._cache.get(player_name, [])
        if not player_games:
            player_lower = player_name.lower()
            for p in self._all_players:
                if player_lower in p.lower() or p.lower() in player_lower:
                    player_games = self._cache.get(p, [])
                    player_name = p
                    break

        teammates: Set[str] = set()
        for game in player_games:
            team = game.get("team", "")
            game_date = game.get("game_date")
            if not team or game_date is None:
                continue
            date_key = game_date.strftime("%Y-%m-%d")
            lineup = self._lineup_cache.get((team, date_key), set())
            teammates.update(lineup)

        teammates.discard(player_name)
        return sorted(teammates)

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
        teammate_played: Optional[bool] = None
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

        # Get player's game logs
        player_games = self._cache.get(player_name, [])

        if not player_games:
            # Try fuzzy match
            player_lower = player_name.lower()
            matched_player = None
            for p in self._all_players:
                if player_lower in p.lower() or p.lower() in player_lower:
                    matched_player = p
                    break

            if matched_player:
                player_games = self._cache.get(matched_player, [])
                player_name = matched_player

        if not player_games:
            return {
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

        # Get all opponents (for filters)
        all_opponents = self.get_player_opponents(player_name)
        # Get all teammates (for star teammate selector, only those on the same team)
        all_teammates = self.get_teammates(player_name)

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

            # Get value for the specified metric
            value = game.get(metric)
            if value is not None:
                values.append(value)

                # Build game log data
                game_date = game.get("game_date")
                minutes = game.get("minutes", 0)
                game_is_starter = game.get("is_starter", False)

                valid_games.append({
                    "date": game_date.strftime("%m/%d") if game_date else "",
                    "date_full": game_date.strftime("%Y-%m-%d") if game_date else "",
                    "opponent": game.get("opponent", ""),
                    "value": value,
                    "is_over": value > threshold,
                    "team": game.get("team", ""),
                    "minutes": round(minutes, 1),  # minutes played
                    "is_starter": game_is_starter,  # whether started
                })

        # Take the most recent N games
        if n > 0 and len(valid_games) > n:
            valid_games = valid_games[:n]
            values = values[:n]

        if not values:
            return {
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

        return {
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


# Create singleton instance
# This instance is created when the module is imported; always use the same instance afterward
csv_player_service = CSVPlayerHistoryService()

