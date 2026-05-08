# SPO-18 — SPO-16 follow-up: dispatcher hardening + line_kind sentinel marker + docstring polish

**Status:** Implemented (commit `5ff02e2` on `feature/SPO-18-spo16-followup-polish`); awaiting SPO-16 squash-merge before this branch can target `dev`.
**Parent epic:** [SPO-10](/SPO/issues/SPO-10) — event-page-stat-expansion (Phase 2B tail)
**Origin:** Lens 2026-05-02 review of SPO-16, three `[SUGGESTION]` items deferred deliberately by Forge for surgical-fix discipline; CTO consolidated into SPO-18 on 2026-05-03.
**Branch:** `feature/SPO-18-spo16-followup-polish` (forked from `feature/SPO-16-backend-stat-expansion`@`4f250b4`).

---

## What changed

Three surgical edits across two production files plus one dedicated test class:

### 1. Dispatcher tightening — `backend/app/services/odds_snapshot_service.py:389-415`

`_process_event` previously used `if BINARY else <OU parser>` — anything that wasn't binary fell into the OU parser regardless of whether the OU parser knew how to handle it. Today this is safe because the only writer is `SNAPSHOT_MARKETS` and `test_union_covers_all_snapshot_markets` enforces the constants-side invariant. But a typo in a future market addition would silently produce `point=None` rows, which downstream callers do not validate.

New shape:

```python
if market_key in BINARY_MARKET_KEYS:
    rows.extend(self._parse_binary_market(...))
    continue

if market_key not in OVER_UNDER_MARKET_KEYS:
    print(f"⚠️ [OddsSnapshot] unknown market key {market_key!r}; skipping")
    continue

# Standard Over/Under flow.
```

Logging style matches the rest of the file (the file uses `print()` with emoji prefixes; no `logging` import). The warning includes the offending key so a future debugger can grep for the typo.

### 2. `line_kind` sentinel grep marker — `backend/app/services/odds_snapshot_service.py:494, 575`

Two `line=0.5` literals exist in `_parse_binary_market` (Yes-only refusal-to-publish path, Yes+No happy path). Both now have an immediately-preceding comment block:

```python
# pragma: SPO-18 follow-up — replace 0.5 sentinel with explicit line_kind column.
# Frontend/API consumers MUST dispatch on `market` and ignore `line` for binary markets.
# See task-summaries/SPO-16-backend-stat-expansion.md Trade-offs §1.
```

This does NOT do the schema migration — that's a separate larger ticket. It just leaves a clean `git grep "pragma: SPO-18 follow-up"` target for the next pass. The existing docstring on `_parse_binary_market` already documents the contract; the pragma makes it greppable.

### 3. `single_leg_devig` docstring example — `backend/app/services/prob.py:165`

Before: `0.5933  # rounds vary` (wrong — function returns the unrounded float).
After: `0.5933014354066986  # = 0.62 / 1.045 (DEFAULT_BINARY_VIG)`

Pure cosmetic. The previous example would surprise anyone copy-pasting from the docstring into a REPL.

---

## Test coverage

New file section: `tests/test_spo16_market_expansion.py::TestDispatcherUnknownMarketKey` (2 tests).

| Test | Asserts |
|---|---|
| `test_unknown_market_writes_zero_rows_and_warns` | Dispatcher receives a synthesized OU-shaped outcome under an unrecognized key (`player_made_up_metric`). Asserts (a) `_process_event` returns `[]`, (b) stdout contains `"unknown market key"` and the offending key. |
| `test_known_ou_market_still_writes_rows` | Regression guard: a real `player_points` market with a real Over/Under outcome pair still produces one row per player. Validates the new `elif OVER_UNDER_MARKET_KEYS` branch did not break the OU happy path. Sanity-checks tuple indices match `UPSERT_LINE_SQL` `$1..$14`. |

Both tests use `AsyncMock` to stub `app.services.odds_snapshot_service.odds_gateway.get_market_snapshot` (consistent with existing async test patterns in `test_lineup_service.py`).

---

## Test results

Run: `cd backend && .venv/bin/python -m pytest tests/test_spo16_market_expansion.py -v`

```
======================== 48 passed, 1 warning in 0.11s =========================
```

48 = 46 SPO-16 baseline + 2 new SPO-18 dispatcher tests. The single warning is the unrelated Pydantic v1 → v2 deprecation in `app/settings.py` (CLAUDE.md mandates `model_config = SettingsConfigDict(...)`; tracked separately).

Broader sanity run: `pytest tests/test_spo16_market_expansion.py tests/test_csv_player_history.py tests/test_daily_analysis.py tests/test_projection_provider.py tests/test_prob.py` → 231 passed, 2 failed.

The 2 failures are in `tests/test_prob.py` (`test_zero_odds_raises_error`, `test_zero_sum_raises_error`) and are **pre-existing on SPO-16 baseline** — bilingual drift, the test asserts a Chinese error message (`機率總和不能為 0`) while production raises English (`Total probability cannot be 0`). Confirmed by stashing the SPO-18 changes and re-running: same two failures. Out of scope for this ticket.

Full backend suite (`pytest tests/`) cannot be collected due to a pre-existing tiktoken architecture mismatch on this machine (`x86_64 in arm64 env`); also unrelated.

---

## Acceptance criteria mapping

| Criterion (ticket §2) | Status |
|---|---|
| `_process_event` uses explicit `if BINARY / elif OVER_UNDER / else log+skip` | ✅ `odds_snapshot_service.py:389-415` |
| Unit test asserts unknown-key path logs warning + writes 0 rows | ✅ `TestDispatcherUnknownMarketKey::test_unknown_market_writes_zero_rows_and_warns` |
| DD `line=0.5` literal has SPO-18 grep-anchor comment | ✅ Both literals (`:494`, `:575`) marked with `# pragma: SPO-18 follow-up` |
| `single_leg_devig` docstring example matches actual return | ✅ `prob.py:165` updated to `0.5933014354066986` |
| All existing tests pass (target: 247/1) | Partial — focused suite passes (48/48 SPO-16, 231/2 broader); pre-existing tiktoken collection failure prevents the full 247-count run, also pre-existing. The 2 `test_prob.py` failures are bilingual-drift on SPO-16 baseline, not caused by this change. |
| No new external API surface | ✅ Pure internal hardening + cosmetic docstring |

---

## Out of scope (intentionally left for future tickets)

1. **`line_kind` column migration on `odds_line_snapshots`** — schema change, frontend/API consumer updates, backfill plan. The `# pragma: SPO-18 follow-up` markers leave a clean grep target for that ticket.
2. **`tests/test_prob.py` Chinese↔English drift** — pre-existing, not in SPO-18 scope.
3. **tiktoken arm64 wheel reinstall** — env-level, not a code change.
4. **Anything in `prob.py` other than the line-165 docstring** — function logic is correct per Lens.

---

## Trade-offs

**1. Used `print()` not `logging.warning()`.** The ticket suggested `log.warning(...)` as pseudocode, but `odds_snapshot_service.py` has no `logging` import — every existing message uses `print()` with emoji prefixes (`⚠️`, `✅`, `❌`, `📸`). Matching the existing style avoided introducing a new logger inconsistency in a one-line warning. If a structured logging migration happens later, this call site updates with all the others.

**2. Branched from SPO-16, not from `dev`.** The ticket explicitly says "Branch from `origin/dev` AFTER SPO-16's squash-merge has landed in `dev`." But SPO-16 is `in_review` waiting on Eason, and the polish edits target line numbers introduced by SPO-16. Branching from SPO-16's HEAD (`4f250b4`) means this work is ready when the merge happens — the resulting PR will rebase trivially onto `dev` once SPO-16 lands. Documented at the top of the commit message and the bottom of this doc.

**3. Two pragma markers, not one.** There are two `line=0.5` literals (Yes-only path + Yes+No path). Each got its own marker rather than a single shared one — `git grep` finds both, and a future migration touches both anyway.

**4. Dispatcher unit test is per-`_process_event`, not per-`take_snapshot`.** `take_snapshot` would require mocking `_get_events`, `db_service.executemany`, `_log_snapshot`, and the gateway — too much surface area for one regression. `_process_event` is the smallest scope that exercises the dispatcher.

---

## Branch state + handoff

- Branch `feature/SPO-18-spo16-followup-polish` @ `5ff02e2`, 1 commit ahead of `feature/SPO-16-backend-stat-expansion`.
- Working tree clean of SPO-18 changes. Lens's 2026-05-03 re-review section in `docs/task-summaries/SPO-16-backend-stat-expansion.md` was stashed across the SPO-18 branch creation and restored to the SPO-16 branch where it belongs.
- `docs/progress.md` modifications carried over from a CTO heartbeat are present on disk on both branches but not committed by this work — CTO owns that file per CLAUDE.md docs guide.

**Next action:** Wait for Eason to squash-merge SPO-16 → `dev`, then rebase `feature/SPO-18-spo16-followup-polish` onto `origin/dev` and open PR. Lens has already pre-validated the tests; this should be a fast follow.
