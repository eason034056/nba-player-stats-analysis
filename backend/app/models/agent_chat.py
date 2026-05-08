from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AgentAction = Literal[
    "general",
    "analyze_pick",
    "review_slip",
    "risk_check",
    "line_movement",
    "plain_english",
    "review_board",
]

AgentStatus = Literal[
    "ok",
    "line_moved",
    "not_enough_market_data",
    "injury_context_missing",
    "insufficient_context",
    "error",
]

AgentDecision = Literal["over", "under", "avoid"]
AgentRecommendation = Literal["keep", "recheck", "remove"]
LineupStatus = Literal["projected", "partial", "unavailable"]
LineupConfidence = Literal["high", "medium", "low"]
AgentVerdictEvidenceTone = Literal["positive", "neutral", "caution", "muted"]
AgentVerdictBreakdownTone = Literal["support", "caution", "neutral", "unavailable"]
AgentVerdictBreakdownSectionKey = Literal[
    "historical",
    "trend_role",
    "shooting",
    "variance",
    "schedule",
    "own_team_injuries",
    "lineup",
    "market",
    "projection",
]


class AgentPageContext(BaseModel):
    route: str = Field(default="/", description="Current frontend route")
    date: str | None = Field(default=None, description="Current board date")
    selected_teams: list[str] = Field(
        default_factory=list,
        description="Currently selected teams on the board",
    )


class AgentPickContext(BaseModel):
    player_name: str = Field(..., description="Player name")
    player_team: str = Field(default="", description="Player team")
    event_id: str = Field(..., description="Event identifier")
    home_team: str = Field(..., description="Home team")
    away_team: str = Field(..., description="Away team")
    commence_time: str = Field(..., description="Game start time")
    metric: str = Field(..., description="Prop metric")
    threshold: float = Field(..., description="Market threshold")
    direction: str = Field(..., description="Current pick direction")
    probability: float = Field(..., description="Current historical probability")
    n_games: int = Field(..., description="Sample size")
    projected_value: float | None = Field(default=None, description="Projection value")
    projected_minutes: float | None = Field(default=None, description="Projected minutes")
    edge: float | None = Field(default=None, description="Projection edge")


class AgentContext(BaseModel):
    page: AgentPageContext | None = Field(default=None, description="Page context")
    selected_pick: AgentPickContext | None = Field(
        default=None,
        description="Selected pick context",
    )
    visible_picks: list[AgentPickContext] = Field(
        default_factory=list,
        description="Visible picks on the current board",
    )
    bet_slip: list[AgentPickContext] = Field(
        default_factory=list,
        description="Current bet slip contents",
    )


class AgentQuickAction(BaseModel):
    action: AgentAction = Field(..., description="Quick action key")
    label: str = Field(..., description="Button label")
    prompt: str = Field(..., description="Prompt to submit for the action")


class AgentLineupTeamContext(BaseModel):
    team: str = Field(..., description="Team code")
    status: LineupStatus = Field(..., description="Current lineup state")
    confidence: LineupConfidence | None = Field(default=None, description="Consensus confidence")
    source_disagreement: bool = Field(default=False, description="Whether sources disagree")
    updated_at: str | None = Field(default=None, description="Latest lineup update timestamp")
    player_is_projected_starter: bool | None = Field(
        default=None,
        description="Whether the selected player is in the projected starters",
    )
    starters: list[str] = Field(default_factory=list, description="Projected starters")


class AgentLineupContext(BaseModel):
    summary: str = Field(default="", description="Human-readable lineup summary")
    freshness_risk: bool = Field(default=False, description="Whether lineup data is stale")
    player_team: AgentLineupTeamContext | None = Field(
        default=None,
        description="Selected player's team lineup context",
    )
    opponent_team: AgentLineupTeamContext | None = Field(
        default=None,
        description="Opponent lineup context",
    )


class AgentVerdictEvidenceStat(BaseModel):
    label: str = Field(..., description="Short stat label")
    value: str = Field(..., description="Formatted stat value")
    tone: AgentVerdictEvidenceTone | None = Field(
        default=None,
        description="positive | neutral | caution | muted",
    )


class AgentVerdictBreakdownSection(BaseModel):
    key: AgentVerdictBreakdownSectionKey = Field(..., description="Breakdown section key")
    label: str = Field(..., description="Human-readable section label")
    tone: AgentVerdictBreakdownTone = Field(
        ...,
        description="support | caution | neutral | unavailable",
    )
    reliability: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Section reliability score when available",
    )
    signal_note: str = Field(..., description="Primary user-facing signal note")
    risk_note: str | None = Field(default=None, description="Material caution for this section")
    stats: list[AgentVerdictEvidenceStat] = Field(
        default_factory=list,
        description="Compact evidence stats for the section",
    )


class AgentVerdictBreakdown(BaseModel):
    sections: list[AgentVerdictBreakdownSection] = Field(
        default_factory=list,
        description="Ordered breakdown sections for the verdict",
    )


class AgentVerdictCard(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    subject: str = Field(..., description="Human-readable subject label")
    decision: AgentDecision = Field(..., description="Agent decision")
    confidence: float = Field(..., ge=0, le=1, description="Confidence score")
    model_probability: float = Field(..., ge=0, le=1, description="Modeled probability")
    market_implied_probability: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Market implied probability for the queried side",
    )
    expected_value_pct: float | None = Field(
        default=None,
        description="Expected value percentage",
    )
    market_pricing_mode: str = Field(
        default="unavailable",
        description="How the live market priced the queried pick",
    )
    queried_line: float | None = Field(
        default=None,
        description="Original line requested for pricing",
    )
    best_line: float | None = Field(
        default=None,
        description="Best currently available live line",
    )
    available_lines: list[float] = Field(
        default_factory=list,
        description="Distinct live lines currently available",
    )
    best_book: str | None = Field(
        default=None,
        description="Best bookmaker for the live line",
    )
    best_odds: int | None = Field(
        default=None,
        description="Best available American odds",
    )
    summary: str = Field(..., description="Verdict summary")
    breakdown: AgentVerdictBreakdown | None = Field(
        default=None,
        description="Structured reasoning breakdown",
    )
    reasons: list[str] = Field(default_factory=list, description="Primary reasons")
    risk_factors: list[str] = Field(default_factory=list, description="Risk factors")
    lineup_context: AgentLineupContext | None = Field(
        default=None,
        description="Projected lineup context for the matchup",
    )
    recommendation: AgentRecommendation | None = Field(
        default=None,
        description="Slip review recommendation",
    )


class AgentSlipReview(BaseModel):
    items: list[AgentVerdictCard] = Field(
        default_factory=list,
        description="Per-leg verdicts",
    )
    summary: str = Field(..., description="Slip-level summary")
    keep_count: int = Field(default=0, ge=0, description="Count of keep recommendations")
    recheck_count: int = Field(
        default=0,
        ge=0,
        description="Count of recheck recommendations",
    )
    remove_count: int = Field(
        default=0,
        ge=0,
        description="Count of remove recommendations",
    )


class AgentChatRequest(BaseModel):
    thread: str = Field(default="", description="Client-managed thread identifier")
    message: str = Field(default="", description="User message")
    action: AgentAction = Field(default="general", description="Requested action")
    context: AgentContext | None = Field(default=None, description="UI context payload")


class AgentChatResponse(BaseModel):
    thread: str = Field(default="", description="Client-managed thread identifier")
    action: AgentAction = Field(..., description="Resolved action")
    status: AgentStatus = Field(..., description="Response status")
    reply: str = Field(..., description="Assistant reply text")
    verdict: AgentVerdictCard | None = Field(
        default=None,
        description="Single-pick verdict card",
    )
    slip_review: AgentSlipReview | None = Field(
        default=None,
        description="Slip review payload",
    )
    quick_actions: list[AgentQuickAction] = Field(
        default_factory=list,
        description="Suggested follow-up actions",
    )
