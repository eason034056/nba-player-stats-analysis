# SPO-23 — Fix `test_lineup_player_context.py` sys.path off-by-one

**Agent:** Forge
**Branch:** `feature/SPO-22-test-lineup-player-context-syspath` (branch name follows the ticket text; the SPO-22 vs SPO-23 mismatch is a typo in the ticket — the work is owned by SPO-23)
**Commit:** `c9b7f63 fix(test): add PROJECT_ROOT to sys.path in test_lineup_player_context`
**Parent epic:** SPO-21 test-suite triage

## Problem

`backend/tests/test_lineup_player_context.py` failed at collection when run alone:

```
ModuleNotFoundError: No module named 'scripts'
```

Root cause: line 7 inserted only `BACKEND_DIR` into `sys.path`, but the test imports `scripts.agents.tools.historical`, which lives at `PROJECT_ROOT` (one level up). The test only passed in mixed runs because `tests/test_role_conditioned_scoring.py` happens to insert `PROJECT_ROOT` at module top, and that side-effect leaked into the rest of the pytest session. Alphabetical collection order put `test_lineup_player_context.py` first and prevented the leak from saving it.

## Fix

Replaced the single-line `sys.path.insert` with the same multi-path `pathlib`-based pattern already in use in `tests/test_role_conditioned_scoring.py`:

```python
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
for path in (str(BACKEND_DIR), str(PROJECT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
```

`import os` was removed because nothing else in the file used it. No production code changed; no behavior changed; only test discovery was affected.

## Verification

| AC | Command | Result |
|----|---------|--------|
| AC1 (collect alone) | `pytest tests/test_lineup_player_context.py -v` | 1 passed in 0.31s |
| AC2 (no regression with role-conditioned) | `pytest tests/test_role_conditioned_scoring.py tests/test_lineup_player_context.py -q` | 11 passed in 0.96s |
| AC3 (full backend collection) | `pytest backend/tests -q --collect-only` | 553 tests collected in 1.23s, no collection errors for this file |

The 5 stale-fixture failures called out in SPO-21 triage are unchanged and still owned by sibling tickets (SPO-24, SPO-25, etc.) — explicitly out of scope here.

## Out of scope (per ticket)

- Consolidating sys.path manipulation into `backend/conftest.py` (deferred per SPO-21 "triage before fixing" criterion).
- Any production code change.

## Notes for Lens / Sentinel

- Diff is 6 insertions / 2 deletions in one file; reviewing requires only `tests/test_role_conditioned_scoring.py:1-15` for the canonical pattern.
- Pattern intentionally mirrors the working file rather than introducing a new variant. If a future hygiene ticket lifts this into `conftest.py`, this file will simply lose its top block — no behavioral change.
