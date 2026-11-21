"""SPO-97 re-review gaps: season windows, Cup notes, and sample leaks.

Season documents are curl recordings. They live outside the
``*_team_*_schedule_*_type_*.json`` glob next to ``schedule_events.json``,
so loading them here does not change the schedule the hygiene script
joins against.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.csv_player_history import CSVPlayerHistoryService
from app.services.espn_schedule import (
    USER_AGENT,
    _season_years_covering,
    compact_event,
)
from app.services.game_log_hygiene import (
    GAME_TYPE_AMBIGUOUS,
    GAME_TYPE_NBA_CUP,
    GAME_TYPE_PLAYOFFS,
    GAME_TYPE_REGULAR,
    GAME_TYPE_UNCLASSIFIED,
    _local_dates,
    _parse_event_instant,
    game_type_for_event,
    hygiene_rows,
    load_schedule_events,
)

_REPO = Path(__file__).resolve().parents[2]
_ESPN = _REPO / "tests" / "fixtures" / "espn"
_SEASONS = _ESPN / "seasons"
_CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues"
_RAW_COLUMNS = [
    "Player", "Season", "Date", "Team", "Opponent", "MIN", "PTS", "REB",
    "AST", "STL", "BLK", "GameType",
]


class _PayloadResponse:
    """Just enough of an httpx response for ``_get_json``."""

    def __init__(self, status_code: int, payload: dict | None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        """Raise when the recorded client was asked for a missing document."""
        if self.status_code >= 400:
            request = httpx.Request("GET", _CORE)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("status", request=request, response=response)

    def json(self) -> dict:
        """Return the recorded JSON body."""
        return self._payload


class _RecordedSeasonClient:
    """Serves the committed season index and the 2025-2027 season documents.

    ``_season_years_covering`` asks for ``/seasons?limit=100``, then GETs
    each ``$ref`` whose year is a CSV calendar year or the next year.
    Anything else is a 404, which that function treats as "no document".
    """

    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}
        for league in ("nba",):
            index = json.loads((_SEASONS / f"{league}_index.json").read_text(encoding="utf-8"))
            self._docs[f"{_CORE}/{league}/seasons?limit=100"] = index
            saved = {
                str(year): json.loads(
                    (_SEASONS / f"{league}_{year}.json").read_text(encoding="utf-8")
                )
                for year in (2025, 2026, 2027)
            }
            for item in index.get("items") or []:
                ref = str(item.get("$ref") or "")
                tail = ref.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
                if tail in saved:
                    self._docs[ref.replace("http://", "https://")] = saved[tail]

    async def get(self, url: str) -> _PayloadResponse:
        """Return one recorded document, or 404 when this test did not save it."""
        payload = self._docs.get(url)
        if payload is None:
            return _PayloadResponse(404, None)
        return _PayloadResponse(200, payload)


def _season_doc(league: str, year: int) -> dict:
    """One recorded core-API season document."""
    return json.loads((_SEASONS / f"{league}_{year}.json").read_text(encoding="utf-8"))


def _prefix(doc: dict, field: str) -> str:
    """Calendar date ESPN put on ``startDate`` / ``endDate`` (``YYYY-MM-DD``)."""
    return str(doc[field])[:10]


def _shift(iso_day: str, days: int) -> str:
    """Move an ISO date by ``days``. Used for the day just outside a window."""
    return (date.fromisoformat(iso_day) + timedelta(days=days)).isoformat()


async def _covering(league: str, dates: set[str]) -> list[int]:
    """Season years the recorded client says overlap ``dates``."""
    return await _season_years_covering(_RecordedSeasonClient(), league, dates)


class TestSeasonOverlap:
    """Inclusive start/end on the NBA ending-year season ids.

    The recorded timestamps are early-morning UTC (``T07:00Z`` at the start,
    ``T06:59Z`` or ``T07:59Z`` at the end). The date prefix is therefore the
    US calendar day the window opens, and the morning after the last night
    it closes. Overlap keeps a CSV date that equals either prefix and drops
    the day on either side.
    """

    @pytest.mark.asyncio
    async def test_nba_window_is_inclusive_and_the_neighbors_fall_outside(self):
        # 2026 is the 2025-26 season. Its start is still in calendar 2025,
        # so the candidate set has to look at year+1 or this date matches nothing.
        doc = _season_doc("nba", 2026)
        assert doc["displayName"] == "2025-26"
        start, end = _prefix(doc, "startDate"), _prefix(doc, "endDate")
        assert start.startswith("2025-")
        assert await _covering("nba", {start}) == [2026]
        assert await _covering("nba", {_shift(start, -1)}) == []
        assert await _covering("nba", {end}) == [2026]
        assert await _covering("nba", {_shift(end, 1)}) == []


    @pytest.mark.asyncio
    async def test_one_nba_calendar_year_can_span_two_seasons(self):
        # 2025-26 ends in June 2026 and 2026-27 starts in September 2026.
        # Both dates are calendar year 2026, and both seasons have to be fetched.
        ending = _season_doc("nba", 2026)
        starting = _season_doc("nba", 2027)
        dates = {_prefix(ending, "endDate"), _prefix(starting, "startDate")}
        assert {day[:4] for day in dates} == {"2026"}
        assert set(await _covering("nba", dates)) == {2026, 2027}



@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Live ESPN season windows — set RUN_INTEGRATION=1 to enable.",
)
async def test_live_season_windows_match_the_recorded_boundaries():
    """The recorded start/end dates still select the same season years live."""
    nba_open = _prefix(_season_doc("nba", 2026), "startDate")
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        nba_years = await _season_years_covering(client, "nba", {nba_open})
    assert nba_years == [2026]


def _csv_date(event: dict) -> str:
    """Arena-local date, formatted the way the scraper writes it."""
    instant = _parse_event_instant(str(event.get("date") or ""))
    assert instant is not None
    local = date.fromisoformat(sorted(_local_dates(instant))[0])
    return f"{local.month}/{local.day}/{local.year}"


def _clubs(event: dict) -> tuple[str, str]:
    """``(away, home)`` short names off a compact event."""
    named: dict[str, str] = {}
    for competitor in event.get("competitors") or []:
        team = competitor.get("team") or {}
        named[str(competitor.get("homeAway") or "")] = str(team.get("shortDisplayName") or "")
    assert named.get("away") and named.get("home")
    return named["away"], named["home"]


def _joined_row(event: dict, player: str, *, pts: str = "10") -> dict[str, str]:
    """One CSV row whose date and both clubs are copied off ``event``."""
    away, home = _clubs(event)
    return {
        "Player": player,
        "Season": "1999-2000",
        "Date": _csv_date(event),
        "Team": away,
        "Opponent": home,
        "MIN": "20:00",
        "PTS": pts,
        "REB": "0",
        "AST": "0",
        "STL": "0",
        "BLK": "0",
    }


def test_nba_cup_notes_keep_group_through_semifinals_regular():
    """A Cup headline is not enough. Only the CC championship leaves the sample.

    These four events are in the Bucks 2024-25 recording, so the compact
    index has their competition type and notes after the overlay.
    """
    events = load_schedule_events()
    expected = {
        "401703374": ("NBA Cup - Group Play", "STD", GAME_TYPE_REGULAR),
        "401734902": ("NBA Cup - Quarterfinals", "STD", GAME_TYPE_REGULAR),
        "401734906": ("NBA Cup - Semifinals", "STD", GAME_TYPE_REGULAR),
        "401734908": ("NBA Cup Championship", "CC", GAME_TYPE_NBA_CUP),
    }
    by_id = {str(event.get("id")): event for event in events}
    rows = []
    for event_id, (headline, abbreviation, _game_type) in expected.items():
        event = by_id[event_id]
        competition = event.get("competition") or {}
        notes = [note.get("headline") for note in competition.get("notes") or []]
        assert headline in notes
        assert (competition.get("type") or {}).get("abbreviation") == abbreviation
        rows.append(_joined_row(event, f"Cup {event_id}"))
    report = hygiene_rows(rows, events, league="nba")
    labelled = {row["Player"]: row["GameType"] for row in report.rows}
    for event_id, (_headline, _abbreviation, game_type) in expected.items():
        assert labelled[f"Cup {event_id}"] == game_type






def test_recorded_schedules_label_only_cc_finals_as_cup_championship():
    """Pool games, quarterfinals, and semifinals stay regular season.

    The three NBA curl files are unmodified site-API responses. A
    Standard competition that mentions the Cup is not the final. Only
    abbreviation CC / slug commissioners-cup becomes ``cup_championship``,
    and those ids are the two finals in these files.
    """
    sources = (
        (_ESPN / "nba_team_15_schedule_2025_type_2.json", "nba"),
        (_ESPN / "nba_team_18_schedule_2026_type_2.json", "nba"),
        (_ESPN / "nba_team_2_schedule_2027_type_2.json", "nba"),
    )
    cup_ids: list[str] = []
    for path, league in sources:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for raw in payload["events"]:
            event = compact_event(league, raw)
            game_type = game_type_for_event(event)
            comp_type = (event.get("competition") or {}).get("type") or {}
            abbreviation = str(comp_type.get("abbreviation") or "").upper()
            slug = str(comp_type.get("slug") or "")
            headlines = [
                str((note or {}).get("headline") or "")
                for note in (event.get("competition") or {}).get("notes") or []
            ]
            text = " ".join(headlines).lower()
            if abbreviation == "CC" or slug == "commissioners-cup":
                assert game_type == "cup_championship"
                assert game_type == GAME_TYPE_NBA_CUP
                assert any("championship" in headline.lower() for headline in headlines)
                cup_ids.append(str(raw["id"]))
                continue
            if "cup" in text or "commissioner" in text:
                assert abbreviation == "STD"
                assert slug == "standard"
                assert "championship" not in text
                assert game_type == GAME_TYPE_REGULAR
    assert cup_ids == ["401734908", "401809839"]


def test_recorded_team_schedules_match_their_urls_and_isolate_the_cup_final():
    """The three curl files are team schedules, not hand-built events."""
    specs = (
        ("nba_team_2_schedule_2027_type_2.json", "2", "BOS", "2026-27", 80),
        ("nba_team_15_schedule_2025_type_2.json", "15", "MIL", "2024-25", None),
        ("nba_team_18_schedule_2026_type_2.json", "18", "NY", "2025-26", None),
    )
    forbidden = ("apikey", "api_key", "authorization", "bearer ", "access_token")
    for name, team_id, abbreviation, display, exact_count in specs:
        path = _ESPN / name
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for marker in forbidden:
            assert marker not in lowered
        payload = json.loads(text)
        assert str(payload["team"]["id"]) == team_id
        assert payload["team"]["abbreviation"] == abbreviation
        assert payload["requestedSeason"]["displayName"] == display
        events = payload["events"]
        ids = [str(event.get("id")) for event in events]
        assert len(ids) == len(set(ids))
        assert ids
        if exact_count is not None:
            assert len(events) == exact_count
            assert min(event["date"] for event in events).startswith("2026-10-20")
        championships = []
        for event in events:
            competition = event["competitions"][0]
            competitor_ids = {
                str((competitor.get("team") or {}).get("id"))
                for competitor in competition.get("competitors") or []
            }
            assert team_id in competitor_ids
            assert event.get("date")
            if str((competition.get("type") or {}).get("abbreviation") or "").upper() == "CC":
                championships.append(event)
        if team_id == "2":
            assert championships == []
            continue
        assert len(championships) == 1
        notes = [
            note.get("headline")
            for note in championships[0]["competitions"][0].get("notes") or []
        ]
        assert "NBA Cup Championship" in notes
        assert (championships[0].get("seasonType") or {}).get("abbreviation") == "reg"


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a small game log with the columns ``load_csv`` reads."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_RAW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _tagged(player: str, game_type: str, when: str, pts: str, reb: str) -> dict[str, str]:
    """One loaded row. ``pts`` / ``reb`` are what a leak would move."""
    return {
        "Player": player,
        "Season": "2025-2026",
        "Date": when,
        "Team": "Lakers",
        "Opponent": "Celtics",
        "MIN": "24:00",
        "PTS": pts,
        "REB": reb,
        "AST": "0",
        "STL": "0",
        "BLK": "0",
        "GameType": game_type,
    }


def test_unclassified_rows_do_not_move_hit_rate_average_or_double_doubles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Default stats, the mean, and DD history stay on the regular-season row.

    The other rows would each be a hit and a double-double. Playoffs move
    the numbers only when the caller opts in. The Cup final has no opt-in.
    """
    player = "Leak Player"
    rows = [
        _tagged(player, GAME_TYPE_REGULAR, "1/5/2026", "10", "2"),
        _tagged(player, GAME_TYPE_UNCLASSIFIED, "1/6/2026", "40", "12"),
        _tagged(player, GAME_TYPE_AMBIGUOUS, "1/7/2026", "40", "12"),
        _tagged(player, GAME_TYPE_NBA_CUP, "1/8/2026", "40", "12"),
        _tagged(player, GAME_TYPE_PLAYOFFS, "4/20/2026", "40", "12"),
    ]
    path = tmp_path / "nba_player_game_logs.csv"
    _write_rows(path, rows)
    monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
    service = CSVPlayerHistoryService(league="nba")
    service.load_csv()
    cached_types = {game["game_type"] for game in service._cache[player]}
    assert GAME_TYPE_UNCLASSIFIED not in cached_types
    assert GAME_TYPE_AMBIGUOUS not in cached_types
    assert GAME_TYPE_NBA_CUP in cached_types

    default = service.get_player_stats(player, "points", 20)
    assert default["n_games"] == 1
    assert default["mean"] == 10
    assert default["p_over"] == 0
    dd = service.player_dd_history(player)
    assert dd["n_games"] == 1
    assert dd["dd_games"] == 0
    assert dd["prob_dd"] == 0

    with_playoffs = service.get_player_stats(player, "points", 20, include_playoffs=True)
    assert with_playoffs["n_games"] == 2
    assert with_playoffs["p_over"] == 0.5
    still_no_cup = service.player_dd_history(player, include_playoffs=True)
    assert still_no_cup["n_games"] == 2
    assert still_no_cup["dd_games"] == 1
