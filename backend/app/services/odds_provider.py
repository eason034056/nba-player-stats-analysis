"""
odds_provider.py - Abstract Odds Provider Interface

Defines the abstract interface for interaction with external odds APIs (Abstract Base Class).
Using an interface design has several benefits:
1. Easy to swap different odds API providers
2. Easy unit testing (mocking)
3. Conforms to Dependency Inversion Principle (DIP)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime


class OddsProvider(ABC):
    """
    Abstract base class for odds providers.

    Defines all methods that an odds API must implement.
    ABC (Abstract Base Class): Python's abstract class decorator.
    abstractmethod: Marks methods that must be implemented by subclasses.
    """
    
    @abstractmethod
    async def get_events(
        self, 
        sport: str, 
        regions: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the list of events.

        Args:
            sport: Type of sport (e.g., "basketball_nba")
            regions: Region code (e.g., "us")
            date_from: Start date (optional)
            date_to: End date (optional)

        Returns:
            List of events, each as a dictionary

        Raises:
            OddsAPIError: When an API call fails
        """
        pass


@dataclass(frozen=True)
class QuotaUsage:
    """
    Odds API quota usage information.

    - remaining: Number of remaining allowed requests
    - used: Number of requests already used
    - last: Number used in the most recent request
    """

    remaining: Optional[int] = None
    used: Optional[int] = None
    last: Optional[int] = None

    @property
    def total(self) -> Optional[int]:
        if self.remaining is None or self.used is None:
            return None
        return self.remaining + self.used

    @property
    def remaining_ratio(self) -> Optional[float]:
        total = self.total
        if total in (None, 0) or self.remaining is None:
            return None
        return self.remaining / total
    
    @abstractmethod
    async def get_event_odds(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        odds_format: str = "american",
        bookmakers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Retrieve the odds data for a single event.
        
        Args:
            sport: Type of sport
            event_id: Event ID
            regions: Region code
            markets: Betting market type (e.g., "player_points")
            odds_format: Odds format ("american" or "decimal")
            bookmakers: List of specified bookmaker(s) (optional, None for all)
        
        Returns:
            Odds data as a dictionary
        
        Raises:
            OddsAPIError: When an API call fails
        """
        pass


class OddsAPIError(Exception):
    """
    Odds API error exception class.

    Used to encapsulate all errors related to external odds APIs.
    Contains status code and message for debugging and error handling.

    Attributes:
        status_code: HTTP status code (e.g., 401, 404, 500)
        message: Error message
    """
    
    def __init__(self, message: str, status_code: Optional[int] = None):
        """
        Initialize OddsAPIError

        Args:
            message: Error message
            status_code: HTTP status code (optional)
        """
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """
        String representation

        Status code is included if present.
        """
        if self.status_code:
            return f"[{self.status_code}] {self.message}"
        return self.message
