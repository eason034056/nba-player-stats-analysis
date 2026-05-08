---
name: NBA Multi-Agent Betting Advisor
overview: Build a LangGraph betting advisor with 6 LLM agents, 1 deterministic scoring layer, and 20+ tool functions that analyze NBA player props from 7 analytical dimensions. The first strong production layer should be built from Existing CSV + NBA Stats + Official Injury Report + The Odds API; Dimensions 1-5 and 7 are active from those sources today, while Dimension 6 (projection + matchup) remains an explicit stub because the current SportsDataIO feed is dummy data and must not influence recommendations.
todos:
  - id: csv-enhance
    content: Enhance csv_player_history.py load_csv() to parse all 28 CSV columns and preserve metadata needed for structured signals (Season, W/L, Pos, shooting splits, FIC, etc.)
    status: pending
  - id: tools-historical
    content: "Create scripts/agents/tools/historical.py with structured tools for Dims 1-5 using Existing CSV + NBA Stats + Official Injury Report: base stats, minutes opportunity, usage/touches, shooting mix, lineup context, variance, schedule, and injury-aware teammate effects with reliability + sample-size outputs"
    status: pending
  - id: tools-projection
    content: Create scripts/agents/tools/projection.py with 4 tool interfaces for Dimension 6 that always return unavailable until SportsDataIO is replaced with a real data source.
    status: pending
  - id: tools-market
    content: Create scripts/agents/tools/market.py with pricing tools for Dimension 7 (current market, line movement, best price, bookmaker spread / disagreement)
    status: pending
  - id: scoring-layer
    content: Create scoring.py to aggregate structured signals deterministically, apply shrinkage / caps, avoid double-counting correlated features, and output calibrated probability + EV fields.
    status: pending
  - id: state-agents
    content: Create state.py (structured BettingState) and agents.py (6 LLM agents with prompts focused on planning, critique, and explanation rather than raw scoring)
    status: pending
  - id: graph
    content: "Create graph.py with LangGraph StateGraph: planner -> parallel analysis agents -> deterministic scoring node -> critic -> synthesizer -> conditional loop, plus Mermaid visualization export"
    status: pending
  - id: cli
    content: Create cli.py CLI frontend with input loop, structured scorecard output, and explicit unavailable-dimension handling
    status: pending
  - id: validation
    content: Run 5+ prompt demos plus offline backtest / calibration checks, then generate sample_outputs.md and backtest_report.md
    status: pending
isProject: false
---

# NBA Multi-Agent Betting Advisor (Assignment 4)

## Problem: Current Analysis Is Still Too Shallow

The current `daily_analysis.py` is still anchored on historical hit rate plus some optional projection fields. That is not enough for a serious player-prop workflow:

- the CSV has 28 columns but `csv_player_history.py` currently parses only a small subset
- recent role changes, shooting context, variance, and schedule effects are mostly ignored
- market data is used as a line source, not as a pricing benchmark
- the projection API may look integrated, but **the current SportsDataIO feed is dummy data and must be treated as unavailable**

This design therefore treats projection + matchup as a **schema-stable stub**, not a live signal.

---

## Design Corrections From the Previous Version

1. Projection is not merely "weak"; it is **explicitly unusable** until the dummy feed is replaced.
2. LLMs should not invent confidence scores from prose. Scoring must come from deterministic, structured signals.
3. Market should be a benchmark for pricing and EV, not just one more vote in a 7-way debate.
4. Correlated historical signals must be capped so one hot streak does not get counted multiple times.
5. Every output must carry sample size, reliability, source, and timestamp metadata.
6. Backtesting, calibration, and ablation are required deliverables, not optional polish.

---

## Architecture: 6 Agents, 1 Deterministic Scoring Layer, 7 Dimensions

```mermaid
graph TD
    User[User Query] --> Planner[Planner Agent]
    Planner -->|"fan-out"| Stats[Historical + Opportunity Agent]
    Planner -->|"fan-out"| ProjectionStub[Projection Agent (stub only)]
    Planner -->|"fan-out"| Market[Market + Odds Agent]
    Stats --> Score[Deterministic Scoring Node]
    ProjectionStub --> Score
    Market --> Score
    Score --> Critic[Critic Agent]
    Critic --> Synthesizer[Synthesizer Agent]
    Synthesizer -->|"missing mandatory input only"| Planner
    Synthesizer -->|"ready"| FinalOutput[Final Decision]
```

Key principle:

- LLMs handle query parsing, tool planning, contradiction analysis, and final explanation.
- Deterministic code handles availability checks, sample-size gating, projection exclusion, feature aggregation, and probability / EV calculation.

This is a better split for a betting system than "LLM decides everything."

---

## The 7 Analysis Dimensions

| # | Dimension | Status in this design | Primary use | Data source |
| --- | --- | --- | --- | --- |
| 1 | Base rate + role splits | Active | prior distribution and contextual splits | Existing CSV + NBA Stats game logs / splits |
| 2 | Form / trend / role change | Active | detect recent minutes, usage, touches drift | Existing CSV + NBA Stats usage / tracking / rotations |
| 3 | Shooting efficiency | Active | explain points variance and regression risk | Existing CSV + NBA Stats shooting dashboards |
| 4 | Variance / floor-ceiling | Active | risk control, avoid noisy props | CSV distributions |
| 5 | Schedule / availability / teammate context | Active | rest, game script, injury-driven role shifts | Existing CSV + NBA Stats lineups + Official Injury Report |
| 6 | Projection + matchup | Stub only, zero weight | interface stability only | SportsDataIO dummy data |
| 7 | Market / line / price | Active and mandatory for betting advice | fair probability, line movement, EV, price shopping | The Odds API + PostgreSQL odds_line_snapshots |

Important consequence:

- The system may still expose a `projection` object in the final JSON.
- That object must remain `unavailable` and receive **zero score weight** until a real provider is connected.

---

## Phase 1 Active Data Stack

Before adding any new premium feed, the strongest practical first layer should come from these four sources:

| Source | What it gives us | Why it matters |
| --- | --- | --- |
| Existing CSV | season logs, role tags, box-score outcomes, simple lineup cache | stable base rates, splits, variance, schedule context |
| NBA Stats | minutes trends, usage, touches, play types, shooting dashboards, lineup combinations | turns "what happened" into "why it happened" |
| Official Injury Report | official statuses, timing, team availability context | converts role assumptions into today's likely rotation reality |
| The Odds API | lines, prices, consensus, movement, best book | turns analysis into pricing and EV rather than just opinions |

This stack is already enough to build a much stronger `Historical + Opportunity Agent` without using dummy projection data.

### What This Phase 1 Stack Should Model Well

- `minutes`: recent minutes trend, starter probability, closing-role stability, injury-driven minute expansion
- `usage`: touches, usage rate, shot attempts per minute, rebound chances / assist creation proxies
- `shooting_mix`: rim vs mid-range vs 3PA mix, catch-and-shoot vs pull-up tendency, FTA pressure
- `lineup`: with/without key teammates, likely starter groups, small-ball vs big lineups, who absorbs missing usage
- `market`: no-vig fair probability, best line, line movement, disagreement across books

### Data-Source-to-Feature Mapping

| Capability | Minimum source combination |
| --- | --- |
| Base hit rate and threshold distribution | Existing CSV |
| Minutes opportunity model | Existing CSV + NBA Stats + Official Injury Report |
| Usage / touches model | NBA Stats + Existing CSV |
| Shooting mix and regression risk | NBA Stats + Existing CSV |
| Lineup-conditioned on/off context | NBA Stats + Existing CSV + Official Injury Report |
| Bet pricing / EV | The Odds API |

---

## Core Output Contract

Each tool should return structured data, not just a paragraph. Every dimension-specific tool should be normalized into something like:

```json
{
  "signal": "over | under | neutral | caution | unavailable",
  "effect_size": 0.0,
  "sample_size": 0,
  "reliability": 0.0,
  "window": "last_10 | season | with_star_out | etc",
  "source": "csv | nba_stats | official_injury_report | odds_api | sportsdataio_stub",
  "as_of": "2026-03-12T18:30:00Z",
  "details": {}
}
```

The deterministic scoring node then produces the real decision payload:

```json
{
  "decision": "over | under | avoid",
  "confidence": 0.0,
  "model_probability": 0.0,
  "market_implied_probability": 0.0,
  "expected_value_pct": 0.0,
  "best_book": "DraftKings",
  "best_line": 0.0,
  "eligible_for_bet": true,
  "pass_reason": null
}
```

`confidence` should be derived from calibrated scoring rules and reliability metadata, not from an LLM making up a number.

---

## Agent Details

### Agent 1: Planner

- **Role**: parse the user query into `(player, metric, threshold, date, opponent, direction preference, comparison intent)`
- **LLM job**: understand ambiguous phrasing and decide which tools are relevant
- **Deterministic guardrails**:
  - if the user asks for a bet recommendation, market data is mandatory
  - if only projection exists for an angle, the planner must mark that path as unavailable
  - if sample size or event context is missing, route to data gathering instead of free-form reasoning

### Agent 2: Historical + Opportunity Agent

This remains the deepest active agent. It should expose structured tools for Dimensions 1-5, but the key design change is that it should no longer rely on CSV-only history. Phase 1 should deliberately combine:

- Existing CSV for base distributions and simple splits
- NBA Stats for minutes, usage, touches, shot profile, and lineup context
- Official Injury Report for same-day availability and rotation risk

That combination is enough to build a strong non-projection opportunity layer.

**Dimension 1 -- Base Distribution / Role Splits**

- `get_base_stats(player, metric, threshold, n)`
- `get_starter_bench_split(player, metric, threshold)`
- `get_opponent_history(player, metric, threshold, opponent)`
- `get_teammate_impact(player, metric, threshold, teammate, played)`

These tools should return:

- hit rate
- mean / median
- standard deviation
- sample size
- season / recent window tags
- reliability after shrinkage for small samples

**Dimension 1b -- Real-Time Injury + Teammate Chemistry**

- `get_official_injury_report(team, date)`
- `get_availability_context(player, date)`
- `auto_teammate_impact(player, metric, threshold)`

`auto_teammate_impact()` should keep the same broad idea as before, but with stronger controls:

1. Identify the player's current team and position from the most recent valid CSV row.
2. Pull likely star teammates from `star_players.json`.
3. Fetch same-day status from the **Official Injury Report** and treat it as the primary availability source.
4. Compute both `with` and `without` splits for each star teammate using CSV + NBA Stats lineup context.
5. Apply shrinkage when the `without` sample is small.
6. Lower reliability if the roster mapping looks stale or name resolution is fuzzy.

This is especially important because `star_players.json` is a manual heuristic and can drift after trades. The doc should assume freshness checks and fallback logic, not blind trust.

**Dimension 2 -- Form / Trend / Role Change**

- `get_trend_analysis(player, metric)`
- `get_streak_info(player, metric, threshold)`
- `get_minutes_role_trend(player)`
- `get_usage_touches_profile(player, date)`
- `get_opportunity_profile(player, metric, date)`

This dimension should answer:

- is the player trending because of true role change or just short-term shot variance?
- are minutes rising because of starting role / injuries?
- are touches and on-ball reps rising with the minutes, or is the player just standing on the floor more?
- does recent form deserve a bounded adjustment, or is it mostly noise?

**Dimension 3 -- Shooting Efficiency**

- `get_shooting_profile(player)`
- `get_shooting_mix_profile(player, date)`

This tool should compare recent vs season shooting rates and volume, then tag:

- hot-shooting risk
- free-throw attempt trend
- rim / mid-range / 3PA mix changes
- catch-and-shoot vs pull-up shot dependence
- volume-backed improvement vs percentage-only spike

**Dimension 4 -- Variance / Consistency**

- `get_variance_profile(player, metric)`

This should return:

- std
- coefficient of variation
- floor / median / ceiling percentiles
- threshold proximity density
- a volatility flag used for bet sizing or `avoid`

**Dimension 5 -- Schedule / Context**

- `get_schedule_context(player, date)`
- `get_game_script_splits(player, metric, threshold)`
- `get_lineup_context(player, date)`
- `get_rotation_absorption_map(player, metric, date)`

These tools should emphasize:

- back-to-back / 1-day rest vs 2+ day rest
- win/loss or blowout sensitivity
- likely starting and closing groups
- which teammates absorb minutes, shots, rebounds, or assists when a key player sits
- whether the context is stable enough to trust season-long history

### Phase 1 Tool Bundles for This Agent

The most important Phase 1 bundles should look like this:

1. `minutes_opportunity_bundle`
   Uses Existing CSV + NBA Stats + Official Injury Report.
   Returns recent minutes distribution, starter probability, closing-role confidence, and injury-driven minute upside/downside.

2. `usage_opportunity_bundle`
   Uses NBA Stats + Existing CSV.
   Returns usage trend, touches trend, shot attempts per minute, assist creation proxies, and whether the player's opportunity is truly expanding.

3. `shooting_mix_bundle`
   Uses NBA Stats + Existing CSV.
   Returns shot zones, 3PA share, rim pressure, FTA trend, and regression-risk tags.

4. `lineup_context_bundle`
   Uses Existing CSV + NBA Stats lineups + Official Injury Report.
   Returns likely active teammates, with/without rates, likely replacement roles, and reliability based on sample size plus roster freshness.

5. `historical_distribution_bundle`
   Uses Existing CSV.
   Returns threshold distribution, variance, floor/ceiling, and role-based historical splits.

### Agent 3: Projection + Matchup Agent

This agent remains in the graph only for interface stability. It is **not an active signal source**.

All 4 projection tools should exist:

- `get_full_projection(player, date)`
- `calculate_edge(projected_value, threshold)`
- `get_opponent_defense_profile(player, date)`
- `get_minutes_confidence(player, date)`

But every tool should currently return:

```json
{
  "status": "unavailable",
  "reason": "SportsDataIO data is dummy and excluded from scoring"
}
```

The deterministic scoring node must always assign zero weight to this dimension.

### Agent 4: Market + Odds Agent

Market is not just a descriptive add-on. It is the pricing layer.

Recommended tools:

- `get_current_market(player, metric, date)` -- all bookmaker lines, prices, no-vig fair probability, consensus line
- `get_line_movement(player, metric, date)` -- opening line, current line, direction, magnitude, move count
- `get_best_price(player, metric, direction, date)` -- best currently available line / odds for the intended side
- `get_bookmaker_spread(player, metric, date)` -- disagreement across books

The Market Agent should help answer:

- what probability is the market implying right now?
- is there any real edge after price, not just after line?
- is the market moving with or against the model?
- is there enough consensus to trust the available price?

If market data is unavailable, the system may still produce an informational analysis, but it should not label the output a bet recommendation.

### Deterministic Scoring Node (Non-LLM)

This is the most important addition versus the previous design.

Responsibilities:

1. Build a baseline probability from base historical stats.
2. Apply bounded adjustments from role/minutes trend, shooting, schedule, and teammate context.
3. Penalize low-reliability or stale signals.
4. Prevent double-counting correlated signals.
5. Compare the model probability to market-implied probability and best available price.
6. Output `decision_candidate`, `confidence`, `expected_value_pct`, and `eligible_for_bet`.

Expected behavior:

- a strong trend signal cannot overpower a weak base sample
- a tiny with/without split cannot dominate the model
- high volatility or unresolved injury news can force `avoid` even when raw hit rate looks good
- projection stub contributes nothing until real data exists

### Agent 5: Critic

The Critic should not recompute the whole model. Its job is to attack the scorecard.

Required checks:

- double-counting risk across trend / shooting / recent form
- small or asymmetric samples
- stale roster assumptions from `star_players.json`
- unresolved or conflicting injury reports
- high variance with weak payout edge
- market disagreement or line movement against the recommendation
- whether the deterministic score is overconfident relative to signal quality

Output:

- a short list of risk factors
- a risk grade
- explicit recommendation to downgrade to `avoid` when the scorecard is too fragile

### Agent 6: Synthesizer

The Synthesizer should explain the deterministic result, not replace it.

It receives:

- structured dimension outputs
- deterministic scorecard
- critic notes

It produces final JSON plus a concise narrative, for example:

```json
{
  "decision": "over | under | avoid",
  "confidence": 0.0,
  "model_probability": 0.0,
  "market_implied_probability": 0.0,
  "expected_value_pct": 0.0,
  "dimensions": {
    "historical": {"signal": "over", "reliability": 0.72, "detail": "..."},
    "trend_role": {"signal": "over", "reliability": 0.58, "detail": "..."},
    "shooting": {"signal": "caution", "reliability": 0.61, "detail": "..."},
    "variance": {"signal": "caution", "reliability": 0.79, "detail": "..."},
    "schedule": {"signal": "neutral", "reliability": 0.67, "detail": "..."},
    "projection": {"signal": "unavailable", "reliability": 0.0, "detail": "dummy data excluded"},
    "market": {"signal": "over", "reliability": 0.83, "detail": "..."}
  },
  "risk_factors": ["...from critic..."],
  "summary": "one paragraph conclusion"
}
```

Loop-back behavior should be narrow:

- retry only when mandatory market data or injury context is missing
- do not loop just because the LLM feels uncertain

---

## Data Quality and Reliability Rules

These rules should be explicit in the design doc because they materially affect betting quality:

1. Every signal must include `sample_size`, `as_of`, and `reliability`.
2. Every live scrape must preserve a source timestamp.
3. With/without teammate splits must use shrinkage and minimum-sample rules.
4. Team / player resolution must tolerate trades and naming mismatches.
5. The system should distinguish `analysis available` from `bet recommendation allowed`.
6. Official Injury Report should be the primary injury source for Phase 1 bet decisions.

Suggested bet gating:

- `avoid` if `sample_size < 10`
- `avoid` if injury scenario is unresolved for a key teammate
- `avoid` if no market price is available
- `avoid` if expected value is positive only because of one weak signal

---

## LangGraph State Schema

```python
class BettingState(TypedDict):
    messages: Annotated[list, add_messages]
    user_query: str
    parsed_query: dict[str, Any]
    event_context: dict[str, Any]
    availability: dict[str, bool]
    historical_signals: dict[str, dict[str, Any]]
    projection_signals: dict[str, dict[str, Any]]
    market_signals: dict[str, dict[str, Any]]
    scorecard: dict[str, Any]
    data_quality_flags: list[str]
    critic_notes: list[str]
    final_decision: dict[str, Any]
    audit_log: list[dict[str, Any]]
    iteration: int
```

This is more useful than storing large free-form strings because it supports:

- backtesting
- auditability
- prompt debugging
- deterministic post-processing

---

## File Structure

```text
scripts/agents/
  requirements_agents.txt
  state.py
  scoring.py                 # deterministic scoring + calibration-friendly outputs
  tools/
    historical.py            # Dimensions 1-5
    projection.py            # Dimension 6 stub only
    market.py                # Dimension 7 pricing tools
  agents.py                  # 6 LLM agent definitions
  graph.py                   # LangGraph graph: nodes, edges, compile
  cli.py                     # CLI frontend
  visualize.py               # Mermaid export
  evaluation/
    backtest.py              # offline replay over historical markets
    calibration_report.py    # bucketed confidence / hit-rate report
```

---

## Implementation Order

### Step 1: CSV Foundation (`backend/app/services/csv_player_history.py`)

Parse all 28 CSV columns, not just the current subset.

Must-haves:

- store `Season`, `W/L`, `Pos`, `FGM`, `FGA`, `FG%`, `3PM`, `3PA`, `3P%`, `FTM`, `FTA`, `FT%`, `STL`, `BLK`, `TOV`, `PF`, `FIC`
- preserve enough raw metadata to compute structured historical signals
- keep lineup cache and teammate lookup working

### Step 2: Historical Tools (`scripts/agents/tools/historical.py`)

Build the active signal layer for Dimensions 1-5 from the Phase 1 stack:

- Existing CSV
- NBA Stats
- Official Injury Report

Requirements:

- all tools return structured signal payloads
- all split-based tools report sample size and reliability
- `get_minutes_role_trend()`, `get_usage_touches_profile()`, `get_shooting_mix_profile()`, and `get_lineup_context()` become first-class tools because projection is unavailable
- `auto_teammate_impact()` uses Official Injury Report plus shrinkage
- the agent must be able to explain minutes, usage, shooting mix, and lineup changes without touching projection data

### Step 3: Projection Stub (`scripts/agents/tools/projection.py`)

Keep the 4 interfaces, but force them to return `unavailable`.

Reason:

- the current projection feed is dummy data
- keeping the interfaces now avoids future graph churn
- the rest of the system learns to degrade gracefully

### Step 4: Market Tools (`scripts/agents/tools/market.py`)

Build the pricing layer from The Odds API:

- current market consensus and no-vig probability
- line movement
- best price by side
- bookmaker disagreement
- keep odds snapshots when available so the same layer supports future backtests and CLV checks

### Step 5: Deterministic Scoring (`scripts/agents/scoring.py`)

Aggregate signals into:

- model probability
- confidence
- expected value
- eligibility / pass reason

This is also where signal caps, shrinkage, and duplicate-count controls belong.

### Step 6: Agents + Graph (`agents.py`, `graph.py`, `state.py`)

Build the LangGraph flow:

- `planner`
- parallel fan-out to `stats_agent`, `projection_agent`, `market_agent`
- `scoring_node`
- `critic`
- `synthesizer`
- conditional retry only for missing mandatory inputs

### Step 7: CLI Frontend (`cli.py`)

The CLI should surface both recommendation and uncertainty:

```text
> Should I bet Stephen Curry over 28.5 points today?
[Planner] Parsed: Stephen Curry, points, 28.5, 2026-03-12
[Stats Agent] Built 5 active historical/context dimensions
[Projection Agent] Unavailable: dummy SportsDataIO feed excluded
[Market Agent] Loaded 7 books, best over price -102 at FanDuel
[Scoring] Model 0.61 vs Market 0.54 -> EV +3.8%
[Critic] Risk: elevated volatility, recent FG% spike
[Synthesizer] Final decision: OVER / low-medium confidence
```

### Step 8: Validation

Do both prompt demos and offline evaluation.

Prompt demos:

1. "Should I bet Stephen Curry over 28.5 points tonight?"
2. "Is Giannis under 12.5 rebounds a good bet?"
3. "Should I bet A.J. Green over 10.5 points when Giannis is out?"
4. "Who is more consistent for assists overs, Haliburton or Brunson?"
5. "Should I bet Victor Wembanyama over 22.5 PRA?"

Offline validation:

- backtest against stored odds snapshots
- calibration buckets for confidence
- ablation study: remove trend / teammate / market features one at a time
- log when the model says `avoid` and whether that improves realized ROI

Deliverables:

- `sample_outputs.md`
- `backtest_report.md`

---

## Dependencies (`requirements_agents.txt`)

```text
langgraph>=0.2.0
langchain-openai>=0.2.0
langchain-core>=0.3.0
python-dotenv>=1.0.0
pydantic>=2.0.0
```
