# SPO-96 — Rewrite process docs for the current team workflow

## Summary

The repo's process docs still described a retired dev-agent roster (company id, routing table, heartbeat log, push chain). This ticket rewrites them for the current flow: an engineer branches `feature/SPO-<NN>-<slug>` from `origin/dev`, opens one PR into `dev` with a task summary, QA Reviewer tests and reviews, and the owner (Eason) squash-merges. Only the owner merges. Pushes go to feature branches only. `master` is the production branch. The anti-hallucination policy, domain lenses, coding conventions, settings rules, and Postgres/Redis rules stay.

## Changes

| File | Change |
|---|---|
| `CLAUDE.md` | Dropped the company id, local checkout path, dev-agent roster, routing table, subtask handoff, owner-profile section, and the Forge/Lens/Sentinel push chain. Product-agent section kept. Anti-hallucination rules restated by role (engineer writes the exploration script and `tests/fixtures/` recordings; research cites curl; QA requires proof of a real run). Git workflow now uses `master` + `dev`. Docs-organization actors are generic. |
| `docs/progress.md` | Replaced the 2026-05-08 heartbeat with a snapshot: SPO-29 shipped, SPO-10 phases 0–3.5 done and phases 4–5 open, SPO-59/62/63/75/81 abandoned, SPO-67/73/94 dropped (owner closing PRs #21, #23, #26), cleanup SPO-95–SPO-103 in flight. Engineers update their own row in the PR. |
| `.github/PULL_REQUEST_TEMPLATE.md` | Template now points at the task summary and the engineer → QA → owner merge. |
| `docs/archive/paperclip/decision_20260502_paperclip_company_bootstrap.md` | `git mv` from `docs/decisions/initial-roadmap/`. One-line historical note added at the top. |
| `.paperclip-staging/` | Deleted (six staged agent instruction files). |
| `docs/task-summaries/SPO-96-claude-md-workflow-rewrite.md` | This file. |

## Why

Contributors reading `CLAUDE.md` were being told to wake a roster that no longer exists, to push through a single QA actor, and to treat `main` as production. The production branch on the remote is `master` (`origin/HEAD` → `origin/master`). The anti-hallucination policy stays because odds and lineup clients still drift; only the role names changed. `docs/progress.md` stopped at 2026-05-08, before the WNBA epic landed, so a new reader would think Phase 3.5 was still in review.

SPO-67, SPO-73, and SPO-94 stay off `dev`. Their PRs (#21, #23, #26) are stale; the owner is closing them, so the snapshot records those tickets as dropped.

## Tests

Docs only. No pytest.

- `rg -n -i paperclip` over the repo after the edit. Remaining hits are the three files listed under Follow-ups / left in place.
- `rg` for the old path `docs/decisions/initial-roadmap/decision_20260502_paperclip_company_bootstrap.md`: no remaining references.
- `git log origin/dev..HEAD --format='%an %ae%n%B'` checked for tool or model attribution before push.

## Follow-ups

- `.github/workflows/ci.yml` and `.github/workflows/deploy-staging.yml` still trigger on `main`. Production is `master`. Left for SPO-95 (CI fix).
- SPO-99 through SPO-103 have no titles in `docs/task-summaries/` or `git log` on `dev`. Fill the rows when those PRs open.
- SPO-10 phases 4 and 5 have no ticket numbers in the repo.

## Paperclip references left in place

| Path | Why it stays |
|---|---|
| `docs/archive/paperclip/decision_20260502_paperclip_company_bootstrap.md` | The archived record. The word is the subject of the file. A historical note is at the top. |
| `docs/decisions/event-page-stat-expansion/decision_20260502_phase0-research-first-and-derive-strategy.md` (Addendum 1) | One sentence explaining why a quota-measurement requirement was written into the decision log. Rewriting it would change a historical decision. |
| `docs/research/event-page-stat-expansion/research_odds_api_markets.md` (author line) | Historical byline on the SPO-12 research. |

Historical task summaries, decision logs, and research docs still name the old roles (Scout, Forge, Lens, Sentinel, CTO) as who did that work. Those files do not contain the word "paperclip" except the three rows above, and they were not rewritten.
