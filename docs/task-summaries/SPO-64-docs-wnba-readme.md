# SPO-64 — Docs: README + dev-doc.md reflect WNBA as a first-class league

## Summary

`README.md` and `docs/dev-doc.md` were written for the pre-WNBA, NBA-only product and contained zero mentions of WNBA despite the SPO-29 epic shipping a fully-parameterized league architecture (PRs #10–#19 merged 2026-05-26). Nightly audit SPO-63 flagged this as the highest-leverage docs gap: the README is the project's front door, and new contributors had no signal that WNBA was supported. This ticket adds the missing references with surgical inserts only — no rewrite, no churn on the existing NBA-focused MVP body.

## Changes

| File | Change | Why |
|---|---|---|
| `README.md` | Title → `NBA + WNBA Multi-Agent Betting Advisor`; lead paragraph says both leagues are first-class | Front door of the repo must mention WNBA |
| `README.md` § Project Features | Mentions both NBA + WNBA props, both CSVs, league-aware Agent Widget | Existing bullets were NBA-only |
| `README.md` § 2.A Historical Data CSV | Adds `data/wnba_player_game_logs.csv` alongside NBA CSV; notes both ship with repo and use the same `_get_csv_path(league=...)` loader | Per task description; verified `data/wnba_player_game_logs.csv` exists, no canonical WNBA URL is documented in-repo so the WNBA bullet stays neutral on re-download path |
| `README.md` § 3 Web Front-End | Adds `/wnba/*` route family (event, player, picks, betslip) and `/api/wnba/agent/chat` | Verified each route exists under `frontend/app/wnba/` and `backend/app/api/wnba_agent.py:27` |
| `README.md` § 5 Project Structure | Expands `backend/app/api/` to show `nba.py / wnba.py + nba_agent.py / wnba_agent.py`; expands `frontend/app/` to show NBA and `wnba/` route groups; CSV bullet lists both CSVs | Per task description; endpoint list grounded in `backend/app/api/wnba.py:7–15` docstring (authoritative) |
| `docs/dev-doc.md` | Surgical insert (Traditional Chinese) at top — between the lead paragraph and the original `# 開發文檔：NBA ...` title — noting the architecture is league-parameterized, with code-citation evidence | Original doc reads as NBA-only PRD; new contributors need a single signal that `league` flows through state → agents → tools/services. Original body untouched. |

## Why

WNBA was shipped as a full first-class league via the SPO-29 epic but the user-facing docs still claimed NBA-only. This is a docs/observability gap — the code is correct, the docs lied. SPO-63's audit charter prioritized this exact case (highest-leverage README fix on a recently-shipped feature).

## Evidence / grounding (anti-hallucination policy applies to docs too)

Every WNBA path/endpoint mentioned was verified before writing:

- `data/wnba_player_game_logs.csv` — confirmed with `ls data/`
- `frontend/app/wnba/{betslip,event,picks,player,layout.tsx,page.tsx}` — confirmed with `ls frontend/app/wnba/`
- `/api/wnba/csv/*`, `/api/wnba/events`, `/api/wnba/props/no-vig`, `/api/wnba/players/suggest`, `/api/wnba/player-history`, `/api/wnba/player-dd-history` — sourced from `backend/app/api/wnba.py:7–15` docstring
- `/api/wnba/agent/chat` — confirmed at `backend/app/api/wnba_agent.py:27` (`prefix="/api/wnba/agent"`)
- `_get_league(state)` helper — `scripts/agents/agents.py:68`, used at lines 198, 276, 301, 395, 565
- `league: LeagueId` field in state — `scripts/agents/state.py:32`
- `_get_csv_path(league="nba")` — `backend/app/services/csv_player_history.py:117`

No file outside `README.md` and `docs/dev-doc.md` was modified.

## Acceptance criteria check

| Criterion | Required | Actual |
|---|---|---|
| `grep -ic wnba README.md` | ≥ 5 | **13** ✓ |
| `grep -ic wnba docs/dev-doc.md` | ≥ 2 | **3** ✓ |
| All paths/endpoints exist | yes | verified — see Evidence above |
| Only README.md + dev-doc.md touched | yes | `git diff --stat origin/dev..HEAD` shows only these two files |
| Diff total ≤ 200 lines | yes | 50 insertions + 14 deletions = **64 lines** ✓ |
| Branch naming | `feature/SPO-64-...` | `feature/SPO-64-docs-wnba-readme` ✓ |

## Forbidden-zones audit (per SPO-63 charter)

None of these were touched:

- `backend/app/services/*_gateway.py` — untouched
- `backend/app/settings.py` — untouched
- `backend/migrations/` — untouched
- `.github/workflows/` — untouched
- Files changed in the last 24h (`frontend/app/wnba/layout.tsx`, `frontend/.gitignore`, `frontend/tsconfig.tsbuildinfo`, `docs/task-summaries/SPO-60-wnba-metadata-title.md`) — untouched

## Tests

No tests — this is a docs-only diff. `grep` acceptance checks (above) are the verification.

## Follow-ups

- (Owner judgment, not in scope) A canonical WNBA CSV download URL is not documented in-repo; if the owner wants a direct-download link analogous to the NBA one, the scraper repo would need to publish it and the README bullet could be updated.
- (Out of scope for this ticket) The mermaid System Architecture diagram in README still labels nodes generically — it remains accurate for both leagues (league is a state field, not a topology change), so no edit needed, but a future polish pass could add a single annotation noting "league flows through every node."

## Routing

Per the standard chain: Forge complete on local commit, awaiting Lens review → Sentinel QA + push + PR.

Local commits on `feature/SPO-64-docs-wnba-readme` (not pushed):

- `ca7b576` docs(wnba): SPO-64 — README reflects WNBA as first-class league
- `06e422e` docs(wnba): SPO-64 — dev-doc.md note that architecture is league-parameterized
