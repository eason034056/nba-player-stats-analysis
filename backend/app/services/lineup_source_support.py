from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any


TIME_LINE_RE = re.compile(r"\d+:\d+\s*(AM|PM)\s*ET", flags=re.IGNORECASE)


def _normalize_lookup_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("*", "").strip()).lower()


TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    "ATL": ("Atlanta Hawks", "Hawks", "ATL"),
    "BOS": ("Boston Celtics", "Celtics", "BOS"),
    "BKN": ("Brooklyn Nets", "Nets", "BKN"),
    "CHA": ("Charlotte Hornets", "Hornets", "CHA"),
    "CHI": ("Chicago Bulls", "Bulls", "CHI"),
    "CLE": ("Cleveland Cavaliers", "Cavaliers", "Cavs", "CLE"),
    "DAL": ("Dallas Mavericks", "Mavericks", "Mavs", "DAL"),
    "DEN": ("Denver Nuggets", "Nuggets", "DEN"),
    "DET": ("Detroit Pistons", "Pistons", "DET"),
    "GSW": ("Golden State Warriors", "Warriors", "Golden State", "Golden St", "GSW"),
    "HOU": ("Houston Rockets", "Rockets", "HOU"),
    "IND": ("Indiana Pacers", "Pacers", "IND"),
    "LAC": ("Los Angeles Clippers", "Clippers", "LA Clippers", "LAC"),
    "LAL": ("Los Angeles Lakers", "Lakers", "LA Lakers", "LAL"),
    "MEM": ("Memphis Grizzlies", "Grizzlies", "MEM"),
    "MIA": ("Miami Heat", "Heat", "MIA"),
    "MIL": ("Milwaukee Bucks", "Bucks", "MIL"),
    "MIN": ("Minnesota Timberwolves", "Timberwolves", "Wolves", "MIN"),
    "NOP": ("New Orleans Pelicans", "Pelicans", "NOP"),
    "NYK": ("New York Knicks", "Knicks", "NYK"),
    "OKC": ("Oklahoma City Thunder", "Thunder", "OKC"),
    "ORL": ("Orlando Magic", "Magic", "ORL"),
    "PHI": ("Philadelphia 76ers", "76ers", "Sixers", "PHI"),
    "PHX": ("Phoenix Suns", "Suns", "PHX"),
    "POR": ("Portland Trail Blazers", "Trail Blazers", "Blazers", "POR"),
    "SAC": ("Sacramento Kings", "Kings", "SAC"),
    "SAS": ("San Antonio Spurs", "Spurs", "SAS"),
    "TOR": ("Toronto Raptors", "Raptors", "TOR"),
    "UTA": ("Utah Jazz", "Jazz", "UTA"),
    "WAS": ("Washington Wizards", "Wizards", "WAS"),
}

TEAM_LOOKUP: dict[str, str] = {}
for code, aliases in TEAM_ALIASES.items():
    TEAM_LOOKUP[_normalize_lookup_key(code)] = code
    for alias in aliases:
        TEAM_LOOKUP[_normalize_lookup_key(alias)] = code

POSITION_TOKENS = {"PG", "SG", "SF", "PF", "C", "G", "F"}
SUFFIX_TOKENS = {"JR", "JR.", "SR", "SR.", "II", "III", "IV", "V"}
ROTOWIRE_STATUS_TOKENS = {"PROB", "PROBABLE", "QUES", "QUESTIONABLE", "DOUBT", "DOUBTFUL", "OUT", "GTD"}
ROTOWIRE_IGNORE_TOKENS = ROTOWIRE_STATUS_TOKENS | {"INJ", "DAY-TO-DAY", "DNP"}
IGNORE_LINE_PATTERNS = (
    "watch now",
    "tickets",
    "alerts",
    "lineups",
    "props",
    "news",
    "injury report",
    "starting lineups",
    "expert survey",
)
NON_PLAYER_LINE_KEYS = {
    "admin",
    "edit",
    "projected minutes",
    "on/off court stats",
    "may not play",
    "lineup not released",
    "referees:",
    "not announced yet",
    "line",
    "spread",
    "o/u",
    "play 1-day fantasy basketball to win tonight",
    "-->",
    "–",
}

_TEAM_ROSTER_CACHE: dict[str, list[str]] | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def strip_html_lines(raw_html: str) -> list[str]:
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw_html)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</(div|p|li|ul|ol|section|article|h1|h2|h3|h4|h5|tr|td|th)>", "\n", cleaned)
    cleaned = re.sub(r"<[^>]+>", "\n", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("\xa0", " ")

    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if line.lower() in {"nba", "dfs"}:
            continue
        lines.append(line)
    return lines


def detect_team_code(raw_line: str) -> str | None:
    line = re.sub(r"\(\d+\s*-\s*\d+\)", "", raw_line).strip()
    line = TIME_LINE_RE.sub("", line).strip()
    if not line:
        return None
    return TEAM_LOOKUP.get(_normalize_lookup_key(line))


def _is_non_player_line(line: str) -> bool:
    lowered = _normalize_lookup_key(line)
    if lowered in NON_PLAYER_LINE_KEYS:
        return True
    return any(pattern in lowered for pattern in IGNORE_LINE_PATTERNS)


def _is_time_line(line: str) -> bool:
    return bool(TIME_LINE_RE.fullmatch(line))


def _is_position_token(token: str) -> bool:
    cleaned = token.upper().rstrip(",")
    if cleaned in POSITION_TOKENS:
        return True
    parts = [part for part in cleaned.split("/") if part]
    return bool(parts) and all(part in POSITION_TOKENS for part in parts)


def is_control_line(line: str) -> bool:
    if not line:
        return True
    if _is_non_player_line(line):
        return True
    if detect_team_code(line):
        return True
    if _is_time_line(line):
        return True
    if line in {"Expected Lineup", "Confirmed Lineup", "Starters", "Bench"}:
        return True
    return False


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("*", "").strip())


def _normalize_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _last_name_key(value: str) -> str:
    tokens = [token for token in _normalize_spaces(value).split() if token]
    while tokens and tokens[-1].upper().rstrip(".") in SUFFIX_TOKENS:
        tokens.pop()
    if not tokens:
        return ""
    return re.sub(r"[^a-z]", "", tokens[-1].lower())


def _first_initial(value: str) -> str:
    tokens = [token for token in _normalize_spaces(value).split() if token]
    if not tokens:
        return ""
    token = re.sub(r"[^A-Za-z]", "", tokens[0])
    return token[:1].lower()


def _looks_abbreviated_name(value: str) -> bool:
    tokens = _normalize_spaces(value).split()
    if len(tokens) < 2:
        return False
    first = re.sub(r"[^A-Za-z.]", "", tokens[0])
    first_plain = first.replace(".", "")
    return len(first_plain) == 1


def clean_player_name(line: str) -> str | None:
    cleaned = _normalize_spaces(line)
    if not cleaned:
        return None
    if _is_non_player_line(cleaned):
        return None
    if not re.search(r"[A-Za-z]", cleaned):
        return None
    alpha_tokens = [token for token in cleaned.split() if re.search(r"[A-Za-z]", token)]
    if len(alpha_tokens) < 2:
        return None
    return cleaned


def normalize_rotowire_player_candidate(raw_name: str) -> str | None:
    candidate = clean_player_name(raw_name)
    if not candidate:
        return None

    tokens = candidate.split()
    while tokens and tokens[-1].upper().rstrip(".") in ROTOWIRE_IGNORE_TOKENS:
        tokens.pop()
    if not tokens:
        return None
    return _normalize_spaces(" ".join(tokens))


def normalize_rotogrinders_player_candidate(raw_name: str) -> str | None:
    candidate = clean_player_name(raw_name)
    if not candidate:
        return None

    name_tokens: list[str] = []
    for token in candidate.split():
        if _is_position_token(token):
            break
        if token.startswith("$") or re.search(r"\d", token):
            break
        name_tokens.append(token.rstrip(","))

    if not name_tokens:
        return None
    return _normalize_spaces(" ".join(name_tokens))


def _build_team_roster_cache() -> dict[str, list[str]]:
    from app.services.csv_player_history import CSVPlayerHistoryService

    service = CSVPlayerHistoryService()
    service.load_csv()

    roster_map: dict[str, list[str]] = {code: [] for code in TEAM_ALIASES}
    for player_name, logs in service._cache.items():
        if not logs:
            continue
        latest_team = detect_team_code(logs[0].get("team", "") or "")
        if not latest_team:
            continue
        roster_map.setdefault(latest_team, []).append(player_name)

    for team_code, players in roster_map.items():
        roster_map[team_code] = sorted(dict.fromkeys(players))
    return roster_map


def _get_team_roster_candidates(team_code: str) -> list[str]:
    global _TEAM_ROSTER_CACHE
    if _TEAM_ROSTER_CACHE is None:
        _TEAM_ROSTER_CACHE = _build_team_roster_cache()
    return list(_TEAM_ROSTER_CACHE.get(team_code, []))


def resolve_canonical_player_name(raw_name: str, team_code: str) -> dict[str, str | None]:
    candidate = _normalize_spaces(raw_name)
    if not candidate:
        return {
            "canonical_name": None,
            "resolution_status": "unresolved",
            "resolution_reason": "empty_candidate",
        }

    roster = _get_team_roster_candidates(team_code)
    normalized_candidate = _normalize_name_key(candidate)
    for roster_name in roster:
        if _normalize_name_key(roster_name) == normalized_candidate:
            return {
                "canonical_name": roster_name,
                "resolution_status": "exact",
                "resolution_reason": "roster_exact_match",
            }

    if _looks_abbreviated_name(candidate):
        if not roster:
            return {
                "canonical_name": None,
                "resolution_status": "unresolved",
                "resolution_reason": "missing_team_roster",
            }

        matches = [
            roster_name
            for roster_name in roster
            if _last_name_key(roster_name) == _last_name_key(candidate)
            and _first_initial(roster_name) == _first_initial(candidate)
        ]
        if len(matches) == 1:
            return {
                "canonical_name": matches[0],
                "resolution_status": "team_resolved",
                "resolution_reason": "initials_team_match",
            }
        if len(matches) > 1:
            return {
                "canonical_name": None,
                "resolution_status": "unresolved",
                "resolution_reason": "ambiguous_team_match",
            }
        return {
            "canonical_name": None,
            "resolution_status": "unresolved",
            "resolution_reason": "no_team_match",
        }

    return {
        "canonical_name": candidate,
        "resolution_status": "exact",
        "resolution_reason": "full_name",
    }


def normalize_source_players(raw_names: list[str], team_code: str, source: str) -> dict[str, list[str]]:
    display_names: list[str] = []
    canonical_names: list[str] = []
    unresolved_names: list[str] = []
    warnings: list[str] = []

    for raw_name in raw_names:
        candidate = (
            normalize_rotowire_player_candidate(raw_name)
            if source == "rotowire"
            else normalize_rotogrinders_player_candidate(raw_name)
        )
        if not candidate:
            continue

        resolution = resolve_canonical_player_name(candidate, team_code)
        canonical_name = resolution.get("canonical_name")
        if canonical_name:
            display_names.append(str(canonical_name))
            canonical_names.append(str(canonical_name))
        else:
            display_names.append(candidate)
            unresolved_names.append(candidate)
            warnings.append(f"unresolved: {candidate}")

    return {
        "display": list(dict.fromkeys(display_names)),
        "canonical": list(dict.fromkeys(canonical_names)),
        "unresolved": list(dict.fromkeys(unresolved_names)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def make_source_lineup(
    *,
    date: str,
    team: str,
    opponent: str,
    home_or_away: str,
    starters: list[str],
    bench_candidates: list[str],
    source: str,
    source_status: str,
    raw_starters: list[str] | None = None,
    canonical_starters: list[str] | None = None,
    unresolved_starters: list[str] | None = None,
    normalization_warnings: list[str] | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    deduped_starters = list(dict.fromkeys(starters))
    deduped_bench = [player for player in dict.fromkeys(bench_candidates) if player not in deduped_starters]
    deduped_raw = list(dict.fromkeys(raw_starters or []))
    deduped_canonical = list(dict.fromkeys(canonical_starters or []))
    deduped_unresolved = [player for player in dict.fromkeys(unresolved_starters or []) if player not in deduped_canonical]
    warnings = list(dict.fromkeys(normalization_warnings or []))
    return {
        "date": date,
        "team": team,
        "opponent": opponent,
        "home_or_away": home_or_away,
        "status": "projected" if len(deduped_starters) == 5 and not deduped_unresolved else ("partial" if deduped_starters else "unavailable"),
        "starters": deduped_starters[:5],
        "bench_candidates": deduped_bench[:7],
        "sources": [source],
        "source_disagreement": False,
        "confidence": "low",
        "updated_at": updated_at or now_iso(),
        "source_snapshots": {
            source: {
                "team": team,
                "opponent": opponent,
                "home_or_away": home_or_away,
                "status": source_status,
                "starters": deduped_starters[:5],
                "bench_candidates": deduped_bench[:7],
                "raw_starters": deduped_raw[:5],
                "canonical_starters": deduped_canonical[:5],
                "unresolved_starters": deduped_unresolved[:5],
                "normalization_warnings": warnings[:10],
            }
        },
    }


def parse_position_player_pairs(lines: list[str], start_index: int) -> tuple[list[str], int]:
    starters: list[str] = []
    index = start_index
    while index < len(lines) and len(starters) < 5:
        line = lines[index]
        if is_control_line(line):
            break
        if line in POSITION_TOKENS and index + 1 < len(lines):
            player = clean_player_name(lines[index + 1])
            if player:
                starters.append(player)
            index += 2
            continue
        player = clean_player_name(line)
        if player:
            starters.append(player)
        index += 1
    return starters[:5], index


def parse_named_player_block(lines: list[str], start_index: int, stop_tokens: set[str], limit: int) -> tuple[list[str], int]:
    players: list[str] = []
    index = start_index
    while index < len(lines):
        line = lines[index]
        if line in stop_tokens or detect_team_code(line):
            break
        if _is_time_line(line):
            break
        player = clean_player_name(line)
        if player:
            players.append(player)
            if len(players) >= limit:
                index += 1
                break
        index += 1
    return players[:limit], index
