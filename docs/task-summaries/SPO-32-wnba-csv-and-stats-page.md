# SPO-32 — WNBA Phase 1: CSV service parameterization + /wnba read-only stats page

- **Ticket:** [SPO-32](/SPO/issues/SPO-32)
- **Parent epic:** [SPO-29](/SPO/issues/SPO-29) (WNBA rollout)
- **Orchestrator:** [SPO-30](/SPO/issues/SPO-30)
- **Branch:** `feature/SPO-32-wnba-csv-and-stats-page`
- **Author:** Forge (`d5d67ab1-e5b6-4792-ab6e-563e174f81fd`)
- **Date:** 2026-05-13
- **Status:** Ready for Lens review

## Summary

Stand up the WNBA data layer end-to-end so users can browse historical
WNBA player props the same way they browse NBA — but with zero Odds API
dependency. Backend service is parameterized on `league` (not duplicated);
new sibling route `/api/wnba/*` exposes the four required endpoints; new
frontend routes `/wnba` and `/wnba/player/[name]` render the read-only
stats UI; Navbar gains a WNBA entry with prefix-based active state.

Phase 2+ (events, odds, no-vig) gated on Scout's Phase 0 ([SPO-31](/SPO/issues/SPO-31))
verification of WNBA market inventory on The Odds API. This Phase 1 work
is intentionally parallel with Phase 0 and ships standalone even if Phase
0 finds no WNBA props.

## Changes

| Layer | File | Type | Reason |
|---|---|---|---|
| Backend | `backend/app/services/csv_player_history.py` | Modified | Parameterize `CSVPlayerHistoryService` on `league` (default `"nba"` for backward compat). Add `_LEAGUE_FILE_NAMES` + `_LEAGUE_ENV_VARS` dispatch. Add `nba_csv_player_service` + `wnba_csv_player_service` singletons; legacy `csv_player_service` alias preserved. `load_csv()` honors the legacy `CSV_PATH` constant for NBA so existing tests stay green. |
| Backend | `backend/app/api/wnba.py` | New | Sibling of `nba.py`. Exposes `/api/wnba/csv/players`, `/api/wnba/csv/reload`, `/api/wnba/player-history`, `/api/wnba/player-dd-history`. Metric whitelist derived from `CONTINUOUS_METRIC_EXTRACTORS` for parity with NBA. |
| Backend | `backend/app/main.py` | Modified | Register `wnba.router` alongside `nba.router`. |
| Backend | `backend/tests/test_wnba_csv.py` | New | 16 tests against the real `data/wnba_player_game_logs.csv` (no mocks): singleton wiring, CSV load, A'ja Wilson smoke test (PRA + DD), league isolation, threshold-rejection on DD path. |
| Frontend | `frontend/lib/api.ts` | Modified | `getWNBACSVPlayers` + `getWNBAPlayerHistory` sibling functions. Reuse existing Zod schemas (response shapes are identical to NBA). |
| Frontend | `frontend/app/wnba/page.tsx` | New | Read-only player list with client-side search. Links to `/wnba/player/[name]`. |
| Frontend | `frontend/app/wnba/player/[name]/page.tsx` | New | Per-player history: metric selector + threshold input + Over/Under summary cards + recharts histogram + game-log table. |
| Frontend | `frontend/components/Navbar.tsx` | Modified | New WNBA entry. `isLinkActive` helper + `matchPrefix` flag for league-section active state (any `/wnba/*` route highlights the WNBA pill). Existing exact-match behavior preserved for leaf routes. |

## Why

1. **Single-source service, not duplication.** The CSV schema is
   identical across NBA and WNBA, so the right factoring is one class
   parameterized on `league` — not two. Subclassing adds an inheritance
   hierarchy with zero behavioral difference. Parameterization keeps one
   set of tests in sync.
2. **Backward compatibility was a hard requirement.** Every existing
   NBA call site imports `csv_player_service`; renaming would have
   triggered a large unrelated refactor. The legacy alias points at the
   new `nba_csv_player_service` so day-1 behavior is unchanged.
3. **Read-only by design.** Phase 1 is data + UI only — no agent
   awareness, no odds, no events, no DB-schema changes. This honors the
   "Architectural guardrails" section of the SPO-32 mandate and keeps
   the Phase 2/3 work mergeable cleanly later.
4. **Path-prefix navbar active state, not exact-match.** League pages
   nest (`/wnba/player/<name>`); exact-match was good enough for
   leaf-only routes but breaks the moment a section has children. The
   `matchPrefix` flag is targeted (only WNBA opts in for now) so the
   existing Home / Picks / About behavior is unchanged.

## Acceptance criteria

- [x] `CSVPlayerHistoryService` accepts `league` parameter; no duplicate class.
- [x] `wnba_csv_player_service` singleton wired up.
- [x] All 4 `/api/wnba/csv*` + `/api/wnba/player-*` endpoints registered in FastAPI app. Routes return shaped responses for a valid WNBA player (verified via `TestClient` + direct call to the service layer through pytest).
- [x] `/wnba` and `/wnba/player/[name]` render in the browser; Navbar shows WNBA entry with `/wnba/*` prefix-based active state.
- [x] `test_wnba_csv.py` passes against the real CSV — 16/16 PASS.
- [x] Existing `test_csv_player_history.py` stays green — 68/68 PASS.
- [x] Full backend pytest suite (excluding external-dep tests): **321 passed, 3 skipped**.
- [x] Frontend `tsc --noEmit` clean.
- [x] Task summary committed at `docs/task-summaries/SPO-32-wnba-csv-and-stats-page.md`.

## Verification commands

```bash
# Backend — WNBA + NBA CSV tests (real data, no mocks)
cd backend
.venv/bin/pytest tests/test_csv_player_history.py tests/test_wnba_csv.py -v

# Backend — full suite (excluding live-API tests)
.venv/bin/pytest -q --ignore=tests/test_agent_chat.py --ignore=tests/test_agent_planner.py \
  --ignore=tests/test_db.py --ignore=tests/test_lineup_consensus.py \
  --ignore=tests/test_lineup_live_validation.py --ignore=tests/test_odds_gateway.py \
  --ignore=tests/test_odds_snapshot.py --ignore=tests/test_odds_theoddsapi.py \
  --ignore=tests/test_projection_provider.py --ignore=tests/test_projection_service.py \
  --ignore=tests/test_scheduler.py --ignore=tests/test_lineup_service.py \
  --ignore=tests/test_lineup_player_context.py

# Frontend — TypeScript check
cd frontend && npx tsc --noEmit
```

Anchor player smoke (real CSV):

```
A'ja Wilson — 55 games, mean PTS = 23.82, P(PTS > 20.5) = 0.60
WNBA CSV total players = 184 (verified by `len(svc.get_all_players())`)
```

## Tests

- `tests/test_wnba_csv.py::TestSingletonWiring` — 5 tests on module-level
  singleton + alias correctness.
- `tests/test_wnba_csv.py::TestRealWNBACSVLoad` — 4 tests on real CSV
  load (≥100 players, A'ja Wilson present, list sorted).
- `tests/test_wnba_csv.py::TestAnchorPlayerStats` — 4 tests on A'ja
  Wilson historical stats (points well-formed, opponents populated,
  PRA combo metric works).
- `tests/test_wnba_csv.py::TestLeagueIsolation` — 1 test that the WNBA
  service path does NOT point at NBA's CSV (catches the most
  catastrophic refactor bug: two singletons sharing a path).
- `tests/test_wnba_csv.py::TestAnchorPlayerDD` — 2 tests on the binary
  DD path (well-formed prob_dd; threshold misuse rejected with
  ValueError).

## Follow-ups (out of scope for this ticket)

- **`next build` failure is pre-existing on `dev`** — every page
  (`/`, `/picks`, `/about`, `/betslip`, plus my new `/wnba`,
  `/wnba/player/[name]`) fails prerendering with
  `Cannot read properties of null (reading 'useContext')`. This is a
  Providers/SSR config issue affecting the whole frontend, not a WNBA
  regression. Confirmed by running `npx next build` on a clean `dev`
  checkout. Recommend a follow-up ticket (`fix(frontend): repair
  next build prerender`) — it's blocking but orthogonal to Phase 1.
- **Vitest jsdom is known-broken** per CLAUDE.md / `MEMORY.md`. No new
  vitest tests added; existing tests not touched.
- **WNBA Navbar copy.** The header still says "No-Vig NBA" — leagues
  share the brand. Phase 6 (SPO-37) owns the navbar/about polish to
  acknowledge multi-league.
- **WNBA dataset refresh cadence.** The CSV is static (committed in
  `efa285c`). Phase 3 / SPO-35 owns the DB schema audit + ingest
  cadence decision.

## Workflow recovery note

Mid-task, parallel agent activity caused multiple branch-switch
disruptions (twice my uncommitted work landed under `feature/SPO-34-…`
and once on a fresh stash). All work was recovered via reflog +
`stash@{0}` apply, then cherry-picked to `feature/SPO-32-…`. SPO-34 was
reset to `74ca06b` (its proper HEAD) to remove an accidentally-misrouted
commit. Final state: my SPO-32 work lives in commits `3f30e37` (feature)
and `b06e7d1` (TypeScript fix) on `feature/SPO-32-wnba-csv-and-stats-page`.

## Architectural guardrails honored

- ✅ Route sibling, service parameterized, single LangGraph (no agent code touched).
- ✅ No agent code in Phase 1 (Phase 5 owns league-awareness in LangGraph).
- ✅ No `league` column in DB tables (Phase 3 owns DB schema audit).
- ✅ Anti-hallucination: existing CSV is real production data already in `dev`; no external API calls added in Phase 1.

## Links

- Parent epic: [SPO-29](/SPO/issues/SPO-29)
- Orchestrator: [SPO-30](/SPO/issues/SPO-30)
- WNBA Odds API verification (parallel): [SPO-31](/SPO/issues/SPO-31)
- WNBA CSV: `data/wnba_player_game_logs.csv` (commit `efa285c`)
- NBA-side reference: `backend/app/api/nba.py`, `backend/app/services/csv_player_history.py`
