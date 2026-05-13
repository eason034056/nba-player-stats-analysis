# SPO-32 — WNBA Phase 1: CSV service parameterization + /wnba read-only stats page

- **Ticket:** [SPO-32](/SPO/issues/SPO-32)
- **Parent epic:** [SPO-29](/SPO/issues/SPO-29) (WNBA rollout)
- **Orchestrator:** [SPO-30](/SPO/issues/SPO-30)
- **Branch:** `feature/SPO-32-wnba-csv-and-stats-page`
- **Author:** Forge (`d5d67ab1-e5b6-4792-ab6e-563e174f81fd`)
- **Date:** 2026-05-13 (rev 2 after Lens v1 review)
- **Status:** Lens-fix complete, ready for Lens re-review

## Summary

Stand up the WNBA data layer end-to-end so users can browse historical
WNBA player props the same way they browse NBA — but with zero Odds API
dependency. Backend service is parameterized on `league` (not duplicated);
new sibling route `/api/wnba/*` exposes the four required Phase 1
endpoints; new frontend routes `/wnba` and `/wnba/player/[name]` render
the read-only stats UI; Navbar gains a WNBA entry with **working**
prefix-based active state.

## Commits on this branch

1. `3f30e37` feat(wnba): Phase 1 — initial implementation
2. `b06e7d1` fix(wnba): defensive Tooltip formatter for recharts
3. `3aa5ad0` docs(task): initial task summary
4. `e9c29e0` fix(wnba): Navbar isLinkActive (Lens v1 followup)
5. `7ff9a7d` fix(wnba): correct wnba.py route content for Phase 1 (Lens v1 followup, catastrophic find)
6. `a4daa6d` test(wnba): add TestClient route assertions (Lens v1 followup)
7. `9bc0d2b` test(wnba): disable slowapi limiter in TestClient fixture
8. _(this commit)_ docs(task): updated task summary

## Lens review v1 findings → fixes

Lens's first review caught real bugs hidden by service-only tests during the parallel-agent branch-switch chaos. All four critical findings are now resolved:

| Lens v1 finding | Status | Fix commit |
|---|---|---|
| **#1** wnba.py contained SPO-33 Phase 2 odds content, not the four Phase 1 endpoints | ✅ Fixed | `7ff9a7d` |
| **#2** Frontend pages would 404 (consequence of #1) | ✅ Fixed (transitively via #1) | `7ff9a7d` |
| **#3** Navbar `matchPrefix` was dead code — `isLinkActive` defined but never called | ✅ Fixed | `e9c29e0` |
| **#4** Tests only exercised the service layer; no HTTP-boundary coverage let #1 slip past green tests | ✅ Fixed | `a4daa6d` + `9bc0d2b` |

## Changes (final state)

| Layer | File | Type | Reason |
|---|---|---|---|
| Backend | `backend/app/services/csv_player_history.py` | Modified | Parameterize `CSVPlayerHistoryService` on `league` (default `"nba"` for backward compat). Add `_LEAGUE_FILE_NAMES` + `_LEAGUE_ENV_VARS` dispatch. Add `nba_csv_player_service` + `wnba_csv_player_service` singletons; legacy `csv_player_service` alias preserved. `load_csv()` honors the legacy `CSV_PATH` constant for NBA so existing tests stay green. |
| Backend | `backend/app/api/wnba.py` | New (rewritten in `7ff9a7d`) | Sibling of `nba.py`. Exposes `/api/wnba/csv/players`, `/api/wnba/csv/reload`, `/api/wnba/player-history`, `/api/wnba/player-dd-history`. Metric whitelist derived from `CONTINUOUS_METRIC_EXTRACTORS` for parity with NBA. |
| Backend | `backend/app/main.py` | Modified | Register `wnba.router` alongside `nba.router`. |
| Backend | `backend/tests/test_wnba_csv.py` | New + expanded | **24 tests total**: 16 service-layer (singleton wiring, CSV load, A'ja Wilson smoke, DD path, league isolation) + 8 HTTP-boundary tests via `TestClient` (the gate that should have caught Lens v1 #1). |
| Frontend | `frontend/lib/api.ts` | Modified | `getWNBACSVPlayers` + `getWNBAPlayerHistory` sibling functions. Reuse existing Zod schemas (response shapes are identical to NBA). |
| Frontend | `frontend/app/wnba/page.tsx` | New | Read-only player list with client-side search. Links to `/wnba/player/[name]`. |
| Frontend | `frontend/app/wnba/player/[name]/page.tsx` | New | Per-player history: metric selector + threshold input + Over/Under summary cards + recharts histogram + game-log table. |
| Frontend | `frontend/components/Navbar.tsx` | Modified | New WNBA entry. `isLinkActive` helper + `matchPrefix` flag for league-section active state — now **actually called** at the two render sites (Lens v1 #3 fix in `e9c29e0`). |

## Why (design rationale, unchanged from rev 1)

1. **Single-source service, not duplication.** The CSV schema is identical across NBA and WNBA, so the right factoring is one class parameterized on `league` — not two. Subclassing adds an inheritance hierarchy with zero behavioral difference. Parameterization keeps one set of tests in sync.
2. **Backward compatibility was a hard requirement.** Every existing NBA call site imports `csv_player_service`; renaming would have triggered a large unrelated refactor. The legacy alias points at the new `nba_csv_player_service` so day-1 behavior is unchanged.
3. **Read-only by design.** Phase 1 is data + UI only — no agent awareness, no odds, no events, no DB-schema changes. Honors the SPO-32 mandate's "Architectural guardrails".
4. **Path-prefix navbar active state, not exact-match.** League pages nest. The `matchPrefix` flag is targeted (only WNBA opts in) so existing Home / Picks / About behavior is unchanged.
5. **HTTP-boundary tests (rev 2).** Service-only tests let a wrong-content route file ship in rev 1. Rev 2 adds `TestClient` route assertions that catch this exact class of bug at the gate where it matters.

## Acceptance criteria

- [x] `CSVPlayerHistoryService` accepts `league` parameter; no duplicate class.
- [x] `wnba_csv_player_service` singleton wired up.
- [x] All 4 `/api/wnba/csv*` + `/api/wnba/player-*` endpoints registered AND return shaped 200 responses for a valid WNBA player (verified by `TestWNBARoutesEndToEnd`).
- [x] `/wnba` and `/wnba/player/[name]` render in the browser; Navbar shows WNBA entry with `/wnba/*` prefix-based active state (Navbar now actually calls `isLinkActive`).
- [x] `test_wnba_csv.py` passes — 24/24 (16 service + 8 HTTP).
- [x] Existing `test_csv_player_history.py` stays green — 68/68.
- [x] Task summary committed.

## Verification commands

```bash
# Backend — WNBA + NBA tests (24 + 68 = 92 tests)
cd backend
.venv/bin/pytest tests/test_csv_player_history.py tests/test_wnba_csv.py -v

# Frontend — TypeScript check
cd frontend && npx tsc --noEmit

# Sanity — confirm the four endpoints are wired in app.routes
cd backend && .venv/bin/python -c "
from app.main import app
paths = sorted({r.path for r in app.routes if hasattr(r, 'path') and '/wnba' in r.path})
for p in paths: print(p)
"
```

Anchor smoke (real CSV):

```
A'ja Wilson — 55 games, mean PTS = 23.82, P(PTS > 20.5) = 0.60
WNBA CSV total players = 184
```

## Tests (final state)

- `tests/test_wnba_csv.py::TestSingletonWiring` — 5 tests on singleton + alias correctness
- `tests/test_wnba_csv.py::TestRealWNBACSVLoad` — 4 tests on real CSV load
- `tests/test_wnba_csv.py::TestAnchorPlayerStats` — 4 tests on A'ja Wilson stats (PRA combo, opponents)
- `tests/test_wnba_csv.py::TestLeagueIsolation` — 1 test that WNBA service doesn't leak into NBA's CSV
- `tests/test_wnba_csv.py::TestAnchorPlayerDD` — 2 tests on the binary DD path
- `tests/test_wnba_csv.py::TestWNBARoutesRegistered` — **NEW** 1 test that asserts all 4 endpoints in `app.routes`
- `tests/test_wnba_csv.py::TestWNBARoutesEndToEnd` — **NEW** 7 HTTP-boundary tests via `TestClient` (with slowapi limiter disabled for hermetic runs)

## Follow-ups (out of scope, unchanged from rev 1)

- **`next build` failure is pre-existing on `dev`** — affects every page, not a WNBA regression. Recommend a separate fix ticket. Manual browser verification is the documented fallback per CLAUDE.md.
- **Vitest jsdom is known-broken** per CLAUDE.md / `MEMORY.md`. No new vitest tests added.
- **WNBA Navbar copy** ("No-Vig NBA" brand still in header) — Phase 6 (SPO-37) owns multi-league navbar/about polish.
- **WNBA dataset refresh cadence** — Phase 3 (SPO-35) owns DB schema audit + ingest cadence.

## Workflow recovery notes

This task fought three rounds of parallel-agent branch-switch chaos:

- **Rev 1 chaos**: commits temporarily landed on SPO-34 twice; recovered via cherry-pick + `git branch -f` reset of SPO-34 to its proper HEAD. Same parallel agent also overwrote `wnba.py` with SPO-33 Phase 2 content somewhere during the cherry-pick chain — the wrong content got baked into commit `3f30e37` and was caught by Lens v1.
- **Rev 2 fix-cycle**: same dynamics — commits landed on SPO-34 multiple times despite being authored on SPO-32. Each landing was cherry-picked back and SPO-34 reset. All eight SPO-32 commits are correctly attributed and live on `feature/SPO-32-wnba-csv-and-stats-page`.
- **Rev 2 commit-history contamination (this commit)**: while Forge's Rev 2 commits landed correctly, the parallel SPO-34 agent stacked **11 commits on top of** the legitimate SPO-32 tip (`07dd76b`), making the branch tip `06675a9` (later `ff8d0ed`). `git status` returning empty fooled the Rev 2 handoff into reporting a clean branch — *clean working tree ≠ clean commit history*. Lens caught this on Rev 2 review.

  Cleanup approach:
  1. Verified all 11 SPO-34 commits also exist on `feature/SPO-34-wnba-lineup-ingestion` (note: `feature/SPO-34-wnba-lineup-research` is the abandoned name; `-ingestion` is the live SPO-34 branch). `git merge-base feature/SPO-32 feature/SPO-34-wnba-lineup-ingestion` = `06675a9`, confirming full overlap.
  2. Atomic-CAS reset via `git update-ref refs/heads/feature/SPO-32-wnba-csv-and-stats-page 07dd76b <old-sha>` — preferred over `git reset --hard` because it doesn't require a checkout (which would race the parallel agent) and the compare-and-swap fails loudly if the branch moved underneath us.
  3. Reflog preserves the dropped 11 commits for 90 days as a recovery net; the SPO-34-ingestion branch is the canonical home of that work.
  4. Re-ran the test suite post-reset: 92/92 still PASS.

Updated memory note (`parallel_agent_branch_switching.md`) now instructs Forge to use `git update-ref` for branch surgery and to always cross-check `git log origin/dev..HEAD` against `git status` — the latter does not reflect commit-history contamination.


## Architectural guardrails honored

- ✅ Route sibling, service parameterized, single LangGraph (no agent code touched).
- ✅ No agent code in Phase 1 (Phase 5 owns league-awareness in LangGraph).
- ✅ No `league` column in DB tables (Phase 3 owns DB schema audit).
- ✅ Anti-hallucination: existing CSV is real production data already in `dev`; no external API calls added.

## Links

- Parent epic: [SPO-29](/SPO/issues/SPO-29)
- Orchestrator: [SPO-30](/SPO/issues/SPO-30)
- WNBA Odds API verification (parallel): [SPO-31](/SPO/issues/SPO-31)
- Lens v1 review: [SPO-32 comment #686c7c1b](/SPO/issues/SPO-32#comment-686c7c1b-a84b-4d7e-93b2-f669df958e7d)
- NBA-side reference: `backend/app/api/nba.py`, `backend/app/services/csv_player_history.py`
