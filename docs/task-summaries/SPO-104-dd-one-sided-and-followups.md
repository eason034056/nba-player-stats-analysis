# SPO-104 — One-sided DD quotes, league-aware team codes, season hygiene follow-ups

- Ticket: SPO-104
- Branch: `feature/SPO-104-dd-one-sided-and-followups` (from `origin/dev`)
- Base: `dev`

## Summary

A binary quote that posts only Yes no longer copies that price into `under_odds` or invents `p_under_imp` from `1 - p_yes_imp`. `under_odds` and `p_under_imp` are null. `p_under_fair` / `no_fair_prob` stay the complement of the single-leg de-vigged Yes fair, and `vig` stays `DEFAULT_BINARY_VIG` (0.045). Each result row carries `line_is_synthetic`, `market_kind` (`"binary"` or `"over_under"`), and `uses_prior`. The consensus object carries `consensus_uses_prior` and `consensus_prior_book_count`.

The three strict SPO-98 xfails pass without markers. A late Pacific tip uses the US game date on the Pacific clock, so it does not roll onto the next Eastern morning. Roster and name lookup are scoped by league. `canonical_team_code` and `_team_code_from_name` take `league`, default `"nba"`.

The offline ESPN index now reads `tests/fixtures/espn/recorded/`. Event 401736430, the WNBA Commissioner's Cup final, is `cup_championship` instead of `regular_season`. League on that overlay is an explicit argument, with a logged filename fallback when it is omitted. A blank `GameType` is regular season in one helper.

## Changes

| Area | File | Change |
|---|---|---|
| Response schema | `backend/app/models/schemas.py` | `BookmakerResult.under_odds` and `p_under_imp` are optional. Every row has `line_is_synthetic`, `market_kind` (`"binary"` or `"over_under"`), and `uses_prior`. `Consensus` carries `consensus_uses_prior` and `consensus_prior_book_count`. |
| NBA no-vig | `backend/app/api/nba.py` | One-sided Yes leaves `under_odds`, `p_under_imp`, `no_price`, and `p_no_imp` null and sets `uses_prior` true. A two-sided binary row and every Over/Under row set `uses_prior` false. Consensus counts how many included books used the prior. |
| WNBA no-vig | `backend/app/api/wnba.py` | Same contract as the NBA route. |
| Best price | `scripts/agents/tools/market.py` | A missing side is skipped when choosing the best American price, so `None` does not crash `max`. |
| US game date | `backend/app/services/csv_player_history.py` | Aware timestamps use `America/Los_Angeles`. Naive datetimes and date-only strings are unchanged. |
| Rosters | `backend/app/services/lineup_source_support.py` | `_build_team_roster_cache`, `_get_team_roster_candidates`, `resolve_canonical_player_name`, and `normalize_source_players` take `league` (default `"nba"`). NBA and WNBA lists are not merged. |
| Team codes | `backend/app/services/daily_analysis.py`, `scripts/agents/tools/historical.py` | `canonical_team_code` and `_team_code_from_name` take `league` (default `"nba"`). WNBA callers pass it through. Lynx → MIN and Wings → DAL only for `league="wnba"`. |
| Schedule index | `backend/app/services/game_log_hygiene.py`, `backend/app/services/espn_schedule.py` | Overlay includes `recorded/`. `league` is an argument; a missing league logs a warning and uses the filename, and a filename with no prefix raises. `coalesce_game_type` maps blank, None, and missing to `regular_season`. WNBA Commissioner's Cup final is `cup_championship`. |
| Fixtures | `tests/fixtures/espn/schedule_events.json`, `tests/fixtures/espn/recorded/wnba_team_5_schedule_2025_type_2.json` | Recorded ESPN bodies used by the offline index. Not edited. |
| Tests | `backend/tests/test_spo104_one_sided_dd.py`, `backend/tests/test_spo104_game_log_hygiene.py`, `backend/tests/test_spo98_gaps.py` | One-sided and two-sided DD, Over/Under flags, cup final, league argument, blank GameType. SPO-98 xfails removed. |
| Docs | `docs/progress.md` | SPO-104 row. |

## API contract (SPO-105)

`POST /api/nba/props/no-vig` and `POST /api/wnba/props/no-vig`.

| Field | Binary, Yes only | Binary, Yes and No | Over/Under |
|---|---|---|---|
| `over_odds` | Yes price | Yes price | Over price |
| `under_odds` | `null` | No price | Under price |
| `p_under_imp` | `null` | No implied | Under implied |
| `no_price` / `p_no_imp` | `null` | posted No | `null` |
| `p_under_fair` / `no_fair_prob` | complement of the single-leg Yes fair | two-leg de-vig | two-leg de-vig |
| `vig` | `0.045` | measured from the pair | measured from the pair |
| `line` | `0.5` | `0.5` | posted total |
| `line_is_synthetic` | `true` | `true` | `false` |
| `market_kind` | `"binary"` | `"binary"` | `"over_under"` |
| `uses_prior` | `true` | `false` | `false` |

`line_is_synthetic`, `market_kind`, and `uses_prior` live on each `BookmakerResult`. They are not on the response envelope. `uses_prior` is true only when that row's fair probability came from `single_leg_devig` because No was not posted.

The response has a `consensus` object. These two fields live on that object, next to `p_over_fair` / `p_yes_fair`:

| Consensus field | Every book two-sided | Mixed (one book used the prior) | Every book used the prior |
|---|---|---|---|
| `consensus_uses_prior` | `false` | `true` | `true` |
| `consensus_prior_book_count` | `0` | number of prior books | number of books in the consensus |

An Over/Under consensus is `false` / `0`. A missing consensus (no priced books) omits the object, so the flags are not on the envelope either.

`line_is_synthetic` and `market_kind` use those exact names. Fair No on a one-sided quote is a model output, not a posted price. Consensus still averages the fair pairs, including a one-sided book.

## Why

The calculator table treated a copied Yes price as a posted Under. FanDuel's recorded Yes `-240` with `no_price: null` was coming back as `under_odds: -240` and an implied probability of `1 - p_yes_imp`. Readers could price a side the book did not offer. The fair complement stays, because a binary outcome still sums to 1 after the 4.5% prior.

`America/New_York` already keeps a 7:30pm PT tip (after midnight UTC, still evening in the East) on the CSV date. It does not keep a 10:30pm PT tip: that kick is the next morning in New York and the same evening in Los Angeles. The CSV row for Jayson Kent that night is Remix on 2026-03-15. The game-date clock is `America/Los_Angeles` so both the SPO-98 00:30Z case and the later Pacific tip stay on the US date. Date-only strings and naive datetimes are still not shifted.

TOR is the Raptors and the Tempo. One roster list made `T. Key` ambiguous. The default cache is NBA. Teonni Key is only on the WNBA Tempo list, so an NBA lookup of `T. Key` does not return her. `league="wnba"` resolves `T. Key` to Teonni Key. Tyreke Key's only rows were Summer League and are not in the canonical NBA file, so the NBA side has no `T. Key` left to match. `canonical_team_code("Lynx")` stays unresolved on the NBA default; `league="wnba"` returns MIN. Wings returns DAL the same way.

SPO-97 landed on `dev` as #30 while this branch was open, and this branch merges that tip. The parent glob `*_team_*_schedule_*_type_*.json` does not enter `recorded/`, so `load_schedule_events()` left 401736430 on the compact index's regular-season label and null competition. The recorded body has competition type `CC` / `commissioners-cup` and the headline `WNBA Commissioner's Cup Championship`. After the overlay, that id is `cup_championship`. `GAME_TYPE_NBA_CUP` is the same token.

When `league` is omitted, the overlay logs a warning and reads the slug from `{league}_team_...`. A name with an empty prefix raises `ValueError`. Callers that know the league pass `league=`.

`coalesce_game_type` is the only blank-GameType rule: None, `""`, whitespace, and a missing cell are `regular_season`. Other tokens pass through.

## Tests

```
cd backend && pytest
```

Local run with Redis down: 726 passed, 2 failed, 9 skipped, 0 xfailed. The failures are the two known Redis cases named below. `pytest scripts/agents/tests`: 46 passed.

New coverage:

- One-sided DD (FanDuel in `frontend/test/fixtures/props-no-vig/player-double-double.json`): `under_odds` null, `over_odds` equals the Yes price, `line_is_synthetic` true, `market_kind` `"binary"`, `uses_prior` true. NBA and WNBA.
- Two-sided DD (DraftKings in the same fixture): both prices kept, `uses_prior` false. The recorded pair is a mixed consensus: `consensus_uses_prior` true and `consensus_prior_book_count` 1.
- Every recorded book with its No leg removed: both Yes prices still come from that fixture, `uses_prior` is true on each row, and the consensus count is 2.
- DraftKings alone: `consensus_uses_prior` false and `consensus_prior_book_count` 0.
- Over/Under uses `backend/tests/fixtures/odds_api_event_odds__player_points.json`. `line_is_synthetic` false, `market_kind` `"over_under"`, `uses_prior` false, consensus prior count 0. NBA and WNBA.
- Offline index: 401736430 is `regular_season` in the compact file and `cup_championship` after load.
- Missing `league` logs the filename fallback. An explicit `league="wnba"` does not. A filename with no prefix raises.
- `coalesce_game_type` for None, blank, whitespace, missing, and `playoffs`.
- SPO-98: `test_pacific_late_tip_stays_on_the_us_game_date`, `test_shared_team_code_initials_do_not_cross_leagues`, and `test_wnba_nickname_uses_the_wnba_team_code` have no xfail marker. The late tip is checked on the two-club log (Remix on the US date, Trail Blazers on the UTC date) because SPO-97 removed the G League row from the canonical file. `T. Key` on NBA does not resolve to Teonni Key; on WNBA it does.

No live Odds API call. No new hand-typed Odds API body. The DD input is the posted `yes_price` / `no_price` from the existing route fixture. The Over/Under input is the recorded v4 odds body.

The two Redis failures that already fail on `dev` when Redis is down are expected: `test_agent_chat_endpoint_validates_action_and_uses_service` and `test_lineups_api_returns_team_count`. CI runs Redis, so those should pass there.

## Follow-ups

- SPO-105 owns the frontend read of null `under_odds`, `line_is_synthetic`, `market_kind`, and `uses_prior`. This branch does not change the Zod schema. `consensus_uses_prior` and `consensus_prior_book_count` are on the consensus object for a mixed board.
- `cup_championship` stays in the canonical game-type set, so the final is kept and stays out of the default regular-season sample. `GAME_TYPE_NBA_CUP` is an alias of that token.
- The snapshot table still stores the 0.5 sentinel in `line`. The new flags are on the no-vig response, not a new SQL column.
