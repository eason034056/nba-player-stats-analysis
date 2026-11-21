# SPO-138j — ML dataset as-of core

- **Ticket:** SPO-138j
- **Branch:** `feature/SPO-138j-ml-dataset-core`
- **Base:** `dev` (`6d9fa0a`)

## Summary

This PR adds an offline dataset export. One output row is one `player_game_stats` row. T is tip-off minus 3 hours. Features are prior played games only. Labels are `prop_actuals`, one target per market. The command writes Parquet and a metadata file. It does not write `predictions`, and it does not add a feature table.

`info_source` is `pregame` on every row. Game-odds features (138k) and absence stand-ins (138l) are not in this PR. Migrations 003 and 005 are not added and are not required. `prop_actuals` from 004 is reused.

## Changes

| Area | Files | Change |
|---|---|---|
| Sources | `backend/app/ml/sources.py` | Allow-list. This PR registers `games` and `player_game_stats` with a prior-date rule. `player_prop_snapshots` is rejected by name. `prop_actuals` is a label source, not a feature. |
| T | `backend/app/ml/asof.py` | `games.datetime_utc - hours_before_tip`. Default is 3. A NULL tip is 00:00 America/New_York on `games.date` itself: the hour offset is not applied again. The fallback is counted. It is not stored as a tip time. |
| Load | `backend/app/ml/load.py` | Read-only asyncpg, one season per query. The output window plus the previous season. DSN from the env var named by `--dsn-env`. Connection errors drop the URL and the password. An unreadable DSN (a raw `#` or `?`, including after percent-decoding) is replaced by a fixed message, so the driver text is never shown. |
| Features | `backend/app/ml/features.py` | Last 5 and last 10 played games (`dnp` false) for `pts`, `reb`, `ast`, `fg3m`, `stl`, `blk`, and `seconds_played`. Also `n_prev_games`, `n_played_prev`, `dnp_last_10`, `days_rest`, `is_back_to_back`, `is_home`, `season_type`. |
| Labels | `backend/app/ml/labels.py` | Pivot to `y_<market>`. All-NULL rows are dropped. A single NULL market stays NULL. Double-double and triple-double stay 0/1. |
| CLI | `backend/app/ml/build_dataset.py` | `python -m app.ml.build_dataset`. `--seasons START:END` is inclusive. Metadata is `<file>.meta.json`. |
| Deps | `backend/requirements.txt` | `pandas==3.0.1`, `pyarrow==23.0.1`. |
| Tests | `backend/tests/test_spo138j_ml_dataset.py`, `test_spo138j_ml_dataset_db.py`, `test_spo138j_qa_review.py`, `test_spo138j_qa_review2.py` | In-memory boundaries, a scratch database with 002 and 004, and the review checks for password pieces, a decoded or short piece, and the NULL tip. |

`dnp_last_10` counts DNP rows among the last 10 prior player rows (date, then game id), not among the last 10 played games. `dnp_last_10_window` is how many rows that count used. A short played window is NULL plus `n_played_prev`. It is not a partial mean and not a zero.

The package is larger than the 600-line sketch (about 1,100 lines across the six modules). The loader, the CLI, and the Parquet writer are the extra bulk. 138k and 138l are still out.

## Why

- **The model must not see the line.** `player_prop_snapshots` is named in the rejection, so a later query cannot treat it as a source we merely forgot.
- **Stats use a stricter cut than a timestamp.** A game on the target date is excluded even when its tip is already before T. The target game and any later game are excluded with the same check.
- **T is 3 hours, not 60 minutes.** `--hours-before-tip` and `prediction_instant` both default to 3. A known tip still subtracts that offset. A missing `datetime_utc` is 00:00 America/New_York on `games.date`, and that midnight is not shifted by the offset.
- **One prior season is loaded on purpose.** Output season 2015 still sees 2014. If that is still fewer than 5 or 10 played games, the mean is NULL and the count says how many games existed.
- **DNP is void.** It stays out of the played means, it counts in `dnp_last_10`, and a DNP label row is dropped because every actual is NULL.
- **The work stays out of the API process.** `app.main` does not import `app.ml`. The export is a CLI. The connection is read-only.

## Tests

Pins: `pandas==3.0.1` and `pyarrow==23.0.1` install and import on Python 3.11.18.

```
cd backend
DATABASE_URL="" python -m pytest tests/test_spo138j_ml_dataset.py -q
DATABASE_URL=postgresql://test:test@127.0.0.1:5441/test python -m pytest tests/test_spo138j_ml_dataset_db.py tests/test_spo138j_qa_review.py tests/test_spo138j_qa_review2.py -q
```

- In-memory: 20 passed. Timestamp boundary (one second before T, exactly T, one second after). Prior-date rule, including a same-day game whose tip is already before T. Allow-list, including `player_prop_snapshots`, and `prop_actuals` refused as a feature. Own game, later game, and same-day game do not change means. Shuffled input and a season boundary produce the same 2015 row. DNP, per-market NULL, all-NULL drop, short history, a NULL stat inside a full window, trade / home-away, NULL tip. Parquet and metadata round-trip. API import does not load `app.ml`.
- Scratch Postgres 16 on `127.0.0.1:5441`, migrations 002 and 004 only: 2 passed. CLI from loader through labels to Parquet. Cross-season last-5, DNP drop, NULL threes with a kept row, double-double 1 and triple-double 0, same-day exclusion, NULL-tip fallback, away game after a team change. `predictions` stayed empty. A read-only connection could not `CREATE TABLE`.
- Queries are `SELECT` only. No `home_score`, no `player_prop_snapshots`, no `predictions`.

**Mutation check** (reverted before commit):

- Prior-date guard `row_date < target_date` changed to `<=`. `test_own_game_later_game_and_same_day_game_do_not_change_features` failed with `assert 7 == 5` (the same-day game and the target entered the played window). `test_games_and_stats_use_the_prior_date_rule_including_same_day` failed with `assert not True`.
- T guard `observed_at <= as_of` changed to `<`. `test_timestamp_boundary_includes_t_and_excludes_the_next_second` failed on the exactly-T assertion (`assert False`).

Both edits were reverted. The same commands then passed again (20 and 2).

QA review file `tests/test_spo138j_qa_review.py`: 5 passed on scratch Postgres 16 (`127.0.0.1:5441`), migrations 002 and 004 only. Together with the database tests that is 7 passed. The in-memory file stayed at 20 passed.

- A password containing `#`, `/`, or `?` does not appear on stderr, and the CLI does not print `postgresql://`. `urlsplit` leaves that password empty, so the redaction also removes the raw userinfo password and the pieces split on those three characters.
- A NULL tip is 00:00 America/New_York on `games.date`. Winter `2026-01-15` is 05:00 UTC. Summer `2026-07-15` is 04:00 UTC, and `hours_before_tip=6` does not move it. A known tip of `2026-01-16 00:30` UTC is still `2026-01-15 21:30` UTC.
- The Parquet file, the metadata, and stdout omit the DSN. An empty 2015 export has `row_count` 0.

**QA mutation check** (reverted before commit):

- NULL-tip line changed back to `as_of = tip - timedelta(hours=hours_before_tip)` so the fallback subtracted hours again. `test_null_tip_t_is_new_york_midnight_on_the_game_date` failed: `datetime(2026, 1, 15, 2, 0, tzinfo=UTC)` against `datetime(2026, 1, 15, 5, 0, tzinfo=UTC)`.
- Password-piece redaction removed. `test_cli_never_prints_part_of_a_password_with_an_unencoded_separator` failed for `#`, `/`, and `?` (3 failed). The driver message contained the password piece before the separator.

Both edits were restored. The three commands then passed again: 20, and 7 (2 database + 5 review).

Second review file `tests/test_spo138j_qa_review2.py` is applied as written: 3 passed. A password that percent-encodes `@` or `/` and still has a raw `#` or `?` does not print the decoded piece. A first piece shorter than 4 characters does not print either. The CLI exits 1, does not print `postgresql://`, and shows `invalid DSN: percent-encode every special character in the password` instead of the driver text.

**Second QA mutation check** (reverted before commit):

- The `ValueError` handler in `connect_readonly` was removed, so the driver text was printed again. `test_cli_never_prints_a_decoded_or_short_password_piece` failed on all 3 cases.

The handler was restored. In-memory plus the second review file: 23 passed. Database plus the first review file: 7 passed. That is 30 tests in all (20 + 2 + 5 + 3).

Known failures that are not this ticket: 3 tests in `test_spo132b_optional_vpc.py::TestVpcIdConsole`. They fail the same way on clean `origin/dev`. This PR does not change them.

## Follow-ups

- [ ] SPO-138k: opening game-odds features, median across books, visible at T.
- [ ] SPO-138l: absence stand-ins. `info_source` stays `pregame` until that lands.
- [ ] When migration 005 exists, compare `prediction_instant` with `game_as_of`. This PR does not depend on 005.
- [ ] A player with fewer than 10 played games in the loaded window (output seasons plus one prior season) keeps NULL means. More history is a later choice, not a fabricated mean.

## Progress notes (for the docs PR)

- SPO-138j: offline dataset export. One `pregame` row per `player_game_stats` line, T = tip-off minus 3 hours, form features from prior dates, labels from `prop_actuals`. Parquet out. No feature table and no writes to `predictions`.
- SPO-138j QA: a NULL tip stays at 00:00 America/New_York on the game date (the hour offset is not applied again). A connection error masks a password that contains `#`, `/`, or `?`, and the CLI does not print the URL. An unreadable DSN, including one the driver percent-decodes, is replaced by a fixed message.
