# SPO-151 follow-up — stop when a name step is ambiguous

## Architect sketch

Written before the matcher change. This is the rule the code will follow.

`match_report_name` still runs the same six steps, in the same order. A step is tried only when it has the facts it needs (`team_id` and `season` for the team steps, `season` for the season steps).

Each tried step returns every candidate it accepted, not a single player and not a collapsed miss:

1. Exact folded name, this team, this season.
2. Exact folded name, any team, this season.
3. Same team and season, `token_sort_ratio` at or above 88.
4. Same team and season, same surname, same first character. Surname alone still does not match, so Jordan Miller does not become Baba Miller.
5. Exact folded name on a stat membership in a different season. The payload team is still not a second season.
6. Unmatched.

`_decide_step` reads that list:

- Zero candidates: return nothing. The caller tries the next step.
- One candidate: that player, and the caller stops.
- Two or more candidates: unmatched, and the caller stops. A later step is not allowed to break the tie, even when that later step would have been unique.

`g_league` still only chooses `unmatched` versus `unmatched_g_league`. It is not a seventh matching step.

`ingest_report` still matches only when the caller passes a catalog. This change does not pass one, and the scheduler still does not.

### Behavior on `304f51d` before the change

`_exact`, `_fuzzy`, and `_surname_initial` return a player only when the list length is 1. Length 0 and length 2 or more both return `None`. `match_report_name` treats `None` as "try the next step". An ambiguous step is not terminal.

Reproduced with synthetic players: Alex Doe id 7 on Boston in 2026 and in 2020, and Alex Doe id 8 on Boston in 2026 only. The report name is `Doe, Alex`, team Boston, season 2026. Steps 1 through 4 each see two candidates and return `None`. Step 5 sees only id 7 and returns `exact_other_season`. That is the fall-through.

The five catalogs in the uploaded `test_two_candidates_at_one_step_stay_unmatched` do not have that shape. On `304f51d` they already return unmatched, because every later step is empty or also has two candidates. Measured floors: `john smith` vs `jon smith` is 94.7, vs `johnn smith` is 95.2, so both are fuzzy candidates. `jordan miller` vs `julius miller` is 61.5 and vs `jabari miller` is 69.2, so the fuzzy step is empty and the surname step is the ambiguous one. Baba Miller vs Jordan Miller stays at 66.7, under 88.

## Summary

A matching step that finds two or more players now returns unmatched and does not try a later step. A later step still matches when every earlier step found nobody. The six-step order and the Jordan Miller / Baba Miller first-letter guard are unchanged.

The uploaded QA file is applied. One extra synthetic catalog was added to `test_two_candidates_at_one_step_stay_unmatched`, because the five uploaded catalogs already stayed unmatched on `304f51d` and would not go red if the fall-through came back. The extra catalog is the reproduced case above: two exact team-and-season players, and only the first id also has another season.

The empty-parse recheck test is renamed to `test_a_failed_empty_parse_keeps_that_minute`. Its assertions are unchanged. The `is_g_league` docstring now matches the code: casefold only, so `G-League` is false and `G League` is true. The check itself was not changed. The spaced phrase is what the parser stores (`G League - Two-Way`).

No unfiltered `GET /v1/players` fixture was recorded. This environment has no `BALLDONTLIE_API_KEY` (the variable is unset, there is no repo `.env`, and there is no local secret directory). `list_players_page` is still tested against the response already in `backend/tests/fixtures/bdl/players_ids_v2.json`.

This PR does not pass a catalog to `ingest_report` or to the scheduler. `ingest_fetch_results` still calls `ingest_report(conn, item, dry_run=False)`.

## Changes

| Area | Files | Change |
|---|---|---|
| Matcher | `backend/app/services/injury_report_names.py` | Each step returns its candidate list. Two or more stops the search. The G League docstring matches the hyphen rule |
| QA | `backend/tests/test_spo151_qa_pr131.py` | Uploaded synthetic tests, plus one catalog that falls through on the old rule |
| QA | `backend/tests/test_spo157_qa_recheck.py` | Renamed the empty-parse test so the name says the parse failed |
| Docs | `docs/task-summaries/SPO-151-follow-up-ambiguous-name.md` | This note |
| Docs | `docs/task-summaries/SPO-151-injury-report-player-ids.md` | One-line pointer. The earlier writeup is otherwise unchanged |

## Why

Collapsing "nobody" and "two or more" into the same miss made the next step the tie-break. A unique player in another season could win after the team-and-season step had already found two people. Stopping on that step keeps the tie unmatched. Skipping a step that found nobody keeps Jordan Miller on the other-season step, because Baba Miller is not a candidate there.

The G League docstring said hyphenation does not matter. The function only casefolds and looks for the substring `g league`. `G-League` does not contain that substring. The code matches the rule already written in the SPO-151 summary, so the docstring was the part that was wrong.

## Tests

Throwaway Postgres 16 on `127.0.0.1:5441`. `DATABASE_URL` set to that local database. Not port 5434.

Before the matcher change, the five uploaded ambiguous catalogs passed. After the extra catalog was added, and before the matcher change, `test_two_candidates_at_one_step_stay_unmatched[exact team then a later season-Doe, Alex-players5]` failed: `assert 7 is None` with `match_method='exact_other_season'`.

After the fix, same server:

- `test_spo151_qa_pr131.py`, `test_spo151_player_ids.py`, and `test_spo157_qa_recheck.py`: 27 passed.
- The QA file collects 12 tests: the uploaded 11, plus the extra catalog row (6 ambiguous cases instead of 5).
- Full backend suite: **2003 passed, 17 skipped, 4 xfailed, 0 failed** in 95.39s. The previous SPO-151 run on this base was 1991 passed. The increase is these 12 new tests.
- `TestVpcIdConsole`: 3 skipped, `terraform is not on PATH`. They did not fail. Terraform is not installed here.
- Ruff `E9,F63,F7,F82` on the edited Python files: all checks passed.
- `git ls-files | grep -i '\.pdf$'` printed nothing. No route under `backend/app/api/` or `frontend/` references the matcher, `list_players_page`, or the review list.
- `is_g_league("G-League", None)` is false. `is_g_league("G League", None)` and `is_g_league(None, "G League - Two-Way")` are true.

## Mutation checks

1. `_decide_step` returned `None` for two or more candidates, which is the old "try the next step" behavior. `test_two_candidates_at_one_step_stay_unmatched` failed on `exact team then a later season` (`assert 7 is None` was the failure before the fix, and it failed again). The five uploaded catalogs still passed, which is why the extra row is in the test. Restored. The test passed, including that row.
2. `_decide_step` returned `None` for a single candidate, so a unique step no longer counted. `test_one_candidate_at_the_later_steps_still_matches` failed: `assert None == 7`. `test_jordan_miller_does_not_match_baba_miller` failed: `assert None == 2`. Restored. Both passed.

## Blast radius

- **Aliases and Jordan / Baba.** `test_known_aliases_resolve_on_that_team_and_season` and `test_jordan_miller_does_not_match_baba_miller` passed. Baba is still not a surname-initial candidate, and the earlier steps for Jordan find nobody, so the other-season step still runs.
- **Ingest with no catalog.** `ingest_report` and `ingest_store` still default `catalog` to `None`. The scheduler file was not edited. `ingest_fetch_results` still calls `ingest_report` with no catalog. The SPO-150 and SPO-157 modules passed in the full suite, including rows whose `match_method` stays null.
- **G League.** Classification is unchanged. The QA test that stores category `G League - Two-Way` still writes `unmatched_g_league` and does not create the review file.
- **Empty parse.** The renamed recheck test passed. The uploaded empty-parse, dry-run, dash-player, and team-note tests passed. Assertions were not edited.
- **Review list.** Still the return value of `match_report_rows`, plus an optional JSONL file. No HTTP route was added.
- **`list_players` callers.** `bdl_client.py` was not edited. `list_players` still rejects an empty id list. The full suite passed.
- **Public surface.** No PDF is tracked. `docs/progress.md` was not edited.

## Follow-ups

- Record a real unfiltered `GET /v1/players` page when a key is available, and point `test_list_players_page_sends_no_player_ids` at that file. It still uses `players_ids_v2.json`.
- The scheduler still does not pass a catalog. That wiring stays out of this PR.
- SPO-152 alerts and SPO-153 model features stay out.

## Progress notes (for the docs PR)

SPO-151 follow-up: a name step with two or more players stops and stays unmatched; a later step still matches when earlier steps found nobody; the empty-parse recheck test is renamed to the failed parse; the G League docstring now says a hyphen is not a space. No catalog was passed to ingest or the scheduler. No unfiltered players fixture, because no key was available.
