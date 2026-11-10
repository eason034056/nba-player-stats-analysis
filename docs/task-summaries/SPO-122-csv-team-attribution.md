# SPO-122 — CSV team attribution on an event

- Ticket: SPO-122
- Branch: `feature/SPO-122-csv-team-attribution` (from `origin/dev` at `7fcf31f`)

## Summary

The shipped game log and the abbreviation map are doing what they were written to do. `data/nba_player_game_logs.csv` is one row per game. `load_csv` keeps the newest row first, and `team_from_game_logs` still picks the club on the US game date, or the latest club on or before that day. `Bulls` maps to `CHI`.

That club is the wrong label for a game the Bulls are not in. Anfernee Simons' rows in the shipped file are Celtics from 2025-10-22 through 2026-02-01 (49 games) and Bulls from 2026-02-05 through 2026-02-21 (6 games). The file's last game for any player is 2026-05-11. The recorded Celtics at 76ers board is event `cfa503c66cd505776a910921875ef7dd`, tip `2026-11-11T01:10:00Z`. There is no later Simons row, so the date rule returns Bulls, and the teammate list is everyone who shared a Bulls lineup with him, including Josh Giddey.

The lookup does not substitute the older Celtics stint. That stint ended before the Bulls games. Putting him on Boston would place a player on the other side of this game.

## Changes

| 檔案 | 變更 |
|---|---|
| `backend/app/services/csv_player_history.py` | `team_on_event` keeps a projection or log club only when its code is home or away. `get_teammates(..., only_team=)` limits the walk. `get_player_stats` takes `home_team`, `away_team`, and `as_of`. |
| `backend/app/services/daily_analysis.py` | Daily picks call `team_on_event` instead of applying `team_from_game_logs` whenever the projection club is empty. |
| `backend/app/api/nba.py`, `backend/app/api/wnba.py` | Player-history accepts `home_team`, `away_team`, and `as_of`. Omitting them keeps the previous list. |
| `frontend/lib/event-page.ts` | Lineup side wins for the team label. A code that is neither home nor away is not shown. `eventTeammates` keeps the scoped history list and appends that side's lineup names. |
| `frontend/lib/api.ts`, `frontend/lib/schemas.ts`, `frontend/components/EventDetail.tsx`, `frontend/components/PlayerHistoryStats.tsx` | The event history request sends the two clubs and the tip time. |
| `backend/tests/fixtures/csv/spo122_anfernee_simons_excerpt.csv` | Real lines copied from `data/nba_player_game_logs.csv`. |
| `backend/tests/test_spo122_csv_team_attribution.py` | Simons on the recorded Celtics at 76ers tip stays unlabeled, and Josh Giddey is not a teammate. |
| `backend/tests/test_spo98_team_and_names.py`, `backend/tests/test_daily_analysis.py`, `backend/tests/test_spo113_field_enrichment.py` | Existing callers pass a slate that contains the club under test, or the new history arguments. |
| `frontend/lib/event-page.test.ts` | CHI is not shown on BOS@PHI. Jaylen Brown stays on the Celtics lineup. A teammate who is out tonight stays in the filter. |

## Root cause

Two facts, and only the second one is a code bug.

1. The CSV source stops on 2026-05-11. It has no 2026-27 games. A player who changed clubs after the last logged game keeps the last logged club. The abbreviation map is not wrong: Bulls is CHI, Lakers is LAL, Knicks is NYK.
2. Event and teammate views applied that last logged club even when the club is neither home nor away. The teammate walk then listed the old lineup.

## Fix

`team_on_event` is the label for one event.

- Both home and away known: keep a projection club when its code is one of those two. Otherwise keep `team_from_game_logs` when that code is one of those two. Otherwise return `""`. An older stint is not filled in.
- Either side missing: unchanged. A projection club wins, otherwise `team_from_game_logs`.

`get_player_stats(..., home_team, away_team, as_of)` passes that label into `get_teammates(..., only_team=)`. `only_team=""` returns no names. `only_team=None` (player page, no event) still returns every stint. NBA and WNBA history routes accept the three query fields. WNBA behavior is unchanged when they are omitted.

Daily picks use the same helper. A projection abbreviation that is not in the game is dropped, and so is a last-season CSV club that is not in the game.

The event page prefers the lineup side for the team label. A stored `player_team_code` that is neither home nor away is not shown. The teammate filter keeps the history list, which the request scopes to a club in the game, and appends starters and bench from the player's side. A teammate who is out tonight is not on the lineup and still appears. The lineup names are used alone only when that history list is empty.

## Other players on the recorded boards

Same shape: the player is on a recorded Odds API board, `team_from_game_logs` at that tip is a club that is not home or away, and `team_on_event` now returns `""`. Name resolution is the existing exact key (`VJ Edgecombe` resolves to `V.J. Edgecombe`, whose last row is Sixers, so he is not in this list).

Celtics at 76ers, `cfa503c66cd505776a910921875ef7dd`, `odds_api_event_odds__nba_expanded_markets.json`:

| Player | Last CSV club | Last CSV game | Code that was applied |
|---|---|---|---|
| Anfernee Simons | Bulls (Celtics until 2026-02-01) | 2026-02-21 | CHI |
| LeBron James | Lakers | 2026-05-11 | LAL |
| Mitchell Robinson | Knicks | 2026-05-10 | NYK |

Lakers at Hawks, `07361a8381206817e27bd2697fad7479`, `odds_api_event_odds__player_points.json`:

| Player | Last CSV club | Last CSV game | Code that was applied |
|---|---|---|---|
| Aaron Wiggins | Thunder | 2026-05-11 | OKC |
| Luguentz Dort | Thunder | 2026-05-11 | OKC |
| Matisse Thybulle | Trail Blazers | 2026-04-28 | POR |
| Sandro Mamukelashvili | Raptors | 2026-05-03 | TOR |
| Walker Kessler | Jazz | 2025-10-31 | UTA |
| Ziaire Williams | Nets | 2026-04-03 | BKN |

Kingston Flemings is on the Lakers at Hawks board and is not in the CSV at all. That is a missing player, not a third-club label.

The other names on those two boards already match a club in the game (Celtics, Sixers, Lakers, or Hawks), including `V.J. Edgecombe` (Sixers, last game 2026-05-10).

## Tests

```
$ cd backend
$ python3 -m pytest -q --tb=line
1045 passed, 23 skipped, 6 xfailed
```

`tests/test_spo122_csv_team_attribution.py` loads `tests/fixtures/csv/spo122_anfernee_simons_excerpt.csv`. Every data line of that excerpt is a line from `data/nba_player_game_logs.csv` (Simons, plus Derrick White and Josh Giddey on the same dates so the lineup cache has both clubs). The test checks:

- Simons' latest row is Bulls and `canonical_team_code("Bulls")` is CHI. `team_from_game_logs` at the recorded tip is still Bulls.
- `team_on_event` for Celtics at 76ers is `""`, including a CHI candidate. A Sixers candidate is kept. The older Celtics stint is not substituted.
- Unscoped teammates include Josh Giddey and Derrick White. Scoped to the event, Simons' teammate list is empty.
- Derrick White stays Celtics. His scoped teammates include Simons and do not include Josh Giddey.

`tests/test_spo113_field_enrichment.py` calls the history route as a function, so it now passes the three new arguments. FastAPI supplies them on the HTTP path.

## Follow-ups

- The CSV still ends on 2026-05-11. A blank event label is the honest result until a later game log, or a lineup/projection that names a club in the game, is available. This change does not invent the 2026-27 club.
- The player page still lists every historical stint. That list is not an event.
