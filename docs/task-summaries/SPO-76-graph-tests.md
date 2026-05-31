---
ticket: SPO-76
role: Forge
status: ready-for-review
branch: feature/SPO-76-graph-tests
parent: SPO-75
date: 2026-05-31
---

# [Forge] Add unit tests for scripts/agents/graph.py retry-guard + compile smoke

## Summary
Added `scripts/agents/tests/test_graph.py`, closing the zero-coverage gap on the
two critical surfaces of the LangGraph wiring: the `_should_retry` retry-loop
guard and the graph structure itself. Tests-only — no production logic was
changed. All 14 new tests pass without a live `OPENAI_API_KEY`; the full
`scripts/agents/tests/` suite is green (42 passed). Continues the nightly
pattern (date_utils → data_logger → scoring → graph).

## Changes
| 檔案 | 變更 |
|---|---|
| `scripts/agents/tests/test_graph.py` (NEW) | 14 tests: parametrized `_should_retry` coverage + `compile_graph()` structural smoke |
| `docs/task-summaries/SPO-76-graph-tests.md` (NEW) | this summary |

## Why (設計意圖 / 取捨)
- **`_should_retry` is the loop guard for the entire agent.** A regression here
  is bimodal: either runaway retries (re-running the whole graph per query =
  compute/$$) or silent never-retry (degraded recs when mandatory inputs are
  missing). I parametrized across `needs_retry × iteration` so each branch is a
  named row. The `iteration == 3` row is called out as the **cap boundary** —
  the single most important case, and the `iteration == 4` row additionally
  guards against an accidental `==` (instead of `<`) regression. Default-path
  rows (missing `final_decision`, missing `iteration`, empty `{}`) pin the safe
  fallbacks. Also added an explicit assertion that the return value is exactly
  the routing literal `"retry"`/`"done"` — a typo there routes to a
  non-existent node at runtime, which compilation would not catch.
- **Structural smoke captured from reality, not imagined.** Per the
  cassette-recorded-reality lens, the expected node set and edge targets were
  read off the *real* compiled graph (verification command below), not
  hand-typed. Node-set assertion uses `==` (after stripping the synthetic
  `__start__`/`__end__` sentinels) so a *stray added* node fails too, not just a
  dropped one.
- **Conditional edge asserted two ways.** On the uncompiled `StateGraph` via
  `g.branches["synthesizer"]` (proves `_should_retry` is registered as the
  branch fn), and on the compiled graph via the synthesizer's edge targets
  `{planner, __end__}` (proves both the retry and done branches are physically
  wired). Losing either direction silently breaks the loop one-way; one
  assertion alone would miss that.
- **Import style** mirrors `test_scoring.py` / `test_phase5b_league.py`:
  `conftest.py` puts `scripts/agents` on `sys.path`, so `graph` is a top-level
  module and its `agents` dependency imports cleanly without an API key (the LLM
  client is lazily constructed, not built at import time).
- **Did NOT touch `graph.py` production logic** (per ticket constraint). No
  genuine bug found in `_should_retry` — its behaviour matches the documented
  contract exactly, so nothing to report.

## Tests / Verification
- New file: `env -u OPENAI_API_KEY .venv/bin/python -m pytest scripts/agents/tests/test_graph.py -q` → **14 passed**.
- Full dir (no regressions): `... pytest scripts/agents/tests/ -q` → **42 passed**.
- Structural facts confirmed against the live graph before writing assertions:
  ```
  env -u OPENAI_API_KEY .venv/bin/python -c "import sys; sys.path.insert(0,'scripts/agents'); \
    import graph; g=graph.build_graph(); print(sorted(g.nodes), g.branches); \
    app=graph.compile_graph(); print(sorted({e.target for e in app.get_graph().edges if e.source=='synthesizer'}))"
  # -> 7 nodes, {'synthesizer': ['_should_retry']}, synthesizer targets ['__end__', 'planner']
  ```
- No external API surface touched → no fixture/exploration-script obligation.

## Follow-ups
- [ ] None required for this ticket. (Nightly pattern may next target another
      zero-coverage `scripts/agents/` module — owner/CTO to pick under SPO-75.)
