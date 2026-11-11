# Recorded external API responses

Byte-for-byte responses. Do not reformat or edit these files.

## The Odds API v4

Recorded 2026-11-09 ~15:35 America/Chicago. The `apiKey` query parameter was removed from the URLs below. It is not in the files.

| File | Request |
|---|---|
| `odds_api_events__basketball_nba.json` | `GET /v4/sports/basketball_nba/events` (cost 0) |
| `odds_api_event_odds__player_points.json` | `GET /v4/sports/basketball_nba/events/07361a8381206817e27bd2697fad7479/odds?regions=us&markets=player_points&oddsFormat=american` (cost 1; `x-requests-remaining` 499 after) |

Event in the odds file: Los Angeles Lakers @ Atlanta Hawks, `commence_time` `2026-11-10T00:10:00Z`, 6 bookmakers, market `player_points` only.

Naming follows `<provider>_<endpoint>__<variant>.json`.

## Loader

`tests/fixtures/odds_api/load_odds_fixture(name)` reads these files. Tests copy a loaded body when they need a smaller case (one bookmaker, one side removed, a player relabeled). They do not type a new response.

## Expanded NBA markets

Recorded 2026-11-10T19:02:40Z. The body is committed unchanged. `odds_api_event_odds__nba_expanded_markets.meta.json` sits beside it and holds the request and the quota headers. The key is not in either file.

| File | Request |
|---|---|
| `odds_api_event_odds__nba_expanded_markets.json` | `GET /v4/sports/basketball_nba/events/cfa503c66cd505776a910921875ef7dd/odds?regions=us&bookmakers=draftkings,fanduel&oddsFormat=american&dateFormat=iso&markets=player_rebounds,player_assists,player_threes,player_steals,player_frees_made,player_field_goals,player_points_rebounds_assists,player_rebounds_assists,player_points_rebounds,player_points_assists,player_double_double` (HTTP 200; `x-requests-last` 9, `x-requests-used` 59, `x-requests-remaining` 441) |

Event: Boston Celtics @ Philadelphia 76ers, `commence_time` `2026-11-11T01:10:00Z`. FanDuel and DraftKings each returned the same 9 markets: assists, double-double, points+assists, points+rebounds, points+rebounds+assists, rebounds, rebounds+assists, steals, threes. `player_frees_made` and `player_field_goals` were requested and neither book posted them. Double-double is Yes only.

`test_process_event_missing_over` copies recorded rebounds and drops Over. The double-double Yes case copies the first recorded Yes. Yes+No and No-only stay on the inline builder, marked `TODO(SPO-106)`, because no No was posted.

## BALLDONTLIE

`bdl/` holds the SPO-130a captures unchanged. Each file is `{request, status, elapsed_s, rate_headers, response}`. The API key is not in these files. `response._raw` on the 429 file is the response text, not a JSON object. No second injuries page was recorded. The only 429 capture is `GET /nba/v1/lineups`, which the client does not call.
