# SPO-138 data model

Base: `origin/dev` `55750de`. The schema is [`backend/app/migrations/002_bdl_core.sql`](../../../backend/app/migrations/002_bdl_core.sql). This document records why each table has its shape, which readers use it, how big it gets, and what Eason decided. If this document and the migration disagree, the migration is what runs; fix this document. [backfill-plan.md](backfill-plan.md) follows from it. ER diagram: [data-model-er.drawio.svg](data-model-er.drawio.svg) (open it in draw.io to edit).

Eason, via Lead, 2026-11-12 9:22 PM CT: backfill every data type to the earliest season BDL offers; old Odds API history lives only in the pre-wipe RDS snapshot (no S3 export of that history). Amended by Eason 2026-11-15: games and stats start at 2000-01, not 1946-47 (§9). The other data types keep their start seasons, all later than 2000. Eason's SPO-130 decisions (SPO-130 plan §7, not in this repo): BetParx and Bally Bet count as one source; drop alt lines; add 130j pre-tip closing snapshots; no RotoWire fallback for NBA.

RDS from `infra/aws/rds.tf` + `variables.tf` + `terraform.tfvars.example` (defaults, not a live describe): `db.t4g.micro` (2 vCPU, 1 GB RAM), `allocated_storage = 20` GB gp3, `max_allocated_storage = 50`, PostgreSQL 16, db name `novig_nba`.

Row-size measurements were taken on a local PG 16.2 in a throwaway database, loading recorded BDL samples plus the shipped `data/nba_player_game_logs.csv` (28,820 rows). Bytes/row are `pg_total_relation_size / count(*)`, which includes indexes. Tables with only tens of rows are page-padded (8 KB); those figures are not used for extrapolation. The measurements predate the 2026-11-16 schema review, which removed copied name and abbreviation columns (§9.1), so the stats and props figures are upper bounds.

## 0. Candidates and synthesis

Two structurally different shapes were compared (architect: exhaust the design space, then pick one public surface).

**Candidate A — extend the six `SCHEMA_SQL` tables.** 130e adds `league`, `provider`, `provider_player_id`, `source_updated_at` to `odds_line_snapshots`. A later `snapshot_kind` column covers opening / live / closing. Games, stats, and injuries stay out of Postgres or arrive as one-off tables. `DatabaseService.init()` keeps running `CREATE TABLE IF NOT EXISTS` on boot. NBA game logs stay a CSV loaded into process memory.

**Candidate B — a normalized BDL-id core, with a new odds snapshot pair.** Teams, players, seasons, games, and `player_game_stats` are first-class. Player props and game odds live in their own snapshot tables with `snapshot_kind`. A `books` table carries `source_group` so BetParx and Bally Bet merge at read/vote time. Versioned SQL migrations replace boot-time `SCHEMA_SQL`. The CSV API facade stays; its NBA backend becomes SQL.

**Synthesis: B.** Stats from 2000-01 on (about 0.92 million rows, estimated, ≈ 1.6 GB in Python dicts) cannot be loaded into the backend container (`mem_limit: 1g` on the `#64` `t4g.small` host) the way today's 28,820-row CSV is. Game odds do not fit `odds_line_snapshots` (no player, different columns). 130e would add columns to a table this model then replaces. The public surface stays the existing services (`CSVPlayerHistoryService`, snapshot readers, lineup service) so routes do not each learn the new schema.

A rejected hybrid — one unified odds table for both game odds and player props — was dropped because the grains differ and the current readers only want player props. Two snapshot tables share `books`, `games`, and the `snapshot_kind` enum.

## 1. Core tables

Conventions, unless a table says otherwise:

- Every table has `league league_code NOT NULL`, with no default. `league_code` is a domain that allows only `'nba'` and `'wnba'`. BDL's NBA and WNBA ids overlap, so a writer that leaves `league` out must fail instead of landing on an NBA row. WNBA rows are allowed and stay empty until a later WNBA backfill. Unique keys always include `league`.
- Fact tables store ids, not names. Player names, team abbreviations, home/away, and starter flags are joined at read time (the `player_game_log` view, §1.6). A copied name goes stale when BDL corrects it, and a copied abbreviation is BDL's current one, not the one the team used that season.
- BDL integer ids are stored as given (`INTEGER` for teams/players, `BIGINT` for games, stats, and BDL odds/lineup ids that already exceed 2^31 in samples, e.g. opening-prop `id` `2260087586`).
- Surrogate `BIGSERIAL` primary keys are used only on log-style tables. Domain tables use natural primary keys so upserts are `ON CONFLICT` on that key.
- No foreign keys into the six legacy tables. FKs among the new tables are defined, but backfill should be able to disable them per session or load dimensions first (teams and players before games, games before facts).
- `snapshot_kind` is `TEXT` with a check: `'opening' | 'live' | 'closing'`. Closing rows come from the 130j pre-tip job, not from BDL (BDL does not store closing history).
- Deeplinks are not stored.
- **Unique-key idempotency (QA M1 / S5).** Every column that appears in a `PRIMARY KEY` or `UNIQUE` constraint or unique index is `NOT NULL`. PostgreSQL 16 treats `NULL = NULL` as unknown, so a unique key with a nullable column is not a conflict target (proved by QA on this box). RDS is PostgreSQL 16 (`engine_version` default `16.15` in `infra/aws/variables.tf`, family `postgres16`); `NULLS NOT DISTINCT` (PG15+) is available but is **not** used. Opening odds and props omit `snapshot_at` from the conflict target entirely (a changed or missing `opened_at` would still insert a second row if the timestamp were in the key, even when it is `NOT NULL`). Live and closing ticks use a separate partial unique index that includes `snapshot_at`, with a `CHECK` that `snapshot_at IS NOT NULL` unless `snapshot_kind = 'opening'`. The design-time proof was a replay script outside the repo. `backend/tests/test_migration_002_bdl_core.py` now checks the same thing against the real migration: a replayed opening prop or opening game-odds upsert leaves one row per natural key, including a replay whose `opened_at` changes or goes missing. There is **no CSV-import shim**: `player_game_stats.bdl_player_id` is `NOT NULL`. The BDL `/v1/stats` row always carries `player.id`. A shipped-CSV comparison is a verification step, not a load path; a name that cannot be resolved to a BDL player id is refused, not stored with a null id.

### 1.1 `books`

| Column | Type | Notes |
|---|---|---|
| league | TEXT NOT NULL | |
| book_key | TEXT NOT NULL | BDL `vendor` (`draftkings`, `betparx`, `ballybet`, …) |
| source_group | TEXT NOT NULL | Vote/consensus key. `betparx` and `ballybet` both use `parx_bally`. Every other book uses its own `book_key`. |
| display_name | TEXT NOT NULL | |
| active | BOOLEAN NOT NULL DEFAULT TRUE | |

- **PK / unique:** `(league, book_key)`
- **Natural key:** same
- **FK:** none
- Seed the allow-list from 130d (DraftKings, FanDuel, BetMGM, Caesars, BetRivers, Fanatics, BetParx, Bally Bet, Betway, Rebet). Store the vendor that actually posted; collapse to `source_group` before the main-line vote, keeping BetParx when both appear (130 plan §5 Q1 / Eason §7).

### 1.2 `seasons`

| Column | Type | Notes |
|---|---|---|
| league | TEXT NOT NULL | |
| season_start_year | INTEGER NOT NULL | BDL `season` (2025 = 2025-26) |
| label | TEXT NOT NULL | `2025-26` |
| start_date, end_date | DATE | Inclusive slate dates, nullable until known |

- **PK:** `(league, season_start_year)`

### 1.3 `teams`

| Column | Type | Notes |
|---|---|---|
| league | TEXT NOT NULL | |
| bdl_team_id | INTEGER NOT NULL | |
| abbreviation, name, full_name, city, conference, division | TEXT | As returned by BDL |

- **PK:** `(league, bdl_team_id)`
- Historical relocations may reuse a BDL id (a known 1949 quality issue found during the BDL evaluation). Store what BDL sends; do not invent a second id.

### 1.4 `players`

| Column | Type | Notes |
|---|---|---|
| league | TEXT NOT NULL | |
| bdl_player_id | INTEGER NOT NULL | |
| first_name, last_name | TEXT | |
| display_name | TEXT NOT NULL | `first_name || ' ' || last_name`, plus the alias file used by 130d |
| position | TEXT | |

- **PK:** `(league, bdl_player_id)`
- **Index:** `(league, display_name)` for the current name-based routes until they switch to player id
- `position` is the player's position today. The position in one game is `game_lineups.position` (2025-26 on).

### 1.5 `games`

| Column | Type | Notes |
|---|---|---|
| league | TEXT NOT NULL | |
| bdl_game_id | BIGINT NOT NULL | Becomes NBA `event_id` after 130i |
| season | INTEGER NOT NULL | |
| date | DATE NOT NULL | US slate date (`BDL.date`) |
| datetime_utc | TIMESTAMPTZ | |
| status, status_state | TEXT | Prefer `status_state` for lifecycle |
| postponed | BOOLEAN | |
| season_type | TEXT NOT NULL | `regular_season`, `playoffs`, `play_in`, or `cup_championship` (Eason Q7, revised 2026-11-17, §9), enforced by a CHECK. These are the `CANONICAL_GAME_TYPES` tokens (`app/services/game_log_hygiene.py`) the history readers already filter on. Not in the `/v1/games` object: the writer records the BDL `season_type` it asked for, translated `regular`→`regular_season`, `playoffs`→`playoffs`, `playin`→`play_in`, `ist`→`cup_championship`. BDL's own names fail the CHECK. Preseason is never fetched |
| home_team_id, visitor_team_id | INTEGER | |
| home_score, visitor_score | INTEGER | |
| home_q1..q4, home_ot1..ot3, visitor_* | INTEGER | Already on the `/v1/games` object |
| period | INTEGER | |
| ist_stage | TEXT | |

- **PK:** `(league, bdl_game_id)`
- **Unique:** `(league, bdl_game_id, season, date)`. Redundant as a key; it exists so `player_game_stats` can reference the game's season and date with a composite FK (§1.6).
- **FK:** `(league, season) → seasons`; `(league, home_team_id) → teams` and visitor (nullable until the team row exists)
- **Indexes:** `(league, date)`, `(league, season, date)`
- `season_type` is the only place a game's type is stored. There is no `postseason` column here or in `player_game_stats`: two columns for one fact can disagree. The flag could not stand in for the type anyway: BDL marks the 2019-20 bubble play-in `postseason=true` and the 2025-26 play-in `false` (recorded 2026-11-17).
- **Score after a fourth overtime** (full walk, 2026-11-19): the `/v1/games` object has `ot1`–`ot3` only. In the five four-overtime games of 2000-01 to 2026-27 (28012, 32587, 34714, 48851, 61851) the score is the tied score after the third overtime, and `period` is 4 on three of them. The player points in `player_game_stats` add to the final: 48851 stores 155–155, and its lines add to 168–161 (`games__game48851_record.json`, `stats__game48851_page1.json`). The rows are stored as sent. A team or game total for these games is the sum of the player points. `period` is not an overtime count in general either: it is above 4 on 1.5% of final games (504 of 33,659), while `home_ot1` is filled on 5.9%.

This table is the schedule and the box-score *header* (scores, quarters). It replaces the need to call `/v1/box_scores` just to get team totals.

### 1.6 `player_game_stats` (the box score at player grain)

| Column | Type | Notes |
|---|---|---|
| league | TEXT NOT NULL | |
| bdl_stat_id | BIGINT NOT NULL | BDL stats `id` |
| bdl_game_id | BIGINT NOT NULL | |
| bdl_player_id | INTEGER NOT NULL | Always a BDL player id. No CSV shim, no null id |
| bdl_team_id | INTEGER NOT NULL | The team that played this game (see Team below) |
| season, date | INTEGER / DATE NOT NULL | Copies of the game's, for the `(player, date)` and `(season, date)` reads. A composite FK keeps them equal to `games` |
| min_raw | TEXT | BDL `min` as sent: `"16"`, `"13:44"`, `"0"`, `"00"`, or null |
| seconds_played | INTEGER | Parsed from `min_raw` (`"13:44"` → 824, `"16"` → 960, `"28:60"` → 1740: the full 2000-01 walk has 19 rows with 60 seconds, every one a player who played). NULL when `dnp` |
| dnp | BOOLEAN NOT NULL | Did not play. See the DNP rule below |
| fgm, fga, fg3m, fg3a, ftm, fta, oreb, dreb, reb, ast, stl, blk, turnover, pf, pts, plus_minus | INTEGER | NULL on every `dnp` row |
| fg_pct, fg3_pct, ft_pct | NUMERIC(4,3) | 0–1 fraction as BDL sends it, rounded to 3 places. `CHECK` between 0 and 1. NULL when the player took no attempt of that kind (some seasons send 0 there), and on every `dnp` row |

The parser is `normalize_stat_row` in `backend/app/services/bdl_stats.py` (SPO-138a; percentages added 2026-11-16). Measurements below are page 1 of `/v1/stats?seasons[]=` for 2000 and 2025, recorded 2026-11-15 as `backend/tests/fixtures/bdl/stats__season2000_page1.json` and `stats__season2025_page1.json`.

- **DNP rule** (Eason, 2026-11-17): a row is `dnp` when nothing in it shows court time: no seconds (`min` null or zero), every box stat zero or null, and `plus_minus` zero or null. Every spelling becomes the same row: `dnp = true`, every stat NULL. The full 2000-01 to 2026-27 walk (2026-11-17) found these spellings:

  | Seasons | `min` | Stats | `plus_minus` |
  |---|---|---|---|
  | 2000-01 to 2021-22 | `null` (to 2018-19), `"0:00"` (from 2014-15), `""` (from 2018-19), `"0"`, `"00"` (2021-22) | null or zero | null |
  | 2022-23 to 2025-26 (until 2025-12-22) | `"00"` | zero | null |
  | 2025-26 from 2025-12-23 | `"00"` | zero | `0` (11,641 rows; both on `stats__season2025_cursor24626559_page.json`) |
  | 2025-26, added later | `null` | zero | `0` (21 rows, `stats__season2025_cursor43451886_page.json`) |
  | 2026-27 | `"0"` | zero | `0` (`stats__season2026_page1.json`) |

  Before this rule, a `plus_minus` of 0 counted as court time, and the 2025-26 rows from December were stored as played for 0 seconds. That made 30.5 players a game against 20 to 21.4 in every other season, while players with a minute or more stayed at 21.7. The cost of the rule: a player on court for a few seconds who recorded nothing and left with the score level is spelled the same way and reads as `dnp` (28 to 62 rows a season in 2019-20 to 2024-25). A nonzero `plus_minus`, or any stat with `"0"` minutes, is under a minute played. A row with no minutes (`null`) and any nonzero stat or `plus_minus` is refused.
- **Minutes spelling:** 2000-01 mixes `"MM"` (71 rows) and `"MM:SS"` (25 rows) on one page. 2025-26 page 1 is whole minutes only; 2026-27 page 1 is back to `"MM:SS"` (`"1:14"`). Any other spelling is rejected, not guessed.
- **Rejected rows:** a row with stats but no minutes, a missing field, or a value of the wrong type is skipped and counted in the run log. It is not stored.
- **Upstream gaps** (full walk, 2026-11-19): `verify_season` lists, without blocking, final games where a team's player points differ from its score or its minutes add to under 230. The walk lists 50. An audit of the raw pages with no app code in the path finds the same 50, every stored minute and point in them equals the raw value, and seven fetched again by game id (`explore_bdl_backfill.py --game-id`, saved as `stats__game<id>_page1.json`) return the same lines. The errors are in BDL's data:

  | Kind | Games | What is wrong | Example |
  |---|---|---|---|
  | Minutes field, 2005-06 and 2006-07 | 30 (10 + 20) | Points match the score. `min` is wrong: players with full stat lines show `"0"` or `"1"`, and one team's minutes add to anywhere from 54.8 to 254 | 19052: 37 points in `"0"` minutes |
  | Four overtimes | 5 | The score, not the lines (§1.5) | 48851 |
  | Line left out, 2018-19 | 1 | A team is 4 points and about 4 minutes short | 434 |
  | 2024-02-01 to 2024-03-08 | 14 | 6 points short only, 5 minutes short only (points match), 3 both | 1038319, 1038278, 1038379 |

  The rows are stored as sent and `seconds_played` is not corrected from another source. No quality column is added (Q8); the per-season list from `verify_season` is what a model that reads minutes or team totals masks.
- **Team:** `bdl_team_id` is the row's `team.id`, the team that played that game. The nested `player.team_id` is the player's team today. It differs from the game team on 57 of 100 rows of the 2000-01 page and is never read.
- **Season and date:** taken from the row's nested `game` object (`BdlStatLine` does not carry them). The FK `(league, bdl_game_id, season, date) → games` with `ON UPDATE CASCADE` rejects a copy that disagrees with `games` and carries a rescheduled date over to the stat lines.
- **Era gap:** `plus_minus` is null on all 100 rows of the 2000-01 page and filled on every played row of the 2025-26 page. It stays a nullable column. There is no era flag (Q8, §9).
- **Shooting percentages** (Eason, 2026-11-16, §9): stored as BDL sends them, with three corrections the full walk (2026-11-17) needed:
  - **No attempts is NULL.** Page 1 of 2000 and 2025 sent null for a shot type never taken, but 2014-15 to 2018-19, 2023-24, 2025-26, and 2026-27 send `0` there (every such row of 2015-16 to 2017-18). 0 of 0 is not 0%, so the parser stores NULL whenever the attempts are 0. No row in the walk has a percentage above 0 with no attempts.
  - **0–100 scale in the 2019-20 to 2021-22 play-in games.** These 13 games send `66.7` for 4 of 6. All 584 such values equal 100 × made / attempted rounded to a tenth, so a value over 1 is divided by 100. A single-game share under 1% is not possible, so a value over 1 cannot be a fraction. A value over 100, or below 0, is refused.
  - **DNP rows** send `0` for all three, and the DNP rule clears them with the other stats.

  2026-27 sends unrounded fractions (`0.4285714` for 3 of 7). The column keeps 3 places.
- **Multi-game rates:** a season or rolling percentage is `SUM(fgm) / NULLIF(SUM(fga), 0)`, never `AVG(fg_pct)`. Games of 1/14 (0.071) and 3/4 (0.750) average to 0.411, but the rate is 4/18 = 0.222. The stored percentage is for one game: display and per-game model features.
- **Storage:** no change to §5. QA's 385.1 bytes/row was measured on the earlier column list, which already had these three columns. A PG16 temp-table check on 2026-11-16 put them at 13.3 bytes/row, about 12 MB at 0.92M rows.

- **Natural / unique key:** `(league, bdl_game_id, bdl_player_id)`, all `NOT NULL`. `ON CONFLICT (league, bdl_game_id, bdl_player_id) DO UPDATE`.
- **FK:** `(league, bdl_game_id, season, date)` → games (composite, `ON UPDATE CASCADE`), players, teams
- **Indexes (justified in §2):**
  - `(league, bdl_player_id, date)` — `get_player_stats`, `/player-history`, agent historical tools. Name-based callers resolve the name once through `players (league, display_name)`
  - `(league, season, date)` — defense-rank rebuilds, season scans
  - `(league, bdl_team_id, date)` — teammates / `get_players_in_game`

**No separate `box_scores` table as a source of truth.** `/v1/box_scores` is date-required (measured: 400 without `date`, 400 with `seasons[]`), returns one game object with nested player arrays, and duplicates `games` + `player_game_stats`. A full-history JSONB copy would be about 1.1 GB estimated (see §5). If a raw payload is kept at all, it belongs in the raw-retention policy in §3, not in the queryable model.

**Reader view `player_game_log`.** The row today's CSV readers expect, built from ids: `player_game_stats` joined to `games`, `players`, `teams` (own team and opponent), and `game_lineups`. It adds `player_name`, `team_abbr`, `opponent_abbr`, `opponent_team_id`, `home_or_away`, `season_type`, `is_starter`, and `position`. Those columns used to be copies on `player_game_stats`; the 2026-11-16 review removed them (§9.1). A reader that counts the play-in or the Cup final with the regular season groups `season_type` in its query; the stored value keeps the real type (Q7).

- Abbreviations are BDL's current ones. BDL team 3 is `BKN` in 2000-01 too, when the team was the New Jersey Nets. Filter and group by team id, not abbreviation.
- `is_starter` and `position` come from `game_lineups` and are null for games without a lineup row (before 2025-26).
- The hot read `WHERE league = $1 AND bdl_player_id = $2 ORDER BY date DESC` uses `player_game_stats_player_date_idx` (checked with `EXPLAIN` on the local test database).

### 1.7 `injury_snapshots`

BDL `/v1/player_injuries` is a current roster, not a historical log (docs; no date filter). History exists only for snapshots we take from cutover onward. Redis `injuries:nba:latest` remains the hot cache.

| Column | Type | Notes |
|---|---|---|
| league | TEXT NOT NULL | |
| snapshot_at | TIMESTAMPTZ NOT NULL | Job time |
| bdl_player_id | INTEGER NOT NULL | |
| listed | BOOLEAN NOT NULL | `false` on the row that records the player leaving the list. No default |
| bdl_team_id | INTEGER | FK to `teams` |
| status | TEXT | BDL's word with unified spelling: Out, Doubtful, Questionable, Day-To-Day, Probable. Doubtful stays Doubtful. An unknown word is stored as sent (trimmed); blank is NULL (§11) |
| return_date | DATE | |
| description | TEXT | BDL `description`, same name as the API field |

- **PK:** `(league, snapshot_at, bdl_player_id)`
- **Index:** `(league, bdl_player_id, snapshot_at DESC)` for “latest as of”
- **Write rule (Eason Q5, §9):** a change-log. At each refresh, insert a row only when a player's `status`, `return_date`, or `description` changed. Keeping every 30-minute refresh would be millions of rows per year (~200 players × 48 refreshes/day).
- **Leaving the list (Eason, 2026-11-16):** BDL has no removal event. A player who recovers just drops off the list; the recorded rows carry only `player`, `status`, `return_date`, and `description`, and `meta` only the cursor. The writer compares each complete refresh with every player's last row and writes `listed = false` for a player who was listed and is now absent. Without that row, an as-of read keeps returning the player's last `Out`.
- **CHECK `injury_snapshots_removal_has_no_details`:** a `listed = false` row has no `status`, `return_date`, or `description`. Leaving the list is not BDL's `Available` (5 of 100 recorded rows), which is a player still on the list.
- **Only a complete refresh may write a removal.** A failed page, the page cap, or an error makes players vanish who did not recover. The comparison runs only where `refresh_nba_injuries` stores a snapshot, which already refuses a partial walk.
- **The comparison reads each player's last row from this table, not Redis.** `injuries:nba:latest` expires after 24 hours; after that every player would look new and no removal would be found.
- `snapshot_at` is the refresh time, not when the team announced the change. That is the time we knew it, so an as-of read cannot see a change early; it can see it up to one refresh (30 minutes) late.

### 1.8 Lineups

**`game_lineups`** — actual starters and bench from `/nba/v1/lineups`. Docs: available from the 2025-26 season, only once the game begins. `game_ids` is required (docs). `per_page` max 100 (one game fits one page; the recorded fixture used the default 25 and returned `next_cursor`).

| Column | Type | Notes |
|---|---|---|
| league | TEXT NOT NULL | |
| bdl_game_id | BIGINT NOT NULL | |
| bdl_player_id | INTEGER NOT NULL | |
| bdl_team_id | INTEGER | |
| starter | BOOLEAN NOT NULL | |
| position | TEXT | |

- **PK:** `(league, bdl_game_id, bdl_player_id)`. Its prefix serves the by-game read, so there is no separate index.
- **FK:** games, players, teams

**`projected_lineups`** and **`projected_lineup_players`** — pregame projections from `/nba/v1/projected_lineups`. Replaces NBA writes to `team_lineup_snapshots`.

| Table | Key | Other columns |
|---|---|---|
| `projected_lineups` | `(league, bdl_game_id, bdl_team_id, updated_at)` | `first_seen_at`, `status` (`expected` / `confirmed`) |
| `projected_lineup_players` | `(league, bdl_game_id, bdl_team_id, updated_at, bdl_player_id)` | `position` |

- **Every version is kept (Eason, 2026-11-16).** Projected lineups may be an input to the player-props ML model. A training row for a pick made at time T may see only versions with `first_seen_at <= T`, and takes the newest of them by `updated_at`. Keeping only the last projection would hand it a lineup published after T, a future leak.
- **The versions come from our own polling.** BDL returns only the current projection for each game and team and keeps no history. Each version here is one our job saw, so the history starts when 130h starts writing, and a projection BDL replaced between two polls is never stored.
- **`updated_at` is when BDL published a version; `first_seen_at` is when our job first stored it (Eason, 2026-11-16).** The gap is up to one poll. Reading by `updated_at` would let training see a version the product could not have seen yet. A replay keeps the first `first_seen_at` (`ON CONFLICT DO NOTHING`). A backfilled version gets the backfill time, so a pregame read never sees it.
- BDL projects only the five starters per team, with no bench, minutes, or inactive list (recorded sample below).
- Players are rows, not a JSONB array, so they carry FKs to `players` and to the version they belong to.
- Recorded sample: `backend/tests/fixtures/bdl/projected_lineups_21718080.json`.
- A `seasons[]=2025` probe during the BDL evaluation returned 0 rows (that sample is not in this repo); `seasons[]=2026` had data. Actual lineups, not projections, are what Eason asked to backfill for 2025-26. Projected history for 2025-26 may already be gone.

### 1.9 Odds snapshots

Supersedes `odds_line_snapshots`. 130e should not add columns to the old table; see §7.

**`game_odds_snapshots`** — spread, moneyline, total. Opening backfill from `/nba/v2/odds/opening` (coverage measured from 2020-12-23, i.e. 2020-21, matching Eason's start). Live/close from 130g/130j once those jobs also capture game odds (today they do not; §9 Q6 adds them to 130j).

| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PRIMARY KEY | Row id; this is a log-style table (§1 conventions). Upserts use the partial unique indexes below, not `id` |
| league | TEXT NOT NULL | |
| snapshot_kind | TEXT NOT NULL | opening / live / closing |
| bdl_game_id | BIGINT NOT NULL | |
| book_key | TEXT NOT NULL | |
| snapshot_at | TIMESTAMPTZ | Attribute, not part of the opening key. Opening: BDL `opened_at` (nullable if missing). Live/close: job time, required by CHECK |
| source_updated_at | TIMESTAMPTZ | BDL `updated_at` |
| spread_home_value, spread_home_odds, spread_away_value, spread_away_odds | NUMERIC / INTEGER | |
| moneyline_home_odds, moneyline_away_odds | INTEGER | |
| total_value, total_over_odds, total_under_odds | NUMERIC / INTEGER | |

- **CHECK:** `snapshot_kind IN ('opening','live','closing')` and `(snapshot_kind = 'opening' OR snapshot_at IS NOT NULL)`.
- **Opening unique (partial index `game_odds_snapshots_opening_key`):** `(league, bdl_game_id, book_key) WHERE snapshot_kind = 'opening'`. All three columns `NOT NULL`. `ON CONFLICT (league, bdl_game_id, book_key) WHERE snapshot_kind = 'opening' DO UPDATE`. A missing or later-changed `opened_at` updates the same row.
- **Live/closing unique (partial index `game_odds_snapshots_tick_key`):** `(league, snapshot_kind, bdl_game_id, book_key, snapshot_at) WHERE snapshot_kind IN ('live','closing')`. All five columns `NOT NULL` for those rows.
- **Index:** `(league, bdl_game_id, snapshot_kind, snapshot_at)`
- **FK:** games, books
- `source_group` is read from `books`, and `date` / `season` from `games`, at query time. Copies here would need a rewrite whenever a book changes group or a game is rescheduled.
- `dates[]` or `game_ids[]` is required (measured 400: `"At least one of dates or game_ids is required"`). Max 100 per page.

**`prop_markets`** — reference table of the player-prop markets Sports Lab stores. `002_bdl_core.sql` creates and seeds it. One row per market. Eason decided the set on 2026-11-16 (§9).

| Column | Type | Notes |
|---|---|---|
| league | league_code NOT NULL | |
| market | TEXT NOT NULL | App market key. This is the value in `player_prop_snapshots.market` |
| bdl_prop_type | TEXT NOT NULL | The BDL `prop_type` that maps to this market |
| stat_columns | TEXT[] NOT NULL | `player_game_stats` columns the result is read from |
| settle_rule | TEXT NOT NULL | `sum`: over/under the line on the sum of `stat_columns`. `double_digits`: yes when at least `min_double_digits` of `stat_columns` are 10 or more |
| min_double_digits | SMALLINT | 2 for double-double, 3 for triple-double, NULL for `sum` |

- **PK:** `(league, market)`. **Unique:** `(league, bdl_prop_type)`. WNBA can carry its own set.
- **CHECK:** `settle_rule IN ('sum','double_digits')` and `(settle_rule = 'sum') = (min_double_digits IS NULL)`.
- **Seed rows (12):**

| market | bdl_prop_type | stat_columns | settle_rule |
|---|---|---|---|
| `player_points` | `points` | `{pts}` | sum |
| `player_rebounds` | `rebounds` | `{reb}` | sum |
| `player_assists` | `assists` | `{ast}` | sum |
| `player_threes` | `threes` | `{fg3m}` | sum |
| `player_steals` | `steals` | `{stl}` | sum |
| `player_blocks` | `blocks` | `{blk}` | sum |
| `player_points_rebounds` | `points_rebounds` | `{pts,reb}` | sum |
| `player_points_assists` | `points_assists` | `{pts,ast}` | sum |
| `player_rebounds_assists` | `rebounds_assists` | `{reb,ast}` | sum |
| `player_points_rebounds_assists` | `points_rebounds_assists` | `{pts,reb,ast}` | sum |
| `player_double_double` | `double_double` | `{pts,reb,ast,stl,blk}` | double_digits, 2 |
| `player_triple_double` | `triple_double` | `{pts,reb,ast,stl,blk}` | double_digits, 3 |

- **Evidence:** all 12 appear in the recorded live props (`props_live_21718080_OKC@POR_pregame.json`). Opening props probed 2026-11-15 return exactly these 12 and no other type: game 15907438 (2024-10-22) 601 rows, game 18446819 (2025-10-21) 546 rows.
- **Not stored:**
  - `player_frees_made` (FTM) and `player_field_goals` (FGM). BDL has no prop type for either, and the Odds API inventory for both is empty (`backend/app/services/daily_analysis.py:136-140`). The product still lists them (`frontend/components/MarketSelect.tsx`, `odds_snapshot_service.py`, `daily_analysis.py`, `odds_history.py`). Removing them there is a separate ticket.
  - `points_1q`, `rebounds_1q`, `assists_1q`, `points_first3min`, `rebounds_first3min`, `assists_first3min`. These are live only and absent from both opening probes. `player_game_stats` is full-game, so a result cannot be settled.
- **Settlement:** when the player did not play (no minutes and no stat line), the prop is void and gets no result. It is not an under.

**`player_prop_snapshots`** — the table current `odds_line_snapshots` readers move to.

| Column | Type | Notes |
|---|---|---|
| id | BIGSERIAL PRIMARY KEY | Row id; this is a log-style table (§1 conventions). Upserts use the partial unique indexes below, not `id` |
| league | TEXT NOT NULL | |
| snapshot_kind | TEXT NOT NULL | opening / live / closing |
| bdl_game_id | BIGINT NOT NULL | Replaces `event_id` |
| bdl_player_id | INTEGER NOT NULL | Replaces 130e's `provider_player_id`. No props without a player id |
| book_key | TEXT NOT NULL | |
| market | TEXT NOT NULL | FK to `prop_markets`. Mapped from BDL `prop_type` through `prop_markets` |
| market_type | TEXT NOT NULL | `over_under` / `milestone` |
| line | NUMERIC NOT NULL | Main line only (Eason: drop alts) |
| over_odds, under_odds | INTEGER | Both set when `market_type = 'over_under'`, else null |
| milestone_odds | INTEGER | Set only when `market_type = 'milestone'` (DD / TD, Yes-only) |
| snapshot_at | TIMESTAMPTZ | Attribute for opening (`opened_at`, nullable if missing). Required for live/close (job time) by CHECK |
| source_updated_at | TIMESTAMPTZ | BDL `updated_at` |

- **CHECK:** `snapshot_kind IN ('opening','live','closing')` and `(snapshot_kind = 'opening' OR snapshot_at IS NOT NULL)`.
- **CHECK `player_prop_snapshots_odds_fit_market_type`:** an `over_under` row has both `over_odds` and `under_odds` and no `milestone_odds`; a `milestone` row has only `milestone_odds`.
- **Opening unique (partial index `player_prop_snapshots_opening_key`):** `(league, bdl_game_id, bdl_player_id, book_key, market) WHERE snapshot_kind = 'opening'`. All five columns `NOT NULL`. `snapshot_at` is not in the conflict target (QA S5: a changed `opened_at` on retry must not insert a second opening line).
- **Live/closing unique (partial index `player_prop_snapshots_tick_key`):** `(league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, snapshot_at) WHERE snapshot_kind IN ('live','closing')`.
- **One line per key.** `line` is in neither key: one main line per player, book, and market at each snapshot. BDL sends a whole ladder at one time (17 rows for one DraftKings rebounds market in the recorded live props), and some books post two over/under lines for the same market (BetParx had 10.5 and 2.5 in the same sample). The writer picks the main line before the insert. Under these keys a second line replaces the first, so a writer that skips the pick keeps whichever line came last. Two rows with the same key in one multi-row `INSERT … ON CONFLICT DO UPDATE` fail with `ON CONFLICT DO UPDATE command cannot affect row a second time`.
- **Indexes:**
  - `(league, bdl_game_id, snapshot_kind, snapshot_at DESC)` — “latest live (or close) snapshot for this event” (`bulk_props`, `event_reads`)
  - `(league, bdl_player_id, market)` — `GET /api/nba/odds-history` and eval open/close, after the name is resolved to an id and the date to game ids through `games (league, date)`
- Opening props: `game_id` is required; the response is not paged (`meta.per_page` equals the row count, measured up to 3,889 on one 2026 final). Docs say coverage is “the most recently completed season and ongoing seasons”; recorded samples and live probes show 2024-25 (season 2024) is populated and 2023-24 is empty, which matches Eason's start.
- **FK:** games, players, books, `(league, market)` → `prop_markets`.
- **Not stored:** `player_name`, `source_group`, `date`, `season` (joined from `players`, `books`, `games`); `provider` (every row carries BDL game and player ids, so BDL is the only possible source); `vig` and fair probabilities (computed at read time from the two prices with `backend/app/services/prob.py`, so a change to the no-vig method does not leave old rows wrong). `bulk_props` passes stored vig through today and has to compute it when it moves to this table.
- **Ingest filter:** the writer maps `prop_type` through `prop_markets` before the insert. A row whose `prop_type` has no `prop_markets` row is skipped, counted in the run log, and never inserted. A new BDL prop type therefore cannot fail a page with an FK error. Adding one is a seed row in a later migration.
- **Opening time (measured 2026-11-15, two games):** every row of both probed openers has `opened_at` equal to tip-off minus 3 hours (20:30Z for a 23:30Z tip). BDL's “opening” is its first capture, not necessarily the book's first post.

### 1.10 Operational tables (new)

**`bdl_backfill_checkpoints`** — see [backfill-plan.md](backfill-plan.md) §C.

| Column | Type | Notes |
|---|---|---|
| league | league_code NOT NULL | Every table carries `league` (§1 conventions) |
| data_type | TEXT NOT NULL | `games`, `stats`, `opening_odds`, `opening_props`, `lineups`, `projected_lineups`, `players`, `teams` |
| season | INTEGER NOT NULL DEFAULT 0 | 0 when the work is not seasonal |
| shard_key | TEXT NOT NULL DEFAULT '' | Date or game-id batch |
| cursor | TEXT | BDL `next_cursor`, or the next date / game id |
| status | TEXT NOT NULL | `in_progress`, `done`, `error` |
| rows_written | BIGINT NOT NULL DEFAULT 0 | |
| pages_fetched | INTEGER NOT NULL DEFAULT 0 | |
| last_error | TEXT | No URLs with keys, no DSNs |
| updated_at | TIMESTAMPTZ NOT NULL DEFAULT now() | |

- **PK:** `(league, data_type, season, shard_key)`

**`schema_migrations`** — `(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ)`. Used by the runner in §4.

Job logs (`odds_snapshot_logs`, `lineup_fetch_logs`) can stay as they are, with `league` already present.

### 1.11 Legacy six tables

Created today by `SCHEMA_SQL` in `backend/app/services/db.py:39-364`. They stay until the writers and readers in §2 have moved, and until the SPO-138 wipe has run.

| Legacy table | Fate |
|---|---|
| `odds_line_snapshots` | Superseded by `player_prop_snapshots`. Do not add 130e columns. Drop after 130i + 138 wipe + reader cutover. |
| `odds_snapshot_logs` | Keep (job log). |
| `team_lineup_snapshots` | Superseded by `projected_lineups` for NBA. Drop after 130h writes to the new table and 138 wipe. |
| `lineup_fetch_logs` | Keep. |
| `player_projections`, `projection_fetch_logs` | Already 100% legacy. Drop with the planned `--drop-legacy` / `SCHEMA_SQL` removal, not as part of the new model. |

## 2. Read paths and indexes

Every current (non-test) reader, mapped to the new tables. Frontend calls are listed through the backend route they hit. WNBA CSV routes stay on the WNBA CSV and are included only so the list is complete.

**History scope** (Lead): every reader declares one of `current_season`, `last_n_seasons`, or `full`. NBA full history is queried from Postgres **by player and season** (or by a bounded date window). It is never loaded into the backend container (`mem_limit: 1g` at `#64` `deploy/docker-compose.prod.yml:65`). QA measured the current in-memory `_cache` at 1,729 bytes/row; ~0.92 million rows (2000-01 on, estimated) would be about **1.6 GB** of Python dicts. A current-season-only `_cache` (~20–30k rows, ~50 MB) may exist as a hot cache for `current_season` readers only. It is not the API for `last_n_seasons` or `full` readers. See §6.

Several production callers walk `CSVPlayerHistoryService._cache` or call `latest_position` / `latest_team` rather than `get_player_stats`. Those are listed explicitly.

Fact tables are keyed by BDL id and carry no player names (§9.1). A name-based reader resolves the name to `bdl_player_id` once through `players (league, display_name)`, then uses the id indexes below. Readers that want today's CSV row shape read the `player_game_log` view (§1.6).

| Current path | File:line | Today reads | Scope | New table(s) / access | Index used |
|---|---|---|---|---|---|
| `GET /api/nba/events`, `GET /api/nba/events/{id}` | `backend/app/api/nba.py:363`, `:574` | Odds API / (after 130f) BDL `/v1/games`, not Postgres | current_season (slate) | `games` (optional cache of the slate; live path can keep calling BDL with a Redis TTL) | `(league, date)` |
| `GET /api/nba/events/{id}/props` | `nba.py:682` → `bulk_props.py:66-73, 803` | Latest `odds_line_snapshots` for `event_id` | current_season | `player_prop_snapshots` where `snapshot_kind IN ('live','closing')`, `MAX(snapshot_at)` per game | `(league, bdl_game_id, snapshot_kind, snapshot_at)` |
| same, team/position enrichment | `bulk_props.py:646-667, 653`; `latest_position` | `load_csv`, `team_on_event`, `latest_position` | current_season (or previous, early season) | SQL `player_game_stats` / `players` via facade methods, not `_cache` | `(league, bdl_player_id, date)` |
| `GET /api/nba/events/{id}/reads` | `nba.py:773` → `event_reads.py:86-93, 260-264, 326, 476` | Latest snapshot + `get_player_stats` + `latest_position` / `latest_team` + defense ranks + Redis injuries | last_n_seasons (history n, usually current + previous) | `player_prop_snapshots` + SQL `get_player_stats` / `latest_*` on `player_game_stats`; `injury_snapshots` if Redis is empty | same as props + `(league, bdl_player_id, date)` + `(league, bdl_player_id, snapshot_at DESC)` |
| `POST /api/nba/props/no-vig`, `GET /api/nba/players/suggest` | `nba.py:829`, `:1037` / `:1099` | Live odds gateway; suggest also `latest_position` | current_season | Live BDL + SQL `latest_position` | `(league, display_name)` / `(league, bdl_player_id, date)` |
| `GET /api/nba/odds-history` | `odds_history.py:63-67, 108, 177` | `odds_line_snapshots` by `player_name, market, date` | current_season (one date) | `player_prop_snapshots` (all kinds for that date): name → id through `players`, date → game ids through `games` | `(league, display_name)`, `(league, date)`, `(league, bdl_player_id, market)` |
| `POST /api/nba/odds-history/snapshot` | `odds_history.py:267` | Writer into `odds_line_snapshots` | n/a (writer) | `player_prop_snapshots` `kind=live` (and game odds if in scope) | unique key |
| Odds snapshot jobs 16:05/22:05/23:35 UTC; 130j pre-tip close | `odds_snapshot_service.py:125-268`; `scheduler.py:230-253` | Writer | n/a (writer) | `player_prop_snapshots` `live` / `closing` | unique key |
| `GET /api/nba/daily-picks` and daily analysis job | `daily_analysis.py:1247, 1280, 1290-1292`; `scheduler.py` | `get_player_stats`, `team_on_event`, `latest_position` / `latest_team`, defense ranks, live odds | last_n_seasons (early-season last-10 can cross a season) | SQL via facade, never a current-season-only `_cache` as the only source | `(league, bdl_player_id, date)`, `(league, season, date)` |
| `GET /api/nba/csv/players` | `nba.py:1115, 1139` | `get_all_players` | current_season | `SELECT DISTINCT display_name` from `players` joined to current-season `player_game_stats` | `(league, display_name)` / `(league, season, date)` |
| `POST /api/nba/csv/reload` | `nba.py:1161` | `csv_player_service.reload()` | n/a | No-op or cache bust of the current-season hot cache once NBA reads SQL | — |
| `GET /api/nba/player-history` | `nba.py:1194, 1336` | `get_player_stats` | last_n_seasons (or `full` when `n=0` / no season bound) | SQL `get_player_stats` by player/date, limit N; **not** `_cache` | `(league, bdl_player_id, date)` |
| `GET /api/nba/player-dd-history` | `nba.py:1434, 1472` | `player_dd_history` | last_n_seasons or full for a named season | SQL on `player_game_stats` (pts/reb/ast) | same |
| `GET /api/health` | `health.py:34-60` | `{ok, service, time}` only. **Does not read the CSV.** This is the `#64` `remote-up.sh` and compose healthcheck | n/a | Unchanged | — |
| `POST /api/trigger-csv-download` | `health.py:103` | `csv_downloader_service.get_last_modified()` | n/a | After the NBA downloader is retired: last successful NBA stats incremental job time | checkpoint `updated_at` |
| `GET /api/scheduler-status` | `health.py:139` | `csv_last_modified` from the downloader | n/a | Same new field as the trigger route | checkpoint `updated_at` |
| NBA CSV download job | `scheduler.py:609, 619, 759` | GitHub CSV → memory cache | n/a (writer) | Replaced by an incremental BDL stats job writing `player_game_stats` (Q10) | checkpoint |
| Defense ranks | `defense_ranks.py:207-217` walks `csv_player_service._cache.values()`; callers `event_reads.py:270`, `daily_analysis.py:50` | Full in-memory CSV walk | current_season | **SQL** `SELECT` from `player_game_stats` for one `season` (or a materialized defense table rebuilt daily). Must not walk `_cache` | `(league, season, date)` |
| NBA lineups API and jobs | `api/lineups.py:31, 53, 69`; `lineup_service.py:449, 485-489` | Redis → scrape → `team_lineup_snapshots` | current_season | After 130h: `projected_lineups`; actuals: `game_lineups` | `(league, bdl_game_id)` |
| Lineup roster helper | `lineup_source_support.py:299-311` constructs a new `CSVPlayerHistoryService(league=…)` and walks `_cache` for **both** leagues | `team_from_game_logs` over `_cache` | current_season | **NBA:** SQL roster for the current season (`player_game_stats` / `game_lineups`). **WNBA:** keep walking the WNBA CSV `_cache` (4,875 rows). The class honors a per-league source, so a new instance with `league='wnba'` never looks at Postgres | `(league, bdl_team_id, date)` |
| NBA injuries refresh + startup fill | `scheduler.py:351-498`; `nba_injuries.py` | BDL → Redis `injuries:nba:latest` | current_season | Same Redis cache, plus a change-log row in `injury_snapshots` (Q5) | unique key |
| Agent historical tools (`get_base_stats`, splits, trends, `_games_for`, `_team_for`, …) | `scripts/agents/tools/historical.py:151, 183` and the `get_*` tools from `:261` | `csv._cache.get(resolved, [])` — **not** `get_player_stats` | last_n_seasons or **full** (career / n=0) | Public methods that **SELECT by player (and optional season/date)** from `player_game_stats`. Keep the tool signatures. Do **not** fill `_cache` with 2000–present. These scripts should open their own DB connection when run outside the API process; if they ever run inside the 1g container they still query per player, never `SELECT *` | `(league, display_name)` → `(league, bdl_player_id, date)` |
| Agent market tool | `scripts/agents/tools/market.py:4, 483` | Live odds + note pointing at `odds_line_snapshots` | current_season / one date | `player_prop_snapshots` | event + history indexes |
| Walk-forward, backtest, calibration guard | `walk_forward.py:340, 600, 917`; `backtest.py:234`; `calibration_guard.py:225` — they **read or replace `service._cache`**; also `get_player_stats` at `walk_forward.py:351, 909`, `backtest.py:73, 255, 295`, `calibration_guard.py:27, 181`, `report.py:220, 480` | `_cache` + `get_player_stats` | **full** (the season window of the harness, often many seasons) | Script-side SQL (or a copy of the facade pointed at Postgres) fetching **by player and season** for the window under test. Must not assume `_cache` holds the window, and must not load 1.8M rows into the 1g API container | `(league, bdl_player_id, date)`, `(league, season, date)` |
| Eval odds open/close | `scripts/agents/evaluation/odds_history.py:8, 320, 422` | `odds_line_snapshots`-shaped rows | last_n_seasons or full for the eval window | `player_prop_snapshots` `opening` + `closing`, queried by player id and market | `(league, bdl_player_id, market)` |
| Dataset sampler | `scripts/dataset/01_sample_contexts.py:28, 56, 248-289` | CSV service | last_n_seasons or full (sampler window) | SQL by player/season, not a full `_cache` load | `(league, bdl_player_id, date)` |
| Hygiene script | `scripts/hygiene_game_logs.py:35` | Rewrites the CSV in place | n/a | One-time; then hygiene rules live in the stats loader (Q7: the four product game types, no preseason) | — |
| Board-shift measurer | `scripts/measure_spo121_board_shift.py:9` | Shipped CSV through the analysis path | last_n_seasons (the measured window) | Same SQL facade / analysis path | `(league, bdl_player_id, date)` |
| Data-logger catalog | `scripts/agents/data_logger.py:18, 84-90, 120` | Documents CSV + injuries Redis + snapshots | n/a | Update the catalog when the facade switches | — |
| Frontend player history / DD / CSV players | `frontend/lib/api.ts:275-411` | The NBA CSV routes above | inherits the route scope | Unchanged API | — |
| Frontend event props / reads | `frontend/lib/api.ts:879, 891` | The snapshot routes above | current_season | Unchanged API | — |
| Frontend daily picks, lineups, events, no-vig, suggest | `frontend/lib/api.ts:144-244, 614, 811-862` | Existing routes | current_season / last_n | Unchanged API | — |
| `GET /api/wnba/csv/players`, `/player-history`, `/player-dd-history`, daily picks, lineups | `backend/app/api/wnba.py:126, 203, 290` | `wnba_csv_player_service` / Odds API / scrapes | full WNBA CSV (4,875 rows, measured) | **Unchanged.** WNBA source is always CSV in the same process | — |

`db.py:20, 491, 515` are examples in the module docstring / helpers, not production routes.

## 3. Raw JSON retention

This is about BDL responses we fetch during backfill and live jobs, not the pre-wipe Odds API history. Eason already decided that old odds history stays only in the RDS snapshot, with no S3 export of that history. Lead later decided (see §9 Q2) that **new** BDL raw bodies do go to the existing data bucket under **`bdl-raw/`**, plus a short local cache.

| Option | Size (opening props alone) | Ops | Recommendation |
|---|---|---|---|
| JSONB in RDS, all backfill payloads | 2026 one-game sample `props_opening_21718074_final.json` is 1.37 MB measured. ~2,810 opening-prop calls (estimated) at a mix of 56–1,370 KB would land around 0.5–1.5 GB estimated, on top of the relational copy | Eats the 20 GB instance; duplicates `player_prop_snapshots` | **No** |
| S3 prefix `bdl-raw/` on the existing data bucket | Same bytes, already in the `#64` IAM allow-list | `s3:PutObject` is already granted on `bdl-raw/` (`infra/aws/locals.tf:5`, `iam.tf:21-24`, same on `origin/dev` and `refs/remotes/pr64`). `#64` `s3.tf:41-90` transitions objects >128 KB to Standard-IA at 30 days and Glacier at 90 days, but **only `pg-dumps/` expires**. A current-object expiration rule for `bdl-raw/` still has to be added if 90-day deletion is the intent (Glacier transition is not a delete) | **Yes**, Lead §9 Q2. Gzip bodies. Keep the bucket name and account id out of committed code; read them from settings/SSM |
| Short local cache during the run | Temporary disk on the box running 138a | Enough to retry a page without a second S3 or BDL round-trip | **Yes**, alongside S3 |
| Prefix `raw/bdl/` | — | Not in the IAM allow-list; a put would be denied | **No.** Lead chose the existing `bdl-raw/` prefix |

Do not store `deeplinks` anywhere. Do not write API keys or DSNs into cache file names or logs.

## 4. Migration approach

There is no Alembic (or any migration runner) on `origin/dev`. Schema changes today are `SCHEMA_SQL` executed by `db_service.init()` on every backend boot (`backend/app/services/db.py:401-413`, called from `backend/app/main.py:72`).

`#64` does **not** run migrations before uvicorn today. At `refs/remotes/pr64` (current tip `0b2b7b7`, which contains the QA review head `4dae092`):

- `deploy/docker-compose.prod.yml:56-64` — `command: [uvicorn, app.main:app, …]`. No migrate service, no entrypoint wrapper. `mem_limit: 1g` is at `:65`. Healthcheck hits `GET /api/health` (`:71-76`, `start_period` 40s).
- `deploy/remote-up.sh:48-49` only runs `docker compose pull` and `docker compose up -d --remove-orphans`, then curls `/api/health` (`:55-57`) up to 30×2s. It never runs a migration command. **Do not rely on `remote-up.sh` to migrate.**
- `backend/Dockerfile:72` — `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`.
- Re-running `SCHEMA_SQL` after a `DROP TABLE` recreates an **empty** `odds_line_snapshots` (QA proved this; the wipe script already documents the same hole for `--drop-legacy`). The default wipe stays `TRUNCATE`.

**Recommendation: numbered SQL files plus a small runner, not Alembic.** The app has no SQLAlchemy models; every query is raw SQL. A runner that applies `backend/app/migrations/00N_*.sql` in order and records versions in `schema_migrations` matches how the schema is actually written.

Suggested versions:

1. **`001_baseline.sql`** — the **end state** of today's `SCHEMA_SQL`, including the SPO-35 `ALTER`s that add `league` and replace `UNIQUE(date, team)` on `team_lineup_snapshots` (`db.py:235-286`) and the SPO-117 unique-key `DO` block. A squash of only the original `CREATE TABLE` blocks would leave a blank RDS (CI, a new instance) without those constraints. On an existing six-table DB the runner **stamps** `001` without re-applying. On a blank database it applies `001`.
2. **`002_bdl_core.sql`** — the new tables and indexes in §1, all additive, one transaction (or every statement `IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`) so a mid-run container restart is retry-safe. Compose `restart: unless-stopped` will rerun the entrypoint; if `002` is not retry-safe the container loops and `/api/health` never becomes ready. No drop, no rewrite of the six tables.
3. Later, after 130 writers/readers and the 138 wipe, and only after the DROP gate below: **`00N_drop_legacy_snapshots.sql`** drops `odds_line_snapshots` and `team_lineup_snapshots` (and the two SportsDataIO tables if that has not already happened).

**Same image, same PR (must-fix M2).** The first foundation deploy must ship, in **one** image and **one** PR, both of:

1. Migrate-before-uvicorn: change `deploy/docker-compose.prod.yml` `command` (and `backend/Dockerfile` `CMD`) to `python -m app.migrations upgrade && uvicorn app.main:app …` (keep the existing `--proxy-headers` / `--forwarded-allow-ips` flags). A thin entrypoint script in the image is fine; a separate compose `migrate` service is not required.
2. Stop executing `SCHEMA_SQL` in `db_service.init()` (`backend/app/services/db.py`). `init()` only creates the pool and confirms `schema_migrations` is at head. `backend/app/main.py:72` can keep calling `init()`.

Those two changes cannot land in different deploys. `deploy/remote-up.sh` does not need a new migration step if the compose `command` already runs `upgrade && uvicorn`; a comment in `remote-up.sh` should say so, so a later editor does not assume the script migrates. `DATABASE_REQUIRED=true` already fails boot if Postgres is down.

The runner never prints the DSN (reuse `mask_database_url` / redact helpers). CI: start PG, run the runner from zero and from a stamped-001 fixture that looks like today's end-state schema, then run the suite.

**DROP gate.** Do not ship `00N` (and do not run `wipe_league_data.py --drop-legacy`) until **every image we might roll back to** has also stopped running `SCHEMA_SQL`. Otherwise a rollback to today's image recreates the dropped tables empty. How we know:

- `00N` is a **later PR**, not the foundation PR that removes `SCHEMA_SQL`.
- The foundation image (and every later image) records its image tag — the tag passed to `remote-up.sh`, also `BACKEND_IMAGE` — into `schema_migrations` or a small `deployed_images(tag, deployed_at, schema_sql_removed BOOLEAN)` table at boot, after a successful `upgrade`.
- The `00N` runner **refuses to apply** unless at least **N = 2** distinct production image tags have booted with `schema_sql_removed = true`. That is the foundation deploy plus one subsequent deploy. Rolling `00N` back to any pre-foundation tag is forbidden in the runbook.
- Keep the wipe as `TRUNCATE` until that gate passes.

**130 sequencing.** The foundation (`002`) should land before or instead of 130e. 130g and 130j then write to `player_prop_snapshots`. The 138a backfill writes `snapshot_kind=opening` into the same tables. See §7.

## 5. Storage vs the RDS instance

Instance: RDS `db.t4g.micro` (1 GiB RAM, 20 GB gp3, autoscale 50 GB) from terraform defaults, not a live `describe-db-instances`. The **backend host** on `#64` is `t4g.small` (2 GiB, `variables.tf:226-229`). The cap that will OOM the API process is the backend container **`mem_limit: 1g`** (`deploy/docker-compose.prod.yml:65` on `refs/remotes/pr64`). Disk is not the tight bound; that 1g container limit is.

Measured bytes/row (`pg_total_relation_size`, includes indexes), only where n is large enough to trust:

| Table | Sample n | Bytes/row (measured) | Source |
|---|---|---|---|
| `player_game_stats` | 28,848 | **385.1** | 28 BDL `/v1/stats` rows + 28,820 shipped CSV logs |
| `player_prop_snapshots` (all lines) | 10,784 | **290.9** | Recorded opening-prop samples, deeplinks dropped |
| `player_prop_snapshots` (main only) | 4,835 | **313.4** | Same samples, one line per (game, player, vendor, prop_type) |
| `game_odds_snapshots` | 222 | 627 (inflated by empty toast pages; heap 147.6) | Opening-odds samples, deeplinks dropped |
| `games` | 107 | 995 (inflated; heap 153.1) | BDL game samples |

Trusted extrapolations use 385.1 (stats), 313.4 (main props), ~450 (games, estimated from measured heap plus index growth), ~400 (game odds, estimated after removing empty-toast padding). Stats and props were measured with the copied name and abbreviation columns the 2026-11-16 review removed (§9.1), so the totals below are upper bounds.

Game counts: **1,260** measured for 2000 (13 pages, 2000-10-31 to 2001-06-15: 1,189 regular season, which is 29 teams × 82 / 2, plus 71 playoff games; measured 2026-11-16), **1,322** measured for 2025 (14 pages, 2025-10-21 to 2026-05-11; by `season_type`, measured 2026-11-17: 85 playoffs, 6 play-in, 1 Cup final, so 1,230 regular season by subtraction until the full walk confirms it), **1,200** measured for 2026 (12 pages, 2026-10-20 to 2027-03-30, playoffs not listed yet). All other seasons: **estimated** from published regular-season schedules (29 teams through 2003-04, 30 after; 2011-12, 2019-20 and 2020-21 shortened) plus era-typical playoff totals → **~34,500** games for 2000–2026 inclusive.

Stats rows: page-1 densities **measured** at 24 player-rows per game for 2000-01 and 33 for 2025-26 (2025-26 lists inactive players as `min: "00"` rows). 26 per game is **assumed** for 2001–2024. → **~0.92 million rows, estimated** (0.85–1.0M). Opening-prop coverage start 2024-25 and opening-odds start 2020-12-23 are **measured**.

| Table | Rows | Size | Row count | Bytes/row |
|---|---|---|---|---|
| `player_game_stats` | ~0.92M | **~354 MB** | estimated | measured 385.1 |
| `games` | ~34,500 | **~16 MB** | mix (3 seasons measured, rest estimated) | estimated 450 |
| `player_prop_snapshots` opening, **main only** (the plan) | 1.33M | **416 MB** | 2024 density estimated from samples; 2025 1,322 games measured × ~500 estimated; 2026-to-date ~170 estimated × 816 measured main lines | measured 313.4 |
| `player_prop_snapshots` opening, **all lines** (not recommended) | 1.90M today, plus ~1.1 GB more if the rest of 2026 stays at ~3,800 lines/game | 553 MB now, ~1.7 GB if 2026 is filled dense | estimated | measured 290.9 |
| `game_odds_snapshots` opening | ~22k | **~10 MB** | 2020-25 ≈ 1 vendor/game measured on sample dates; 2026 ≈ 12 vendors/game measured 2026-11-10 | estimated 400 |
| `game_lineups` 2025-26 + 2026-27 | ~65k | **~15 MB** | estimated 26 players/game × 2,522 games | estimated ~200 (small sample was page-padded) |
| `projected_lineups` + `projected_lineup_players`, `teams`, `players`, `seasons`, `books`, `prop_markets`, checkpoints, injuries (change-log) | small | **<10 MB** | estimated before projected lineups kept every BDL version; not re-estimated | — |
| Optional `box_scores` JSONB for 2000 on | ~34,500 | **~0.5 GB** | game count as above; ~15 KB/game from measured 11.6 KB JSON + toast | estimated; 6-row PG measurement was too small to trust |
| **Recommended backfill total (no box JSONB, main props only)** |  | **~0.8 GB** |  |  |
| + ~30% WAL / bloat / free space |  | **~1.1 GB estimated** |  |  |

**20 GB is enough for the backfill**, with a large margin. Autoscaling to 50 GB is a sufficient ceiling. Raising `allocated_storage` before the run is optional, not required.

What would change that:

- Keeping **every live tick** (3/day × ~8 games × ~800 main lines × ~200 days) is about **1.2 GB/year estimated** on top of opening + closing (~400 MB/year for close). Recommendation: persist opening and closing forever; downsample or TTL live rows (keep the last live before tip, or a 14-day window). Ask Eason.
- Storing all 2026 alt / milestone ladders in opening or live snapshots. One recorded 2026 final was 3,889 lines vs 816 main (measured). A full dense season at that rate is about **1.5 GB estimated** for opening alts alone. Eason already said to drop alts.
- Loading full-history stats into the API process. QA loaded the real `CSVPlayerHistoryService` and measured 1,729 bytes/row in `_cache` (49.83 MB for 28,820 rows). ~0.92 million rows at that density is about **1.6 GB** of Python dicts, which will still OOM the **1g** container `mem_limit`. A current-season hot cache (~20–30k rows, similar to today, ~50 MB) fits. Full history is queried from Postgres by player/season (§6) and is never loaded into that container. The 1 GiB RAM on the RDS instance itself is a separate concern: stop the backend during the 138a load, create indexes after the heap is loaded, and watch autovacuum / `maintenance_work_mem`. The `#64` parameter group only sets `rds.force_ssl=1`.

## 6. What the CSV game logs become

Today NBA history is **not** in Postgres. The shipped file `data/nba_player_game_logs.csv` is 28,820 rows, 3.79 MB, seasons 2024-25 (partial, 730 rows) and 2025-26 (28,090 rows), dates 2024-10-22 to 2026-05-11 (all measured). It is downloaded from `github.com/eason034056/nba-player-stats-scraper` (`csv_downloader.py:42`) and loaded entirely into `CSVPlayerHistoryService._cache` (`csv_player_history.py:514-662`). WNBA uses `data/wnba_player_game_logs.csv` (**4,875** data rows, 608,991 bytes, dates 2025-05-16 to 2026-05-08, measured; 4,876 was `wc -l` including the header) the same way and stays on that file (Q10).

Both leagues share one class in one process (`csv_player_history.py:1470-1475`: `nba_csv_player_service` and `wnba_csv_player_service`; `daily_analysis.py:90-92` picks by league). The scheduler runs both jobs inside the backend process (`#64` compose comment). A process-wide `HISTORY_SOURCE=csv|db` would take WNBA off its CSV (empty in Postgres) and would break `_build_team_roster_cache` (`lineup_source_support.py:299-311`), which constructs a new `CSVPlayerHistoryService(league=league_key)` and walks `_cache` for **both** leagues.

**Recommendation.** Keep `CSVPlayerHistoryService` as the public facade (same method names and return shapes, including `latest_position`, `latest_team`, `resolve_player_name`, `get_player_opponents`, `get_all_players`, `get_player_stats`, `player_dd_history`, and the module-level `team_on_event` / `team_from_game_logs`). Internally:

1. **The source flag is per league, on the class**, not per process. `NBA_HISTORY_SOURCE=csv|db` (default `csv` until the backfill is verified) is read by instances with `league='nba'`. Instances with `league='wnba'` are **always** `csv`. A new `CSVPlayerHistoryService(league='wnba')` (the lineup helper) must honor that, not a module-level flag. Do not introduce a process-wide `HISTORY_SOURCE`.
2. **Each reader declares a history scope** — `current_season`, `last_n_seasons`, or `full` — as in the §2 table. The facade takes that scope (or a season/date window) on the public methods.
3. **Full history is queried from Postgres by player and season** (or a bounded date window). It is never loaded into the 1g backend container. ~0.92 million rows ≈ 1.6 GB in `_cache` (1,729 bytes/row QA measured; row count estimated).
4. An optional **current-season-only** in-process `_cache` (~20–30k rows, ~50 MB) may serve `current_season` NBA readers after the flip. It is **not** a public surface for `last_n_seasons` or `full` readers. If those callers today walk `_cache`, they are switched to a public method that hits SQL for the requested window.
5. The GitHub NBA downloader is retired once the NBA facade reads Postgres (Q10). WNBA keeps its CSV and its downloader. Tests that `patch` `CSV_PATH` keep a CSV-backed path for fixtures.

Readers that need **more than the current season** (must have a DB query path, not a current-season `_cache`):

| Reader | Scope | Query path |
|---|---|---|
| `GET /api/nba/player-history` / `get_player_stats` when `n` spans a prior season or `n=0` | last_n_seasons or full | `SELECT … FROM player_game_log WHERE league='nba' AND bdl_player_id = $1 AND date < $2 ORDER BY date` (optional `season` / `LIMIT`), after resolving the name through `players` |
| `GET /api/nba/player-dd-history` | last_n_seasons or a named season | same, filtered to the season and pts/reb/ast |
| Daily analysis / event reads early in the season (last-10 can cross) | last_n_seasons | same, window = current + previous |
| Agent historical tools (`historical.py:151, 183`, `_games_for`, `_team_for`, `get_base_stats`, splits, trends) | last_n_seasons or **full** (career) | Public methods that query by player/season. Do not do `csv._cache.get(...)`. Scripts run off-process with their own connection when possible |
| Walk-forward / backtest / calibration (`walk_forward.py:340, 600, 917`, `backtest.py:234`, `calibration_guard.py:225`) | **full** for the harness window | Script-side SQL or the facade pointed at Postgres, fetching by player and season for that window. They must stop replacing or reading `_cache` as the season store |
| Dataset sampler | last_n_seasons or full (sampler window) | SQL by player/season |
| Board-shift measurer | last_n_seasons (the measured window) | same analysis path, SQL-backed |
| Eval odds open/close | the eval window | `player_prop_snapshots` by player/market/date |

`current_season` readers (defense ranks, `get_all_players`, tonight’s `latest_position` / `latest_team`, lineup roster for NBA, slate routes) may use the optional hot cache or a single-season SQL scan. Defense ranks today walk `_cache` (`defense_ranks.py:211-217`) and must switch to a current-season SQL scan (or a daily materialized table) even though their scope is only the current season.

Migration plan:

1. Land the tables and the per-league adapter (default NBA `csv`).
2. Backfill `games` + `player_game_stats` (138a). Verify per-season counts against BDL and, for 2025-26, against the shipped CSV (row counts will not match exactly: BDL vs scraper, DNP handling, name spelling, and game-type classification: BDL `season_type` against the CSV's ESPN-derived `game_type`).
3. Flip `NBA_HISTORY_SOURCE=db`. WNBA is unchanged. Confirm `_build_team_roster_cache` still loads the WNBA CSV.
4. Retire the NBA GitHub download job (Q10). Leave the file in the repo until QA is satisfied, then stop shipping it.
5. Point eval / walk-forward / dataset scripts at the SQL facade. No second source of truth for NBA.

## 7. 130e: do not add columns twice

130e as written (SPO-130 plan §3) adds `league`, `provider`, `provider_player_id`, `source_updated_at` to `odds_line_snapshots`, and points `bulk_props`, `event_reads`, and `odds_history` at `league`.

**The new `player_prop_snapshots` table supersedes 130e.** Three of those fields are first-class in §1.9 (`league`, `bdl_player_id`, `source_updated_at`), together with `snapshot_kind`, `book_key` (grouped through `books.source_group`), and a unique key that includes kind. `provider` is not needed: every row carries BDL ids.

Recommendation:

- **Do not ship 130e as an ALTER of `odds_line_snapshots`.**
- Replace 130e with a foundation PR that applies `002_bdl_core.sql` (additive, no behavior change if writers are not yet switched) and retargets the three readers + the one writer when 130g is ready.
- 130g writes `snapshot_kind='live'`. 130j writes `closing`. 138a writes `opening`. One table, no column added twice.
- If 130e has already merged when this lands, stop adding more columns to the old table; add a follow-up that copies any new NBA rows into `player_prop_snapshots` and leaves the old table read-only until the 138 wipe drops it.

## 8. Open questions for Eason

These questions are answered in §9 (Q7/Q10 by Eason after the first pass; Q2's prefix later confirmed by Lead as `bdl-raw/`, plus a short local cache — not ephemeral-only). Left here as the original list.

1. Confirm **no queryable `box_scores` JSONB table** (use `games` + `player_game_stats`). Raw box payloads, if any, follow the §3 / §9 Q2 retention (`bdl-raw/` plus a short local cache). **Answered §9.**
2. Confirm raw BDL body retention. **Answered §9 Q2:** gzip to the existing data bucket under `bdl-raw/` (not `raw/bdl/`) with a 90-day lifecycle, plus a short local cache. Not RDS JSONB.
3. **Live snapshot retention:** keep opening + closing forever, but TTL or downsample live ticks? Default proposal: keep only the last pre-tip live row (or 14 days). Three ticks a day at 2026 main-line density is ~1.2 GB/year estimated if all are kept.
4. **130e sequencing:** is it acceptable to replace 130e with the foundation migration, so 130g writes straight to `player_prop_snapshots`?
5. **Injury history:** daily snapshot + Redis latest, or every 30-minute refresh kept forever?
6. Should **130j also store closing game odds** (spread/ML/total), or only player props?
7. **Preseason / IST / play-in** in `games` and `player_game_stats`? Proposal: store IST, play-in, and playoffs; omit preseason, matching BDL's default and today's CSV hygiene. **Answered §9: regular + playoffs only (2026-11-12); revised 2026-11-17 to store the play-in and the Cup final too.**
8. Early-season **stat quality** (null rebounds/steals, `min="0"` with points, teams mapped onto modern names): backfill anyway and flag `season < 1979` (or similar) as reduced quality?
9. Optional: bump `allocated_storage` from 20 to 40 GB before the run, or rely on autoscale to 50? The backfill itself does not need it.
10. After the wipe, is it acceptable that **the GitHub NBA CSV is no longer the source of truth**, even if the file remains in the repo for a while? **Answered §9: yes, DB is the NBA source of truth; downloader retired.**


## 9. Decisions (2026-11-12, Lead; Q7/Q10 answered by Eason the same evening)

Lead and Eason added the Q7 and Q10 answers below after the first design pass. Lead later confirmed the S3 prefix is `bdl-raw/` (not `raw/bdl/`); Q2 is updated only for that prefix.

- Q1: no `box_scores` JSONB table.
- Q2: raw BDL bodies gzip to the existing data bucket under `bdl-raw/` (Lead; the `#64` / `origin/dev` IAM allow-list already grants `s3:PutObject` on that prefix — `infra/aws/locals.tf:5`, `iam.tf:21-24`) with a 90-day lifecycle, plus a short local cache. Keep the bucket name/account id out of committed code; read it from settings/SSM. `#64` `s3.tf` currently expires only `pg-dumps/`; a current-object expiration rule for `bdl-raw/` still has to be added if 90-day deletion is the intent (a 90-day Glacier transition is not a delete).
- Q3: opening + closing kept forever; live ticks downsampled to the last pre-tip row after 14 days.
- Q4: 130e is replaced by the foundation PR applying `001_baseline` + `002_bdl_core`.
- Q5: injuries stored as a change-log: insert only when status/return_date/description changes, checked at each refresh.
- Q6: 130j stores closing game odds (spread/ML/total) as well as props.
- Q8: superseded by Eason on 2026-11-15. No data-era or quality flag. Games and stats start at 2000-01, where page-1 measurements show every box column filled for players who played. The one era gap measured, `plus_minus` null across 2000-01, stays a nullable column. Missing values are NULL, never guessed (§1.6).
- Start season (Eason, 2026-11-15): games and stats from 2000-01 instead of 1946-47. The change can be undone, because upserts and checkpoints let earlier seasons be added later. Estimates in §5 are updated (~34,500 games, ~0.92M stat rows).
- Q9: stay at 20 GB with autoscaling.
- Status: migration code on hold until QA's interrogate review and Eason's OK.
- Q7 (Eason, revised 2026-11-17): store the regular season, playoffs, play-in, and Cup final, each under its own product game type (§1.5); no preseason. Whether the play-in and the Cup final count with the regular season is decided in the reader's query, not by the stored label. The NBA keeps both out of regular-season statistics, the play-in plays closer to the playoffs, and a merged label could not be split again because the `/v1/games` object does not carry its type. The 2026-11-12 answer stored regular season and playoffs only.
  - Measured 2026-11-12 (2 BDL calls): BDL labels NBA Cup group games and the quarterfinals/semifinals `season_type=regular` (`ist_stage` set, e.g. `East Quarterfinal`), and only the Championship `season_type=ist`. Group, QF, and SF games stay regular season with `ist_stage` stored (the NBA counts them in regular-season stats). `ist_stage` is only populated from the 2025 season; earlier Cup games are just regular games.
  - Measured 2026-11-17 (3 BDL calls, fixtures `games__season2025_playin_page1.json`, `games__season2025_ist_page1.json`, `games__season2019_playin_page1.json`): `playin`, the value BDL's docs list, returns the 6 play-in games of 2025-26 (2026-04-14 to 04-17) and the 2019-20 bubble game (2020-08-15, MEM at POR). `ist` returns one 2025-26 game, the Championship on 2025-12-16.
  - The backfill walks each season once per BDL `season_type` (`regular`, `playoffs`, `playin`, `ist`) and the writer translates it (§1.5). Stats for a game not in `games` are still dropped and counted, now as a guard: with every type stored, a dropped row is unexpected and is listed in the season's verification.
- Q10 (Eason): NBA source of truth is the DB. The GitHub NBA CSV downloader (`csv_download_job` for NBA) is retired once `CSVPlayerHistoryService` reads Postgres; WNBA stays on its CSV and its downloader.
- Shooting percentages (Eason, 2026-11-16): store `fg_pct`, `fg3_pct`, and `ft_pct` in `player_game_stats` as BDL sends them. They are for one-game reads and model features; multi-game rates are computed from made and attempted (§1.6).
- Prop markets (Eason, 2026-11-16): store the 12 full-game BDL prop types in `prop_markets` (§1.9), including `player_blocks` and `player_triple_double`, which the product does not list yet. Drop `player_frees_made` and `player_field_goals` from the data model, because BDL has no prop type for them. Do not store first-quarter or first-three-minute props, because they have no opening history and full-game stats cannot settle them.

### 9.1 Schema review (Eason, 2026-11-16)

Review of the first `002_bdl_core.sql`, written on the SPO-138b branch. `001_baseline.sql` (§4) is not written yet. Each item below is in the migration and covered by `backend/tests/test_migration_002_bdl_core.py`.

- **Props keep the narrow key.** One main line per game, player, book, and market at each snapshot; `line` stays out of both keys. This reaffirms “drop alts” (SPO-130 §7). A wider key that kept the whole ladder was considered and rejected. The writer picks the main line (§1.9).
- **Projected lineups are versioned** by BDL `updated_at`, with players in `projected_lineup_players` (§1.8). They may be an ML input, so a pregame read takes the newest version our job had stored by its own time (`first_seen_at`), not the newest BDL had published. The versions come from our own polling; BDL keeps none. Keeping only the latest projection was considered on 2026-11-16 and dropped: it would leak later lineups into training, and the lost versions could not be recovered.
- **Ids only in fact tables.** `player_game_stats`, `game_lineups`, `injury_snapshots`, and the two odds tables no longer copy names, abbreviations, home/away, starter flags, `source_group`, or the game's date and season where a join gives them. `games.season_type` is the only place a game's type is stored (`postseason` and `game_type` are gone). The `player_game_log` view rebuilds the reader row (§1.6).
- **`player_game_stats` keeps `season` and `date`** for its indexes, tied to `games` by a composite FK with `ON UPDATE CASCADE`.
- **`league` has no default** and is the `league_code` domain (§1 conventions).
- **Injury removals are rows.** `injury_snapshots.listed = false` records a player leaving the list, found by comparing complete refreshes, because BDL sends no removal (§1.7).
- **Props store prices, not derived values.** No `vig`, fair probabilities, or `provider` (§1.9). `market_type` and `line` are `NOT NULL`, a CHECK ties the set odds columns to `market_type`, and `market` is an FK to `prop_markets`.
- **Not decided: opening and closing semantics for CLV.** BDL's opening is its first capture at tip-off minus 3 hours (§1.9), not the book's first post. No CLV work is planned now, so this stays open.

## 10. Foundation PR carry-overs (QA recheck 1)

QA cleared the design for Eason's approval. The foundation PR (001_baseline + 002_bdl_core) must also do the following:

- **Compose command:** a YAML list command does not treat `&&` as a shell operator. Run `upgrade && uvicorn` through `sh -c` or an entrypoint script, in both `deploy/docker-compose.prod.yml` and the Dockerfile CMD.
- **DROP gate:** the "2 later images migrated first" gate counts only unique, non-`latest` image tags.
- **Partial-index upserts:** every writer uses the exact `ON CONFLICT (...) WHERE ...` predicate from §1.9. A mismatched WHERE that still names a real partial index fails at runtime with 23505 instead of updating. Add one test per writer.
- **Baseline diff:** QA diffs `001_baseline.sql` against dev 55750de's `SCHEMA_SQL` with `pg_dump --schema-only`. `odds_line_snapshots.line` stays nullable and in the legacy unique key; the baseline matches it as it is.

Open questions for Eason (they don't block approval): whether to stop the backend during the GOAT-600 backfill, whether the current backend refills NBA odds from The Odds API if it restarts after the wipe, and how to handle BDL cursor expiry mid-walk.

### 10.1 Lead's answers to QA's operational items (2026-11-12)

- **Backfill rate and backend state:** the key is GOAT 600/min (verified live). The backend stays stopped for the whole wipe and backfill, and the backfill is capped at 500/min.
- **Wipe gate:** the 130 cutover (130i merged and deployed) is a hard gate before the wipe. After the wipe, nothing restarts the backend with NBA on The Odds API.
- **Expired BDL cursor:** the backfill script has a documented `--restart-season <season>` path, which re-walks that season from its first page. Upserts are idempotent, so a re-walk is safe.
- **#64 follow-up:** add a 90-day current-object expiration rule for `bdl-raw/` in `s3.tf`, alongside s3:PutObject.

## 11. Read layer: `004_read_layer.sql` (SPO-138i, 2026-11-20)

`004` adds one table and four views. It is 004 because SPO-138g's `003_bdl_game_gaps.sql` holds version 003. No 002 table changes. The reasons and the rejected alternatives are in [`decision_20261120_read-layer-and-ml-inputs.md`](decision_20261120_read-layer-and-ml-inputs.md).

| Object | Kind | Read by |
|---|---|---|
| `predictions` | Append-only table. `predicted_at` is the insert time; inserts at or after tip-off are refused | Frontend predictions and record; model grading |
| `current_predictions` | View: newest run per game, player, market, and model version | Frontend |
| `prop_actuals` | View: the result of every market for each stat line of a final game. NULL is void (`dnp`) or unknown | Model label; grading |
| `current_injuries` | View: each player's newest row, kept only if still listed | Frontend |
| `current_projected_lineups` | View: newest projected version per game and team | Frontend |

The model never reads `player_prop_snapshots`; prop odds enter only the betting decision and its evaluation. Model inputs are built outside Postgres by the dataset module (SPO-138j) under the as-of rules in the decision file.
