"""NBA injury cache filled from BALLDONTLIE ``/v1/player_injuries``.

Product agents read :func:`get_cached_nba_injuries`. They do not call
BALLDONTLIE during a request. The shared key is 5 requests per minute,
and one user question can ask for injuries more than once.

``refresh_nba_injuries`` is the writer. It is not on the scheduler yet.
The client that performs the HTTP call, including 429 retries, lands in
``backend/app/services/bdl_client.py`` with SPO-130a. This module only
sees the JSON that client returns: ``{"data": [...], "meta": {...}}``.

BDL injury rows have no timestamp and no team abbreviation. ``fetched_at``
is the time we stored the page. The team code comes from a ``team_id``
map the caller supplies (SPO-130d will own the official map).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol

from app.services.cache import CacheService

logger = logging.getLogger(__name__)

# Redis keeps the last good body for a day. Readers stop trusting it
# after six hours, while the key is still there, so a stale snapshot
# is visible instead of looking like a missing key.
NBA_INJURIES_CACHE_KEY = "injuries:nba:latest"
NBA_INJURIES_CACHE_TTL_SECONDS = 24 * 60 * 60
NBA_INJURIES_STALE_AFTER_SECONDS = 6 * 60 * 60
# per_page is 100, so 20 pages is about 2000 rows.
NBA_INJURIES_MAX_PAGES = 20

BALLDONTLIE_SOURCE = "balldontlie"

# Status words on the recorded /v1/player_injuries page. Anything else is
# kept and logged so a new BDL word is visible instead of dropped.
_STATUS_AVAILABLE = "Available"
_STATUS_DOUBTFUL = "Doubtful"
_STATUS_QUESTIONABLE = "Questionable"
_PASSTHROUGH_STATUSES = frozenset({"Out", "Questionable", "Day-To-Day", "Probable"})


class BdlInjuryClient(Protocol):
    async def list_player_injuries(self, *, cursor: int | None = None, per_page: int = 100) -> dict: ...


def open_injury_cache() -> CacheService:
    """Open a cache client that is not the process-wide singleton.

    Sync product-agent tools run on a worker thread. The shared
    ``cache_service`` client belongs to the server event loop, so a
    request-path read opens and closes its own client instead.
    """
    return CacheService()


def team_id_to_code_from_standings(payload: Mapping[str, Any]) -> dict[int, str]:
    """Build ``team_id -> abbreviation`` from a BDL standings body.

    Reads ``data[].team.id`` and ``data[].team.abbreviation`` only.
    It does not invent codes. SPO-130d will supply this map in
    production; tests build it from the recorded standings fixture.
    """
    mapping: dict[int, str] = {}
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        return mapping
    for row in rows:
        if not isinstance(row, dict):
            continue
        team = row.get("team")
        if not isinstance(team, dict):
            continue
        team_id = team.get("id")
        abbreviation = team.get("abbreviation")
        if team_id is None or not abbreviation:
            continue
        mapping[int(team_id)] = str(abbreviation)
    return mapping


def _lookup_team_code(team_id: Any, team_id_to_code: Mapping[Any, str]) -> str | None:
    """Resolve a BDL ``team_id`` against the caller's map.

    JSON objects use int keys after ``json.loads``. A caller that built
    the map with string keys still matches.
    """
    if team_id in team_id_to_code:
        return team_id_to_code[team_id]
    if team_id is None:
        return None
    text = str(team_id)
    if text in team_id_to_code:
        return team_id_to_code[text]
    try:
        number = int(team_id)
    except (TypeError, ValueError):
        return None
    return team_id_to_code.get(number)


def _mapped_status(raw_status: Any) -> str | None:
    """Return the status stored on a normalized row, or None to drop it.

    ``Available`` is not an injury. ``Doubtful`` is stored as
    ``Questionable`` because the scorer's unresolved bucket is
    ``Questionable`` / ``Day-To-Day`` and has no ``Doubtful`` label.
    The original word stays on ``raw_status``.
    """
    if raw_status == _STATUS_AVAILABLE:
        return None
    if raw_status == _STATUS_DOUBTFUL:
        return _STATUS_QUESTIONABLE
    if not isinstance(raw_status, str):
        return None
    return raw_status


def normalize_bdl_injuries(
    rows: list[dict],
    team_id_to_code: Mapping[Any, str],
    *,
    fetched_at: str | None = None,
) -> list[dict[str, Any]]:
    """Turn BDL injury rows into the cache entry shape.

    Args:
        rows: ``data`` arrays from ``/v1/player_injuries``, already
            concatenated across pages.
        team_id_to_code: BDL team id to a 3-letter code. Unknown ids
            are logged and dropped.
        fetched_at: UTC ISO time the pages were stored. Each entry
            carries the same value so a later history table can keep
            this shape. BDL itself does not send a timestamp.

    Returns:
        One dict per kept row. ``Available`` rows are omitted.
        ``Doubtful`` is ``status="Questionable"`` with
        ``raw_status="Doubtful"``. ``Out``, ``Questionable``,
        ``Day-To-Day``, and ``Probable`` are unchanged.
    """
    entries: list[dict[str, Any]] = []
    seen_unknown: set[Any] = set()
    seen_unrecognized: set[Any] = set()
    for row in rows:
        if not isinstance(row, dict):
            logger.warning("dropping BDL injury row that is not an object")
            continue
        raw_status = row.get("status")
        status = _mapped_status(raw_status)
        if status is None:
            continue
        if (
            raw_status not in _PASSTHROUGH_STATUSES
            and raw_status != _STATUS_DOUBTFUL
            and raw_status not in seen_unrecognized
        ):
            logger.warning("keeping unrecognized BDL injury status=%s", raw_status)
            seen_unrecognized.add(raw_status)
        player = row.get("player")
        if not isinstance(player, dict):
            logger.warning("dropping BDL injury row with no player object")
            continue
        team_id = player.get("team_id")
        team_code = _lookup_team_code(team_id, team_id_to_code)
        if team_code is None:
            if team_id not in seen_unknown:
                logger.warning(
                    "dropping BDL injury row with unknown team_id=%s",
                    team_id,
                )
                seen_unknown.add(team_id)
            continue
        first_name = player.get("first_name") or ""
        last_name = player.get("last_name") or ""
        description = row.get("description") or ""
        entries.append(
            {
                "player": f"{first_name} {last_name}".strip(),
                "bdl_player_id": player.get("id"),
                "team": team_code,
                "position": player.get("position") or "",
                "status": status,
                "raw_status": raw_status,
                "injury": description,
                "return_date": row.get("return_date"),
                "source": BALLDONTLIE_SOURCE,
                "fetched_at": fetched_at,
            }
        )
    return entries


def _parse_utc(fetched_at: str | None) -> datetime | None:
    """Parse an ISO timestamp. Return None when it is missing or invalid."""
    if not isinstance(fetched_at, str) or not fetched_at.strip():
        return None
    try:
        parsed = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_stale(fetched_at: str | None, *, now: datetime | None = None) -> bool:
    """True when ``fetched_at`` is missing or older than the 6h window.

    Exactly six hours is still fresh. Older than six hours is stale.
    """
    parsed = _parse_utc(fetched_at)
    if parsed is None:
        return True
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = current.astimezone(timezone.utc) - parsed
    return age > timedelta(seconds=NBA_INJURIES_STALE_AFTER_SECONDS)


def _snapshot_from_payload(
    raw: Any,
    team_code: str | None,
) -> dict[str, Any]:
    """Turn a cached JSON object into entries, fetched_at, and stale.

    A missing body, a non-object, or an unreadable time is stale with
    an empty entry list. Filtering by team does not change ``stale``.
    """
    if not isinstance(raw, dict):
        return {"entries": [], "fetched_at": None, "stale": True}
    fetched_at = raw.get("fetched_at")
    if not isinstance(fetched_at, str):
        fetched_at = None
    entries = raw.get("entries")
    if not isinstance(entries, list):
        entries = []
    kept = [row for row in entries if isinstance(row, dict)]
    if team_code:
        wanted = team_code.strip().upper()
        kept = [row for row in kept if str(row.get("team", "")).upper() == wanted]
    return {
        "entries": kept,
        "fetched_at": fetched_at,
        "stale": _is_stale(fetched_at),
    }


async def get_cached_nba_injuries(
    team_code: str | None = None,
    *,
    cache: Any | None = None,
) -> dict[str, Any]:
    """Read the NBA injury snapshot. This never calls BALLDONTLIE.

    Args:
        team_code: When set, ``entries`` is limited to that 3-letter
            code. ``fetched_at`` and ``stale`` still describe the whole
            snapshot.
        cache: Cache client. Defaults to the process ``cache_service``.
            Request-path reads pass a short-lived client from
            :func:`open_injury_cache`.

    Returns:
        ``{"entries", "fetched_at", "stale"}``. ``stale`` is true when
        the key is missing or ``fetched_at`` is older than six hours.
    """
    reader = cache
    if reader is None:
        from app.services.cache import cache_service

        reader = cache_service
    raw = await reader.get(NBA_INJURIES_CACHE_KEY)
    return _snapshot_from_payload(raw, team_code)


async def refresh_nba_injuries(
    client: BdlInjuryClient,
    cache: Any,
    team_id_to_code: Mapping[Any, str],
) -> dict[str, Any] | None:
    """Fetch injury pages, normalize, and store the snapshot.

    Follows ``meta.next_cursor`` until it is missing, null, or equal to
    the cursor just requested. Stops after
    :data:`NBA_INJURIES_MAX_PAGES` pages and logs a warning when that
    cap is what stopped the walk. Rate limits and 429 retries belong
    to ``client``. A ``ValueError`` (a page without a ``data`` list)
    logs a warning. Any other exception logs the traceback. Both leave
    the previous ``injuries:nba:latest`` value untouched.

    Args:
        client: SPO-130a client. Only ``list_player_injuries`` is used.
        cache: Object with ``async set(key, value, ttl) -> bool``,
            matching :class:`CacheService`.
        team_id_to_code: Passed through to :func:`normalize_bdl_injuries`.

    Returns:
        The stored ``{"fetched_at", "entries"}`` body, or None when
        nothing was written.
    """
    rows: list[dict] = []
    cursor: int | None = None
    try:
        hit_page_cap = True
        for _page_number in range(NBA_INJURIES_MAX_PAGES):
            requested = cursor
            page = await client.list_player_injuries(cursor=requested, per_page=100)
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise ValueError("player_injuries page is missing a data list")
            rows.extend(page["data"])
            meta = page.get("meta")
            next_cursor = meta.get("next_cursor") if isinstance(meta, dict) else None
            # Missing, null, or a repeat of the cursor we just sent.
            if next_cursor is None or next_cursor == requested:
                hit_page_cap = False
                break
            cursor = next_cursor
        if hit_page_cap:
            logger.warning(
                "NBA injury refresh stopped at the %s page cap",
                NBA_INJURIES_MAX_PAGES,
            )
        fetched_at = datetime.now(timezone.utc).isoformat()
        entries = normalize_bdl_injuries(
            rows,
            team_id_to_code,
            fetched_at=fetched_at,
        )
        payload = {"fetched_at": fetched_at, "entries": entries}
        stored = await cache.set(
            NBA_INJURIES_CACHE_KEY,
            payload,
            NBA_INJURIES_CACHE_TTL_SECONDS,
        )
        if stored is False:
            return None
        return payload
    except ValueError:
        logger.warning(
            "NBA injury refresh rejected a page; previous cache left in place"
        )
        return None
    except Exception:
        # TODO(SPO-130a): narrow this catch to BdlError once bdl_client.py lands.
        logger.exception(
            "NBA injury refresh failed; previous cache left in place"
        )
        return None
