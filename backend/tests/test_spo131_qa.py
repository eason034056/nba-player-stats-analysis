"""SPO-131 QA — cache edge cases on the recorded BALLDONTLIE fixtures.

Every BDL body here is the recorded page or a copy of it. No test types
a new BDL response.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests import test_spo131_bdl_injuries as base
from tests.test_spo131_bdl_injuries import (
    INJURY_PAGE,
    STANDINGS,
    NBA_INJURIES_CACHE_KEY,
    NBA_INJURIES_CACHE_TTL_SECONDS,
    nba_injuries,
    normalize_bdl_injuries,
    refresh_nba_injuries,
    team_id_to_code_from_standings,
)

_MAPPING = team_id_to_code_from_standings(STANDINGS)
_REPO = Path(base._REPO)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_entries() -> list[dict]:
    return normalize_bdl_injuries(INJURY_PAGE["data"], _MAPPING, fetched_at=_now_iso())


def _single_page() -> dict:
    """The recorded page as the only page: a copy with ``next_cursor`` cleared."""
    page = copy.deepcopy(INJURY_PAGE)
    page["meta"]["next_cursor"] = None
    return page


def _row(last_name: str) -> dict:
    return copy.deepcopy(next(r for r in INJURY_PAGE["data"] if r["player"]["last_name"] == last_name))


# ---------------------------------------------------------------------------
# Fresh, empty, malformed
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Clock handling
# ---------------------------------------------------------------------------


def test_z_suffix_and_naive_times_are_read_as_utc():
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    five_h = now - timedelta(hours=5)
    seven_h = now - timedelta(hours=7)
    assert nba_injuries._is_stale(five_h.strftime("%Y-%m-%dT%H:%M:%SZ"), now=now) is False
    assert nba_injuries._is_stale(seven_h.strftime("%Y-%m-%dT%H:%M:%SZ"), now=now) is True
    assert nba_injuries._is_stale(five_h.replace(tzinfo=None).isoformat(), now=now) is False
    assert nba_injuries._is_stale(seven_h.replace(tzinfo=None).isoformat(), now=now) is True


def test_offset_times_are_compared_in_utc():
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    chicago = timezone(timedelta(hours=-6))
    # 01:00 CST is 07:00 UTC, five hours before ``now``.
    assert nba_injuries._is_stale(datetime(2026, 11, 11, 1, 0, tzinfo=chicago).isoformat(), now=now) is False
    # 23:00 CST the day before is 05:00 UTC, seven hours before ``now``.
    assert nba_injuries._is_stale(datetime(2026, 11, 10, 23, 0, tzinfo=chicago).isoformat(), now=now) is True


def test_refresh_stamps_fetched_at_in_utc():
    service, _fake = base._cache()
    client = base.PageClient([_single_page()])
    payload = asyncio.run(refresh_nba_injuries(client, service, _MAPPING))
    parsed = datetime.fromisoformat(payload["fetched_at"])
    assert parsed.utcoffset() == timedelta(0)
    assert nba_injuries._is_stale(payload["fetched_at"]) is False


# ---------------------------------------------------------------------------
# Refresh must not publish an empty list over a good one
# ---------------------------------------------------------------------------


def test_refresh_with_no_team_map_keeps_the_previous_snapshot():
    service, _fake = base._cache()
    previous = {"fetched_at": _now_iso(), "entries": _fresh_entries()}
    asyncio.run(service.set(NBA_INJURIES_CACHE_KEY, previous, ttl=NBA_INJURIES_CACHE_TTL_SECONDS))
    client = base.PageClient([_single_page()])

    result = asyncio.run(refresh_nba_injuries(client, service, {}))

    assert result is None
    assert asyncio.run(service.get(NBA_INJURIES_CACHE_KEY)) == previous


def test_refresh_failure_log_does_not_echo_the_exception_text(caplog):
    service, _fake = base._cache()

    class _Leaky:
        async def list_player_injuries(self, *, cursor=None, per_page=100):
            raise RuntimeError("GET /v1/player_injuries Authorization: SECRET-TOKEN-123")

    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(refresh_nba_injuries(_Leaky(), service, _MAPPING)) is None
    assert "SECRET-TOKEN-123" not in caplog.text
    assert "RuntimeError" in caplog.text


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------


def test_recorded_statuses_are_all_handled():
    raw = {row["status"] for row in INJURY_PAGE["data"]}
    assert raw == {"Out", "Questionable", "Available", "Day-To-Day", "Probable", "Doubtful"}
    entries = normalize_bdl_injuries(INJURY_PAGE["data"], _MAPPING, fetched_at=_now_iso())
    assert {e["raw_status"] for e in entries} == raw - {"Available"}
    for entry in entries:
        assert entry["status"] == entry["raw_status"]


def test_unrecognized_status_is_kept_and_logged(caplog):
    row = _row("Jackson Jr.")
    row["status"] = "Out For Season"
    with caplog.at_level(logging.WARNING):
        entries = normalize_bdl_injuries([row], _MAPPING, fetched_at=_now_iso())
    assert [e["raw_status"] for e in entries] == ["Out For Season"]
    assert "unrecognized BDL injury status" in caplog.text


# ---------------------------------------------------------------------------
# Player matching
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# No BALLDONTLIE call on the agent path
# ---------------------------------------------------------------------------


def test_cache_read_module_has_no_http_client():
    text = (_REPO / "backend" / "app" / "services" / "nba_injuries.py").read_text(encoding="utf-8")
    for needle in ("import httpx", "import aiohttp", "import requests", "balldontlie.io"):
        assert needle not in text


def test_fixtures_carry_no_credentials():
    for path in (_REPO / "backend" / "tests" / "fixtures" / "bdl").glob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        for needle in ("authorization", "apikey", "api_key", "bearer"):
            assert needle not in text, path.name


# ---------------------------------------------------------------------------
# WNBA regression
# ---------------------------------------------------------------------------


