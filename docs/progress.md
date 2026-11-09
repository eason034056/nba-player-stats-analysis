# Sports Lab Progress

> Engineers update the row for their ticket in the pull request that changes that ticket. This file is a snapshot of ticket state, not a heartbeat log. Last updated: **2026-11-09** (SPO-96). Facts below were checked against `docs/task-summaries/`, `git log` on `dev`, and `gh pr list --base dev`. Titles that were not in those sources are left blank.

## Shipped

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
| 4 integration-test pass | still open — no task summary, no merge |
| 5 final check that the exploration script and integration test are in the diff | still open — no task summary, no merge |

Phase 4 and Phase 5 names come from `docs/decisions/event-page-stat-expansion/decision_20260502_phase0-research-first-and-derive-strategy.md`. No ticket numbers for those two phases were found in the repo.

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
| SPO-95 | CI fix, owned by QA. |
| SPO-96 | This docs rewrite (`feature/SPO-96-claude-md-workflow-rewrite`). |
| SPO-97 | CSV season hygiene. No task summary on `dev` yet. |
| SPO-98 | Team attribution and exact name matching. No task summary on `dev` yet. |
| SPO-99 – SPO-103 | In flight. Titles were not in `docs/task-summaries/` or `git log` on `dev`. |

## Not classified

`research/SPO-65-parlay-correlation` is on the remote (`268fd28`) and is not merged to `dev`. No pull request for it showed up in `gh pr list --base dev`. Status is not recorded here.

## How this file is maintained

The engineer who changes a ticket's state updates that ticket's row in the same pull request. Keep a row terse when the title or status is not in the repo.
