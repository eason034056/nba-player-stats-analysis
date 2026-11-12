# Decision — NBA field enrichment contract

**Date:** 2026-11-10
**Ticket:** SPO-113
**Epic:** spo-113-field-enrichment
**Status:** accepted for the PR into `dev`

> Superseded in part by SPO-135 (2026-11-11): `GET /api/nba/projections` is removed. Defense ranks are `csv` only. A number already on a row is not kept.

## Context

The No-Vig redesign (frontend PRs #39 and #40) reads fields the NBA API does not return. PR #40's data-gap table is the list: an Eastern tip time, a per-team lineup confirmation, a season hit rate, opponent defense ranks that are often null, home or away on a game log, games a listed teammate missed, and a position. WNBA work is paused. New optional fields on shared models may serialize as null there. Existing WNBA routes are not extended.

SPO-111 (PR #42, not merged) adds `tier`, `p_over`, and `p_under` on `DailyPick` and `top_read` on `NBAEvent`. SPO-112 will add `signals` and `combined_probability` on `DailyPick`. This change stays on its own lines so those edits merge cleanly.

## Decision

### Clock

`commence_time` stays the UTC timestamp. NBA events add `commence_time_et` and `display_tz`.

`commence_time_et` is the same instant formatted with `zoneinfo.ZoneInfo("America/New_York")`. January is `-05:00`. July is `-04:00`. `display_tz` is the string `"ET"` on every enriched NBA event. A timestamp that does not parse yields null for `commence_time_et`. WNBA events use the same model and leave both fields null.

Enrichment runs on the way out of `GET /api/nba/events`, including a cache hit. The cache keeps the Odds API shape.

### Lineup confirmation

Two words were being asked to do one job. `TeamLineup.status` already means completeness from the starter count: `projected`, `partial`, or `unavailable`. This change does not redefine it.

`TeamLineup.status` is completeness from the starter count: `projected` when five names are present, `partial` when fewer than five are present, `unavailable` when none are. It is not a confirmation word. A four-name slate can be `status="partial"` and still be confirmed.

Confirmation is a new field, `confirmation_status`, on `GET /api/nba/lineups` and `GET /api/nba/lineups/{team}`:

- `"confirmed"` when any `source_snapshots` entry has `status` equal to `confirmed`, compared case-insensitively. One confirmation is enough.
- `"projected"` when the record has a snapshot or at least one starter and nobody reported confirmed. `expected` lands here.
- `null` when the record is missing, or it has neither a snapshot nor a starter.

RotoGrinders always writes `projected`. RotoWire writes `confirmed` only when the page says "Confirmed Lineup", and `expected` otherwise. A rule that waits for every snapshot to say confirmed never becomes confirmed while RotoGrinders is in the slate. The frontend chip in PR #40 currently requires every snapshot to be confirmed. The backend rule is the any-source rule above, on purpose, so a RotoWire confirmation is not vetoed.

NBA events expose the same word per club as `lineup_status.home` and `lineup_status.away` (`"confirmed"`, `"projected"`, or null). Team names are resolved with `canonical_team_code` (`Los Angeles Lakers` to `LAL`, `Golden State Warriors` to `GSW`). The events route calls `peek_lineups`, which reads Redis and then Postgres and does not scrape. A failure or a miss is an empty slate, and that side is null.

### Position

`DailyPick.position` and `suggestions[].position` on `GET /api/nba/players/suggest` are the `Pos` value on the player's most recent NBA game log. Games are stored newest first. A blank `Pos` is skipped. A name that is not in the log is null. The suggest route keeps `players` as the name list and adds `suggestions` in the same order. WNBA suggest does not set `suggestions`, so the model default `[]` is what serializes. Daily picks set `position` only when `league` is `nba` and the lookup returns a non-empty string.

### Home or away

The game log CSV has no venue column. `game_logs[].home_or_away` is `"home"`, `"away"`, or null. The value comes from the recorded ESPN schedule. The schedule index stores which competitor is home. `venue` returns a side only when exactly one event matches the date and the two clubs. Zero matches or more than one match is null. The same uniqueness rule supplies `game_id` on a missed-teammate row. WNBA log rows do not get the key; the shared `GameLog` model then serializes null.

### Season hit rate

`GET /api/nba/player-history` takes an optional `season` query. The response echoes `season` and adds `season_n_games`, `season_p_over`, and `season_p_under`. `n_games`, `p_over`, and `p_under` stay the all-games sample, including the `n` window.

The default season is the recorded ESPN window that contains the UTC date, read from `tests/fixtures/espn/seasons/nba_*.json`. Overlapping windows use the one that started latest. A gap uses the season that started most recently. `season_label_for_event` turns `2026-27` into `2026-2027`. `2025-26` and `2025-2026` are the same label. On 2026-11-10 the window is `2026-2027` (`nba_2027.json` runs 2026-09-30 through 2027-06-26). The date compared with those windows is the UTC calendar date. QA pins that, including a Chicago evening whose UTC date has already crossed the boundary. The events clock is still displayed in Eastern time.

Season rates use the same filters as the all-games sample: game type through `coalesce_game_type` (a blank type is regular season), opponent, starter, teammate, and DNP. They ignore `n`. They are computed before the last-N trim. An empty season returns `season_n_games: 0` and null rates. The shipped CSV is `2025-2026` and `2024-2025`, so the default season can be an empty sample until the log is refreshed. WNBA history does not compute these keys; the response model leaves them null.

### Opponent ranks

`opponent_rank` and `opponent_position_rank` stay the existing integer fields on `GET /api/nba/projections`, `GET /api/nba/projections/{player}`, and `DailyPick`.

The nulls come from a missing source, not from the league parameter. `FIELD_MAPPING` copies `OpponentRank` and `OpponentPositionRank`. Nothing else in the repo wrote them, so a null on the projection stayed null on the API. The NBA fetch URL is already `/v3/nba/`. WNBA is outside the projection leagues, and those ranks stay null on purpose. No SportsData key was available here, so the fill is not based on a newly recorded live body.

Filling a null by matching the raw abbreviation would still miss six clubs. SportsData writes `GS`, `NO`, `NY`, `SA`, `PHO`, and `UTAH`. The canonical codes are `GSW`, `NOP`, `NYK`, `SAS`, `PHX`, and `UTA`. The lookup uses `canonical_team_code`, which already maps those aliases.

When a rank is null, it is computed from NBA regular-season game logs. A team's points on a date are the sum of its players' points, excluding rows with zero minutes. That sum is points allowed by the opponent. Rank 1 is the most real points allowed per game (the weakest defense), not fantasy points. Ties break by team code so ranks are unique. Only places 1 through 30 are emitted. Position rank is points allowed to `PG`, `SG`, `SF`, `PF`, or `C`, ranked inside that position, using the first token of the logged position. One combined list of every team-position pair is not used. An integer already on the projection in 1–30 is kept. A vendor value that is not an int in 1–30, including 0, 31, a float, or a bool, becomes null with source `sportsdata_invalid` and is not filled from the game log. If either rank on the row is invalid, both ranks are cleared, so a 0 next to an in-range 8 is not published as a half vendor pair. `PlayerProjection` and `DailyPick` still declare `ge=1, le=30`. An unknown opponent stays null.

The CSV spells Philadelphia `Sixers`. `TEAM_CODE_ALIASES` maps `SIXERS` to `PHI`, next to `76ERS`.

Each rank has its own source, season, and note. A null overall rank filled from the log is `opponent_rank_source: "csv"`, `opponent_rank_season` (the game-log label, `2025-2026` for the 2025-26 season), and `opponent_rank_note` (`Computed from real points allowed, not fantasy points.`). The position rank uses `opponent_position_rank_source`, `opponent_position_rank_season`, and `opponent_position_rank_note`. An in-range number that arrived on the projection is `sportsdata` on that rank only and leaves that rank's season and note null. A valid overall rank next to a null position rank stays `sportsdata` on the overall rank while the position rank can be `csv`. Redis stores the unfilled dict from both `fetch_and_store` and the Postgres fallback. The fill runs on the way out of `get_projections`.

The rank season is the recorded current season when the log has regular-season games for it, otherwise the latest season label that does. In November 2026 the CSV has not been refreshed for `2026-2027`, so ranks use `2025-2026`.

The fill runs on every `ProjectionService.get_projections` read (cache hit, fetch return, and the Postgres fallback). `fetch_and_store` still writes the unfilled dict to Redis. Daily picks read projections through that service, so a null rank is filled before the pick is built. A pick built from a projection dict that already contains a number keeps that number.

### Teammate context

`teammates` stays the list of names. `teammate_context` is one object per name, on the sample after `n` is applied:

- `games_missed` and `missed_games` (`date`, and `game_id` when the schedule join is unique). Oldest first.
- `with_n`, `without_n`, `with_mean`, `without_mean` for the requested stat.

A teammate missed a game when they are not in the lineup cache for that team and date. The cache holds players with minutes greater than zero. WNBA returns no context list; the model default is `[]`.

## Consequences

Frontend can wire the contract in `docs/task-summaries/SPO-113-field-enrichment.md`. The lineup chip should read `confirmation_status` or `lineup_status`, not "every snapshot is confirmed." A default-season hit rate of zero games is a stale CSV, not a failed query. Opponent ranks of 1 are the weakest defense, matching the existing 1–10 / 11–20 / 21–30 bands.
