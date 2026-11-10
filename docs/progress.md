# Sports Lab Progress

> Engineers update the row for their ticket in the pull request that changes that ticket. This file is a snapshot of ticket state, not a heartbeat log. Last updated: **2026-11-10** (SPO-111). Facts below were checked against `docs/task-summaries/`, `git log` on `dev`, and `gh pr list --base dev`. Titles that were not in those sources are left blank.

## Shipped

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

Phases 0–3.5 are done. Phases 4 and 5 are still open.

| Phase | Evidence on `dev` |
|---|---|
| 0–1 research | `docs/research/event-page-stat-expansion/research_odds_api_markets.md` and `docs/task-summaries/SPO-12-odds-api-9-markets-research.md`, landed in `be2bfb3` |
| 2 backend services | SPO-16 / SPO-17 / SPO-18, PR #1 (`35a25dd`) |
| 3 frontend | SPO-20, PR #3 (`e36cb57`) |
| 3.5 API route gap | SPO-26, PR #4 (`490b9be`) |
| 4 integration tests | SPO-101, shipped on `dev` in #34. Gated with `RUN_INTEGRATION=1`. |
| 5 final review | SPO-103, open. Final review; closes SPO-10 and SPO-11. No merge yet. |

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

| Ticket | Note |
|---|---|
| SPO-111 | NBA read data for the No-Vig redesign. `top_read` on `GET /api/nba/events`. `DailyPick.tier`, `p_over`, and `p_under`. Candidates stored down to the Lean floor; the default daily-picks query stays 0.65 / 10 games. WNBA routes are unchanged. Branch `feature/SPO-111-read-data`, PR into `dev`. Summary: `docs/task-summaries/SPO-111-read-data.md`. |
| SPO-96 | This docs rewrite (`feature/SPO-96-claude-md-workflow-rewrite`). |
| SPO-104 | One-sided DD quotes (`under_odds` / `p_under_imp` null, including a JSON null No price; `line_is_synthetic`, `market_kind`, `uses_prior`), league-scoped team codes, and the SPO-97 schedule-index follow-ups. Lands with #36. PR #37 into `dev`. Summary: `docs/task-summaries/SPO-104-dd-one-sided-and-followups.md`. |
| SPO-102 | Wire `PlayerDDTile` to double-double history and yes/no odds. Open on `feature/SPO-102-player-dd-tile-wiring`. Summary: `docs/task-summaries/SPO-102-player-dd-tile-wiring.md`. |
| SPO-103 | SPO-10 Phase 5 final review. Open. |

## Not classified

`research/SPO-65-parlay-correlation` is on the remote (`268fd28`) and is not merged to `dev`. No pull request for it showed up in `gh pr list --base dev`. Status is not recorded here.

## How this file is maintained

The engineer who changes a ticket's state updates that ticket's row in the same pull request. Keep a row terse when the title or status is not in the repo.
