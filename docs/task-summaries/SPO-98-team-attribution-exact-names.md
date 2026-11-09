# SPO-98 — Player team attribution and exact name matching

- Ticket: SPO-98
- Branch: `feature/SPO-98-team-attribution-exact-names` (from `origin/dev`)

## Summary

Daily picks took a player's team from `game_logs[0]` after `get_player_stats` reversed logs to oldest-first, so a mid-season trade was labeled with the old club. Name lookup in `csv_player_history` and `historical._games_for` treated either string as a match when one contained the other, so `Smith` resolved to `Aaron Nesmith` and `Curry` resolved to `Seth Curry`.

Team is now the club on the US game date of the event (America/New_York, which is how the CSV `Date` column lines up with an Odds API `commence_time`), or the latest club on or before that day. A date before every log uses the earliest known club. Names match only when a shared normalizer produces the same key on both sides. NBA and WNBA go through the same league-parameterized service.

QA review on PR #28 (tests in `0ee1fb5`) is addressed below. `ODDS_API_KEY` is not set in this environment and the repo has no complete captured Odds API body, so the daily-picks wiring test still builds its bookmaker list inline. That payload was not replaced with a hand-written stand-in file.

## Changes

| Area | File | Change |
|---|---|---|
| Name key | `backend/app/services/normalize.py` | `player_name_key` + `match_player_name`. Folds case, whitespace, diacritics, punctuation, initials (`P. J.` / `P.J.` / `PJ`), and a trailing Jr/Sr/II/III/IV/V/VI. Nickname aliases stay on `canonical_name` and are not applied here. |
| History lookup | `backend/app/services/csv_player_history.py` | `resolve_player_name` replaces the four bidirectional substring loops (`get_player_stats`, `player_dd_history`, `get_player_opponents`, `get_teammates`). `team_from_game_logs` picks the team on the US game date, else the latest team on or before that day. A date before every log returns the earliest known team. Aware timestamps convert through America/New_York; naive CSV datetimes and `YYYY-MM-DD` strings are already that game date. |
| Daily picks | `backend/app/services/daily_analysis.py` | CSV fallback uses `team_from_game_logs(game_logs, commence_time)`. A projection `team` still wins. |
| Product historical agent | `scripts/agents/tools/historical.py` | `_games_for` uses `resolve_player_name` (NBA and WNBA via `_csv_for`). `_team_for` reads the full log for the six `games[0]["team"]` sites. `get_lineup_context` samples the 10 games on or before the event day. Star exclusion, injury-report identity, and odds-board `description` all use `player_name_key`. |
| Roster cache | `backend/app/services/lineup_source_support.py` | Latest club comes from `team_from_game_logs`. The cache loads NBA and WNBA, and each league resolves its nickname with its own alias table (Lynx → MIN). |
| Training contexts | `scripts/dataset/01_sample_contexts.py` | Scenario team is the most recent club in that scenario's logs, not the oldest row. |
| API copy | `backend/app/api/nba.py`, `backend/app/api/wnba.py` | DD-history query text no longer promises fuzzy match. |
| Tests | `backend/tests/test_spo98_team_and_names.py`, `backend/tests/test_spo98_gaps.py` | Real CSV rows. The four QA xfails are normal tests. A date before Buddy Hield's first log expects Warriors. |

## Why

`load_csv` sorts each player newest-first, then `get_player_stats` reverses that list so charts draw left-to-right. Index 0 of the chart list is the first game in the file. For 2025-2026 that is the pre-trade club whenever the player changed teams and did not return.

The event-day rule is the club on the US game date, or the latest log on or before it (a future slate has no log that day; the team heading into the slate is the most recent one). A date before the first log uses the earliest known club. Mo Bamba and P.J. Hall went out and came back, so earliest and latest are the same club; only the event day shows the middle stint. Odds API `commence_time` is UTC. `2026-03-16T00:30:00Z` is 20:30 America/New_York on 2026-03-15, which is Kent's Remix row in the CSV. Taking `.date()` on the UTC timestamp labeled him Trail Blazers.

Substring identity was the wrong tool for a roster. `smith` is contained in `nesmith`, and `curry` is contained in both Curry brothers, with the alphabetically first row winning. Suffixes and accents failed the other way: `Gary Trent Jr.` did not match the stored `Gary Trent, Jr.`, and `Nikola Jokić` did not match `Nikola Jokic`, because the comma and the diacritic broke containment. Folding those into one key and requiring equality fixes both directions. `Steph` / `Stephen` is left as an explicit alias on `canonical_name` so the history path does not grow a second fuzzy matcher.

## Tests

```
$ cd backend
$ python3 -m pytest -q --tb=line
2 failed, 654 passed, 6 skipped
```

QA's `test_spo98_gaps.py` was 22 passed and 4 xfailed. All four xfails now pass:

- `test_post_midnight_utc_commence_stays_on_us_game_date` — `2026-03-16T00:30:00Z` is 2026-03-15 in America/New_York, so Jayson Kent stays Remix. Checked against his CSV rows (Remix vs Lakers on 2026-03-15, Trail Blazers on 2026-03-16). `2026-03-15T23:00:00Z` stays the 15th. Date-only strings are not shifted.
- `test_lineup_sample_follows_the_event_day`
- `test_resolved_player_is_not_his_own_star`
- `test_wnba_player_is_on_her_own_roster`

Odds fixture: no `ODDS_API_KEY` in the environment, no `.env`, and no complete Odds API response saved under `tests/fixtures/` or elsewhere in the repo (research docs keep the first ~500 bytes, cut mid-string). `TestDailyAnalysisWiring._picks` is unchanged. A new hand-written JSON file was not added.

SPO-98 tests: `tests/test_spo98_team_and_names.py` (real NBA and WNBA rows), plus the updated substring cases in `test_csv_player_history.py` and `test_spo16_market_expansion.py`. Covered:

- Buddy Hield: chart `game_logs[0]` is Warriors; 2025-11-01 stays Warriors; 2026-02-09 and a later slate are Hawks. Daily-analysis wiring checks the same shape, and a projection `team` still overrides.
- Mo Bamba: latest team is Jazz, but 2026-01-15 is Raptors.
- DiJonai Carrington (WNBA): oldest row is Wings; 2025-06-01 is Wings; 2025-08-05 and the latest row are Lynx. `Aja Wilson` resolves to `A'ja Wilson`.
- `Smith` / `Curry` / `Porter` / `Williams` do not resolve. `Nikola Jokić` resolves to `Nikola Jokic` and not to `Nikola Jovic`. `Michael Porter Jr.`, `Gary Trent Jr.`, `Jimmy Butler`, `CJ McCollum` resolve to the stored spelling. `Steph Curry` does not resolve to `Stephen Curry`.

Team labels that change under the old oldest-first fallback versus most-recent / event-day (counted from the shipped CSVs, also asserted in the test):

| League | Players with 2+ teams | Earliest team ≠ latest team (label changes) |
|---|---|---|
| NBA (`nba_player_game_logs.csv`, 2025-2026 only) | 126 | 124 |
| WNBA (`wnba_player_game_logs.csv`) | 52 | 52 |

The audit's ~126 is the NBA multi-team count. 124 of those are labeled with the old club by `game_logs[0]`. The other two (Mo Bamba, P.J. Hall) returned to their original club, so oldest and latest coincide, and only an event inside the middle stint changes. WNBA uses the same daily-picks fallback, so 52 additional labels were on the old club. NBA projections still override the CSV team when SportsDataIO sends one; the 124 is the CSV fallback.

The 2 failures also fail on `origin/dev` with the working tree stashed. Both are `slowapi/extension.py:81: AttributeError: 'ConnectionError' object has no attribute 'detail'` when Redis is down:

- `tests/test_agent_chat.py::test_agent_chat_endpoint_validates_action_and_uses_service`
- `tests/test_lineup_consensus.py::test_lineups_api_returns_team_count`

Left untouched (SPO-95).

## Follow-ups

- `get_all_players(search)` is still a substring search box. It is not an identity lookup.
- `teammate_filter` still requires the stored spelling, so `Gary Trent Jr.` does not filter the teammate `Gary Trent, Jr.`.
- Wiring `canonical_name` nicknames (`Steph` → `Stephen`) into `resolve_player_name` should be an explicit alias table if product wants it, not a return to containment.
- Record one real Odds API event body into `backend/tests/fixtures/` once a key is available, and point `TestDailyAnalysisWiring._picks` at `bookmakers` from that file.
- A tip after midnight Eastern (late Pacific) is the next America/New_York date. The CSV row for Kent vs Lakers is 2026-03-15, which matches an Eastern-evening commence (`00:30Z`). A 10:30pm Pacific tip would need `America/Los_Angeles` to stay on that local date.
