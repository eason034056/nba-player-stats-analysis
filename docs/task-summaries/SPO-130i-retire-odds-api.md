# SPO-130i — Retire The Odds API

NBA odds come from BALLDONTLIE only. `PROVIDERS["nba"]` is that provider. The old client, its settings, and its environment variables are gone.

## QA fix: why the marker-before-delete is the bug

`flush_retired_odds_cache` used to `SET NX` the permanent key `migrations:spo130i:odds_flush_done` and only then `SCAN` and `DELETE`. The marker has no TTL. If a delete raises halfway, the `except` logs a warning and returns. The marker is already set, so the next start sees it and does not scan. Keys that were not deleted stay forever.

One of those keys is `odds:quota_usage:v1`. `OddsMarketGateway.is_quota_protected` (called from `get_market_snapshot`, `prewarm_hot_keys`, and `refresh_market_snapshot`) reads that key. A low remaining ratio makes a background refresh return the stale snapshot or skip the warm-up. BALLDONTLIE never writes `odds:quota_usage:v1`, so nothing repairs the ratio. A leftover key can pause refreshes for good.

The fix is two changes, not a retry flag on top of the same order. A short lock (`migrations:spo130i:odds_flush_lock`, `SET NX EX 60`) keeps two replicas from flushing at once. The permanent marker is set only after every delete has succeeded. An error releases the lock and leaves the marker unset, so the next start tries again. Separately, the quota guard and its key reads and writes leave `odds_gateway`. Background refresh no longer looks at `odds:quota_usage:v1`. The flush still deletes that key so a leftover does not sit in Redis, but nothing in the app reads it after this change.

## Metrics rename (for the frontend PR)

Do not edit `frontend/` in this PR. The metrics JSON changed:

| | Old | New |
|---|---|---|
| Top-level key | `odds_api_quota` | `bdl_rate` |
| Inner fields kept | `remaining`, `used`, `total`, `remaining_ratio` | same four fields |
| Inner field removed | `quota_protected` | gone |

`bdl_rate` is `null` until a BALLDONTLIE response has carried a rate-limit header.

## Changes

| Area | What changed |
|---|---|
| Registry | `PROVIDERS["nba"]` always returns the BALLDONTLIE provider. `nba_odds_provider` is gone. |
| Client | `backend/app/services/odds_theoddsapi.py` is deleted. Callers use the BALLDONTLIE provider. |
| Settings | `odds_api_key`, `odds_api_base_url`, and the three odds-quota percents are gone. `bdl_rate_limit_per_min` stays `5` in code. |
| Routes | Event list cache keys end in `:balldontlie`. No-vig, suggest, and event detail return 404 for an id that is not ASCII digits. Event detail checks that before any provider call. Props and reads still use the wider stored-id check. |
| Jobs | Snapshot and daily analysis list only scheduled games whose tip is still ahead. Daily analysis asks for `SNAPSHOT_MARKETS` once. |
| Metrics | `GET /api/metrics` reads `PROVIDERS["nba"].rate_status()` and returns `bdl_rate`. |
| Startup | First start deletes the old Redis keys once. See the flush section. An empty `BALLDONTLIE_API_KEY` logs a warning and does not print the value. |
| Env | `ODDS_API_KEY`, `ODDS_API_BASE_URL`, and `NBA_ODDS_PROVIDER` are gone from `env.example`, compose, and CI. `env.example` sets `BDL_RATE_LIMIT_PER_MIN=600`. Compose uses `${BDL_RATE_LIMIT_PER_MIN:-600}`. |
| Scripts | `scripts/explore_odds_api_extensions.py` is deleted. The recorder no longer calls the old feed. |
| Tests | Live old-feed tests are deleted. A guard test imports the NBA surfaces and checks the provider name and the import graph. |

## Redis flush

On startup, `flush_retired_odds_cache` takes `migrations:spo130i:odds_flush_lock` with `SET NX EX 60`, then `SCAN`s (never `KEYS`):

- `daily_picks:nba*`
- `odds_snapshot:*`
- `odds_snapshot_meta:v2:*`
- `events:nba:*`
- `*:wnba:*` (this also matches leftover `lineups:wnba:*` and `daily_picks:wnba:*`)

It also deletes the exact key `odds:quota_usage:v1`. Nothing reads or writes that key. The permanent marker `migrations:spo130i:odds_flush_done` is set only after every delete succeeds. A second start sees the marker and deletes nothing. A second replica that finds the lock returns without setting the marker. An error releases the lock, leaves the marker unset, logs a warning, and does not stop startup. The next start retries.

The same commands are in `docs/deployment/aws.md` and `docs/deployment/aws-steps-zh-TW.md`. Production must set `BALLDONTLIE_API_KEY` and `BDL_RATE_LIMIT_PER_MIN=600`. The code default stays 5, so a process that starts without the env var limits itself to 5 calls a minute.

## Event ids

Live NBA odds routes use decimal BALLDONTLIE game ids. No backend code requires a 32-hex id. `bulk_props.event_id_is_well_formed` still allows 1–128 characters from `[A-Za-z0-9_-]`, so a stored snapshot row with a 32-hex id can still be read. The comment is in `backend/app/services/bulk_props.py`.

`GET /api/nba/events/{id}` uses `_malformed_bdl_event_id` first. A non-ASCII or non-digit id, including a 32-hex id, `abc`, and `12a`, is 404 and does not call the provider. No-vig and suggest use the same check. `_game_id` uses `isascii()` and `isdigit()`, so `١٢٣` raises before HTTP.

`/props` and `/reads` were left on `event_id_is_well_formed`. A 32-hex id with no snapshot is HTTP 200 and an empty body, or HTTP 503 when Postgres is down. A digit-only check would turn that into 404. Those two routes do not call BALLDONTLIE.

## Tests

Full backend suite after the QA fix, `ODDS_API_KEY` unset, throwaway Postgres 16 migrated through 005:

- 1872 passed
- 17 skipped
- 4 xfailed
- 0 failed

The first cut of this branch, before the QA fix, was 1864 passed, 17 skipped, 4 xfailed, 0 failed. `test_spo132b_optional_vpc.py::TestVpcIdConsole` did not fail in either run.

The new tests were run on `ab25d50` before the code change. All eight failed: the marker stayed set after a bad delete, a pre-set lock did not stop the flush, `١٢٣` did not raise, `rate_status` raised out of `/metrics`, a hex id was looked up (`Event not found` instead of `Malformed event_id`), and a background refresh did not run while `odds:quota_usage:v1` was present.

### Mutation checks

Each change was reverted before the commit.

First cut:

1. Importing the deleted odds module from `backend/app/api/nba.py` made both guard tests fail (`ModuleNotFoundError`, and the source scan listed `nba.py`).
2. Dropping `SET NX` and the early return made the second-run flush test fail (`assert 1 == 0`: the second call deleted a key created after the first flush).
3. Pointing `PROVIDERS["nba"]` at a provider named `sample` made `test_nba_provider_is_balldontlie` fail (`assert 'sample' == 'balldontlie'`).

QA fix:

1. Setting the done marker before the deletes made `test_flush_retries_when_a_delete_fails_midway` fail (`assert '1' is None`).
2. Restoring a skip when `odds:quota_usage:v1` is present made `test_background_refresh_runs_when_stale_quota_key_exists` fail (`assert 1 == 2`).
3. Switching `GET /api/nba/events/{id}` back to `event_id_is_well_formed` made `test_non_digit_event_id_is_404_with_no_provider_call` fail for the hex id, `abc`, and `12a` (`Event not found` instead of `Malformed event_id`).

## Blast radius

Callers after the QA fix:

| Name | Where | What this change does |
|---|---|---|
| `is_quota_protected` | was `odds_gateway.py` at the stale-snapshot branch, the empty-cache background branch, `prewarm_hot_keys`, and `refresh_market_snapshot` | Removed, with `record_quota_usage`, `get_quota_usage`, and the quota-key write in `_fetch_and_store`. No caller remains. |
| `odds:quota_usage:v1` | flush exact key; tests that seed it; deploy docs | Nothing in `backend/app` or `frontend/` reads it. The flush still deletes a leftover. Historical task summaries still name it. |
| `odds_flush_done` | `odds_cache_flush.py`, the two AWS docs, this summary | Set only after every delete succeeds. |
| `event_id_is_well_formed` | `bulk_props.py` (definition); `nba.py` props and reads; `_malformed_bdl_event_id` for the 1–128 length | Unchanged on props and reads, so a stored hex id stays 200-empty or 503. The detail route no longer uses it as the first check. |
| `_game_id` | `bdl_odds_provider.py` `_props_filtered` and the event-odds body | Rejects a non-ASCII digit string before `get_player_props`. |
| `_positive_game_id` | `bdl_client.py` `get_game` | Not changed. The odds path raises in `_game_id` first. |

- The frontend metrics reader still expects `odds_api_quota` until the paired frontend PR.
- Event-list cache keys gained a `:balldontlie` suffix. The startup flush deletes `events:nba:*`, which covers the old key and the new one.
- Snapshot and daily jobs drop a game that has tipped or is not `scheduled`.
- A connected database always attempts the 002 live write. A missing parent is counted and does not fail the line-table write.
- A non-digit id is 404 on no-vig, suggest, and event detail.
- An empty `BALLDONTLIE_API_KEY` warns at startup. Odds calls then fail.
- A hot-key member whose stored provider name is not `balldontlie` is skipped, not deleted. Its last-seen TTL is 5 minutes.

## Remaining search hits

`rg -n -i "odds_api_key|ODDS_API_KEY|theoddsapi|the-odds-api|NBA_ODDS_PROVIDER"` outside this list is empty.

| Hit | Why it stays |
|---|---|
| `frontend/lib/schemas.ts`, `frontend/app/about/page.tsx` | Paired frontend PR. This PR does not edit `frontend/`. |
| `docs/task-summaries/SPO-*.md` listed by that search | Historical task notes. Not rewritten. |
| `docs/decisions/SPO-145/decision_20261121_nba-only.md` | Decision record. Not rewritten. |
| `docs/research/event-page-stat-expansion/research_odds_api_markets.md` | Research record. Not rewritten. |
| `backend/tests/fixtures/same_slate/2026-11-22_OKC@MIA__odds_api_events.json` | Recorded request URL. The same-slate scorer still reads this file. |
| `backend/tests/fixtures/same_slate/2026-11-22_OKC@MIA__odds_api_odds.json` | Same. The saved URL has no key. |

## Follow-ups

- The paired frontend PR should read `bdl_rate` and stop linking the old odds site.
- Deploy must set `BALLDONTLIE_API_KEY` and `BDL_RATE_LIMIT_PER_MIN=600`.
- `bulk_props.event_id_is_well_formed` still accepts a stored hex id. Live odds routes do not.

## Progress notes (for the docs PR)

| Ticket | PR | Note |
|---|---|---|
| SPO-130i | this PR | NBA odds are BALLDONTLIE only. `PROVIDERS["nba"].name` is `balldontlie`. The old odds client, `odds_api_key`, `odds_api_base_url`, `nba_odds_provider`, and `ODDS_API_KEY` / `ODDS_API_BASE_URL` / `NBA_ODDS_PROVIDER` are gone. `GET /api/metrics` key `odds_api_quota` is now `bdl_rate` (`remaining`, `used`, `total`, `remaining_ratio`; `quota_protected` removed). A `rate_status` error returns `bdl_rate: null`. Code default `bdl_rate_limit_per_min` stays 5. `env.example` and compose set 600. Production must set `BALLDONTLIE_API_KEY` and `BDL_RATE_LIMIT_PER_MIN=600`. Startup warns, without the value, when `NBA_ODDS_PROVIDER` or `ODDS_API_KEY` is still set. First start takes `migrations:spo130i:odds_flush_lock` (`SET NX EX 60`), `SCAN`-deletes `daily_picks:nba*`, `odds_snapshot:*`, `odds_snapshot_meta:v2:*`, `events:nba:*`, `*:wnba:*` (also `lineups:wnba:*` and `daily_picks:wnba:*`), and `odds:quota_usage:v1`, then sets `migrations:spo130i:odds_flush_done`. The quota guard is gone, so a leftover quota key cannot skip a background refresh. Event detail rejects a non-digit id before any provider call. Props and reads keep the stored-id check. `001` / `002` / `005` were not altered. `docs/progress.md` was not edited. |
