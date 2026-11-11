# SPO-130a — BALLDONTLIE client with a shared rate limiter

- Ticket: SPO-130a
- Branch: `feature/SPO-130a-bdl-client` (from `origin/dev`)

## Summary

This pull request adds the BALLDONTLIE HTTP client and nothing else. It is not imported by a route, the scheduler, or the odds gateway. Calls share a Redis per-minute budget so several processes on one trial key (5/min) or one paid key (600/min) do not stampede the API. Recorded captures live under `backend/tests/fixtures/bdl/` unchanged. The live integration test is skipped unless `RUN_INTEGRATION=1` and `BALLDONTLIE_API_KEY` are set. This run did not call BALLDONTLIE.

## Changes

| Area | File | Change |
|---|---|---|
| Client | `backend/app/services/bdl_client.py` | Async HTTPX client, exceptions, Redis minute budget, `iter_pages`. |
| Settings | `backend/app/settings.py` | `balldontlie_api_key`, `bdl_rate_limit_per_min` (default 5). |
| Probe | `scripts/explore_balldontlie_api.py` | Three recorded endpoints. Prints status and rate-limit headers. Does not print the key. |
| Fixtures | `backend/tests/fixtures/bdl/*.json` | The nine captures, byte for byte. |
| Fixtures note | `backend/tests/fixtures/README.md` | Points at `bdl/` and the 429 file's `_raw` text. |
| Tests | `backend/tests/test_bdl_client.py` | URL, auth, pagination, 429, 5xx, shared budget. Live test skipped. |
| Dependency | `backend/requirements.txt` | `fakeredis==2.26.2` for the budget tests. |
| Docs | `docs/task-summaries/SPO-130a-bdl-client.md` | This file. |

## Why

The trial key allows 5 requests per minute and is shared with other programs. A per-process sleep cannot see those other callers. The counter `bdl:ratelimit:v1:window:{minute}` is in Redis, so every process on this app takes a slot from the same minute. `BDL_RATE_LIMIT_PER_MIN` is the limit until a response includes `x-ratelimit-limit`. That header is written to `bdl:ratelimit:v1:observed_limit` and replaces the configured number, up or down. A header of 5 therefore caps a process that was configured for 600, and a header of 600 lifts a process that was configured for 5.

Before a call, a full minute waits until that minute ends. A response with `x-ratelimit-remaining: 0` waits until `x-ratelimit-reset`, because some other program may already have spent the server window. On HTTP 429 the client sleeps until that same reset, or 60 seconds when the header is missing or already past, and tries again. Three 429 responses raise `BdlRateLimitError`. 5xx uses that same wait. A 4xx other than 429 raises `BdlApiError` immediately. Sleep and the clock are constructor arguments so tests move time instead of waiting.

`list_players` sends `player_ids[]` and refuses more than 100 ids before taking a budget slot. `ids[]` is not sent. `get_player_props` does not paginate. `iter_pages` follows `meta.next_cursor` and stops when it is missing, null, or unchanged.

Paths are the ones in the captures, not a remembered doc:

| Method | Recorded path |
|---|---|
| `list_games` | `GET /v1/games?dates[]=` |
| `list_players` | `GET /v1/players?player_ids[]=` |
| `list_player_injuries` | `GET /v1/player_injuries` |
| `get_player_props` | `GET /v2/odds/player_props?game_id=` |
| `list_odds` | `GET /v2/odds?dates[]=` |
| `list_projected_lineups` | `GET /nba/v1/projected_lineups?game_ids[]=` |

The only recorded 429 is `GET /nba/v1/lineups`. This client does not call that path. The file supplies the 429 text and the reset header `1794370905`. No capture contains a second injuries page. `iter_pages` is tested by requesting `cursor=15504814` and then stopping on the recorded games body, whose `meta` has no `next_cursor`. No capture shows a page-2 query string. The outgoing parameter name is `cursor`, which is the method argument and the value already stored in `meta.next_cursor`. No capture has `x-ratelimit-limit: 600`. The 600-call test keeps a recorded body and sets that header to the paid-tier value.

## Tests

```
cd backend && pytest -q
```

`1220 passed, 27 skipped, 6 xfailed`. `RUN_INTEGRATION` was unset, so `test_live_list_games_smoke` did not call BALLDONTLIE. WNBA tests that were already skipped stayed skipped.

## Follow-ups

- Wire the client into the provider, gateway, and scheduler only in a later ticket.
- Record a real injuries page 2 before treating `cursor` page-2 bytes as verified.
- Record a response whose `x-ratelimit-limit` is 600 once the key is on the paid plan.
- The 429 capture's path (`/nba/v1/lineups`) is not a client method. Add one only if a later ticket needs confirmed lineups, and only from a success capture.
