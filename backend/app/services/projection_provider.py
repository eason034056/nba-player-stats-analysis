"""
projection_provider.py - SportsDataIO Projection Data API Client

Encapsulates calls to the SportsDataIO Projected Player Game Stats API.

API Endpoint:
    GET https://api.sportsdata.io/v3/nba/projections/json/PlayerGameProjectionStatsByDate/{date}

Features:
- Returns projections for "all players" on a given date in a single call (bulk endpoint).
- 1-3 calls per day cover all needs.
- InjuryStatus / LineupStatus fields in Free Trial version may be scrambled.

Main Functions:
- fetch_projections_by_date(): Call the API to get projection data.
- normalize_projection(): Convert API field names to internal format (snake_case).

Dependencies:
- httpx: Asynchronous HTTP client (already in requirements.txt)
- settings: For API key and base URL

Usage:
    from app.services.projection_provider import projection_provider
    
    projections = await projection_provider.fetch_projections_by_date("2026-02-08")
    # projections = [{ "player_name": "Stephen Curry", "points": 29.3, ... }, ...]
"""

import asyncio
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from app.settings import settings


class SportsDataProjectionError(Exception):
    """
    SportsDataIO API Call Error

    Used to encapsulate all SportsDataIO API related errors,
    so higher-level callers can catch them uniformly.

    Attributes:
        status_code: HTTP status code (0 indicates network error)
        message: Error description
    """
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"SportsDataIO Error {status_code}: {message}")


# ==================== Field Name Mapping ====================

# Mapping from SportsDataIO's returned field names (PascalCase) to internal field names (snake_case)
# Only the fields we need are mapped; unnecessary ones are ignored.
FIELD_MAPPING: Dict[str, str] = {
    # Basic Info
    "PlayerID": "player_id",
    "Name": "player_name",
    "Team": "team",
    "Position": "position",
    "GameID": "game_id",
    
    # Match Info
    "Opponent": "opponent",
    "HomeOrAway": "home_or_away",
    "Day": "day",
    "DateTime": "date_time",
    
    # Core Projection Data
    "Minutes": "minutes",
    "Points": "points",
    "Rebounds": "rebounds",
    "OffensiveRebounds": "offensive_rebounds",
    "DefensiveRebounds": "defensive_rebounds",
    "Assists": "assists",
    "Steals": "steals",
    "BlockedShots": "blocked_shots",
    "Turnovers": "turnovers",
    "PersonalFouls": "personal_fouls",
    "PlusMinus": "plus_minus",
    
    # Shooting Data
    "FieldGoalsMade": "field_goals_made",
    "FieldGoalsAttempted": "field_goals_attempted",
    "FieldGoalsPercentage": "field_goals_percentage",
    "TwoPointersMade": "two_pointers_made",
    "TwoPointersAttempted": "two_pointers_attempted",
    "ThreePointersMade": "three_pointers_made",
    "ThreePointersAttempted": "three_pointers_attempted",
    "FreeThrowsMade": "free_throws_made",
    "FreeThrowsAttempted": "free_throws_attempted",
    
    # Lineup and Injury
    "Started": "started",
    "LineupConfirmed": "lineup_confirmed",
    "LineupStatus": "lineup_status",
    "InjuryStatus": "injury_status",
    "InjuryBodyPart": "injury_body_part",
    "InjuryStartDate": "injury_start_date",
    "InjuryNotes": "injury_notes",
    
    # Opponent Difficulty
    "OpponentRank": "opponent_rank",
    "OpponentPositionRank": "opponent_position_rank",
    
    # DFS Salary
    "DraftKingsSalary": "draftkings_salary",
    "FanDuelSalary": "fanduel_salary",
    "YahooSalary": "yahoo_salary",
    "FantasyDataSalary": "fantasydata_salary",
    
    # Fantasy Scores
    "FantasyPointsDraftKings": "fantasy_points_dk",
    "FantasyPointsFanDuel": "fantasy_points_fd",
    "FantasyPointsYahoo": "fantasy_points_yahoo",
    "FantasyPoints": "fantasy_points",
    
    # Advanced Metrics
    "UsageRatePercentage": "usage_rate_percentage",
    "PlayerEfficiencyRating": "player_efficiency_rating",
    "TrueShootingPercentage": "true_shooting_percentage",
    "AssistsPercentage": "assists_percentage",
    "StealsPercentage": "steals_percentage",
    "BlocksPercentage": "blocks_percentage",
    
    # Metadata
    "Updated": "api_updated_at",
    "IsGameOver": "is_game_over",
    "SeasonType": "season_type",
    "Season": "season",
}


def _is_scrambled(value: Any) -> bool:
    """
    Detects scrambled fields in Free Trial.

    SportsDataIO's Free Trial may replace certain fields (such as InjuryStatus)
    with randomly scrambled strings (which look like gibberish).

    Detection logic:
    - String longer than 15 chars and containing a mix of digits and letters -> likely scrambled
    - Common valid values (like "Questionable", "Out", "Probable") are not considered scrambled

    Args:
        value: The value to check

    Returns:
        True if determined to be scrambled
    """
    if not isinstance(value, str):
        return False
    
    # Whitelist of common valid values
    valid_values = {
        "questionable", "out", "doubtful", "probable", "day-to-day",
        "scrambled", "active", "inactive",
        "confirmed", "not confirmed",
    }
    if value.lower().strip() in valid_values:
        return False
    
    # Scrambled values are usually long strings containing mixed letters and digits
    if len(value) > 15:
        has_digit = any(c.isdigit() for c in value)
        has_alpha = any(c.isalpha() for c in value)
        if has_digit and has_alpha:
            return True
    
    return False


class SportsDataProjectionProvider:
    """
    SportsDataIO Projection Data API Client

    Responsible for calling the SportsDataIO Projected Player Game Stats API
    and normalizing returned PascalCase field names to snake_case.

    Features:
    - Uses httpx async HTTP client
    - Built-in retry logic (max_retries=2, exponential backoff)
    - Automatically detects and handles scrambled fields from Free Trial

    Usage:
        provider = SportsDataProjectionProvider()
        projections = await provider.fetch_projections_by_date("2026-02-08")
    """
    
    def __init__(self):
        """
        Initialize API client

        Reads API key and base URL from settings.
        max_retries: Maximum number of retries (not counting the initial try)
        timeout: HTTP request timeout in seconds
        """
        self.api_key = settings.sportsdata_api_key
        self.base_url = settings.sportsdata_base_url
        self.max_retries = 2
        self.timeout = 30.0  # seconds
    
    async def fetch_projections_by_date(self, date: str) -> List[Dict[str, Any]]:
        """
        Fetches all player projections for the specified date from SportsDataIO API.

        API Endpoint:
            GET {base_url}/v3/nba/projections/json/PlayerGameProjectionStatsByDate/{date}

        Authentication:
            Header: Ocp-Apim-Subscription-Key: {api_key}

        Args:
            date: Game date (EST timezone), format YYYY-MM-DD (e.g. "2026-02-08")

        Returns:
            List of normalized projection data, each element is a dict like:
            [
                {
                    "player_id": 20000441,
                    "player_name": "Stephen Curry",
                    "team": "GS",
                    "points": 29.3,
                    "minutes": 34.5,
                    ...
                },
                ...
            ]
        
        Raises:
            SportsDataProjectionError: If the API call fails (even after all retries)
        """
        if not self.api_key:
            raise SportsDataProjectionError(
                0, 
                "SPORTSDATA_API_KEY is not set. Please set SPORTSDATA_API_KEY in your .env."
            )
        
        url = (
            f"{self.base_url}/v3/nba/projections/json/"
            f"PlayerGameProjectionStatsByDate/{date}"
        )
        
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
        }
        
        # Retry logic: exponential backoff (1s, 2s, 4s, ...)
        last_error: Optional[Exception] = None
        
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, headers=headers)
                
                # Check HTTP status code
                if response.status_code == 200:
                    raw_data = response.json()
                    
                    # Empty list returned means no projections for the date
                    if not raw_data:
                        print(f"ℹ️ SportsDataIO: No projections for {date}")
                        return []
                    
                    # Normalize each projection record
                    normalized = [
                        self.normalize_projection(raw)
                        for raw in raw_data
                        if raw.get("Name")  # Exclude invalid records with no name
                    ]
                    
                    print(f"✅ SportsDataIO: Got {len(normalized)} projections ({date})")
                    return normalized
                
                elif response.status_code == 401:
                    raise SportsDataProjectionError(
                        401,
                        "API Key is invalid or expired. Please check your SPORTSDATA_API_KEY setting."
                    )
                
                elif response.status_code == 403:
                    raise SportsDataProjectionError(
                        403,
                        "You do not have permission to access this API. Your subscription may need to be upgraded."
                    )
                
                elif response.status_code == 429:
                    # Rate limit reached, wait before retrying
                    wait_time = 2 ** (attempt + 1)
                    print(f"⚠️ SportsDataIO Rate Limit, waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                    last_error = SportsDataProjectionError(
                        429, "API rate limit exceeded"
                    )
                    continue
                
                else:
                    last_error = SportsDataProjectionError(
                        response.status_code,
                        f"API returned unexpected status code: {response.status_code}"
                    )
            
            except httpx.TimeoutException:
                last_error = SportsDataProjectionError(
                    0, f"API request timed out ({self.timeout}s)"
                )
            except httpx.HTTPError as e:
                last_error = SportsDataProjectionError(
                    0, f"HTTP connection error: {str(e)}"
                )
            except SportsDataProjectionError:
                raise  # 401, 403 and other non-retryable errors are raised directly
            except Exception as e:
                last_error = SportsDataProjectionError(
                    0, f"Unexpected error: {str(e)}"
                )
            
            # Wait before retrying (exponential backoff)
            if attempt < self.max_retries:
                wait_time = 2 ** attempt  # 1s, 2s
                print(f"⚠️ SportsDataIO API call failed (attempt {attempt + 1}/{self.max_retries + 1}), "
                      f"waiting {wait_time}s before retrying...")
                await asyncio.sleep(wait_time)
        
        # All attempts failed
        raise last_error or SportsDataProjectionError(0, "Unknown error")
    
    def normalize_projection(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize SportsDataIO API's PascalCase fields to snake_case

        Logic:
        1. Iterate over the fields defined in FIELD_MAPPING
        2. If the API response contains the field, add it to output using internal name
        3. If the field is a scrambled string (Free Trial), set it as None
        4. Compute derived fields (such as PRA = points + rebounds + assists)

        Args:
            raw: API response dict (PascalCase field names)
        
        Returns:
            Dictionary with normalized field names (snake_case)
        
        Example:
            >>> raw = {"Name": "Stephen Curry", "Points": 29.3, "Minutes": 34}
            >>> normalize_projection(raw)
            {"player_name": "Stephen Curry", "points": 29.3, "minutes": 34, ...}
        """
        result: Dict[str, Any] = {}
        
        for api_field, internal_field in FIELD_MAPPING.items():
            value = raw.get(api_field)
            
            if value is not None:
                # Check if this is a scrambled value due to Free Trial limitations
                if isinstance(value, str) and _is_scrambled(value):
                    result[internal_field] = None
                else:
                    result[internal_field] = value
            else:
                result[internal_field] = None
        
        # Derived combo fields (SPO-16 Phase 1 expansion).
        # 💡 We sum the components on our side because the SportsDataIO
        # projection API exposes the single stats but not the combos. This
        # is safe arithmetic (not vig/odds math) — there is no double-count
        # concern. Compare with The Odds API where combos ship as native
        # markets (player_rebounds_assists etc) and we MUST NOT sum the
        # single-stat odds.
        points = result.get("points") or 0
        rebounds = result.get("rebounds") or 0
        assists = result.get("assists") or 0
        has_p = result.get("points") is not None
        has_r = result.get("rebounds") is not None
        has_a = result.get("assists") is not None

        # PRA (Points + Rebounds + Assists)
        result["pra"] = (
            round(points + rebounds + assists, 2)
            if (has_p or has_r or has_a) else None
        )
        # R + A (combo for player_rebounds_assists market)
        result["r_a"] = (
            round(rebounds + assists, 2)
            if (has_r or has_a) else None
        )
        # P + R (combo for player_points_rebounds market)
        result["p_r"] = (
            round(points + rebounds, 2)
            if (has_p or has_r) else None
        )
        # P + A (combo for player_points_assists market)
        result["p_a"] = (
            round(points + assists, 2)
            if (has_p or has_a) else None
        )
        # ⚠ Intentionally NO `dd` derived field. DD is a multi-variate joint
        # probability (≥2 of {PTS, REB, AST, STL, BLK} ≥ 10) which cannot be
        # estimated from marginal projections without correlation data. Per
        # decision_20260502_phase0-research-first-and-derive-strategy.md §4,
        # DD ML projection is Phase 2 scope. Phase 1 DD tiles render
        # "ML projection N/A (Phase 2)" on the frontend.
        
        # Parse game date (extract YYYY-MM-DD from Day field)
        day_value = result.get("day")
        if day_value and isinstance(day_value, str):
            # API format: 2026-02-08T00:00:00
            result["date"] = day_value[:10]
        else:
            result["date"] = None
        
        return result


# Create a global API client instance
projection_provider = SportsDataProjectionProvider()
