# SPO-67 — Unit tests for scripts/agents/date_utils.py

**Agent:** Forge
**Branch:** `feature/SPO-67-date-utils-tests` → squash-merge to `dev`
**Parent triage:** SPO-66 (nightly audit, PR-track `[small]`)

## Summary

Pure test-addition. `scripts/agents/date_utils.py` (71 lines, 2 public functions) had **zero** unit tests despite sitting on a critical path: planner colloquial dates ("today"/"tomorrow") → `normalize_date()` → YYYY-MM-DD → `date_to_utc_range()` → the UTC window sent to The Odds API. A silent bug here queries the wrong day → wrong/empty props. Added a deterministic, timezone-agnostic test file covering both functions. **No production code changed.**

## Changes

| File | Lines | What |
|---|---|---|
| `scripts/agents/tests/test_date_utils.py` | +140 (new) | 30 tests across `normalize_date` and `date_to_utc_range` |

Diff scope: 1 new file, 140 lines. Well under the `[small]` ≤ 200-line cap. Production code untouched.

## Coverage

`normalize_date(date_str)`:
- `"today"` → local today; `"tomorrow"` + misspellings `"tomorow"`/`"tommorow"` → today+1
- case-insensitive + whitespace-trimmed (`"  TODAY  "`, `"ToMoRrOw"`)
- already-formatted `"2025-03-13"` returned unchanged (incl. padded `"  2025-03-13  "`)
- invalid calendar date `"2025-02-30"` → `""`
- garbage / wrong format / non-string (`None`, `int`, `list`, `dict`, `object`) → `""`

`date_to_utc_range(date_yyyy_mm_dd)`:
- valid date → tz-aware UTC tuple; `utcoffset()==0`, `start < end`, span ≈ 86399 s (~24h)
- malformed / empty / colloquial / impossible-date → `None`

## Anti-flake design

Both functions read `datetime.now().astimezone()` (machine-local tz). freezegun is **not** an installed dep, so the suite never hard-codes an absolute date or UTC string:
- relative-date expectations are derived from the same local clock (`datetime.now().astimezone().date()`) at test time;
- `date_to_utc_range` asserts **structural invariants** (tz-aware UTC, ordering, ~24h span) — a fixed local offset cancels in the difference, so the span check is timezone-independent and passes in any CI tz.

## Verification

```
$ python3 -m pytest scripts/agents/tests/test_date_utils.py -q
30 passed in 0.02s
```

## Bugs found in production code

None. `date_utils.py` behaved correctly against every case (including the `2025-02-30` / `2025-13-01` ValueError paths). No production fix was needed, so scope stayed at test-only per the ticket's STOP-and-report rule.

## Chain

Forge (this commit, local) → Lens (review) → Sentinel (test + push + open PR to `dev`) → Owner squash-merge.
