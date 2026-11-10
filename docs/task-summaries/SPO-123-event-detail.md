# SPO-123 — One NBA event from the events list

- Ticket: SPO-123
- Branch: `feature/SPO-123-event-detail` (from `origin/dev`)
- Base: `dev`

## Summary

`GET /api/nba/events/{event_id}` returns one NBA game. The body is `NBAEvent`, the same model `GET /api/wnba/events` already returns for each game, plus the fields `GET /api/nba/events` already joins onto an NBA game (`commence_time_et`, `display_tz`, `lineup_status`, `top_read`). The Odds API `id` is `event_id`. The sport is `sport_key`.

The handler calls the existing list function. The same `date`, `regions`, and `tz_offset` produce the same Redis key (`events:nba:{date}:{regions}:tz{offset}`). A hit does not call `odds_provider.get_events` or `odds_gateway`. A miss uses that list request, which is the events endpoint, and stores the list. This route does not call `/events/{id}/odds`.

A malformed id is HTTP 404 `Malformed event_id`, using `event_id_is_well_formed` (the same rule as `GET /api/nba/events/{event_id}/props`). A well-formed id that is not on that date's list is HTTP 404 `Event not found`. The slowapi limit is `settings.rate_limit_props`, the same limit as the props route.

`GET /api/nba/events/{event_id}/reads` (PR #52) is a different path. This change does not edit that handler.

## Changes

| Area | File | Change |
|---|---|---|
| HTTP | `backend/app/api/nba.py` | `GET /api/nba/events/{event_id}`. Response model `NBAEvent`. Calls `get_events`. 404 for a malformed id and for an id missing from that date's list. Limit `settings.rate_limit_props`. |
| Tests | `backend/tests/test_spo123_event_detail.py` | Found, not on the date, malformed id, cache hit. Bodies come from `odds_api_events__basketball_nba.json`. |
| Docs | `docs/task-summaries/SPO-123-event-detail.md` | This summary. |

## Why（設計意圖 / 取捨）

The game page already loads the day's list and finds one id. A separate Odds API call per game would spend a request the list has already spent. Calling `get_events` keeps one cache key, one date filter, and the same joined fields (`top_read`, ET clock, lineup confirmation). WNBA's list items are `NBAEvent` with the five core fields; the NBA list fills the optional fields on the way out. Returning that model keeps one shape.

The id check runs before the list read, so a malformed id does not touch Redis or the provider. An id on another local date is absent from this date's list, so the response is 404 until the client sends that date. The list defaults stay: omitted `date` is today UTC, omitted `tz_offset` is 480, omitted `regions` is `us`.

The route is registered beside `/events/{event_id}/props`. The reads route from PR #52 is `/events/{event_id}/reads`. The three paths do not share a handler.

## Tests / Verification

- Backend pytest: `cd backend && /tmp/spo123-venv/bin/python -m pytest --tb=line -q` → **1049 passed, 23 skipped, 6 xfailed, 0 failed**
- Frontend: not touched.
- Integration test: SKIPPED (env unset). The new route's miss uses the existing events list call. No new live endpoint.
- Fabrication scan: PASS. The events body in the new tests is `load_odds_fixture("odds_api_events__basketball_nba.json")`. The cache payload copies `id`, `sport_key`, `home_team`, `away_team`, and `commence_time` from that file into the list's stored shape.

Cases:

- Found: Lakers at Hawks, `07361a8381206817e27bd2697fad7479`, tip `2026-11-10T00:10:00Z`, from the recording. `sport_key` is `basketball_nba`. The ET clock is `2026-11-09T19:10:00-05:00`. The list provider runs once. The odds gateway does not.
- Not found: the first recorded id whose tip is not on `2026-11-10` (Celtics at 76ers, `2026-11-11T01:10:00Z`) returns 404 `Event not found`.
- Malformed: `!!!`, `bad id`, `a.b`, `a..b` return 404 `Malformed event_id` and do not call the list provider.
- Cache hit: the stored list for `events:nba:2026-11-10:us:tz0` returns the same game. `odds_provider.get_events`, `get_event_odds`, and `odds_gateway.get_market_snapshot` stay at 0 calls.

The route limit string matches `get_event_props`.

## Follow-ups

- [ ] The frontend game page still loads the whole list and finds the id in the client. Pointing it at this route is a separate change.
- [ ] An id is only found on the date, region, and offset that list used. A client that omits `date` searches today UTC.
- [ ] WNBA has no single-event route. This ticket is NBA only.
