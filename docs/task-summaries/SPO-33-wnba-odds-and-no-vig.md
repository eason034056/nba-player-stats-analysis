# SPO-33 — WNBA Phase 2: odds + no-vig

- **Ticket:** [SPO-33](/SPO/issues/SPO-33)
- **Parent epic:** [SPO-29](/SPO/issues/SPO-29) (WNBA rollout)
- **Orchestrator:** [SPO-30](/SPO/issues/SPO-30)
- **Phase 0 evidence:** [`docs/research/wnba-rollout/odds_api_wnba_markets.md`](../research/wnba-rollout/odds_api_wnba_markets.md) (SPO-31)
- **Phase 1 baseline:** [SPO-32](/SPO/issues/SPO-32) — merged 2026-05-13 via [PR #11](https://github.com/eason034056/nba-player-stats-analysis/pull/11)
- **Branch:** `feature/SPO-33-wnba-odds-no-vig` (from `origin/dev`)
- **Author:** Forge (`d5d67ab1-e5b6-4792-ab6e-563e174f81fd`)
- **Date:** 2026-05-13
- **Status:** Ready for Lens review

## Summary

Wire the WNBA league through the existing `odds_provider` / `odds_gateway`
(both already accept `sport` as a parameter on `origin/dev` — no fork
needed) and expose three Phase 2 endpoints on top of SPO-32's WNBA router:

- `GET /api/wnba/events`
- `POST /api/wnba/props/no-vig` (Over/Under + DD-binary)
- `GET /api/wnba/players/suggest`

Frontend gains the corresponding API client functions, a Phase-2-slim
event page at `/wnba/event/[eventId]`, and an upgraded `/wnba` landing
that mirrors the NBA home layout (events + players).

Grounded entirely on SPO-31 Phase 0 curl evidence: 9 hard-supported WNBA
markets, 3 schema-valid+empty (`player_steals`, `player_blocks`,
`player_turnovers`). The DD-binary path from SPO-26 is a high-fidelity port
of `nba.py` (one deliberate null-safe divergence on `outcome.name` parsing —
see `wnba.py` module docstring) — no new parser branch required.

## Changes

| Layer | File | Type | Reason |
|---|---|---|---|
| Backend | `backend/app/services/cache.py` | Modified | Add optional `league` parameter to `CacheService.build_events_key` (default `"nba"`). League-namespaces the events cache so NBA + WNBA do not collide in Redis. Strictly additive — every existing NBA caller continues to produce the historical `events:nba:...` key shape with no source-code change. |
| Backend | `backend/app/api/wnba.py` | Modified | Append three Phase 2 endpoints (`/events`, `/props/no-vig`, `/players/suggest`) on top of SPO-32's four Phase 1 CSV endpoints in the same `APIRouter(prefix="/api/wnba")`. Calls into the existing parameterized `odds_gateway` / `odds_provider` with `sport="basketball_wnba"`. Reuses `BINARY_MARKET_KEYS`, devig math, fuzzy-match helpers, and the `NBAEvent` / `NoVigResponse` schemas (which are sport-agnostic by content). |
| Backend | `backend/tests/test_cache.py` | Modified | Three new tests: default-league-is-nba regression guard, WNBA-league key shape, namespace isolation between NBA and WNBA for the same date+region. |
| Backend | `backend/tests/test_wnba_odds_integration.py` | New | Three `@pytest.mark.integration` tests + one parametrized test, all gated on `RUN_INTEGRATION=1`: `/events` schema (free), `player_points` Over/Under shape (1 unit), `player_double_double` binary contract (1 unit if populated), and a parametrized `test_wnba_empty_bookmakers_market_graceful` covering `player_steals`/`player_frees_made`/`player_field_goals` (0 units while empty). The FTM/FGM cases were added post-Lens-review per the SPO-33 anti-hallucination remediation — see `scripts/explore_odds_api_wnba_ftm_fgm.py` + research doc §3.2.4. Anchored on the Phase 0 event id `efb5e7faabc4ea9406b9b479ae805b38` (Storm @ Tempo) with a live-event fallback. |
| Scripts | `scripts/explore_odds_api_wnba_ftm_fgm.py` | New | Phase 0 follow-up probe (added 2026-05-14). Targets only `player_frees_made` and `player_field_goals` on `basketball_wnba`. Mirrors `explore_odds_api_wnba.py`'s env-loading + classification logic. Output appended to research doc §3.2.4. Run cost: 0 paid units (both markets classified `schema-valid+empty`, unbilled). |
| Docs | `docs/research/wnba-rollout/odds_api_wnba_markets.md` | Modified | Added §3.2.4 (FTM/FGM curl evidence with headers + full bodies), extended §4 support table from 12 to 14 rows, replaced §6 "NOT probed this run" lines with verified classifications. Closes the anti-hallucination gap flagged in Lens review of commit `d1b00f3`. |
| Frontend | `frontend/lib/api.ts` | Modified | Three new exports — `getWNBAEvents`, `calculateWNBANoVig`, `getWNBAPlayerSuggestions`. Reuses existing Zod schemas (`eventsResponseSchema`, `noVigResponseSchema`, `playerSuggestResponseSchema`) which are sport-agnostic by content. |
| Frontend | `frontend/lib/event-detail-link.ts` | Modified | Add optional `league: "nba" \| "wnba"` parameter to `buildEventDetailHref` (default `"nba"`). NBA produces `/event/<id>` exactly as before; WNBA callers get `/wnba/event/<id>`. Adds an exported `LeagueSegment` type for typed callers. |
| Frontend | `frontend/components/PlayerInput.tsx` | Modified | Add two optional props: `suggestFn` (default `getPlayerSuggestions`) and `cacheNamespace` (default `"nba"`). NBA call sites untouched. WNBA caller injects `getWNBAPlayerSuggestions` and `"wnba"` so autocomplete + TanStack Query cache keys land in the right namespace. Adds an exported `PlayerSuggestFn` type. |
| Frontend | `frontend/components/EventList.tsx` | Modified | Thread an optional `league` prop through `EventList` → `EventCard` → `buildEventDetailHref`. Default `"nba"` keeps the NBA home page output identical. |
| Frontend | `frontend/app/wnba/event/[eventId]/page.tsx` | New | WNBA event detail page: 12-tile MarketSelect + player autocomplete (WNBA endpoint) + bookmaker filter + no-vig calculator + ResultsTable. Phase-2-slim — projection panel (SPO-35) and lineup panels (SPO-34) intentionally deferred. |
| Frontend | `frontend/app/wnba/page.tsx` | Modified | Phase 1 was players-only. Upgraded to a dual section: hero + date picker + EventList (with `league="wnba"`) + players search/list (Phase 1 surface preserved). Mirrors NBA `/page.tsx` structure. |
| Docs | `docs/task-summaries/SPO-33-wnba-odds-and-no-vig.md` | New | This file. |

## Why

1. **`odds_provider` / `odds_gateway` were already parameterized.** The
   abstract base `OddsProvider` accepts `sport: str`, and
   `OddsMarketGateway.get_market_snapshot` embeds `sport` in the snapshot
   cache key. So Phase 2 needed **zero** changes to those modules — the
   architectural guardrail "no fork of the gateway" is satisfied by
   reusing what's there, not by adding abstraction.
2. **The only NBA-literal in a shared service was the events cache key.**
   `events:nba:...` was hardcoded; adding an optional `league` kwarg with
   `default="nba"` preserves NBA behavior byte-for-byte while letting WNBA
   produce `events:wnba:...` keys. A regression-guard test
   (`test_build_events_key_default_league_is_nba`) protects against an
   accidental default flip.
3. **Schemas reused, not duplicated.** `NBAEvent`, `EventsResponse`,
   `NoVigRequest`, `NoVigResponse`, `PlayerSuggestResponse` already carry
   `sport_key` and are sport-agnostic in content. Forking into a parallel
   `WNBAEvent` would serialize identically. The cosmetic rename to
   `LeagueEvent` is an unrelated refactor and stays out of scope.
4. **Route handlers duplicated, not factored.** The DD-binary helper
   (`_build_binary_no_vig_response`) and the standard Over/Under loop are
   **high-fidelity ports** from `nba.py` — duplicated rather than factored
   out because SPO-33's acceptance criterion "existing NBA path unchanged"
   forbids touching `nba.py`. One deliberate divergence in the WNBA copy:
   `(outcome.get("name") or "").lower()` (both binary and OU paths) is
   null-safe against a `{"name": null}` payload from The Odds API, where
   NBA's `outcome.get("name", "").lower()` would crash on `AttributeError`.
   Functional behaviour is otherwise identical. **Drift risk acknowledged**:
   when a 3rd league joins, factor `_collect_player_names`,
   `_snapshot_metadata`, `_build_binary_no_vig_response` into
   `backend/app/services/no_vig_helpers.py` — rule-of-three lives at 3,
   not 2 — and apply the WNBA null-safe hardening to NBA in the same PR so
   the two parsers stay aligned. Both module docstrings flag this trigger.
5. **`PlayerInput` gets optional injection, not a hardcoded league switch.**
   Adding `suggestFn` (default = NBA's `getPlayerSuggestions`) and
   `cacheNamespace` keeps NBA call sites untouched. The alternative — a
   `league` prop with `if (league === 'wnba')` inside the component —
   would couple PlayerInput to the league set, forcing a code change
   inside the component for every new league rather than at the boundary.
6. **`EventList` parameterized via `buildEventDetailHref` link builder.**
   Threading `league` through to the link builder is the smallest possible
   change that lets one component serve both leagues. EventList's visual
   contract (logo + VS badge + matchup line) is identical between
   leagues; only the destination URL differs.
7. **Phase 2 frontend event page is slimmer than NBA on purpose.** The
   NBA event page renders projection + team-lineup panels driven by data
   layers that Phase 2 does not own. Stubbing them would waste layout
   space on UI the user can't yet use; deferring until SPO-34 (lineups)
   and SPO-35 (picks/projections) land keeps the page honest. The
   components drop straight in once their data layers exist.
8. **Cross-midnight refresh on `/wnba`.** Mirrors NBA `/page.tsx` — if a
   user leaves the tab open across midnight, the auto-pinned date rolls.
   Same `visibilitychange` + `focus` listeners.

## Acceptance criteria

- [x] `odds_provider` / `odds_gateway` accept `sport_key`; existing NBA path unchanged. Verified: both already accepted `sport: str` on `origin/dev`; no fork added; the NBA route still passes `sport="basketball_nba"` literally.
- [x] All three new `/api/wnba/*` endpoints registered. Smoke: `python -c "from app.api import wnba; print([r.path for r in wnba.router.routes])"` →
  `['/api/wnba/csv/players', '/api/wnba/csv/reload', '/api/wnba/player-history', '/api/wnba/player-dd-history', '/api/wnba/events', '/api/wnba/props/no-vig', '/api/wnba/players/suggest']`.
- [x] `/wnba` shows events list + players list. Dual section with shared `EventList` (league="wnba") and the preserved Phase 1 player search.
- [x] `/wnba/event/[eventId]` shows no-vig view. 12-tile MarketSelect + autocomplete + bookmaker filter + calculate button + ResultsTable.
- [x] Integration test passes locally with `RUN_INTEGRATION=1`; skipped by default. Default `pytest tests/test_wnba_odds_integration.py` → `1 skipped` (module-level skip when `RUN_INTEGRATION != "1"`).
- [x] DD-binary parsing path verified for WNBA — `_build_binary_no_vig_response` is a high-fidelity port of `nba.py._build_binary_no_vig_response` (one deliberate null-safe divergence documented in `wnba.py:315–320`). Integration test asserts the binary shape (`name in {yes, no}`, no `point` field) on a live WNBA event.
- [x] Task summary at `docs/task-summaries/SPO-33-wnba-odds-and-no-vig.md`.

## Architectural guardrail check

- **One gateway, one provider, parameterized.** ✓ No new file under `app/services/odds_*`. WNBA route calls the same `odds_gateway` and `odds_provider` instances NBA uses.
- **No new market keys.** ✓ All 14 markets reachable on the WNBA route via the shared `MarketSelect` are classified `hard-supported` or `schema-valid+empty` in Phase 0's research doc — the original 12 in SPO-31's ticket scope plus `player_frees_made` and `player_field_goals` added in the 2026-05-14 SPO-33 follow-up probe (§3.2.4 of [`odds_api_wnba_markets.md`](../research/wnba-rollout/odds_api_wnba_markets.md), prompted by Lens review of commit `d1b00f3`). Both follow-up markets returned `bookmakers=[]` with `x-requests-last: 0` — same Tier-B graceful-degrade contract as `player_steals`/`blocks`/`turnovers` and as NBA's existing FTM/FGM path. The anti-hallucination guard is the WNBA route reusing exactly the constants `BINARY_MARKET_KEYS` and the validation surface from the NBA route, not a parallel WNBA-specific market enum.
- **Existing NBA path unchanged.** ✓ `nba.py` is byte-for-byte unchanged. `cache.build_events_key` default behavior preserved (regression test enforces this). `PlayerInput` NBA defaults preserved. `EventList`/`buildEventDetailHref` NBA defaults preserved. Frontend NBA home page produces identical paths/links.

## Verification commands

```bash
# Backend — cache key unit tests (5 tests, 3 new in SPO-33)
cd backend
.venv/bin/pytest tests/test_cache.py -k "build_events_key" -v
# → 5 passed

# Backend — integration tests (default skip; live with RUN_INTEGRATION=1)
.venv/bin/pytest tests/test_wnba_odds_integration.py -v
# → 1 skipped (module-level skip without RUN_INTEGRATION=1)

# Backend — full suite excluding live-API and DB-required tests
.venv/bin/pytest -q \
  --ignore=tests/test_wnba_odds_integration.py \
  --ignore=tests/test_spo16_integration.py \
  --ignore=tests/test_quota_simulation.py \
  --ignore=tests/test_db.py \
  --ignore=tests/test_agent_chat.py \
  --ignore=tests/test_agent_planner.py \
  --ignore=tests/test_lineup_consensus.py \
  --ignore=tests/test_lineup_live_validation.py
# → 530 passed

# Backend — smoke: WNBA router is registered with all 7 expected paths
.venv/bin/python -c "from app.api import wnba; \
    print([r.path for r in wnba.router.routes])"

# Frontend — typecheck (clean)
cd ../frontend
npx tsc --noEmit
```

Local integration-test run (`RUN_INTEGRATION=1`) intentionally NOT executed
in this heartbeat — Forge does not burn paid quota by default. Sentinel /
owner runs `RUN_INTEGRATION=1` locally before merge.

## Cost & quota

- Phase 0 (SPO-31) verification burned 9 units total — already paid.
- 2026-05-14 SPO-33 follow-up probe (FTM + FGM) burned 0 units — both markets
  classified `schema-valid+empty`, unbilled.
- This Phase 2 integration test burns **at most 2 paid units per typical run**
  (`player_points` + `player_double_double`) when `RUN_INTEGRATION=1`.
  `/events` is free; the three parametrized `schema-valid+empty` markets
  (`player_steals`/`player_frees_made`/`player_field_goals`) cost 0 while
  bookmakers haven't started posting them. Worst case (all three start
  posting between the Phase 0 probe and the test run) raises the bill to 5
  units. Per the per-market billing model from SPO-12, full local
  verification still costs ≤ 1% of the monthly quota — well within
  `[Minor]` budget.
- Default (no env var set) → 0 units burned in dev/CI runs.

## Workflow handoff

- **Lens:** review the diff. Particular attention to (a) anti-hallucination guardrails — confirm no market keys are wired up that Phase 0 didn't probe, (b) the duplication of `_build_binary_no_vig_response` between `nba.py` and `wnba.py` is intentional and flagged, (c) NBA defaults preserved on all parameterized helpers.
- **Sentinel:** run backend pytest + `RUN_INTEGRATION=1` integration test + frontend tsc + Playwright smoke against `/wnba` and `/wnba/event/<id>` per `sentinel_browser_smoke_required.md` memory. Push to `origin/feature/SPO-33-wnba-odds-no-vig` and open PR against `dev` once all green.
- **Owner:** squash-merge PR into `dev` after Sentinel reports PASS.

## Follow-ups (not blocking)

1. **Helper extraction trigger** — when SPO-36 (Phase 5) or a 3rd league joins, factor `_build_binary_no_vig_response` / `_collect_player_names` / `_snapshot_metadata` from `nba.py` + `wnba.py` into `backend/app/services/no_vig_helpers.py`. Rule-of-three lives at the 3-caller boundary.
2. **Snapshot service league-awareness** — `odds_snapshot_service.py` and `daily_analysis.py` still carry NBA literals (`sport="basketball_nba"` at lines 312, 365 and 436, 667 respectively). Out of Phase 2 scope (no picks for WNBA yet); lands in [SPO-35](/SPO/issues/SPO-35) Phase 3.
3. **WNBA projection + lineup panels** — drop straight into `/wnba/event/[eventId]` when [SPO-34](/SPO/issues/SPO-34) (lineup ingestion) and [SPO-35](/SPO/issues/SPO-35) (picks/projections) land. No UI redesign needed.
4. **Schema rename `NBAEvent` → `LeagueEvent`** — cosmetic only (same fields). Defer to a dedicated cleanup ticket.
