# SPO-150 — Parse official injury-report PDFs into rows

- **Ticket:** SPO-150
- **Branch:** `feature/SPO-150-parse-injury-report-rows`
- **Base:** `dev` (`5168c7d`, SPO-149)
- **Repo:** public, and it stays public

## Architect sketch

PDF bytes, the database, and the clock stay at the edges. Row assembly is pure. Callers match `tag`. They do not catch an exception to learn that a PDF failed.

- `ReportLayout` — `A` (iText, Category and Previous Status), `B` (iText, status and reason), `C` (GemBox, status and reason).
- `InjuryRow` — frozen. `game_date`, `game_time_et`, `matchup`, `team_name`, `team_abbr`, `player_raw` (`""` on a team note), `status`, `reason`, `category`, `not_yet_submitted`, `all_players_available`, `previous_status`.
- `ParsedReport` — `tag="ok"`, `layout`, `report_at` (UTC), `report_at_source` (`title`, `last_modified`, or `filename`), `rows`, `pagebreak_joins`, `unattached_reasons`. `player_rows` and `nys_rows` are counts.
- `ParseFailure` — `tag="failed"`, `error`, optional `report_at`.
- `ParseResult` — `ParsedReport | ParseFailure`.
- `parse_pdf(data, *, last_modified=None, filename=None) -> ParseResult`.
- `OFFICIAL_SOURCE` — `"injuries_nba_official"`. The BALLDONTLIE list stays `"injuries"`.
- `IngestOutcome` — `tag` is `stored`, `unchanged`, `failed`, or `dry_run`.
- `ingest_report(conn, stored, *, dry_run=False) -> IngestOutcome`.
- `ingest_store(conn, store, *, dry_run=False) -> list[IngestOutcome]`.
- `ingest_fetch_results(report)` — scheduler hook. Returns immediately when `results` is not a tuple, when nothing was stored, or when the pool is down.
- `injury_rows_as_of(conn, bdl_game_id, *, league="nba", as_of=None)` — calls SQL `injury_report_rows_asof`. `as_of=None` uses `game_as_of` (tip minus 3 hours).

The natural key is `(league, report_at, game_date, matchup, team_name, player_raw, not_yet_submitted)`. Inserts use `ON CONFLICT DO NOTHING`. A `source_refreshes` row updates an existing row only when that row is `complete=false`, so a success is not overwritten and a later success can replace a failure. `bdl_player_id` and `match_method` stay null (SPO-151). Writing into `injury_snapshots` was skipped.

## Summary

Stored injury-report PDFs become rows in `nba_injury_report_rows` (migration 006). Each stored report also gets one `source_refreshes` row under `injuries_nba_official`. The point-in-time read for a game is the latest report with `report_at <= T`, where T is `games.datetime_utc` minus 3 hours, the same instant as `game_as_of()`. A report at T is selected. A report one second later is stored and is not selected.

There is no new HTTP route, page, or feed. No PDF and no report text are committed. Player ids are not matched.

## Changes

| Area | Files | Change |
|---|---|---|
| Parser | `backend/app/services/injury_report_parser.py` | Three layouts, title clock, page-break join |
| Ingest | `backend/app/services/injury_report_ingest.py` | Resolve game and team ids, idempotent write, PIT read |
| Cache walk | `backend/app/services/injury_report_store.py` | `iter_stored` reads sidecars already on disk |
| CLI | `backend/scripts/ingest_injury_reports.py` | `--dry-run`, counts only, no DSN printed |
| Scheduler | `backend/app/services/scheduler.py` | After a flagged fetch, parse what that tick stored |
| Migration | `backend/app/migrations/006_injury_report_rows.sql` | Table, natural key, game/report index, `injury_report_rows_asof`, new source value |
| Dependencies | `backend/requirements.txt` | `pdfplumber==0.11.11`, `reportlab==5.1.1` (tests only) |
| Tests | `backend/tests/test_spo150_injury_report_rows.py`, `test_migration_006_injury_report_rows.py` | Synthetic PDFs and the 006 checks |
| Fixtures | `backend/tests/fixtures/injury_report_rows/README.md` | `synthetic: true` |
| Version lists | migration runner, 001, 005, two SPO-130h tests | Shipped versions now include 006 |

## Why

- **The title clock wins.** The title line is `Injury Report: MM/DD/YY HH:MM AM/PM` in Eastern time, and that minute is what `report_at <= T` has to hit. Last-Modified is the file write a few seconds later (for example 22:30:07 when the title is 22:30:00 UTC). Using Last-Modified would miss a decision at the labeled minute. Last-Modified is used only when the title is missing. An hour-format filename (`05PM`) means HH:30, the same rule as SPO-149, and is used only when both of the others are missing.
- **Layout comes from the header first.** Category and Previous Status together mean layout A, even if the producer string is odd. Otherwise a GemBox producer is C, and anything else with the status/reason header is B. A team with nothing to report is absent. `NOT YET SUBMITTED` and `ALL PLAYERS AVAILABLE` are team rows, not players.
- **A reason line joins the nearest anchor within 16 points.** That sits between a wrap of about 7 points and the next player at about 22 points. A reason at the top of a page with no anchor that close joins the last row of the previous page. Date, time, matchup, and team carry down when the next line leaves them blank.
- **Re-ingest writes nothing new.** The natural key plus `ON CONFLICT DO NOTHING` makes the injury rows idempotent. The refresh row is inserted once. A second success sees `rows_written = 0` and no refresh update, and is reported as `unchanged`.
- **A bad PDF does not stop the batch.** The failure is a `source_refreshes` row with `complete=false` and `error` set. The error is the exception type, or a short parser message. It is not the PDF bytes.
- **Game and team ids come from `games` and `teams`.** The matchup is `AWAY@HOME`. Abbreviations are folded (`GS` to `GSW`, and the same six aliases the rest of the app uses). A postponed game loses to a non-postponed game on the same date and matchup. An unresolved id stays null. No player id is filled.

## Tests

Throwaway PostgreSQL 16 on `127.0.0.1:5441`, database `test`. Not port 5434. Docker was not used. `DATABASE_URL` was set explicitly for pytest.

Behavior tests in `test_spo150_injury_report_rows.py` (13) and `test_migration_006_injury_report_rows.py` (4):

- Layouts A, B, and C, including a two-comma name, a wrapped reason, a page-break join, `NOT YET SUBMITTED`, `ALL PLAYERS AVAILABLE`, and today plus tomorrow in one report.
- Title beats a Last-Modified seven seconds later. Filename time is used only when the title is missing, and Last-Modified beats the filename.
- Ingest resolves `bdl_game_id` and `bdl_team_id`. A second ingest is `unchanged` and the row count stays put. `--dry-run` writes nothing.
- A broken PDF records `complete=false` with an error, and the next PDF in the batch still loads.
- A report at exactly T is selected. A report at T+1s is stored and is not selected. `game_as_of` with no explicit time selects the same row.
- The scheduler does not ingest when `INJURY_PDF_FETCH_ENABLED` is false. When the flag is on, the handler calls ingest after the fetch.

The behavior tests were written after the parser already matched four real files, and they passed on the first run. The mutation checks below are the red runs.

**Full backend suite** (`pytest -q`, same throwaway Postgres, after the category prefixes): **1946 passed, 17 skipped, 4 xfailed, 0 failed** (109.46s). `test_spo132b_optional_vpc.py::TestVpcIdConsole` did not fail. The 4 xfailed marks are the ones already in `test_spo104_qa_review.py` and `test_spo132e_qa_verify_edges.py`.

`git ls-files | grep -i '\.pdf$'` printed nothing.

### Private parser check (counts only)

79 files from `https://ak-static.cms.nba.com/referee/injury/`, saved under `/tmp/injury_sample/`, parsed, then deleted. Every file matched the baseline `player_rows` and `nys`. `pagebreak_joins` matched too.

| Layout | Files | player_rows | nys | page-break joins |
|---|---:|---:|---:|---:|
| A | 1 | 95 | 5 | 0 |
| B | 2 | 216 | 10 | 0 |
| C | 76 | 9202 | 406 | 70 |

Structural counters, all files: statuses outside the five = 0, team names outside the 30 = 0, team abbreviation missing from its matchup = 0, player names without a comma = 0, unattached reason lines = 0. `pdftotext -layout` lines that contain a `Last, First` name and one of the five statuses equaled `player_rows` on every file (0 files differed).

76 player rows had a reason whose prefix was not in the first list. The prefixes were category labels, and they were added: League Suspension 39, Concussion Protocol 25, Team Suspension 7, Coach's Decision 5 (ASCII apostrophe, plus the typographic apostrophe as a second spelling). After that, rows with a reason and a null category = 0, and the 79-file match was unchanged. No report prose was copied into git.

### CDN requests

79 GETs, sequential, at least one second apart, `User-Agent: sportslab-injury-pdf/1.0`. No HEAD. No retries. 4 were made while checking the parser on the first four files, and 75 while fetching the rest (`made=75`, `non200=[]`). Every response was HTTP 200 `application/pdf`. No 429, no 5xx, no HTML block page.

### CLI against the throwaway database

Three of those files were loaded through `python -m backend.scripts.ingest_injury_reports` into a database created for the run and dropped afterward. Games were seeded from the parsed dates and matchups (15 games). The files and the database are gone.

| File | rows seen | first write | second write |
|---|---:|---:|---:|
| `Injury-Report_2024-05-10_03PM.pdf` | 15 | 15 | 0 (`unchanged`) |
| `Injury-Report_2024-05-10_05PM.pdf` | 19 | 19 | 0 |
| `Injury-Report_2026-11-05_08_45PM.pdf` | 105 | 105 | 0 |

139 injury rows, 0 with a null game or team id, 4 `NOT YET SUBMITTED`, 3 `source_refreshes` rows with `complete=true`. Migration 006 applied as the sixth file. A second runner pass applied nothing.

For one game on 2024-05-10 (`NYK@IND`), tip was set so `game_as_of` equals that file's title time. The report has 7 rows for that game. `injury_report_rows_asof` returned 7. A synthetic row at that instant plus one second (`Late, One`) was inserted: 1 row stored, 0 selected, and the selected count stayed 7.

### Mutation checks

Each edit was restored, and the same tests then passed (3 passed).

1. **Drop `report_at <= T`.** Both PIT tests failed. The read returned `Late, One` (the report after T) instead of `On, Time`.
2. **Change `<=` to `<`.** Both PIT tests failed. The read returned `Old, Out` (the report before T) instead of `On, Time`.
3. **Disable the page-break join.** `test_layout_c_joins_a_wrapped_reason_and_a_page_break` failed: `unattached_reasons` was 1, and the assertion is 0. The orphan reason was no longer attached.

## Blast radius

| Surface | Result |
|---|---|
| Migration runner | `discover()` and the apply tests now expect `001` through `006`. A second `upgrade` is `[]`. Passed. |
| Tests that list shipped versions | Updated: `test_migration_runner.py`, `test_migration_001_baseline.py`, `test_migration_005_bdl_pit.py`, `test_spo130h_bdl_lineups.py`, `test_spo130h_qa_empty_snapshots.py`. `test_spo130g` and `test_spo130j` assert `applied[:5]` and were left as they are. Passed. |
| `test_migration_005` partial apply | The copy step now keeps versions before `005`, because 006 alters `source_refreshes` from 005. The second upgrade is `["005", "006"]`. The 002-table column, index, and trigger diffs were not given new expectations. Passed. |
| `injuries_asof` and `source_covered` | 005 was not edited. The 90-minute window was not widened. The 005 tests passed. |
| SPO-149 fetch, flag off | The job still returns before any HTTP call and before a parse. A new test asserts ingest is not called. Existing SPO-149 tests passed. The flag default is still false, so the job is not registered. |
| `source_refreshes` CHECK | `injuries_nba_official` was added. The six old values still insert. An unknown value still fails the check. |
| Dependencies | `pdfplumber` 0.11.11 is MIT. It pulls `pdfminer.six`, Pillow, and `pypdfium2` (about 8 MB for the native library, BSD/Apache). `reportlab` 5.1.1 is BSD and is imported only by tests, but it is in `requirements.txt`, so the backend image installs it. The image was not rebuilt here (`docker` is not available). CI installs `requirements.txt` and still rejects a tracked PDF. |
| Ruff | `ruff check . --select E9,F63,F7,F82` passed. `compileall` passed. |
| Public surface | No route, page, or feed was added. No player map was added. |

## Terms-limits checklist

- The repo stays public. No PDF file, no parsed dump, and no real report text were committed. CI's tracked-PDF guard still applies. `git ls-files | grep -i '\.pdf$'` printed nothing.
- No public route serves these rows.
- No unmatched-player list and no player-id map. `bdl_player_id` and `match_method` stay null.
- The private check used the CDN at one request per second, sequentially, with no HEAD, into `/tmp/injury_sample/`. The files were deleted.
- Use was not widened. A public site, a paid product, or a data feed is still out of scope.

## Follow-ups

- [ ] SPO-151: match `player_raw` to `bdl_player_id`. That mapping stays private.
- [ ] SPO-152: monitoring.
- [ ] No backfill of 2018-19 through 2020-21 in this ticket.
- [ ] Do not widen `source_covered`'s 90-minute window for this source.

## Progress notes (for the docs PR)

- SPO-150: parse stored official injury-report PDFs into `nba_injury_report_rows` (migration 006) and one `source_refreshes` row per report (`injuries_nba_official`). The read for a game is the latest report at or before tip minus 3 hours. Re-ingest is a no-op. A bad PDF records `complete=false` and the batch continues. No public route and no PDF in git. Player matching is still open (SPO-151).
