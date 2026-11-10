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

## Not recorded yet

`tests/fixtures/odds_api/record_fixtures.py` writes the two files below when `ODDS_API_KEY` is set. It was not run for SPO-106 (no key), so the files are not in git.

| File | Request |
|---|---|
| `odds_api_event_odds__nba_expanded_markets.json` | One `GET /v4/sports/basketball_nba/events/{id}/odds` with `regions=us`, `bookmakers=draftkings,fanduel`, `oddsFormat=american`, and `markets=` set to rebounds, assists, threes, steals, frees made, field goals, the four combo keys, and `player_double_double`. |
| `odds_api_event_odds__wnba_expanded_markets.json` | The same odds call for `basketball_wnba`, and only if the free WNBA events list is non-empty. |

The events list itself is free and is not written over the SPO-98 file. Unit tests that need a market in this table keep an inline builder, marked `TODO(SPO-106)`, until `first_posted_market` can see an outcome in the file.
