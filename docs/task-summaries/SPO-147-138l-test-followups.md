# SPO-147 — lock the WNBA absence skip and non-canonical injury words

- Ticket: SPO-147
- Branch: `feature/SPO-147-138l-test-followups`
- Base: `dev` at `416c00e` (`feat: remove the WNBA backend`, #115, on top of the #117 merge)

## Summary

Two tests from the #117 QA review now lock behavior the SPO-138l suite left open. `assemble_dataset(league="wnba", absence_source="actual")` keeps the row `pregame`, leaves the new absence columns NULL, and does not call `team_absences`, even when the inputs include an Out injury and a 2025 starter lineup. Listed status words outside the five injury-status constants (`out`, `OUT`, `Day To Day`, `Out For Season`, `doubtful`, and `gtd`) get no `p_out` and increment `unknown_status_count`. The CLI check `--league wnba` is rejected. No production code changed.

## Changes

| Area | What changed |
|---|---|
| Tests | `backend/tests/test_spo147_138l_test_followups.py` adds the two locks, plus a small check that `build_parser()` exits 2 on `--league wnba`. |
| Docs | This summary. `docs/progress.md` is not edited. |

The other five checks in the QA review file are not in this PR.

## Why

`p_out_for_status` strips whitespace and then looks up the shared constants exactly: Out 1, Doubtful 0.75, Questionable 0.5, Day-To-Day 0.25, Probable 0.1. SPO-138l already maps those five words, a padded `Doubtful`, `GTD`, a blank, and `None`. It does not lock a different case (`out`, `OUT`, `doubtful`) or a different spelling (`Day To Day`, `Out For Season`). Those words must stay unknown. Guessing them would put a probability on a status the scale does not define.

`_AbsenceReader` builds no absence index unless `league == "nba"`, and `cell` returns NULL absence columns and `info_source="pregame"` before `team_absences`. A WNBA call with `absence_source="actual"` must not become a stand-in and must not read the NBA rotation rule. #115 removed `--league wnba` from the CLI (`choices=("nba",)`). `assemble_dataset` still takes `league` and still ignores the other league inside one export. This PR does not put the flag or the WNBA backend back.

Item 1 did not need new assertions after #115. The only ML edit in `416c00e` is the CLI choice list. `feature_sources` is still `games`, `player_game_stats`, `game_odds_snapshots`. Filtering is still "keep the league argument." The WNBA test from the review passes against current `dev` with those assertions unchanged.

## Tests

```
cd backend
DATABASE_URL="" python -m pytest tests/test_spo147_138l_test_followups.py tests/test_spo138l_ml_absence.py tests/test_spo138j_ml_dataset.py tests/test_spo138k_ml_game_odds.py -q
```

`DATABASE_URL=""`. No database. 57 passed.

| File | Result |
|---|---|
| `tests/test_spo147_138l_test_followups.py` | 3 passed |
| `tests/test_spo138l_ml_absence.py` | 22 passed |
| `tests/test_spo138j_ml_dataset.py` | 20 passed |
| `tests/test_spo138k_ml_game_odds.py` | 12 passed |

The new three are the WNBA export lock, the non-canonical status words, and the CLI rejection. The other 54 are the existing in-memory SPO-138l, SPO-138j, and SPO-138k files.

**Mutation check** (reverted before commit):

Both edits were applied together, then removed.

- The non-NBA branch of `_AbsenceReader.cell` called `team_absences` before returning the NULL columns. `test_wnba_export_keeps_new_columns_null_and_skips_nba_absence` failed with `AssertionError: team_absences must not run for a WNBA export`.
- `p_out_for_status` looked up a case-folded copy of the five constants. `test_noncanonical_status_words_are_counted_and_not_given_p_out` failed on `out` with `assert 1.0 is None`.

That run was 2 failed, 23 passed. The CLI test and the 22 SPO-138l tests stayed green. Both edits were reverted. The same four files then passed again: 57 passed.

`test_spo132b_optional_vpc.py::TestVpcIdConsole` was not run. Those 3 tests are the known terraform console failures on clean `dev` when terraform is installed. They are not part of this change.

## Follow-ups

- The other five QA checks (WNBA `team_absences` rejection, newest unlisted row, NULL tip with a non-default offset, projected-version order plus a bench stand-in, and a zero team total versus an empty absence list) stay out of this PR.
- Do not add a WNBA absence path, and do not put `--league wnba` back on the exporter.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-147 | 本 PR | 只加測試。`assemble_dataset(league="wnba")` 維持 `pregame`、新缺陣欄位是 NULL、不呼叫 `team_absences`。`out` / `OUT` / `Day To Day` / `Out For Season` / `doubtful` 沒有 `p_out`，並計入 `unknown_status_count`。`--league wnba` 被 CLI 拒絕。#115 之後這兩個斷言不用改。沒有改產品程式，也沒有改 `docs/progress.md`。 |
