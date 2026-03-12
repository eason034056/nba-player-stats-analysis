"""
extract_entities.py - Entity Extraction Module

This module is responsible for:
1. Extracting team names from text
2. Extracting player names from text
3. Extracting date information from text
4. Identifying injury-related status keywords

The purpose of entity extraction is to add structured metadata to a chunk,
so that it can be precisely filtered during queries.

Naming conventions:
- EntityExtractor: Entity extraction class
- extract_teams(): Extract teams
- extract_players(): Extract players
- extract_dates(): Extract dates
- extract_injury_status(): Extract injury statuses
"""

import re
from datetime import datetime
from typing import List, Set, Optional, Dict, Any
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from src.config import get_config, NBA_TEAMS, TEAM_ALIAS_TO_CODE, normalize_team_name
from src.logging_utils import get_logger

logger = get_logger(__name__)


# TODO: Common player name list (can be extended or loaded from external sources)
# Here are some well-known players as examples
KNOWN_PLAYERS = [
    # Lakers
    "LeBron James", "Anthony Davis", "D'Angelo Russell", "Austin Reaves",
    # Celtics
    "Jayson Tatum", "Jaylen Brown", "Derrick White", "Kristaps Porzingis",
    # Warriors
    "Stephen Curry", "Klay Thompson", "Draymond Green", "Andrew Wiggins",
    # Nuggets
    "Nikola Jokic", "Jamal Murray", "Michael Porter Jr.", "Aaron Gordon",
    # Bucks
    "Giannis Antetokounmpo", "Damian Lillard", "Khris Middleton", "Brook Lopez",
    # 76ers
    "Joel Embiid", "Tyrese Maxey", "Tobias Harris", "De'Anthony Melton",
    # Suns
    "Kevin Durant", "Devin Booker", "Bradley Beal", "Jusuf Nurkic",
    # Heat
    "Jimmy Butler", "Bam Adebayo", "Tyler Herro", "Terry Rozier",
    # Mavericks
    "Luka Doncic", "Kyrie Irving", "Tim Hardaway Jr.", "Dereck Lively II",
    # Timberwolves
    "Anthony Edwards", "Karl-Anthony Towns", "Rudy Gobert", "Mike Conley",
    # Thunder
    "Shai Gilgeous-Alexander", "Chet Holmgren", "Jalen Williams", "Josh Giddey",
    # Kings
    "De'Aaron Fox", "Domantas Sabonis", "Keegan Murray", "Harrison Barnes",
    # Cavaliers
    "Donovan Mitchell", "Darius Garland", "Evan Mobley", "Jarrett Allen",
    # Knicks
    "Jalen Brunson", "Julius Randle", "RJ Barrett", "Josh Hart",
    # Clippers
    "Kawhi Leonard", "Paul George", "Russell Westbrook", "James Harden",
    # Grizzlies
    "Ja Morant", "Desmond Bane", "Jaren Jackson Jr.", "Marcus Smart",
    # Pelicans
    "Zion Williamson", "Brandon Ingram", "CJ McCollum", "Trey Murphy III",
]

# Injury status keywords
INJURY_STATUS_KEYWORDS = {
    "out": ["out", "ruled out", "will not play", "sidelined", "inactive"],
    "questionable": ["questionable", "game-time decision", "uncertain"],
    "doubtful": ["doubtful", "unlikely to play"],
    "probable": ["probable", "likely to play", "expected to play"],
    "day-to-day": ["day-to-day", "day to day", "d2d"],
    "available": ["available", "will play", "active", "cleared"],
}

# Date patterns
DATE_PATTERNS = [
    # 2026-01-27
    r"\b(\d{4}-\d{2}-\d{2})\b",
    # January 27, 2026
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b",
    # Jan 27, 2026
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{1,2}),?\s+(\d{4})\b",
    # 01/27/2026 or 1/27/26
    r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b",
    # tonight, tomorrow, Monday, etc.
    r"\b(tonight|tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
]


@dataclass
class ExtractedEntities:
    """
    Extracted entity result

    Field descriptions:
    - teams: List of team codes (e.g. ['LAL', 'BOS'])
    - players: List of player names
    - dates: List of dates (ISO format)
    - injury_statuses: List of injury statuses
    - raw_dates: Original date strings
    """
    teams: List[str]
    players: List[str]
    dates: List[str]
    injury_statuses: List[str]
    raw_dates: List[str]

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "teams": self.teams,
            "players": self.players,
            "dates": self.dates,
            "injury_statuses": self.injury_statuses,
        }


class EntityExtractor:
    """
    Entity extractor

    Extracts structured information from text: teams, players, dates, injury statuses

    Usage example:
        extractor = EntityExtractor()
        entities = extractor.extract(
            "LeBron James is questionable for tonight's game against the Celtics"
        )
        print(entities.teams)    # ['LAL', 'BOS'] (if context available)
        print(entities.players)  # ['LeBron James']
        print(entities.injury_statuses)  # ['questionable']
    """

    def __init__(self, player_list: List[str] = None):
        """
        Initialize extractor

        Args:
            player_list: List of players (for fuzzy matching)
        """
        self.player_list = player_list or KNOWN_PLAYERS

        # Build lowercase mapping of player names
        self.player_lower_map = {p.lower(): p for p in self.player_list}

    def extract(self, text: str) -> ExtractedEntities:
        """
        Extract all entities from text

        Args:
            text: Text to analyze

        Returns:
            ExtractedEntities: Extraction result
        """
        if not text:
            return ExtractedEntities(
                teams=[], players=[], dates=[],
                injury_statuses=[], raw_dates=[]
            )

        teams = self.extract_teams(text)
        players = self.extract_players(text)
        dates, raw_dates = self.extract_dates(text)
        statuses = self.extract_injury_status(text)

        return ExtractedEntities(
            teams=list(teams),
            players=list(players),
            dates=dates,
            injury_statuses=list(statuses),
            raw_dates=raw_dates,
        )

    def extract_teams(self, text: str) -> Set[str]:
        """
        Extract teams from text

        Using multiple approaches:
        1. Directly match team full names
        2. Match team abbreviations
        3. Match aliases

        Args:
            text: Text to analyze

        Returns:
            Set[str]: Set of team codes (e.g. {'LAL', 'BOS'})
        """
        found_teams = set()
        text_lower = text.lower()

        # Search all possible team names
        for code, aliases in NBA_TEAMS.items():
            # Check code (e.g. LAL)
            # Use word boundary to avoid false matches
            if re.search(rf"\b{code}\b", text, re.IGNORECASE):
                found_teams.add(code)
                continue

            # Check aliases
            for alias in aliases:
                if alias.lower() in text_lower:
                    found_teams.add(code)
                    break

        return found_teams

    def extract_players(self, text: str) -> Set[str]:
        """
        Extract player names from text

        Methods used:
        1. Exact match to known player list
        2. Fuzzy matching to handle spelling variations

        Args:
            text: Text to analyze

        Returns:
            Set[str]: Set of player names
        """
        found_players = set()
        text_lower = text.lower()

        # Exact matching
        for player in self.player_list:
            if player.lower() in text_lower:
                found_players.add(player)

        # Fuzzy matching (to handle spelling variants)
        # Uses rapidfuzz for fuzzy matching
        # This can find variants such as "Lebron" (without correct capitalization) or "LeBron"
        words = text.split()
        for i in range(len(words)):
            # Try combinations of 2-3 consecutive words (player names are usually 2-3 words)
            for length in [2, 3]:
                if i + length <= len(words):
                    candidate = " ".join(words[i:i+length])

                    # Use rapidfuzz to find best match
                    # process.extractOne returns (match result, score, index)
                    result = process.extractOne(
                        candidate,
                        self.player_list,
                        scorer=fuzz.ratio,
                        score_cutoff=85,  # At least 85% similarity
                    )

                    if result:
                        found_players.add(result[0])

        return found_players

    def extract_dates(self, text: str) -> tuple[List[str], List[str]]:
        """
        Extract dates from text

        Args:
            text: Text to analyze

        Returns:
            tuple: (List of ISO format dates, list of raw date strings)
        """
        dates = []
        raw_dates = []

        # ISO format (2026-01-27)
        for match in re.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", text):
            date_str = match.group(1)
            raw_dates.append(date_str)
            dates.append(date_str)

        # Full month name (January 27, 2026)
        months = {
            "january": "01", "february": "02", "march": "03", "april": "04",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "september": "09", "october": "10", "november": "11", "december": "12",
        }
        pattern = r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            month_name = match.group(1).lower()
            day = match.group(2).zfill(2)
            year = match.group(3)
            if month_name in months:
                date_str = f"{year}-{months[month_name]}-{day}"
                raw_dates.append(match.group(0))
                dates.append(date_str)

        # Abbreviated month (Jan 27, 2026)
        months_short = {
            "jan": "01", "feb": "02", "mar": "03", "apr": "04",
            "may": "05", "jun": "06", "jul": "07", "aug": "08",
            "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        }
        pattern = r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+(\d{1,2}),?\s+(\d{4})\b"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            month_name = match.group(1).lower()
            day = match.group(2).zfill(2)
            year = match.group(3)
            if month_name in months_short:
                date_str = f"{year}-{months_short[month_name]}-{day}"
                raw_dates.append(match.group(0))
                dates.append(date_str)

        # Remove duplicates while preserving order
        seen = set()
        unique_dates = []
        for d in dates:
            if d not in seen:
                seen.add(d)
                unique_dates.append(d)

        return unique_dates, raw_dates

    def extract_injury_status(self, text: str) -> Set[str]:
        """
        Extract injury status from text

        Args:
            text: Text to analyze

        Returns:
            Set[str]: Set of statuses (e.g. {'questionable', 'out'})
        """
        found_statuses = set()
        text_lower = text.lower()

        for status, keywords in INJURY_STATUS_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    found_statuses.add(status)
                    break

        return found_statuses

    def extract_to_metadata(self, text: str) -> Dict[str, Any]:
        """
        Extract entities and convert to metadata format

        Directly returns a dictionary that can be added to chunk metadata

        Args:
            text: Text to analyze

        Returns:
            dict: Dictionary directly usable as metadata

        Usage example:
            metadata = extractor.extract_to_metadata(text)
            chunk.metadata.update(metadata)
        """
        entities = self.extract(text)

        result = {}

        if entities.teams:
            result["team"] = entities.teams[0]  # Main team
            if len(entities.teams) > 1:
                result["opponent"] = entities.teams[1]
            result["teams_mentioned"] = entities.teams

        if entities.players:
            result["player_names"] = entities.players

        if entities.dates:
            result["game_date"] = entities.dates[0]  # Most recent date

        if entities.injury_statuses:
            result["injury_status"] = entities.injury_statuses
            result["topic"] = "injury"

        return result


def extract_entities(text: str, player_list: List[str] = None) -> ExtractedEntities:
    """
    Convenience function: extract entities

    Args:
        text: Text to analyze
        player_list: List of players

    Returns:
        ExtractedEntities: Extraction result

    Usage example:
        entities = extract_entities(article_text)
        print(f"Mentioned teams: {entities.teams}")
        print(f"Mentioned players: {entities.players}")
    """
    extractor = EntityExtractor(player_list)
    return extractor.extract(text)

