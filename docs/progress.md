# Sports Lab Progress

> Engineers update the row for their ticket in the pull request that changes that ticket. This file is a snapshot of ticket state, not a heartbeat log. Last updated: **2026-11-10** (Nov 10 merge batch on `dev` at `6688384`: #35, #39–#48; SPO-96, SPO-102, SPO-103, SPO-104, and SPO-107 moved to Shipped; SPO-10 and SPO-11 Done). Facts below were checked against `docs/task-summaries/`, `git log` on `dev`, and `gh pr list --base dev`. Titles that were not in those sources are left blank.

## Shipped

### Nov 10 merge batch

Shipped on `dev` at `6688384`. Notes for #35 and #39–#48 are those pull requests' progress notes, with open-branch status replaced by the merge. SPO-107, SPO-104, SPO-102, SPO-96, and SPO-103 moved here from In flight after `git log origin/dev`.

| Ticket | Note |
|---|---|
| SPO-118 | Merged into `dev` in #47. Review follow-ups from #43, #45, and #46. Direct `latest_position`, six rank fields plus a fully invalidated row, events cache hit and a failed top-read join, logged lineup-peek failure, shared main-line vote, spliced rung drops the first row's vig, and the rate limiter falls back when Redis is down. Summary: `docs/task-summaries/SPO-118-merge-batch-nits.md`. |
| #48 | Merged into `dev` in #48. League daily-analysis unit tests and the FanDuel player-points regression load recorded NBA Odds API captures through `tests.fixtures.odds_api`. Each case rewrites player, line, event id, teams, and tip time. Prices stay the prices the recording posted. This removes the hand-typed Odds API bodies in `test_daily_analysis_league.py` and the untagged FanDuel Curry body in `test_spo16_market_expansion.py`. |
| SPO-106 | Merged into `dev` in #35. Recorded NBA Odds API fixtures for unit tests. `player_points`, the NBA events list, and `odds_api_event_odds__nba_expanded_markets.json` (Celtics at 76ers, 2026-11-10) load through `tests.fixtures.odds_api`. Rebounds Under-only and double-double Yes use that file. FTM, FGM, and double-double No stay inline because the recording did not post those sides. WNBA fixture work is deferred while WNBA work is paused. Summary: `docs/task-summaries/SPO-106-recorded-odds-fixtures.md`. |
| SPO-112 | Merged into `dev` in #44. NBA Daily Picks carry five side-relative signals and a calibrated `combined_probability`. WNBA leaves both null. Backtest Analyst verdict INSUFFICIENT REAL-LINE DATA (2026-11-10): `probability` stays the headline until a separate real-line check. Summary: `docs/task-summaries/SPO-112-signal-verdicts.md`. Decision: `docs/decisions/SPO-112/decision_20261110_signal-verdicts-combined-probability.md`. |
| SPO-113 | Merged into `dev` in #45. NBA field enrichment for the No-Vig redesign. Position ranks are 1–30 inside each position. Each rank has its own source. A vendor rank outside 1–30 becomes null with `sportsdata_invalid` and is not CSV-filled. Summary: `docs/task-summaries/SPO-113-field-enrichment.md`. Decision: `docs/decisions/spo-113-field-enrichment/decision_20261110_field-enrichment.md`. |
| SPO-114 | Merged into `dev` in #46. Snapshot-only bulk props, `GET /api/nba/events/{event_id}/props`. NBA only. Reads `odds_line_snapshots`. Does not call the Odds API. The one-vote line mirrors SPO-115 (de-vig, two-sided beats one-sided, posted-mode fallback). League column and the writer's last-pair / no-line unique key are deferred. Summary: `docs/task-summaries/SPO-114-bulk-props.md`. |
| SPO-111 | Merged into `dev` in #42. NBA read data for the No-Vig redesign. `top_read` on `GET /api/nba/events`. `DailyPick.tier`, `p_over`, and `p_under`. Candidates stored down to the Lean floor; the default daily-picks query stays 0.65 / 10 games. WNBA routes are unchanged. Summary: `docs/task-summaries/SPO-111-read-data.md`. |
| SPO-115 | Merged into `dev` in #43. `bookmakers_count` counted Over and Under (and every alt rung). One main line per bookmaker. Summary: `docs/task-summaries/SPO-115-bookmakers-count.md`. |
| SPO-110c | Merged into `dev` in #41. NBA only; WNBA paused, routes unchanged. Daily Picks, Bet Slip, Method, and the Ask agent panel. Summary: `docs/task-summaries/SPO-110c-picks-slip-method.md`. |
| SPO-110b | Merged into `dev` in #40. NBA and WNBA game page restyle. Summary: `docs/task-summaries/SPO-110b-game-page.md`. |
| SPO-110a | Merged into `dev` in #39. Design tokens, app shell, and the Today page (NBA and WNBA). Summary: `docs/task-summaries/SPO-110a-design-system-shell-today.md`. Picks, Bet Slip, and Method were not restyled in this pull request. |
| SPO-107 | Merged into `dev` in #38 (`23b4443`). Harness game types match production regular season. `_active_games` uses `CSVPlayerHistoryService._allowed_game_types()` (regular season; a missing game type counts as regular). Headline metrics are regular-season targets scored with that history. Playoffs and the play-in are scored with the same history and reported in their own section, not in the headlines. The CI guard compares 25 daily L10 rates per league (seed 7) with `get_player_stats` and fails on any mismatch. `oracle.py` and `backtest_report.md` are the full run on the post-SPO-97 CSVs. Decision: `docs/decisions/SPO-107/decision_20261110_regular-season-harness.md`. Summary: `docs/task-summaries/SPO-107-harness-gametype-parity.md`. |
| SPO-104 | Merged into `dev` in #37 (`a14370d`). One-sided DD quotes (`under_odds` / `p_under_imp` null, including a JSON null No price; `line_is_synthetic`, `market_kind`, `uses_prior`), league-scoped team codes, and the SPO-97 schedule-index follow-ups. Summary: `docs/task-summaries/SPO-104-dd-one-sided-and-followups.md`. |
| SPO-102 | Merged into `dev` in #33 (`e64621b`). `PlayerDDTile` loads double-double history and yes/no odds. Summary: `docs/task-summaries/SPO-102-player-dd-tile-wiring.md`. |
| SPO-96 | Merged into `dev` in #27 (`adbbc69`). Process docs rewritten for the current team workflow. Summary: `docs/task-summaries/SPO-96-claude-md-workflow-rewrite.md`. |
| SPO-103 | SPO-10 phase 5 final review. Done with SPO-10 and SPO-11. Verified on `dev` at `6688384` (backend 1041 passed, 23 skipped, 6 xfailed, 0 failed, CI 6/6). WNBA live coverage is deferred because WNBA work is paused. Frontend fixes from this review shipped as SPO-105 in #36 (`4267d88`). |

### SPO-105 — frontend review fixes

Shipped on `dev` in #36. The in-flight row that came in with the merge still said the branch was open. `under_odds` is nullable in the frontend schema. This PR lands with that change.

### SPO-101 — event-page integration tests

Shipped on `dev` in #34. The progress row that came in with the merge still said the pull request was awaiting squash-merge.

Live tests for the 12-tile `/event` surface and the double-double round-trip. Skipped unless `RUN_INTEGRATION=1`. One batched odds call. Not run in this environment (`ODDS_API_KEY` unset).

### SPO-99 — walk-forward backtest

Shipped on `dev` in #32. The progress section that came in with the merge still said the pull request was open and not merged.

Replaces the in-sample five-player `scripts/agents/evaluation/backtest.py` with a walk-forward harness. Each player-game uses only games dated strictly before it. Daily Picks goes through `choose_daily_pick_side`. The agent path calls `compute_scorecard` on a prior-only cache.

Proxy lines are MED20 by default; L10 is also supported. ROI assumes -110. Closing-line value is not measured. The CLV hook stays inactive unless an odds-history file is passed.

CI job `walk-forward-guard` sits between `frontend-test` and `docker-build` on the workflow from #29. It runs the harness tests, including a 40-player sample (seed 7) that fails if MED20 Brier exceeds 0.30 or the calibration gap exceeds 0.15.

### SPO-97 — Game-log season labels and game types

Shipped on `dev` in #30. Task summary: `docs/task-summaries/SPO-97-csv-season-hygiene.md`.

Cup finals are `cup_championship` and stay out of the default regular-season sample. The progress row that came in with the merge still said the branch was in review and the summary was not on `dev`.

### SPO-98 — Player team attribution and exact name matching

Shipped on `dev` in #28 (`fad723a`). Task summary: `docs/task-summaries/SPO-98-team-attribution-exact-names.md`.

US game date, exact `player_name_key`, league-aware roster. Daily-picks wiring loads recorded Odds API `player_points` (`backend/tests/fixtures/`). The progress row that came in with the merge still said `in_review` on `feature/SPO-98-team-attribution-exact-names`; the squash-merge is on `dev`.

### SPO-100 — junk-file pass (2026-11-09)

Shipped on `dev` in #31 (`f267e06`).

Untrack `nba_lineup_rag/RAG_evaluation.html`, `RAG_evaluation.pdf`, and `outputs/notebook_results_*.json`. `frontend/tsconfig.tsbuildinfo` was already gitignored and untracked. `data/*.jsonl` stays in git; `.dockerignore` keeps it out of the backend image. The progress note that landed with that merge listed the branch as `feature/SPO-100-junk-pass` and the status as PR open against `dev`.

### SPO-95 — CI branch triggers (2026-11-09)

Shipped on `dev` in #29 (`546dc5d`). QA owned the CI fix.

`ci.yml` and `deploy-staging.yml` filtered on `main`. This repo has no `main` ref; `origin/HEAD` is `master`, and integrated work lands on `dev`. CI now runs on push to `master` and `dev`, and on pull requests that target either branch. Staging deploy runs on push to `master` (the branch the workflow called `main`). Production deploy stays on `v*` tags (that file never named `main`). Neither deploy workflow runs on pull requests.

### SPO-29 — WNBA rollout

Shipped. Phases 0–6 are on `dev`:

| Phase | Ticket | PR |
|---|---|---|
| 0 — Odds API verification | SPO-31 | #10 |
| 1 — CSV + read-only stats page | SPO-32 | #11 |
| 2 — odds + no-vig | SPO-33 | #12 |
| 3 — daily picks | SPO-35 | #14 |
| 4 — lineup ingestion | SPO-34 | #13 |
| 5 — LangGraph league-awareness | SPO-48, SPO-52, SPO-58 | #15, #16, #17 |
| 6 — betslip + navbar/about | SPO-37 | #18 |

Later WNBA follow-ups also on `dev`: SPO-60 metadata title (#19), SPO-64 README + `dev-doc.md` (#20), SPO-83 event-detail parity (#25, phase 0 of SPO-82).

### SPO-10 — event-page stat expansion

SPO-10 and SPO-11 are Done. Verified on `dev` at `6688384` (backend 1041 passed, 23 skipped, 6 xfailed, 0 failed, CI 6/6). WNBA live coverage is deferred because WNBA work is paused.

| Phase | Evidence on `dev` |
|---|---|
| 0–1 research | `docs/research/event-page-stat-expansion/research_odds_api_markets.md` and `docs/task-summaries/SPO-12-odds-api-9-markets-research.md`, landed in `be2bfb3` |
| 2 backend services | SPO-16 / SPO-17 / SPO-18, PR #1 (`35a25dd`) |
| 3 frontend | SPO-20, PR #3 (`e36cb57`) |
| 3.5 API route gap | SPO-26, PR #4 (`490b9be`) |
| 4 integration tests | SPO-101, shipped on `dev` in #34. Gated with `RUN_INTEGRATION=1`. |
| 5 final review | Done with SPO-10 and SPO-11. Verified on `dev` at `6688384` (backend 1041 passed, 23 skipped, 6 xfailed, 0 failed, CI 6/6). WNBA live coverage is deferred because WNBA work is paused. |

## Abandoned

Process tickets from the retired setup. No task summary of their own on `dev`.

| Ticket | What the repo shows |
|---|---|
| SPO-59 | Cited in `docs/task-summaries/SPO-60-wnba-metadata-title.md` as a review of SPO-37. |
| SPO-62 | Cited in the same file as a browser smoke of WNBA page titles. The title fix landed as SPO-60 (#19). |
| SPO-63 | Cited in `docs/task-summaries/SPO-64-docs-wnba-readme.md` as the docs audit that flagged the README. The README fix landed as SPO-64 (#20). |
| SPO-75 | Parent of SPO-76 (`docs/task-summaries/SPO-76-graph-tests.md`). SPO-76 merged as #24. |
| SPO-81 | Parent of SPO-82 (`docs/decisions/SPO-82/decision_20260531_wnba-parity-approach.md`). SPO-83 (phase 0 of SPO-82) merged as #25. |

## Dropped

Stale pull requests the owner is closing. Not merged.

| Ticket | PR | Branch | Subject on the branch |
|---|---|---|---|
| SPO-67 | #21 | `feature/SPO-67-date-utils-tests` | unit tests for `date_utils.py` |
| SPO-73 | #23 | `feature/SPO-73-scoring-tests` | unit tests for `scoring.py` numeric guards |
| SPO-94 | #26 | `feature/SPO-94-market-tools-tests` | unit tests for `tools/market.py` deterministic helpers |

## In flight (cleanup)

None in this snapshot.

## Backlog

| Ticket | Note |
|---|---|
| SPO-117 | Snapshot writer stores 0 rows, and alt lines overwrite the main line. Waiting for Eason's approval. `calculate_mode_threshold` already applies the tie rule. `assemble_bulk_props` takes the player `line` from that function. The per-book main line does not: `bulk_props._main_book_line` calls `daily_analysis._main_book_line` (equal distance keeps the lower posted point; with no usable price, `_posted_point`). That path should follow the same tie rule. `OddsSnapshotService.rows_from_bookmakers` stores the last Over and the last Under and does not pick a mode. |
| #47 QA | Follow-ups from the #47 QA review. Move `_main_book_line`, `_even_money_distance` and `_posted_point` out of `daily_analysis` into a shared public module. Comment in `rate_limit.py` that the in-memory fallback counts per process and `swallow_errors` lets any limiter error through. Assert `opponent_position_rank_source` in `test_spo113_qa_review.py`. Fix the "Odds API shape" docstring in `test_spo113_field_enrichment.py` (it's our cache). Stop patching slowapi private attributes in the Redis-down test. Reject NaN/inf in `bulk_props._as_float`. Add QA's SPO-118 tests. |
| Limiter | Before running more than one worker process, re-evaluate the limiter's in-memory fallback (limits become per process). |

## Not classified

`research/SPO-65-parlay-correlation` is on the remote (`268fd28`) and is not merged to `dev`. No pull request for it showed up in `gh pr list --base dev`. Status is not recorded here.

## How this file is maintained

The engineer who changes a ticket's state updates that ticket's row in the same pull request. Keep a row terse when the title or status is not in the repo.
