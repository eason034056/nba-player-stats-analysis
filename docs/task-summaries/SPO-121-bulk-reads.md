# SPO-121 — Reads for every posted player, tier from the blend

- Ticket: SPO-121
- Branch: `feature/SPO-121-bulk-reads` (from `origin/dev`)
- Base: `dev`

## Summary

Every posted player on an NBA event now has a read: side, combined probability, tier, and signals. The read is a new route, `GET /api/nba/events/{event_id}/reads`, not a field on the bulk-props player. NBA `DailyPick.tier` and the daily-picks board use `combined_probability` with the existing 0.70 / 0.65 / 0.56 cutoffs. Storage still uses the historical rate. `season_mean` is on player history and on `DailyPick`. Bulk props players carry `position` and `team_code` from the newest game log.

WNBA routes, the WNBA filter, and the WNBA tier are unchanged. The signal model's math is unchanged.

## Changes

| Area | File | Change |
|---|---|---|
| HTTP | `backend/app/api/nba.py` | `GET /api/nba/events/{event_id}/reads`. Optional `market` (one key). 404 / 400 / 503 / 500. Same limiter as props. No Odds API call. |
| Reads | `backend/app/services/event_reads.py` | One `PropRead` per posted player from the latest snapshot, the game log, and a Redis projection only when that key already exists. 60s cache. |
| Schema | `backend/app/models/schemas.py` | `PropRead`, `EventReadsResponse`. `season_mean` on history and `DailyPick`. `position` and `team_code` on `BulkPropPlayer`. |
| Board | `backend/app/services/daily_analysis.py` | NBA tier and `select_daily_picks` use `combined_probability`. WNBA still uses `probability`. Storage unchanged. |
| Query text | `backend/app/api/daily_picks.py` | The NBA floor is described as `combined_probability`. The query name and the 0.65 default stay. |
| History | `backend/app/services/csv_player_history.py` | `season_mean` on the season sample. `latest_team` beside `latest_position`. |
| Props | `backend/app/services/bulk_props.py` | Roster fields filled on the way out, including a cache hit. Not stored in the cached JSON. |
| Shift | `backend/app/services/board_shift.py`, `scripts/measure_spo121_board_shift.py` | Counts who enters, leaves, and changes tier. |
| Tests | `backend/tests/test_spo121_bulk_reads.py` and the SPO-111 / daily-analysis / SPO-113 cases the new board touches | Route, schema, tier boundaries, filter, roster, recorded shift. |
| Docs | `docs/decisions/spo-121-bulk-reads/decision_20261110_bulk-reads-and-combined-tier.md` | Route choice and the tier input. |

## Why

Props have to paint from a stored snapshot without waiting on history. Putting the read on `BulkPropPlayer` would make every props response pay for every market's signal math and would mix two caches. The game page already asks for one market and joins on player name, so a sibling route matches that use.

The owner asked for the tier to follow the blend, with the same cutoffs. Storage stays historical so the Lean floor and the candidate set do not move in the same change. A row whose blend is missing does not fall back to the hit rate: that would hide Out, Doubtful, and a one-sided price. WNBA has no blend, so it keeps the historical filter and tier.

## API contract

`GET /api/nba/events/{event_id}/reads`

| Name | Type | Required | Meaning |
|---|---|---|---|
| `market` | string | no | One snapshot market key. Omit for every stored market. Unknown key: HTTP 400. More than one key: HTTP 400. |

`event_id` uses the same well-formed check as props. A bad id is HTTP 404. A well-formed id with no snapshot is HTTP 200, `reads` empty, `snapshot_at` null. Postgres down is 503. A failed snapshot query is 500. None of those call the Odds API.

`EventReadsResponse`: `event_id`, `market` (the query, or null), `snapshot_at`, `source` always `"snapshot"`, `reads`.

`reads[]`: `player`, `market`, `line`, `side` (`over`, `under`, or null), `combined_probability`, `tier` (`Strong play`, `Playable`, `Lean`, or null), `signals` (five, or null).

## Breaking changes for the frontend

Field names on existing payloads stay. These behaviors change for NBA:

- `DailyPick.tier` is `read_tier(combined_probability)`. The strings are the same. The tier is null when the blend is missing, not finite, or below 0.56, even when the historical rate is 0.90.
- `GET /api/nba/daily-picks` and the analysis trigger apply `min_probability` to `combined_probability`. Default remains 0.65 and 10 games. `probability` is still the historical rate and is still on the payload. Out, Doubtful, or no two-sided price at the modal line drops the row.
- A player whose historical rate is below 0.56 is still not stored, so they still cannot appear.

Not changed, called out so the frontend does not assume they moved:

- `top_read` is still the highest historical probability.
- `GET /api/picks/today` still filters on the historical rate.

Additive, null when unknown:

- `season_mean` on player history and on `DailyPick`.
- `position` and `team_code` on `BulkPropPlayer`.
- The new reads route.

WNBA serializes the new keys as null and does not compute them. The WNBA daily-picks filter and tier are unchanged.

## Measured shift

Recorded `player_points` capture `07361a8381206817e27bd2697fad7479` (tip `2026-11-10T00:10:00Z`) against the shipped game log. Projections omitted. 15 posted, 11 stored.

| | Count |
|---|---|
| Old board | 4 |
| New board | 6 |
| Entered | 3 |
| Left | 1 |
| Tier changed | 5 |

Entered: Dyson Daniels over (0.6316 → 0.6862), Nickeil Alexander-Walker over (0.5897 → 0.6730), Ziaire Williams over (0.6071 → 0.6738). Left: Matisse Thybulle under (0.7333 Strong play → 0.6386 Lean). Jalen Johnson over changed Lean → null (0.5972 → 0.5361) and was on neither board. Detail is in the decision note. `scripts/measure_spo121_board_shift.py` reprints the JSON.

## Tests

- Tier boundaries at 0.56, 0.65, and 0.70, including the value just below each cut. The board uses the blend while the historical rate is held at 0.99.
- A missing or non-finite blend leaves the NBA board. WNBA still uses `probability`.
- Enter, leave, and relabel on `measure_board_shift`.
- The recorded capture's counts are locked to the table above.
- Every posted player on the recorded points body has a read. A binary market and an Out injury stay on the list with a null tier.
- The route returns 200, 400, 404, and 503, and does not await the odds gateway. The reads module does not import it. A cache hit does not read Postgres again.
- Old history, pick, and bulk-player payloads still parse. New keys are present and null when the source has no value.

## Follow-ups

- `top_read` and `GET /api/picks/today` still use the historical rate.
- Storage still drops anyone below historical 0.56, so a high blend cannot add them.
- The recorded shift is one event and one market, with projections omitted.
- Default `season_mean` is often null: the shipped log is mostly 2025-2026, and the season label for 2026-11-10 is 2026-2027.
