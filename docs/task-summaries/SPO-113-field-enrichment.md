# SPO-113 — NBA field enrichment for the No-Vig redesign

## Summary

Frontend PRs #39 and #40 need fields the NBA API does not return yet. This change adds them on the NBA routes only. WNBA routes are unchanged. New fields on the shared models default to null or an empty list, so a WNBA payload still parses and the new keys are null or `[]`.

`commence_time` stays the UTC timestamp. NBA events also return `commence_time_et` (ISO 8601 with the `America/New_York` offset, via `zoneinfo`, so EST and EDT are both right) and `display_tz` (`"ET"`). Each event carries `lineup_status.home` and `lineup_status.away`. `GET /api/nba/lineups` and `GET /api/nba/lineups/{team}` add `confirmation_status`. `status` stays completeness (`projected` = five names, `partial` = fewer, `unavailable`). `confirmation_status` is a different word: `confirmed` when any snapshot says confirmed. A four-name slate can be `status="partial"` and `confirmation_status="confirmed"`. Both fields can read `projected` for different reasons.

`DailyPick.position` and suggest `suggestions[].position` come from the `Pos` column on the player's most recent NBA game log. Player-history game logs gain `home_or_away`. The history route accepts `season` and returns season-scoped hit rate and sample size beside the existing all-games numbers. `teammates` stays the name list. `teammate_context` adds how many sample games each of those teammates missed, the dates and ESPN ids, and the player's mean with and without them.

`opponent_rank` and `opponent_position_rank` were null because the projection row did not carry them and nothing else filled them. A null rank is now filled from the NBA regular-season game log. A rank already on the row is kept. See the root cause below.

Schema edits are additive and sit on their own lines. This PR does not add `tier`, `p_over`, `p_under`, or `top_read` (SPO-111) or `signals` and `combined_probability` (SPO-112).

## Changes

| File | Change |
|---|---|
| `backend/app/models/schemas.py` | Optional NBA fields on `NBAEvent`, `DailyPick`, `GameLog`, `PlayerHistoryResponse`, `PlayerSuggestResponse`, and `TeamLineup`. New models `EventLineupStatus`, `PlayerSuggestion`, `TeammateMissedGame`, `TeammateContext`. |
| `backend/app/services/event_fields.py` | ET conversion and per-team lineup status applied on the way out of the events route. |
| `backend/app/services/lineup_service.py` | `confirmation_status` and `peek_lineups` (cache or Postgres, no scrape). |
| `backend/app/api/nba.py` | Events enrichment, suggest positions, history `season` and the new history fields. |
| `backend/app/api/lineups.py` | Overlay `confirmation_status` on list and single-team reads. |
| `backend/app/services/csv_player_history.py` | Position, venue, season rates, teammate context. NBA only. |
| `backend/app/services/game_log_hygiene.py` | Schedule index remembers which side is home, and can return the venue and the event id when the join is unique. |
| `backend/app/services/nba_season.py` | Current NBA season from the recorded ESPN season windows. |
| `backend/app/services/defense_ranks.py` | Fill a null opponent rank from the game log. |
| `backend/app/services/projection_service.py` | Fill ranks on every read. Redis still stores the unfilled projection dict. |
| `backend/app/services/daily_analysis.py` | Set `DailyPick.position` from the NBA game log. |
| `backend/tests/test_spo113_field_enrichment.py` | Tests for all seven items, including the null-rank case and a WNBA history payload that does not gain the NBA keys. |
| `docs/decisions/spo-113-field-enrichment/decision_20261110_field-enrichment.md` | Contract and the confirmation rule. |

## Why

The events cache stores the Odds API shape. Timezone and lineup status are applied after the cache read, so a lineup change is not frozen into that cache and the events route does not scrape RotoWire or RotoGrinders. `peek_lineups` reads Redis, then Postgres, and returns `{}` on failure. The event field is then null.

RotoGrinders always writes `projected`. A rule that requires every snapshot to say `confirmed` never fires when both sources are present. Confirmation is therefore "any snapshot says confirmed." `expected` is not confirmed. The completeness `status` is a different word and is left alone. The new field is `confirmation_status` on the lineup payload and `lineup_status` on the event.

The CSV has no venue column. `home_or_away` is the side on the recorded ESPN schedule when exactly one event matches the date and the two clubs. Zero matches or two matches stay null.

Season rates use the same filters as the all-games sample (game type through `coalesce_game_type`, opponent, starter, teammate, DNP) and ignore `n`. The default season is the recorded ESPN window that contains today, not a hardcoded October boundary. `2025-26` and `2025-2026` are the same label. On 2026-11-10 that window is `2026-2027`. The shipped CSV is still `2025-2026` and `2024-2025`, so a default-season sample can be zero until the log is refreshed. The all-games `n_games`, `p_over`, and `p_under` do not change.

### Opponent rank root cause

Two separate facts.

The nulls exist because the value is missing at the source. `projection_provider.FIELD_MAPPING` copies `OpponentRank` and `OpponentPositionRank` and no other writer sets them. A null on the SportsData row stays null on `GET /api/nba/projections` and on `DailyPick`. This environment has no SportsData key, so this PR does not claim a live response body. The fill is computed from the game log we already ship.

A fill that looked the abbreviation up as-is would still miss six clubs. SportsData writes `GS`, `NO`, `NY`, `SA`, `PHO`, and `UTAH`. `canonical_team_code` and the lineup table use `GSW`, `NOP`, `NYK`, `SAS`, `PHX`, and `UTA`. The lookup goes through `canonical_team_code`, which already has those aliases. The league query param is not the NBA bug: the projection URL is hardcoded to `/v3/nba/`. WNBA is not in the projection leagues, and its ranks stay null on purpose.

Rank 1 is the most real points allowed per game (the weakest defense), which is the scale the picks page already uses: 1–10 easy, 11–20 average, 21–30 hard. Position rank is points allowed to `PG`, `SG`, `SF`, `PF`, or `C`, and each position is ranked on its own 1–30 list. A single list of every team-position pair is not used, because that list runs to 150. `_rank_descending` keeps only places 1 through 30. A number already on the projection is kept, including a vendor 0 or 31; the response models reject those with `ge=1, le=30` when they are serialized. An unknown opponent stays null. Zero-minute rows are left out of the sum, the same way history leaves them out.

The CSV spells Philadelphia as `Sixers`. That token was missing from `TEAM_CODE_ALIASES`, so the table stored `SIXERS` and a lookup for `PHI` stayed null. `SIXERS` now maps to `PHI`, beside the existing `76ERS` alias.

The rank season is the recorded current season when the log has regular-season games for it, otherwise the latest season that does. In November 2026 that is `2025-2026` (the 2025-26 season). A filled rank is labeled `opponent_rank_source: "csv"`, `opponent_rank_season: "2025-2026"`, and `opponent_rank_note` saying it is real points allowed, not fantasy points. A number that was already on the row is `opponent_rank_source: "sportsdata"`. Redis stores the unfilled dict on both the fetch path and the Postgres fallback, and the fill runs after the read. The season label used to choose that window stays the UTC date. QA pins that choice (`test_chicago_evening_uses_the_utc_date` and the inclusive window edges). An Eastern evening can already be the next UTC date.

## API contract

Shared models also serialize these keys on WNBA. WNBA routes do not compute them. They are null or `[]` there.

### `GET /api/nba/events` — each `events[]` item

| Field | JSON type | Null | Notes |
|---|---|---|---|
| `commence_time` | string, date-time | no | Unchanged. UTC. |
| `commence_time_et` | string | yes | ISO 8601 with the `America/New_York` offset. `2026-01-15T01:00:00Z` is `2026-01-14T20:00:00-05:00`. `2026-07-15T00:00:00Z` is `2026-07-14T20:00:00-04:00`. Null if the timestamp does not parse. |
| `display_tz` | string | yes | `"ET"` on an enriched NBA event. |
| `lineup_status` | object | yes | Present on NBA events. `home` and `away` are each `"confirmed"`, `"projected"`, or null. Null when that club has no stored lineup for the events date. The events route does not scrape. |
| `lineup_status.home` | string | yes | `"confirmed"` or `"projected"`. |
| `lineup_status.away` | string | yes | `"confirmed"` or `"projected"`. |

### `GET /api/nba/lineups` and `GET /api/nba/lineups/{team}`

| Field | JSON type | Null | Notes |
|---|---|---|---|
| `status` | string | no | Completeness from the starter count. `projected` = five names, `partial` = fewer than five, `unavailable` = none. This word is not confirmation. |
| `confirmation_status` | string | yes | Confirmation, separate from `status`. `"confirmed"` if any `source_snapshots.*.status` is `confirmed` (case-insensitive), including a stale confirmation next to a fresh `projected` snapshot. `"projected"` if a snapshot or a starter exists and nobody reported confirmed (`expected` lands here). Null when the record has neither. Does not read `updated_at`. A partial slate can still be confirmed. |

### `GET /api/nba/players/suggest`

| Field | JSON type | Null | Notes |
|---|---|---|---|
| `players` | string[] | no | Unchanged name list. |
| `suggestions` | object[] | no | Same order as `players`. Empty array on WNBA. |
| `suggestions[].name` | string | no | Same spelling as `players[]`. |
| `suggestions[].position` | string | yes | `Pos` on the most recent NBA game log. Null when the name is not in the log or `Pos` is blank. |

### `GET /api/nba/daily-picks` and `POST /api/nba/daily-picks/trigger`

| Field | JSON type | Null | Notes |
|---|---|---|---|
| `picks[].position` | string | yes | Same `Pos` source as suggest. Null on WNBA and when the log has no position. |
| `picks[].opponent_rank` | integer | yes | 1–30 (`ge=1`, `le=30`). 1 = most real points allowed. Filled when the projection left it null. |
| `picks[].opponent_position_rank` | integer | yes | 1–30, ranked inside that position only. |
| `picks[].opponent_rank_source` | string | yes | `"csv"` or `"sportsdata"`. |
| `picks[].opponent_rank_season` | string | yes | Game-log season for a csv rank, e.g. `"2025-2026"` (the 2025-26 season). Null for a SportsData rank. |
| `picks[].opponent_rank_note` | string | yes | On a csv rank: computed from real points allowed, not fantasy points. |

### `GET /api/nba/player-history`

Query `season`: optional string. Omit it and the season is the current recorded NBA season (`2026-2027` on 2026-11-10). `2025-26` and `2025-2026` are the same label. The query does not change `n_games`, `p_over`, or `p_under`.

| Field | JSON type | Null | Notes |
|---|---|---|---|
| `season` | string | yes | Echo of the season the `season_*` numbers use. Null on WNBA. |
| `season_n_games` | integer | yes | Games in that season after the same filters as the all-games sample. Ignores `n`. `0` when that season has no games. |
| `season_p_over` | number | yes | Share of those games with value strictly above the threshold. Null when `season_n_games` is 0. |
| `season_p_under` | number | yes | Share strictly below the threshold. Null when `season_n_games` is 0. |
| `game_logs[].home_or_away` | string | yes | `"home"`, `"away"`, or null. Null when the CSV row does not join exactly one recorded ESPN event. |
| `teammates` | string[] | no | Unchanged name list. |
| `teammate_context` | object[] | no | One entry per name in `teammates`. Empty on WNBA. Computed on the sample after `n` is applied. |
| `teammate_context[].name` | string | no | Same spelling as `teammates[]`. |
| `teammate_context[].games_missed` | integer | no | Count of sample games where that teammate did not play (no positive-minute row that date for that team). |
| `teammate_context[].missed_games` | object[] | no | Those games, oldest first. |
| `teammate_context[].missed_games[].date` | string | no | `YYYY-MM-DD`. |
| `teammate_context[].missed_games[].game_id` | string | yes | ESPN event id when the schedule join is unique. Otherwise null. |
| `teammate_context[].with_n` | integer | no | Sample games the teammate played. |
| `teammate_context[].without_n` | integer | no | Sample games the teammate missed. Equals `games_missed`. |
| `teammate_context[].with_mean` | number | yes | Mean of the requested stat in the games the teammate played. Null when `with_n` is 0. |
| `teammate_context[].without_mean` | number | yes | Mean in the games the teammate missed. Null when `without_n` is 0. |

### `GET /api/nba/projections` and `GET /api/nba/projections/{player}`

| Field | JSON type | Null | Notes |
|---|---|---|---|
| `opponent_rank` | integer | yes | 1–30. 1 is the most real points allowed per game. Kept when the projection already has a number. Null when the opponent code is unknown or the log has no regular-season games. |
| `opponent_position_rank` | integer | yes | 1–30 inside `PG` / `SG` / `SF` / `PF` / `C`. A center rank is not compared with a point-guard rank. |
| `opponent_rank_source` | string | yes | `"csv"` when a null rank was filled from the game log. `"sportsdata"` when the row already carried the number. |
| `opponent_rank_season` | string | yes | Season of the csv table, e.g. `"2025-2026"`. Null for `"sportsdata"` and when the rank stays null. |
| `opponent_rank_note` | string | yes | `"Computed from real points allowed, not fantasy points."` when `opponent_rank_source` is `"csv"`. |

## Tests / Verification

`python3 -m pytest --tb=line -q` from `backend/` at `655ec6a`: 855 passed, 23 skipped, 6 xfailed. Two failures, both the known Redis misses (`ConnectionError` from the rate limiter): `test_agent_chat_endpoint_validates_action_and_uses_service` and `test_lineups_api_returns_team_count`. QA's five pin tests in `backend/tests/test_spo113_qa_review.py` pass. That file was not edited.

No live Odds API call. No live SportsData call. The home/away assertion reads `tests/fixtures/espn/nba_team_18_schedule_2026_type_2.json` (event `401809234`, Knicks home against the Cavaliers on 2025-10-22). Rank tests use in-memory projection dicts and the shipped game log, not a hand-typed SportsData body.

## Follow-ups

- SPO-111 (PR #42, not merged) still adds `tier`, `p_over`, `p_under` on `DailyPick` and `top_read` on `NBAEvent`. A trial merge conflicts in `backend/app/api/nba.py` (`_with_event_fields` vs `_events_with_top_reads`), `backend/app/models/schemas.py` (`NBAEvent` / `EventLineupStatus` vs `top_read`), and `backend/app/services/daily_analysis.py` (the pick constructor). Resolve that after #42 lands on `dev`. This branch was not rebased onto #42.
- SPO-112 adds `signals` and `combined_probability`. Those lines were left untouched. A position rank above 30 used to look like a strong defense to that verdict; position ranks are now 1–30.
- The shipped CSV has no `2026-2027` rows. Default season hit rate stays empty until that log is refreshed. Opponent ranks fall back to `2025-2026` for the same reason.
- The events lineup chip is only as fresh as the last lineup cache or Postgres row. The events route does not refresh it.
- Until the picks-page rank colors land, `PlayerProjectionPanel` on this branch still treats ranks 1–10 as Hard.
