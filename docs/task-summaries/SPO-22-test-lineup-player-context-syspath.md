# SPO-22 — Fix test_lineup_player_context.py sys.path off-by-one

**Type:** code-bug fix (surfaced by [SPO-21](../task-summaries/SPO-21-test-suite-triage.md) triage)
**Branch:** `feature/SPO-22-test-lineup-player-context-syspath`
**PR:** [#2](https://github.com/eason034056/nba-player-stats-analysis/pull/2) → `dev`
**Commit:** `c9b7f63 fix(test): add PROJECT_ROOT to sys.path in test_lineup_player_context`

## Problem

`backend/tests/test_lineup_player_context.py` failed collection with `ModuleNotFoundError: No module named 'scripts'` whenever it was the first (or only) file pytest collected. The file's module-top `sys.path` setup inserted only `BACKEND_DIR` (`backend/`) — but `scripts/` lives at `PROJECT_ROOT` (`backend/..`), so `from scripts.agents.tools import historical` could not resolve.

The test happened to pass in some local runs because `backend/tests/test_role_conditioned_scoring.py` does its own module-top `sys.path` insert that adds `PROJECT_ROOT`, and that side effect leaked into the rest of the pytest session. Pytest's alphabetical collection order meant `test_lineup_player_context.py` was collected first → no leak yet → import error.

## Fix

Replaced the single-line insert at line 7 with the same pathlib pattern already used at the top of `test_role_conditioned_scoring.py`:

```python
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
for path in (str(BACKEND_DIR), str(PROJECT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
```

Also dropped the now-unused `import os`.

## Verification

| Acceptance check | Command | Result |
|---|---|---|
| Collects alone | `pytest backend/tests/test_lineup_player_context.py -v` | 1 passed |
| No regression | `pytest backend/tests/test_role_conditioned_scoring.py backend/tests/test_lineup_player_context.py -q` | 11 passed |
| Full collection | `pytest backend/tests -q --co` | 530 tests collected; no error for `test_lineup_player_context.py` |

The two remaining collection errors in the full backend suite (`test_agent_chat.py`, `test_lineup_consensus.py`) are unrelated `slowapi` env-dependency failures, scoped to sibling tickets per [SPO-21](../task-summaries/SPO-21-test-suite-triage.md).

## Out of scope (deferred)

Consolidating `sys.path` setup into `backend/conftest.py` would eliminate the duplication across `test_role_conditioned_scoring.py` and `test_lineup_player_context.py`. SPO-21 triage explicitly deferred this hygiene improvement — fix the bug first, refactor when a third caller forces it.

## Notes for CTO / Sage

During this heartbeat the harness rapidly checkout-swapped HEAD across four parallel Forge wakes (SPO-22, SPO-23 (renamed → SPO-22), SPO-24, SPO-25). The fix landed correctly on SPO-22 because the file change was made before the swap and committed by an earlier wake under the SPO-23 branch name (which I renamed to SPO-22 to match the wake payload's issue ID), but the experience suggests two questions worth raising at next CTO planning:

1. Are concurrent Forge wakes on the same workspace intentional? They share a working tree and rapidly stash/swap, which makes durable progress fragile.
2. Should the harness pin `assigneeAgentId` ↔ branch name from issue creation to avoid the SPO-22 vs SPO-23 vs SPO-24 branch-name drift seen in this run?
