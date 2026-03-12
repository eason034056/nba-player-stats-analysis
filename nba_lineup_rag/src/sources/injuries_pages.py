"""
injuries_pages.py - Injury Page Scraping Module

This module is responsible for:
1. Scraping injury data from ESPN Injuries page
2. Scraping injury data from CBS Sports Injuries page
3. Parsing HTML tables and extracting player injury status
4. Converting the data to a standard format

Data Sources:
- ESPN: https://www.espn.com/nba/injuries
- CBS: https://www.cbssports.com/nba/injuries/

Naming Explanation:
- InjuriesPageFetcher: Injury page fetcher class
- PlayerInjury: Data class for a single player's injury info
- fetch_espn(): Fetch ESPN injuries page
- fetch_cbs(): Fetch CBS injuries page
"""

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict

import requests
from bs4 import BeautifulSoup

from src.config import get_config, normalize_team_name
from src.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class PlayerInjury:
    """
    Single player injury information

    The @dataclass decorator automatically generates:
    - __init__(): Initialization based on fields
    - __repr__(): String representation for debugging
    - __eq__(): Equality comparison

    Field Description:
    - team: Team abbreviation (e.g., 'LAL')
    - player_name: Player name
    - position: Position (e.g., 'PG', 'SF')
    - status: Injury status (e.g., 'Out', 'Questionable', 'Day-To-Day')
    - injury: Injury description
    - notes: Additional notes
    """
    team: str
    player_name: str
    position: Optional[str] = None
    status: Optional[str] = None
    injury: Optional[str] = None
    notes: Optional[str] = None

    def to_chunk_text(self) -> str:
        """
        Convert injury info to text format for embedding

        This format is intended for vector search and contains all key info

        Returns:
            str: Formatted text
        """
        lines = [
            f"TEAM: {self.team}",
            f"PLAYER: {self.player_name}",
        ]
        if self.position:
            lines.append(f"POSITION: {self.position}")
        if self.status:
            lines.append(f"STATUS: {self.status}")
        if self.injury:
            lines.append(f"INJURY: {self.injury}")
        if self.notes:
            lines.append(f"NOTES: {self.notes}")

        return "\n".join(lines)


def compute_hash(text: str) -> str:
    """Calculate SHA256 hash of text"""
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class InjuriesPageFetcher:
    """
    Injury page fetcher

    Supports multiple injury data sources:
    1. ESPN NBA Injuries
    2. CBS Sports NBA Injuries

    Usage example:
        fetcher = InjuriesPageFetcher()
        injuries = fetcher.fetch_all()
        fetcher.save_raw(injuries)
    """

    def __init__(self):
        """Initialize fetcher"""
        self.config = get_config()

        # Create HTTP session
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        self.timeout = 30

    def fetch_all(self) -> Dict[str, List[PlayerInjury]]:
        """
        Fetch injury data from all sources

        Returns:
            dict: {source_name: list of injuries}
        """
        results = {}

        # Fetch ESPN
        espn_injuries = self.fetch_espn()
        if espn_injuries:
            results["espn"] = espn_injuries

        # Fetch CBS
        cbs_injuries = self.fetch_cbs()
        if cbs_injuries:
            results["cbs"] = cbs_injuries

        return results

    def fetch_espn(self) -> List[PlayerInjury]:
        """
        Fetch ESPN injuries page

        ESPN injuries page structure:
        - Each team has a ResponsiveTable section
        - Table__Title is INSIDE the ResponsiveTable (as a child element)
        - Table columns: Name, POS, Date, Status

        Returns:
            List[PlayerInjury]: Parsed injury data
        """
        url = self.config.ESPN_INJURIES_URL
        logger.info(f"Fetching ESPN injuries page: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            # Use lxml parser (faster and more stable)
            soup = BeautifulSoup(response.text, "lxml")

            injuries = []

            # ESPN injuries page structure:
            # Find all team blocks (ResponsiveTable contains both title and table)
            team_sections = soup.find_all("div", class_="ResponsiveTable")

            for section in team_sections:
                # FIXED: Table__Title is a CHILD of ResponsiveTable, not a previous sibling
                # Use find() instead of find_previous() to get the title within this section
                team_header = section.find("div", class_="Table__Title")
                team_name = ""
                if team_header:
                    team_name = team_header.get_text(strip=True)

                # Normalize team name to code
                team_code = normalize_team_name(team_name) or team_name

                if not team_code:
                    logger.warning(f"ESPN: Could not find team name for section")
                    continue

                # Find table content
                table = section.find("table") or section.find("tbody")
                if not table:
                    continue

                # Parse each row
                rows = section.find_all("tr")
                for row in rows:
                    # Skip header row
                    if row.find("th"):
                        continue

                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        injury = self._parse_espn_row(cells, team_code)
                        if injury:
                            injuries.append(injury)

            logger.info(f"ESPN: Found {len(injuries)} injury records")
            return injuries

        except Exception as e:
            logger.error(f"Failed to fetch ESPN injuries page: {e}")
            return []

    def _parse_espn_row(self, cells: list, team_code: str) -> Optional[PlayerInjury]:
        """
        Parse a single row in ESPN injury table

        Args:
            cells: List of table cells (td elements)
            team_code: Team code

        Returns:
            PlayerInjury | None: Parsed injury info
        """
        try:
            # Usually: Name | POS | Date | Status
            player_name = cells[0].get_text(strip=True) if len(cells) > 0 else ""

            if not player_name:
                return None

            position = cells[1].get_text(strip=True) if len(cells) > 1 else None
            injury = cells[2].get_text(strip=True) if len(cells) > 2 else None
            status = cells[3].get_text(strip=True) if len(cells) > 3 else None

            return PlayerInjury(
                team=team_code,
                player_name=player_name,
                position=position,
                status=status,
                injury=injury,
            )
        except Exception as e:
            logger.debug(f"Failed to parse ESPN row: {e}")
            return None

    def fetch_cbs(self) -> List[PlayerInjury]:
        """
        Fetch CBS Sports injuries page

        CBS injuries page structure:
        - Each team has a TableBaseWrapper section
        - TeamName span is INSIDE the TableBaseWrapper (as a child element)
        - Table columns: Name | Position | Updated | Injury | Status

        Returns:
            List[PlayerInjury]: Parsed injury data
        """
        url = self.config.CBS_INJURIES_URL
        logger.info(f"Fetching CBS injuries page: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            injuries = []

            # CBS injuries page structure
            # Find all team blocks
            team_sections = soup.find_all("div", class_="TableBaseWrapper")

            # If not found, try alternate structure
            if not team_sections:
                team_sections = soup.find_all("table")

            for section in team_sections:
                # FIXED: TeamName is a CHILD of TableBaseWrapper, not a previous sibling
                # Use find() to get the team name within this section
                team_span = section.find("span", class_="TeamName")
                team_name = ""
                if team_span:
                    team_name = team_span.get_text(strip=True)

                # Normalize team name to code
                team_code = normalize_team_name(team_name) or team_name

                if not team_code:
                    logger.warning(f"CBS: Could not find team name for section")
                    continue

                # Parse table rows
                rows = section.find_all("tr")
                for row in rows:
                    if row.find("th"):
                        continue

                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        injury = self._parse_cbs_row(cells, team_code)
                        if injury:
                            injuries.append(injury)

            logger.info(f"CBS: Found {len(injuries)} injury records")
            return injuries

        except Exception as e:
            logger.error(f"Failed to fetch CBS injuries page: {e}")
            return []

    def _parse_cbs_row(self, cells: list, team_code: str) -> Optional[PlayerInjury]:
        """
        Parse a single row in CBS injury table

        Args:
            cells: Table cell list
            team_code: Team code

        Returns:
            PlayerInjury | None: Parsed injury info
        """
        try:
            player_name = cells[0].get_text(strip=True) if len(cells) > 0 else ""

            if not player_name:
                return None

            # CBS columns are: Name | Position | Updated | Injury | Status
            position = cells[1].get_text(strip=True) if len(cells) > 1 else None
            injury = cells[3].get_text(strip=True) if len(cells) > 3 else None
            status = cells[4].get_text(strip=True) if len(cells) > 4 else None

            return PlayerInjury(
                team=team_code,
                player_name=player_name,
                position=position,
                status=status,
                injury=injury,
            )
        except Exception as e:
            logger.debug(f"Failed to parse CBS row: {e}")
            return None

    def save_raw(self, injuries_by_source: Dict[str, List[PlayerInjury]]) -> int:
        """
        Save injury data to the raw directory

        Each fetch generates a complete snapshot
        with a timestamp, making it easy to track status changes

        Args:
            injuries_by_source: {source: list of injuries}

        Returns:
            int: Total number saved
        """
        raw_dir = self.config.get_raw_subdir("injuries_pages")

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        total_count = 0

        for source, injuries in injuries_by_source.items():
            # Compile raw data
            raw_items = []
            for injury in injuries:
                raw_text = injury.to_chunk_text()
                raw_item = {
                    "source": f"injuries_pages_{source}",
                    "source_url": (
                        self.config.ESPN_INJURIES_URL if source == "espn"
                        else self.config.CBS_INJURIES_URL
                    ),
                    "published_at": now.isoformat(),
                    "fetched_at": now.isoformat(),
                    "title": f"{injury.team} - {injury.player_name} Injury Update",
                    "author": None,
                    "raw_text": raw_text,
                    "raw_hash": compute_hash(raw_text),
                    # Additional structured fields
                    "player_data": asdict(injury),
                }
                raw_items.append(raw_item)

            # Save as JSONL
            raw_file = raw_dir / f"injuries_{source}_{timestamp}.jsonl"
            with open(raw_file, "w", encoding="utf-8") as f:
                for item in raw_items:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")

            logger.info(f"Saved {source} injury data: {len(raw_items)} records -> {raw_file}")
            total_count += len(raw_items)

        return total_count


def fetch_injuries(sources: List[str] = None) -> Dict[str, List[PlayerInjury]]:
    """
    Convenience function: fetch injury data

    Args:
        sources: List of sources to fetch from. None means all.
                 Options: ['espn', 'cbs']

    Returns:
        Dict[str, List[PlayerInjury]]: {source: list of injuries}

    Usage example:
        from src.sources.injuries_pages import fetch_injuries

        # Fetch all sources
        all_injuries = fetch_injuries()

        # Fetch only ESPN
        espn_injuries = fetch_injuries(sources=['espn'])
    """
    fetcher = InjuriesPageFetcher()

    if sources is None:
        return fetcher.fetch_all()

    results = {}
    if "espn" in sources:
        results["espn"] = fetcher.fetch_espn()
    if "cbs" in sources:
        results["cbs"] = fetcher.fetch_cbs()

    return results
