# SPO-52 — WNBA Phase 5b: five-nodes league-awareness

- **Ticket:** SPO-52 — second sub-slice of SPO-36 (WNBA Phase 5)
- **Parent ticket:** SPO-36 (`[Forge] WNBA Phase 5 — agent LangGraph league-awareness`)
- **Parent epic:** SPO-29 (`wnba-rollout`)
- **Predecessor:** SPO-48 (5a — `state.league` + planner) merged in PR #15 @ `2cb80e8`.
- **Forge:** `d5d67ab1-…`
- **Implementation date:** 2026-05-15
- **Branch:** `feature/SPO-52-five-nodes-league` (off `origin/dev` @ `2cb80e8`)

## Summary

Second slice of the SPO-36 owner-mandated split. With 5a merged, the planner
already populates `state["league"]` from `event_context["league"]`. 5b
teaches the next five graph nodes — `historical_agent_node`,
`projection_agent_node`, `market_agent_node`, `critic_node`,
`synthesizer_node` — to **read** that value, propagate it in returned
partial state, stamp it into the audit_log, and (for the two LLM-driven
nodes) select a league-aware system prompt.

**Scope is intentionally narrow.** No tool-signature changes
(`scripts/agents/tools/`), no new endpoint, no NBA regression gate against
`backend/tests/test_agent_chat.py` — those are 5c.

## Changes

| File | Change |
|---|---|
| `scripts/agents/agents.py` | + `_get_league(state)` helper (fallback to `DEFAULT_LEAGUE`). + `_WNBA_LEAGUE_CONTEXT` block (40-min games, May–October cadence, 11–12-player rosters). + `_build_critic_system(league)` / `_build_synthesizer_system(league)` builders — NBA returns the legacy constant by reference (byte-identical); WNBA swaps the first sentence and inserts the context block right after it. Five nodes (`historical_agent`, `projection_agent`, `market_agent`, `critic`, `synthesizer`) now read `state.league`, return it, and stamp it into their `audit_log` entry. |
| `scripts/agents/tests/conftest.py` | New: inserts `scripts/agents/` onto `sys.path` so test files can `import agents as agent_module` (mirrors the convention already used by `backend/tests/test_agent_planner.py`). |
| `scripts/agents/tests/test_phase5b_league.py` | New: 14 unit tests covering the four prompt-builder paths (NBA byte-identical × 2 + WNBA context-markers × 2) and league threading through each of the five nodes for both NBA-default and WNBA-explicit paths (10 node tests, 2 of which also assert the LLM saw the right prompt). |

Total diff (excluding this task summary): **`agents.py` +89 / −7 lines** + **3 new test files (conftest + test, with `__init__.py` deliberately omitted)**.

## Why (architectural decisions)

### 1. NBA returns the legacy constant **by reference**, not by re-templating

The SPO-52 acceptance criterion is "NBA invocation contains 'NBA' and is
byte-identical to the pre-5b prompt." The strongest guarantee against
drift is to literally return the pre-5b `_CRITIC_SYSTEM` /
`_SYNTH_SYSTEM` Python objects on the NBA branch. The unit test asserts
exactly that with `==`, which short-circuits on identity. Any future
formatting change to the NBA prompt now has to flow through the same
constant, removing the "parallel-fork" risk where a WNBA template
silently diverges from the NBA one.

### 2. `str.replace(_NBA_FIRST_LINE, …, 1)`, not f-string templating

I considered an f-string template (`"You are the Critic of {phrase}..."`)
with `phrase = "an NBA"` for NBA and `"a WNBA"` for WNBA, plus an
empty-string context insertion to keep NBA byte-identical. That works
but adds a templating surface to every future prompt edit. The
`replace(_NBA_FIRST_LINE, _WNBA_HEADER, 1)` approach is shorter, keeps
the prompt body as a single readable string, and the `, 1)` limit
guarantees we only swap the opening sentence even if "NBA" appears
elsewhere inside the body. Both approaches were considered; the explicit
swap won on auditability.

### 3. Article grammar matters: "an NBA" vs "a WNBA"

"An" precedes vowel **sounds**; "NBA" begins with the sound /ɛn/, so "an
NBA" is correct. "WNBA" begins with /ˈdʌb.əl.juː/ (a consonant sound), so
"a WNBA" is the right article. Encoding the article inside the first-line
constants prevents future contributors from running a naive
"NBA"→"WNBA" find-and-replace that would otherwise produce
ungrammatical "an WNBA".

### 4. Context block lives next to the prompts, not in `state.py`

The WNBA context block (`_WNBA_LEAGUE_CONTEXT`) is consumed only by the
critic and synthesizer prompts. Per CLAUDE.md's domain-organisation rule
("Prompt template lives in `agents.py` next to the existing strings — no
new module"), the block stays in `agents.py`. If a third LLM-driven node
appears later that needs the same context, that is the right time to
factor it out — not before.

### 5. `_get_league(state)` helper — single fallback site

Every node uses `league = _get_league(state)` rather than open-coding
`state.get("league") or DEFAULT_LEAGUE` six times. One source of truth
for the "what counts as a missing league?" rule. If 5c discovers it
needs a stricter "raise on unset" mode for a specific node, the change
touches one function. The helper is `_`-prefixed because it's internal
to `agents.py` and not part of the public planner/state surface.

### 6. NO `scripts/agents/tests/__init__.py`

Initially I added an empty `__init__.py` so pytest would treat the
directory as a package, matching `backend/tests/`. That made pytest see
`scripts/agents/tests/` as a *sub-package* of `scripts/agents/` (whose
own `__init__.py` has existed since the LangGraph rewrite). Result: the
test's `import agents as agent_module` resolved to the empty package
`scripts/agents/__init__.py`, not the module `scripts/agents/agents.py`.
Removing the test-dir `__init__.py` makes `tests/` a flat rootdir under
pytest's collection, and the conftest's `sys.path` injection wins. This
matches the import convention used everywhere else in the repo (cli.py,
backend tests). Documenting here so 5c does not re-add the file by reflex.

## Tests

```
scripts/agents/tests/test_phase5b_league.py        14 passed (new)
backend/tests/test_agent_planner.py                 3 passed (5a regression)
```

Run from project root:

```bash
.venv/bin/python -m pytest scripts/agents/tests/test_phase5b_league.py \
  backend/tests/test_agent_planner.py -v
```

### What 5b does **not** test (deferred)

- `pytest backend/tests/test_agent_chat.py` end-to-end NBA golden run —
  done in 5c per SPO-36 Gate 3 acceptance.
- WNBA end-to-end smoke ("A'ja Wilson points avg") — needs 5c tool
  routing + the new `POST /api/wnba/agent/chat` endpoint.
- Pre-existing `test_agent_chat_endpoint_validates_action_and_uses_service`
  flake (slowapi/Redis env issue) — documented in SPO-48's task summary,
  unchanged here.

## Anti-hallucination & domain lenses (per CLAUDE.md)

- **Anti-hallucination policy** — not engaged. 5b introduces no new
  external API surface; it only refactors prompts and threads an
  existing state field.
- **Domain lenses** — no probability / EV / Kelly math touched. The
  league context block is a prompt-engineering signal, not a math
  signal; the deterministic `scoring.py` path is untouched and will be
  the right surface for any future league-specific math (e.g. WNBA
  vig-free probability calibration).

## Follow-ups for 5c (next ticket)

- Add `league` parameter to every function in `scripts/agents/tools/`
  (signature change — Lens / Sentinel must run the full backend test
  suite to catch any caller drift).
- Add `POST /api/wnba/agent/chat` endpoint defaulting `page.league="wnba"`
  in `_build_event_context`.
- Run the NBA regression gate (`backend/tests/test_agent_chat.py`) and
  the WNBA end-to-end smoke before closing 5c — the SPO-36 Gate 3
  acceptance contract.

## Acceptance check against SPO-52

- [x] All 5 nodes (`historical_agent`, `projection_agent`,
  `market_agent`, `critic`, `synthesizer`) read `state.league` and emit
  it in their returned partial state.
- [x] `_CRITIC_SYSTEM` and `_SYNTH_SYSTEM` are league-templated via
  `_build_critic_system(league)` / `_build_synthesizer_system(league)`;
  WNBA invocation contains "WNBA" + the 40-min / May–October /
  11–12-player context, NBA invocation is byte-identical to the pre-5b
  prompt (asserted by `_build_critic_system("nba") == _CRITIC_SYSTEM`).
- [x] New unit tests in `scripts/agents/tests/` cover both leagues and
  the NBA-default fallback for every node.
- [x] Existing planner tests still pass (5a regression).
- [x] Task summary at `docs/task-summaries/SPO-52-five-nodes-league.md`
  (this file).

## Reference

- Parent: SPO-36 · Orchestrator: SPO-29
- Predecessor: SPO-48 (5a, PR #15 @ `2cb80e8`)
- Successor: 5c (created after this PR merges)
