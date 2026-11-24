# SPO-153 — Official injury rows on the reported absence path

## Data shape

One report row is one line from `nba_injury_report_rows`:

`league`, `report_at`, `bdl_game_id`, `bdl_team_id` or null, `player_raw`, `bdl_player_id` or null, `status` or null, `reason`, `category`, `not_yet_submitted`, `all_players_available`.

A team marker has an empty `player_raw`, a null status, and either `not_yet_submitted` or `all_players_available`. This code does not match names. A null `bdl_player_id` stays unmatched. A null `bdl_team_id` is not given to either team.

One refresh row is `league`, `refreshed_at`, `complete`, for source `injuries_nba_official`.

One feature row is the existing player-game row from `assemble_dataset`. Team absence is still the 138l list of `(bdl_player_id, p_out)` for rotation players. Four columns are added on that same row: `rot_out_n`, `rot_q_n`, `unmatched_listed_n`, `injury_report_missing`.

## Summary

`absence_source='reported'` can now read official report lines that were known at T, where T is `games.datetime_utc` minus 3 hours. The latest `report_at` at or before T is kept. A line one second later is not. Lines for another `bdl_game_id` are not. `Available` weighs 0 on this path only. Out 1, Doubtful 0.75, Questionable 0.5, Day-To-Day 0.25, and Probable 0.1 are unchanged.

No usable report means every official absence number is NULL and `injury_report_missing` is 1. A NOT YET SUBMITTED team is NULL for that team only. A team left off a report that covers the game has missing minutes 0. Numbers are stored only when a complete `injuries_nba_official` refresh covers T, using the same 90-minute rule as `source_covered`. Box-score `source='actual'` still fills the old minute column and leaves the four new columns NULL.

Passing no official rows keeps the 138l snapshot path, so older tests stay on that path. `export_dataset` loads the new table when it exists. If the table is not in the database, the export still uses snapshots.

## Changes

| File | What it does |
|---|---|
| `backend/app/ml/absence.py` | Selects the report, maps Available to 0, applies the NULL rules, and counts rotation outs, questionables, and unmatched names. |
| `backend/app/ml/load.py` | Adds the row and refresh records and a read-only loader. The SQL does not filter `report_at` and does not write. |
| `backend/app/ml/sources.py` | Registers `nba_injury_report_rows` on the absence allow-list only. |
| `backend/app/ml/build_dataset.py` | Puts the four counts on the dataset row and uses official lines when the caller passes them. |
| `backend/tests/fixtures/spo153/harden_cle_bkn_20260301.json` | Parsed-style rows and made-up seconds for the worked example. No PDF. |
| `backend/tests/test_spo153_official_injury_features.py` | Locks the acceptance checks. |
| `docs/task-summaries/SPO-153-official-injury-features.md` | This note. |

`features.py`, `game_odds.py`, `asof.py`, the fetcher, the parser, the matcher, and the 151/152 files are not edited. `docs/progress.md` is not edited.

## Why

A report published after T, and a box score, both know facts that were not known when the bet would have been made. The dataset has to keep those out of the reported columns. A missing report is not the same fact as a healthy team, so it cannot be stored as 0.

## Tests

Command, from `backend/`, with `DATABASE_URL` set to an empty string:

`python -m pytest tests/test_spo153_official_injury_features.py -q`

Result: 21 passed.

Same setting, full `backend/tests`: 1746 passed, 283 skipped, 3 xfailed, 0 failed. `tests/test_spo132b_optional_vpc.py` was 8 passed and 3 skipped. The three console failures named in the ticket did not fail on this `dev`.

### Harden rows and the minutes

Fixture: `backend/tests/fixtures/spo153/harden_cle_bkn_20260301.json`.

Game 18447687, Cleveland visitor team id 5, Brooklyn home team id 2, tip 2026-03-01 20:30 UTC, T 2026-03-01 17:30 UTC. Team ids are fixture ids, not a live catalog.

The T report is named `Injury-Report_2026-03-01_12_15PM` with `report_at` 2026-03-01 17:15:05 UTC. Cleveland lines: Ellis Questionable 38017714, Harden Questionable 192, Minix Out 1028245994 (G League, no minutes, not rotation), Mitchell Out 322, Strus Out 666908 (no minutes, not rotation), Wade Out 666940. Brooklyn lines: Claxton Out 666508, Demin Out 1057266813, Etienne 900001, Johnson 900002, and Liddell 900003 (G League, no minutes), Powell Out 1057279425 (G League, but he has minutes, so he counts). A decoy line for game 999 lists Mitchell Available at the same timestamp and is ignored.

The minutes are not a downloaded box score. They are per-game seconds in that file, chosen so the existing average formula returns the study's published feature values. The study's one-decimal display (31.0, 20.8, 21.7) adds to 62.65, not 62.67.

| Player | Seconds on the five prior dates | Average | Weight | Adds |
|---|---|---|---|---|
| Mitchell | 1860, 1860, 1860, 1860, 1860 | 31.00 | 1 | 31.00 |
| Wade | 1249, 1249, 1249, 1249, 1253 | 20.83 | 1 | 20.83 |
| Ellis | 1300, 1300, 1300, 1300, 1304 | 21.68 | 0.5 | 10.84 |
| Harden | 1200 five times | 20.00 | left out | 0 |

31.00 + 20.83 + 10.84 = 62.67. `team_missing_minutes` on the assembled Harden row is that number. `rot_out_n` is 2 (Mitchell, Wade). `rot_q_n` is 1 (Ellis). Harden is Questionable and is rotation, and he is left out of his own counts. `player_injury_status` is Questionable. `as_of` is 2026-03-01 17:30 UTC.

Opponent minutes in the fixture are Claxton 1680 seconds (28), Demin 1620 (27), and Powell 1200 (20). The sum is 75.0. The study's published opponent total was 75.43 from real logs that are not in this repo. This test does not claim 75.43.

Point share on the fixture is 85/140: Mitchell 50, Wade 20, Ellis 30 times 0.5, Harden's 40 left out of the numerator, team total 140. The study's published point share was 0.2350 from a 1200-point team total. This test does not claim 0.2350.

The tip report is named `Injury-Report_2026-03-01_03_15PM` at 2026-03-01 20:15:05 UTC. Ellis and Harden are Available there. With both reports in the input, the row at T stays 62.67. Calling the same builder at the tip instant, and adding a refresh at 20:15:05 UTC so the 90-minute coverage rule passes at that later instant, returns 51.83 (31.00 + 20.83). The 12:15 PM refresh alone is too old to cover 20:30 UTC, so it cannot leak the tip report by itself.

A game with an empty official list, a covering refresh, and an older snapshot that says Mitchell is Out still returns NULL minutes, NULL shares, NULL counts, and `injury_report_missing` 1. The snapshot is not used.

`source='actual'`, with a played target-game row for every rotation player, returns `team_missing_minutes` 0 and leaves `rot_out_n`, `rot_q_n`, `unmatched_listed_n`, and `injury_report_missing` NULL. `info_source` is `standin`.

## Follow-ups

- SPO-154 recalibrates weights. This ticket does not.
- SPO-155 decides whether the columns belong in the model. They are not on the baseline list (`is_home`, count columns, form columns, odds columns). `feature_source_names()` is still games, player_game_stats, and game_odds_snapshots.
- The name matcher is not called. A non-G-League line with a null player id increments `unmatched_listed_n`. Wiring the matcher waits on the open matcher follow-up.
- If `nba_injury_report_rows` exists and is empty, an export marks every game missing. It does not fall back to snapshots. A database without the table still uses snapshots.
- WNBA rows do not read these reports. Their four new columns stay NULL.

## Pstack steps

1. Smallest change: ran. The reported path in `absence.py`, `load.py`, `build_dataset.py`, and `sources.py` was extended. No second pipeline.
2. Name the shape: ran. The shapes above were fixed before the loader and the dataset wiring.
3. Prove it: ran. The Harden builder returned 62.67 with both reports present. The tip-time call returned 51.83 only when asked at the tip with a fresh refresh. An empty report list returned NULLs and `injury_report_missing` 1. Command: the 21-test file above.
4. Blast radius: ran. `backend/app/main.py` has no `app.ml` import, and `test_importing_the_api_does_not_import_app_ml` passed with `DATABASE_URL` empty. `git diff --name-only` does not include the fetcher, parser, matcher, 151/152 files, `features.py`, `game_odds.py`, or `docs/progress.md`. Official SQL strings are `SELECT` only and do not name `predictions`. The stand-in test shows the four new columns stay NULL on `source='actual'`. One safety fact: starting the API does not import `app.ml`. Proved by that test and by reading `main.py`.
5. Explain the numbers: ran. 62.67, 51.83, 75.0, 85/140, and the test totals are sourced in the Tests section. 1746 passed, 283 skipped, and 3 xfailed come from `pytest tests` in `backend/` with `DATABASE_URL` empty.
6. Mutation check: ran. Both edits were reverted. The 21-test file was green afterward, and the full suite was green after the revert (1746 passed, 283 skipped, 3 xfailed).

## Mutation check

(a) Removed `if not known_at(row.report_at, as_of): continue` inside `select_official_report`, then ran the Harden test and the one-second-after-T test.

- Harden test failed: `assert 0.0 == 62.67`.
- One-second test failed: `assert 0.0 is None`.

The value was 0.0, not the leaked 51.83. `team_absences` still ignores a snapshot time after T. The later report became the chosen report and then contributed no listings, so the good T report was dropped and the minutes became 0. The filter was put back.

(b) In `features_when_official_report_missing`, the NULL minute dict was replaced with 0.0 for each minute and share column. The no-report test failed: `assert 0.0 is None` on `team_missing_minutes`. The NULL dict was put back.

## Progress notes (for the docs PR)

SPO-153 points the reported absence features at `nba_injury_report_rows` known at tip minus 3 hours, with `bdl_game_id` filtering, Available mapped to 0, and the four new columns. A missing report is NULL plus `injury_report_missing=1`. NOT YET SUBMITTED is NULL for that team only. A team left off a covering report is 0 minutes. Box-score stand-ins do not fill the new columns. The Harden check is 62.67 from the 12:15 PM fixture rows, not 51.83 from the tip report. Weights are unchanged. The matcher is not wired. The baseline feature list is unchanged. No production default was flipped. SPO-154 and SPO-155 are still open.
