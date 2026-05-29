# SPO-70 — Unit tests for `scripts/agents/data_logger.py`

## Summary
Adds `scripts/agents/tests/test_data_logger.py` — the first test coverage for
`data_logger.py` (286 LOC, previously zero-coverage). `data_logger.py` powers
the `cli.py --log-data` debug path that formats the full agent `state` for
developers. A crash on partial/malformed `state` kills a debug trace exactly
when it's needed, so this locks down its robustness. Pure-additive, test-only;
no production code touched.

## Changes
| File | Change |
|---|---|
| `scripts/agents/tests/test_data_logger.py` | **New.** 14 unit tests via the existing `conftest.py` sys.path bootstrap + pytest `capsys`. |

## Why
Mirrors the owner-approved SPO-67 pattern (zero-coverage critical path → unit
tests). Debug tooling that crashes on edge-case state is worse than useless;
these tests pin the guards (`isinstance` checks, optional-section skipping,
`query_probability is not None` formatting) that keep `--log-data` resilient.

## Coverage (maps to ticket success criteria)
1. `log_all_agent_data({})` — empty state prints the banner, does not raise.
2. Partial state (only `parsed_query`) — Planner section prints, signal groups skipped.
3. `_log_signal_group` skips a non-dict signal value (`{"get_base_stats": None}`) via the `isinstance(data, dict)` guard, no crash.
4. `_format_signal` happy-path emits all fields + JSON `details`; missing-field fallback uses `?`/`0` placeholders. (The `▶ / 說明 / 資料來源` lines are emitted by `_log_signal_group`, which wraps `_format_signal` — asserted in a dedicated test.)
5. Branch coverage:
   - Market note: non-`exact_line` pricing prints the "查詢線沒有精準對上" warning + lists `available_lines`; `exact_line` short-circuits it.
   - `query_aligned_context`: `query_probability` rendered with `.4f` when present; silently skipped when absent; non-dict `scorecard` falls back to `{}` without crashing.
   - Extra: `data_quality_flags` listing + public-surface guard against helper renames.

## Tests
```
python3 -m pytest scripts/agents/tests/test_data_logger.py -v
# 14 passed in 0.02s
```
Pre-existing, unrelated: `test_phase5b_league.py` fails *collection* in this
environment because `langchain_openai` is not installed (it imports
`agents.py`). This is an environment gap on `origin/dev`, not introduced here —
`test_data_logger.py` and `test_date_utils.py` import no LLM deps and run clean.

## Constraints honored
- Tier `[small]`: non-test production lines changed = **0** (test-only).
- Branched off `dev`; PR targets `dev`.
- No forbidden zones touched (`*_gateway.py`, `settings.py`, `migrations/`, `.github/workflows/`).
- `date_utils.py` untouched (owned by SPO-67 / PR #21).

## Follow-ups
- None required. No real bug spotted in `data_logger.py` while writing tests
  (the `isinstance` and `is not None` guards already cover the malformed-state paths).
