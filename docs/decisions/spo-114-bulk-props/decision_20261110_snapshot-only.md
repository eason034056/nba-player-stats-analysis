# Decision — SPO-114 bulk props are snapshot-only

- **Ticket:** SPO-114 (backend half)
- **Date:** 2026-11-10
- **Status:** Accepted for this change. Options B and C are not accepted and are not implemented.

## Context

The event board needs a line for every player in one NBA game. The Odds API charges per market key that returns odds on an event. Empty markets cost 0. A live call from the page would repeat work the snapshot scheduler already does.

`SNAPSHOT_MARKETS` is 12 keys (`odds_snapshot_service.py`): points, rebounds, assists, threes, steals, frees made, field goals, the four combo totals, and double-double. Frees made and field goals are the Tier B keys that are usually empty, so a game costs about 10 credits per refresh rather than 12.

The scheduler runs that refresh three times a day, at UTC 16:05, 22:05, and 23:35 (`scheduler.py`, jobs `odds_snapshot_early`, `odds_snapshot_mid`, `odds_snapshot_final`).

## Decision

Serve `GET /api/nba/events/{event_id}/props` only from the latest row set in `odds_line_snapshots` for that event. `source` is `"snapshot"`. A missing capture is HTTP 200 with empty `markets` and null `snapshot_at` / `data_age_seconds`. The handler does not call the Odds API gateway or provider on a hit, a miss, a cache failure, or a database failure.

A short Redis cache (60 seconds) may hold the assembled JSON. The cache is not a live quote. A miss reads Postgres.

This endpoint adds **0 credits**. It does not call `/v4/sports/.../odds`.

## Credit math

| Step | Credits |
|---|---|
| One game, one refresh, `SNAPSHOT_MARKETS` | about 10. Twelve keys are requested. A key with no posted odds costs 0, and the two Tier B keys are usually empty, so the bill is about 10 rather than 12. |
| One full NBA slate, one refresh | about 75. That is the planning figure for a slate at about 10 credits per game. |
| Scheduler, 3 snapshots per day | about 225 per day (75 × 3). |
| This endpoint, any number of page views | 0. Reads are Postgres, plus an optional 60s Redis copy of the JSON. |

The 75 and 225 figures are the slate-level planning numbers for Option A. They are not a new measurement of the Odds API invoice. They follow from "about 10 credits per game" times a full slate of about 75 credits, times the three scheduled captures.

## Options not implemented

These stay pending the owner's decision. This change does not add either path, and the tests fail if the gateway or provider is called.

- **Option B.** On-demand refresh: at most one Odds API call per game per 30 minutes when the stored snapshot is missing or considered stale.
- **Option C.** One extra pre-tip snapshot on the scheduler, in addition to the three captures already scheduled.

## Consequences

- The board can be as stale as the last scheduled capture, plus up to 60 seconds of response cache. `snapshot_at` and `data_age_seconds` are on the payload so the client can show that age. `data_age_seconds` is recomputed on a cache hit.
- Bovada-style alternate ladders: the read path counts each bookmaker once. `_main_book_line` mirrors `daily_analysis._main_book_line` (SPO-115) and stays local until PR #43 merges, when one of the two copies should be removed. Remove the vig, then keep the pair closest to even money. A two-sided rung beats a one-sided Over. Equal distances keep the lower line. With no usable price, the fallback is the mode of the posted lines, not the lower line. On the recorded player_points fixture, Luka's Bovada vote is 36.5 (-115/-115).
- WNBA is out of scope while that league is paused. No WNBA route was added. A `league` column on `odds_line_snapshots` is deferred for the same reason. It was not added.

## Deferred, not this change

- Since SPO-117 the writer stores every two-sided total. `_process_event` pairs Over and Under on `(player_name, point)` and writes one row per rung (`odds_snapshot_service.py`). The unique key is `UNIQUE (snapshot_at, event_id, player_name, market, bookmaker, line)` (`db.py`, constraint `odds_line_snapshots_book_line_key`; the startup block widens a database created with the older key). A book that posts a ladder keeps the main total and every alternate. The read path still picks one main line per book when it votes.
- No `league` column. WNBA is paused.
