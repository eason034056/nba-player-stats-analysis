#!/usr/bin/env python3
"""Record ESPN schedule payloads used to label game-log seasons.

The NBA/WNBA CSVs are scraped from RealGM with a season string stamped on
every row (see the upstream ``scrape_nba.py`` ``SEASON`` constant). That
string is not the game's season, and the "All Games" filter mixes Summer
League, preseason, regular season, playoffs, and G League. This script
calls ESPN's public site API, keeps the fields the hygiene parser reads,
and writes them under ``tests/fixtures/espn/``.

Recorded endpoints (curl equivalents)::

    curl -sS -A 'Mozilla/5.0' \\
      'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20251021'

    curl -sS -A 'Mozilla/5.0' \\
      'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams?limit=50'

    curl -sS -A 'Mozilla/5.0' \\
      'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/13/schedule?season=2026&seasontype=2'

    curl -sS -A 'Mozilla/5.0' \\
      'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/2/schedule?season=2027&seasontype=2'

    curl -sS -A 'Mozilla/5.0' \\
      'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/2026/types/2?lang=en&region=us'

Re-run this script when a new season starts so ``schedule_events.json``
covers dates the fixture has not seen yet. Tests read that fixture.
``CSVDownloaderService.download`` fetches the live team schedules for
the seasons present in the file it just downloaded. Raw responses
recorded with curl (``*_team_*_schedule_*_type_*.json``) are folded
onto the compact index at load time.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; sports-lab-schedule-fixture/1.0)"
SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball"
CORE_API = "https://sports.core.api.espn.com/v2/sports/basketball/leagues"

# league slug, ESPN season years (the year the season ends, except WNBA
# where the year is the calendar season), seasontype ids observed on
# /seasons/{year}/types.
LEAGUE_REQUESTS: list[tuple[str, list[str], list[int]]] = [
    ("nba", ["2025", "2026", "2027"], [1, 2, 3, 5]),
    ("wnba", ["2025", "2026"], [1, 2, 3]),
    ("nba-development", ["2025", "2026"], [1, 2, 3]),
    ("nba-summer-las-vegas", ["2021", "2024", "2025"], [1, 2]),
    ("nba-summer-california", ["2025"], [1, 2]),
    ("nba-summer-utah", ["2021", "2024", "2025"], [1, 2]),
    ("nba-summer-sacramento", ["2021", "2024"], [1, 2]),
]


def repo_root() -> Path:
    """Directory that contains ``data/`` and ``tests/``."""
    return Path(__file__).resolve().parent.parent


_BACKEND = repo_root() / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def fixture_dir() -> Path:
    """On-disk home for the recorded ESPN payloads."""
    return repo_root() / "tests" / "fixtures" / "espn"


def _get_json(url: str) -> Any:
    """GET ``url`` and parse a JSON body. Raises on HTTP errors."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _team_directory(league: str) -> list[dict[str, Any]]:
    """Team id + names for one league, copied from the teams payload."""
    payload = _get_json(f"{SITE_API}/{league}/teams?limit=80")
    teams = payload["sports"][0]["leagues"][0]["teams"]
    directory: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in teams:
        team = entry["team"]
        team_id = str(team["id"])
        if team_id in seen:
            continue
        seen.add(team_id)
        directory.append(
            {
                "league": league,
                "id": team_id,
                "abbreviation": team.get("abbreviation"),
                "shortDisplayName": team.get("shortDisplayName"),
                "displayName": team.get("displayName"),
                "name": team.get("name"),
                "location": team.get("location"),
            }
        )
    return directory


def _fetch_team_schedule(
    league: str, team_id: str, season: str, season_type: int
) -> list[dict[str, Any]]:
    """One team-season-type schedule, compacted. Empty when ESPN has none."""
    from app.services.espn_schedule import compact_event

    url = (
        f"{SITE_API}/{league}/teams/{team_id}/schedule"
        f"?season={season}&seasontype={season_type}"
    )
    try:
        payload = _get_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 400):
            return []
        raise
    events = payload.get("events") or []
    return [compact_event(league, event) for event in events if event.get("id")]


def fetch_schedule_fixtures() -> dict[str, Any]:
    """Download teams, schedules, and two raw witness payloads."""
    teams: list[dict[str, Any]] = []
    jobs: list[tuple[str, str, str, int]] = []
    for league, seasons, season_types in LEAGUE_REQUESTS:
        try:
            league_teams = _team_directory(league)
        except urllib.error.HTTPError as exc:
            print(f"skip league {league}: HTTP {exc.code}", file=sys.stderr)
            continue
        teams.extend(league_teams)
        print(f"{league}: {len(league_teams)} teams", file=sys.stderr)
        for team in league_teams:
            for season in seasons:
                for season_type in season_types:
                    jobs.append((league, team["id"], season, season_type))

    compact: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(_fetch_team_schedule, league, team_id, season, season_type): (
                league,
                team_id,
                season,
                season_type,
            )
            for league, team_id, season, season_type in jobs
        }
        done = 0
        for future in as_completed(futures):
            done += 1
            league, team_id, season, season_type = futures[future]
            try:
                for event in future.result():
                    compact[event["id"]] = event
            except Exception as exc:  # noqa: BLE001 — record and continue
                errors.append(f"{league} team={team_id} season={season} type={season_type}: {exc}")
            if done % 100 == 0:
                print(f"  schedules {done}/{len(jobs)}, events {len(compact)}", file=sys.stderr)

    scoreboard = _get_json(f"{SITE_API}/nba/scoreboard?dates=20251021")
    season_type_doc = _get_json(f"{CORE_API}/nba/seasons/2026/types/2?lang=en&region=us")
    return {
        "teams": teams,
        "events": sorted(compact.values(), key=lambda event: (event.get("date") or "", event["id"])),
        "scoreboard": scoreboard,
        "season_type_doc": season_type_doc,
        "errors": errors,
        "request_count": len(jobs),
    }


def write_fixtures(bundle: dict[str, Any]) -> None:
    """Persist the bundle under ``tests/fixtures/espn/``."""
    destination = fixture_dir()
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "team_directory.json").write_text(
        json.dumps(bundle["teams"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (destination / "schedule_events.json").write_text(
        json.dumps(bundle["events"], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (destination / "nba_scoreboard_20251021.json").write_text(
        json.dumps(bundle["scoreboard"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (destination / "nba_season_2026_type_regular.json").write_text(
        json.dumps(bundle["season_type_doc"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    by_league: dict[str, int] = {}
    for event in bundle["events"]:
        by_league[event["league"]] = by_league.get(event["league"], 0) + 1
    meta = {
        "source": "site.api.espn.com team schedule + one raw scoreboard",
        "request_count": bundle["request_count"],
        "event_count": len(bundle["events"]),
        "events_by_league": by_league,
        "errors": bundle["errors"],
    }
    (destination / "schedule_manifest.json").write_text(
        json.dumps(meta, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(meta, indent=2))


def main() -> None:
    """Fetch the live API and overwrite the fixtures."""
    write_fixtures(fetch_schedule_fixtures())


if __name__ == "__main__":
    main()
