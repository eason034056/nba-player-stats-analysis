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
layers — Pydantic request boundary, agent-chat service event_context, and
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
| `scripts/agents/agents.py` | `planner_node` reads `event_context.get("league") or DEFAULT_LEAGUE` and emits it as `state["league"]`. Audit-log entry includes `_league` for replay/debug. Import of `DEFAULT_LEAGUE`, `LeagueId` from `state` module. |
| `backend/app/models/agent_chat.py` | + `AgentLeague = Literal["nba", "wnba"]`. `AgentPageContext` gains optional `league: AgentLeague \| None = None`. |
| `backend/app/services/agent_chat.py` | `_build_event_context` copies `page.league` (or `"nba"`) into the event_context dict that the graph runner receives. |
| `backend/tests/test_agent_planner.py` | + 3 tests: planner defaults `state.league` to NBA when omitted; threads `"wnba"` when present in event_context; records league in the audit log. |
| `backend/tests/test_agent_chat.py` | + 2 tests: `_build_event_context` defaults to NBA when `page.league` is omitted; propagates `"wnba"` when set. |

## Why (architectural decisions)

### 1. Single source of truth at three boundaries

The `league` value crosses three trust boundaries: HTTP request →
Pydantic model, Pydantic model → service → graph state, graph state →
downstream node logic. I validated at the **outermost** boundary
(`AgentPageContext.league: AgentLeague | None`) so anything reaching the
service or graph is already a known literal. Inside the graph, the value
is trusted and only defaulted (not re-validated). This is the right side
of the CLAUDE.md guidance ("Only validate at system boundaries").

### 2. `Literal` type instead of an Enum

`Literal["nba", "wnba"]` gives the same type-checker / IDE / Pydantic
behaviour as `enum.Enum` but stays string-shaped through JSON, the graph
state dict, the audit log, and Redis keys. The graph state is a
`TypedDict`, not a Pydantic model, so an Enum would force coercion at
every read site. Using `Literal` keeps the value a plain string everywhere.

### 3. Default-to-NBA on the **read side**, not the write side

`event_context.get("league") or DEFAULT_LEAGUE` keeps the default in the
planner. I considered putting the default in `_build_event_context` (and
in fact did — that's where `(page.league if page and page.league else "nba")`
already runs), but adding a second default in the planner protects against
future internal callers that bypass the service (e.g. CLI invocations
through `scripts/agents/cli.py`). Two defenses are cheap; a `KeyError` in
production is not.

### 4. Audit-log includes `_league` rather than overwriting the `parsed_query`

The planner already audits `parsed["output"]`. I added `_league` (leading
underscore = "synthetic, not from LLM") into a merged copy rather than
adding `league` to `parsed_query` itself, so the rest of the graph that
reads `state.parsed_query` doesn't see a phantom field that the LLM didn't
emit. The audit-log line gets full replay information; the live graph
state stays clean.

### 5. Explicitly **not** routing tools or other nodes in 5a

The other five nodes (`historical_agent`, `projection_agent`,
`market_agent`, `critic`, `synthesizer`) still ignore `state["league"]`
in this slice — they continue to behave exactly as before. The first
real consumer is 5b. Splitting it this way means Lens's review surface
in 5a is six small files and 157 lines instead of "all of scripts/agents
+ all of tools/", which is what the owner explicitly requested when
splitting SPO-36.

## Tests

```
backend/tests/test_agent_planner.py  4 passed
backend/tests/test_agent_chat.py     13 passed (2 new), 1 failed (pre-existing)
```

The single failure (`test_agent_chat_endpoint_validates_action_and_uses_service`)
also fails on `origin/dev` without my changes — it depends on a live
PostgreSQL instance which is not running in this sandbox
(`Connect call failed ('127.0.0.1', 5432)`). Not introduced by this slice.

Re-verification command for Sentinel:

```bash
git stash
git checkout origin/dev -- backend/tests/test_agent_chat.py backend/app/models/agent_chat.py backend/app/services/agent_chat.py
.venv/bin/python -m pytest backend/tests/test_agent_chat.py::test_agent_chat_endpoint_validates_action_and_uses_service
# observe same failure → confirms pre-existing
git checkout HEAD -- ...
git stash pop
```

### What 5a does **not** test (deferred)

- NBA `pytest backend/tests/test_agent_chat.py -v` golden run — done in 5c
  per SPO-36 acceptance criteria (Gate 3).
- WNBA end-to-end smoke ("A'ja Wilson points avg") — needs 5b/5c tool routing.

## Follow-ups for 5b (next ticket)

- Thread `state["league"]` into the five remaining nodes:
  - `historical_agent_node` → pass `league=` to tool calls in 5c, but 5b
    only needs the value visible in the node for prompt construction.
  - `projection_agent_node` — projection layer is mostly NBA-only today;
    when WNBA path can't find a projection, return `availability.projection=False`
    rather than failing.
  - `market_agent_node` — Phase 2 (SPO-33) already split `sport_key` plumbing
    by league inside the gateway; 5b/5c just need to pass `league` down.
  - `critic_node` — system prompt must drop NBA-specific framing
    (game-length expectations, 82-game schedule). WNBA games are 40 min
    over 4×10-min quarters; regular season is 40 games.
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
- Anti-hallucination policy: not directly hit in 5a (no new external API)
- Domain lenses: not directly hit in 5a (no probability/EV math touched)
