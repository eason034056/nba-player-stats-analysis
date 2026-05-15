# SPO-48 — WNBA Phase 5a: state + planner league-awareness

- **Ticket:** SPO-48 — first sub-slice of SPO-36 (WNBA Phase 5)
- **Parent ticket:** SPO-36 (`[Forge] WNBA Phase 5 — agent LangGraph league-awareness`)
- **Parent epic:** SPO-29 (`wnba-rollout`)
- **Forge:** `d5d67ab1-…`
- **Implementation date:** 2026-05-14
- **Branch:** `feature/SPO-48-state-planner-league` (off `origin/dev`)

## Summary

First and smallest slice of the SPO-36 owner-mandated split. Adds a single
`league: Literal["nba", "wnba"]` discriminator to the agent graph at three
layers — Pydantic request boundary, agent-chat service `event_context`, and
LangGraph `BettingState` — and makes the planner node populate
`state["league"]` from `event_context["league"]`. Every read site defaults
to NBA so existing callers stay on the NBA path with zero behavioural change.

**Scope is intentionally narrow.** No tool routing, no other node changes,
no new endpoint. 5b will teach the remaining five nodes to read
`state["league"]`; 5c will route the tool layer and add
`POST /api/wnba/agent/chat`.

## Changes

| File | Change |
|---|---|
| `scripts/agents/state.py` | + `LeagueId = Literal["nba", "wnba"]`, `DEFAULT_LEAGUE = "nba"`. `BettingState` gains a `league: LeagueId` key. |
| `scripts/agents/agents.py` | `planner_node` reads `event_context.get("league") or DEFAULT_LEAGUE` and emits it as `state["league"]`. Adds `from state import DEFAULT_LEAGUE, LeagueId`. |
| `backend/app/models/agent_chat.py` | + `AgentLeague = Literal["nba", "wnba"]`. `AgentPageContext` gains optional `league: AgentLeague \| None = None`. |
| `backend/app/services/agent_chat.py` | `_build_event_context` copies `page.league` (or `"nba"`) into the event_context dict that the graph runner receives. |
| `backend/tests/test_agent_planner.py` | + 2 tests: planner defaults `state.league` to NBA when `event_context.league` is omitted; threads `"wnba"` through when it is set. |
| `backend/tests/test_agent_chat.py` | + 2 tests: `_build_event_context` defaults `league` to `"nba"` when `page.league` is omitted; propagates `"wnba"` when present. |

Total diff (excluding this task summary): **6 files, +130 / -1 lines**.

## Why (architectural decisions)

### 1. Validate at the boundary, default in the planner

The `league` value crosses three trust boundaries: HTTP request → Pydantic
model, model → service → graph state, graph state → downstream nodes. I
validated at the **outermost** boundary (`AgentPageContext.league: AgentLeague
| None`) so anything reaching the service or graph is already a known literal.
Inside the graph, the value is trusted and only defaulted (not re-validated).
This matches `CLAUDE.md`: "Only validate at system boundaries."

### 2. `Literal` type instead of an `Enum`

`Literal["nba", "wnba"]` gives the same type-checker / IDE / Pydantic
behaviour as `enum.Enum` but stays string-shaped through JSON, the graph
state dict, the audit log, and Redis keys. `BettingState` is a `TypedDict`,
not a Pydantic model, so an `Enum` would force coercion at every read site.
Using `Literal` keeps the value a plain string everywhere.

### 3. Default-to-NBA on **both** the service write side and the planner read side

`_build_event_context` already defaults `league` to `"nba"` when `page.league`
is missing. The planner also re-defaults via
`event_context.get("league") or DEFAULT_LEAGUE`. Two cheap defenses guard
against internal callers that bypass the service (e.g. `scripts/agents/cli.py`,
backtest harnesses) and feed the graph an `event_context` that omits the key.

### 4. Explicitly **not** touching the other five nodes in 5a

The five non-planner nodes (`historical_agent`, `projection_agent`,
`market_agent`, `critic`, `synthesizer`) continue to ignore
`state["league"]` in this slice — they behave exactly as before. The first
real consumer is 5b. Splitting it this way keeps Lens's review surface in
5a at five small files / 65 lines instead of "all of scripts/agents + all
of tools/", which is what the owner explicitly asked for when splitting
SPO-36.

### 5. Why no audit-log change

I considered adding a synthetic `_league` field to the planner's audit-log
entry for replay/debug. Rejected it: the value is already on the top-level
returned state (`state["league"]`), which is what gets persisted and
replayed. Adding it twice creates duplicate state that can drift. If 5b
needs richer audit, that's the right time to add it.

## Tests

```
backend/tests/test_agent_planner.py  3 passed (2 new)
backend/tests/test_agent_chat.py     13 passed (2 new), 1 failed (pre-existing env flake)
backend/tests/test_daily_analysis_league.py + test_daily_analysis.py
 + test_spo16_integration.py + test_role_conditioned_scoring.py
                                     85 passed, 1 skipped
```

The single failure (`test_agent_chat_endpoint_validates_action_and_uses_service`)
also fails on `origin/dev` without this branch's changes — it relies on the
slowapi rate-limiter, which raises `AttributeError: 'ConnectionError' object
has no attribute 'detail'` when Redis is unreachable in this sandbox. Not
introduced by this slice.

Sentinel re-verification:

```bash
git stash
.venv/bin/python -m pytest backend/tests/test_agent_chat.py::test_agent_chat_endpoint_validates_action_and_uses_service
# observe same failure → pre-existing env flake
git stash pop
```

### What 5a does **not** test (deferred)

- Full NBA `pytest backend/tests/test_agent_chat.py` golden run — done in 5c
  per SPO-36 Gate 3 acceptance.
- WNBA end-to-end smoke ("A'ja Wilson points avg") — needs 5b/5c tool routing.

## Follow-ups for 5b (next ticket)

- Thread `state["league"]` into the five remaining nodes:
  - `historical_agent_node` — pass `league=` into tool calls (actual routing in 5c).
  - `projection_agent_node` — return `availability.projection=False` when the
    WNBA path has no projection rather than failing.
  - `market_agent_node` — SPO-33 already split `sport_key` plumbing by league
    inside the gateway; 5b just needs to pass `league` down.
  - `critic_node` — system prompt must drop NBA-specific framing (82-game
    schedule, 48-minute games).
  - `synthesizer_node` — explanation language ("over an 82-game season")
    is NBA-coded; needs league-aware copy.

## Follow-ups for 5c

- Add `league` parameter to every function in `scripts/agents/tools/`.
- Add `POST /api/wnba/agent/chat` endpoint defaulting `page.league="wnba"`.
- Run the NBA regression gate (SPO-36 Gate 3) before closing 5c.

## Acceptance check against SPO-36 (this slice only)

- [x] `state.py` has `league` field (typed, defaulted via `DEFAULT_LEAGUE`).
- [x] Planner reads `event_context["league"]` and emits `state["league"]`.
- [x] `AgentPageContext` accepts optional `league` literal.
- [x] `_build_event_context` defaults `league` to `"nba"`.
- [x] Unit tests cover both NBA-default and WNBA paths.
- [ ] (deferred to 5b) other five nodes read `state["league"]`.
- [ ] (deferred to 5c) tools accept `league`.
- [ ] (deferred to 5c) `POST /api/wnba/agent/chat` endpoint.
- [ ] (deferred to 5c) NBA regression test gate.

## Reference

- Parent: SPO-36 · Orchestrator: SPO-29
- Blockers (DONE): SPO-32 · SPO-33 · SPO-34
- Anti-hallucination policy: not directly hit in 5a (no new external API).
- Domain lenses: not directly hit in 5a (no probability/EV math touched).
