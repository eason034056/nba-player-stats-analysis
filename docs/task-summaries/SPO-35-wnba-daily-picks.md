# SPO-35 — WNBA Phase 3 daily picks + DB schema audit

- Ticket: [SPO-35](/SPO/issues/SPO-35) (Phase 3 of [SPO-29](/SPO/issues/SPO-29))
- Author: Forge (`d5d67ab1-...`)
- Branch: `feature/SPO-35-wnba-daily-picks` (from `origin/dev` @ 328f9bd)
- Decision log: [`docs/decisions/wnba-rollout/decision_20260514_db-schema-audit.md`](../decisions/wnba-rollout/decision_20260514_db-schema-audit.md)
- Owner ack: `request_confirmation` `3f28b632` resolved `rejected → reason:
  "Include observability tables (lineup_fetch_logs, odds_snapshot_logs)
  in this PR"` — i.e. accept the audit, take the optional observability
  additive too. Step 2 unblocked.

## Summary

Wire WNBA into the daily-picks pipeline behind a `league` parameter so
`daily_analysis_service` is one function tree, not a fork — per the
ticket's "Parameterize, don't fork" guardrail. Adds league-namespaced
Redis cache keys, an independent WNBA scheduler job, three
`/api/wnba/daily-picks*` routes, and a `/wnba/picks` page that mirrors
the NBA card layout against the WNBA pipeline. Closes SPO-34's deferred
follow-up by adding a `league` column (and widening the unique
constraint) on `team_lineup_snapshots`.

## Changes

| Area | File | Change |
|---|---|---|
| DB migration | `backend/app/services/db.py` | Append additive migration block to `SCHEMA_SQL`: `ADD COLUMN IF NOT EXISTS league` on `team_lineup_snapshots` (DEFAULT `'nba'`), drop old `UNIQUE(date, team)`, add `UNIQUE(date, team, league)` (idempotent via DO block); `ADD COLUMN league` on `lineup_fetch_logs` + `odds_snapshot_logs` for per-league observability. PK and column types untouched → not Gate 2 (audit §5). |
| Daily analysis | `backend/app/services/daily_analysis.py` | New `_resolve_sport_key(league)` / `_resolve_csv_service(league)` registries; `run_daily_analysis`, `_get_events_for_date`, `_analyze_single_event`, `_get_props_for_market` accept `league: str = "nba"` (NBA callers unchanged); cache key namespaced as `daily_picks:{league}:{date}:tz{offset}`; projection prefetch gated on `_LEAGUES_WITH_PROJECTIONS = {"nba"}` (WNBA degrades to history-only — `has_projection=False`, `edge=None`); NBA path keeps reading `self.csv_service` so existing test patches (`service.csv_service = MagicMock()`) keep working. |
| Cache | `backend/app/services/cache.py` | `clear_daily_picks_cache(league: str \| None = None)` — when `league` is set, sweeps only `daily_picks:{league}:*`; `None` keeps legacy `daily_picks:*` semantics so any pre-SPO-35 unnamespaced keys are still reachable. |
| Scheduler | `backend/app/services/scheduler.py` | Register `wnba_daily_analysis_job` (UTC 12:00, independent of NBA's `daily_analysis_job` — separate `id`, separate handler, `try/except` local to the handler so a WNBA crash never bubbles into the NBA job); add `trigger_wnba_daily_analysis_now(date, tz_offset_minutes)` for `POST /api/wnba/daily-picks/trigger`; rename startup log line to disambiguate the two jobs. |
| API (WNBA) | `backend/app/api/wnba.py` | Add `GET /api/wnba/daily-picks` (same response shape as NBA — `DailyPicksResponse` is league-agnostic), `POST /api/wnba/daily-picks/trigger`, `DELETE /api/wnba/daily-picks/cache` (scoped to `daily_picks:wnba:*`). |
| Frontend (API) | `frontend/lib/api.ts` | `getWnbaDailyPicks(request?)` + `triggerWnbaDailyAnalysis(date?)`; reuse the existing `dailyPicksResponseSchema` zod parser (league-agnostic). |
| Frontend (page) | `frontend/app/wnba/picks/page.tsx` | New page: header + date picker + `min_probability` selector + refresh button + stats summary + responsive card grid (`PickCard`). Mirrors `/picks` visual hierarchy; deep-links via `buildEventDetailHref({..., league: "wnba"})`. Deliberate scope reduction: no lineup badges (SPO-34's WNBA lineup endpoint is still in PR #13), no bet-slip / agent-widget / context-menu wiring (NBA-coupled today). |
| Tests | `backend/tests/test_daily_analysis_league.py` | 11 new tests: resolver invariants (sport_key + csv_service per league, case-insensitive, unknown raises), `run_daily_analysis(league="wnba")` end-to-end behaviours — unknown-league raises before I/O, sport_key dispatch (`basketball_wnba` ↔ `basketball_nba`), league-namespaced cache key shape (NBA + WNBA), WNBA skips projection_service, NBA still calls it, WNBA history routes to `wnba_csv_player_service` not `csv_player_service`. |
| Tests (regression) | `backend/tests/test_daily_analysis.py` | One-line fix: the existing `mock_analyze` stub now accepts `league="nba"` so `run_daily_analysis`'s new kwarg doesn't TypeError it. |

## Why

- **DB audit decided this is additive, not Gate 2.** PK unchanged, no column drop, no type change. The replacement UNIQUE constraint is strictly more permissive than the old one. See `decision_20260514_db-schema-audit.md` §5 for the full classification.
- **Parameter, not fork.** Adding `wnba_daily_analysis_service` as a separate class instance was tempting (CSV + lineup services do it), but the orchestrator function tree (`run_daily_analysis` → `_get_events_for_date` → `_analyze_single_event` → `_get_props_for_market`) is a single pipeline. Threading `league` through is one short kwarg per method and keeps SUPPORTED_MARKETS / threshold logic shared.
- **`self.csv_service` retention.** Initially the NBA path also went through `_resolve_csv_service`, which broke the existing `service.csv_service = MagicMock()` pattern in `test_full_flow_with_mocked_events_and_analysis`. Switching the NBA branch to read `self.csv_service` (and only the WNBA branch through the registry) keeps the existing tests green without re-architecting them, and matches the established practice in this file.
- **Independent scheduler jobs.** APScheduler tracks `max_instances` per `id`. Registering NBA + WNBA under separate ids means a WNBA misfire / overrun does not interfere with NBA scheduling (and vice versa). The handlers each have a top-level `try/except` so exceptions never reach the scheduler loop.
- **No projection wrapper for WNBA today.** SPO-29 didn't budget the SportsDataIO WNBA projection wrapper — that's a separate epic when it comes. The daily-picks code already gracefully handles `projections = {}` per-pick (`has_projection=False`, `edge=None`, opponent metadata null), and the SPO-26 frontend tile UX already renders that state correctly. Adding the wrapper later is `"wnba"` → `_LEAGUES_WITH_PROJECTIONS`, nothing else moves.
- **Frontend scope reduction is intentional.** The NBA picks page integrates with bet slip, agent widget, lineup badges, and a right-click context menu — all NBA-context-coupled today. SPO-35's acceptance is "`/wnba/picks` renders" — the new page calls the right endpoint, parses the right schema, renders cards with probability tiering. Bet-slip / agent / lineup integration are separate follow-ups, tracked as the WNBA contexts are built out.

## Tests

```
$ cd backend
$ .venv/bin/python -m pytest tests/test_daily_analysis_league.py tests/test_daily_analysis.py -q
75 passed in 0.16s

$ .venv/bin/python -m pytest -q --ignore=tests/test_wnba_odds_integration.py
2 failed, 590 passed, 4 skipped
```

The 2 failures (`test_agent_chat_endpoint_validates_action_and_uses_service`,
`test_lineups_api_returns_team_count`) **also fail on `HEAD~1`** (the
audit-only commit) — verified by stashing SPO-35 work and re-running the
same two tests. Root cause is unrelated to this PR: a slowapi /
ConnectionError exception path in the rate-limit middleware (`slowapi/
extension.py:81: AttributeError: 'ConnectionError' object has no
attribute 'detail'`) when Redis is offline at test time. Flagged for
Sentinel as a separate environmental issue.

Frontend:

```
$ cd frontend
$ npx tsc --noEmit
EXIT=0
```

Integration test (live WNBA slate) — gated behind `RUN_INTEGRATION=1`
per CLAUDE.md anti-hallucination rule §2 — is recommended for Sentinel
to author against the WNBA event IDs already captured by SPO-31
(`docs/research/wnba-rollout/odds_api_wnba_markets.md` §3.1). Forge did
not add it here because the integration plumbing for `daily_analysis`
boils down to "live odds_provider call" — exact same code path as the
SPO-33 odds integration test, just with `league="wnba"` in the call.

## Follow-ups

1. **SportsDataIO WNBA projections wrapper.** Add `"wnba"` to
   `_LEAGUES_WITH_PROJECTIONS` once the wrapper lands. Daily-picks
   `edge` / `opponent_rank` light up automatically — no further changes
   to `daily_analysis.py` or the API.
2. **SPO-34 rebase.** SPO-34 currently has WNBA lineups Redis-only with
   three deferred-migration comments referencing this work. When SPO-34
   PR #13 lands on `dev`, drop those three `if self.league == "nba":`
   gates in `lineup_service.py` so WNBA lineups persist to
   `team_lineup_snapshots` (now possible thanks to this migration).
3. **`/wnba/picks` integrations.** Bet-slip / agent-widget / lineup
   badges / right-click context menu — tracked separately as the WNBA
   contexts are built. Drop-in once the shared contexts learn the WNBA
   route shape.
4. **Live integration test (Sentinel).** `@pytest.mark.integration`
   test against the WNBA event IDs in
   `docs/research/wnba-rollout/odds_api_wnba_markets.md` §3.1, gated
   behind `RUN_INTEGRATION=1`.
5. **Pre-existing slowapi/Redis test failures.** Two tests fail on
   `origin/dev` (independent of SPO-35) due to an exception path in
   slowapi when Redis is offline. Worth a separate ticket — out of
   scope here.

## Workflow

Forge implement → **Lens review next** → Sentinel test+push → owner squash-merge.

Branch: `feature/SPO-35-wnba-daily-picks` (off `origin/dev` @ 328f9bd,
unrelated to the open SPO-34 PR #13).
