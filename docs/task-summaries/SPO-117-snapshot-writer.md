# SPO-117 — Snapshot writer, alternate lines, and the mode tie

- Ticket: SPO-117
- Branch: `feature/SPO-117-snapshot-writer` (from `origin/dev` at `7fcf31f`)
- Base: `dev`

## Summary

The scheduled `odds_line_snapshots` writer stored 0 rows because it filtered the UTC date with the UTC+8 offset. It now uses the America/New_York game date. Each two-sided total is its own row, and the unique key includes `line`, so an alternate does not replace the main total. Bulk props and daily analysis vote each book's main line, then take the mode. A tie keeps the line closest to even money, then the lower posted line. It is not an average.

WNBA daily analysis still uses the same mode function. Its date and offset are unchanged. There is no WNBA snapshot writer.

## Changes

| Area | File | Change |
|---|---|---|
| Clock | `backend/app/services/odds_snapshot_service.py` | `nba_slate_date` and `offset_for_us_game_date`. `take_snapshot` defaults to the Eastern date and offset. Parser pairs Over and Under by point. Upsert conflict target includes `line`. A failed `executemany` is logged as `error` and re-raised. |
| Schedule | `backend/app/services/scheduler.py`, `backend/app/api/odds_history.py` | The three jobs and the manual trigger call `take_snapshot()` with no UTC date. An explicit date is still passed through. |
| Schema | `backend/app/services/db.py` | `odds_line_snapshots_book_line_key` on `(snapshot_at, event_id, player_name, market, bookmaker, line)`. Idempotent `DO` block drops any unique constraint on that table that does not include `line`, then adds the named key. |
| Consensus | `backend/app/services/prob.py`, `backend/app/services/daily_analysis.py`, `backend/app/services/bulk_props.py` | `calculate_mode_threshold(lines, distances=None)`. `_main_line_vote` / `_group_main_votes` supply the even-money distance. `assemble_bulk_props` passes one distance per book. |
| Tests | `backend/tests/test_spo117_snapshot_writer.py`, `test_spo114_qa_review.py`, `test_spo114_bulk_props.py`, `test_scheduler.py` | Recorded events and player-points bodies. Postgres commit and the migration. Tie cases. |
| Docs | `docs/decisions/spo-117-snapshot-writer/decision_20261110_line-key-and-mode-tie.md` | Empty-table cause, why the key is wider, and the tie rule. |

## Why

The recorded Hawks tip `2026-11-10T00:10:00Z` is 19:10 on 2026-11-09 in New York. UTC date 2026-11-09 plus offset 480 does not contain it, so the mid job wrote nothing and still logged success. Eastern date 2026-11-09 with offset -300 contains the evening slate.

The old unique key plus a last-Over/last-Under parser stored one row per book. Bovada's last alternate replaced the main total, so the read-side collapse never saw the ladder. Adding `line` is safe on existing rows because the new key is a superset of the old one.

A tied mode used to average the two central values when every line appeared once (24.5 and 25.5 became 25.0; the four-value docstring example returned 25.25). Nobody posted that number. SPO-115 already kept a posted point inside one book. The cross-book rule is the same idea: closest to even money, then the lower line. Within one unpriced book, `_posted_point` stays the SPO-115 central posted point. That path has no prices to compare.

`run_daily_analysis` still defaults to offset 480. That call is the viewer's "today", not the snapshot table.

## Tests / Verification

- Backend pytest: `cd backend && /tmp/nba-venv/bin/python -m pytest -q --tb=line` → 1050 passed, 23 skipped, 6 xfailed, 0 failed.
- Frontend: not touched.
- Integration test: the snapshot insert and the migration ran against local Postgres inside the unit suite. `RUN_INTEGRATION` was not set.
- Fabrication scan: PASS. Event and odds bodies are `tests/fixtures/odds_api_events__basketball_nba.json` and `tests/fixtures/odds_api_event_odds__player_points.json`. The 2–2 tie copies one recorded rung onto another recorded bookmaker key so the counts match. Prices are the recorded prices.

## Follow-ups

- [ ] `run_daily_analysis` still defaults to UTC+8. Leave it until a ticket separates the viewer's local date from the US slate on purpose.
- [ ] `_posted_point` (no prices, inside one book) still uses the central posted point. The cross-book tie uses even money, then the lower line. They are different rules on purpose.
- [ ] Move `_main_book_line` and `_even_money_distance` to a shared module. Already noted on the #47 QA backlog.
