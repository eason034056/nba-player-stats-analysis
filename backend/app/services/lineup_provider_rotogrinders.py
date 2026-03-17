from __future__ import annotations

from typing import Any

import requests

from app.services.lineup_source_support import (
    detect_team_code,
    make_source_lineup,
    normalize_source_players,
    now_iso,
    parse_named_player_block,
    strip_html_lines,
)


ROTOGRINDERS_LINEUPS_URL = "https://rotogrinders.com/lineups/nba"


def parse_rotogrinders_html(raw_html: str, date: str) -> dict[str, dict[str, Any]]:
    lines = strip_html_lines(raw_html)
    parsed: dict[str, dict[str, Any]] = {}

    pending_matchup: list[str] = []
    matchup: list[str] = []
    lineup_index = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        team_code = detect_team_code(line)
        if team_code:
            if not pending_matchup or pending_matchup[-1] != team_code:
                pending_matchup.append(team_code)
            if len(pending_matchup) == 2:
                matchup = pending_matchup[:]
                pending_matchup = []
                lineup_index = 0
            index += 1
            continue

        if line == "Starters" and len(matchup) == 2 and lineup_index < 2:
            team = matchup[lineup_index]
            opponent = matchup[1 - lineup_index]
            raw_starters, next_index = parse_named_player_block(
                lines,
                index + 1,
                stop_tokens={"Bench", "Starters"},
                limit=5,
            )
            normalized_starters = normalize_source_players(raw_starters, team, "rotogrinders")
            bench_candidates: list[str] = []
            if next_index < len(lines) and lines[next_index] == "Bench":
                raw_bench, next_index = parse_named_player_block(
                    lines,
                    next_index + 1,
                    stop_tokens={"Starters", "Bench"},
                    limit=7,
                )
                bench_candidates = normalize_source_players(raw_bench, team, "rotogrinders")["display"]

            parsed[team] = make_source_lineup(
                date=date,
                team=team,
                opponent=opponent,
                home_or_away="AWAY" if lineup_index == 0 else "HOME",
                starters=normalized_starters["display"],
                bench_candidates=bench_candidates,
                source="rotogrinders",
                source_status="projected",
                raw_starters=raw_starters,
                canonical_starters=normalized_starters["canonical"],
                unresolved_starters=normalized_starters["unresolved"],
                normalization_warnings=normalized_starters["warnings"],
                updated_at=now_iso(),
            )
            lineup_index += 1
            if lineup_index >= 2:
                matchup = []
            index = next_index
            continue

        index += 1

    return parsed


def fetch_rotogrinders_lineups(date: str) -> dict[str, dict[str, Any]]:
    response = requests.get(
        ROTOGRINDERS_LINEUPS_URL,
        timeout=20,
        headers={"User-Agent": "no-vig-lineup-bot/1.0"},
    )
    response.raise_for_status()
    return parse_rotogrinders_html(response.text, date)
