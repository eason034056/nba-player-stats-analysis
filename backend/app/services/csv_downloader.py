"""
csv_downloader.py - CSV Auto-Download Service

Download NBA player game log CSV file from GitHub

Features:
- Download raw CSV file from a specified GitHub repo
- Save to data/nba_player_game_logs.csv
- Automatically reload memory cache after download completes
- Supports error handling and retry

GitHub URL format explanation:
- Original URL: https://github.com/eason034056/nba-player-stats-scraper/blob/main/nba_player_game_logs.csv
- Raw URL:  https://raw.githubusercontent.com/eason034056/nba-player-stats-scraper/main/nba_player_game_logs.csv
- Use raw.githubusercontent.com to directly download the file contents

Cache update strategy:
- Automatically call csv_player_service.reload() to reload memory cache after download
- Optionally: Clear daily analysis cache in Redis (if needed)
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

# Use TYPE_CHECKING to avoid circular imports
# This import only executes during type checking, not at runtime
if TYPE_CHECKING:
    from app.services.csv_player_history import CSVPlayerHistoryService

# GitHub raw file URL
# raw.githubusercontent.com is GitHub's service for direct file access
# Format: https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}
GITHUB_RAW_URL = "https://raw.githubusercontent.com/eason034056/nba-player-stats-scraper/main/nba_player_game_logs.csv"


def _get_csv_save_path() -> Path:
    """
    Get CSV save path
    
    Uses the same path logic as csv_player_history.py for consistency
    
    Priority order:
    1. Environment variable CSV_DATA_PATH
    2. /app/data/nba_player_game_logs.csv (Docker environment)
    3. data/nba_player_game_logs.csv relative to project root (local development)
    
    Returns:
        Path: CSV save path
    """
    import os
    
    # 1. Prefer environment variable
    env_path = os.environ.get("CSV_DATA_PATH")
    if env_path:
        return Path(env_path)
    
    # 2. Docker environment path (/app/data/)
    # This is the path mounted in docker-compose.yml
    docker_path = Path("/app/data/nba_player_game_logs.csv")
    if docker_path.parent.exists():
        return docker_path
    
    # 3. Local development path (relative to project root)
    # Path(__file__): Absolute path of csv_downloader.py
    # .parent (1): services/
    # .parent (2): app/
    # .parent (3): backend/
    # .parent (4): bet/ (project root)
    local_path = Path(__file__).parent.parent.parent.parent / "data" / "nba_player_game_logs.csv"
    return local_path


# CSV save path (calculated by function to ensure consistency with csv_player_history.py)
CSV_SAVE_PATH = _get_csv_save_path()


class CSVDownloaderService:
    """
    CSV Download Service
    
    Responsible for downloading the latest NBA player game log CSV from GitHub
    
    Usage:
        downloader = CSVDownloaderService()
        success = await downloader.download()
    
    Attributes:
        url (str): The GitHub raw file URL
        save_path (Path): Local path to save CSV
    """
    
    def __init__(
        self, 
        url: str = GITHUB_RAW_URL, 
        save_path: Path = CSV_SAVE_PATH
    ):
        """
        Initialize the downloader service
        
        Args:
            url: The GitHub raw file URL, default is the GITHUB_RAW_URL constant
            save_path: The local path to store the CSV, default is CSV_SAVE_PATH constant
        
        Why use default arguments?
        - Convenient to pass different URLs or paths for testing
        - For production use, you don't need to pass arguments, just use defaults
        """
        self.url = url
        self.save_path = save_path
    
    async def download(self) -> bool:
        """
        Download CSV file
        
        Download CSV from GitHub and save it locally
        
        Returns:
            bool: Returns True if download succeeded, False if failed
        
        Steps:
        1. Use httpx to send a GET request to GitHub raw URL
        2. Check if HTTP status code indicates success (2xx)
        3. Ensure the target directory exists
        4. Write content to local file
        
        Why async?
        - httpx.AsyncClient is an asynchronous HTTP client
        - Large file downloads won't block other tasks
        - Compatible with FastAPI's async architecture
        """
        print(f"\n📥 Starting CSV download...")
        print(f"   Source: {self.url}")
        print(f"   Target: {self.save_path}")
        
        try:
            # httpx.AsyncClient: Asynchronous HTTP client
            # async with: ensures connection closes after completion
            # timeout=60.0: 60 seconds timeout since CSV files might be large
            async with httpx.AsyncClient(timeout=60.0) as client:
                # client.get(): Send GET request
                # await: Wait for asynchronous result
                response = await client.get(self.url)
                
                # raise_for_status(): Check HTTP status code
                # Raises HTTPStatusError if status isn't 2xx (success)
                # e.g., 404 Not Found, 500 Internal Server Error
                response.raise_for_status()
                
                # response.text: Get response as string
                # This is the full CSV content
                content = response.text
                
                # Ensure target directory exists
                # self.save_path.parent: parent directory (data/)
                # mkdir(): create directory
                #   parents=True: create any intermediate directories as needed
                #   exist_ok=True: do not raise exception if directory exists
                self.save_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Write file
                # write_text(): Path method to directly write text content
                # encoding='utf-8': Use UTF-8 encoding to support special characters
                self.save_path.write_text(content, encoding='utf-8')
                
                # Get file size for logging
                # stat(): get file status info
                # st_size: file size in bytes
                file_size = self.save_path.stat().st_size
                file_size_mb = file_size / (1024 * 1024)  # Bytes to MB
                
                print(f"✅ CSV downloaded successfully!")
                print(f"   File size: {file_size_mb:.2f} MB")
                print(f"   Download time: {datetime.now(timezone.utc).isoformat()}")
                
                # Reload memory cache
                # So subsequent frontend requests get the newest CSV data
                await self._reload_csv_cache()
                
                return True
                
        except httpx.HTTPStatusError as e:
            # HTTP status code error
            # e.response.status_code: offending status code
            print(f"❌ HTTP error: {e.response.status_code}")
            print(f"   URL: {self.url}")
            return False
            
        except httpx.RequestError as e:
            # Network error (connection timeout, DNS failure, etc.)
            print(f"❌ Network request error: {e}")
            return False
            
        except Exception as e:
            # Other errors (e.g., file write failure)
            print(f"❌ Download failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_last_modified(self) -> str | None:
        """
        Get last modified time for local CSV
        
        Returns:
            ISO formatted last modified time string, or None (if file not present)
        
        Use cases:
        - Check if local file needs updating
        - Show data update time in API responses
        """
        if not self.save_path.exists():
            return None
        
        # stat().st_mtime: file last modified Unix timestamp
        # fromtimestamp(): convert timestamp to datetime object
        # isoformat(): convert to ISO 8601 string
        mtime = self.save_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, timezone.utc).isoformat()
    
    async def _reload_csv_cache(self) -> None:
        """
        Reload CSV memory cache and clear related Redis cache
        
        After downloading a new CSV:
        1. Reload memory cache (csv_player_service)
        2. Clear daily analysis cache in Redis (daily_picks:*)
        
        This ensures API requests use the latest data
        
        Why delayed import?
        - To avoid circular imports (csv_downloader -> csv_player_history -> csv_downloader)
        - Only import when actually needed
        """
        # ===== 1. Reload memory cache =====
        try:
            # Delayed import to avoid circular dependency
            # csv_player_service is a singleton at module scope
            from app.services.csv_player_history import csv_player_service
            
            # Reload CSV to memory
            # reload() clears old cache and reads CSV again
            csv_player_service.reload()
            print("🔄 Memory cache updated")
            
        except Exception as e:
            # Failure to update cache should not affect download success
            print(f"⚠️ Failed to reload memory cache: {e}")
            import traceback
            traceback.print_exc()
        
        # ===== 2. Clear Redis cache =====
        try:
            from app.services.cache import cache_service
            
            # Clear daily picks cache
            # The next /api/daily-picks request will re-analyze
            deleted = await cache_service.clear_daily_picks_cache()
            
            if deleted > 0:
                print(f"🗑️ Cleared {deleted} Redis cache entries")
            else:
                print("ℹ️ No Redis cache needs clearing")
            
            print("✅ All caches updated, API requests will use latest data")
            
        except Exception as e:
            # Redis cache clearing failure does not affect main function
            print(f"⚠️ Failed to clear Redis cache: {e}")


# Create global service instance
# Other modules can just import csv_downloader_service directly
# No need to instantiate every time
csv_downloader_service = CSVDownloaderService()
