"""
raw_cache.py - keep every fetched BALLDONTLIE page as gzipped JSON on local disk.

A page is saved before it is written, so the page that broke a walk can still
be read. The file is named by the cursor that was requested, so a resumed or
restarted walk rewrites the same file instead of adding one:

    <root>/<league>/<data_type>/<season>/<season_type, or "all" for stats>/<cursor, or "first">.json.gz

The directory is git-ignored (``bdl-raw/``). Pages hold no key: the key
travels in a header, not in the response.
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.backfill.walker import Shard


class RawCache:
    """Pages for one league under ``root``."""

    def __init__(self, root: Path, league: str) -> None:
        self.root = root
        self.league = league

    def path_for(self, shard: Shard, cursor: int | None) -> Path:
        return (
            self.root / self.league / shard.data_type / str(shard.season)
            / (shard.shard_key or "all") / f"{'first' if cursor is None else cursor}.json.gz"
        )

    def save(self, shard: Shard, cursor: int | None, page: dict[str, Any]) -> Path:
        """Write the page, replacing any earlier copy in one rename."""
        path = self.path_for(shard, cursor)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "league": self.league,
            "data_type": shard.data_type,
            "season": shard.season,
            "shard_key": shard.shard_key,
            "cursor": cursor,
            "fetched_at": datetime.now(UTC).isoformat(),
            "response": page,
        }
        partial = path.with_name(f"{path.name}.partial")
        partial.write_bytes(gzip.compress(json.dumps(record, ensure_ascii=False).encode("utf-8"), mtime=0))
        os.replace(partial, path)
        return path
