# Decision — WNBA rollout Phase 3 DB schema audit (SPO-35 Step 1)

- Date: 2026-05-14
- Author: Forge (agent `d5d67ab1-...`)
- Ticket: [SPO-35](/SPO/issues/SPO-35)
- Parent epic: [SPO-29](/SPO/issues/SPO-29) (WNBA rollout) · prior decision: `decision_20260513_phase-decomposition.md`
- Gate: Gate 2 (destructive migration escalation) — **NOT triggered**, see §5.
- Scope: every table `daily_analysis.py` writes to or reads from, plus every table written by scheduler jobs that share the same lifecycle (`projection_service`, `odds_snapshot_service`, `lineup_service`).

> Output of Step 1 of SPO-35. Step 2 (implementation) is gated on owner / CTO
> acknowledgement of the recommendation in §6.

---

## 1. Background & mandate

SPO-35 wires WNBA into the daily-picks pipeline (league-aware `daily_analysis`,
independent scheduler job, `/api/wnba/daily-picks*`, `/wnba/picks` page).

Before writing any migration the ticket mandates a schema audit:

> Inspect every table `daily_analysis.py` (and downstream scheduler tasks)
> writes to or reads from. For each table, answer: does it need a `league`
> column to keep NBA + WNBA rows from colliding?

If the audit recommends a **destructive** migration (drop column, change type,
change PK, ALTER large table without `IF NOT EXISTS`), do NOT run it — reassign
to CTO with the destructive op and table size.

## 2. What `daily_analysis.py` actually writes

Read of `backend/app/services/daily_analysis.py` (lines 248–394):

- The only write target is **Redis**, key `daily_picks:{date}:tz{offset}`
  (`DAILY_PICKS_CACHE_KEY = "daily_picks"`, TTL 15 min).
- It does NOT write to PostgreSQL.
- It reads from `cache_service`, `odds_gateway` (snapshot cache), `csv_player_service` (file), `projection_service` (DB-backed).

The task brief mentions "the `daily_picks` table" — that table does **not exist
in PostgreSQL**. `daily_picks` is purely a Redis namespace. So the migration
question for `daily_picks` reduces to a Redis-key namespacing question (§4.7).

## 3. Tables touched by scheduler jobs

Mapped from `backend/app/services/scheduler.py` job handlers to the SQL they ultimately execute
(`db.py` → `SCHEMA_SQL`):

| Table | Written by | Read by | Unique constraint | Row volume / day (est.) |
|---|---|---|---|---|
| `player_projections` | `projection_service.fetch_and_store` | `projection_service.get_projections` (PG miss fallback) | `UNIQUE(date, player_name, game_id)` | ~250 (NBA) |
| `projection_fetch_logs` | `projection_service` (success/error log) | — | none | 3/day per league |
| `odds_line_snapshots` | `odds_snapshot_service.take_snapshot` (`UPSERT_LINE_SQL`) | `odds_history` API (`grouped by snapshot_at,player,market`) | `UNIQUE(snapshot_at, event_id, player_name, market, bookmaker)` | ~10k–30k (NBA, 3 snapshots × ~30 events × ~12 markets × ~10 players × ~6 books) |
| `odds_snapshot_logs` | `odds_snapshot_service._log_snapshot` | — | none | 3/day per league |
| `team_lineup_snapshots` | `lineup_service.fetch_and_store` (`UPSERT_LINEUP_SQL`) | `lineup_service._read_from_postgres` (Redis-miss fallback) | **`UNIQUE(date, team)`** | ~30 (NBA) |
| `lineup_fetch_logs` | `lineup_service._log_fetch` | — | none | many (cron runs every 15 min, 5 min near tip-off) |

All six tables live in a single PostgreSQL instance defined in
`backend/app/services/db.py` (`SCHEMA_SQL`). There is **no alembic** and no
migration directory — schema is applied once on startup via
`CREATE TABLE IF NOT EXISTS` in `db_service.init()`. Schema changes go in the
same SQL block, idempotent via `IF NOT EXISTS` / `IF EXISTS` predicates.

## 4. Per-table verdict

### 4.1 `player_projections` — **DEFER**

- Today: NBA-only (`projection_service` calls SportsDataIO NBA endpoint;
  Redis namespace is already `projections:nba:{date}`).
- Collision risk: `(date, player_name, game_id)` — SportsDataIO uses
  separate `game_id` spaces per league, player names are practically distinct
  across rosters. Low risk even if WNBA wired later.
- WNBA projections are **not** part of SPO-35 scope (SportsDataIO WNBA
  projections endpoint isn't wired yet — `projection_service.get_projections`
  in daily_analysis is best-effort, returns `{}` if API fails, and the WNBA
  CSV path can run history-only).
- Recommendation: **no migration**. Re-evaluate when (and if) WNBA
  projections are wired. The fix at that point is a one-line
  `ADD COLUMN league TEXT NOT NULL DEFAULT 'nba'` plus drop/recreate the
  unique constraint to include `league`.

### 4.2 `projection_fetch_logs` — **DEFER**

- No unique constraint; only used for observability.
- Same WNBA-not-wired status as 4.1.
- Recommendation: **no migration**. Add `league` later if and when WNBA
  projections become a routine cron target.

### 4.3 `odds_line_snapshots` — **DEFER**

- Collision risk: **NONE** under the existing unique constraint. The
  Odds API `event_id` is globally unique across sport keys
  (`basketball_nba` vs `basketball_wnba` produce disjoint event IDs); player
  names overlap is negligible.
- Read queries pass `event_id` and/or `player_name + market`, which already
  scope to a single league implicitly.
- Future analytics that aggregate by date+market without an event filter
  would benefit from an explicit `league` column, but that's a feature, not
  a correctness gap.
- Recommendation: **no migration in SPO-35**. Track as a SPO-29 follow-up
  if analytics over mixed-league market data becomes a requirement.

### 4.4 `odds_snapshot_logs` — **OPTIONAL ADDITIVE**

- No unique constraint, observability table.
- Today both leagues' snapshot health is **indistinguishable** in this log
  (and SPO-35 introduces the second league). A `league` column would let
  oncall query "did the WNBA snapshot job succeed at UTC 22:05?" without
  cross-referencing application logs.
- Migration would be a one-line `ADD COLUMN IF NOT EXISTS league TEXT
  NOT NULL DEFAULT 'nba'`. No constraint changes.
- Recommendation: **include in this migration as a quality-of-life fix**.
  Pure additive, zero risk, and SPO-35 is the natural moment because
  it adds the second league.

### 4.5 `team_lineup_snapshots` — **REQUIRED, ADDITIVE**

This is the only **blocking** schema concern.

- Existing constraint: `UNIQUE(date, team)`.
- **Collision is real and immediate**: WNBA teams share short codes with
  NBA teams. From `backend/app/services/lineup_provider_rotowire.py` /
  RotoWire WNBA scrape + SPO-34's enumeration:
  `ATL`, `CHI`, `DAL`, `IND`, `MIN`, `PHO`, `SEA`, `WAS`, `GS`.
  The WNBA Atlanta Dream and the NBA Atlanta Hawks share `ATL` and play on
  overlapping calendars (WNBA May–Oct overlaps with NBA late-season May,
  preseason Oct).
- SPO-34 (currently in open PR #13, not yet on `origin/dev`) punted on
  this: WNBA lineups are routed to Redis only, and the
  `wnba_lineup_service` instance in that PR has three explicit comments
  flagging the deferred `league` column. The PostgreSQL persistence path
  is `if self.league == "nba"` gated. The migration here closes that
  follow-up so when SPO-34 merges and SPO-35 rebases on top, the WNBA
  PG write/read path becomes a one-line code change.
- Without `league`, the dev-DB fallback for WNBA lineups (Redis-miss case)
  is dead code — `_read_from_postgres` returns `{}` for non-NBA. SPO-35
  doesn't *strictly* require fixing this (daily-picks doesn't read
  lineups from PG today), but SPO-35 is the natural place per SPO-34's
  follow-up and there is no foreseeable reason to defer further.
- On the current branch base (`origin/dev` @ 328f9bd, pre-SPO-34) the file
  `backend/app/services/lineup_service.py` is still NBA-only — the
  migration is being authored against the post-SPO-34 shape, and rebase
  conflicts (if any) will be in `lineup_service.py`, not in the SQL.
- Migration shape (proposed):
  ```sql
  ALTER TABLE team_lineup_snapshots
    ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'nba';

  -- Drop the old narrower unique constraint and replace with a
  -- strictly-more-permissive one that includes league. New constraint
  -- accepts every (date, team) row the old one did, plus WNBA rows that
  -- previously could not coexist.
  ALTER TABLE team_lineup_snapshots
    DROP CONSTRAINT IF EXISTS team_lineup_snapshots_date_team_key;

  ALTER TABLE team_lineup_snapshots
    ADD CONSTRAINT IF NOT EXISTS team_lineup_snapshots_date_team_league_key
    UNIQUE (date, team, league);
  ```
  Wrapped in a single transaction inside the `db_service.init()` startup
  block (idempotent on re-run).
- Row volume: ~30/day × ~200 game days × ~1 season currently in dev DB.
  Production DB does not exist as a separate environment in this repo
  (see `db.py` graceful-degrade "Projections will run without persistent
  storage" — PostgreSQL is optional, not production-critical). ALTER on a
  few thousand rows in dev is instant.

### 4.6 `lineup_fetch_logs` — **OPTIONAL ADDITIVE**

- No unique constraint, observability table.
- WNBA lineup refresh failures are currently indistinguishable from NBA
  failures in this log (the cron writes to it on every run, every 15 min
  during the day, every 5 min near tip-off — high volume).
- Migration: `ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'nba'`.
- Recommendation: **include**. Same reasoning as 4.4.

### 4.7 Redis key `daily_picks:*` — **REQUIRED, code-only**

- Not a SQL table. Cache key shape today:
  `daily_picks:{date}:tz{offset}` (from `daily_analysis.py:285`).
- `cache_service.clear_daily_picks_cache()` deletes pattern
  `daily_picks:*` (from `cache.py:188`). After SPO-35 this would blast both
  leagues' caches when only one needs refreshing.
- Fix is code-only, not a migration:
  - Cache key becomes `daily_picks:{league}:{date}:tz{offset}`.
  - `clear_daily_picks_cache(league: str = "nba")` deletes
    `daily_picks:{league}:*`.
  - Backward compatibility: the `DELETE /api/nba/daily-picks/cache`
    endpoint can delete both the new `daily_picks:nba:{date}:tz{offset}`
    and the legacy `daily_picks:{date}` / `daily_picks:{date}:tz{offset}`
    keys (15-min TTL means anything legacy is gone within one TTL anyway).

## 5. Gate 2 assessment

Gate 2 triggers on "drop column, change type, change PK, ALTER large table
without `IF NOT EXISTS`" (SPO-35 description).

- **Drop column**: not proposed.
- **Change type**: not proposed.
- **Change PK**: not proposed. `team_lineup_snapshots` PK is
  `id SERIAL PRIMARY KEY`; that does not change. Only the secondary
  `UNIQUE(date, team)` constraint is replaced with a strictly-more-permissive
  one.
- **ALTER without IF NOT EXISTS / IF EXISTS**: all proposed ALTERs use
  `ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS`,
  `ADD CONSTRAINT IF NOT EXISTS`.

Replacing a unique constraint with a strictly-more-permissive one is
**not destructive**: every row that was previously legal remains legal,
and the new constraint additionally admits WNBA rows that the old one
could not represent at all. The data is preserved and the runtime semantics
get strictly wider.

**Verdict: Gate 2 is NOT triggered.** Forge may proceed with implementation
once the owner / CTO acknowledges this audit.

## 6. Recommended migration (SPO-35 Step 2)

Single migration block appended to `SCHEMA_SQL` in `backend/app/services/db.py`,
run on startup via the existing `db_service.init()` path:

```sql
-- SPO-35: league-aware tables for WNBA rollout (Phase 3).
-- Additive only; pre-existing NBA rows backfill to league='nba'.

ALTER TABLE team_lineup_snapshots
  ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'nba';

ALTER TABLE team_lineup_snapshots
  DROP CONSTRAINT IF EXISTS team_lineup_snapshots_date_team_key;

ALTER TABLE team_lineup_snapshots
  ADD CONSTRAINT IF NOT EXISTS team_lineup_snapshots_date_team_league_key
  UNIQUE (date, team, league);

ALTER TABLE lineup_fetch_logs
  ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'nba';

ALTER TABLE odds_snapshot_logs
  ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'nba';
```

Tables explicitly left UNCHANGED (and why):

- `player_projections`, `projection_fetch_logs` — WNBA projections not wired
  (§4.1, §4.2).
- `odds_line_snapshots` — globally-unique event_id makes the existing PK
  collision-proof (§4.3).

Companion code changes (Step 2):

1. `daily_analysis.py` — accept `league: str = "nba"` parameter, plumb to
   `odds_provider.get_events(sport=...)` (`basketball_nba` vs `basketball_wnba`),
   route to `csv_player_service` (NBA) vs `wnba_csv_player_service` (WNBA),
   skip projection lookup for WNBA (no SportsDataIO WNBA endpoint wired yet),
   namespace cache key per §4.7.
2. `scheduler.py` — register a separate `wnba_daily_analysis_job` cron;
   failure-isolated from the NBA job (independent `try`/`except`).
3. `cache.py` — `clear_daily_picks_cache(league: str = "nba")`.
4. `backend/app/api/wnba.py` — append `GET /api/wnba/daily-picks` and
   `POST /api/wnba/daily-picks/trigger` mirroring `daily_picks.py`.
5. `lineup_service.py` — drop the `if self.league == "nba"` PG-write gate
   (WNBA now persists too); pass `league` into `_write_to_postgres` and
   `_read_from_postgres` queries.
6. `frontend/app/wnba/picks/page.tsx` — mirror `app/picks/page.tsx` against
   the new endpoint.

Tests (Step 2):

- Unit: `test_daily_analysis_league.py` — verifies `league="wnba"` passes
  `basketball_wnba` to the odds provider, uses `wnba_csv_player_service`,
  and writes to the `daily_picks:wnba:{date}:*` cache namespace.
- Integration (`@pytest.mark.integration`, `RUN_INTEGRATION=1` gated):
  trigger WNBA daily picks against today's slate; assert no 500, assert
  response shape.
- Migration smoke: pytest fixture starts a fresh PG, runs SCHEMA_SQL twice,
  asserts no error (idempotency).

## 7. Outstanding questions for owner / CTO

1. Acknowledge that "drop a UNIQUE constraint + add a wider UNIQUE" is
   classified as **additive** under the SPO-35 Gate 2 definition (§5). My
   reading is yes; flagging explicitly so the gate isn't litigated later.
2. Optional table coverage (§4.4 `odds_snapshot_logs`, §4.6
   `lineup_fetch_logs`) — accept as part of this PR, or split into a
   separate observability-only PR? My recommendation is to include because
   the diff cost is one line per table and the WNBA scheduler job is the
   natural cause.
3. Defer `player_projections` / `odds_line_snapshots` league columns until
   actual WNBA writes appear (§4.1, §4.3) — sound, or pre-emptively add
   now? My recommendation is defer; YAGNI without a write path.

## 8. Sources

Branch base: `origin/dev` @ 328f9bd (post-SPO-33, pre-SPO-34).

- `backend/app/services/daily_analysis.py` — Redis-only write path, cache
  key constructed at line 285 (`f"{DAILY_PICKS_CACHE_KEY}:{date}:tz{tz_offset_minutes}"`)
- `backend/app/services/db.py` — `SCHEMA_SQL` (`CREATE TABLE IF NOT EXISTS`
  blocks), `UNIQUE(date, team)` on line 200
- `backend/app/services/lineup_service.py` — currently NBA-only on this
  base; SPO-34 PR #13 adds the `wnba_lineup_service` and the
  deferred-migration comments cited above
- `backend/app/services/odds_snapshot_service.py` — `UPSERT_LINE_SQL` and
  `INSERT_LOG_SQL`
- `backend/app/services/projection_service.py` — `_build_projections_key`
  returns `f"projections:nba:{date}"` (already league-namespaced)
- `backend/app/services/scheduler.py` — cron registration for
  `daily_analysis_job`, `projection_fetch_*`, `odds_snapshot_*`,
  `csv_download_job`, `lineup_fetch_*` (SPO-34 PR additionally adds the
  WNBA lineup variants)
- `backend/app/services/cache.py:188` — `clear_daily_picks_cache` deletes
  pattern `daily_picks:*`
- `docs/decisions/wnba-rollout/decision_20260513_phase-decomposition.md`
- SPO-34 task summary (lives on the SPO-34 branch / PR #13, not yet on
  `origin/dev`)
