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
    "not_enough_market_data",
    "injury_context_missing",
    "insufficient_context",
    "error",
]

AgentDecision = Literal["over", "under", "avoid"]
AgentRecommendation = Literal["keep", "recheck", "remove"]


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
    expected_value_pct: float = Field(..., description="Expected value percentage")
    summary: str = Field(..., description="Verdict summary")
    reasons: list[str] = Field(default_factory=list, description="Primary reasons")
    risk_factors: list[str] = Field(default_factory=list, description="Risk factors")
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
