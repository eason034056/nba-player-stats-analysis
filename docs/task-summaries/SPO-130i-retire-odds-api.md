# SPO-130i — Retire The Odds API

NBA odds come from BALLDONTLIE only. `PROVIDERS["nba"]` is that provider. The old client, its settings, and its environment variables are gone.

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
| Routes | Event list cache keys end in `:balldontlie`. No-vig, suggest, and event detail return 404 for an id that is not all digits. |
| Jobs | Snapshot and daily analysis list only scheduled games whose tip is still ahead. Daily analysis asks for `SNAPSHOT_MARKETS` once. |
| Metrics | `GET /api/metrics` reads `PROVIDERS["nba"].rate_status()` and returns `bdl_rate`. |
| Startup | First start deletes the old Redis keys once. See the flush section. An empty `BALLDONTLIE_API_KEY` logs a warning and does not print the value. |
| Env | `ODDS_API_KEY`, `ODDS_API_BASE_URL`, and `NBA_ODDS_PROVIDER` are gone from `env.example`, compose, and CI. `env.example` sets `BDL_RATE_LIMIT_PER_MIN=600`. Compose uses `${BDL_RATE_LIMIT_PER_MIN:-600}`. |
| Scripts | `scripts/explore_odds_api_extensions.py` is deleted. The recorder no longer calls the old feed. |
| Tests | Live old-feed tests are deleted. A guard test imports the NBA surfaces and checks the provider name and the import graph. |

## Redis flush

On startup, `flush_retired_odds_cache` sets `migrations:spo130i:odds_flush_done` with `SET NX`, then `SCAN`s (never `KEYS`):

- `daily_picks:nba*`
- `odds_snapshot:*`
- `events:nba:*`
- `*:wnba:*`

It also deletes the exact key `odds:quota_usage:v1`. Nothing writes that key anymore. Leaving it would make a background refresh think the budget is gone. A second start, or a second replica, sees the marker and deletes nothing. A Redis error is logged at warning and does not stop startup.

The same commands are in `docs/deployment/aws.md` and `docs/deployment/aws-steps-zh-TW.md`. Production must set `BALLDONTLIE_API_KEY` and `BDL_RATE_LIMIT_PER_MIN=600`. The code default stays 5, so a process that starts without the env var limits itself to 5 calls a minute.

## Event ids

Live NBA odds routes use decimal BALLDONTLIE game ids. No backend code requires a 32-hex id. `bulk_props.event_id_is_well_formed` still allows 1–128 characters from `[A-Za-z0-9_-]`, so a stored snapshot row with a 32-hex id can still be read. The comment is in `backend/app/services/bulk_props.py`. No-vig, suggest, and event detail reject a non-digit id before they read odds.

## Tests

Full backend suite, `ODDS_API_KEY` unset, throwaway Postgres 16 migrated through 005:

- 1864 passed
- 17 skipped
- 4 xfailed
- 0 failed

`test_spo132b_optional_vpc.py::TestVpcIdConsole` did not fail in this run.

### Mutation checks

Each change was reverted before the commit.

1. Importing the deleted odds module from `backend/app/api/nba.py` made both guard tests fail (`ModuleNotFoundError`, and the source scan listed `nba.py`).
2. Dropping `SET NX` and the early return made the second-run flush test fail (`assert 1 == 0`: the second call deleted a key created after the first flush).
3. Pointing `PROVIDERS["nba"]` at a provider named `sample` made `test_nba_provider_is_balldontlie` fail (`assert 'sample' == 'balldontlie'`).

## Blast radius

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
| SPO-130i | this PR | NBA odds are BALLDONTLIE only. `PROVIDERS["nba"].name` is `balldontlie`. The old odds client, `odds_api_key`, `odds_api_base_url`, `nba_odds_provider`, and `ODDS_API_KEY` / `ODDS_API_BASE_URL` / `NBA_ODDS_PROVIDER` are gone. `GET /api/metrics` key `odds_api_quota` is now `bdl_rate` (`remaining`, `used`, `total`, `remaining_ratio`; `quota_protected` removed). Code default `bdl_rate_limit_per_min` stays 5. `env.example` and compose set 600. Production must set `BALLDONTLIE_API_KEY` and `BDL_RATE_LIMIT_PER_MIN=600`. First start `SCAN`-deletes `daily_picks:nba*`, `odds_snapshot:*`, `events:nba:*`, `*:wnba:*`, and `odds:quota_usage:v1`, guarded by `SET NX` on `migrations:spo130i:odds_flush_done`. Event ids on live odds routes are decimal game ids. `001` / `002` / `005` were not altered. `docs/progress.md` was not edited. |
