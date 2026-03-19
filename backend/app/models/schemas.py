"""
schemas.py - Pydantic schema definitions

Defines all API request and response data structures
- BaseModel: Pydantic base model class, provides data validation
- Field: Used to define extra info for fields (description, default values, etc)
"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime


# ==================== Health Check ====================

class HealthResponse(BaseModel):
    """
    API response model for health check
    Used for GET /api/health endpoint
    """
    ok: bool = Field(..., description="Is the service operating normally")
    service: str = Field(..., description="Service name")
    time: datetime = Field(..., description="Current server time (UTC)")


# ==================== NBA Events ====================

class NBAEvent(BaseModel):
    """
    Single NBA game information

    - event_id: Unique identifier for the event, for subsequent prop queries
    - sport_key: Sport key, NBA is "basketball_nba"
    - home_team: Name of the home team
    - away_team: Name of the away team
    - commence_time: Game start time (UTC ISO 8601 format)
    """
    event_id: str = Field(..., description="Event ID")
    sport_key: str = Field(..., description="Sport key")
    home_team: str = Field(..., description="Home team")
    away_team: str = Field(..., description="Away team")
    commence_time: datetime = Field(..., description="Game start time (UTC)")


class EventsResponse(BaseModel):
    """
    API response model for event list
    Used for GET /api/nba/events endpoint
    """
    date: str = Field(..., description="Query date YYYY-MM-DD")
    events: List[NBAEvent] = Field(default_factory=list, description="Event list")


# ==================== Props Calculation ====================

class NoVigRequest(BaseModel):
    """
    No-vig probability calculation API request model
    Used for POST /api/nba/props/no-vig endpoint

    - event_id: Event ID to query
    - player_name: Player name (supports fuzzy match)
    - market: Betting market type, default "player_points" (player points)
    - regions: Region code, affects available sportsbooks
    - bookmakers: List of sportsbooks to query, empty means all
    - odds_format: Odds format, "american" or "decimal"
    """
    event_id: str = Field(..., description="Event ID")
    player_name: str = Field(..., description="Player name")
    market: str = Field(default="player_points", description="Betting market type")
    regions: str = Field(default="us", description="Region")
    bookmakers: Optional[List[str]] = Field(default=None, description="Bookmaker list, None means all")
    odds_format: str = Field(default="american", description="Odds format")


class BookmakerResult(BaseModel):
    """
    Single bookmaker calculation result

    - bookmaker: Bookmaker name
    - line: Threshold value (e.g. 28.5 points)
    - over_odds / under_odds: Raw odds (American format)
    - p_over_imp / p_under_imp: Implied probability (with vig)
    - vig: Vig percentage (bookmaker profit)
    - p_over_fair / p_under_fair: Fair probability after vig removed
    - fetched_at: Data fetch time
    """
    bookmaker: str = Field(..., description="Bookmaker name")
    line: float = Field(..., description="Threshold value")
    over_odds: float = Field(..., description="Over odds")
    under_odds: float = Field(..., description="Under odds")
    p_over_imp: float = Field(..., description="Over implied probability")
    p_under_imp: float = Field(..., description="Under implied probability")
    vig: float = Field(..., description="Vig (bookmaker edge)")
    p_over_fair: float = Field(..., description="Over fair (no-vig) probability")
    p_under_fair: float = Field(..., description="Under fair (no-vig) probability")
    fetched_at: datetime = Field(..., description="Data fetch time")


class Consensus(BaseModel):
    """
    Market consensus calculation result

    Average the no-vig probabilities from multiple bookmakers to get market consensus
    - method: Calculation method ("mean" or "weighted")
    - p_over_fair / p_under_fair: Consensus probabilities
    """
    method: str = Field(..., description="Calculation method")
    p_over_fair: float = Field(..., description="Consensus over probability")
    p_under_fair: float = Field(..., description="Consensus under probability")


class NoVigResponse(BaseModel):
    """
    No-vig probability calculation API response model
    """
    event_id: str = Field(..., description="Event ID")
    player_name: str = Field(..., description="Player name")
    market: str = Field(..., description="Betting market type")
    results: List[BookmakerResult] = Field(default_factory=list, description="Bookmaker results")
    consensus: Optional[Consensus] = Field(default=None, description="Market consensus")
    message: Optional[str] = Field(default=None, description="Extra message (e.g. player not found)")
    fetched_at: Optional[datetime] = Field(default=None, description="Cache data fetch time")
    data_age_seconds: Optional[int] = Field(default=None, description="Data age in seconds")
    cache_state: Optional[str] = Field(default=None, description="fresh | stale | refreshed")
    source: Optional[str] = Field(default=None, description="snapshot_cache | upstream")


# ==================== Player Suggest ====================

class PlayerSuggestResponse(BaseModel):
    """
    Player name suggestion API response model
    For frontend autocomplete feature
    """
    players: List[str] = Field(default_factory=list, description="List of player names")
    fetched_at: Optional[datetime] = Field(default=None, description="Cache data fetch time")
    data_age_seconds: Optional[int] = Field(default=None, description="Data age in seconds")
    cache_state: Optional[str] = Field(default=None, description="fresh | stale | refreshed")
    source: Optional[str] = Field(default=None, description="snapshot_cache | upstream")


# ==================== Error Response ====================

class ErrorResponse(BaseModel):
    """
    Error response model
    Unified error response format
    """
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(default=None, description="Additional details")


# ==================== CSV Player History Data ====================

class CSVPlayersResponse(BaseModel):
    """
    CSV players list API response model
    For GET /api/nba/csv/players endpoint

    Returns all player names read from CSV file
    """
    players: List[str] = Field(default_factory=list, description="List of player names")
    total: int = Field(..., description="Total number of players")


class HistogramBin(BaseModel):
    """
    Single histogram bin data

    - binStart: Bin start value
    - binEnd: Bin end value
    - count: Number of data points in the bin
    """
    binStart: float = Field(..., description="Bin start value")
    binEnd: float = Field(..., description="Bin end value")
    count: int = Field(..., description="Count in this bin")


class GameLog(BaseModel):
    """
    Single game log

    Used for time series charts, shows details for each game
    """
    date: str = Field(..., description="Game date (MM/DD format)")
    date_full: str = Field(..., description="Full date (YYYY-MM-DD format)")
    opponent: str = Field(..., description="Opponent team")
    value: float = Field(..., description="Value for the metric")
    is_over: bool = Field(..., description="Whether above threshold")
    team: str = Field(default="", description="Player's team")
    minutes: float = Field(default=0.0, description="Minutes played")
    is_starter: bool = Field(default=False, description="Is starter")


class PlayerHistoryResponse(BaseModel):
    """
    Player historical data statistics API response model
    For GET /api/nba/player-history endpoint

    Calculates player's empirical probability for a given metric (e.g. points)
    This is empirical probability, not model prediction

    - player: Player name
    - metric: Metric type (points/assists/rebounds/pra)
    - threshold: User-set threshold (e.g. 24.5)
    - n_games: Number of games in sample
    - p_over: Probability of over (value > threshold)
    - p_under: Probability of under (value < threshold)
    - mean: Mean of the metric
    - std: Std of the metric
    - histogram: Histogram data (for visualization, backward compatible)
    - game_logs: Detail for each game (for time series)
    - opponents: List of opponents (for filter)
    """
    player: str = Field(..., description="Player name")
    metric: str = Field(..., description="Metric type")
    threshold: float = Field(..., description="Threshold value")
    n_games: int = Field(..., description="Sample game count")
    p_over: Optional[float] = Field(default=None, description="Over probability")
    p_under: Optional[float] = Field(default=None, description="Under probability")
    equal_count: Optional[int] = Field(default=0, description="Count of games equal to threshold")
    mean: Optional[float] = Field(default=None, description="Mean value")
    std: Optional[float] = Field(default=None, description="Standard deviation")
    histogram: List[HistogramBin] = Field(default_factory=list, description="Histogram data")
    game_logs: List[GameLog] = Field(default_factory=list, description="Per-game details")
    opponents: List[str] = Field(default_factory=list, description="Opponent list")
    teammates: List[str] = Field(default_factory=list, description="Teammate list (for star teammate selector)")
    opponent_filter: Optional[str] = Field(default=None, description="Current opponent filter")
    teammate_filter: Optional[List[str]] = Field(default=None, description="Current star teammate filter")
    teammate_played: Optional[bool] = Field(default=None, description="Star teammate presence filter")
    message: Optional[str] = Field(default=None, description="Additional message")


# ==================== Player Projection Data ====================

class PlayerProjection(BaseModel):
    """
    Projection data for a single player

    Corresponds to SportsDataIO Projected Player Game Stats API data.
    This is a predicted value, not actual game results.

    Field categories:
    - Basic info: player name, team, position
    - Core projections: expected points, rebounds, assists, etc (Free Trial available)
    - Matchup difficulty: opponent defense rank
    - Starter/injury: starter status, injury info (Free Trial will be scrambled)
    - DFS: DraftKings / FanDuel salary and fantasy points
    """
    # Basic info
    player_id: Optional[int] = Field(default=None, description="SportsDataIO player ID")
    player_name: str = Field(..., description="Player name")
    team: Optional[str] = Field(default=None, description="Team abbreviation (e.g. GS, LAL)")
    position: Optional[str] = Field(default=None, description="Position (PG/SG/SF/PF/C)")
    opponent: Optional[str] = Field(default=None, description="Opponent team abbreviation")
    home_or_away: Optional[str] = Field(default=None, description="HOME or AWAY")

    # Core projections (Free Trial available)
    minutes: Optional[float] = Field(default=None, description="Projected minutes played")
    points: Optional[float] = Field(default=None, description="Projected points")
    rebounds: Optional[float] = Field(default=None, description="Projected rebounds")
    assists: Optional[float] = Field(default=None, description="Projected assists")
    steals: Optional[float] = Field(default=None, description="Projected steals")
    blocked_shots: Optional[float] = Field(default=None, description="Projected blocks")
    turnovers: Optional[float] = Field(default=None, description="Projected turnovers")
    pra: Optional[float] = Field(default=None, description="Projected PRA (Points + Rebounds + Assists)")

    # Shooting stats
    field_goals_made: Optional[float] = Field(default=None, description="Field goals made")
    field_goals_attempted: Optional[float] = Field(default=None, description="Field goals attempted")
    three_pointers_made: Optional[float] = Field(default=None, description="3PT made")
    three_pointers_attempted: Optional[float] = Field(default=None, description="3PT attempted")
    free_throws_made: Optional[float] = Field(default=None, description="Free throws made")
    free_throws_attempted: Optional[float] = Field(default=None, description="Free throws attempted")

    # Starter / injury (Free Trial will be scrambled, shown as None)
    started: Optional[int] = Field(default=None, description="Starter (1=Yes, 0=No)")
    lineup_confirmed: Optional[bool] = Field(default=None, description="Lineup confirmed")
    injury_status: Optional[str] = Field(default=None, description="Injury status (Free Trial: None)")
    injury_body_part: Optional[str] = Field(default=None, description="Injured body part")

    # Matchup difficulty
    opponent_rank: Optional[int] = Field(default=None, description="Opponent overall defense rank (1-30)")
    opponent_position_rank: Optional[int] = Field(default=None, description="Opponent defense vs position rank")

    # DFS related
    draftkings_salary: Optional[float] = Field(default=None, description="DraftKings DFS salary")
    fanduel_salary: Optional[float] = Field(default=None, description="FanDuel DFS salary")
    fantasy_points_dk: Optional[float] = Field(default=None, description="DraftKings Fantasy points")
    fantasy_points_fd: Optional[float] = Field(default=None, description="FanDuel Fantasy points")

    # Advanced stats
    usage_rate_percentage: Optional[float] = Field(default=None, description="Usage rate %")
    player_efficiency_rating: Optional[float] = Field(default=None, description="Player Efficiency Rating (PER)")


class ProjectionsResponse(BaseModel):
    """
    Player projection data API response model

    For GET /api/nba/projections endpoint
    Returns projection data for all players on given date
    """
    date: str = Field(..., description="Query date (YYYY-MM-DD)")
    player_count: int = Field(..., description="Player count")
    fetched_at: Optional[str] = Field(default=None, description="Data fetch time")
    projections: List[PlayerProjection] = Field(default_factory=list, description="Player projections")


class ProjectionRefreshResponse(BaseModel):
    """
    Projection data refresh API response model

    For POST /api/nba/projections/refresh endpoint
    """
    date: str = Field(..., description="Refresh date")
    player_count: int = Field(..., description="Fetched player count")
    message: str = Field(..., description="Operation message")


class TeamLineup(BaseModel):
    date: str = Field(..., description="Query date YYYY-MM-DD")
    team: str = Field(..., description="Team code")
    opponent: str = Field(default="", description="Opponent team code")
    home_or_away: str = Field(default="", description="HOME or AWAY")
    status: str = Field(..., description="projected | partial | unavailable")
    starters: List[str] = Field(default_factory=list, description="Projected starting five")
    bench_candidates: List[str] = Field(default_factory=list, description="Primary bench candidates")
    sources: List[str] = Field(default_factory=list, description="Consensus sources")
    source_disagreement: bool = Field(default=False, description="Is source inconsistent")
    confidence: str = Field(..., description="high | medium | low")
    updated_at: Optional[str] = Field(default=None, description="Source update time")
    source_snapshots: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Standardized snapshot of each source",
    )


class LineupsResponse(BaseModel):
    date: str = Field(..., description="Query date YYYY-MM-DD")
    team_count: int = Field(..., description="Team count")
    fetched_at: Optional[str] = Field(default=None, description="Data fetch time")
    cache_state: str = Field(default="fresh", description="fresh | stale | refreshed")
    lineups: List[TeamLineup] = Field(default_factory=list, description="Team lineup list")


class LineupRefreshResponse(BaseModel):
    date: str = Field(..., description="Refresh date")
    team_count: int = Field(..., description="Fetched team count")
    message: str = Field(..., description="Operation message")


# ==================== Daily High Probability Players Analysis ====================

class DailyPick(BaseModel):
    """
    Single high-probability player pick

    When a player's historical probability for a metric > 65%, included in daily picks

    Field explanation:
    - player_name: Player name (e.g. "Stephen Curry")
    - player_team: Player's team (short name, e.g. "Lakers", "Warriors")
    - event_id: Event ID, for linking to detail page
    - home_team / away_team: Home/away teams
    - commence_time: Game start time (ISO 8601 format)
    - metric: Stat metric (points/assists/rebounds/pra)
    - threshold: Modal line (mode of all bookmaker lines)
    - direction: "over" or "under," higher probability direction
    - probability: Historical probability (>= 0.65)
    - n_games: Number of historical games used
    - bookmakers_count: Number of bookmakers offering this line
    - all_lines: List of all bookmaker lines (for distribution display)
    """
    player_name: str = Field(..., description="Player name")
    player_team: str = Field(default="", description="Player's team (short name)")
    player_team_code: str = Field(default="", description="Player's team code")
    event_id: str = Field(..., description="Event ID")
    home_team: str = Field(..., description="Home team")
    away_team: str = Field(..., description="Away team")
    commence_time: str = Field(..., description="Game start time")
    metric: str = Field(..., description="Stat metric (points/assists/rebounds/pra)")
    threshold: float = Field(..., description="Modal threshold")
    direction: str = Field(..., description="Direction (over/under)")
    probability: float = Field(..., description="Historical probability")
    n_games: int = Field(..., description="Sample size (games)")
    bookmakers_count: int = Field(..., description="Bookmakers count")
    all_lines: List[float] = Field(default_factory=list, description="All bookmaker lines")

    # === Projection fields (from SportsDataIO Projection API) ===
    has_projection: bool = Field(default=False, description="Has projection data")
    projected_value: Optional[float] = Field(
        default=None,
        description="Projected value (e.g. projected points = 29.3)"
    )
    projected_minutes: Optional[float] = Field(
        default=None,
        description="Projected minutes played"
    )
    edge: Optional[float] = Field(
        default=None,
        description="Difference between projection and line (projected_value - threshold), positive favors Over"
    )
    opponent_rank: Optional[int] = Field(
        default=None,
        description="Opponent overall defense rank (1-30, 1=weakest defense)"
    )
    opponent_position_rank: Optional[int] = Field(
        default=None,
        description="Opponent defense vs position rank (1-30)"
    )
    injury_status: Optional[str] = Field(
        default=None,
        description="Injury status (Free Trial: None)"
    )
    lineup_confirmed: Optional[bool] = Field(
        default=None,
        description="Is lineup confirmed"
    )


class AnalysisStats(BaseModel):
    """
    Analysis statistics

    Provides summary statistics for the overall analysis
    """
    total_events: int = Field(..., description="Total events analyzed")
    total_players: int = Field(..., description="Total players analyzed")
    total_props: int = Field(..., description="Total number of props analyzed")
    high_prob_count: int = Field(..., description="Number of high probability picks")
    analysis_duration_seconds: float = Field(..., description="Analysis duration (seconds)")


class DailyPicksResponse(BaseModel):
    """
    Daily high probability player picks API response model
    Used for GET /api/nba/daily-picks endpoint

    Returns all player picks with probability > 65% for the day
    """
    date: str = Field(..., description="Analysis date YYYY-MM-DD")
    analyzed_at: str = Field(..., description="Analysis execution time (ISO 8601)")
    total_picks: int = Field(..., description="Total number of eligible picks")
    picks: List[DailyPick] = Field(default_factory=list, description="High-probability player list")
    stats: Optional[AnalysisStats] = Field(default=None, description="Analysis stats")
    message: Optional[str] = Field(default=None, description="Additional message")


# ==================== Odds Line Snapshot (Line Movement Tracking) ====================

class OddsLineSnapshot(BaseModel):
    """
    Single odds line snapshot

    Represents the no-vig calculation for a single bookmaker, player, market at a given time.
    One snapshot run yields many OddsLineSnapshot records.

    Field explanation:
    - bookmaker: Bookmaker key (e.g. "draftkings")
    - line: Odds line value (e.g. 24.5), core value that moves
    - over_odds / under_odds: Raw American odds (e.g. -110)
    - vig: Vig percentage (e.g. 0.0476 = 4.76%)
    - over_fair_prob / under_fair_prob: Fair probability (vig removed)
    """
    bookmaker: str = Field(..., description="Bookmaker key")
    line: Optional[float] = Field(default=None, description="Line value")
    over_odds: Optional[int] = Field(default=None, description="Over American odds")
    under_odds: Optional[int] = Field(default=None, description="Under American odds")
    vig: Optional[float] = Field(default=None, description="Vig percentage")
    over_fair_prob: Optional[float] = Field(default=None, description="Over no-vig (fair) probability")
    under_fair_prob: Optional[float] = Field(default=None, description="Under no-vig (fair) probability")


class OddsConsensus(BaseModel):
    """
    Odds consensus

    Average no-vig probability from multiple bookmakers, representing market consensus.
    In API response, consensus is calculated in real time from odds_line_snapshots grouped by
    (snapshot_at, player_name, market) using SQL AVG(); not stored separately.
    """
    over_fair_prob: float = Field(..., description="Consensus over no-vig probability")
    under_fair_prob: float = Field(..., description="Consensus under no-vig probability")
    avg_line: Optional[float] = Field(default=None, description="Average line")
    bookmaker_count: int = Field(default=0, description="Number of bookmakers")


class OddsSnapshotGroup(BaseModel):
    """
    Group of snapshots at a single time

    Represents all bookmaker lines for a given time.
    For example, UTC 16:00 snapshot includes lines + no-vig from DraftKings, FanDuel, etc.
    Used for line movement visualization: each group is one data point on the timeline.

    Fields:
    - snapshot_at: Snapshot time (ISO 8601)
    - lines: List of per-bookmaker no-vig calculation results
    - consensus: Market consensus
    """
    snapshot_at: str = Field(..., description="Snapshot time (ISO 8601)")
    lines: List[OddsLineSnapshot] = Field(
        default_factory=list, description="Bookmaker line data"
    )
    consensus: Optional[OddsConsensus] = Field(
        default=None, description="Market consensus (avg no-vig probability)"
    )


class OddsHistoryResponse(BaseModel):
    """
    Odds history API response model

    For GET /api/nba/odds-history endpoint.
    Returns all snapshots for a given player, market, and date.
    Each snapshot includes no-vig results per bookmaker and the market consensus.

    Usage: Data source for frontend line movement chart.
    """
    date: str = Field(..., description="Game date YYYY-MM-DD")
    player_name: str = Field(..., description="Player name")
    market: str = Field(..., description="Market type")
    snapshot_count: int = Field(default=0, description="Snapshot count")
    snapshots: List[OddsSnapshotGroup] = Field(
        default_factory=list, description="Snapshot list (time ordered)"
    )


class OddsSnapshotTriggerResponse(BaseModel):
    """
    Manual odds line snapshot trigger API response model

    For POST /api/nba/odds-history/snapshot endpoint.
    Returns a summary of the snapshot run.
    """
    date: str = Field(..., description="Snapshot date")
    event_count: int = Field(default=0, description="Number of events processed")
    total_lines: int = Field(default=0, description="Total odds line records written")
    duration_ms: int = Field(default=0, description="Duration (ms)")
    message: str = Field(default="", description="Operation message")
