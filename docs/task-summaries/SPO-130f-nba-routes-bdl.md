# SPO-130f — NBA event routes through the odds gateway

- Ticket: SPO-130f
- Branch: `feature/SPO-130f-nba-routes-bdl` (from `origin/dev` `9b9d0c2`)

## Summary

`GET /api/nba/events` and `GET /api/nba/events/{event_id}` now ask `odds_gateway.list_event_dicts` for the local-day window. The gateway calls that league's provider. The default `nba_odds_provider` stays `theoddsapi`, so the events request is still `GET /v4/sports/basketball_nba/events` with `commenceTimeFrom` and `commenceTimeTo` only, and the ids stay hex. `NBA_ODDS_PROVIDER=balldontlie` returns the recorded 2026-11-10 digit game ids. `POST /api/nba/props/no-vig` and `GET /api/nba/players/suggest` were already on `get_market_snapshot`; they stay there. A non-digit id on those two routes is 404 only when the flag is `balldontlie`. A digit id whose props body has no rows is 200 with an empty list.

## Changes

| Area | File | Change |
|---|---|---|
| Gateway | `backend/app/services/odds_gateway.py` | `list_event_dicts` calls the selected provider's `get_events` and returns the dicts the events route already reads. |
| Routes | `backend/app/api/nba.py` | The list and the detail route use that method. The local-day filter and Redis read/write stay. `balldontlie` rejects a non-digit id on no-vig and suggest before the snapshot call. |
| Cache | `backend/app/api/nba.py` | `events_list_cache_key`. The default key stays `events:nba:{date}:{regions}:tz{offset}`. `balldontlie` appends `:balldontlie`. |
| Config | `env.example`, `docker-compose.yml` | Placeholders for `NBA_ODDS_PROVIDER`, `BALLDONTLIE_API_KEY`, and `BDL_RATE_LIMIT_PER_MIN`. No secret values. The code default of the rate limit stays 5. |
| Tests | `backend/tests/test_spo130f_nba_routes_bdl.py` | Both provider values, from the recorded fixtures. |
| Docs | `docs/task-summaries/SPO-130f-nba-routes-bdl.md` | This file. |

## Why

The events list was the last NBA read that called `odds_provider.get_events` directly, so the flag could not change it. `list_event_dicts` is the small seam: both providers already implement `get_events` with `id`, `sport_key`, `home_team`, `away_team`, and `commence_time`. The route's local-date filter is unchanged, so `tz_offset` still decides which tip belongs on the requested day. The Odds API events call still does not send `regions`; the region stays on the cache key, as it did before.

The historical cache key does not contain the provider name. Existing route tests and any warm Redis entry use that exact string, and this change leaves it in place for `theoddsapi`. Putting `:theoddsapi` on it would miss those entries. The collision the flag can cause is the other way: a digit-id list stored under the hex-id key, or the reverse. The `balldontlie` key is `events:nba:{date}:{regions}:tz{offset}:balldontlie`, so a flip cannot serve one shape from the other's key.

`POST /api/nba/props/no-vig` and `GET /api/nba/players/suggest` already called `get_market_snapshot`, whose snapshot key already contains the provider name. Under `balldontlie`, `_game_id` raises on a hex id. That used to become a 500. The routes now answer 404 and do not call BALLDONTLIE. A digit id with an empty props `data` array stays 200. The detail route still answers 404 when a well-formed id is not on that day's list.

`bdl_rate_limit_per_min` stays 5 in code. A paid limit is an environment value only.

Out of scope, and not edited: odds snapshot jobs, the manual snapshot route, hot-key prewarm, and `daily_analysis` event lists. Those still call The Odds API when the flag is `balldontlie`. That is 130g.

## Tests

```
cd backend && DATABASE_URL=<throwaway local Postgres 16 on 127.0.0.1:5432> REDIS_URL=redis://127.0.0.1:6379 python -m pytest --tb=line -q
```

`1855 passed, 35 skipped, 4 xfailed`. Not port 5434. `REQUIRE_DOCKER_TESTS` was unset, so the docker verify skipped. The three `test_spo132b_optional_vpc.py::TestVpcIdConsole` cases did not fail here: terraform is not on PATH, so they skipped.

Mutation: the list route was pointed back at `odds_provider.get_events` and the new BDL tests were run. `test_bdl_slate_returns_digit_ids_and_does_not_read_the_odds_api_key` and `test_bdl_cache_does_not_serve_a_hex_payload` returned 500 instead of 200. The call was put back on `list_event_dicts` before the suite above.

Integration test: SKIPPED. No new client, and no live call. Bodies are `backend/tests/fixtures/bdl/` and the recorded Odds API events and player-points files. Fabrication scan: PASS. No response body was typed by hand.

WNBA tests stayed in the green suite. This change does not add a WNBA provider.

## Follow-ups

- SPO-130g: odds snapshot jobs, the manual snapshot route, hot-key prewarm, and `daily_analysis` event lists still read The Odds API when the flag is `balldontlie`.
- Do not set `NBA_ODDS_PROVIDER=balldontlie` in production until that cutover. The code default stays `theoddsapi`.

## Progress notes (for the docs PR)

| 票 | PR | 結果 |
|---|---|---|
| SPO-130f | 本 PR | `GET /api/nba/events` 與 `GET /api/nba/events/{id}` 改走 `odds_gateway.list_event_dicts`。預設仍是 `theoddsapi`：請求仍是 `/v4/sports/basketball_nba/events`，只帶 `commenceTimeFrom` / `commenceTimeTo`，id 仍是 hex，快取鍵仍是 `events:nba:{date}:{regions}:tz{offset}`。`balldontlie` 用數字 game id，快取鍵多 `:balldontlie`，避免和 hex 清單撞鍵。no-vig 與 suggest 本來就走 gateway；旗標打開時非數字 id 回 404，有數字 id 但 props 沒有列回 200 空清單。`bdl_rate_limit_per_min` 程式預設仍是 5。快照工作、hot-key、`daily_analysis` 的賽事清單留給 130g。 |

---

**Ticket**: SPO-130f
**Branch**: `feature/SPO-130f-nba-routes-bdl`
**Task summary**: `docs/task-summaries/SPO-130f-nba-routes-bdl.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
