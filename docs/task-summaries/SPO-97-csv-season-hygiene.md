# SPO-97 — Game-log season labels and game-type hygiene

- **Ticket:** SPO-97
- **Branch:** `feature/SPO-97-csv-season-hygiene`
- **Base:** `dev`

## Summary

The NBA game log stamped `Season=2025-2026` on every row, and the WNBA file stored Maria Conde's 2026-05-08 game twice. Both files are scraped from RealGM with "All Games" selected, so Summer League, preseason, the regular season, playoffs, and (in the NBA file) G League and college rows shared one season string.

Each row is now joined to a recorded ESPN schedule on local date plus both club names. `Season` is rewritten from that event and a `GameType` column is added. Summer League and preseason are removed from the canonical CSVs. Playoffs and the play-in stay, labeled, and the stats / picks / historical-agent paths read regular-season rows unless the caller opts in.

## Changes

| File | Change |
|---|---|
| `data/nba_player_game_logs.csv` | Relabeled and filtered. Before: **31,572** rows, every `Season` = `2025-2026` (849 of them July 2025; 3,416 dated before 2025-10-21). After: **28,820** rows. |
| `data/wnba_player_game_logs.csv` | Relabeled, preseason removed, Maria Conde deduped. Before: **5,365** rows (5,046 labeled 2025, 319 labeled 2026). After: **4,875** rows. |
| `backend/app/services/game_log_hygiene.py` | Join, relabel, dedupe, drop. |
| `scripts/explore_espn_schedule_api.py` | Records the ESPN team-schedule payloads. |
| `tests/fixtures/espn/` | Recorded schedule (4,882 events), team directory, and one raw scoreboard. |
| `scripts/hygiene_game_logs.py` | Rewrites both CSVs from the fixture. No network. |
| `backend/app/services/csv_downloader.py` | Runs hygiene after a download so a fresh scrape does not put the bad labels back. |
| `backend/app/services/csv_player_history.py` | Skips non-canonical game types at load. Stats default to `regular_season`. `include_playoffs` / `include_play_in` opt in. |
| `backend/app/api/nba.py`, `backend/app/api/wnba.py` | Those two flags on player-history and player-dd-history. Game logs return `game_type` and `season`. |
| `scripts/agents/tools/historical.py` | `_games_for` keeps regular-season rows. Nikola Jokic: 65 regular-season games used, 6 playoff games left in the cache. |
| `backend/tests/test_game_log_hygiene.py` | Season label, drop rules, playoff split, dedupe, shipped-file checks. |
| `README.md` | Curl instructions now run the hygiene script. |

### NBA row counts

| | Rows |
|---|---|
| Before | 31,572 |
| After | 28,820 |
| Kept `regular_season` | 27,200 |
| Kept `playoffs` | 1,488 |
| Kept `play_in` | 132 |
| Kept season `2025-2026` | 28,090 |
| Kept season `2024-2025` | 730 |
| Dropped `preseason` | 1,803 |
| Dropped `summer_league` | 858 (the 849 July 2025 rows, plus 4 from August 2021 and 5 from July 2024) |
| Dropped `g_league` | 48 |
| Dropped `unclassified` | 43 (Georgetown college logs, G League rows the recorded schedule did not list, one exhibition vs Ratiopharm Ulm) |

July 2025 rows remaining: 0. `2025-2026` regular-season rows dated before 2025-10-21: 0.

### WNBA row counts

| | Rows |
|---|---|
| Before | 5,365 |
| After | 4,875 |
| Kept `regular_season` | 4,493 |
| Kept `playoffs` | 382 |
| Kept season `2025` | 4,836 |
| Kept season `2026` | 39 |
| Dropped `preseason` | 489 |
| Duplicates removed | 1 |

Maria Conde, 2026-05-08, Tempo vs Mystics: one row, `Season=2026`, `GameType=regular_season`. No other player-game is stored under two seasons. The 39 season-2026 rows are the 2026-05-08 slate. ESPN's recorded schedule marks the April 25–May 3, 2026 WNBA games as preseason; regular season in that payload starts 2026-05-08. Those preseason rows were dropped rather than left under a guessed label.

## Why

**Drop Summer League and preseason from the canonical file**, and also refuse them in `load_csv` if a raw file is loaded anyway.

The historical agent reads `csv._cache` directly. Daily picks and the dataset sampler call `get_player_stats`. A flag that every one of those call sites must remember will be missed, and a Summer League minute total will move a prop. Removing the rows from the file the product ships means a missed filter cannot see them. The loader drop is the second gate for a download that has not been rewritten yet.

Playoffs stay in the file with `GameType=playoffs` (and `play_in` where the schedule has a play-in). They are real league games. Callers pass `include_playoffs=true` or `include_play_in=true`. The default is regular season only, because a regular-season prop is not a seven-game series.

G League and college rows came in through the same "All Games" scrape. They are not an NBA season. They are dropped with Summer League and preseason. Forty NBA rows matched both an NBA game and a G League game that reuse the same nicknames on the same night (Lakers/Suns, Bulls/Magic). The NBA event is kept. The G League clubs in this file otherwise use their own names (`Remix`, `Blue`).

The wrong label is not produced by this repo's parser. Upstream `scrape_nba.py` sets `SEASON = "2025-2026"` and writes that constant onto every row (`cell_data_with_info = [player_name, SEASON] + cell_data`) after selecting "All Games". Upstream `scrape_wnba.py` dedupes on `Player + Season + Date + Team + Opponent`, so the same game stored under two dropdown seasons is kept twice. That scraper is a different repository. The ingest path in this repo is `CSVDownloaderService.download` and `scripts/hygiene_game_logs.py`. Both now run the rewrite, so regenerating the CSV from the raw URL does not restore the bad season column.

Season and game type come from `tests/fixtures/espn/schedule_events.json`, recorded by `scripts/explore_espn_schedule_api.py` from `site.api.espn.com` team schedules. NBA `displayName` `"2025-26"` is expanded to `"2025-2026"`. WNBA `displayName` is the calendar year (`"2025"`, `"2026"`). Game type follows the recorded `seasonType.abbreviation` (`pre`, `reg`, `post`, `playin`), except events whose fixture league slug contains `summer` (those are `summer_league` even when ESPN calls that league's own season `reg`) and `nba-development` (those are `g_league`). No season boundary in the code is a hand-typed calendar cutoff.

## Tests

`cd backend && pytest` (this environment, no Redis):

- **621 passed, 7 skipped, 2 failed**
- Skipped: `RUN_INTEGRATION=1` live tests, including the new ESPN scoreboard shape check
- Failed, not changed here (both die in slowapi before the handler, Redis `ConnectionError`, and this environment has no Redis):
  - `tests/test_agent_chat.py::test_agent_chat_endpoint_validates_action_and_uses_service`
  - `tests/test_lineup_consensus.py::test_lineups_api_returns_team_count`

New coverage in `backend/tests/test_game_log_hygiene.py`: season label expansion, Summer League and preseason dropped, playoffs and play-in kept and labeled, G League and unmatched rows dropped, Sixers → recorded `76ers`, parent-league tie-break, Maria Conde dedupe, loader default vs `include_playoffs` / `include_play_in`, and the shipped CSVs (no July 2025 NBA rows, no `2025-2026` regular-season row before 2025-10-21, one Conde row on 2026).

## Follow-ups

- The RealGM scraper still stamps one season and selects "All Games". Fixing that repository would stop the bad file at the source. This repo's ingest now corrects it on the way in.
- Re-run `python scripts/explore_espn_schedule_api.py` when a new season starts, then `python scripts/hygiene_game_logs.py`. Dates absent from the fixture are left unclassified and dropped, not guessed.
- 43 NBA rows had no schedule hit (college, a handful of G League dates, one international exhibition). They are not in the canonical file.
- WNBA season 2026 in this CSV is only the 2026-05-08 regular-season slate. Later games show up on the next scrape plus a fixture refresh.
