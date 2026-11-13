# SPO-130c — league-keyed odds provider registry

- Ticket: SPO-130c
- Branch: `feature/SPO-130c-odds-provider-registry` (from `origin/dev` `55750de`)

## Summary

Odds reads now go through a league-keyed provider table. NBA and WNBA both still resolve to `TheOddsAPIProvider`. A caller passes `league` (`nba` or `wnba`). The sport key (`basketball_nba`, `basketball_wnba`) is chosen inside that provider, and the HTTP path and query are the same strings the previous `sport=` call sent. Snapshot cache keys gain the provider name. No BALLDONTLIE client is wired here.

## Changes

| Area | File | Change |
|---|---|---|
| Contract | `backend/app/services/odds_provider.py` | `OddsProvider` protocol: `name`, `list_events`, `get_event_props`, `rate_status`, plus the existing `get_events` / `get_event_odds`. Frozen `ProviderEvent`, `EventOdds`, `RateStatus`. `League = Literal["nba", "wnba"]`. `QuotaUsage` and `OddsAPIError` unchanged. |
| Client | `backend/app/services/odds_theoddsapi.py` | `name = "theoddsapi"`. `SPORT_KEY_BY_LEAGUE` lives here. `league=` on the HTTP methods selects that key. `list_events`, `get_event_props`, `rate_status`. |
| Gateway | `backend/app/services/odds_gateway.py` | `PROVIDERS` lookup. NBA reads `settings.nba_odds_provider` (only `theoddsapi`). Unknown league raises. `get_market_snapshot` / `refresh_market_snapshot` / `list_events` take `league`. Cache key `odds_snapshot:v2:{provider}:{league}:{event_id}:...`. Same TTL, lock, and single-flight. |
| Setting | `backend/app/settings.py` | `nba_odds_provider: str = "theoddsapi"`. |
| Call sites | `api/nba.py`, `api/wnba.py`, `odds_snapshot_service.py`, `daily_analysis.py`, `api/metrics.py`, `scripts/agents/tools/market.py`, `scripts/agents/tools/historical.py` | `sport=` replaced with `league=`. |
| Metrics | `backend/app/api/metrics.py` | `rate_status()` reads the same Redis quota object. JSON keys unchanged. |
| Tests | `backend/tests/test_spo130c_odds_provider_registry.py` | Registry, URL equality, unknown league, cache key, quota. Recorded `odds_api_*` bodies only. |
| Docs | `docs/task-summaries/SPO-130c-odds-provider-registry.md` | This file. |

## Why

The next tickets need one place that chooses a provider per league. Doing that by swapping the HTTP client in every route would change the request. This change only moves the sport-key map. `get_events(league="nba")` builds `/v4/sports/basketball_nba/events` with the same `commenceTimeFrom` / `commenceTimeTo` / `apiKey` query as `get_events(sport="basketball_nba")`. `regions` is still not sent on the events call. Props still send `regions`, `markets`, `oddsFormat`, and `bookmakers` when the caller passed bookmakers. The gateway still sorts markets and bookmakers before the request.

`PROVIDERS["nba"]` reads `nba_odds_provider` on each lookup. The only accepted value is `theoddsapi` (case-insensitive, blank counts as the default). Anything else raises `ValueError` before HTTP, and only for NBA. WNBA always uses `TheOddsAPIProvider` and does not read the setting. An unknown league raises `ValueError` (`Unknown league`) from the table and from the gateway. `sport_key_for_league` still says `Unsupported league`, which is what daily analysis already tests.

`EventOdds.bookmakers` is the Odds API bookmaker list. `player_ids` is empty for this provider. `ProviderEvent.status` is `scheduled` because the events payload has no status field. `slate_date` is the America/New_York date of `commence_time`. Routes do not consume `ProviderEvent` yet. They still call `get_events(league=...)` and read the raw dict, so filtering and `NBAEvent` fields stay on the same code path.

Cache keys were `odds_snapshot:{sport}:...`. They are now `odds_snapshot:v2:{provider}:{league}:{event_id}:{regions}:{markets}:{books}:{format}`. The meta key uses `odds_snapshot_meta:v2:` with the same tail. The lock key is still `odds_lock:` plus the snapshot key. Fresh TTL, stale TTL, and single-flight are unchanged. Old keys are not read. They expire at the existing stale TTL (900s). A hot-key member written before this deploy stores `sport` and no `league`. Prewarm maps `basketball_nba` / `basketball_wnba` for the 5-minute last-seen window, then drops an unknown sport. New members store `league` and `provider`.

`/metrics` still returns `odds_api_quota` with `remaining`, `used`, `total`, `remaining_ratio`, and `quota_protected`. `rate_status` reads `odds:quota_usage:v1`, the object `record_quota_usage` writes. No stored quota still yields `odds_api_quota: null`.

Agent tools used to map an unknown league string to `basketball_nba`. They now pass the league through, and the provider raises. `nba` and `wnba` are unchanged. The default when league is omitted is still `nba`.

## Tests

```
cd backend && pytest --tb=line -q
```

Redis on `localhost:6379`, Postgres `novig` / `novig_nba` (the CI services). Python 3.12 in this run (CI is 3.11).

| Tree | Result |
|---|---|
| `origin/dev` `55750de` | `1599 passed, 28 skipped, 7 xfailed` |
| this branch | `1610 passed, 28 skipped, 7 xfailed` |

The extra 11 passes are `tests/test_spo130c_odds_provider_registry.py` (8) and three protocol signature cases (`list_events`, `get_event_props`, `rate_status`) on the existing provider-signature test. Skipped and xfailed counts match dev.

Local API, no call to `api.the-odds-api.com`. `ODDS_API_BASE_URL` pointed at `127.0.0.1:8765`, which returned the recorded NBA events file (WNBA path rewritten only in that process). `GET /api/nba/events?date=2026-11-10&regions=us&tz_offset=0` → 200, 8 events, `sport_key=basketball_nba`, first id `07361a8381206817e27bd2697fad7479`. `GET /api/wnba/events` with the same query → 200, 8 events, `sport_key=basketball_wnba`. The mock saw exactly:

- `GET /v4/sports/basketball_nba/events` with `commenceTimeFrom=2026-11-09T23:00:00Z` and `commenceTimeTo=2026-11-11T00:59:59Z`
- `GET /v4/sports/basketball_wnba/events` with those same two parameters

`apiKey` was not written to the log.

## Blast radius

| Call site | Migration |
|---|---|
| `GET /api/nba/events` `api/nba.py` `get_events` | `league="nba"` |
| `GET /api/nba/events/{id}` | reuses `get_events`; no provider call of its own |
| `POST /api/nba/props/no-vig` | `get_market_snapshot(league="nba")` |
| `GET /api/nba/players/suggest` | `get_market_snapshot(league="nba")` |
| `GET /api/wnba/events`, `POST /api/wnba/props/no-vig`, `GET /api/wnba/players/suggest` | `league="wnba"`. `WNBA_SPORT_KEY` remains the response fallback when a raw row has no `sport_key` |
| `odds_snapshot_service._get_events` and `_process_event` | `league="nba"` |
| `POST` manual snapshot `api/odds_history.py` | calls `take_snapshot()`; that method has no sport argument and now uses the snapshot service above |
| scheduler `prewarm_hot_keys` | no argument change. Members store `league`. A member that only has `sport` is mapped, then expires with the 5-minute last-seen key |
| `daily_analysis._get_events_for_date` and `_get_props_for_market` | `league=`. `_resolve_sport_key` delegates to `TheOddsAPIProvider.sport_key_for` and is still used to reject an unknown league before I/O and to print the sport key |
| `GET /api/metrics` | `rate_status()`; same JSON |
| `scripts/agents/tools/market.py` `_get_events`, `_get_player_odds` | `league=` |
| `scripts/agents/tools/historical.py` `_infer_opponent_from_schedule` | `league=` |

Searched `backend/` and `scripts/` for `sport=`, `get_market_snapshot`, `get_events`, and `_SPORT_KEY`. The only remaining `sport=` under `backend/app` is the gateway building `/v4/sports/{sport_key}/...` from `sport_key_for_league`. Exploration scripts (`scripts/explore_odds_api_*.py`) and a few tests still call `get_events(sport=...)`. That parameter still works and sends the same URL. In-repo routes, jobs, and agent tools do not pass it.

## Follow-ups

- SPO-130d adds `BdlOddsProvider` and does not register it. `nba_odds_provider` stays `theoddsapi` until a later ticket.
- Routes still parse the raw events dict. `gateway.list_events` is available and is not what `/events` calls.
- An unknown league string in the agent tools now raises instead of silently requesting `basketball_nba`.
