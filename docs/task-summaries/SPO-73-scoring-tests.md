# SPO-73 — Unit tests for `scripts/agents/scoring.py` numeric guards

**Ticket:** SPO-73 (Nightly-audit PR-track, parent SPO-72)
**Branch:** `feature/SPO-73-scoring-tests` (based on `origin/dev`)
**Author:** Forge
**Status:** Local commit ready for Lens review

## Summary

One-file, test-only addition that pins the deterministic numeric-guard helpers
in `scripts/agents/scoring.py` — the pick-generation critical path. Before this,
the module had only two happy-path role-blend tests in
`backend/tests/test_role_conditioned_scoring.py`; the guard helpers that the
scorecard math depends on were exercised only incidentally. A silent regression
in any of them corrupts *every* recommendation, so these tests lock their
edge-case behaviour. No production code was modified.

## Changes

| File | Change |
|---|---|
| `scripts/agents/tests/test_scoring.py` | **New.** 11 tests (148 lines) — direct edge-case coverage of 9 guard helpers + 2 uncovered `compute_scorecard` edges. |
| `docs/task-summaries/SPO-73-scoring-tests.md` | **New.** This summary. |

## Coverage

Guard helpers (one focused test each, multiple branch asserts):
- `_clamp` — below lo / above hi / within / exactly at both bounds
- `_safe` — present, missing key, nested miss, drill-through-non-dict, present
  `None` → default, **and present non-numeric value passes through unchanged**
  (documents the actual contract — `_safe` does not type-validate)
- `_round_optional` — `None` passthrough vs rounding
- `_historical_rate` — `hit_rate` > `shrunk_rate` > default precedence
- `_role_confidence_weight` — high/medium/low + case-insensitive + unknown/None → 0
- `_role_sample_discount` — `sample_size == 0` (no div-by-zero), below-minimum, and
  every step of the 0.60 / 0.80 / 1.00 curve
- `_query_side_probability` — over passthrough, under complement, None
- `_unique_names` — dedupe + strip + order preservation + blank/None drop
- `_trend_alignment` — None inputs, equal-within-epsilon neutral, over/under
  supports vs against branches

`compute_scorecard` edges (NOT re-testing the role-blend cases already covered):
- Fully-empty signals → graceful neutral, ineligible scorecard, full key contract
- Sufficient base sample but no market → `no market price available` branch
  (distinct from the sample-too-small gate)

## Why

`scoring.py` (582 lines) turns historical/projection/market signals into the
recommendation scorecard. The guard helpers are the load-bearing arithmetic;
their failure modes (boundary, None, zero-sample, direction) are exactly the
silent-corruption class. Pinning them is cheap insurance on a pick-critical path.

## Tests

- `pytest scripts/agents/tests/test_scoring.py` → **11 passed**
- `pytest scripts/agents/tests/ backend/tests/test_role_conditioned_scoring.py`
  → **46 passed, 3 deselected** (no regressions; deselected are integration-gated)
- Assertions were grounded against live helper output before being written
  (ground-truth probe, not assumed behaviour).

## Size

148 additions — within the `[small]` ≤ 200-line cap.

## Follow-ups

None required. All assertions reflect current behaviour; no genuine bug was
surfaced (so no separate bug ticket needed per the "STOP and report" clause).

## Chain

Forge (implement, local commit) → Lens (review local diff) → Sentinel (run
tests + `git push` + open PR to `dev`) → Owner squash-merges.
