# SPO-138 full-history NBA backfill

Planning only. Nothing in this file has run against RDS or AWS. Live BDL calls used for counts were read-only and are listed in §F. The key was never printed or written.

This plan **follows the data model** in [data-model.md](data-model.md). Table names, keys, and `snapshot_kind` values are defined there. 138a reuses the SPO-130 BDL provider / adapter once those PRs exist; it does not invent a second mapping.

Eason, via Lead, 2026-11-12 9:22 PM CT:

1. Backfill every data type to the earliest season BDL offers: games and stats from 1946-47, box scores as far as BDL has them (measured: **1946-11-01**). **Amended by Eason 2026-11-15: games, stats, and any box-score walk start at 2000-01** (data model §9). The rest of this item is unchanged: opening game odds from 2020-21 (measured: first hit **2020-12-23**; 2018–2020-01-15 empty), opening player props from 2024-25 (measured: 2024-11-20 has data; 2024-01-15 and 2023-03-01 empty), actual lineups from 2025-26 (docs, and a 2024 projected/lineup probe was empty).
2. Old Odds API history survives only in the pre-wipe RDS snapshot. No S3 export of that history.

Still no execution until 130 merges and Eason OKs the dry-run. The wipe itself is in the SPO-138 `plan.md`, which is not in this repo.

## A. RDS storage

See [data-model.md §5](data-model.md) for the full table, the measurement method (local PG 16, `pg_total_relation_size`, recorded samples + shipped CSV), and the instance (RDS `db.t4g.micro`, 1 GiB RAM, 20 GB gp3, autoscale 50 GB, from terraform defaults). The `#64` backend host is a `t4g.small` (2 GiB). The bound that will OOM the API is the container `mem_limit: 1g` (`deploy/docker-compose.prod.yml:65`), not the RDS RAM and not a claim that the API host is 1 GiB.

Recommended load (main-line props only, no box-score JSONB, stats in DB):

| Object | Size | Confidence |
|---|---|---|
| `player_game_stats` | **~354 MB** | 385.1 bytes/row **measured**; ~0.92M rows **estimated** (page-1 densities 24/game for 2000-01 and 33/game for 2025-26 **measured**, 26/game **assumed** between, × game counts) |
| `player_prop_snapshots` opening, main only | **416 MB** | 313.4 bytes/row **measured**; row counts **estimated** from sample densities × games (2025 game count **measured** at 1,322) |
| `games` | **~16 MB** | ~34,500 games: 2000=1,260, 2025=1,322, 2026=1,200 **measured**; other seasons **estimated** from published schedules + typical playoff volume; bytes/row **estimated** at 450 from a 107-row sample |
| `game_odds_snapshots` opening | **~10 MB** | coverage start **measured**; vendors/game **measured** on sample dates; totals **estimated** |
| `game_lineups` + dimensions + checkpoints | **~25 MB** | **estimated** |
| Subtotal | **~0.8 GB** | |
| With ~30% WAL / bloat | **~1.1 GB estimated** | |

**20 GB is enough.** The backfill does not require a storage increase. Leave `max_allocated_storage = 50` on. The risk that does matter is **container RAM** (QA measured 1,729 bytes/row in `_cache`; ~0.92M rows ≈ **1.6 GB** of Python dicts, which will OOM the 1g `mem_limit` — never load full history into that container; see data model §6) and **live-snapshot growth** (~1.2 GB/year estimated if all three daily ticks are kept at 2026 main-line density). Recommendation in the data model: persist opening and closing forever; TTL or downsample live. Runbook for the load itself: stop the backend during 138a, create indexes after the heap is loaded, watch autovacuum / `maintenance_work_mem` on the t4g.micro.

Do **not** also store:

- All alternate / milestone ladders (one 2026 final was 3,889 raw lines vs 816 main, **measured**). A dense 2026 season of alts is ~1.5 GB estimated. Eason already said to drop alts.
- A queryable `box_scores` JSONB table (~0.5 GB estimated from 2000 on, and a duplicate of `games` + `player_game_stats`).

## B. Request count and runtime (cap 500/min)

Pagination (docs + measured): cursor-based, `per_page` max **100**, no `total_count` in `meta` (measured on `/v1/games?seasons[]=2025&per_page=1`: keys are `next_cursor` / `per_page` only). A full page can still return `next_cursor` when the next page is empty (docs; measured on 2026 games, last page `n=0`). Walk `cursor=meta.next_cursor` with the same filters until `next_cursor` is absent or a page is empty. Do not reuse cursors across endpoints or seasons.

Live jobs need about 30 calls in the worst minute (130 plan §4). Cap the backfill at a **hard 500/min** that the Redis-observed GOAT limit (600) cannot raise, leaving 100/min for anything else. `BdlClient` settings default to **5/min**; the observed Redis value can overwrite a soft cap unless 138a hard-caps at 500. If the backend is stopped for the wipe+backfill, 500/min is still the cap we will code to (use a local in-process limiter in that case).

| Data type | Endpoint | Paging | Calls | Basis |
|---|---|---|---|---|
| Games | `GET /v1/games?seasons[]={year}&season_type=…&per_page=100` | cursor | **421 measured** | 27 seasons × 4 `season_type` walks (`regular`, `playoffs`, `playin`, `ist`), 34,650 games, walked 2026-11-17 |
| Stats | `GET /v1/stats?seasons[]={year}&per_page=100` | cursor | **8,871 measured** | 885,873 lines over 27 seasons, walked 2026-11-17 |
| Opening props | `GET /nba/v2/odds/player_props/opening?game_id=` | none (one body per game, `meta.per_page = n`, measured) | **~2,810** | 1,322 **measured** (2025) + ~1,320 **estimated** (2024) + ~170 final 2026 games **estimated** as of 2026-11-12 |
| Opening game odds | `GET /nba/v2/odds/opening?dates[]=` (or `game_ids[]`) | cursor, max 100. Unfiltered is 400 (**measured**) | **~200–400** | Batch dates after `games` is loaded; 6 seasons **estimated** |
| Actual lineups | `GET /nba/v1/lineups?game_ids=…&per_page=100` | `game_ids` required (docs); cursor if a batch exceeds 100 | **~600–1,500** | 2025-26 + 2026-27, batches of a few games so one page holds ~25–30 players each, **estimated** |
| Projected lineups (optional) | `GET /nba/v1/projected_lineups?seasons[]=` | cursor, max 100 | **~30** | If 2025-26 is still queryable; a recorded `seasons[]=2025` sample was empty |
| Players / teams | `/v1/players`, `/v1/teams` | cursor / one call | **~50 + 1** | optional dimensions, **estimated** |
| **Total (no box-score date walk)** |  |  | **~13,000–14,100** | games and stats measured (9,292), the rest estimated |
| Box scores *if* we walked them | `GET /v1/box_scores?date=` only (`date` required, **measured** 400 otherwise) | one call per game date | **~5,000 estimated** | ~27 seasons × ~185 game dates, estimated; skip in the recommended plan |

**Measured (2026-11-17 and 18).** The games and stats walk of 2000-01 to 2026-27 sent 9,292 requests: 794 in the trial run of 2000-01 and 2025-26, then 8,498 in 32 minutes for the other 25 seasons. The walker sends one request at a time, so latency sets the pace: about 263 a minute (0.23 s each), well under the 500 cap. No request got a 429. Re-walking 2014-15 to 2026-27 after the normalizer fixes took 4,702 requests and 18 minutes. Per-season verification adds under 2 s for all 27 seasons.

So the games and stats walk takes about **35 minutes**. The other endpoints add ~3,700–4,800 estimated calls, about 14–18 more minutes at the same pace, for about **50–55 minutes wall** in all. Running two walkers at once could approach the 500 cap, but one is fast enough. The optional box-score walk would add ~19 minutes. Stats are the long pole (8,871 calls, ~34 minutes).

Order: teams/players → games (this also produces the date and game-id lists) → stats → opening odds (by dates from `games`) → opening props (one call per final game, 2024+) → actual lineups (2025+) → optional projected lineups. Opening props can run in parallel with stats only if the shared limiter is respected (still 500/min combined).

Raw BDL bodies gzip to the existing data bucket under **`bdl-raw/`** (Lead, data model §9 Q2; IAM already allows that prefix) plus a short local cache. Do not invent a `raw/bdl/` prefix. If 90-day deletion is still intended, add a current-object expiration rule for `bdl-raw/` (`#64` `s3.tf` expires only `pg-dumps/`; a Glacier transition is not a delete).

### BdlClient methods 138a needs (QA S1)

Do **not** retarget the live methods `list_odds` / `get_player_props` (or any other in-season snapshot writer) for opening history. Add, or extend, these methods on `BdlClient`:

- `list_games` — accept `seasons[]`, `season_type`, `start_date` / `end_date`. Dates are no longer required (the current method forces a date and cannot walk a season). SPO-138a added `seasons=` and `season_type` (`regular`, `playoffs`, `playin`, `ist`; anything else raises before a request). The date range is not added: the walk goes by season.
- `list_stats` — `GET /v1/stats` with `seasons[]` (and optional date / player / game filters). SPO-138a added it with `seasons=`; rows go through `normalize_stat_row` (data model §1.6).
- `list_teams` — `GET /v1/teams`.
- An optional unfiltered `list_players` walk for the dimension backfill. The existing `list_players` still requires `ids` and stays as the live lookup.
- `list_opening_odds` — `GET /nba/v2/odds/opening` with `dates[]` or `game_ids[]` (unfiltered is 400). Separate from live `list_odds`.
- `get_opening_props` — `GET /nba/v2/odds/player_props/opening?game_id=` (required, unpaged). Separate from live `get_player_props`.
- `list_lineups` — `GET /nba/v1/lineups` with `game_ids` required.

Backfill uses its **own paging loop** and stops on an empty page or a missing `next_cursor`. Do not reuse `iter_pages` as-is: a full page can still return `next_cursor` when the next page is empty (measured on 2026 games).

## C. Resumable, idempotent checkpoints

Use `bdl_backfill_checkpoints` from [data-model.md §1.10](data-model.md). Key: `(league, data_type, season, shard_key)`. Store the BDL `next_cursor` (or the next date / game id) in `cursor`, plus `status`, `rows_written`, `pages_fetched`, `last_error`, `updated_at`.

Writer rules:

- **Upsert on the natural keys** in the data model. Every key column is `NOT NULL` (QA M1). Opening game odds conflict on `(league, bdl_game_id, book_key) WHERE snapshot_kind = 'opening'`; opening props conflict on `(league, bdl_game_id, bdl_player_id, book_key, market) WHERE snapshot_kind = 'opening'`. `snapshot_at` / `opened_at` is not in those conflict targets (QA S5). Live/closing ticks are out of 138a's write set. `player_game_stats` conflicts on `(league, bdl_game_id, bdl_player_id)` with `bdl_player_id NOT NULL` — no CSV shim, no null player id. A replay of a completed page does not duplicate rows. The design-time proof was a replay script outside the repo (every table stayed at n=1 after a second identical upsert; a changed `opened_at` still n=1; a null `bdl_player_id` was rejected). `backend/tests/test_migration_002_bdl_core.py` repeats the opening replays against the real migration.
- **Name the league on every insert.** No table has a `league` default (data model §1).
- **One row per key per statement.** A multi-row `INSERT … ON CONFLICT DO UPDATE` with two rows on the same key fails (`cannot affect row a second time`). Opening props pick the main line per (game, player, book, market) before the batch insert (data model §1.9).
- **`rows_written` is SET from `count(*)`** (or from `xmax = 0` inserts plus updates if we want “touched”), not incremented by page length. A replay would otherwise double the counter.
- **Resume:** if a season/shard is `in_progress`, the next run continues with the stored `cursor` and the same filters. If it is `done`, skip. Never start a season from page 1 unless `--restart-season` is passed.
- **Retry / backoff:** on 429 or 5xx, honor `Retry-After` and `x-ratelimit-reset` / `remaining`, cap the sleep (the existing `BdlClient` already pauses on 429; 138a should use that client, not a second HTTP stack). Record `last_error` without the key or the DSN. Do not advance the checkpoint cursor until the page has been upserted.
- **Dry-run:** `--dry-run` walks the same cursors (or uses already-cached pages) and prints would-be row counts by `(data_type, season)` without writing facts. It may write checkpoint rows with `status='dry_run'` or write nothing; pick one and keep it stable.
- **Per-season verification** (must pass before the season is marked `done`):
  - `games`: `count(*)` equals the number of rows fetched (sum of page lengths). Split by `season_type`. Compare 2000 / 2025 / 2026 to the measured 1,260 (1,189 regular + 71 playoff) / 1,322 (85 playoffs, 6 play-in, 1 Cup final measured; 1,230 regular by subtraction) / 1,200; other seasons to the schedule estimate, with a documented tolerance for IST / postponements.
  - `player_game_stats`: rows per game inside the measured band (24 for 2000-01, 33 for 2025-26, with a wide margin). Report per season the `dnp` count and the rejected-row count from `normalize_stat_row`. A season with any rejected rows is listed, not hidden.
  - Opening odds / props: list final games in range with zero rows. A high miss rate on 2024+ props is a fail; some early-season or cup games may be empty and should be listed, not hidden.
  - Lineups: 2025-26+ final games should have two teams and ~5 starters; pre-2025 must be zero.
- Safe to re-run the whole script. Cap rate at 500/min via the shared Redis limiter, even if the backend is stopped (use a local in-process limiter in that case).
- `--league nba` only. Do not write WNBA rows.

138a also records an opening-props fixture if 130d did not (already noted in `plan.md` §3, not in this repo).

## D. CSV vs DB

See [data-model.md §6](data-model.md) for the consumer list, the per-league source flag, and each reader's declared history scope.

**Recommendation: NBA games and stats go into Postgres (`games`, `player_game_stats`).** Keep `CSVPlayerHistoryService` as a facade so routes, daily analysis, defense ranks, and the agent/backtest tools do not each change.

The source flag is **per league, on the class** (`NBA_HISTORY_SOURCE=csv|db` for `league='nba'`; WNBA instances are always `csv`). Do not introduce a process-wide `HISTORY_SOURCE` — both singletons live in one process, and `_build_team_roster_cache` constructs a new service for each league. Each reader declares a scope: `current_season`, `last_n_seasons`, or `full`. An optional current-season hot cache (~20–30k rows, ~50 MB) may serve `current_season` NBA readers only. **Full history is queried from Postgres by player and season and is never loaded into the 1g container** (~0.92M rows ≈ 1.6 GB in `_cache`). Readers that need more than the current season — player-history, daily analysis / event reads early in the season, agent `historical.py`, walk-forward / backtest / calibration, the dataset sampler — get a SQL path, not a `_cache` walk. Retire the GitHub NBA downloader once the NBA facade reads Postgres (Q10). **WNBA stays on its CSV** (4,875 data rows, measured; 4,876 was `wc -l` including the header).

Why not “keep the CSV and also backfill DB” as the long-term state: two sources of truth, and a full-history CSV cannot be loaded in the 1g container. Why not “CSV only, just make it 2000–present”: same RAM problem, and no indexes for `get_player_stats` / defense ranks / backtests.

## E. New tables

All defined in [data-model.md §1](data-model.md), including natural keys and a `league` column on every table. 138a writes:

| Data type | Table | Notes |
|---|---|---|
| Teams / players / seasons | `teams`, `players`, `seasons` | Dimensions first |
| Games, 2000-01–present | `games` | Includes scheduled 2026-27 games (1,200 **measured** through 2027-03-30). Walk each season once per BDL `season_type` (`regular`, `playoffs`, `playin`, `ist`) and write the requested type translated to the product game type (data model §1.5, Q7); the `/v1/games` object does not carry it |
| Stats, 2000-01–present | `player_game_stats` | This is the box score at player grain. Rows go through `normalize_stat_row` (DNP, minutes, team; data model §1.6). `season` and `date` come from the row's nested `game`. Stats whose game is not in `games` are dropped and counted before the insert; the composite FK would otherwise fail the batch. With every game type stored (Q7, revised 2026-11-17), a dropped row is unexpected and is listed in the season's verification |
| Opening game odds, 2020-21–present | `game_odds_snapshots` `kind=opening` | |
| Opening props, 2024-25–present | `player_prop_snapshots` `kind=opening` | Main lines only. Map `prop_type` through `prop_markets` (data-model.md §1.9). Skip and count any type not in it |
| Actual lineups, 2025-26–present | `game_lineups` | |
| Projected lineups (optional) | `projected_lineups`, `projected_lineup_players` | May be current-season only. One version per BDL `updated_at`; a replay inserts nothing new. `first_seen_at` is the backfill time, so pregame reads never see these versions |
| Checkpoints | `bdl_backfill_checkpoints` | |

138a does not write `snapshot_kind=live` or `closing` (those are 130g / 130j from cutover onward) and does not invent historical injuries (BDL injuries have no history).

## F. Probe log (this document)

Read-only live calls for this plan, plus earlier depth probes already on disk. No Odds API calls. Calls this session: **55**, recorded at the time with rate-limit headers only (that log is not in this repo) (no Authorization, key leak check passed). Notable measured results:

- `/v1/games` meta has no total count; cursor pagination works; 1946=350, 2025=1,322, 2026=1,200 (2026 includes future scheduled games; last page empty with `prev_cursor`).
- `/nba/v2/odds/opening` without `dates` or `game_ids`: 400. 2018-11-14, 2019-11-15, 2020-01-15: 0 rows. 2020-12-23: 12 rows (BetMGM). Subsequent sample dates in 2021–2023 also hit.
- `/v1/box_scores` without `date`, or with `seasons[]`: 400. `date=1946-11-01`: 1 game, 11+11 players. Mid-era dates through 2005 also returned games.
- `/v1/stats?dates[]=1946-11-01`: 22 rows, matching the box player count. `min` can be `"0"` with non-zero points (same quality issue as the 1949 research sample).

The supporting size measurements are not in this repo; data model §5 has the results.

SPO-138a probes, 2026-11-15 and 2026-11-16 (read-only, key never printed, 25 calls). Recorded with `scripts/explore_bdl_backfill.py` into `backend/tests/fixtures/bdl/` unless noted:

- `/v1/stats?seasons[]=2000` and `seasons[]=2025`, page 1: 24 and 33 rows per complete game. DNP is `min: null` with null stats in 2000-01 and `min: "00"` with zeros in 2025-26. `plus_minus` is null on every 2000-01 row (data model §1.6).
- `/v1/games` and `/v1/stats` with `seasons[]=1900`: HTTP 200, `data: []`, and no `next_cursor` key in `meta`.
- `/v1/stats?seasons[]=abc`: HTTP 400, JSON body `{"errors":[{"param":"seasons[0]","error":"must be a valid integer (max 2147483647)"}]}`.
- `/v1/games?seasons[]=2000`, every page (not recorded as fixtures): 13 pages, 1,260 games (1,189 regular, 71 playoff), 29 teams, 2000-10-31 to 2001-06-15.
- `/nba/v2/odds/player_props/opening?game_id=` (not recorded as fixtures): game 15907438 (2024-10-22) 601 rows and game 18446819 (2025-10-21) 546 rows, the same 12 full-game prop types (data model §1.9 `prop_markets`). `opened_at` is tip-off minus 3 hours on every row of both games.

## G. Questions for Eason

The data-model questions in [data-model.md §8](data-model.md) and the decisions in §9 apply here. Q1–Q10 are answered (Q7/Q10 by Eason after the first pass; Q2 prefix confirmed by Lead as `bdl-raw/`). Remaining operational notes, not open product questions: add a `bdl-raw/` expiration rule if 90-day deletion is still intended; watch autovacuum during the load; do not ship a DROP migration until the §4 gate (two subsequent images that both migrate-before-uvicorn and do not run `SCHEMA_SQL`) has passed.

## H. Operational gates (Lead, 2026-11-12)

1. The wipe happens only after 130i is merged and deployed. Once the wipe starts, no backend runs NBA on The Odds API.
2. The backend stays stopped for the wipe and the whole backfill. The backfill caps itself at 500/min on the GOAT 600 key.
3. An expired cursor is handled with `--restart-season <season>`, which re-walks that season from page one using idempotent upserts. The checkpoint row is then reset to that season.
4. The `bdl-raw/` 90-day expiration rule ships in the #64 follow-up.
