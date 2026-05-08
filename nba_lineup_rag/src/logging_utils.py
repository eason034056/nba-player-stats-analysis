"""
logging_utils.py - Logging Utilities Module

This module provides:
1. Unified logging format setup
2. Simultaneous output to both console and file
3. A convenient logger acquisition interface

Naming conventions:
- setup_logger(): Set up and return a logger instance
- get_logger(): Retrieve an already-configured logger (or create it if not exists)
- LogLevel: Enum for logging levels

Python logging module log levels:
- DEBUG: Detailed information, typically for diagnosing problems
- INFO: Confirmation that things are working as expected
- WARNING: An indication that something unexpected happened, but the program is still running
- ERROR: More serious problem; the program cannot perform some functionality
- CRITICAL: Severe error indicating the program may be unable to continue running
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from enum import Enum


class LogLevel(Enum):
    """
    Log Level Enum

    Advantages of using Enum over plain strings:
    1. Avoids spelling mistakes
    2. IDE auto-complete support
    3. Type checking
    """
    DEBUG = logging.DEBUG      # 10
    INFO = logging.INFO        # 20
    WARNING = logging.WARNING  # 30
    ERROR = logging.ERROR      # 40
    CRITICAL = logging.CRITICAL  # 50


def setup_logger(
    name: str,
    level: LogLevel = LogLevel.INFO,
    log_dir: Optional[str] = None,
    log_to_file: bool = True,
    log_to_console: bool = True
) -> logging.Logger:
    """
    Set up and return a logger instance

    Args:
        name: logger name, typically use __name__ (module name)
        level: logging level, use LogLevel enum
        log_dir: log file directory, default is logs/
        log_to_file: whether to output to file
        log_to_console: whether to output to terminal

    Returns:
        logging.Logger: configured logger instance

    Example usage:
        logger = setup_logger(__name__)
        logger.info("This is an info message")
        logger.error("This is an error message")

    Log format explanation:
        %(asctime)s - timestamp
        %(name)s - logger name
        %(levelname)s - log level
        %(filename)s:%(lineno)d - filename and line number
        %(message)s - log message
    """
    # Get or create logger
    # logging.getLogger(name) returns a logger with the specified name;
    # if it doesn't exist, a new one is created, else returns the existing one
    logger = logging.getLogger(name)

    # Set logging level (.value gets the enum's numerical value)
    logger.setLevel(level.value)

    # Avoid adding handlers multiple times (prevents duplicate logs)
    if logger.handlers:
        return logger

    # Define log formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(name)-20s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # === Console Handler (output to terminal) ===
    if log_to_console:
        # By default, StreamHandler outputs to sys.stderr
        # Here we change it to sys.stdout
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level.value)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # === File Handler (output to file) ===
    if log_to_file:
        # Determine log directory
        if log_dir is None:
            # Default: logs/ under project root
            log_dir = Path(__file__).parent.parent / "logs"
        else:
            log_dir = Path(log_dir)

        # Ensure directory exists
        log_dir.mkdir(parents=True, exist_ok=True)

        # Log file name includes date for easier management
        log_file = log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"

        # FileHandler writes logs to file
        # encoding='utf-8' ensures correct display of international characters
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level.value)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# Cache for created loggers to avoid redundant logger setup
_loggers: dict = {}


def get_logger(name: str, level: LogLevel = LogLevel.INFO) -> logging.Logger:
    """
    Get logger (with caching)

    This is a convenience function that caches created loggers,
    ensuring that only one logger exists for each name.

    Args:
        name: logger name
        level: logging level

    Returns:
        logging.Logger: logger instance

    Example usage:
        # In any module
        from src.logging_utils import get_logger
        logger = get_logger(__name__)
        logger.info("Processing...")
    """
    if name not in _loggers:
        _loggers[name] = setup_logger(name, level)
    return _loggers[name]


class IngestionStats:
    """
    Ingestion Statistics Class

    Used to track statistics during data ingestion,
    including counts for new, skipped, and error records.

    Example usage:
        stats = IngestionStats("espn_rss")
        stats.add_new()
        stats.add_skipped()
        print(stats.summary())
    """

    def __init__(self, source: str):
        """
        Initialize statistics object

        Args:
            source: source name
        """
        self.source = source
        self.new_count = 0       # Count of new records
        self.skipped_count = 0   # Count of skipped records (duplicates)
        self.error_count = 0     # Count of errors
        self.chunks_count = 0    # Count of generated chunks
        self.embed_time = 0.0    # Embedding time in seconds
        self.start_time = datetime.now()

    def add_new(self, count: int = 1):
        """Record new records"""
        self.new_count += count

    def add_skipped(self, count: int = 1):
        """Record skipped records"""
        self.skipped_count += count

    def add_error(self, count: int = 1):
        """Record errors"""
        self.error_count += count

    def add_chunks(self, count: int):
        """Record chunk count"""
        self.chunks_count += count

    def set_embed_time(self, seconds: float):
        """Set embedding time"""
        self.embed_time = seconds

    def summary(self) -> dict:
        """
        Generate statistics summary

        Returns:
            dict: dictionary containing all statistical data
        """
        elapsed = (datetime.now() - self.start_time).total_seconds()
        return {
            "source": self.source,
            "new": self.new_count,
            "skipped": self.skipped_count,
            "errors": self.error_count,
            "chunks": self.chunks_count,
            "embed_time_sec": round(self.embed_time, 2),
            "total_time_sec": round(elapsed, 2),
            "success_rate": round(
                self.new_count / max(1, self.new_count + self.error_count) * 100, 1
            )
        }

    def log_summary(self, logger: logging.Logger):
        """
        Log the summary statistics to logger

        Args:
            logger: logger instance to use
        """
        s = self.summary()
        logger.info(
            f"[{s['source']}] Finished - "
            f"New: {s['new']}, Skipped: {s['skipped']}, Errors: {s['errors']}, "
            f"Chunks: {s['chunks']}, "
            f"Embed time: {s['embed_time_sec']}s, "
            f"Total time: {s['total_time_sec']}s, "
            f"Success Rate: {s['success_rate']}%"
        )

