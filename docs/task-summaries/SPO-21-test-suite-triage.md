# SPO-21 — Backend test-suite triage

> Owner: Sentinel. Heartbeat: 2026-05-08 (post-SPO-18 squash-merge).
> Baseline: `origin/dev` @ `35a25dd` (PR #1 merge).

## TL;DR

| Bucket | Count | Action |
|---|---|---|
| `env-only` (Redis required) | 2 failures | Documented — `docker compose up -d redis` before running suite |
| `env-only` (tiktoken arch mismatch) | 2 collection errors | Documented — `pip install --force-reinstall --no-deps tiktoken` after Apple-Silicon migration |
| `code-bug` (test sys.path setup) | 1 collection error | Forge ticket: `test_lineup_player_context.py` sys.path off-by-one |
| `stale-fixture` (Chinese→English error msg drift) | 2 failures | Forge ticket: update `test_prob.py` regexes |
| `stale-fixture` (verdict-reason ordering) | 3 failures | Forge ticket: rewrite `test_agent_chat.py` reason assertions to be position-agnostic |

After Redis up + tiktoken reinstall, the previously-claimed-to-fail "3 collection errors" reduce to **1 real test-code bug** (lineup_player_context). Forge's diagnosis from SPO-18 verification ("all 3 are tiktoken arch") was partially wrong — `test_lineup_player_context.py` has its own sys.path defect that only surfaces because alphabetical collection order puts it before `test_role_conditioned_scoring.py`, which is the file that actually inserts `PROJECT_ROOT` on `sys.path`.

## Reproduction

```bash
cd backend
.venv/bin/pytest tests -q --continue-on-collection-errors
```

On clean `origin/dev` @ `35a25dd`, no Redis, x86_64 tiktoken:
```
3 errors during collection
1 skipped
```
(The 7 failures are masked because pytest aborts on collection errors when running the full suite without `--continue-on-collection-errors`. Adding the flag surfaces all 7.)

After `docker compose up -d redis` + `.venv/bin/pip install --force-reinstall --no-deps tiktoken`:
```
5 failed, 544 passed, 4 skipped, 1 error
```
The remaining 5 failures + 1 error are real defects.

## Per-test classifications

### 1. `tests/test_prob.py::TestAmericanToProb::test_zero_odds_raises_error` — **stale-fixture**

Test asserts `pytest.raises(ValueError, match="賠率不能為 0")`. Actual error: `"Odds cannot be 0"`. Commit `bcb511f` translated `app/services/prob.py` error messages from Chinese to English (along with all module/function docstrings) but did not update `test_prob.py` regex matches.

**Remediation:** update test regex to `"Odds cannot be 0"`. No production code change.

### 2. `tests/test_prob.py::TestDevig::test_zero_sum_raises_error` — **stale-fixture**

Identical pattern: `match="機率總和不能為 0"` but actual is `"Total probability cannot be 0"`. Same root commit (`bcb511f`).

**Remediation:** update regex.

### 3-5. `tests/test_agent_chat.py::test_agent_chat_service_*_from_query_aligned_context` (3 tests) — **stale-fixture**

All three assert `response.verdict.reasons[2] == "<market-pricing message>"`. Actual `reasons[2]` is `"Schedule is neutral: this is not a back-to-back."`.

Root cause: `_build_legacy_reasons()` (`backend/app/services/agent_chat.py:510`) takes the first 3 non-`unavailable` sections from a 9-section breakdown:
1. historical 2. trend_role 3. shooting 4. variance **5. schedule** 6. injuries 7. lineup 8. market 9. projection

In the test fixtures, sections 3/4 (`shooting`, `variance`) come back as `unavailable` because no historical_signals are passed, but `schedule` IS available because `_make_query_aligned_context` always sets `schedule.is_back_to_back=False`. So the first 3 non-unavailable sections become `[historical, trend_role, schedule]` — schedule lands in slot `[2]`, not market.

The tests appear to have been authored against an earlier ordering or against a different reason-collection algorithm; both impl + tests landed in the same big commit (`bcb511f`) with this drift baked in. The tests' *intent* is to verify the market-reason text formatting for each pricing_mode (`exact_line` / `line_moved` / `unavailable`), not ordering.

**Remediation (recommended, test-side):** rewrite the assertions to find the market reason by content rather than by index, e.g. `assert any(r.startswith("Market prices") for r in response.verdict.reasons)` — or assert against the formatted output of `_format_market_reason` directly without going through `_build_legacy_reasons`.

**Alternative (impl-side, requires product call):** reorder `_build_verdict_breakdown` sections so `market` comes before `schedule`, or have `_build_legacy_reasons` always include the market reason if available. This affects production UX (the top-3 reasons rendered to users), so should not be done unilaterally.

### 6. `tests/test_lineup_consensus.py::test_lineups_api_returns_team_count` — **env-only (Redis)**

Test uses `TestClient(app)` which exercises the full FastAPI app including the slowapi rate-limit middleware. With Redis down at `localhost:6379`, slowapi raises `redis.ConnectionError`, and the slowapi exception handler in `slowapi/extension.py:81` crashes with `AttributeError: 'ConnectionError' object has no attribute 'detail'` (slowapi handler assumes `RateLimitExceeded`, but its middleware routes any exception through it).

Passes after `docker compose up -d redis`.

**Remediation (env):** ensure Redis is running before invoking the suite. Document in README test-running section (already mentions Redis but doesn't call out test dependency). Consider a session-scoped pytest fixture that detects Redis liveness and skips/xfails TestClient-using tests when down.

**Latent code-bug (out of scope for this ticket):** the slowapi version + Redis-down combination produces a misleading `AttributeError`. Production hardening to fail-open or use an in-memory limiter when Redis is unreachable would be a separate Forge ticket if Eason wants it.

### 7. `tests/test_agent_chat.py::test_agent_chat_endpoint_validates_action_and_uses_service` — **env-only (Redis)**

Same root cause as #6. Same remediation.

### 8. `tests/test_lineup_player_context.py` — **code-bug (test file sys.path)**

The test inserts `os.path.dirname(os.path.dirname(__file__))` on sys.path, which resolves to `backend/`. But the test imports `from scripts.agents.tools import historical`, and `scripts/` lives at the *project root*, not under `backend/`. So the import fails with `ModuleNotFoundError: No module named 'scripts'` whenever the test is collected before any other module that adds `PROJECT_ROOT` to sys.path.

It accidentally passes when collected alongside `test_role_conditioned_scoring.py` (which inserts the correct PROJECT_ROOT path at module top — that side-effect leaks into the rest of the session). Alphabetical collection order means this hidden coupling fails as soon as `test_lineup_player_context.py` is collected first or alone.

**Remediation:** change the sys.path setup to mirror `test_role_conditioned_scoring.py`:

```python
from pathlib import Path
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
for path in (str(BACKEND_DIR), str(PROJECT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
```

Long-term cleanup (out of scope): consolidate sys.path manipulation into a `backend/conftest.py` so individual test files don't need it. That's a hygiene improvement, not a SPO-21 deliverable.

### 9-10. `tests/test_agent_planner.py` and `tests/test_role_conditioned_scoring.py` collection errors — **env-only (tiktoken arch mismatch)**

Both files import `langchain_openai`, which transitively imports `tiktoken`. The shipped `tiktoken/_tiktoken.cpython-313-darwin.so` in `backend/.venv/lib/python3.13/site-packages/` is `Mach-O 64-bit dynamically linked shared library x86_64`, but the host runs Python under arm64 → `dlopen` fails with `incompatible architecture`.

This is a stale x86_64 wheel from before the developer migrated to native arm64 Python (or `pip` was once invoked under Rosetta and cached an x86 wheel).

**Remediation (env):**
```bash
.venv/bin/pip install --force-reinstall --no-deps tiktoken
```
This pulls the arm64 wheel and verified-fixes both collection errors. Confirmed locally — the `.so` flips to `Mach-O 64-bit dynamically linked shared library arm64` and 12 tests pass.

**README/.envrc note:** add a one-liner under "Backend setup" in `README.md` calling out that on Apple Silicon, `tiktoken` may need a force-reinstall after first `pip install -r requirements.txt`. No code change.

## Hygiene observations (not ticket-worthy individually)

1. **`backend/app/settings.py:13` Pydantic deprecation warning.** The `Settings(BaseSettings)` class uses legacy `class Config:` rather than `model_config = SettingsConfigDict(...)`. This directly violates `CLAUDE.md` "Settings" rule. A 5-minute fix should be folded into a future Forge cleanup pass. Not opened as a separate ticket since it's not in SPO-21 scope.

2. **Two TestClient tests in entire suite.** Only `test_agent_chat.py` and `test_lineup_consensus.py` exercise `TestClient(app)` — and both fail without Redis. Adding more endpoint-level tests will hit the same wall. A `conftest.py` with a `fakeredis` or limiter-override fixture would future-proof endpoint test coverage. Defer to whoever opens an endpoint-test expansion epic.

3. **Coupling via sys.path side-effect in test files.** Multiple test files manipulate `sys.path` at module top. This works by accident depending on collection order. Consolidating into `backend/conftest.py` is a low-risk hygiene change, but explicitly out of SPO-21 scope per "triage before fixing" acceptance criterion.

## Acceptance criteria status

- [x] Reproduced 7 failures + 3 collection errors on `origin/dev` @ `35a25dd`.
- [x] Each failure classified with rationale (above).
- [x] tiktoken collection errors confirmed env-only — `pip install --force-reinstall --no-deps tiktoken` flips x86_64 → arm64 and unblocks both. Documented as `.envrc` / README note, not code change.
- [x] Per-test classification + root cause + recommended remediation summarised in the SPO-21 comment thread.
- [ ] Forge tickets opened: `code-bug` (test sys.path) → 1 ticket; `stale-fixture` (test_prob, test_agent_chat reason ordering) → 1–2 tickets.
- [ ] Final `pytest backend/tests -q` → 0 failures + 0 collection errors. Pending downstream fix tickets.
