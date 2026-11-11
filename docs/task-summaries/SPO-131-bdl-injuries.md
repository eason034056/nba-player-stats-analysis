# SPO-131 — NBA injuries from BALLDONTLIE via backend cache

- Ticket: SPO-131
- Branch: `feature/SPO-131-bdl-injuries` (from `origin/dev`)

## Summary

NBA product agents no longer scrape ESPN and CBS on each request when `BALLDONTLIE_API_KEY` is set. A backend refresh reads `/v1/player_injuries` through a client protocol, normalizes the rows, and stores them in Redis at `injuries:nba:latest` for 6 hours. The request path only reads that key. A missing or stale snapshot is `caution` / `injury data unavailable`, not a healthy team. With no key, NBA stays on the ESPN/CBS scrape. WNBA is unchanged. The HTTP client and the scheduler job wait on SPO-130a.

## Changes

| 檔案 | 變更 |
|---|---|
| `backend/app/services/nba_injuries.py` | Normalize BDL rows, page through `next_cursor`, write and read `injuries:nba:latest`. `BdlInjuryClient` is the protocol SPO-130a will implement. Any refresh failure leaves the previous cache. |
| `backend/app/settings.py` | `BALLDONTLIE_API_KEY` (`balldontlie_api_key`) and `NBA_INJURIES_REFRESH_MINUTES` (default 15). The job is not registered. |
| `scripts/agents/tools/historical.py` | NBA with a key reads the cache only. NBA without a key, and every WNBA call, still use `InjuriesPageFetcher`. Stale or missing NBA cache does not default players to Healthy. |
| `scripts/agents/data_logger.py` | Source labels name the BALLDONTLIE cache, and still name ESPN/CBS for the fallback and for WNBA. |
| `backend/tests/fixtures/bdl/player_injuries__page1.json` | Recorded `GET /v1/player_injuries?per_page=100` page, copied unchanged. |
| `backend/tests/fixtures/bdl/standings_2026.json` | Recorded `GET /v1/standings?season=2026`, copied unchanged. Source of the team-id map in tests. |
| `backend/tests/test_spo131_bdl_injuries.py` | Normalizer, 30-team code check, pagination, failed page, stale and missing cache, one-team tool output, no network on the agent path, key-unset scrape, WNBA scrape. |
| `backend/tests/test_spo98_gaps.py` | Injury-fetch stubs accept the new optional `league` argument. |
| `docs/decisions/SPO-131/decision_20261111_bdl-injury-cache.md` | Why the cache exists, why Doubtful maps to Questionable, why the team map is not hand-typed. |

## Why

The shared BALLDONTLIE key allows 5 requests per minute. Injury lookups happen inside a user request and can run more than once per question, so the agent must not be the caller. The injury payload has no timestamp and no history; `fetched_at` on the cache body is the clock, and entries keep `bdl_player_id`, `raw_status`, and `fetched_at` for a later history table. `Doubtful` becomes `Questionable` so the scorer's existing unresolved bucket applies, and `raw_status` keeps the original word. `Available` is dropped. The standings fixture's abbreviations already equal `NBA_TEAMS` and `TEAM_ALIASES`, so the id-to-code map is read from that file rather than typed. See `docs/decisions/SPO-131/decision_20261111_bdl-injury-cache.md`.

## Tests

Recorded fixtures only. No live BALLDONTLIE call.

- `normalize`: 5 `Available` rows dropped, 2 `Doubtful` rows become `Questionable` with `raw_status` kept, team codes come from the standings file, and those 30 codes equal `NBA_TEAMS` and `TEAM_ALIASES`.
- Refresh serves the recorded page and then a last page whose `next_cursor` is null, and again whose `next_cursor` is absent.
- A failure on the first page, a failure on the second page, and a cache write that returns false all leave the previous snapshot in place, including a non-empty list.
- Missing cache and a snapshot older than 6 hours are `stale`. Exactly 6 hours is not.
- `get_official_injury_report` for one club in the fixture matches the normalized rows. The call does not open a socket, does not scrape, and does not refresh.
- A club with no rows in a fresh snapshot stays `neutral`. A missing or stale snapshot is `caution` with `injury data unavailable`, and teammate impact does not label stars Healthy.
- With the key cleared, NBA still uses the ESPN/CBS fetcher. With a dummy key set, WNBA still uses that fetcher.

```
cd backend && python -m pytest tests/test_spo131_bdl_injuries.py -q --tb=short
# 18 passed

cd backend && python -m pytest --tb=line -q
# 1215 passed, 26 skipped, 6 xfailed

cd scripts/agents && python -m pytest tests --tb=line -q
# 114 passed
```

No live BALLDONTLIE call. Integration test not run (`RUN_INTEGRATION` unset). The two Redis-sensitive tests named for this repo (`test_agent_chat_endpoint_validates_action_and_uses_service`, `test_lineups_api_returns_team_count`) passed in this run.

## Follow-ups

- SPO-130a: `bdl_client.py` implements `BdlInjuryClient`, including 429 retries and `BdlError`. Narrow the refresh `except` to `BdlError`. Register scheduler job `nba_injuries_refresh` at `NBA_INJURIES_REFRESH_MINUTES` (default 15), only when `BALLDONTLIE_API_KEY` is set.
- SPO-130d: production `team_id` to abbreviation map. Tests keep building it from the standings fixture.
- Backend follow-up, not this PR: Postgres history of these entries. The normalized shape is already what that table should store.
