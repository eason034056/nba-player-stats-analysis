"""
schemas.py - Pydantic schema definitions

Defines all API request and response data structures
- BaseModel: Pydantic base model class, provides data validation
- Field: Used to define extra info for fields (description, default values, etc)
"""

import math

from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, List, Literal, Optional
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

class EventLineupStatus(BaseModel):
    """Per-team lineup confirmation on one NBA event.

    ``confirmed`` when any source snapshot for that club reports
    ``status == "confirmed"``. ``projected`` when a lineup exists and
    nobody reported confirmed. ``null`` when that club has no lineup
    for the events date. See ``confirmation_status``.
    """
    home: Optional[Literal["confirmed", "projected"]] = Field(
        default=None,
        description="Home club confirmation: confirmed, projected, or null",
    )
    away: Optional[Literal["confirmed", "projected"]] = Field(
        default=None,
        description="Away club confirmation: confirmed, projected, or null",
    )


class TopRead(BaseModel):
    """
    Best stored daily pick for one event.

    Joined from the daily-picks cache for that event_id. This is not an
    Odds API field and does not trigger a props request.

    - player: Player name on the stored pick
    - market: Odds API market key (player_points), not the CSV metric (points)
    - side: Stored direction, over or under
    - line: Modal bookmaker line
    - probability: Chosen-side historical rate, from 0 to 1
    """
    player: str = Field(..., description="Player name")
    market: str = Field(
        ...,
        min_length=1,
        description="Odds API market key, for example player_points",
    )
    side: Literal["over", "under"] = Field(..., description="Stored pick side")
    line: float = Field(..., description="Modal bookmaker line")
    probability: float = Field(..., description="Chosen-side historical probability (0-1)")

    @field_validator("line", "probability")
    @classmethod
    def _must_be_finite(cls, value: float) -> float:
        """Reject NaN and Infinity before a TopRead can be built.

        Args:
            value: Parsed line or probability.

        Returns:
            The same number when it is finite.

        Raises:
            ValueError: ``value`` is NaN or Infinity.
        """
        if not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value


class NBAEvent(BaseModel):
    """
    Single NBA game information

    - event_id: Unique identifier for the event, for subsequent prop queries
    - sport_key: Sport key, NBA is "basketball_nba"
    - home_team: Name of the home team
    - away_team: Name of the away team
    - commence_time: Game start time (UTC ISO 8601 format)
    - top_read: Highest-probability stored daily pick for this event, or null
    """
    event_id: str = Field(..., description="Event ID")
    sport_key: str = Field(..., description="Sport key")
    home_team: str = Field(..., description="Home team")
    away_team: str = Field(..., description="Away team")
    commence_time: datetime = Field(..., description="Game start time (UTC)")
    commence_time_et: Optional[str] = Field(
        default=None,
        description="Same tip as commence_time, ISO 8601 with the America/New_York offset",
    )
    display_tz: Optional[str] = Field(
        default=None,
        description='Zone label for commence_time_et. "ET" on NBA events.',
    )
    lineup_status: Optional[EventLineupStatus] = Field(
        default=None,
        description="Per-team confirmation for this event. Null on WNBA.",
    )
    top_read: Optional[TopRead] = Field(
        default=None,
        description=(
            "Highest-probability stored daily pick for this event, or null "
            "when that event has no stored pick. Filled on GET /api/nba/events "
            "from the daily-picks cache."
        ),
    )


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
    Single bookmaker calculation result.

    Two market shapes share this model:

    Over/Under markets (e.g. ``player_points``):
        - line, over_odds/under_odds, p_over_imp/p_under_imp, vig,
          p_over_fair/p_under_fair are populated as before.
        - The binary-market fields (yes_*, no_*) stay None.

    Binary Yes/No markets (e.g. ``player_double_double``):
        - line is the sentinel ``0.5`` (the bet has no threshold; consumers
          MUST dispatch on ``market`` and not interpret ``0.5`` as a real
          point). Documented also in
          ``odds_snapshot_service._parse_binary_market``.
        - over_odds/p_over_imp/p_over_fair carry the **Yes** leg values; the
          explicit ``yes_price``/``p_yes_imp``/``yes_fair_prob`` mirrors are
          provided for self-documenting consumers.
        - under_odds/p_under_imp carry the **posted** No price and its
          implied probability. When the book did not post No, both are
          None. They are never a copy of the Yes price and never
          ``1 - p_yes_imp``.
        - p_under_fair / no_fair_prob stay the complement of the
          de-vigged Yes fair. On a one-sided quote that complement is a
          model output of the single-leg prior, not a posted price.
        - ``line_is_synthetic`` is True and ``market_kind`` is
          ``"binary"`` when ``line`` is the 0.5 sentinel.
        - ``uses_prior`` is True when this row's fair probability came
          from ``single_leg_devig`` because the book did not post No.
          It is False when both legs were posted, and False for every
          Over/Under row.
        - Anti-hallucination guard: rows where ``yes_fair_prob`` cannot be
          honestly derived (vig prior fails on a single-leg quote) are
          NOT emitted — the route surfaces that via ``message`` rather
          than fabricating a number.
    """
    bookmaker: str = Field(..., description="Bookmaker name")
    line: float = Field(..., description="Threshold value (Over/Under) or 0.5 sentinel for binary markets")
    over_odds: float = Field(..., description="Over odds (or Yes price for binary markets)")
    under_odds: Optional[float] = Field(
        default=None,
        description="Posted Under odds, or the posted No price. None when a binary market has no No price.",
    )
    p_over_imp: float = Field(..., description="Over implied probability (or Yes implied for binary markets)")
    p_under_imp: Optional[float] = Field(
        default=None,
        description="Implied probability of a posted Under or No price. None when that price was not posted.",
    )
    vig: float = Field(..., description="Vig (bookmaker edge)")
    p_over_fair: float = Field(..., description="Over fair (no-vig) probability (or Yes fair for binary markets)")
    p_under_fair: float = Field(..., description="Under fair (no-vig) probability (or No fair for binary markets)")
    fetched_at: datetime = Field(..., description="Data fetch time")
    line_is_synthetic: bool = Field(
        ...,
        description="True when line is the 0.5 sentinel for a binary market, not a posted total.",
    )
    market_kind: Literal["binary", "over_under"] = Field(
        ...,
        description="binary for Yes/No markets such as player_double_double; over_under for a posted total.",
    )
    uses_prior: bool = Field(
        ...,
        description=(
            "True when this row's fair probability came from the single-leg "
            "prior because the No leg was not posted. False for a two-sided "
            "quote and for every Over/Under row."
        ),
    )

    # === Binary-market explicit mirrors (SPO-26) ===================
    # For binary markets the over_*/under_* fields above carry the Yes/No
    # values via positional convention; these explicit fields exist so
    # consumers that prefer self-documenting names (e.g. the SPO-20
    # PlayerDDTile contract) can read directly without having to know the
    # convention. Stay None for Over/Under markets.
    yes_price: Optional[float] = Field(default=None, description="Yes leg American odds (binary markets only)")
    no_price: Optional[float] = Field(default=None, description="No leg American odds (binary markets only)")
    p_yes_imp: Optional[float] = Field(default=None, description="Yes implied probability (binary markets only)")
    p_no_imp: Optional[float] = Field(default=None, description="No implied probability (binary markets only)")
    yes_fair_prob: Optional[float] = Field(default=None, description="Yes single-leg de-vigged probability (binary markets only)")
    no_fair_prob: Optional[float] = Field(default=None, description="No single-leg de-vigged probability (binary markets only)")


class Consensus(BaseModel):
    """
    Market consensus calculation result

    Average the no-vig probabilities from multiple bookmakers to get market consensus
    - method: Calculation method ("mean" or "weighted")
    - p_over_fair / p_under_fair: Consensus probabilities
    - p_yes_fair / p_no_fair: Binary-market mirrors of p_over_fair / p_under_fair,
      populated for binary markets (e.g. player_double_double); None for Over/Under
    - consensus_uses_prior / consensus_prior_book_count: whether any book
      in this average was de-vigged with the single-leg prior, and how many.
      Both are False / 0 for an Over/Under consensus.
    """
    method: str = Field(..., description="Calculation method")
    p_over_fair: float = Field(..., description="Consensus over (or Yes for binary) probability")
    p_under_fair: float = Field(..., description="Consensus under (or No for binary) probability")
    p_yes_fair: Optional[float] = Field(default=None, description="Consensus Yes probability (binary markets only)")
    p_no_fair: Optional[float] = Field(default=None, description="Consensus No probability (binary markets only)")
    consensus_uses_prior: bool = Field(
        ...,
        description="True when any book included in this consensus used the single-leg prior.",
    )
    consensus_prior_book_count: int = Field(
        ...,
        description="How many books included in this consensus used the single-leg prior.",
    )


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

class PlayerSuggestion(BaseModel):
    """One suggested name plus the position from the game log, when known."""
    name: str = Field(..., description="Player name, same spelling as players[]")
    position: Optional[str] = Field(
        default=None,
        description="Pos on the player's most recent game log. Null when the name is not in the log.",
    )


class PlayerSuggestResponse(BaseModel):
    """
    Player name suggestion API response model
    For frontend autocomplete feature
    """
    players: List[str] = Field(default_factory=list, description="List of player names")
    suggestions: List[PlayerSuggestion] = Field(
        default_factory=list,
        description="Same order as players, with position. Empty on WNBA.",
    )
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
    game_type: str = Field(
        default="regular_season",
        description="regular_season, playoffs, or play_in",
    )
    season: str = Field(default="", description="Season label for this game")
    home_or_away: Optional[Literal["home", "away"]] = Field(
        default=None,
        description="home or away from the recorded schedule join. Null when the row does not join.",
    )


class TeammateMissedGame(BaseModel):
    """One game in the history sample where a listed teammate did not play."""
    date: str = Field(..., description="Game date YYYY-MM-DD")
    game_id: Optional[str] = Field(
        default=None,
        description="Recorded ESPN event id when the schedule join is unique. Otherwise null.",
    )


class TeammateContext(BaseModel):
    """Games a listed teammate missed, plus the player's stat with and without them."""
    name: str = Field(..., description="Teammate name. Also present in teammates[].")
    games_missed: int = Field(..., description="How many sample games this teammate did not play")
    missed_games: List[TeammateMissedGame] = Field(
        default_factory=list,
        description="Those games, oldest first",
    )
    with_n: int = Field(default=0, description="Sample games this teammate played")
    without_n: int = Field(default=0, description="Sample games this teammate missed")
    with_mean: Optional[float] = Field(
        default=None,
        description="Mean of the requested stat in games this teammate played",
    )
    without_mean: Optional[float] = Field(
        default=None,
        description="Mean of the requested stat in games this teammate missed",
    )


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
    teammate_context: List[TeammateContext] = Field(
        default_factory=list,
        description="Same names as teammates, with games missed and a with/without split. Empty on WNBA.",
    )
    opponent_filter: Optional[str] = Field(default=None, description="Current opponent filter")
    teammate_filter: Optional[List[str]] = Field(default=None, description="Current star teammate filter")
    teammate_played: Optional[bool] = Field(default=None, description="Star teammate presence filter")
    season: Optional[str] = Field(
        default=None,
        description="Season the season_* rates use. Echoed from the query or the current NBA season.",
    )
    season_n_games: Optional[int] = Field(
        default=None,
        description="Games in that season after the same filters as n_games, ignoring the n window",
    )
    season_p_over: Optional[float] = Field(
        default=None,
        description="Share of season games strictly above the threshold",
    )
    season_p_under: Optional[float] = Field(
        default=None,
        description="Share of season games strictly below the threshold",
    )
    season_mean: Optional[float] = Field(
        default=None,
        description=(
            "Mean of the metric on the same season games as season_n_games. "
            "Ignores the threshold and the n window. Null when that season "
            "has no games. Null on WNBA."
        ),
    )
    message: Optional[str] = Field(default=None, description="Additional message")


class PlayerDDHistoryResponse(BaseModel):
    """
    Player Double-Double historical rate API response model.
    For GET /api/nba/player-dd-history endpoint.

    DD is a binary outcome (Yes/No), not Over/Under — so this endpoint
    returns ``prob_dd`` (a single probability), not ``p_over``/``p_under``,
    and there is no ``threshold`` parameter on the request.

    DD definition (per services layer): a game in which the player records
    ≥10 in at least 2 of {PTS, REB, AST, STL, BLK}.

    Fields:
        - player: resolved player name (post fuzzy-match)
        - season: season filter actually applied (None = all seasons)
        - n_games: count of games considered (DNPs excluded)
        - dd_games: count of those games that were DDs
        - prob_dd: dd_games / n_games (None when n_games == 0)
        - message: explanatory string when sample is empty; None on success
    """
    player: str = Field(..., description="Player name (post fuzzy-match)")
    season: Optional[str] = Field(default=None, description="Season filter applied (None = all)")
    n_games: int = Field(..., description="Sample game count (DNPs excluded)")
    dd_games: int = Field(..., description="Number of DD games in the sample")
    prob_dd: Optional[float] = Field(default=None, description="Historical P(DD = 1); None when sample is empty")
    message: Optional[str] = Field(default=None, description="Explanatory message; None on success")


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

    # Matchup difficulty. 1 is the most points allowed (weakest defense).
    opponent_rank: Optional[int] = Field(
        default=None,
        ge=1,
        le=30,
        description="Opponent overall defense rank. 1-30, 1 = most points allowed (weakest).",
    )
    opponent_position_rank: Optional[int] = Field(
        default=None,
        ge=1,
        le=30,
        description="Opponent defense vs this position. Ranked inside that position only, 1-30.",
    )
    opponent_rank_source: Optional[Literal["csv", "sportsdata", "sportsdata_invalid"]] = Field(
        default=None,
        description=(
            "Source of opponent_rank only. csv when that null was filled "
            "from the game log. sportsdata when the row already carried "
            "an integer in 1..30. sportsdata_invalid means the whole row "
            "is invalidated: the vendor value was not an integer in 1..30, "
            "so both ranks are null and neither is filled from the CSV."
        ),
    )
    opponent_rank_season: Optional[str] = Field(
        default=None,
        description=(
            "Game-log season for opponent_rank when its source is csv, "
            "e.g. 2025-2026 (the 2025-26 season). Null otherwise."
        ),
    )
    opponent_rank_note: Optional[str] = Field(
        default=None,
        description=(
            "Present when opponent_rank_source is csv: computed from real "
            "points allowed, not fantasy points."
        ),
    )
    opponent_position_rank_source: Optional[Literal["csv", "sportsdata", "sportsdata_invalid"]] = Field(
        default=None,
        description=(
            "Source of opponent_position_rank only. csv and sportsdata are "
            "labeled independently of the overall rank. sportsdata_invalid "
            "means the whole row is invalidated: both ranks are null and "
            "neither is filled from the CSV."
        ),
    )
    opponent_position_rank_season: Optional[str] = Field(
        default=None,
        description="Game-log season for the position rank when its source is csv. Null otherwise.",
    )
    opponent_position_rank_note: Optional[str] = Field(
        default=None,
        description="Present when the position rank source is csv: real points allowed, not fantasy points.",
    )

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
    """One team's lineup for a date.

    ``status`` and ``confirmation_status`` are different words.
    ``status`` is completeness from the starter count: ``projected``
    (five names), ``partial`` (fewer than five), or ``unavailable``.
    ``confirmation_status`` is whether any source snapshot reported
    ``confirmed``. A four-name slate can be ``status="partial"`` and
    ``confirmation_status="confirmed"`` at the same time. Both fields
    can also read ``projected``: completeness means the names are a
    projected five, and confirmation means nobody has reported the
    lineup confirmed.
    """
    date: str = Field(..., description="Query date YYYY-MM-DD")
    team: str = Field(..., description="Team code")
    opponent: str = Field(default="", description="Opponent team code")
    home_or_away: str = Field(default="", description="HOME or AWAY")
    status: str = Field(
        ...,
        description=(
            "Completeness from the starter count: projected (five names), "
            "partial (fewer than five), or unavailable. This is not "
            "confirmation. See confirmation_status."
        ),
    )
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
    confirmation_status: Optional[Literal["confirmed", "projected"]] = Field(
        default=None,
        description=(
            "Confirmation consensus, separate from status. confirmed when "
            "any source_snapshots status is confirmed, including a stale "
            "confirmation next to a fresh projected snapshot. projected "
            "when a snapshot or a starter exists and nobody reported "
            "confirmed (expected lands here). null when the record has "
            "neither. Does not read updated_at."
        ),
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


class PickSignal(BaseModel):
    """One signal on a Daily Pick, judged relative to the pick's side.

    ``value`` is display text. None means the input was missing.
    ``verdict`` is supports, neutral, or against. None means the input was
    missing, which is not the same as neutral.
    """

    key: str = Field(..., description="Stable key: market, last10, history, projection, defense")
    label: str = Field(..., description="Display label")
    value: str | None = Field(
        default=None,
        description="Display-ready text. None when the input is missing",
    )
    verdict: Literal["supports", "neutral", "against"] | None = Field(
        default=None,
        description="Relative to the pick's side. None when the input cannot be judged",
    )


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
    - threshold: Modal line (mode of one main line per bookmaker)
    - direction: "over" or "under," higher probability direction
    - probability: Historical probability of the chosen side. The default
      query keeps rows at or above 0.65. Stored NBA candidates go down to
      the Lean floor (0.56).
    - n_games: Number of historical games used
    - bookmakers_count: Distinct bookmakers that posted this player on this market
    - all_lines: One main line per bookmaker, sorted. Alternate rungs are not repeated.
    """
    player_name: str = Field(..., description="Player name")
    player_team: str = Field(default="", description="Player's team (short name)")
    player_team_code: str = Field(default="", description="Player's team code")
    position: Optional[str] = Field(
        default=None,
        description="Pos on the player's most recent NBA game log. Null when unknown. Null on WNBA.",
    )
    event_id: str = Field(..., description="Event ID")
    home_team: str = Field(..., description="Home team")
    away_team: str = Field(..., description="Away team")
    commence_time: str = Field(..., description="Game start time")
    metric: str = Field(..., description="Stat metric (points/assists/rebounds/pra)")
    threshold: float = Field(..., description="Modal threshold (one main line per bookmaker)")
    direction: str = Field(..., description="Direction (over/under)")
    probability: float = Field(..., description="Historical probability")
    n_games: int = Field(..., description="Sample size (games)")
    bookmakers_count: int = Field(
        ...,
        description="Distinct bookmakers posting this player on this market",
    )
    all_lines: List[float] = Field(
        default_factory=list,
        description="One main line per bookmaker",
    )

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
        ge=1,
        le=30,
        description="Opponent overall defense rank (1-30, 1=weakest defense, most points allowed)"
    )
    opponent_position_rank: Optional[int] = Field(
        default=None,
        ge=1,
        le=30,
        description="Opponent defense vs position rank, ranked inside that position (1-30)"
    )
    opponent_rank_source: Optional[Literal["csv", "sportsdata", "sportsdata_invalid"]] = Field(
        default=None,
        description=(
            "Source of opponent_rank only: csv, sportsdata, or "
            "sportsdata_invalid. sportsdata_invalid means the whole row "
            "is invalidated: both ranks are null and neither is filled "
            "from the CSV."
        ),
    )
    opponent_rank_season: Optional[str] = Field(
        default=None,
        description="Game-log season for opponent_rank when its source is csv, e.g. 2025-2026. Null otherwise.",
    )
    opponent_rank_note: Optional[str] = Field(
        default=None,
        description="On a csv overall rank: computed from real points allowed, not fantasy points.",
    )
    opponent_position_rank_source: Optional[Literal["csv", "sportsdata", "sportsdata_invalid"]] = Field(
        default=None,
        description=(
            "Source of opponent_position_rank only: csv, sportsdata, or "
            "sportsdata_invalid. sportsdata_invalid means the whole row "
            "is invalidated: both ranks are null and neither is filled "
            "from the CSV."
        ),
    )
    opponent_position_rank_season: Optional[str] = Field(
        default=None,
        description="Game-log season for the position rank when its source is csv. Null otherwise.",
    )
    opponent_position_rank_note: Optional[str] = Field(
        default=None,
        description="On a csv position rank: computed from real points allowed, not fantasy points.",
    )
    injury_status: Optional[str] = Field(
        default=None,
        description="Injury status (Free Trial: None)"
    )
    lineup_confirmed: Optional[bool] = Field(
        default=None,
        description="Is lineup confirmed"
    )
    # Additive read fields. Older cached payloads omit them and validate
    # as null. Later tickets can add verdict fields beside these.
    tier: Optional[Literal["Strong play", "Playable", "Lean"]] = Field(
        default=None,
        description=(
            "Read tier. NBA uses combined_probability. "
            "Strong play >= 0.70, Playable >= 0.65 and below 0.70, "
            "Lean >= 0.56 and below 0.65. "
            "Null when that probability is below 0.56, missing, or not finite. "
            "WNBA has no combined_probability, so WNBA tier still uses "
            "the historical probability and the same cutoffs."
        ),
    )
    p_over: Optional[float] = Field(
        default=None,
        description="Share of prior games strictly above the line. Null when unknown.",
    )
    p_under: Optional[float] = Field(
        default=None,
        description="Share of prior games strictly below the line. Null when unknown.",
    )
    season_mean: Optional[float] = Field(
        default=None,
        description=(
            "Mean of this metric in the current NBA season. Same games as "
            "player-history season_n_games. Ignores the line. Null when that "
            "season has no games, and null on WNBA."
        ),
    )

    # --- SPO-112 signal verdicts (self-contained; leave this block intact) ---
    # Separate from `probability` and from `tier`, `p_over`, and `p_under`.
    # NBA picks carry five signals. WNBA leaves both fields null.
    signals: list[PickSignal] | None = Field(
        default=None,
        description="Five NBA signal verdicts in a fixed order. None for WNBA",
    )
    combined_probability: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Calibrated probability for the pick's side, 0 to 1. "
            "None when the market price is missing, the player is Out or "
            "Doubtful, or the league is not NBA"
        ),
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


# ==================== Bulk event props (stored snapshot only) ====================

class BulkPropBook(BaseModel):
    """
    One bookmaker's stored line for one player and market.

    Over/Under markets fill ``over_odds`` and ``under_odds``. ``yes_odds``
    and ``no_odds`` are null. Binary markets (``player_double_double``)
    fill ``yes_odds`` and ``no_odds``. A side the book did not post is
    null, not a copy of the other side. ``over_odds`` and ``under_odds``
    are null on a binary row so a Yes price is not read as an Over.
    ``line`` on a binary row is the stored 0.5 sentinel, not a posted total.
    """
    bookmaker: str = Field(..., description="Bookmaker key, one row per book")
    line: float = Field(..., description="This book's stored line. 0.5 sentinel for binary markets")
    over_odds: Optional[int] = Field(default=None, description="Posted Over American odds. Null for binary markets and when Over was not stored")
    under_odds: Optional[int] = Field(default=None, description="Posted Under American odds. Null for binary markets and when Under was not stored")
    yes_odds: Optional[int] = Field(default=None, description="Posted Yes American odds for a binary market. Null for Over/Under markets")
    no_odds: Optional[int] = Field(default=None, description="Posted No American odds for a binary market. Null when that side was not posted, and null for Over/Under markets")


class BulkPropPlayer(BaseModel):
    """
    One player inside one market.

    ``line`` is the modal consensus of one line per bookmaker
    (``calculate_mode_threshold``). ``bookmakers_count`` counts distinct
    books after that collapse and equals ``len(books)``.
    """
    player: str = Field(..., description="Player name as stored on the snapshot")
    position: Optional[str] = Field(
        default=None,
        description=(
            "Pos on the player's most recent NBA game log. Null when the "
            "name is not in the log or Pos is blank."
        ),
    )
    team_code: Optional[str] = Field(
        default=None,
        description=(
            "Canonical NBA team code from that same most recent game log "
            "(for example GSW). Null when the log has no team."
        ),
    )
    line: float = Field(..., description="Modal consensus of one line per bookmaker")
    bookmakers_count: int = Field(..., description="Distinct bookmakers. Equals the length of books")
    books: List[BulkPropBook] = Field(default_factory=list, description="One entry per bookmaker")


class BulkPropMarket(BaseModel):
    """Every player with a stored line in one market."""
    market: str = Field(..., description="Market key, for example player_points")
    players: List[BulkPropPlayer] = Field(default_factory=list, description="Players in this market, sorted by name")


class BulkPropsResponse(BaseModel):
    """
    ``GET /api/nba/events/{event_id}/props``.

    Read from the latest ``odds_line_snapshots`` capture. ``source`` is
    always ``"snapshot"``. When that capture does not exist, ``markets``
    is empty and both ``snapshot_at`` and ``data_age_seconds`` are null.
    That response is HTTP 200. A malformed ``event_id`` is HTTP 404 and
    does not use this body.
    """
    event_id: str = Field(..., description="Event id from the path")
    snapshot_at: Optional[datetime] = Field(
        default=None,
        description="When the newest stored capture was written (ISO 8601). Null when no snapshot exists",
    )
    data_age_seconds: Optional[int] = Field(
        default=None,
        description="Whole seconds since snapshot_at. Null when no snapshot exists. Recomputed on a cache hit",
    )
    source: Literal["snapshot"] = Field(
        default="snapshot",
        description="Always snapshot. This route does not call the Odds API",
    )
    markets: List[BulkPropMarket] = Field(
        default_factory=list,
        description="Markets in the newest snapshot, in SNAPSHOT_MARKETS order. Empty when nothing is stored or nothing matches the filter",
    )


class PropRead(BaseModel):
    """One posted player in one market, with the side we would publish.

    ``side`` is the historical side when the game log has a rate, including
    rates below the Lean floor. It is the no-vig favorite when the log has
    no rate. It is null for a binary market and when neither source can
    choose. ``tier`` is ``read_tier(combined_probability)``. A null
    ``combined_probability`` (no two-sided price at the modal line, or Out
    or Doubtful) has a null tier. The player is still present.
    """

    player: str = Field(..., description="Player name as stored on the snapshot")
    market: str = Field(..., description="Market key, for example player_points")
    line: float = Field(..., description="Modal consensus of one line per bookmaker. Same rule as bulk props")
    side: Optional[Literal["over", "under"]] = Field(
        default=None,
        description="Chosen side. Null for a binary market and when no side can be chosen",
    )
    combined_probability: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Calibrated probability of side, from the existing signal model. "
            "Null when the market price is missing or the player is Out or Doubtful"
        ),
    )
    tier: Optional[Literal["Strong play", "Playable", "Lean"]] = Field(
        default=None,
        description=(
            "read_tier(combined_probability). Null below 0.56, and null when "
            "combined_probability is missing or not finite"
        ),
    )
    signals: Optional[List[PickSignal]] = Field(
        default=None,
        description="Five signals for side. Null when side is null",
    )


class EventReadsResponse(BaseModel):
    """``GET /api/nba/events/{event_id}/reads``.

    One row per posted player in the latest snapshot, for the requested
    market or for every stored market. ``source`` is always ``"snapshot"``.
    A well-formed event with no capture is HTTP 200, ``reads`` empty, and
    ``snapshot_at`` null. This route does not call The Odds API.
    """

    event_id: str = Field(..., description="Event id from the path")
    market: Optional[str] = Field(
        default=None,
        description="The market query when the client sent one. Null when every stored market is included",
    )
    snapshot_at: Optional[datetime] = Field(
        default=None,
        description="When the newest stored capture was written. Null when no snapshot exists",
    )
    source: Literal["snapshot"] = Field(
        default="snapshot",
        description="Always snapshot. This route does not call the Odds API",
    )
    reads: List[PropRead] = Field(
        default_factory=list,
        description="One read per posted player. Empty when nothing is stored or the market has no rows",
    )
