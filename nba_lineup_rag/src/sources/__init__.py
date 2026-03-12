"""
sources - Data Source Fetching Module

This package includes fetchers for various NBA data sources:
- espn_rss: ESPN NBA News RSS Feed
- injuries_pages: ESPN/CBS injury pages
- nba_injury_report: NBA official injury report (if available)

Each fetcher implements the same interface:
- fetch(): Fetch data and return a list of RawItem
- fetch_since(hours): Fetch only items within the specified time range (hours)
"""

from .espn_rss import ESPNRSSFetcher
from .injuries_pages import InjuriesPageFetcher

__all__ = [
    "ESPNRSSFetcher",
    "InjuriesPageFetcher",
]

