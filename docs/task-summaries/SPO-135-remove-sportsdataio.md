# SPO-135 — remove the projection vendor

- Ticket: SPO-135
- Branch: `feature/SPO-135-remove-sportsdataio` (from `origin/dev`)
- Base: `dev`

## Summary

NBA picks no longer load a projection. `projected_value`, `edge`, and `projected_minutes` stay on `DailyPick` and are null. `has_projection` is false. The projection signal slot stays and is missing. Defense ranks come from the game log with source `csv`. `injury_status` and `lineup_confirmed` are null. WNBA daily picks are unchanged.

`GET /api/nba/projections`, the per-player route, and `POST /api/nba/projections/refresh` are gone. `player_projections` and `projection_fetch_logs` stay in the schema and are not read or written.

## Why

The old projection feed was not a model and must not reach picks, the UI, or RDS. BALLDONTLIE has no projection endpoint. A CSV average and the betting line are not substitutes.

## Changes

| Area | What changed |
|---|---|
| Removed | Projection provider, projection service, projections API, three scheduler jobs, the manual trigger, three settings, compose env lines |
| Daily analysis | No projection prefetch. Team comes from the game log. Ranks come from `defense_fields` |
| Event reads | No `projections:nba:{date}` lookup. Projection signal is missing. Defense uses the game log when the club is home or away |
| Schema | Tables retained. Docstring examples use `odds_line_snapshots` |
| Agent tools | Stubs stay unavailable. Reason is `no projection source; ML model pending` |
| Docs | Current docs updated. Projection API doc deleted. Decision log added. Four older decisions get a one-line superseded note |

## Tests / Verification

- `cd backend && python3 -m pytest --tb=line -q` → 1237 passed, 28 skipped, 6 xfailed, 0 failed. WNBA tests are in that run.
- Recorded fixture check, no live HTTP: `GET /api/health` 200 `{"ok": true, "service": "no-vig-nba"}`. `GET /api/nba/projections` 404. `GET /api/nba/daily-picks` 200, 11 picks, first pick `has_projection` false, `projected_value` / `edge` / `projected_minutes` / `injury_status` / `lineup_confirmed` null, `combined_probability` 0.743, projection signal value null. `GET /api/nba/events/07361a8381206817e27bd2697fad7479/reads?market=player_points` 200, 15 reads, projection signal value null, combined still set.
- Diff against `origin/dev`: 718 lines added, 3726 lines removed.

## Follow-ups

- [ ] Drop `player_projections` and `projection_fetch_logs` after a grep shows no reader outside `db.py`.
- [ ] Paired frontend PR: stop calling `/api/nba/projections` and treat the null pick fields as the normal NBA shape.
