"""
espn_rss.py - ESPN NBA RSS Feed fetch module

This module is responsible for:
1. Fetching NBA news from ESPN RSS Feed
2. Parsing the RSS XML format
3. Fetching the full text of articles (not just summaries)
4. Converting data into RawItem format

Data source:
- RSS Feed: https://www.espn.com/espn/rss/nba/news

Naming conventions:
- ESPNRSSFetcher: The ESPN RSS fetcher class
- RawItem: Raw data item (TypedDict)
- fetch(): Main method for fetching
- _parse_article(): Private method for parsing article body (underscore prefix means internal use)
"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, TypedDict
from dataclasses import dataclass

import feedparser
import requests
from bs4 import BeautifulSoup
from readability import Document

from src.config import get_config
from src.logging_utils import get_logger, IngestionStats

# Get logger
logger = get_logger(__name__)


class RawItem(TypedDict):
    """
    Type definition for a raw data item

    TypedDict is a Python type hinting tool,
    allowing IDEs to provide autocompletion and type checking,
    but at runtime it's still just a dict.

    Field descriptions:
    - source: Source identifier (e.g. 'espn_rss')
    - source_url: Original article URL
    - published_at: Publication time (ISO format)
    - fetched_at: Fetch time (ISO format)
    - title: Article title
    - author: Author (optional)
    - raw_text: Full article text
    - raw_hash: SHA256 hash of content (for deduplication)
    """
    source: str
    source_url: str
    published_at: str
    fetched_at: str
    title: str
    author: Optional[str]
    raw_text: str
    raw_hash: str


def compute_hash(text: str) -> str:
    """
    Compute the SHA256 hash of text

    Used for deduplication: identical content yields same hash,
    whereas different content should almost never yield the same hash.

    Args:
        text: The text to hash

    Returns:
        str: 64-character hexadecimal hash string

    Example:
        hash_value = compute_hash("Hello World")
        # Returns something like "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e"
    """
    # 1. Normalize text (remove extra whitespace)
    normalized = " ".join(text.split())
    # 2. Encode as bytes (hashlib needs bytes, not str)
    # 3. Calculate SHA256 and convert to hex string
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class ESPNRSSFetcher:
    """
    ESPN NBA RSS Feed Fetcher

    This class is responsible for:
    1. Fetching the news list from ESPN RSS
    2. Fetching the full text for each news article
    3. Converting the results to standard format and saving them

    Usage example:
        fetcher = ESPNRSSFetcher()
        items = fetcher.fetch()  # Fetch all news
        items = fetcher.fetch_since(hours=6)  # Only fetch news from last 6 hours
    """
    
    def __init__(self):
        """
        Initialize the fetcher

        Get settings from config, and establish HTTP session
        """
        self.config = get_config()
        self.rss_url = self.config.ESPN_RSS_URL
        
        # Using requests.Session allows connection reuse and increases efficiency
        # And it allows us to set headers globally
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        
        # Set request timeout (seconds)
        self.timeout = 30
    
    def fetch(self, max_items: int = 50) -> List[RawItem]:
        """
        Fetch all news from ESPN RSS

        Args:
            max_items: Maximum number of articles to fetch (avoid fetching too many at once)

        Returns:
            List[RawItem]: List of fetched raw data items

        Workflow:
        1. Request the RSS feed
        2. Parse the XML to get the articles list
        3. Fetch the full text of each article
        4. Assemble as RawItem
        """
        logger.info(f"Starting to fetch ESPN RSS: {self.rss_url}")
        
        try:
            # feedparser.parse() automatically handles RSS/Atom formats
            # It can take a URL or raw XML string
            feed = feedparser.parse(self.rss_url)
            
            if feed.bozo:
                # bozo True means there was a problem parsing
                # bozo_exception contains error details
                logger.warning(f"RSS parsing had warnings: {feed.bozo_exception}")
            
            items: List[RawItem] = []
            entries = feed.entries[:max_items]  # Limit amount
            
            logger.info(f"Found {len(entries)} articles")
            
            for entry in entries:
                try:
                    item = self._process_entry(entry)
                    if item:
                        items.append(item)
                except Exception as e:
                    logger.error(f"Failed to process article: {entry.get('link', 'unknown')} - {e}")
            
            logger.info(f"Successfully fetched {len(items)} articles")
            return items
            
        except Exception as e:
            logger.error(f"Failed to fetch RSS: {e}")
            return []
    
    def fetch_since(self, hours: int = 6) -> List[RawItem]:
        """
        Only fetch articles published within the specified time window

        Args:
            hours: Time range (in hours)

        Returns:
            List[RawItem]: Articles matching the time criteria
        """
        # Calculate the time threshold
        # datetime.now(timezone.utc) gets current UTC time
        # timedelta(hours=hours) creates a time difference
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        logger.info(f"Fetching articles within last {hours} hours (after {threshold.isoformat()})")
        
        all_items = self.fetch()
        
        # Filter: keep only articles published after threshold
        filtered = []
        for item in all_items:
            try:
                pub_time = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
                if pub_time >= threshold:
                    filtered.append(item)
            except Exception as e:
                logger.warning(f"Failed to parse time: {item.get('published_at')} - {e}")
                # If time can't be parsed, also keep
                filtered.append(item)
        
        logger.info(f"{len(filtered)} articles remain after filtering")
        return filtered
    
    def _process_entry(self, entry: dict) -> Optional[RawItem]:
        """
        Process a single RSS entry

        Args:
            entry: The entry object parsed by feedparser

        Returns:
            RawItem | None: The processed data, or None on failure

        Sample entry structure:
        {
            'title': 'Article Title',
            'link': 'https://...',
            'published': 'Mon, 27 Jan 2026 10:30:00 GMT',
            'summary': 'Summary...',
            'author': 'Author Name'
        }
        """
        link = entry.get("link", "")
        title = entry.get("title", "")
        
        if not link:
            logger.warning("Article is missing link, skipping")
            return None
        
        # === Parse publication time ===
        published_at = self._parse_time(entry)
        
        # === Fetch article body ===
        # Don't use RSS summary; fetch full article content
        raw_text = self._fetch_article_content(link)
        
        if not raw_text:
            # If fetching the body failed, fall back to summary
            raw_text = entry.get("summary", "")
            logger.warning(f"Using summary as fallback for article body: {link}")
        
        # Calculate hash of the content (for deduplication)
        raw_hash = compute_hash(raw_text)
        
        # === Assemble RawItem ===
        return RawItem(
            source="espn_rss",
            source_url=link,
            published_at=published_at,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            title=title,
            author=entry.get("author"),
            raw_text=raw_text,
            raw_hash=raw_hash,
        )
    
    def _parse_time(self, entry: dict) -> str:
        """
        Parse publication time of an RSS entry

        feedparser attempts to parse various time formats,
        and provides published_parsed (struct_time)

        Returns:
            str: ISO format time string
        """
        # published_parsed is a time.struct_time
        if entry.get("published_parsed"):
            from time import mktime
            # mktime converts struct_time to timestamp
            # fromtimestamp converts timestamp to datetime
            dt = datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc)
            return dt.isoformat()
        
        # Fallback: return original string value or current time
        return entry.get("published", datetime.now(timezone.utc).isoformat())
    
    def _fetch_article_content(self, url: str) -> Optional[str]:
        """
        Fetch the full text of the article

        Uses the readability-lxml package to extract main content;
        it will automatically remove navigation, ads, and other non-content elements.

        Args:
            url: Article URL

        Returns:
            str | None: Extracted plain text content
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()  # Throws if not 2xx
            
            # Document is the main class of readability-lxml
            # It analyzes the HTML structure to find the main content block
            doc = Document(response.text)
            
            # summary() returns the simplified HTML
            content_html = doc.summary()
            
            # Use BeautifulSoup to extract plain text
            soup = BeautifulSoup(content_html, "lxml")
            
            # get_text() extracts all text
            # separator=' ' separates different element texts with space
            # strip=True removes leading/trailing whitespace
            text = soup.get_text(separator=" ", strip=True)
            
            # Remove extra whitespace
            text = re.sub(r"\s+", " ", text).strip()
            
            return text
            
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch article: {url} - {e}")
            return None
        except Exception as e:
            logger.warning(f"Failed to parse article: {url} - {e}")
            return None
    
    def save_raw(self, items: List[RawItem]) -> int:
        """
        Save fetched data to the raw directory

        Uses JSONL (JSON Lines) format: one JSON object per line.
        This format is convenient for appending and for line-by-line reading.

        Args:
            items: List of RawItem to save

        Returns:
            int: Number of new records added (duplicates excluded)
        """
        raw_dir = self.config.get_raw_subdir("espn_rss")
        
        # Filename includes the date
        today = datetime.now().strftime("%Y%m%d")
        raw_file = raw_dir / f"espn_rss_{today}.jsonl"
        
        # Read existing hashes (for deduplication)
        existing_hashes = set()
        if raw_file.exists():
            with open(raw_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        existing_hashes.add(data.get("raw_hash", ""))
                    except json.JSONDecodeError:
                        pass
        
        # Write new data (append mode)
        new_count = 0
        with open(raw_file, "a", encoding="utf-8") as f:
            for item in items:
                if item["raw_hash"] not in existing_hashes:
                    # json.dumps converts dict to JSON string
                    # ensure_ascii=False allows non-ASCII chars (e.g., Chinese)
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    existing_hashes.add(item["raw_hash"])
                    new_count += 1
        
        logger.info(f"Save finished: {new_count} added, {len(items) - new_count} skipped (duplicates)")
        return new_count


def fetch_espn_rss(since_hours: Optional[int] = None) -> List[RawItem]:
    """
    Convenience function: fetch ESPN RSS

    This is a module-level convenience function
    so you don't have to instantiate ESPNRSSFetcher every time

    Args:
        since_hours: Only fetch from how many hours ago; None means fetch all

    Returns:
        List[RawItem]: Fetched data

    Usage example:
        from src.sources.espn_rss import fetch_espn_rss
        items = fetch_espn_rss(since_hours=6)
    """
    fetcher = ESPNRSSFetcher()
    if since_hours:
        return fetcher.fetch_since(since_hours)
    return fetcher.fetch()

