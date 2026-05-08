# SPO-23 — Fix `test_lineup_player_context.py` sys.path off-by-one

**Agent:** Forge
**Branch:** `feature/SPO-22-test-lineup-player-context-syspath` (branch name follows the ticket text; SPO-22 in the description is a typo — the work is owned by SPO-23)
**PR:** [#2](https://github.com/eason034056/nba-player-stats-analysis/pull/2) → `dev`
**Commit:** `c9b7f63 fix(test): add PROJECT_ROOT to sys.path in test_lineup_player_context`
**Parent epic:** SPO-21 test-suite triage

## Problem

`backend/tests/test_lineup_player_context.py` failed at collection when run alone:

```
ModuleNotFoundError: No module named 'scripts'
```

Root cause: line 7 inserted only `BACKEND_DIR` into `sys.path`, but the test imports `scripts.agents.tools.historical`, which lives at `PROJECT_ROOT` (one level up). The test only passed in mixed runs because `tests/test_role_conditioned_scoring.py` happens to insert `PROJECT_ROOT` at module top, and that side-effect leaked into the rest of the pytest session. Alphabetical collection order put `test_lineup_player_context.py` first and prevented the leak from saving it.

## Fix

Replaced the single-line `sys.path.insert` with the multi-path `pathlib`-based pattern already in use in `tests/test_role_conditioned_scoring.py`:

```python
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
for path in (str(BACKEND_DIR), str(PROJECT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
```

`import os` removed (no longer used). No production code changed.

## Verification

| AC | Command | Result |
|----|---------|--------|
| AC1 | `pytest tests/test_lineup_player_context.py -v` | 1 passed in 0.31s |
| AC2 | `pytest tests/test_role_conditioned_scoring.py tests/test_lineup_player_context.py -q` | 11 passed in 0.96s |
| AC3 | `pytest backend/tests -q --collect-only` | 553 tests collected in 1.23s, no collection errors for this file |

## Out of scope

- Consolidating sys.path manipulation into `backend/conftest.py` (deferred per SPO-21 "triage before fixing").
- Sibling stale-fixture failures (SPO-24, SPO-25, etc.).

## Notes for Lens / Sentinel

- Diff: 6 insertions / 2 deletions in one file. Reviewing requires only `tests/test_role_conditioned_scoring.py:1-15` for the canonical pattern.
- Pattern intentionally mirrors the existing working file rather than introducing a new variant.
