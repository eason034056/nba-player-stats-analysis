from __future__ import annotations

from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

from app.services.lineup_source_support import (
    detect_team_code,
    make_source_lineup,
    normalize_source_players,
    now_iso,
    parse_position_player_pairs,
    strip_html_lines,
)


# League → RotoWire lineups page URL. The cards share the same selector
# taxonomy across NBA and WNBA — only the URL and position vocabulary
# differ. See docs/research/wnba-rollout/lineup_sources_comparison.md §2.4.
ROTOWIRE_LEAGUE_URLS: dict[str, str] = {
    "nba": "https://www.rotowire.com/basketball/nba-lineups.php",
    "wnba": "https://www.rotowire.com/wnba/lineups.php",
}

# Back-compat alias for the NBA-only constant existing callers may import.
ROTOWIRE_LINEUPS_URL = ROTOWIRE_LEAGUE_URLS["nba"]


def parse_rotowire_html(raw_html: str, date: str) -> dict[str, dict[str, Any]]:
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

        if line in {"Expected Lineup", "Confirmed Lineup"} and len(matchup) == 2 and lineup_index < 2:
            team = matchup[lineup_index]
            opponent = matchup[1 - lineup_index]
            raw_starters, next_index = parse_position_player_pairs(lines, index + 1)
            normalized_starters = normalize_source_players(raw_starters, team, "rotowire")
            parsed[team] = make_source_lineup(
                date=date,
                team=team,
                opponent=opponent,
                home_or_away="AWAY" if lineup_index == 0 else "HOME",
                starters=normalized_starters["display"],
                bench_candidates=[],
                source="rotowire",
                source_status="confirmed" if line == "Confirmed Lineup" else "expected",
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


def fetch_rotowire_lineups(date: str, league: str = "nba") -> dict[str, dict[str, Any]]:
    """Fetch the RotoWire lineups page for the given league and date.

    Default `league="nba"` preserves all existing callers verbatim. Pass
    `league="wnba"` to fetch the WNBA page and run it through the BS4 parser
    that handles the WNBA-specific position vocabulary (`{G, F, C}`) and
    surfaces `<a title="Full Name">` as the canonical player name. The NBA
    line-strip parser is intentionally left untouched per the SPO-34
    guardrail "NBA path unchanged".
    """
    url = ROTOWIRE_LEAGUE_URLS.get(league)
    if url is None:
        raise ValueError(f"Unsupported league for RotoWire lineups: {league!r}")
    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "no-vig-lineup-bot/1.0"},
    )
    response.raise_for_status()
    if league == "wnba":
        return parse_rotowire_wnba_html(response.text, date)
    return parse_rotowire_html(response.text, date)


# === WNBA path (BS4-based) ====================================================
#
# Why BS4 instead of the NBA line-strip approach:
#
# 1. WNBA's `<a title="Full Name">N. Hiedeman</a>` carries the full name in
#    an attribute while the visible text is the broadcast "N. Hiedeman".
#    Without a roster CSV to disambiguate "N. Hiedeman", the line-strip path
#    would leave the player unresolved. Reading `title=` sidesteps the need
#    for a WNBA roster cache entirely.
#
# 2. The WNBA card uses `is-expected` vs `is-confirmed` on
#    `li.lineup__status` — a sports-betting-domain signal (CLAUDE.md §
#    Domain Lenses — "Lineup / injury validity") that must surface verbatim,
#    not collapsed. The line-strip approach loses the class attribute on the
#    way through `strip_html_lines`.
#
# 3. OUT players are tagged with `lineup__inj` ("OUT") plus
#    `is-pct-play-{0,25,50,75,100}`. Capturing the integer pct as a sortable
#    field is more useful downstream than a free-text "OUT" string.
#
# Selectors are grounded in
# docs/research/wnba-rollout/lineup_sources_comparison.md §2.2 / §2.4. The
# committed `rotowire_wnba_sample.html` is the regression baseline pinned by
# the unit test in tests/test_lineup_provider_rotowire_wnba.py.

_PCT_PLAY_PREFIX = "is-pct-play-"


def _extract_pct_play(li: Tag) -> int | None:
    """Read the `is-pct-play-N` class from a player row.

    Returns the integer N (0/25/50/75/100 observed in the 2026-05-13 sample)
    or None if absent. Preserved verbatim so the betting layer can apply the
    lineup-validity domain lens itself.
    """
    for cls in li.get("class") or []:
        if isinstance(cls, str) and cls.startswith(_PCT_PLAY_PREFIX):
            try:
                return int(cls[len(_PCT_PLAY_PREFIX):])
            except ValueError:
                return None
    return None


def _player_name_from_anchor(anchor: Tag | None) -> str | None:
    """Prefer `<a title="Full Name">` over the visible broadcast text.

    Visible text is "N. Hiedeman"; title is "Natisha Hiedeman". For Sports
    Lab's downstream join against the odds-API player list (which uses full
    names), the title is the correct key.
    """
    if anchor is None:
        return None
    title = (anchor.get("title") or "").strip()
    if title:
        return title
    text = anchor.get_text(strip=True)
    return text or None


def _parse_card(card: Tag, date: str) -> dict[str, dict[str, Any]]:
    """Parse one `<div class="lineup is-nba…">` card into team-keyed lineups.

    Returns up to two entries (visiting + home). Cards whose visiting/home
    abbreviation cannot be resolved to a WNBA team code are skipped silently
    — e.g. RotoWire's `is-tools` widget card has no team block.
    """
    result: dict[str, dict[str, Any]] = {}

    abbreviations: dict[str, str] = {}
    for team_anchor in card.select("a.lineup__team"):
        classes = team_anchor.get("class") or []
        if "is-visit" in classes:
            side = "visit"
        elif "is-home" in classes:
            side = "home"
        else:
            continue
        abbr_el = team_anchor.select_one(".lineup__abbr")
        if abbr_el is None:
            continue
        abbreviations[side] = abbr_el.get_text(strip=True)

    if "visit" not in abbreviations or "home" not in abbreviations:
        return result

    visit_code = detect_team_code(abbreviations["visit"], league="wnba")
    home_code = detect_team_code(abbreviations["home"], league="wnba")
    if not visit_code or not home_code:
        return result

    for ul in card.select("ul.lineup__list"):
        ul_classes = ul.get("class") or []
        if "is-visit" in ul_classes:
            team, opponent, home_or_away = visit_code, home_code, "AWAY"
        elif "is-home" in ul_classes:
            team, opponent, home_or_away = home_code, visit_code, "HOME"
        else:
            continue

        status_el = ul.select_one("li.lineup__status")
        if status_el is None:
            source_status = "unknown"
        elif "is-confirmed" in (status_el.get("class") or []):
            source_status = "confirmed"
        elif "is-expected" in (status_el.get("class") or []):
            source_status = "expected"
        else:
            source_status = status_el.get_text(strip=True).lower() or "unknown"

        starters: list[str] = []
        out_players: list[dict[str, Any]] = []
        questionable_players: list[dict[str, Any]] = []

        # Player rows are emitted in document order: 5 projected starters
        # first (each with its own pct, which may be <100 if questionable),
        # then OUT/bench rows. The first 5 non-OUT rows = projected lineup
        # regardless of pct — validated against the 2026-05-13 sample's
        # CHI side (slot-2 is pct-50 yet is the team's projected SG).
        for li in ul.select("li.lineup__player"):
            anchor = li.find("a")
            player_name = _player_name_from_anchor(anchor)
            if not player_name:
                continue
            pos_el = li.select_one(".lineup__pos")
            position = pos_el.get_text(strip=True) if pos_el else None
            inj_el = li.select_one(".lineup__inj")
            injury_status = inj_el.get_text(strip=True) if inj_el else None
            pct_play = _extract_pct_play(li)
            is_out = pct_play == 0 or (injury_status or "").upper() == "OUT"

            row = {
                "player": player_name,
                "position": position,
                "injury_status": injury_status,
                "pct_play": pct_play,
            }

            if len(starters) < 5 and not is_out:
                starters.append(player_name)
                if pct_play is not None and pct_play < 100:
                    questionable_players.append(row)
            elif is_out:
                out_players.append(row)
            else:
                questionable_players.append(row)

        deduped = list(dict.fromkeys(starters))[:5]

        lineup = make_source_lineup(
            date=date,
            team=team,
            opponent=opponent,
            home_or_away=home_or_away,
            starters=deduped,
            bench_candidates=[],
            source="rotowire",
            source_status=source_status,
            raw_starters=deduped,
            canonical_starters=deduped,
            unresolved_starters=[],
            normalization_warnings=[],
            updated_at=now_iso(),
        )
        # Surface WNBA-specific extras on the source snapshot so the
        # downstream agent layer can flag questionable starters and
        # invalidate props for OUT players (CLAUDE.md § Domain Lenses).
        snapshot = lineup["source_snapshots"]["rotowire"]
        snapshot["out_players"] = out_players
        snapshot["questionable_players"] = questionable_players
        result[team] = lineup

    return result


def parse_rotowire_wnba_html(raw_html: str, date: str) -> dict[str, dict[str, Any]]:
    """Parse a RotoWire WNBA lineups page into team-keyed lineup snapshots.

    Selector basis: `div.lineup.is-nba` cards (RotoWire reuses the literal
    `is-nba` class on the WNBA page — see comparison doc §2.4). Cards with
    no parseable team block (the `is-tools` widget) are skipped.
    """
    soup = BeautifulSoup(raw_html, "lxml")
    parsed: dict[str, dict[str, Any]] = {}
    for card in soup.select("div.lineup.is-nba"):
        parsed.update(_parse_card(card, date))
    return parsed
