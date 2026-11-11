# SPO-131 — NBA injuries from BALLDONTLIE via backend cache

- Ticket: SPO-131
- Branch: `feature/SPO-131-bdl-injuries` (from `origin/dev`)

## Summary

NBA product agents read the BALLDONTLIE injury cache only when `NBA_INJURY_SOURCE` is `bdl`. The default is `espn_cbs`, and an unknown value stays on `espn_cbs`. The API key does not select the feed: it is already set in real environments, and the refresh job is not registered, so an empty cache would mark every NBA report `injury data unavailable`. The flag is flipped to `bdl` only after `nba_injuries_refresh` lands with SPO-130a. When the flag is `bdl`, the request path only reads Redis. A missing or stale snapshot is `caution` / `injury data unavailable`. WNBA stays on the ESPN/CBS scrape for every flag value.

## Changes

| 檔案 | 變更 |
|---|---|
| `backend/app/services/nba_injuries.py` | Normalize BDL rows, page through `next_cursor` (stop on a missing, null, or repeated cursor, and at 20 pages), write `injuries:nba:latest` with a 24h TTL, and treat `fetched_at` older than 6h as stale. Hitting the 20-page cap does not write. `entries` that is not a list is stale. An empty team map, or rows that normalize to nothing, does not write. A first page with `data: []` and a usable map stores an empty list. Unknown statuses containing `Out` become `Out`; every other unknown status becomes `Questionable`. `BdlInjuryClient` is the protocol SPO-130a will implement. A `ValueError` logs a warning. Any other refresh failure logs the exception type and not the message. Both leave the previous cache. The request-path Redis client uses a 2 second socket timeout. |
| `backend/app/settings.py` | `NBA_INJURY_SOURCE` (default `espn_cbs`; `bdl` is the other allowed value; comparison is case-insensitive), `BALLDONTLIE_API_KEY` as `SecretStr`, and `NBA_INJURIES_REFRESH_MINUTES` (default 15). The job is not registered. |
| `scripts/agents/tools/historical.py` | NBA reads the cache only when `NBA_INJURY_SOURCE` is `bdl`. `BDL` folds to `bdl`. A blank value, an unknown value, and a failure reading the setting keep `InjuriesPageFetcher` and log a warning. WNBA always keeps it. A stale, missing, or malformed cache on the `bdl` path does not default players to Healthy, including when the key is unset. Player matching prefers `bdl_player_id`. ESPN and CBS rows for the same player use the first match. Two BDL rows with different ids, or the same name and no id, are not guessed. A single name can still be found off the CSV team. The caution payload includes `fetched_at`. The request-path cache client is closed with `await local.close()`. |
| `scripts/agents/data_logger.py` | Source labels name the BALLDONTLIE cache for `NBA_INJURY_SOURCE=bdl`, and ESPN/CBS for the default and for WNBA. |
| `backend/tests/fixtures/bdl/player_injuries__page1.json` | Recorded `GET /v1/player_injuries?per_page=100` page, copied unchanged. |
| `backend/tests/fixtures/bdl/standings_2026.json` | Recorded `GET /v1/standings?season=2026`, copied unchanged. Source of the team-id map in tests. |
| `backend/tests/test_spo131_bdl_injuries.py` | Normalizer, 30-team code check, pagination from copies of the recorded page, failed page, stale and missing cache, one-team tool output, no network on the agent path, and the `NBA_INJURY_SOURCE` switch (default, `espn_cbs`, `bdl`, `BDL`, unknown, blank, settings read failure, no key, WNBA). |
| `backend/tests/test_spo131_qa.py` | QA cache edge cases. Every BDL body is the recorded page or a copy of it. The three strict xfails (malformed `entries`, empty team map, unrecognized status) are removed because those cases now pass. |
| `backend/tests/test_spo98_gaps.py` | Injury-fetch stubs accept the new optional `league` argument. |
| `docs/decisions/SPO-131/decision_20261111_bdl-injury-cache.md` | Why the cache exists, why Doubtful maps to Questionable, why the team map is not hand-typed. |

## Why

The shared BALLDONTLIE key allows 5 requests per minute. Injury lookups happen inside a user request and can run more than once per question, so the agent must not be the caller. The injury payload has no timestamp and no history; `fetched_at` on the cache body is the clock, and entries keep `bdl_player_id`, `raw_status`, and `fetched_at` for a later history table. `Doubtful` becomes `Questionable` so the scorer's existing unresolved bucket applies. Eason chose that mapping in the Sports Lab Lead chat on 2026-11-10 (~10:34 PM CT). `raw_status` keeps the original word. `Available` is dropped. The standings fixture's abbreviations already equal `NBA_TEAMS` and `TEAM_ALIASES`, so the id-to-code map is read from that file rather than typed. `NBA_INJURY_SOURCE` defaults to `espn_cbs` because the key is already deployed and the refresh job is not. The flag moves to `bdl` only after `nba_injuries_refresh` lands with SPO-130a. See `docs/decisions/SPO-131/decision_20261111_bdl-injury-cache.md`.

## Tests

Recorded fixtures only. No live BALLDONTLIE call.

- `normalize`: 5 `Available` rows dropped, 2 `Doubtful` rows become `Questionable` with `raw_status` kept, team codes come from the standings file, and those 30 codes equal `NBA_TEAMS` and `TEAM_ALIASES`.
- Refresh serves the recorded page and then a last page whose `next_cursor` is null, and again whose `next_cursor` is absent. A client that repeats one `next_cursor` stops on the second call. A client that never ends stops at 20 pages, logs the cap, and does not replace the previous snapshot.
- Redis TTL is 24 hours. A body 7 hours old is still in the cache and is stale: the injury report is `caution` / `injury data unavailable` with that `fetched_at`, which is the stale path rather than a missing key.
- A page without `data` is a copy of the recorded page with `data` removed. It logs a warning and keeps the previous cache. An unexpected exception logs the exception type and not the message, and keeps the previous cache.
- A failure on the first page, a failure on the second page, and a cache write that returns false all leave the previous snapshot in place, including a non-empty list.
- Missing cache and a snapshot older than 6 hours are `stale`. Exactly 6 hours is not.
- `get_official_injury_report` for one club in the fixture matches the normalized rows. The call does not open a socket, does not scrape, and does not refresh.
- A club with no rows in a fresh snapshot stays `neutral`. A missing or stale snapshot is `caution` with `injury data unavailable`, and teammate impact does not label stars Healthy.
- A dummy key with the flag unset, and a dummy key with `espn_cbs`, still use the ESPN/CBS fetcher and do not open the cache.
- `bdl` plus a fresh cache returns that team's rows. `bdl` plus a missing or stale cache is `caution` / `injury data unavailable`.
- An unknown flag value, a blank value, and a failure reading the setting are logged and use the ESPN/CBS fetcher.
- `BDL` is the same as `bdl` after strip and lowercase. It does not log an unknown-value warning.
- `bdl` with no key and a fresh cache returns that team's rows. `bdl` with no key and a missing or stale cache is `caution` / `injury data unavailable`, and the scraper is not called.
- An empty `SecretStr` is not a configured key.
- A fresh body whose `entries` is missing, null, a string, or an object is `caution` / `injury data unavailable`. A fresh `entries: []` is `neutral`.
- An empty team map, and a page of rows that all drop, leave the previous snapshot. A copied page with `data` cleared and a usable team map stores an empty list.
- `Out For Season` is stored as `Out` with `raw_status` kept. The caution payload includes `fetched_at`.
- A player id match wins when two rows share a name. A row on a team other than the CSV team is still found by a unique name.
- WNBA uses the ESPN/CBS fetcher for the default, `espn_cbs`, `bdl`, and an unknown flag.

```
cd backend && python -m pytest tests/test_spo131_bdl_injuries.py tests/test_spo131_qa.py -q --tb=short
# 78 passed

cd backend && python -m pytest --tb=line -q
# 1275 passed, 26 skipped, 6 xfailed

cd scripts/agents && python -m pytest tests --tb=line -q
# 114 passed
```

No live BALLDONTLIE call. Integration test not run (`RUN_INTEGRATION` unset). The two Redis-sensitive tests named for this repo (`test_agent_chat_endpoint_validates_action_and_uses_service`, `test_lineups_api_returns_team_count`) passed in this run.

## Follow-ups

- SPO-130a: `bdl_client.py` implements `BdlInjuryClient`, including 429 retries and `BdlError`. Narrow the refresh `except` to `BdlError`. Register scheduler job `nba_injuries_refresh` at `NBA_INJURIES_REFRESH_MINUTES` (default 15), only when `BALLDONTLIE_API_KEY` is set. Flip `NBA_INJURY_SOURCE` to `bdl` in the same change, after the job is filling `injuries:nba:latest`.
- SPO-130d: production `team_id` to abbreviation map. Tests keep building it from the standings fixture.
- Backend follow-up, not this PR: Postgres history of these entries. The normalized shape is already what that table should store.
