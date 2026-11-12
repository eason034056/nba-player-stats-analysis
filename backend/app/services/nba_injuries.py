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

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from app.services.cache import CacheService
from app.services.normalize import normalize_name

logger = logging.getLogger(__name__)

# Redis keeps the last good body for a day. Readers stop trusting it
# after six hours, while the key is still there, so a stale snapshot
# is visible instead of looking like a missing key.
NBA_INJURIES_CACHE_KEY = "injuries:nba:latest"
NBA_INJURIES_CACHE_TTL_SECONDS = 24 * 60 * 60
NBA_INJURIES_STALE_AFTER_SECONDS = 6 * 60 * 60
# per_page is 100, so 20 pages is about 2000 rows.
NBA_INJURIES_MAX_PAGES = 20
# Request-path reads open their own client. A stuck Redis must not
# hold the user request open.
NBA_INJURY_CACHE_SOCKET_TIMEOUT_SECONDS = 2.0
# One page every 15 seconds is 4 calls in any clock minute. The shared
# trial budget is 5/min (``bdl_rate_limit_per_min``). The spare slot is
# for the other caller on this key. The limiter still refuses a 6th.
NBA_INJURY_PAGE_INTERVAL_SECONDS = 15.0

# Recorded standings body. Team ids are read from this file, not typed.
# ``backend/app/services/nba_injuries.py`` -> ``backend/tests/fixtures/bdl``.
_STANDINGS_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "bdl"
    / "standings_2026.json"
)

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
    The socket timeouts are short so a stuck Redis fails the read
    and the report becomes unavailable.
    """
    return CacheService(
        socket_timeout=NBA_INJURY_CACHE_SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=NBA_INJURY_CACHE_SOCKET_TIMEOUT_SECONDS,
    )


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
    ``Questionable``. Picks and reads use that stored word and do not
    block on the source word. The original word stays on
    ``raw_status`` for the agent payload and a later history table.
    Eason chose the mapping in the Sports Lab Lead chat on 2026-11-10
    (~10:34 PM CT), and on 2026-11-11 that a stored Doubtful keeps
    its blend.

    A word this module does not know is not left as-is. Downstream
    treats an unknown status as healthy. A word that contains ``Out``
    (``Out For Season``) is stored as ``Out``. Every other unknown
    word is stored as ``Questionable``. ``raw_status`` keeps the
    original word, and the caller logs it.
    """
    if raw_status == _STATUS_AVAILABLE:
        return None
    if raw_status == _STATUS_DOUBTFUL:
        return _STATUS_QUESTIONABLE
    if not isinstance(raw_status, str):
        return None
    if raw_status in _PASSTHROUGH_STATUSES:
        return raw_status
    if "Out" in raw_status:
        return "Out"
    return _STATUS_QUESTIONABLE


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


def injury_snapshot_is_fresh(raw: object) -> bool:
    """True when pick and reads loaders would use this body.

    The body must be a dict with an ``entries`` list and a
    ``fetched_at`` that is not older than six hours. Exactly six hours
    is still fresh. A missing body, a non-list ``entries``, and an
    unreadable time are not fresh. This does not log.

    Args:
        raw: Value stored at ``injuries:nba:latest``, or None.

    Returns:
        True when the snapshot is usable. False when a reader would
        leave ``injury_status`` null.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        return False
    fetched_at = raw.get("fetched_at")
    if not isinstance(fetched_at, str):
        return False
    return not _is_stale(fetched_at)


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
    an empty entry list. ``entries`` must be a list, including an
    empty list, before the snapshot can be fresh. A missing key, null,
    string, or object is malformed and stale, so readers say the data
    is unavailable instead of reporting a healthy team. Filtering by
    team does not change ``stale``.
    """
    if not isinstance(raw, dict):
        return {"entries": [], "fetched_at": None, "stale": True}
    fetched_at = raw.get("fetched_at")
    if not isinstance(fetched_at, str):
        fetched_at = None
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return {"entries": [], "fetched_at": fetched_at, "stale": True}
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
        the key is missing, ``entries`` is not a list, or ``fetched_at``
        is older than six hours.
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
    cap is what stopped the walk. Hitting the cap does not write: a
    partial list would replace a complete snapshot and the missing
    pages would be read as healthy. Rate limits and 429 retries belong
    to ``client``. A ``ValueError`` (a page without a ``data`` list)
    logs a warning. Any other exception logs the exception type and
    not the message: a client error can echo a request header. An
    empty team map, or a non-empty page that normalizes to zero
    entries, is also a failure and does not write. A first page whose
    ``data`` is an empty list, with a non-empty team map, is a real
    empty league and is stored. All of these failures leave the
    previous ``injuries:nba:latest`` value untouched.

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
                "NBA injury refresh stopped at the %s page cap; previous cache left in place",
                NBA_INJURIES_MAX_PAGES,
            )
            return None
        fetched_at = datetime.now(timezone.utc).isoformat()
        entries = normalize_bdl_injuries(
            rows,
            team_id_to_code,
            fetched_at=fetched_at,
        )
        # An empty map, or rows that all drop, would publish "nobody is
        # injured" over a good snapshot. A real empty league is
        # ``data: []`` together with a map we could have used.
        if len(team_id_to_code) == 0:
            logger.warning(
                "NBA injury refresh has an empty team map; previous cache left in place"
            )
            return None
        if rows and not entries:
            logger.warning(
                "NBA injury refresh kept no entries from %s rows; previous cache left in place",
                len(rows),
            )
            return None
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
    except Exception as exc:
        # BdlError is the expected client failure. Any other exception is
        # logged the same way: type only, never the message. A client
        # error can include the request line, and that line can carry a
        # credential.
        logger.warning(
            "NBA injury refresh failed (%s); previous cache left in place",
            type(exc).__name__,
        )
        return None


def _injury_name_key(name: str | None) -> str:
    """Fold case, punctuation, and accents. Keep Jr, Sr, and II–VI.

    ``player_name_key`` drops a trailing generational suffix. Injury
    matching must not: ``Gary Trent Jr.`` and ``Gary Trent`` are
    different people, and there is no suffix-stripped fallback.
    ``normalize_name`` is the whole fold. ``Luka Dončić`` and
    ``luka doncic`` share a key. ``Gary Trent Jr.`` and ``gary trent jr``
    share a key. ``Gary Trent`` does not.
    """
    if not name:
        return ""
    return normalize_name(str(name))


def match_injury_entry(
    entries: list[dict],
    player: str,
    bdl_player_id: Any = None,
) -> dict[str, Any] | None:
    """Pick one injury row for ``player``.

    A caller-supplied ``bdl_player_id`` wins when a row carries that
    same id. Daily picks and ``/reads`` do not have one: an Odds API
    outcome and a snapshot row are a player name only, so those
    callers leave this argument unset. The agent tool passes an id
    when it has one.

    Names compare through :func:`_injury_name_key` (case, punctuation,
    and accents). The suffix stays. There is no fallback that drops
    Jr/Sr/II/III/IV. Scraper rows that share a name and have no id
    still return the first row. Two BDL rows with different ids, or
    the same name and no id, are left unmatched.
    """
    rows = [entry for entry in entries if isinstance(entry, dict) and not entry.get("unavailable")]
    if bdl_player_id is not None:
        for entry in rows:
            if entry.get("bdl_player_id") == bdl_player_id:
                return entry

    def _same(entry: dict) -> bool:
        key = _injury_name_key(str(entry.get("player") or ""))
        return bool(key) and key == _injury_name_key(player)

    named = [entry for entry in rows if _same(entry)]
    if not named:
        return None
    bdl_rows = [
        entry
        for entry in named
        if "bdl_player_id" in entry or entry.get("source") == BALLDONTLIE_SOURCE
    ]
    if not bdl_rows:
        return named[0]
    ids = {entry.get("bdl_player_id") for entry in bdl_rows if entry.get("bdl_player_id") is not None}
    if len(ids) > 1:
        return None
    if len(ids) == 1:
        wanted = next(iter(ids))
        for entry in named:
            if entry.get("bdl_player_id") == wanted:
                return entry
    if len(bdl_rows) == 1:
        return bdl_rows[0]
    return None


def load_recorded_team_id_map() -> dict[int, str]:
    """Read ``team_id -> abbreviation`` from the recorded standings fixture.

    The file is the standings capture committed with the injury cache.
    A missing or unreadable file returns an empty map. The refresh then
    refuses to write, which leaves the previous snapshot in place.
    The log line is the exception type only.
    """
    try:
        payload = json.loads(_STANDINGS_FIXTURE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(
            "NBA injury team map could not be read (%s); previous cache left in place",
            type(exc).__name__,
        )
        return {}
    if not isinstance(payload, dict):
        logger.warning(
            "NBA injury team map could not be read (%s); previous cache left in place",
            type(payload).__name__,
        )
        return {}
    return team_id_to_code_from_standings(payload)


class PacedInjuryClient:
    """Space ``list_player_injuries`` so one refresh stays under 5 calls/min.

    The first call goes immediately. Each later call waits
    ``interval_seconds`` after the previous one started. At 15 seconds
    that is 4 calls in any clock minute. The wrapped client is still
    responsible for the shared Redis limiter; this only stops the
    refresh from using every slot itself.

    Args:
        client: Object with ``list_player_injuries`` (the BDL client).
        interval_seconds: Gap between page starts. Default 15.
        sleep: Awaitable delay. Tests pass a clock that records the gap.
        clock: Monotonic clock in seconds. Tests pass the same clock
            ``sleep`` advances.
    """

    def __init__(
        self,
        client: BdlInjuryClient,
        *,
        interval_seconds: float = NBA_INJURY_PAGE_INTERVAL_SECONDS,
        sleep: Any = None,
        clock: Any = None,
    ) -> None:
        self._client = client
        self._interval = interval_seconds
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or time.monotonic
        self._next_allowed: float | None = None

    async def list_player_injuries(
        self,
        *,
        cursor: int | None = None,
        per_page: int = 100,
    ) -> dict:
        """Fetch one page after the pacing gap, then return the client body."""
        now = float(self._clock())
        if self._next_allowed is not None and now < self._next_allowed:
            await self._sleep(self._next_allowed - now)
            now = float(self._clock())
        self._next_allowed = now + self._interval
        return await self._client.list_player_injuries(cursor=cursor, per_page=per_page)


async def refresh_nba_injuries_from_bdl(
    client: BdlInjuryClient,
    cache: Any,
    *,
    team_id_to_code: Mapping[Any, str] | None = None,
    sleep: Any = None,
    clock: Any = None,
    page_interval_seconds: float = NBA_INJURY_PAGE_INTERVAL_SECONDS,
) -> dict[str, Any] | None:
    """Refresh through a paced client and the recorded team-id map.

    ``client`` is the shared BDL client, so every page takes a Redis
    budget slot. ``team_id_to_code`` defaults to the recorded standings
    fixture. Passing a map is how tests avoid the file.

    Returns the stored body, or None when nothing was written.
    """
    mapping = team_id_to_code if team_id_to_code is not None else load_recorded_team_id_map()
    paced = PacedInjuryClient(
        client,
        interval_seconds=page_interval_seconds,
        sleep=sleep,
        clock=clock,
    )
    return await refresh_nba_injuries(paced, cache, mapping)


async def load_nba_pick_injuries(*, cache: Any | None = None) -> list[dict[str, Any]] | None:
    """Return a fresh injury list for NBA picks, or None when it cannot be used.

    This never calls BALLDONTLIE. A missing key, a stale ``fetched_at``,
    a body that is not ``{"entries": [...]}``, and a read error each log
    one warning and return None. The warning names the failure kind, or
    the exception type. It does not include the message, a URL, or a key.
    A fresh empty list is a real snapshot and returns ``[]`` with no warning.

    Args:
        cache: Object with ``async get(key)``. Defaults to the process
            cache client.

    Returns:
        The entry list, or None when picks must leave ``injury_status`` null.
    """
    reader = cache
    if reader is None:
        from app.services.cache import cache_service

        reader = cache_service
    try:
        raw = await reader.get(NBA_INJURIES_CACHE_KEY)
    except Exception as exc:
        logger.warning(
            "NBA pick injury read failed (%s); injury_status left null",
            type(exc).__name__,
        )
        return None
    if raw is None:
        logger.warning("NBA injury snapshot missing; injury_status left null")
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        logger.warning("NBA injury snapshot malformed; injury_status left null")
        return None
    snapshot = _snapshot_from_payload(raw, None)
    if snapshot["stale"]:
        logger.warning("NBA injury snapshot stale; injury_status left null")
        return None
    return [row for row in snapshot["entries"] if isinstance(row, dict)]
