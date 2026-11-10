# SPO-111 — NBA read data for the No-Vig redesign

- Ticket: SPO-111
- Branch: `feature/SPO-111-read-data` (from `origin/dev`)
- Base: `dev`

## Summary

NBA events now carry `top_read`, the highest-probability stored daily pick for that `event_id`, or null. `DailyPick` gains `tier`, `p_over`, and `p_under`. The default NBA analysis stores candidates down to the Lean floor (0.56) and down to 5 games. `GET /api/nba/daily-picks` still defaults to probability 0.65 and 10 games, so the default board is the same set of rows as before. `min_probability=0.56` returns the Lean rows.

WNBA routes were not extended. Shared models serialize the new optional fields. WNBA storage still drops anything below 0.65 or below 10 games, and WNBA events leave `top_read` null.

`readTier` exists on Frontend PR #39 (`frontend/lib/today-board.ts`), which is not on `dev` yet. Its cutoffs are 0.70 / 0.65 / 0.56 (`strong` / `playable` / `lean` / `pass`). Backend `READ_TIER_CUTOFFS` uses those same numbers. The tuple is recorded in `docs/decisions/spo-111-read-data/decision_20261110_read-tier-cutoffs.md`.

## API contract

NBA endpoints only. Existing fields are unchanged. Types are JSON types. `top_read` is joined from the NBA daily-picks cache for the same `date` and `tz_offset` as the events request. A cache miss, or an event with no stored pick, is null. This join does not call the Odds API.

### `GET /api/nba/events`

Each object in `events` gains:

| Field | Type | Null |
|---|---|---|
| `top_read` | object | yes |
| `top_read.player` | string | no, when `top_read` is present |
| `top_read.market` | string | no, when `top_read` is present |
| `top_read.side` | string, `"over"` or `"under"` | no, when `top_read` is present |
| `top_read.line` | number | no, when `top_read` is present |
| `top_read.probability` | number, 0 to 1 | no, when `top_read` is present |

`top_read.market` is the Odds API market key used by no-vig (`player_points`), not the CSV metric on `DailyPick` (`points`). `top_read.side` is that stored pick's `direction`. `top_read.line` is that pick's `threshold`. The chosen pick is the highest `probability` for the `event_id`. An equal probability keeps the earlier stored row.

`GET /api/wnba/events` uses the same `NBAEvent` model, so `top_read` is present and null. The WNBA route does not fill it.

### `GET /api/nba/daily-picks` and `POST /api/nba/daily-picks/trigger`

Each object in `picks` gains:

| Field | Type | Null |
|---|---|---|
| `tier` | string, `"Strong play"`, `"Playable"`, or `"Lean"` | yes |
| `p_over` | number | yes |
| `p_under` | number | yes |

`tier` is null when the chosen side's probability is below 0.56. `p_over` is the share of prior games strictly above the line. `p_under` is the share strictly below the line. Either is null when that rate was not computed. Both are returned even though `direction` / `probability` still describe the chosen side.

Query defaults on `GET` are unchanged:

| Query | Default | What a lower value does |
|---|---|---|
| `min_probability` | `0.65` | `0.56` returns stored Lean rows that also clear `min_games` |
| `min_games` | `10` | `5` is the lowest accepted value and returns stored short samples |

`POST /api/nba/daily-picks/trigger` has no query floors. Its body is the published board (0.65 and 10 games), same rows as the GET default. The cache written by that run keeps the wider candidate set, which a later GET can filter.

Side choice for a stored row still prefers the published board. Over wins when both sides are at least 0.65. The Lean floor is used only when neither side reaches 0.65. A 0.57 over does not replace a 0.90 under, so the default board does not lose that under.

### `GET /api/picks/today`

Each object in `picks` gains:

| Field | Type | Null |
|---|---|---|
| `p_over` | number | yes |
| `p_under` | number | yes |

The default response still requires probability >= 0.65 and `n_games` >= 10. `min_confidence` still defaults to 0.65. The response-level `tier` field (`free` or `premium`) is unchanged and is not the read tier.

### Tiers

| `tier` | Probability |
|---|---|
| `"Strong play"` | >= 0.70 |
| `"Playable"` | >= 0.65 and < 0.70 |
| `"Lean"` | >= 0.56 and < 0.65 |
| `null` | < 0.56 |

## Changes

| Area | File | Change |
|---|---|---|
| Schemas | `backend/app/models/schemas.py` | `TopRead` on `NBAEvent.top_read`. `DailyPick.tier`, `p_over`, `p_under`. |
| Storage and tiers | `backend/app/services/daily_analysis.py` | `READ_TIER_CUTOFFS`, `read_tier`, Lean-floor storage for default NBA only, query helper, top-read join from cache. |
| Events | `backend/app/api/nba.py` | `GET /api/nba/events` attaches `top_read` after the events cache read. |
| Daily picks | `backend/app/api/daily_picks.py` | Defaults stay 0.65 / 10 and are applied to the stored candidates. Trigger returns that same board. |
| Bot picks | `backend/app/api/picks.py` | `p_over` and `p_under` on each bot pick. Default response still drops Lean rows and samples under 10 games. |
| Tests | `backend/tests/test_spo111_read_data.py`, `backend/tests/test_daily_analysis.py` | Tiers, both rates, default-board regression, Lean query, top_read, WNBA storage unchanged. |
| Decision | `docs/decisions/spo-111-read-data/decision_20261110_read-tier-cutoffs.md` | Cutoff table. |
| Progress | `docs/progress.md` | SPO-111 row. |

## Why

`top_read` sits on the event because the Today page already loads `GET /api/nba/events` per game. The number is the best stored pick for that `event_id`, which is what the redesign asked for. Putting it on the daily-picks payload instead would make the events screen wait on a second join in the client. The join reads Redis only. Running analysis from the events route would call the Odds API for props, and this ticket forbids that. Until a daily-picks run has filled the cache for the same date and timezone offset, `top_read` is null.

The published side is chosen at 0.65 before the Lean floor is considered. If Lean were applied first, a 0.57 over would be the stored side and the 0.90 under would never be stored. The default query would then drop the over and the under would be gone. That would change the default board. The regression test builds that case and expects the under.

`stats.high_prob_count` stays the count of rows on the 0.65 / 10 board. `total_picks` on the stored document counts candidates. The GET filter sets `total_picks` to the filtered length. With the default query those two numbers match, which is what the default response did before.

WNBA uses the same analysis service. The wider storage is gated on `league == "nba"` and on the service being constructed without an explicit threshold. WNBA, and any caller that passes `probability_threshold=`, keeps the old 0.65 and 10-game storage. That is why the existing WNBA tests still see the old set of rows.

`DailyPick` only adds optional fields. SPO-112 can add verdicts and `combined_probability` beside `tier` without renaming these.

## Tests

```
cd backend && pytest --tb=line -q
2 failed, 829 passed, 23 skipped, 6 xfailed
```

The two failures are the known Redis cases: `test_agent_chat_endpoint_validates_action_and_uses_service` and `test_lineups_api_returns_team_count` (connection refused on `localhost:6379`). No other failures.

`tests/test_spo111_read_data.py` covers the tier boundaries, the default-board identity (including the 0.57-over / 0.90-under case), `min_probability=0.56`, `min_games=5`, both rates, `top_read` from cache with a single events fetch and no props fetch, and WNBA storage still dropping Lean and short samples.

No new external fixture. The events join does not call a provider.

## Follow-ups

- SPO-112 can add signal verdicts and `combined_probability` on `DailyPick` next to `tier`.
- Frontend `readTier` on PR #39 already uses 0.70 / 0.65 / 0.56 (`strong` / `playable` / `lean` / `pass`). Its lean display label is "Lean only", and below 0.56 it returns `pass` where this API sends null.
- WNBA `top_read` stays null until a later ticket fills it from the WNBA daily-picks cache.
