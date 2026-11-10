"""Compact and fetch ESPN team schedules.

The site API (no key) is the source the hygiene pass joins on. A compact
event keeps the fields that decide season and game type, including the
competition notes and type. Those two fields are how an NBA Cup
championship is distinguished from group play: both are
``seasonType.abbreviation == "reg"``.

Recorded raw responses live in ``tests/fixtures/espn/`` as
``{league}_team_{id}_schedule_{season}_type_{seasontype}.json``.
Production downloads call :func:`fetch_events_for_csv_text` so a new
season is classified from the live schedule, not from whatever the
fixture happened to contain when it was last committed.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; sports-lab-schedule-fixture/1.0)"
SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball"
CORE_API = "https://sports.core.api.espn.com/v2/sports/basketball/leagues"

# Parent CSV league → other ESPN league slugs that show up in that file.
# The slugs are the ones ``scripts/explore_espn_schedule_api.py`` records.
_AFFILIATE_LEAGUES: dict[str, tuple[str, ...]] = {
    "nba": (
        "nba-development",
        "nba-summer-las-vegas",
        "nba-summer-california",
        "nba-summer-utah",
        "nba-summer-sacramento",
    ),
}


def compact_event(league: str, event: dict[str, Any]) -> dict[str, Any]:
    """Copy the hygiene fields off one site-API team-schedule event.

    ``league`` is the slug of the endpoint that returned the event. The
    payload does not repeat that slug on the event object.
    """
    competitions = event.get("competitions") or []
    competition = competitions[0] if competitions else {}
    competitors_out: list[dict[str, Any]] = []
    for competitor in competition.get("competitors") or []:
        team = competitor.get("team") or {}
        competitors_out.append(
            {
                "homeAway": competitor.get("homeAway"),
                "team": {
                    "id": team.get("id"),
                    "abbreviation": team.get("abbreviation"),
                    "shortDisplayName": team.get("shortDisplayName"),
                    "displayName": team.get("displayName"),
                    "name": team.get("name"),
                    "location": team.get("location"),
                },
            }
        )
    raw_type = competition.get("type") or {}
    notes_out: list[dict[str, Any]] = []
    for note in competition.get("notes") or []:
        if not isinstance(note, dict):
            continue
        notes_out.append(
            {
                "type": note.get("type"),
                "headline": note.get("headline"),
            }
        )
    season = event.get("season") or {}
    season_type = event.get("seasonType") or {}
    return {
        "id": str(event.get("id")),
        "league": league,
        "date": event.get("date"),
        "name": event.get("name"),
        "shortName": event.get("shortName"),
        "season": {
            "year": season.get("year"),
            "displayName": season.get("displayName"),
        },
        "seasonType": {
            "id": season_type.get("id"),
            "type": season_type.get("type"),
            "name": season_type.get("name"),
            "abbreviation": season_type.get("abbreviation"),
        },
        "competition": {
            "type": {
                "id": raw_type.get("id"),
                "text": raw_type.get("text"),
                "abbreviation": raw_type.get("abbreviation"),
                "slug": raw_type.get("slug"),
                "type": raw_type.get("type"),
            },
            "notes": notes_out,
        },
        "competitors": competitors_out,
    }


def dates_in_game_log(text: str) -> set[str]:
    """ISO dates in a game-log CSV. Empty when the text is not one."""
    from app.services.game_log_hygiene import looks_like_game_log, parse_csv_date

    if not text.strip():
        return set()
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames is None or not looks_like_game_log(list(reader.fieldnames)):
        return set()
    dates: set[str] = set()
    for row in reader:
        parsed = parse_csv_date(row.get("Date", ""))
        if parsed:
            dates.add(parsed)
    return dates


def _ref_tail(ref: str) -> str:
    """Last path segment of an ESPN ``$ref`` (the id the API assigned)."""
    path = urlsplit(ref).path.rstrip("/")
    return path.rsplit("/", 1)[-1]


async def _get_json(client: httpx.AsyncClient, url: str) -> Any | None:
    """GET JSON. ``None`` when ESPN has no such resource (400 / 404)."""
    response = await client.get(url)
    if response.status_code in (400, 404):
        return None
    response.raise_for_status()
    return response.json()


async def _season_years_covering(
    client: httpx.AsyncClient,
    league: str,
    dates: set[str],
) -> list[int]:
    """ESPN season years whose recorded start/end overlap ``dates``.

    The year list and each season's ``startDate`` / ``endDate`` come
    from the core API. Nothing here treats October as a boundary.
    """
    payload = await _get_json(client, f"{CORE_API}/{league}/seasons?limit=100")
    if not payload:
        return []
    csv_years = {int(day[:4]) for day in dates}
    candidate_years = csv_years | {year + 1 for year in csv_years}
    years: list[int] = []
    for item in payload.get("items") or []:
        ref = str(item.get("$ref") or "")
        tail = _ref_tail(ref)
        if not tail.isdigit():
            continue
        year = int(tail)
        if year not in candidate_years:
            continue
        document = await _get_json(client, ref.replace("http://", "https://"))
        if not document:
            continue
        start = str(document.get("startDate") or "")
        end = str(document.get("endDate") or "")
        if len(start) < 10 or len(end) < 10:
            continue
        start_day, end_day = start[:10], end[:10]
        if any(start_day <= day <= end_day for day in dates):
            years.append(year)
    return years


async def _season_type_ids(
    client: httpx.AsyncClient, league: str, year: int
) -> list[int]:
    """Season-type ids the core API lists for one league-year."""
    payload = await _get_json(
        client, f"{CORE_API}/{league}/seasons/{year}/types?limit=20"
    )
    if not payload:
        return []
    ids: list[int] = []
    for item in payload.get("items") or []:
        tail = _ref_tail(str(item.get("$ref") or ""))
        if tail.isdigit():
            ids.append(int(tail))
    return ids


async def _team_ids(client: httpx.AsyncClient, league: str) -> list[str]:
    """Team ids from the site API teams payload."""
    payload = await _get_json(client, f"{SITE_API}/{league}/teams?limit=80")
    if not payload:
        return []
    try:
        entries = payload["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError, TypeError):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        team = entry.get("team") or {}
        team_id = str(team.get("id") or "")
        if not team_id or team_id in seen:
            continue
        seen.add(team_id)
        ids.append(team_id)
    return ids


async def _fetch_one_schedule(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    league: str,
    team_id: str,
    year: int,
    season_type: int,
) -> list[dict[str, Any]]:
    """One team-season-type schedule, compacted. Empty when ESPN has none."""
    url = (
        f"{SITE_API}/{league}/teams/{team_id}/schedule"
        f"?season={year}&seasontype={season_type}"
    )
    async with semaphore:
        payload = await _get_json(client, url)
    if not payload:
        return []
    return [
        compact_event(league, event)
        for event in (payload.get("events") or [])
        if isinstance(event, dict) and event.get("id")
    ]


async def fetch_events_covering(league: str, dates: set[str]) -> list[dict[str, Any]]:
    """Live compact events for ``league`` and its affiliates over ``dates``.

    Raises when the parent league cannot be listed. A 404 for one
    team-season is an empty schedule, not a failure.
    """
    if not dates:
        return []
    parent = league.lower()
    leagues = (parent, *_AFFILIATE_LEAGUES.get(parent, ()))
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        parent_years = await _season_years_covering(client, parent, dates)
        if not parent_years:
            raise RuntimeError(
                f"ESPN returned no {parent} season covering {min(dates)}..{max(dates)}"
            )
        jobs: list[tuple[str, str, int, int]] = []
        for slug in leagues:
            years = await _season_years_covering(client, slug, dates)
            if not years:
                logger.info("No ESPN seasons for %s overlap the CSV dates", slug)
                continue
            team_ids = await _team_ids(client, slug)
            if not team_ids:
                logger.info("ESPN team list empty for %s", slug)
                continue
            for year in years:
                type_ids = await _season_type_ids(client, slug, year)
                for team_id in team_ids:
                    for season_type in type_ids:
                        jobs.append((slug, team_id, year, season_type))
        logger.info("Fetching %s ESPN team schedules for %s", len(jobs), parent)
        semaphore = asyncio.Semaphore(12)
        batches = await asyncio.gather(
            *(
                _fetch_one_schedule(client, semaphore, slug, team_id, year, season_type)
                for slug, team_id, year, season_type in jobs
            )
        )
    by_id: dict[str, dict[str, Any]] = {}
    for batch in batches:
        for event in batch:
            by_id[event["id"]] = event
    if not by_id:
        raise RuntimeError(f"ESPN schedule fetch for {parent} returned no events")
    return list(by_id.values())


async def fetch_events_for_csv_text(text: str, *, league: str) -> list[dict[str, Any]]:
    """Live schedule covering the dates in a downloaded game-log CSV."""
    return await fetch_events_covering(league, dates_in_game_log(text))
