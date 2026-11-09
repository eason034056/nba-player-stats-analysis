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
| `backend/app/services/csv_downloader.py` | Fetches the live ESPN schedule, hygiened via a temp file and `os.replace`. Returns failure when any row stays unclassified. An exception keeps the previous file. |
| `backend/app/services/espn_schedule.py` | Compacts site-API events (including competition notes and type) and fetches the seasons that overlap the CSV. |
| `tests/fixtures/espn/nba_team_*_schedule_*.json` | Curl recordings: Celtics 2026-27 regular season, Bucks 2024-25 regular season (Cup final `401734908`), Knicks 2025-26 regular season (Cup final `401809839`). |
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

### Review fixes

**Unmatched rows are kept.** A row that does not join a schedule event used to be labeled `unclassified` and deleted. The committed fixture had no NBA event on or after 2026-10-01, so a download of the 2026-27 season would have deleted every one of those games, and `download()` still returned success. An unknown join is not evidence the row is Summer League or preseason. Those rows now stay in the file as `unclassified`. `load_csv` still skips that token, so they do not enter stats, picks, or the historical agent. Hygiene logs a warning with the count. `download()` logs an error and returns `False` when any row is unclassified or ambiguous, so the miss is not a silent success. The hygiened file is still published: refusing to write would also throw away the rows that did classify, and the raw scrape always contains a few college lines. A failed ESPN fetch, or an exception during hygiene, does not replace the canonical file. The rewrite runs on a temp file and `os.replace` publishes it only after hygiene returns.

**The download fetches the live schedule.** `CSVDownloaderService.download` requests ESPN team schedules for every season whose recorded `startDate`/`endDate` overlaps a date in the file (parent league plus G League and Summer League). Tests and `scripts/hygiene_game_logs.py` still read the fixture and do not call the network. The offline path folds three curl recordings onto the compact index at load time:

| File | URL |
|---|---|
| `tests/fixtures/espn/nba_team_2_schedule_2027_type_2.json` | `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/2/schedule?season=2027&seasontype=2` |
| `tests/fixtures/espn/nba_team_15_schedule_2025_type_2.json` | `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/15/schedule?season=2025&seasontype=2` |
| `tests/fixtures/espn/nba_team_18_schedule_2026_type_2.json` | `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/18/schedule?season=2026&seasontype=2` |

The Celtics file is the 2026-27 regular season (`requestedSeason.displayName` `2026-27`, 80 events). Opening night in that payload is 2026-10-20 at Detroit, not Celtics vs Knicks on 2026-10-21, which is why the QA row for that fake matchup stays `unclassified` and is kept. The Bucks 2024-25 file contains event `401734908` (Bucks at Thunder) and the Knicks 2025-26 file contains `401809839` (Spurs at Knicks).

**NBA Cup championship is not the regular season.** ESPN's `seasonType.abbreviation` is `reg` for group play, the quarterfinals, the semifinals, and the championship. The recorded competition type on the two finals is abbreviation `CC`, slug `commissioners-cup`, and the notes headline is `NBA Cup Championship`. Group play, quarterfinals, and semifinals in the same payloads are type Standard. The finals are stored as `nba_cup_championship`. They stay in the file so the game is identifiable, and they are outside the default regular-season sample. Group, quarterfinal, and semifinal games stay `regular_season` (they count toward the 82). The shipped CSVs have no championship rows, so the row counts above do not move.

**Hit rates move because the default sample is the regular season.** Playoffs and the play-in stay in the file and stay out of `get_player_stats`, daily picks, and the historical agent unless the caller passes `include_playoffs` or `include_play_in`. Both flags already exist on the player-history APIs and default off. There is no new UI control, and the historical agent has no opt-in: a regular-season prop is not a playoff series. Summer League and preseason never enter that sample. That is why a player's hit rate on this branch differs from a sample that still mixed those games in.

## Tests

`cd backend && pytest` (this environment, no Redis), after the review fixes:

- **639 passed, 8 skipped, 2 failed**
- Skipped: `RUN_INTEGRATION=1` live tests (scoreboard shape, and the 2026-27 Celtics schedule URL against the recorded file)
- Failed, not changed here (both die in slowapi before the handler, Redis `ConnectionError`, and this environment has no Redis):
  - `tests/test_agent_chat.py::test_agent_chat_endpoint_validates_action_and_uses_service`
  - `tests/test_lineup_consensus.py::test_lineups_api_returns_team_count`

`backend/tests/test_game_log_hygiene.py` loads recorded events by id (no hand-built ESPN payloads): season label expansion, Summer League and preseason dropped, playoffs and play-in kept, G League dropped, unmatched rows kept with a warning, Sixers → recorded `76ers`, parent-league tie-break, Maria Conde dedupe, the curl-recorded 2026-27 Celtics opener labeled `2026-2027` / `regular_season`, loader default vs `include_playoffs` / `include_play_in`, NBA Cup championship outside the default sample, and the shipped CSVs. `backend/tests/test_spo97_season_edges.py` now passes the Cup-final and future-game cases with the xfail removed. The downloader tests cover a non-game-log file (no ESPN fetch), a hygiene exception that leaves the previous file in place, and an unclassified row that is kept while `download()` returns `False`.

## Follow-ups

- The RealGM scraper still stamps one season and selects "All Games". Fixing that repository would stop the bad file at the source. This repo's ingest now corrects it on the way in.
- Re-run `python scripts/explore_espn_schedule_api.py` when a new season starts, then `python scripts/hygiene_game_logs.py`. A download already fetches the live schedule for the seasons in the file. Rows that still do not join are kept as `unclassified`, not guessed and not deleted.
- 43 NBA rows had no schedule hit on the first pass (college, a handful of G League dates, one international exhibition). They were removed from the canonical file then. A later download keeps new unmatched rows and returns failure instead of deleting them.
- WNBA season 2026 in this CSV is only the 2026-05-08 regular-season slate. Later games show up on the next scrape plus a fixture refresh.
