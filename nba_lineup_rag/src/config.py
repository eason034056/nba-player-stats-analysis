"""
config.py - Configuration Management Module

This module is responsible for:
1. Loading environment variables from a .env file
2. Providing a unified configuration access interface
3. Defining defaults and validation

Naming Conventions:
- Config: Configuration class, defines all config items using dataclass
- load_config(): Function, loads and returns a config object
- get_config(): Function, gets the global singleton config (prevents redundant loads)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env file
# load_dotenv() will search for a .env file in the current or parent directory
# and load its KEY=VALUE pairs as environment variables
load_dotenv()


@dataclass
class Config:
    """
    Configuration class - uses @dataclass decorator to automatically generate __init__ etc.
    
    @dataclass automatically generates for class attributes:
    - __init__(): initializer
    - __repr__(): string representation
    - __eq__(): equality comparison
    
    Attribute descriptions:
    - project_root: Project root path
    - chroma_dir: ChromaDB persistent storage directory
    - raw_dir: Raw data directory
    - processed_dir: Processed data directory
    """
    
    # Project root directory (Path object for convenient path manipulation)
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    
    # === Data directory config ===
    # os.getenv(key, default) gets from env variable, uses default if not present
    chroma_dir: str = field(
        default_factory=lambda: os.getenv("CHROMA_DIR", "data/chroma")
    )
    raw_dir: str = field(
        default_factory=lambda: os.getenv("RAW_DIR", "data/raw")
    )
    processed_dir: str = field(
        default_factory=lambda: os.getenv("PROCESSED_DIR", "data/processed")
    )
    
    # === Network request config ===
    user_agent: str = field(
        default_factory=lambda: os.getenv("USER_AGENT", "nba-lineup-rag-bot/1.0")
    )
    timezone: str = field(
        default_factory=lambda: os.getenv("TIMEZONE", "America/New_York")
    )
    
    # === Embedding config ===
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "intfloat/e5-large-v2")
    )
    embedding_device: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_DEVICE", "cpu")
    )
    
    # === Chunking config ===
    chunk_size: int = field(
        default_factory=lambda: int(os.getenv("CHUNK_SIZE", "1000"))
    )
    chunk_overlap: int = field(
        default_factory=lambda: int(os.getenv("CHUNK_OVERLAP", "150"))
    )
    
    # === API Keys (optional) ===
    openai_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )
    
    # === Data source URLs ===
    # These are fixed source URLs
    ESPN_RSS_URL: str = "https://www.espn.com/espn/rss/nba/news"
    ESPN_INJURIES_URL: str = "https://www.espn.com/nba/injuries"
    CBS_INJURIES_URL: str = "https://www.cbssports.com/nba/injuries/"
    ESPN_API_BASE: str = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
    
    # === Update frequency (seconds) ===
    RSS_UPDATE_INTERVAL: int = 180      # 3 minutes
    INJURIES_UPDATE_INTERVAL: int = 600  # 10 minutes
    
    def __post_init__(self):
        """
        __post_init__ is a dataclass special method,
        called automatically after __init__, for additional initialization logic
        """
        # Convert relative paths to absolute
        self.chroma_dir = str(self.project_root / self.chroma_dir)
        self.raw_dir = str(self.project_root / self.raw_dir)
        self.processed_dir = str(self.project_root / self.processed_dir)
        
        # Ensure directories exist
        # Path.mkdir(parents=True, exist_ok=True):
        # - parents=True: create parent folders if not exist
        # - exist_ok=True: do not raise error if folder already exists
        Path(self.chroma_dir).mkdir(parents=True, exist_ok=True)
        Path(self.raw_dir).mkdir(parents=True, exist_ok=True)
        Path(self.processed_dir).mkdir(parents=True, exist_ok=True)
    
    def get_raw_subdir(self, source: str) -> Path:
        """
        Get the raw subdirectory for a specific data source
        
        Args:
            source: Source name, e.g. 'espn_rss', 'injuries_pages'
        
        Returns:
            Path: The raw directory path for that source
        
        Example usage:
            config.get_raw_subdir('espn_rss')
            # returns: Path('/path/to/data/raw/espn_rss')
        """
        subdir = Path(self.raw_dir) / source
        subdir.mkdir(parents=True, exist_ok=True)
        return subdir


# Global config instance (singleton pattern)
# Use _config with a leading underscore to indicate module-internal variable
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global config instance (singleton pattern)
    
    Singleton pattern ensures only one Config instance exists for the whole program,
    preventing redundant loading and inconsistency.
    
    Returns:
        Config: Config object
    
    Example usage:
        from src.config import get_config
        config = get_config()
        print(config.chroma_dir)
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


def load_config() -> Config:
    """
    Load a new config instance (force reload)
    
    Unlike get_config(), this function always creates a new instance,
    intended for scenarios where config needs to be reloaded.
    
    Returns:
        Config: new config object
    """
    global _config
    _config = Config()
    return _config


# NBA team abbreviation table
# Used for entity extraction to normalize various team names
# 注意: 包含各種可能的別名，包括網站上可能出現的縮寫形式
NBA_TEAMS = {
    # Eastern Conference
    "ATL": ["Atlanta Hawks", "Hawks", "Atlanta"],
    "BOS": ["Boston Celtics", "Celtics", "Boston"],
    "BKN": ["Brooklyn Nets", "Nets", "Brooklyn"],
    "CHA": ["Charlotte Hornets", "Hornets", "Charlotte"],
    "CHI": ["Chicago Bulls", "Bulls", "Chicago"],
    "CLE": ["Cleveland Cavaliers", "Cavaliers", "Cavs", "Cleveland"],
    "DET": ["Detroit Pistons", "Pistons", "Detroit"],
    "IND": ["Indiana Pacers", "Pacers", "Indiana"],
    "MIA": ["Miami Heat", "Heat", "Miami"],
    "MIL": ["Milwaukee Bucks", "Bucks", "Milwaukee"],
    "NYK": ["New York Knicks", "Knicks", "New York"],
    "ORL": ["Orlando Magic", "Magic", "Orlando"],
    "PHI": ["Philadelphia 76ers", "76ers", "Sixers", "Philadelphia"],
    "TOR": ["Toronto Raptors", "Raptors", "Toronto"],
    "WAS": ["Washington Wizards", "Wizards", "Washington"],
    # Western Conference
    "DAL": ["Dallas Mavericks", "Mavericks", "Mavs", "Dallas"],
    "DEN": ["Denver Nuggets", "Nuggets", "Denver"],
    # Golden State: 網站上可能出現 "Golden St" 或 "Golden St." 等縮寫
    "GSW": ["Golden State Warriors", "Warriors", "Golden State", "Golden St", "Golden St."],
    "HOU": ["Houston Rockets", "Rockets", "Houston"],
    # LA Clippers: 網站上可能用 "L.A." 而不是 "LA"
    "LAC": ["Los Angeles Clippers", "Clippers", "LA Clippers", "L.A. Clippers"],
    # LA Lakers: 網站上可能用 "L.A." 而不是 "LA"
    "LAL": ["Los Angeles Lakers", "Lakers", "LA Lakers", "L.A. Lakers"],
    "MEM": ["Memphis Grizzlies", "Grizzlies", "Memphis"],
    "MIN": ["Minnesota Timberwolves", "Timberwolves", "Wolves", "Minnesota"],
    "NOP": ["New Orleans Pelicans", "Pelicans", "New Orleans"],
    # OKC: 網站上可能用全名 "Oklahoma City" 而不只是 "Thunder"
    "OKC": ["Oklahoma City Thunder", "Thunder", "OKC", "Oklahoma City"],
    "PHX": ["Phoenix Suns", "Suns", "Phoenix"],
    "POR": ["Portland Trail Blazers", "Trail Blazers", "Blazers", "Portland"],
    "SAC": ["Sacramento Kings", "Kings", "Sacramento"],
    "SAS": ["San Antonio Spurs", "Spurs", "San Antonio"],
    "UTA": ["Utah Jazz", "Jazz", "Utah"],
}

# Reverse lookup: alias -> abbreviation
TEAM_ALIAS_TO_CODE = {}
for code, aliases in NBA_TEAMS.items():
    for alias in aliases:
        TEAM_ALIAS_TO_CODE[alias.lower()] = code
    TEAM_ALIAS_TO_CODE[code.lower()] = code


def normalize_team_name(name: str) -> Optional[str]:
    """
    Normalize team names to standard abbreviations
    
    Args:
        name: Any form of team name
    
    Returns:
        str | None: Abbreviation (e.g. 'LAL'), returns None if not found
    
    Example usage:
        normalize_team_name("Lakers")  # returns "LAL"
        normalize_team_name("Los Angeles Lakers")  # returns "LAL"
    """
    return TEAM_ALIAS_TO_CODE.get(name.lower().strip())

