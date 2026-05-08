# SPO-25 — Make test_agent_chat.py reason assertions content-based, not index-based

**Agent:** Forge
**Branch:** `feature/SPO-25-test-agent-chat-reason-assertions` (off `origin/dev`)
**Commit:** `3911b61` — `fix(test): assert market reason via breakdown, not reasons[2] (SPO-25)`
**Files changed:** `backend/tests/test_agent_chat.py` (17/5)
**Production code touched:** none.

## Problem

Three pure-service tests in `backend/tests/test_agent_chat.py` were failing with structurally identical errors. Each asserted that `response.verdict.reasons[2]` equals a specific market-formatter string:

| Test | Asserted | Actual |
|---|---|---|
| `test_agent_chat_service_builds_under_reasons_from_query_aligned_context` | `"Market prices the under at 53.2% on the 4.50 line, …"` | `"Schedule is neutral: …"` |
| `test_agent_chat_service_uses_line_moved_reason_from_query_aligned_context` | `"The original 4.50 line is no longer available; …"` | `"Schedule is neutral: …"` |
| `test_agent_chat_service_uses_market_unavailable_reason_from_query_aligned_context` | `"No exact same-line market quote is available, …"` | `"Schedule is neutral: …"` |

## Root cause (confirmed against current code)

`AgentChatService._build_legacy_reasons` (`backend/app/services/agent_chat.py:510`) returns the first **3** non-`unavailable` sections from the **9-section** breakdown built by `_build_verdict_breakdown` (`agent_chat.py:433`). Section order:

1. historical
2. trend_role
3. shooting (no fixture data → `unavailable`)
4. variance (no fixture data → `unavailable`)
5. **schedule** (always available; `_make_query_aligned_context` defaults `is_back_to_back=False`)
6. injuries
7. lineup
8. market
9. projection

With the test fixtures, `[shooting, variance]` are unavailable, so the first 3 non-unavailable sections collapse to `[historical, trend_role, schedule]`. The market section never makes it into `reasons[:3]` — so `reasons[2]` is the schedule message, not the market message.

Both impl and tests landed in the same big commit (`bcb511f`); the drift between the assertion style and the reason-collection algorithm is a stale-fixture artifact, not a product bug.

## Fix (test-side only)

Replaced the three `response.verdict.reasons[2] == "<market message>"` assertions with breakdown-based assertions that verify each pricing_mode branch's market formatter directly:

```python
assert response.verdict.breakdown is not None
sections = {section.key: section for section in response.verdict.breakdown.sections}
assert sections["market"].signal_note == "<market formatter output>"
```

This matches the dict-by-key idiom already used elsewhere in the same file (L675 in the pre-edit file: `sections = {section.key: section for section in response.verdict.breakdown.sections}`), so no new patterns introduced.

### Why breakdown access (option A from the ticket) over `any(...)` predicates (option B)

The original tests' intent — confirmed by their fixture setup, which constructs distinct `pricing_mode` values (`exact_line` / `line_moved` / `unavailable`) — is to lock in the **exact formatted string** each market branch emits, including bookmaker name and odds rendering. Membership-by-startswith would let a regression slip through where the formatter still starts with the right prefix but gets the numbers wrong. Breakdown access keeps the verbatim equality without depending on the truncation rule.

The first test's `reasons[0]` and `reasons[1]` checks were left untouched — they correspond to historical and trend_role formatters which are stable at indices 0/1 under the current ordering and remain meaningful regression detectors. Only the broken `reasons[2]` assertions were changed.

## Acceptance criteria

- [x] All three named tests pass.
- [x] Other `test_agent_chat.py` tests do not regress — full file: 12 passed.
- [x] Tests verify the *content* of the expected market reason for each pricing_mode branch, not its position in the array.
- [x] `backend/app/services/agent_chat.py` is unchanged in this commit (verified via `git show 3911b61 --stat`).

## Out of scope (not done)

- Reordering `_build_verdict_breakdown` sections so market precedes schedule (would change top-3 reasons rendered to users — needs CTO/Eason sign-off, raise separately if motivated).
- Cleanup of legacy `_extract_reasons` fallback in `_build_legacy_reasons`.
- Any production code change.

## Verification log

```
$ .venv/bin/python -m pytest tests/test_agent_chat.py -q
............                                                             [100%]
12 passed, 1 warning in 0.35s
```

The three previously-failing tests:
```
tests/test_agent_chat.py::test_agent_chat_service_builds_under_reasons_from_query_aligned_context PASSED
tests/test_agent_chat.py::test_agent_chat_service_uses_line_moved_reason_from_query_aligned_context PASSED
tests/test_agent_chat.py::test_agent_chat_service_uses_market_unavailable_reason_from_query_aligned_context PASSED
```

## Next action

Hand off to Lens for review of the local diff on `feature/SPO-25-test-agent-chat-reason-assertions`. No PR opened (per Forge role — local feature branch only).
