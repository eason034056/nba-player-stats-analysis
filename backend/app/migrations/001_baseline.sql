-- 001_baseline.sql
-- Body is SCHEMA_SQL from app/services/db.py, copied so a blank database
-- matches what db_service.init() creates on origin/dev.
-- Every statement is IF NOT EXISTS or a guarded ALTER, so applying this
-- file on a database that already ran SCHEMA_SQL does not change it.
-- odds_line_snapshots.line stays nullable and stays in the legacy unique key.

-- One lock for this whole script. A simple-query batch runs as one
-- transaction, so two processes starting together take turns instead of
-- deadlocking on the same ALTER TABLE.
SELECT pg_advisory_xact_lock(1170117);

-- Player Projections Table
-- Retained so an existing database is not dropped on boot.
-- No module reads or writes this table. A later change drops it
-- after a grep shows the name only in this schema block.
-- Each row is (date, player_name, game_id) unique
CREATE TABLE IF NOT EXISTS player_projections (
    id SERIAL PRIMARY KEY,

    -- Game date (EST)
    date DATE NOT NULL,

    -- Player basic info
    player_id INTEGER,               -- Vendor player id, unused
    player_name TEXT NOT NULL,       -- Player name
    team TEXT,                       -- Team abbreviation (e.g., GS, LAL)
    position TEXT,                   -- Position (PG/SG/SF/PF/C)

    -- Matchup info
    opponent TEXT,                   -- Opponent team abbreviation
    home_or_away TEXT,               -- HOME or AWAY
    game_id INTEGER,                 -- Vendor game id, unused

    -- Core projection stats (available in Free Trial)
    minutes REAL,                    -- Projected minutes
    points REAL,                     -- Projected points
    rebounds REAL,                   -- Projected rebounds
    assists REAL,                    -- Projected assists
    steals REAL,                     -- Projected steals
    blocked_shots REAL,              -- Projected blocks
    turnovers REAL,                  -- Projected turnovers
    field_goals_made REAL,           -- Field goals made
    field_goals_attempted REAL,      -- Field goals attempted
    three_pointers_made REAL,        -- 3P made
    three_pointers_attempted REAL,   -- 3P attempted
    free_throws_made REAL,           -- Free throws made
    free_throws_attempted REAL,      -- Free throws attempted

    -- Starting status and injuries (Free Trial may be scrambled)
    started INTEGER,                 -- Started (1=Yes, 0=No)
    lineup_confirmed BOOLEAN,        -- Starting lineup confirmed
    injury_status TEXT,              -- Injury status
    injury_body_part TEXT,           -- Body part injured

    -- Opponent difficulty
    opponent_rank INTEGER,           -- Opponent total defense ranking (1-30)
    opponent_position_rank INTEGER,  -- Opponent defense ranking vs. this position

    -- DFS Salary
    draftkings_salary REAL,          -- DraftKings DFS salary
    fanduel_salary REAL,             -- FanDuel DFS salary

    -- Fantasy Points
    fantasy_points_dk REAL,          -- DraftKings fantasy points
    fantasy_points_fd REAL,          -- FanDuel fantasy points

    -- Advanced metrics
    usage_rate_percentage REAL,      -- Usage rate %
    player_efficiency_rating REAL,   -- Player efficiency rating (PER)

    -- Metadata
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- Data fetch time
    api_updated_at TIMESTAMPTZ,                    -- Last update time from API

    -- Uniqueness: one row per (date, player_name, game_id)
    UNIQUE(date, player_name, game_id)
);

-- Indexes for commonly used queries
CREATE INDEX IF NOT EXISTS idx_proj_date ON player_projections(date);
CREATE INDEX IF NOT EXISTS idx_proj_player ON player_projections(player_name);
CREATE INDEX IF NOT EXISTS idx_proj_date_player ON player_projections(date, player_name);

-- Projection Fetch Logs Table
-- Retained with player_projections. Nothing writes a row.
CREATE TABLE IF NOT EXISTS projection_fetch_logs (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,                              -- Game date queried
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- Fetch time
    player_count INTEGER,                            -- Num of players returned
    status TEXT,                                     -- Status (success / error)
    error_message TEXT,                              -- Error message (if any)
    duration_ms INTEGER                              -- Duration (ms)
);


-- ==================== Odds Line Snapshots (Line Movement Tracking) ====================

-- Odds Line Snapshots Table
-- Stores no-vig calculation results for each bookmaker on every scheduled snapshot
-- Each row = 1 snapshot time + 1 game + 1 player + 1 market + 1 bookmaker + 1 line
-- A book that posts a ladder keeps the main total and every alternate.
-- Used to track line movement over time (opening → closing lines)
CREATE TABLE IF NOT EXISTS odds_line_snapshots (
    id SERIAL PRIMARY KEY,

    -- Snapshot time: when this data was captured
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Game date (US slate date)
    date DATE NOT NULL,

    -- Game info (from The Odds API)
    event_id TEXT NOT NULL,              -- The Odds API event ID
    home_team TEXT,                      -- Home team
    away_team TEXT,                      -- Away team

    -- Player & market
    player_name TEXT NOT NULL,           -- Player name (e.g., "Stephen Curry")
    market TEXT NOT NULL,                -- Market type (player_points, player_rebounds, etc.)

    -- Bookmaker
    bookmaker TEXT NOT NULL,             -- Bookmaker key (e.g., "draftkings")

    -- Odds & original lines
    line NUMERIC,                        -- Line threshold (e.g., 24.5) - this value may shift
    over_odds INTEGER,                   -- Over American odds (e.g., -110)
    under_odds INTEGER,                  -- Under American odds (e.g., -110)

    -- No-vig calculations
    vig NUMERIC,                         -- Vig (e.g., 0.0476 for 4.76%)
    over_fair_prob NUMERIC,              -- Over fair prob (e.g., 0.5000)
    under_fair_prob NUMERIC,             -- Under fair prob (e.g., 0.5000)

    -- Unique: one row per posted total. The line is part of the key so an
    -- alternate does not replace the main total for the same book.
    CONSTRAINT odds_line_snapshots_book_line_key
        UNIQUE (snapshot_at, event_id, player_name, market, bookmaker, line)
);

-- Indexes for common query patterns
-- Query all snapshots for a player and market on a date (line movement)
CREATE INDEX IF NOT EXISTS idx_ols_player_market ON odds_line_snapshots(player_name, market, date);
-- Query all snapshots for a game and market
CREATE INDEX IF NOT EXISTS idx_ols_event ON odds_line_snapshots(event_id, market);
-- Query by date
CREATE INDEX IF NOT EXISTS idx_ols_date ON odds_line_snapshots(date);
-- Query by snapshot time
CREATE INDEX IF NOT EXISTS idx_ols_snapshot ON odds_line_snapshots(snapshot_at);


-- Odds Snapshot Logs Table
-- Records a summary of each snapshot execution (success/failure, duration, count)
CREATE TABLE IF NOT EXISTS odds_snapshot_logs (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,                               -- Game date for snapshot
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- Snapshot execution time
    event_count INTEGER,                              -- Number of games processed
    total_lines INTEGER,                              -- Total odds lines written
    status TEXT,                                      -- Status (success / error)
    error_message TEXT,                               -- Error message (if any)
    duration_ms INTEGER                               -- Duration (ms)
);


-- ==================== Free Starting Lineup Consensus ====================

CREATE TABLE IF NOT EXISTS team_lineup_snapshots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    team TEXT NOT NULL,
    opponent TEXT,
    home_or_away TEXT,
    status TEXT NOT NULL,
    starters JSONB NOT NULL DEFAULT '[]'::jsonb,
    bench_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_disagreement BOOLEAN NOT NULL DEFAULT FALSE,
    confidence TEXT NOT NULL,
    updated_at TIMESTAMPTZ,
    source_snapshots JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(date, team)
);

CREATE INDEX IF NOT EXISTS idx_tls_date ON team_lineup_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_tls_team ON team_lineup_snapshots(team);
CREATE INDEX IF NOT EXISTS idx_tls_date_team ON team_lineup_snapshots(date, team);

CREATE TABLE IF NOT EXISTS lineup_fetch_logs (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    team_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    source_statuses JSONB NOT NULL DEFAULT '{}'::jsonb
);


-- ==================== SPO-35: WNBA league-aware migration =================
--
-- Strictly additive. See:
--   docs/decisions/wnba-rollout/decision_20260514_db-schema-audit.md
--
-- Closes the SPO-34 deferred follow-up that left WNBA lineups Redis-only
-- because team_lineup_snapshots' UNIQUE(date, team) collided on shared
-- codes (ATL/CHI/DAL/IND/MIN/PHO/SEA/WAS/GS).
--
-- The replacement UNIQUE constraint (date, team, league) is strictly more
-- permissive than the old one — every previously-legal NBA row remains
-- legal, and WNBA rows that previously could not coexist now can. PK is
-- untouched, no column drop, no type change → not Gate 2.
--
-- Backfill: pre-existing NBA rows get league='nba' via the column DEFAULT.
-- New WNBA writes must pass league='wnba' (lineup_service handles this).
--
-- All statements are idempotent — safe to apply more than once.
-- 001_baseline.sql is this text. init() does not execute it.

ALTER TABLE team_lineup_snapshots
    ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'nba';

ALTER TABLE team_lineup_snapshots
    DROP CONSTRAINT IF EXISTS team_lineup_snapshots_date_team_key;

-- 💡 ADD CONSTRAINT IF NOT EXISTS for table-level constraints isn't
-- portable across PG versions; gate via pg_constraint introspection in a
-- DO block so re-running init() doesn't error on the second startup.
DO $spo35_unique$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'team_lineup_snapshots'::regclass
          AND conname = 'team_lineup_snapshots_date_team_league_key'
    ) THEN
        ALTER TABLE team_lineup_snapshots
            ADD CONSTRAINT team_lineup_snapshots_date_team_league_key
            UNIQUE (date, team, league);
    END IF;
END
$spo35_unique$;

-- Optional additive — per-league observability (owner explicitly opted
-- in via the request_confirmation rejection reason: "Include observability
-- tables (lineup_fetch_logs, odds_snapshot_logs) in this PR").
ALTER TABLE lineup_fetch_logs
    ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'nba';

ALTER TABLE odds_snapshot_logs
    ADD COLUMN IF NOT EXISTS league TEXT NOT NULL DEFAULT 'nba';

-- ==================== SPO-117: keep alternate lines ====================
--
-- The original unique key was (snapshot_at, event_id, player_name, market,
-- bookmaker). A second total for that book updated the same row, so the
-- last alternate replaced the main line. Adding ``line`` makes the key
-- wider: every row that already satisfied the old key still satisfies the
-- new one, and two different totals can now coexist. No row is rewritten
-- or deleted. CREATE TABLE above names the new key for a fresh database.
-- This block is for a database created before that change. It drops every
-- unique constraint on this table that does not include ``line``, and every
-- unique index that does not include ``line``. The primary key is left
-- alone. A hand-built UNIQUE INDEX is not a constraint, so the index loop
-- is what removes it. The named key is added when it is missing. Running
-- the block again does nothing.

DO $spo117_line_unique$
DECLARE
    old_name text;
    old_index record;
BEGIN
    FOR old_name IN
        SELECT con.conname
        FROM pg_constraint con
        WHERE con.conrelid = 'odds_line_snapshots'::regclass
          AND con.contype = 'u'
          AND NOT EXISTS (
              SELECT 1
              FROM unnest(con.conkey) AS col(attnum)
              JOIN pg_attribute att
                ON att.attrelid = con.conrelid
               AND att.attnum = col.attnum
              WHERE att.attname = 'line'
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE odds_line_snapshots DROP CONSTRAINT %I',
            old_name
        );
    END LOOP;

    FOR old_index IN
        SELECT n.nspname AS schema_name, ic.relname AS index_name
        FROM pg_index ix
        JOIN pg_class ic ON ic.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = ic.relnamespace
        WHERE ix.indrelid = 'odds_line_snapshots'::regclass
          AND ix.indisunique
          AND NOT ix.indisprimary
          AND NOT EXISTS (
              SELECT 1
              FROM unnest(ix.indkey) AS col(attnum)
              JOIN pg_attribute att
                ON att.attrelid = ix.indrelid
               AND att.attnum = col.attnum
              WHERE att.attname = 'line'
          )
    LOOP
        EXECUTE format(
            'DROP INDEX IF EXISTS %I.%I',
            old_index.schema_name,
            old_index.index_name
        );
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'odds_line_snapshots'::regclass
          AND conname = 'odds_line_snapshots_book_line_key'
    ) THEN
        ALTER TABLE odds_line_snapshots
            ADD CONSTRAINT odds_line_snapshots_book_line_key
            UNIQUE (snapshot_at, event_id, player_name, market, bookmaker, line);
    END IF;
END
$spo117_line_unique$;
