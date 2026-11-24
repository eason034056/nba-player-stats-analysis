# SPO-151 — Match injury-report names to BDL player ids

- **Ticket:** SPO-151
- **Branch:** `feature/SPO-151-injury-report-player-ids`
- **Base:** `dev` (`c7bf587`, #130)
- **Repo:** public

## Architect sketch

Written before the guard and the matcher.

### 0-row parse

`parse_pdf` can return `tag="ok"` with an empty `rows` tuple. That is a title and a header and no player lines. It is not a stored report.

`_write_report` classifies that file before the write transaction:

1. `player_rows == 0` and every remaining row is `NOT YET SUBMITTED` or `ALL PLAYERS AVAILABLE`: still a stored file. Upsert those team notes. Do not run `_DELETE_ABSENT`. Named rows already stored for that league and minute stay.
2. `player_rows == 0` and there is no team note (the empty file): return `_record_failure` with error `zero player lines`. Tag `failed`. No insert and no DELETE. A previous complete `source_refreshes` row keeps its counts and gains the error, which is the same later-failure rule SPO-157 already uses.

`dry_run` of the empty file is also `failed` and writes nothing. A file that names at least one player still deletes absent keys for that league and minute only.

### Matching

Pure function `match_report_name(player_raw, team_id, season, catalog, g_league) -> MatchDecision`.

`NameKey` is `(first, last)` after this fold, in this order:

1. Split `Last, First` on the last comma.
2. Strip accents. Turn hyphens into spaces. Drop other punctuation. Casefold.
3. Drop the tokens `jr`, `sr`, `ii`, `iii`, `iv`, `v`.

The alias table is a dict of folded `(first, last)` to the BDL spelling. It is not the props alias file. Required entries: Nic Claxton → Nicolas Claxton, Nate Williams → Jeenathan Williams, Sasha Vezenkov → Aleksandar Vezenkov. The report name and the alias name are both exact keys. Catalog names are not rewritten.

`CatalogPlayer` holds `bdl_player_id`, the BDL `first_name` / `last_name` / `position`, `memberships: frozenset[(team_id, season)]` from `player_game_stats`, and `current_team_id` plus `draft_year` from a `/v1/players` object. A season with stat rows uses those teams only. A season with no stat row uses `current_team_id` when it is set and `season >= draft_year` (no gate when `draft_year` is null). That is the payload team, not an invented history. A player with no stat rows can still match. `list_players` is unchanged and still rejects an empty id list. The unfiltered page is a new method, `list_players_page`, and `iter_pages` can walk it. No new fixture file: this VM has no BALLDONTLIE key, so the parser reads the player object already recorded in `players_ids_v2.json` and `backend_players_batch45.json`.

Steps, first hit, and only when that step has one player:

1. Exact name on that team and that season.
2. Exact name on any team that season.
3. Same team and season, `rapidfuzz.fuzz.token_sort_ratio` ≥ 88.
4. Same team and season, same surname, same first character, one player. Surname alone is not a match.
5. Exact name in a different season that has a stat membership. The payload team is not a second season.

`match_method` is `exact_team_season`, `exact_season`, `fuzzy_team`, `surname_initial`, `exact_other_season`, `unmatched`, or `unmatched_g_league`. G League is `g league` in the reason or the category. Both unmatched kinds stay on the row with a null `bdl_player_id`. Only `unmatched` is a review entry.

The review list is the return value of `match_report_rows`. An optional path appends JSON lines. Nothing in `app/api/` reads it. The log line is a count, not the names. `injury-report-unmatched/` is gitignored.

`ingest_report(..., catalog=None)` does not match. SPO-150 still sees null `match_method`. Passing a catalog runs the match after a `stored` or `unchanged` write, in a later transaction. The insert's `DO UPDATE` still does not set `bdl_player_id` or `match_method`. The match `UPDATE` only touches rows whose `match_method` is null, so a value already stored (the QA `'held'` rows) stays. Matched ids are upserted into `players` first because of the foreign key.

### 0-row rule

A successful parse with 0 player lines must not delete that league and minute. The empty file is `failed` and is not stored. A file that has only team-level rows is stored, and the absent-key DELETE does not run.

## Summary

An injury-report file that parses to a title and a header and no player lines is a failed ingest. The rows already stored for that league and that minute stay. A file that is only `NOT YET SUBMITTED` or `ALL PLAYERS AVAILABLE` is stored, and named rows at that minute are not deleted.

When the caller passes a player catalog, null `bdl_player_id` and `match_method` are filled. The name list is BALLDONTLIE `/v1/players` plus stat memberships, not the research box-score cache. Three public nicknames are aliases. A non-G-League miss stays on the row and is returned on a review list. There is no public route and no new migration.

The 2023-24 live sample (about 98.9% of rows, 98.4% of unique player-team-seasons) was not rerun. This repo is public, so official PDFs were not imported.

## Changes

| Area | Files | Change |
|---|---|---|
| Empty parse | `backend/app/services/injury_report_ingest.py` | Zero player lines and no team note is `failed`. Team notes skip `_DELETE_ABSENT`. Optional `catalog` fills ids after the write |
| Matcher | `backend/app/services/injury_report_names.py` | Fold, alias table, six-step match, parse a recorded `/v1/players` object |
| Write | `backend/app/services/injury_report_match.py` | Upsert `players`, update null methods, return the review list, optional JSONL file |
| Client | `backend/app/services/bdl_client.py` | `list_players_page` sends no `player_ids[]`. `list_players` still rejects `[]` |
| QA | `backend/tests/test_spo157_qa_review.py` | Removed the redundant `report_at != GAP_07` compare |
| QA | `backend/tests/test_spo157_qa_recheck.py` | Applied the uploaded recheck. The empty-file test now expects the row to stay and the tag to be `failed` |
| Tests | `backend/tests/test_spo151_player_ids.py` | Aliases, Jordan/Baba, rookie payload team, review list, recorded player page |
| Ignore | `.gitignore` | `injury-report-unmatched/` |

## Why

`_DELETE_ABSENT` treats a successful parse as the full set of keys for that minute. A header with no players is an empty set, so the DELETE removed every stored row. Marking that parse failed keeps the miss on `source_refreshes.error` and does not touch the injury rows. Team notes are real rows, but a file that dropped every name and kept only a team banner must not erase the names, so those files skip the DELETE.

`bdl_player_id` is a foreign key to `players`. The insert still writes null and the `DO UPDATE` still does not set the column, so a re-ingest cannot clear a match that was stored earlier. The match runs in a later statement and only where `match_method` is null.

The current team on a `/v1/players` object is used only for a season that has no stat row, and not before `draft_year`. That covers a player who has no box score yet without inventing a career. `list_players` still requires ids so an empty list cannot spend a budget slot on the first page of every player.

## Tests

Red before the guard, on throwaway Postgres 16 at `127.0.0.1:5441`:

- `test_a_successful_file_with_no_player_rows_keeps_that_minute` failed: `assert 'stored' == 'failed'`.
- `test_spo151_player_ids.py` did not collect: `ModuleNotFoundError: app.services.injury_report_match`.
- `test_a_0200_title_is_not_stored_as_the_0300_instant` passed after the redundant compare was removed.

Green after the fix, same server, `DATABASE_URL` set to that local database:

- SPO-151 file and the QA recheck file: 15 passed (11 new tests, 4 recheck tests).
- Full backend suite: **1991 passed, 17 skipped, 4 xfailed, 0 failed** in 117.86s.
- `TestVpcIdConsole` did not fail. Terraform is not on PATH, so those 3 tests skipped. They are not a new failure and they are not a pass.
- Ruff `E9,F63,F7,F82` on the edited Python files: all checks passed.
- `git ls-files | grep -i '\.pdf$'` printed nothing. No route under `backend/app/api/` or `frontend/` references the matcher, `list_players_page`, or the review list.

No BALLDONTLIE key was present, so no new unfiltered page was recorded. `list_players_page` is tested against the response object already in `backend/tests/fixtures/bdl/players_ids_v2.json`. That page has no `meta.next_cursor`, and `iter_pages` stops after it. The request asserts no `player_ids[]`.

## Mutation checks

1. `_initials_match` returned true after the surname check, with no first-character compare. `test_jordan_miller_does_not_match_baba_miller` failed: `assert 1 == 2` (Baba's id, not Jordan's). Restored. The test passed.
2. `_ALIASES` was set to `{}`. `test_known_aliases_resolve_on_that_team_and_season` failed on `Claxton, Nic`. `test_ingest_writes_the_alias_and_the_review_list` failed: `assert 'surname_initial' == 'exact_team_season'` (Nic still reached Nicolas by surname and initial when he was the only Claxton). Restored. Both passed. Noah Claxton is in the pure test so that surname-plus-initial is not a unique Nic match.
3. The zero-player failure was disabled and `_DELETE_ABSENT` ran for an empty file. `test_a_successful_file_with_no_player_rows_keeps_that_minute` failed: `assert 'stored' == 'failed'`. Restored. The test passed.

## Blast radius

- **Delete and dry_run.** The three unchanged recheck tests passed: another minute and the other league stay; `dry_run` does not delete a name the file omits; a missed game id with the same status writes nothing.
- **SPO-150 and SPO-157.** Those modules passed in the full suite. `test_ingest_resolves_ids_and_a_second_run_writes_nothing` still sees `match_method` null, because ingest does not match unless a catalog is passed. The `'held'` re-ingest tests passed. The `DO UPDATE` text still does not contain `bdl_player_id` or `match_method`.
- **Players foreign key.** The alias ingest inserts the `players` row before it sets `bdl_player_id`. A null id is still allowed for an unmatched row.
- **`list_players` callers.** The method still raises `BdlError` on `[]` before HTTP. The SPO-130 fakes that implement `list_players(player_ids=...)` were not asked for the new method. The full suite passed.
- **Point-in-time read.** `injury_report_rows_asof` is unchanged. The empty-file test still reads Doe for game 701. Migration 006 and 007 were not edited.
- **Scheduler.** `ingest_fetch_results` does not pass a catalog, so a fetch does not call BALLDONTLIE and does not stamp every row unmatched.
- **Docker and CI.** No new dependency. `rapidfuzz` is already in `backend/requirements.txt`. The image still installs that file only. CI still installs both requirement files and runs pytest. Docker is not installed here, so the image was not built.
- **Public surface.** No new route. The review file is optional and `injury-report-unmatched/` is gitignored. `docs/progress.md` was not edited.

## Follow-ups

- The scheduler does not match. A later job can call `match_report_rows` with `catalog_from_database` plus pages from `list_players_page` when a key is available. That walk was not recorded here.
- SPO-152 can alert on the unmatched rate. This ticket only returns the list.
- The live 2023-24 rates were not rerun, because that needs official PDFs.

## Progress notes (for the docs PR)

SPO-151: a parsed injury report with no player lines is failed and does not delete that league and minute; a team-note-only file is stored and does not delete named rows; null `bdl_player_id` and `match_method` can be filled from `/v1/players`, stat teams, and a three-name alias table; Jordan Miller is not Baba Miller; non-G-League misses stay on the row and on a private review list. `list_players` still requires ids. No new migration, no public route, no tracked PDF.
