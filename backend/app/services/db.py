"""
db.py - PostgreSQL Database Service

Provides asynchronous PostgreSQL connection pool and query functionality using asyncpg.
Responsible for:
1. Managing the database connection pool
2. Automatically creating tables (schema migration) when the application starts
3. Providing helper methods for queries (execute, fetch, fetchrow)

asyncpg is a high-performance async PostgreSQL driver, does not rely on an ORM,
and uses direct SQL queries, consistent with the project's existing lightweight and direct style.

Usage:
    from app.services.db import db_service

    # Initialize at startup
    await db_service.init()

    # Query
    rows = await db_service.fetch("SELECT * FROM player_projections WHERE date = $1", date)

    # Cleanup when closing
    await db_service.close()
"""

import asyncpg
from typing import Optional, Any, List
from app.settings import settings


# ==================== Table Creation SQL ====================

SCHEMA_SQL = """
-- Player Projections Table
-- Stores daily player game projections from SportsDataIO
-- Each row is (date, player_name, game_id) unique
CREATE TABLE IF NOT EXISTS player_projections (
    id SERIAL PRIMARY KEY,

    -- Game date (EST)
    date DATE NOT NULL,

    -- Player basic info
    player_id INTEGER,               -- SportsDataIO player ID
    player_name TEXT NOT NULL,       -- Player name
    team TEXT,                       -- Team abbreviation (e.g., GS, LAL)
    position TEXT,                   -- Position (PG/SG/SF/PF/C)

    -- Matchup info
    opponent TEXT,                   -- Opponent team abbreviation
    home_or_away TEXT,               -- HOME or AWAY
    game_id INTEGER,                 -- SportsDataIO game ID

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
-- Records each API call status for monitoring and debugging
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
-- Each row = 1 snapshot time + 1 game + 1 player + 1 market + 1 bookmaker
-- Used to track line movement over time (opening → closing lines)
CREATE TABLE IF NOT EXISTS odds_line_snapshots (
    id SERIAL PRIMARY KEY,

    -- Snapshot time: when this data was captured
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Game date (EST, same as player_projections)
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

    -- Unique: snapshot time + game + player + market + bookmaker must be unique
    UNIQUE(snapshot_at, event_id, player_name, market, bookmaker)
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
"""


class DatabaseService:
    """
    PostgreSQL Database Service Class

    Uses an asyncpg connection pool to manage PostgreSQL database connections.
    Benefits of a connection pool:
    - Avoid creating a new connection on every query (connection creation is expensive)
    - Automatically manages connection reuse and cleanup
    - Limits the maximum number of concurrent connections to prevent DB overload

    Usage:
        db = DatabaseService()
        await db.init()          # Create connection pool + tables
        rows = await db.fetch("SELECT * FROM table WHERE id = $1", 123)
        await db.close()         # Close the pool
    """

    def __init__(self):
        """
        Initialize the database service

        _pool is the asyncpg connection pool, lazily initialized in init()
        """
        self._pool: Optional[asyncpg.Pool] = None

    async def init(self):
        """
        Initialize the database connection pool and create tables

        asyncpg.create_pool: creates the connection pool
        - dsn: PostgreSQL URI string
        - min_size: minimum pool size (default 2)
        - max_size: maximum pool size (default 10)

        After creation, immediately executes SCHEMA_SQL to ensure tables exist
        Uses IF NOT EXISTS for idempotency (won't error if run repeatedly)
        """
        try:
            self._pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=2,
                max_size=10
            )

            # Run schema migration (create tables)
            async with self._pool.acquire() as conn:
                await conn.execute(SCHEMA_SQL)

            print("✅ PostgreSQL connection pool established, tables are ready")

        except Exception as e:
            print(f"⚠️ PostgreSQL initialization failed: {e}")
            print("   Projections will run without persistent storage (Redis only)")
            self._pool = None

    async def close(self):
        """
        Close the database connection pool

        Call at application shutdown to release all connections
        """
        if self._pool:
            await self._pool.close()
            self._pool = None
            print("✅ PostgreSQL connection pool closed")

    @property
    def is_connected(self) -> bool:
        """Check if the connection pool is established and available"""
        return self._pool is not None

    async def execute(self, query: str, *args) -> str:
        """
        Execute SQL that does not return rows (INSERT, UPDATE, DELETE)

        Args:
            query: SQL string with $1, $2, ... as parameter placeholders
            *args: Query parameters (ordered to match $1, $2, ...)

        Returns:
            Execution status string (e.g., "INSERT 0 1")

        Example:
            await db.execute(
                "INSERT INTO logs (date, status) VALUES ($1, $2)",
                "2026-02-08", "success"
            )
        """
        if not self._pool:
            raise RuntimeError("Database not initialized, call init() first")

        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> List[dict]:
        """
        Run a query and return multiple rows

        asyncpg returns Record objects, which are converted to dicts for convenience

        Args:
            query: SQL query string
            *args: Query parameters

        Returns:
            List of result rows (each as dict)

        Example:
            rows = await db.fetch(
                "SELECT * FROM player_projections WHERE date = $1",
                datetime.date(2026, 2, 8)
            )
        """
        if not self._pool:
            raise RuntimeError("Database not initialized, call init() first")

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def fetchrow(self, query: str, *args) -> Optional[dict]:
        """
        Run a query and return a single row

        Args:
            query: SQL string
            *args: Query parameters

        Returns:
            One row as a dict, or None if no result

        Example:
            row = await db.fetchrow(
                "SELECT * FROM player_projections WHERE date = $1 AND player_name = $2",
                datetime.date(2026, 2, 8), "Stephen Curry"
            )
        """
        if not self._pool:
            raise RuntimeError("Database not initialized, call init() first")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def executemany(self, query: str, args_list: List[tuple]) -> None:
        """
        Batch execute SQL (for bulk INSERT/UPDATE)

        executemany is much more efficient than looped execute,
        because it does one prepare + many bind/executes

        Args:
            query: SQL string
            args_list: a list of parameter tuples (one for each execution)

        Example:
            await db.executemany(
                "INSERT INTO table (col1, col2) VALUES ($1, $2)",
                [("a", 1), ("b", 2), ("c", 3)]
            )
        """
        if not self._pool:
            raise RuntimeError("Database not initialized, call init() first")

        async with self._pool.acquire() as conn:
            await conn.executemany(query, args_list)


# Global database service instance
db_service = DatabaseService()
