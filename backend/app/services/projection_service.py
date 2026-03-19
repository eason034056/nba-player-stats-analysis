"""
projection_service.py - Hybrid Projection Data Fetch + Storage Service (Plan C + D)

This is the core module for the projection feature, responsible for:
1. Unified entry point for getting projection data (get_projections)
2. Hybrid fetch strategy:
   - Redis hit + fresh → return directly
   - Redis hit + stale → return old data + background refresh
   - Redis miss → fetch synchronously + cache
3. Dual storage: Redis (fast read) + PostgreSQL (historical persistence)
4. Provides historical projection queries (for future backtest use)

Strategy notes:
    The SportsDataIO Projection API is a bulk endpoint,
    One call returns projections for all players for the specified date.
    This means:
    - Scheduled prefetching (3 times daily) is most efficient
    - On-demand API calls are only a fallback on cache miss
    - Background refresh is for when data is stale but users don't need to wait

Dependencies:
    - projection_provider: SportsDataIO API client
    - cache_service: Redis cache
    - db_service: PostgreSQL database

Usage:
    from app.services.projection_service import projection_service
    
    # Get projections for all players for a date (automatic cache handling)
    projections = await projection_service.get_projections("2026-02-08")
    # projections = {"Stephen Curry": {...}, "LeBron James": {...}, ...}
    
    # Force refresh (called by scheduler)
    projections = await projection_service.fetch_and_store("2026-02-08")
"""

import asyncio
import json
import time
from datetime import datetime, timezone, date as date_type
from typing import Dict, Any, Optional, List

from app.services.projection_provider import (
    projection_provider,
    SportsDataProjectionError,
)
from app.services.cache import cache_service
from app.services.db import db_service
from app.settings import settings


# ==================== Redis Key Design ====================

def _build_projections_key(date: str) -> str:
    """
    Construct the Redis cache key for projections
    
    Format: projections:nba:{date}
    Example: projections:nba:2026-02-08
    
    Stores a dict, key is player_name, value is projection data
    """
    return f"projections:nba:{date}"


def _build_projections_meta_key(date: str) -> str:
    """
    Construct the Redis cache key for projection metadata
    
    Format: projections:nba:{date}:meta
    
    Stores a dict like:
    {
        "fetched_at": "2026-02-08T22:00:00Z",  # fetch timestamp
        "player_count": 250                     # number of players
    }
    
    Used to determine data freshness (stale check)
    """
    return f"projections:nba:{date}:meta"


# ==================== PostgreSQL UPSERT SQL ====================

# ON CONFLICT ... DO UPDATE: If the same record (date, player_name, game_id) already exists,
# update it instead of inserting a new one. This prevents duplicates if the scheduler runs multiple times.
UPSERT_PROJECTION_SQL = """
INSERT INTO player_projections (
    date, player_id, player_name, team, position,
    opponent, home_or_away, game_id,
    minutes, points, rebounds, assists, steals, blocked_shots, turnovers,
    field_goals_made, field_goals_attempted,
    three_pointers_made, three_pointers_attempted,
    free_throws_made, free_throws_attempted,
    started, lineup_confirmed, injury_status, injury_body_part,
    opponent_rank, opponent_position_rank,
    draftkings_salary, fanduel_salary,
    fantasy_points_dk, fantasy_points_fd,
    usage_rate_percentage, player_efficiency_rating,
    fetched_at, api_updated_at
) VALUES (
    $1, $2, $3, $4, $5,
    $6, $7, $8,
    $9, $10, $11, $12, $13, $14, $15,
    $16, $17,
    $18, $19,
    $20, $21,
    $22, $23, $24, $25,
    $26, $27,
    $28, $29,
    $30, $31,
    $32, $33,
    $34, $35
)
ON CONFLICT (date, player_name, game_id)
DO UPDATE SET
    team = EXCLUDED.team,
    position = EXCLUDED.position,
    opponent = EXCLUDED.opponent,
    home_or_away = EXCLUDED.home_or_away,
    minutes = EXCLUDED.minutes,
    points = EXCLUDED.points,
    rebounds = EXCLUDED.rebounds,
    assists = EXCLUDED.assists,
    steals = EXCLUDED.steals,
    blocked_shots = EXCLUDED.blocked_shots,
    turnovers = EXCLUDED.turnovers,
    field_goals_made = EXCLUDED.field_goals_made,
    field_goals_attempted = EXCLUDED.field_goals_attempted,
    three_pointers_made = EXCLUDED.three_pointers_made,
    three_pointers_attempted = EXCLUDED.three_pointers_attempted,
    free_throws_made = EXCLUDED.free_throws_made,
    free_throws_attempted = EXCLUDED.free_throws_attempted,
    started = EXCLUDED.started,
    lineup_confirmed = EXCLUDED.lineup_confirmed,
    injury_status = EXCLUDED.injury_status,
    injury_body_part = EXCLUDED.injury_body_part,
    opponent_rank = EXCLUDED.opponent_rank,
    opponent_position_rank = EXCLUDED.opponent_position_rank,
    draftkings_salary = EXCLUDED.draftkings_salary,
    fanduel_salary = EXCLUDED.fanduel_salary,
    fantasy_points_dk = EXCLUDED.fantasy_points_dk,
    fantasy_points_fd = EXCLUDED.fantasy_points_fd,
    usage_rate_percentage = EXCLUDED.usage_rate_percentage,
    player_efficiency_rating = EXCLUDED.player_efficiency_rating,
    fetched_at = EXCLUDED.fetched_at,
    api_updated_at = EXCLUDED.api_updated_at
"""

# Insert fetch log
INSERT_FETCH_LOG_SQL = """
INSERT INTO projection_fetch_logs (date, fetched_at, player_count, status, error_message, duration_ms)
VALUES ($1, $2, $3, $4, $5, $6)
"""


class ProjectionService:
    """
    Hybrid projection data fetch + storage service
    
    Implements three data retrieval paths:
    1. Redis hit + fresh (< max_stale_minutes) → return directly
    2. Redis hit + stale (> max_stale_minutes) → return old data + trigger async background refresh
    3. Redis miss → synchronous API call + store to Redis and PostgreSQL + return
    
    Write path:
    - Each time data is fetched from the API, write to both Redis and PostgreSQL
    - Redis: fast read, has TTL (default 2 hours)
    - PostgreSQL: persistent history, used for backtesting
    """
    
    def __init__(self, max_stale_minutes: int = 120):
        """
        Initialize the service
        
        Args:
            max_stale_minutes: Data freshness expiration threshold (minutes)
                Cache older than this will trigger background refresh
                Default 120 minutes (2 hours), same as Redis TTL
        """
        self.max_stale_minutes = max_stale_minutes
        self._refresh_locks: Dict[str, bool] = {}  # Prevent duplicate refresh for same date
    
    async def get_projections(self, date: str) -> Dict[str, Dict[str, Any]]:
        """
        Unified entry-point for getting projection data
        
        This is the most commonly called method, used by daily_analysis and API endpoints.
        Returns a dict where key is player_name and value is the projection data,
        for efficient lookup by player_name.
        
        Hybrid strategy flow:
        1. Check Redis → if data exists → check staleness
           - fresh → return directly
           - stale → return old data + trigger background refresh
        2. Redis miss → synchronous API call → store to both layers → return
        3. If API also fails → try to read from PostgreSQL → still missing → return empty dict
        
        Args:
            date: game date (YYYY-MM-DD)
        
        Returns:
            Dict[player_name, projection_dict]
            Example: {"Stephen Curry": {"points": 29.3, "minutes": 34.5, ...}}
        """
        cache_key = _build_projections_key(date)
        meta_key = _build_projections_meta_key(date)
        
        # 1. Try to read from Redis
        cached_data = await cache_service.get(cache_key)
        cached_meta = await cache_service.get(meta_key)
        
        if cached_data and isinstance(cached_data, dict):
            # Cache hit! Check staleness
            if cached_meta and self._is_stale(cached_meta):
                # Data is stale → return old data, trigger background refresh
                self._trigger_background_refresh(date)
                print(f"📦 Projection data cache hit (stale, background refresh triggered): {date}")
            else:
                print(f"📦 Projection data cache hit (fresh): {date}")
            
            return cached_data
        
        # 2. Cache miss → synchronous fetch
        print(f"📭 Projection data cache miss: {date}, fetching synchronously...")
        try:
            return await self.fetch_and_store(date)
        except SportsDataProjectionError as e:
            print(f"⚠️ SportsDataIO API call failed: {e}")
            
            # 3. Fallback: try to read from PostgreSQL
            pg_data = await self._read_from_postgres(date)
            if pg_data:
                print(f"📀 Projections loaded from PostgreSQL: {date} ({len(pg_data)} records)")
                # Backfill Redis
                await self._write_to_redis(date, pg_data)
                return pg_data
            
            print(f"❌ Unable to get projections: {date}")
            return {}
        except Exception as e:
            print(f"❌ Unexpected error while getting projections: {e}")
            return {}
    
    async def get_player_projection(
        self, date: str, player_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get projection data for a single player
        
        Internally calls get_projections() for all data,
        then does O(1) key lookup by player_name
        
        Args:
            date: game date (YYYY-MM-DD)
            player_name: player name
        
        Returns:
            projection dict, or None (if not found)
        """
        projections = await self.get_projections(date)
        return projections.get(player_name)
    
    async def fetch_and_store(self, date: str) -> Dict[str, Dict[str, Any]]:
        """
        Force fetch projection data from API and store to both layers
        
        This method is used by:
        1. Scheduler's periodic prefetch
        2. Cache miss synchronous fallback
        3. Manually triggered refresh
        
        Flow:
        1. Call SportsDataIO API
        2. Convert list to dict (by player_name as key)
        3. Write to Redis (cache)
        4. Write to PostgreSQL (persistence)
        5. Log fetch
        
        Args:
            date: game date (YYYY-MM-DD)
        
        Returns:
            Dict[player_name, projection_dict]
        
        Raises:
            SportsDataProjectionError: if API fetch fails
        """
        start_time = time.time()
        error_message = None
        status = "success"
        player_count = 0
        
        try:
            # 1. Call API
            raw_projections = await projection_provider.fetch_projections_by_date(date)
            player_count = len(raw_projections)
            
            # 2. Convert to dict (by player_name)
            # If the same player has more than one row (e.g. multiple games), use the last one
            projections_dict: Dict[str, Dict[str, Any]] = {}
            for proj in raw_projections:
                name = proj.get("player_name")
                if name:
                    projections_dict[name] = proj
            
            # 3. Write to Redis
            await self._write_to_redis(date, projections_dict)
            
            # 4. Write to PostgreSQL (non-blocking, failure does not affect main flow)
            try:
                await self._write_to_postgres(date, raw_projections)
            except Exception as e:
                print(f"⚠️ Failed to write to PostgreSQL (ignored): {e}")
            
            print(f"✅ Projection data fetched and stored: {date} ({player_count} players)")
            return projections_dict
        
        except SportsDataProjectionError as e:
            status = "error"
            error_message = str(e)
            raise
        
        except Exception as e:
            status = "error"
            error_message = str(e)
            raise SportsDataProjectionError(0, f"Unexpected error: {e}")
        
        finally:
            # 5. Log fetch (whether success or fail)
            duration_ms = int((time.time() - start_time) * 1000)
            await self._log_fetch(date, player_count, status, error_message, duration_ms)
    
    async def get_historical_projections(
        self, player_name: str, n_days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Load a player's historical projection data from PostgreSQL
        
        Used for future backtesting: compare projections vs real performance
        
        Args:
            player_name: player name
            n_days: number of days to look back (default 30)
        
        Returns:
            List of historical projections, ordered by date DESC
        """
        if not db_service.is_connected:
            return []
        
        try:
            rows = await db_service.fetch(
                """
                SELECT * FROM player_projections
                WHERE player_name = $1
                  AND date >= CURRENT_DATE - $2
                ORDER BY date DESC
                """,
                player_name,
                n_days,
            )
            return rows
        except Exception as e:
            print(f"⚠️ Failed to read historical projections: {e}")
            return []
    
    # ==================== Internal Methods ====================
    
    def _is_stale(self, meta: Dict[str, Any]) -> bool:
        """
        Determine if cached data is stale
        
        Compare fetched_at in meta to now;
        if older than max_stale_minutes, treat as stale.
        
        Args:
            meta: cache meta information {"fetched_at": "...", "player_count": N}
        
        Returns:
            True if stale
        """
        fetched_at_str = meta.get("fetched_at")
        if not fetched_at_str:
            return True
        
        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
            # Ensure timezone info
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            
            age_minutes = (
                datetime.now(timezone.utc) - fetched_at
            ).total_seconds() / 60
            
            return age_minutes > self.max_stale_minutes
        
        except (ValueError, TypeError):
            return True
    
    def _trigger_background_refresh(self, date: str):
        """
        Trigger asynchronous background refresh
        
        Uses asyncio.create_task() to call API in the background,
        without blocking the current request.
        
        Uses _refresh_locks to prevent duplicate refresh for same date:
        if a refresh job is already running, do not start a new one.
        
        Args:
            date: game date (YYYY-MM-DD)
        """
        # Prevent duplicate refresh
        if self._refresh_locks.get(date):
            return
        
        self._refresh_locks[date] = True
        
        async def _do_refresh():
            try:
                await self.fetch_and_store(date)
                print(f"🔄 Background refresh complete: {date}")
            except Exception as e:
                print(f"⚠️ Background refresh failed: {date} - {e}")
            finally:
                self._refresh_locks.pop(date, None)
        
        # Launch background task
        asyncio.create_task(_do_refresh())
        print(f"🔄 Background refresh triggered: {date}")
    
    async def _write_to_redis(
        self, date: str, projections_dict: Dict[str, Dict[str, Any]]
    ):
        """
        Write projection data to Redis
        
        Writes two keys:
        1. projections:nba:{date} → full projection dictionary
        2. projections:nba:{date}:meta → meta info (fetched_at, player_count)
        
        TTL uses settings.cache_ttl_projections (default 7200s = 2h)
        
        Args:
            date: game date
            projections_dict: projections keyed by player_name
        """
        cache_key = _build_projections_key(date)
        meta_key = _build_projections_meta_key(date)
        ttl = settings.cache_ttl_projections
        
        # Write main projection data
        await cache_service.set(cache_key, projections_dict, ttl=ttl)
        
        # Write metadata
        meta = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "player_count": len(projections_dict),
        }
        await cache_service.set(meta_key, meta, ttl=ttl)
    
    async def _write_to_postgres(self, date: str, projections: List[Dict[str, Any]]):
        """
        Write projection data to PostgreSQL
        
        Uses UPSERT (INSERT ... ON CONFLICT DO UPDATE) for idempotence:
        - If (date, player_name, game_id) does not exist → insert
        - If exists → update all fields
        
        Args:
            date: game date
            projections: normalized list of projections
        """
        if not db_service.is_connected:
            return
        
        now = datetime.now(timezone.utc)
        
        # Prepare batch upsert parameters
        args_list = []
        for proj in projections:
            # Date parsing
            proj_date = proj.get("date")
            if proj_date:
                try:
                    parsed_date = date_type.fromisoformat(proj_date)
                except (ValueError, TypeError):
                    parsed_date = date_type.fromisoformat(date)
            else:
                parsed_date = date_type.fromisoformat(date)
            
            # API updated_at timestamp parsing
            api_updated = proj.get("api_updated_at")
            parsed_api_updated = None
            if api_updated and isinstance(api_updated, str):
                try:
                    parsed_api_updated = datetime.fromisoformat(
                        api_updated.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass
            
            args_list.append((
                parsed_date,                           # $1 date
                proj.get("player_id"),                 # $2 player_id
                proj.get("player_name", ""),           # $3 player_name
                proj.get("team"),                      # $4 team
                proj.get("position"),                  # $5 position
                proj.get("opponent"),                  # $6 opponent
                proj.get("home_or_away"),              # $7 home_or_away
                proj.get("game_id"),                   # $8 game_id
                proj.get("minutes"),                   # $9 minutes
                proj.get("points"),                    # $10 points
                proj.get("rebounds"),                  # $11 rebounds
                proj.get("assists"),                   # $12 assists
                proj.get("steals"),                    # $13 steals
                proj.get("blocked_shots"),             # $14 blocked_shots
                proj.get("turnovers"),                 # $15 turnovers
                proj.get("field_goals_made"),          # $16
                proj.get("field_goals_attempted"),     # $17
                proj.get("three_pointers_made"),       # $18
                proj.get("three_pointers_attempted"),  # $19
                proj.get("free_throws_made"),          # $20
                proj.get("free_throws_attempted"),     # $21
                proj.get("started"),                   # $22
                proj.get("lineup_confirmed"),          # $23
                proj.get("injury_status"),             # $24
                proj.get("injury_body_part"),          # $25
                proj.get("opponent_rank"),             # $26
                proj.get("opponent_position_rank"),    # $27
                proj.get("draftkings_salary"),         # $28
                proj.get("fanduel_salary"),            # $29
                proj.get("fantasy_points_dk"),         # $30
                proj.get("fantasy_points_fd"),         # $31
                proj.get("usage_rate_percentage"),     # $32
                proj.get("player_efficiency_rating"),  # $33
                now,                                  # $34 fetched_at
                parsed_api_updated,                   # $35 api_updated_at
            ))
        
        if args_list:
            try:
                await db_service.executemany(UPSERT_PROJECTION_SQL, args_list)
                print(f"💾 Wrote to PostgreSQL: {len(args_list)} records ({date})")
            except Exception as e:
                print(f"⚠️ Batch write to PostgreSQL failed: {e}")
    
    async def _read_from_postgres(self, date: str) -> Dict[str, Dict[str, Any]]:
        """
        Load projection data from PostgreSQL (fallback for Redis cache miss)
        
        Args:
            date: game date
        
        Returns:
            Dict[player_name, projection_dict]
        """
        if not db_service.is_connected:
            return {}
        
        try:
            parsed_date = date_type.fromisoformat(date)
            rows = await db_service.fetch(
                "SELECT * FROM player_projections WHERE date = $1",
                parsed_date,
            )
            
            result: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                name = row.get("player_name")
                if name:
                    # Convert asyncpg Record to normal dict
                    # Serialize date/datetime objects
                    cleaned = {}
                    for k, v in row.items():
                        if isinstance(v, (datetime, date_type)):
                            cleaned[k] = v.isoformat()
                        else:
                            cleaned[k] = v
                    result[name] = cleaned
            
            return result
        
        except Exception as e:
            print(f"⚠️ PostgreSQL read failed: {e}")
            return {}
    
    async def _log_fetch(
        self,
        date: str,
        player_count: int,
        status: str,
        error_message: Optional[str],
        duration_ms: int,
    ):
        """
        Record fetch log to PostgreSQL
        
        Args:
            date: query date
            player_count: number of players
            status: status (success / error)
            error_message: error message
            duration_ms: duration in ms
        """
        if not db_service.is_connected:
            return
        
        try:
            parsed_date = date_type.fromisoformat(date)
            await db_service.execute(
                INSERT_FETCH_LOG_SQL,
                parsed_date,
                datetime.now(timezone.utc),
                player_count,
                status,
                error_message,
                duration_ms,
            )
        except Exception as e:
            # Logging failure should not affect main flow
            print(f"⚠️ Failed to write fetch log: {e}")


# Create global service instance
projection_service = ProjectionService()
