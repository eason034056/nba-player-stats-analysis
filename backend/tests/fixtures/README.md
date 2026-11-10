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
