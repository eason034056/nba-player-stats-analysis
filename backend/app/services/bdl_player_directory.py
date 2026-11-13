"""
bdl_player_directory.py - BALLDONTLIE player id to a display name.

``BdlPlayerDirectory`` is the phone book the props adapter uses. A prop
row carries ``player_id`` and no name. The directory answers with the
string that becomes ``outcome.description``.

Lookup order for one id:

1. Redis ``bdl:player:v1:{id}``, kept for 24 hours.
2. ``bdl_player_aliases.json``, when that id has an override.
3. ``GET /v1/players?player_ids[]=`` via ``BdlClient.list_players``.

An id with no alias uses ``first_name`` and ``last_name`` from that
response. That is BALLDONTLIE's own name. The directory logs one line
and increments ``unaliased_count`` so a new id is visible. It does not
invent a spelling. An id the response does not contain is counted as
missing and is omitted, so the adapter skips that row.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import redis.asyncio as redis_async

from app.services.bdl_client import BdlClient

logger = logging.getLogger(__name__)

_ALIAS_PATH = Path(__file__).with_name("bdl_player_aliases.json")
_KEY_PREFIX = "bdl:player:v1:"
_TTL_SECONDS = 24 * 60 * 60
_BATCH = 100


def load_player_aliases(path: Path | None = None) -> dict[int, str]:
    """Read the alias file. An empty object means every id uses the BDL name.

    Keys in the file are decimal player ids. Values are the description
    string. A blank value is ignored.
    """
    source = path if path is not None else _ALIAS_PATH
    if not source.exists():
        return {}
    raw = json.loads(source.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"player alias file must be an object: {source}")
    aliases: dict[int, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or not value.strip():
            continue
        aliases[int(key)] = value.strip()
    return aliases


def bdl_player_name(player: dict[str, Any]) -> str:
    """``first_name`` plus ``last_name``, the name on the players payload."""
    first = player.get("first_name")
    last = player.get("last_name")
    parts = [part.strip() for part in (first, last) if isinstance(part, str) and part.strip()]
    return " ".join(parts)


class BdlPlayerDirectory:
    """Resolve BALLDONTLIE player ids to description strings.

    Usage:
        directory = BdlPlayerDirectory(client, redis=redis)
        names = await directory.names_for([175, 476])

    ``unaliased_count`` is how many ids used the BALLDONTLIE name because
    the alias file had no entry. ``missing_count`` is how many ids were
    absent from both the alias file and the players response. Each of
    those ids produces one log line per directory instance.
    """

    def __init__(
        self,
        client: BdlClient,
        redis: redis_async.Redis | None = None,
        aliases: dict[int, str] | None = None,
    ) -> None:
        self._client = client
        self._redis = redis
        self._aliases = aliases if aliases is not None else load_player_aliases()
        self.unaliased_count = 0
        self.missing_count = 0
        self._logged_unaliased: set[int] = set()
        self._logged_missing: set[int] = set()

    async def names_for(self, player_ids: list[int]) -> dict[int, str]:
        """Return ``{player_id: description}`` for the ids that resolved.

        Ids already in Redis are not fetched again. Missing ids are
        requested in batches of 100, which is ``list_players``' limit.
        An empty ``player_ids`` list does not call the network.
        """
        unique: list[int] = []
        seen: set[int] = set()
        for player_id in player_ids:
            if not isinstance(player_id, int) or player_id in seen:
                continue
            seen.add(player_id)
            unique.append(player_id)
        if not unique:
            return {}

        resolved: dict[int, str] = {}
        pending: list[int] = []
        for player_id in unique:
            cached = await self._read_cache(player_id)
            if cached is not None:
                resolved[player_id] = cached
            else:
                pending.append(player_id)

        alias_hits = [player_id for player_id in pending if player_id in self._aliases]
        for player_id in alias_hits:
            name = self._aliases[player_id]
            resolved[player_id] = name
            await self._write_cache(player_id, name)
        pending = [player_id for player_id in pending if player_id not in self._aliases]

        for start in range(0, len(pending), _BATCH):
            batch = pending[start : start + _BATCH]
            payload = await self._client.list_players(player_ids=batch)
            data = payload.get("data") if isinstance(payload, dict) else None
            found: dict[int, str] = {}
            if isinstance(data, list):
                for player in data:
                    if not isinstance(player, dict) or not isinstance(player.get("id"), int):
                        continue
                    name = bdl_player_name(player)
                    if name:
                        found[player["id"]] = name
            for player_id in batch:
                name = found.get(player_id)
                if name is None:
                    self._note_missing(player_id)
                    continue
                self._note_unaliased(player_id, name)
                resolved[player_id] = name
                await self._write_cache(player_id, name)
        return resolved

    def _note_unaliased(self, player_id: int, name: str) -> None:
        """One counted line the first time this id uses the BDL spelling."""
        if player_id in self._logged_unaliased:
            return
        self._logged_unaliased.add(player_id)
        self.unaliased_count += 1
        logger.info("bdl_player_unaliased id=%s name=%s", player_id, name)

    def _note_missing(self, player_id: int) -> None:
        """One counted line when the players response has no such id."""
        if player_id in self._logged_missing:
            return
        self._logged_missing.add(player_id)
        self.missing_count += 1
        logger.info("bdl_player_unknown id=%s", player_id)

    async def _read_cache(self, player_id: int) -> str | None:
        if self._redis is None:
            return None
        try:
            value = await self._redis.get(f"{_KEY_PREFIX}{player_id}")
        except Exception:
            logger.warning("bdl_player_cache_read_failed id=%s", player_id)
            return None
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    async def _write_cache(self, player_id: int, name: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(f"{_KEY_PREFIX}{player_id}", name, ex=_TTL_SECONDS)
        except Exception:
            logger.warning("bdl_player_cache_write_failed id=%s", player_id)
