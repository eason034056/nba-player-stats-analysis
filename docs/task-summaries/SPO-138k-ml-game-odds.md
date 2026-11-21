# SPO-138k — ML dataset: as-of opening game-odds features

- **Ticket:** SPO-138k
- **Branch:** `feature/SPO-138k-ml-game-odds`
- **Base:** `dev` (`5b65b58`, which contains SPO-138j at `b5da8c5`)

## Summary

Opening game odds are now features on the SPO-138j dataset row. The cutoff is the same T: tip minus `--hours-before-tip` (default 3), or 00:00 America/New_York on the game date when the tip is NULL. That midnight is not shifted again.

A row is eligible only when `snapshot_kind` is `opening` and `snapshot_at` is non-NULL and `snapshot_at <= T`. The median home spread and the median total are taken across those books. NULL numbers are skipped per column. The player's team and the opponent then get `total / 2 - team_spread / 2`. Home uses the median home spread. Away uses its negation. Home -4 and total 220 is 112 and 108. No eligible number stays NULL. It is not stored as zero. Book counts are recorded beside the values. One player-game stays one row.

The real-database timing of game-odds openers is **PENDING**. The SQL is in the repo. Nothing in this change treats those openers as tip minus 3 hours, and nothing hard-codes one book or twelve books.

## Changes

| Area | Files | Change |
|---|---|---|
| Allow-list | `backend/app/ml/sources.py` | `game_odds_snapshots` is a timestamped feature source. `opening_game_odds_visible` keeps an opening row only when `snapshot_at <= T`. Live, closing, a NULL timestamp, and a timestamp after T are not visible. |
| Features | `backend/app/ml/game_odds.py` | Median `spread_home_value`, median `total_value`, team and opponent implied points, and the three book counts. |
| Load | `backend/app/ml/load.py` | Read-only `SELECT` of opening rows with a non-NULL `snapshot_at`, one season at a time. The time cutoff stays in Python so T is not copied into SQL. |
| Export | `backend/app/ml/build_dataset.py` | The same `prediction_instant` result is passed into the odds features. Metadata records the new columns, row coverage, the limitation, and `game_odds_measurement: PENDING`. |
| Measurement | `docs/decisions/SPO-138/game-odds-opener-timing.sql`, `game-odds-opener-timing.md` | Exact SQL for the season buckets and the per-game book counts. Status PENDING. No DSN. |
| Tests | `backend/tests/test_spo138k_ml_game_odds.py`, `test_spo138k_ml_game_odds_db.py` | Boundaries, medians, implied points, one row per player. The 138j allow-list assertions now include `game_odds_snapshots`. |

Columns added, in order: `opening_spread_home`, `opening_total`, `team_implied_points`, `opp_implied_points`, `opening_books`, `opening_spread_books`, `opening_total_books`. Counts are 0 when nothing qualified. The four values are NULL in that case. A spread of 0 is a real line.

`dnp_last_10` and the played-game means are unchanged. `info_source` stays `pregame`. Migrations 003 and 005 are not required. `player_prop_snapshots` is still rejected by name. Closing and live game odds are not selected and are not features. The command still does not write `predictions`.

An opening row is one per game and book. `snapshot_at` is BDL `opened_at` and is not part of that key, so a retry can change the timestamp and the values. The row is not an immutable first-observed history. A historical import shows that BDL published a value at `opened_at`. It does not show that this application polled that value then. That note is in the metadata and in the timing doc.

## Why

- **One T.** Odds use `prediction_instant`, including the NULL-tip midnight. A second cutoff in SQL would drift from `--hours-before-tip` and from that midnight. The loader only drops non-opening rows and NULL timestamps.
- **The line is not a feature.** Player props stay off the allow-list. Game odds are the median spread and total, not a price and not a prop line.
- **NULL is not zero.** A missing book, a missing spread, or a missing total does not become 0. Counts say how many books were eligible and how many supplied each number.
- **Books do not multiply rows.** The median is attached to the player-game. Two players in one game are two rows with the same odds features.
- **Book counts are data.** The handoff estimate (about one book in 2020-25, about twelve from 2026) is not a constant. The timing SQL is how that estimate gets checked.
- **Prop openers are not game-odds openers.** Two probed prop openers sat at tip minus 3 hours. Game-odds openers have not been measured. T was not moved to match that probe.

## Tests

```
cd backend
DATABASE_URL="" .venv/bin/python -m pytest tests/test_spo138k_ml_game_odds.py tests/test_spo138j_ml_dataset.py -q
DATABASE_URL=postgresql://test:test@127.0.0.1:5441/test .venv/bin/python -m pytest tests/test_spo138k_ml_game_odds_db.py tests/test_spo138j_ml_dataset_db.py tests/test_spo138j_qa_review.py tests/test_spo138j_qa_review2.py -q
```

Throwaway PostgreSQL 16.15 on `127.0.0.1:5441`. Not `127.0.0.1:5434`. The URL above is that local server. `ruff check` with `--select E9,F63,F7,F82` passed on the touched Python files.

- In-memory, `DATABASE_URL=""`: 32 passed. 12 are new. 20 are the SPO-138j file. Opening versus live/closing, NULL `snapshot_at`, one second before T, exactly T, one second after T. NULL-tip T is 05:00 UTC on 2026-01-15, and a 04:00 UTC line stays in (it would fall out if the midnight were shifted by another 3 hours). Odd and even medians, NULL values skipped per column, no rows, a spread of 0, home 112 / away 108, unknown home team, two players staying two rows, a non-default `--hours-before-tip`, a duplicate visible book rejected. Metadata coverage and `PENDING`. The odds SQL is a `SELECT` and does not encode T.
- Scratch Postgres, `DATABASE_URL=postgresql://test:test@127.0.0.1:5441/test`: 12 passed. 2 are new (CLI through Parquet, and the timing SQL parses). 2 are the SPO-138j database file. 5 are the first QA file. 3 are the second QA file. The CLI case: two books at or before T median to spread -5 and total 220 (home 112.5 / 107.5); an after-T book, a closing book, a live book, and a NULL timestamp do not enter; a half-point away line is 108 and 112.5; a NULL tip keeps the line from an hour before midnight and drops the line from one second after. Four player-games, not one row per book. `predictions` stayed empty. The timing script returns columns on the fixture. Those numbers are not the real-database measurement.

**Mutation check** (reverted before commit):

- `row_is_visible` returned true for every non-NULL timestamp, so an opening book one second after T was kept. `test_boundary_includes_t_and_an_after_t_book_does_not_move_the_median` failed with `assert 3 == 2` (`opening_books`). `test_timestamp_boundary_includes_t_and_excludes_the_next_second` failed with `assert not True` on the one-second-after case.

The comparison was restored to `snapshot_at <= T`. Those two tests then passed.

Known failures that are not this ticket: 3 tests in `test_spo132b_optional_vpc.py::TestVpcIdConsole`. They fail the same way on clean `dev` when terraform is installed. This run skipped them because terraform is not on PATH.

## Follow-ups

- [ ] Run `docs/decisions/SPO-138/game-odds-opener-timing.sql` on a sanitized read-only database and replace PENDING with the season aggregates. Do not change T from that result without a new decision.
- [ ] SPO-138l: absence stand-ins. `info_source` stays `pregame` until that lands.
- [ ] Do not hard-code a book count from the handoff estimate. The measured per-game counts are the check.

## Progress notes (for the docs PR)

- SPO-138k: opening game-odds features on the dataset row. Same T as SPO-138j, including the NULL-tip midnight. Median home spread and total across opening books with `snapshot_at <= T`. Implied points are `total/2 - team_spread/2`. No prop odds, no closing or live game odds, no writes to `predictions`.
- SPO-138k: game-odds opener timing against the real database is PENDING. The SQL is `docs/decisions/SPO-138/game-odds-opener-timing.sql`. An opening row is not an immutable first post, and a historical import does not show that this application polled the value at `opened_at`.
