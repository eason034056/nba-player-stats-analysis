# SPO-24 — Update test_prob.py regexes to match English error messages

**Agent:** Forge
**Branch:** `feature/SPO-24-test-prob-english-regex` → squash-merge to `dev`
**Parent triage:** [SPO-21](../task-summaries/SPO-21-test-suite-triage.md)

## Summary

Test-side stale-fixture fix. Two `pytest.raises(..., match=...)` regexes in `backend/tests/test_prob.py` still asserted Chinese substrings, but production `backend/app/services/prob.py` ships English `ValueError` messages (translated in commit `bcb511f`). The mismatch caused two persistent failures during SPO-21 triage. Production code was correct; tests had drifted.

## Changes

| File | Line | Before | After |
|---|---|---|---|
| `backend/tests/test_prob.py` | 88 | `match="賠率不能為 0"` | `match="Odds cannot be 0"` |
| `backend/tests/test_prob.py` | 227 | `match="機率總和不能為 0"` | `match="Total probability cannot be 0"` |

Diff scope: 2 lines changed in 1 file. Production code untouched.

## Verification

```
$ pytest tests/test_prob.py::TestAmericanToProb::test_zero_odds_raises_error \
         tests/test_prob.py::TestDevig::test_zero_sum_raises_error -v
2 passed in 0.02s

$ pytest tests/test_prob.py -v
25 passed in 0.01s    # full file — no regressions
```

## Out-of-scope (intentionally kept)

- Chinese-language **docstrings** on the test methods (`測試賠率為 0 時應該拋出例外`, `測試總和為 0 時應該拋出例外`). These describe **test intent**, not the matched string. Per owner profile (Eason — bilingual, prefers Traditional Chinese for explanation), kept as-is.
- File-level header / module docstring — also kept.
- No production-side change to `backend/app/services/prob.py`.

## Why this drifted

Commit `bcb511f` translated docstrings + `ValueError` messages in `prob.py` from Chinese to English in one pass, but the corresponding `match=` regexes in `test_prob.py` were not updated. The tests passed before that commit and silently broke after, because nothing exercised the error paths in the CI window when the translation landed.

**Lesson** (for Sage if epic closes): when translating user-facing strings — even internal `ValueError` messages — grep for `match=` regexes that reference them. Localised tests are an under-appreciated source of stale fixtures.

## Branching note

This branch was created from `origin/dev` (`35a25dd`) per the issue's branching instructions. A leftover SPO-23 working-tree change (`backend/tests/test_lineup_player_context.py` — pathlib refactor) was present when the harness handed off the branch; it has been left unstaged in the working tree so the SPO-23 owner can pick it up. It is NOT part of this commit or PR.
