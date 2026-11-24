# SPO-157 — Injury-parser follow-up fixes

- **Ticket:** SPO-157
- **Branch:** `feature/SPO-157-injury-parser-fixes`
- **Base:** `dev` (`ec8b7db`, SPO-150 / #129)
- **Repo:** public, and it stays public

## Architect sketch

Written before the clock guard and the upsert. The QA file stays the source of truth for the spring-forward title and for the fall-back hour.

### Clock (`_eastern_instant`)

Input is a year, month, day, hour, minute, and AM/PM. Output is an aware UTC `datetime`, or `None`.

1. Fold a two-digit year into the 2000s. Map 12 AM to hour 0 and a PM hour other than 12 onto the 24-hour clock.
2. Build `datetime(..., tzinfo=America/New_York)`. `fold` stays 0. An impossible calendar day raises `ValueError` and returns `None`.
3. Fall-back: `fold` 0 is the earlier offset. `11/03/24 01:30 AM` is 05:30 UTC, not 06:30 UTC. A short comment in the function says so. The QA test locks this. Do not flip it.
4. Spring-forward: `datetime` does not raise for a missing minute. `2024-03-10 02:30` becomes 07:30 UTC, and converting that instant back to Eastern is 03:30. Compare the requested hour and minute with the hour and minute after UTC and back to Eastern. If either differs, return `None`. Do not substitute 03:00 or 03:30.
5. `None` means the title or the filename is not `report_at`. Last-Modified, then a filename that names a real minute, still apply through `_fallback_time`.

### Upsert (same natural key, new status)

The key stays `(league, report_at, game_date, matchup, team_name, player_raw, not_yet_submitted)`. Status and reason are not added to it.

`INSERT ... ON CONFLICT ON CONSTRAINT nba_injury_report_rows_natural_key DO UPDATE` sets the columns a re-issued PDF can correct:

- `game_time_et`
- `bdl_game_id` — `COALESCE(EXCLUDED.bdl_game_id, nba_injury_report_rows.bdl_game_id)`
- `bdl_team_id` — `COALESCE(EXCLUDED.bdl_team_id, nba_injury_report_rows.bdl_team_id)`
- `status`
- `reason`
- `category`
- `previous_status`
- `all_players_available`

`bdl_player_id` and `match_method` stay out of the `SET` list. They are null until a later match, and a re-ingest must not wipe them. A resolved game id is kept the same way: when this file cannot resolve the game, `EXCLUDED.bdl_game_id` and `EXCLUDED.bdl_team_id` are null, and `COALESCE` leaves the stored ids in place.

The `DO UPDATE` has a `WHERE` of `IS DISTINCT FROM` on those same columns. For the two ids, the comparison is against the `COALESCE` value that will actually be written, so a miss is not a write. An identical row is not updated and `RETURNING 1` returns nothing. `rows_written` counts inserted rows, rows whose corrected columns actually changed, and rows deleted because the new file no longer names them.

The newest successful file for a given report minute replaces that minute's rows. In the same transaction as the upserts, rows for this `(league, report_at)` whose natural key is not in the parsed set are deleted. The natural key is `(league, report_at, game_date, matchup, team_name, player_raw, not_yet_submitted)`. Deletes are counted in `rows_written`. Rows for any other `report_at` stay. `dry_run` does not delete. An identical rerun deletes nothing, stays tag `unchanged`, and `rows_written` is 0.

`source_refreshes` is still one row per `(league, source, refreshed_at)`. The conflict update runs when the stored row is incomplete, when this call's `rows_written` is greater than 0, or when this call carries an error. An identical retry leaves that row alone (`RETURNING` empty, tag `unchanged`, `rows_written` 0). A real correction rewrites it with `complete=true` and this call's `rows_written`, and may clear `error`. A later failure at that same `refreshed_at` records `error` on the existing complete row. It does not set `complete` to false, and it does not change `rows_seen` or `rows_written`. It does not delete injury rows.

League `'nba'` is the constant `LEAGUE`, bound as a parameter. There is no WNBA source.

### Read order and index (migration 007)

006 is not edited. 007 `CREATE OR REPLACE`s `injury_report_rows_asof` with `ORDER BY team_name, player_raw, not_yet_submitted, matchup, id`. 007 drops `nba_injury_report_rows_game_report_idx` and creates it again on `(league, bdl_game_id, report_at)`.

## Summary

A title of `2024-03-10 02:30 AM` is not stored as 07:30 UTC. A PDF that is issued again with the same title minute can replace status, reason, and the other corrected columns. The point-in-time read returns those new values, in a stable order. `reportlab` is installed only for tests.

`rows_written` counts rows inserted, actually corrected, or deleted for that report minute. An identical second run still reports `unchanged` and 0. A real correction reports `stored` and the number of rows that changed or were removed, and the `source_refreshes` row for that report time is rewritten with `complete=true` and that same count. A later parse failure records `error` and leaves the earlier complete counts in place.

## Changes

| Area | Files | Change |
|---|---|---|
| Clock | `backend/app/services/injury_report_parser.py` | Reject a missing Eastern minute. Fall-back keeps the earlier offset |
| Ingest | `backend/app/services/injury_report_ingest.py` | Upsert corrected columns; bind `LEAGUE` |
| Migration | `backend/app/migrations/007_injury_report_rows_order.sql` | Stable `ORDER BY`; index leads with `league` |
| QA tests | `backend/tests/test_spo150_qa_edges.py` | 14 tests. Rollback reverses 007 before 006. The redundant `None != 07:30` check is gone |
| QA review | `backend/tests/test_spo157_qa_review.py` | A dropped player and a NOT YET SUBMITTED note are removed. A missed game id is kept. A later failure stores `error` |
| Corrected PDF | `backend/tests/test_spo157_corrected_report.py` | Status change, PIT read, identical retry |
| Order | `backend/tests/test_migration_007_injury_report_order.py` | 007 is a no-op the second time; row order |
| Version lists | migration runner, 001, 005, 006, SPO-130h, SPO-150 | Lists now include `007`. The `001`–`006` checks stay |
| Retry tag | `backend/tests/test_spo150_injury_report_rows.py` | The second ingest of the broken file must be `failed` |
| Deps | `backend/requirements.txt`, `backend/requirements-test.txt` | `reportlab` is test-only. Pin Pillow and pypdfium2 |
| CI / docs | `.github/workflows/ci.yml`, `README.md`, fixture README | Tests install both requirement files |

## Why

`datetime(..., tzinfo=America/New_York)` accepts `2024-03-10 02:30` and yields 07:30 UTC. A real 3:00 AM Eastern report is 07:00 UTC, so the missing minute sorts later and can be chosen at T. The natural key does not include status, and `ON CONFLICT DO NOTHING` kept the first status when a corrected PDF used the same title minute. `reportlab` is imported only by tests, but `requirements.txt` is what the image installs.

## Tests

Red before the fix, on a throwaway Postgres 16 listening on port 5441 (Docker is not installed here):

- `test_a_title_in_the_spring_forward_gap_is_not_the_report_clock` failed: `report_at_source` was `title`, not `last_modified`.
- `test_a_corrected_pdf_replaces_status_and_an_identical_retry_does_not` failed: the second ingest was `unchanged` instead of `stored`.

After the fix, same server, Python 3.12.3 (3.11 is not installed on this machine):

- QA file: 14 passed, including the spring-forward test and the fall-back test (`11/03/24 01:30 AM` is 05:30 UTC).
- Corrected-PDF test: 1 passed. A later `injury_rows_as_of` and `injury_report_rows_asof` return Questionable / Personal Reasons. A third ingest of the same file is `unchanged`, `rows_written` 0, and the table still has one row.
- Migration 007 tests: 2 passed.
- Full backend suite: **1963 passed, 17 skipped, 4 xfailed, 0 failed** in 106.95s. The three `test_spo132b_optional_vpc.py::TestVpcIdConsole` failures did not appear. Terraform and Docker are not installed here.
- Ruff `E9,F63,F7,F82`: all checks passed.
- `git ls-files` has no `.pdf`. `grep reportlab backend/Dockerfile` prints nothing. `reportlab` is not in `backend/requirements.txt`.

Pins from a fresh `pip install pdfplumber==0.11.11` (nothing else in that environment): `Pillow==13.0.0` (license MIT-CMU) and `pypdfium2==5.15.2` (BSD-3-Clause and Apache-2.0). `pdfminer.six` came along as MIT. All three licenses are permissive. Those two pins are in `requirements.txt` next to `pdfplumber==0.11.11`.

007 was free: `git ls-tree` of `backend/app/migrations/` on every `origin` branch showed no `007_*.sql`. It was needed because 006 is already on `dev` and must not be edited. On a database that had only 001–006, the runner applied `['007']`, and the next run applied `[]`. The new index is `(league, bdl_game_id, report_at)`.

### QA assertions that changed, and why

- Spring-forward filename with no Last-Modified (`Injury-Report_2024-03-10_02AM.pdf`). The test asked for `tag == "ok"` and a `report_at` other than 07:30 UTC. `02AM` means 02:30, which does not exist, and nothing else supplies a clock. Returning `None` makes the parse `failed`. Making it `ok` would invent an instant inside or past the gap, which this ticket forbids. The assertion is `tag == "failed"` and `report_at is None`. A second comparison of that `None` with 07:30 UTC was redundant and is gone. The title half of that test is unchanged: Last-Modified wins, and the instant is not 07:30 UTC.
- `test_a_changed_status_at_the_same_key_writes_zero_rows` locked `ON CONFLICT DO NOTHING` (status stayed Out, tag `unchanged`, 0 rows). That is the bug. It is now `test_a_changed_status_at_the_same_key_updates_the_row`: tag `stored`, `rows_written` 1, status Questionable, reason Personal Reasons, still one table row, refresh `complete=true` and `rows_written` 1. The check got stricter. It was not loosened.
- The QA database fixture asserted the last applied version was `006`. It now asserts `006` is in the list and the last version is `007`. `test_006_reverses_and_the_runner_applies_it_again` deletes version `007` before it reverses `006`, then expects the re-apply to be `['006', '007']`.

The second `ingest_report` in `test_spo150_injury_report_rows.py` used to accept `stored`, `unchanged`, or `failed`, so it could not fail. `iter_stored()` is path order, and `[0]` is the broken `01PM` file, not the good `05PM` file. The honest tag is `failed`. The test now asserts that filename and that tag.

## Mutation checks

1. Removed the UTC round-trip from `_eastern_instant` and returned `local.astimezone(UTC)` again. `test_a_title_in_the_spring_forward_gap_is_not_the_report_clock` failed: `assert 'title' == 'last_modified'`. The fall-back test still passed (fold 0 is still 05:30 UTC). Restored the round-trip. The spring-forward test passed again.
2. Replaced the row conflict clause with `DO NOTHING`. `test_a_corrected_pdf_replaces_status_and_an_identical_retry_does_not` failed: `assert 'unchanged' == 'stored'`. The renamed QA status test failed the same way. Restored the `DO UPDATE`. Both passed again.
3. Commented out the DELETE in `_write_report`. `test_a_player_dropped_from_the_corrected_pdf_is_removed` failed: `assert 'unchanged' == 'stored'`. Restored the DELETE. The full suite then passed.

## Blast radius

- **Migration runner.** Tests that listed `001`–`006` now also list `007`. None of those assertions were deleted. `test_002_tables_keep_columns` expects the pending tail to be `['005', '006', '007']`. 007 does not alter the 002 tables, and the index check in that test only looks at those tables. The full suite passed, including a second `upgrade()` that returns `[]`.
- **Point-in-time reads.** The existing boundary tests and the QA spring-forward and fall-back night tests passed. Two players in one report now come back by team name, then player name, even when inserted in the other order.
- **Identical retry.** `test_ingest_resolves_ids_and_a_second_run_writes_nothing` passed. The corrected-PDF test's third ingest is `unchanged` with 0 rows and no duplicate.
- **Docker image.** `backend/Dockerfile` still copies and installs only `requirements.txt`. It does not mention `reportlab` or `requirements-test.txt`. `pdfplumber` is still in `requirements.txt`. The image was not built: `docker` is not installed.
- **CI.** The backend-test job installs both requirement files and caches both. The production deploy workflow calls that same CI file. The staging deploy workflow does not. Compose does not pip-install.
- **Docs.** README's local backend notes say tests also install `requirements-test.txt`. The fixture README points at that file. Old task summaries were not edited. `docs/progress.md` was not edited.
- **`bdl_player_id`.** The upsert does not set it, so a later match is not cleared when the same PDF is stored again.
- **Same-minute replace.** `_write_report` is called only from `ingest_report`. `ingest_store` and `ingest_fetch_results` call that. The DELETE sits in the upsert transaction and keeps rows only for this `league` and `report_at`. `dry_run` returns before that transaction. An identical rerun is still `unchanged`, `rows_written` 0, and it does not rewrite a complete refresh row.
- **Later failure.** `_record_failure` writes `source_refreshes` only. Injury rows stay. `lineup_service` inserts `source_refreshes` with its own SQL, so this conflict clause does not change a lineup poll.
- **Resolved game.** A re-ingest that cannot find the game keeps `bdl_game_id` and `bdl_team_id`. `injury_rows_as_of` for that game still returns the updated status.

## QA follow-up

Python 3.12.3. Python 3.11 is not installed. Docker is not installed. The suite used a throwaway Postgres 16.15 listening on `127.0.0.1:5432` (not `5434`), with `DATABASE_URL` set to that server.

- `tests/test_spo157_qa_review.py` and `tests/test_spo150_qa_edges.py`: 27 passed.
- Full backend suite: **1976 passed, 17 skipped, 4 xfailed, 0 failed** in 105.39s.
- Ruff `E9,F63,F7,F82` on the edited Python files: all checks passed.

## Follow-ups

- SPO-151 can match `bdl_player_id`. This change does not clear that column.
- A filename that itself falls in the spring-forward gap, with no Last-Modified, is a failed parse. It is not turned into 03:00 or 03:30.

## Progress notes (for the docs PR)

SPO-157: a missing Eastern minute is not a report clock; a corrected PDF with the same title minute updates the stored row and replaces that minute's rows; a missed game id does not clear a resolved game; a later parse failure records the error and leaves the complete refresh in place; `injury_report_rows_asof` sorts its rows; `reportlab` is test-only. Migration `007`. No public route and no tracked PDF.
