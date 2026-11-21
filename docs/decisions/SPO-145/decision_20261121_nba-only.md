# Decision — NBA only

- **Ticket:** SPO-145a
- **Date:** 2026-11-21
- **Status:** Accepted

## Context

Eason is focusing on NBA. The backend still had a WNBA route module, four WNBA scheduler jobs, a WNBA CSV, a RotoWire WNBA parser, and league branches that built `basketball_wnba` requests.

BALLDONTLIE ids overlap across leagues. The SQL `league` column and the `league_code` check still have to accept `'wnba'` so an NBA row and a stored WNBA row cannot collide on the same id. That constraint is not tightened here.

## Decision

Remove the WNBA product code from the backend. `/api/wnba` is gone. The four jobs `wnba_daily_analysis_job`, `wnba_lineup_fetch_opening`, `wnba_lineup_fetch_active_window`, and `wnba_lineup_fetch_pre_tipoff` are not registered. `wnba_jobs_enabled` is gone. The WNBA CSV, the ESPN WNBA fixtures used only for that file, and the dedicated WNBA docs are deleted.

Keep:

- `odds_theoddsapi.py` and `ODDS_API_KEY`. NBA still defaults `nba_odds_provider` to `theoddsapi`. Retiring that client is 130i.
- The SQL value `'wnba'` on the `league` column. No migration edit. No data DELETE. Any stored WNBA rows are cleared in the 138 wipe.
- The frontend tree. SPO-145b stops the Next.js app from calling `/api/wnba`.

Redis keys `events:wnba:*`, `daily_picks:wnba:*`, `lineups:wnba:*`, and hot-key members for `basketball_wnba` should be flushed at deploy. This PR does not flush Redis and does not touch RDS.
