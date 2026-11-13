# SPO-135g — top_read skips Out players

- Ticket: SPO-135g
- Branch: `feature/SPO-135g-top-read-skip-out`
- Base: `dev`
- Stacks on PR #77, which stacks on #72 and #69. After those squash-merge, `git merge origin/dev` on this branch.

## Summary

`best_top_reads` skips a stored candidate whose player matches an Out row in a fresh `injuries:nba:latest` snapshot. The match is `match_injury_entry`, the same helper daily picks and `/reads` use: case, punctuation, and accents fold, and the suffix stays. The choice is per game. The next-highest historical probability on that game is the top read. When every candidate is Out, that game's `top_read` is null.

A missing, stale, malformed, or unreadable snapshot does not skip, and this path does not log that. The events request only reads Redis. It does not call BALLDONTLIE. Raw Doubtful stays Questionable, and top_read does not look at `raw_status`. SPO-135h keeps that player's blend. WNBA does not load this snapshot.

The startup job's display name is `NBA Injury Snapshot Startup Refill`. The job id is still `nba_injuries_startup_fill`.

## Why

SPO-135e made daily picks and `/reads` honor the snapshot. `best_top_reads` still ranked every stored row by historical probability, so an Out player could be the top read when that row was a different line than the published pick. The Today board only hides that read after the daily-picks query has loaded. If that query never succeeds, the Out player's top read still shows. The events response has to be the guard.

The snapshot is read at request time, not copied off `DailyPick.injury_status`. A pick cached while the snapshot was fresh can still be an Out player, and a pick cached with a null status can become Out after the snapshot arrives. A stale key means picks leave `injury_status` null. Top read follows that: it does not skip.

## Changes

| Area | What changed |
|---|---|
| `best_top_reads` | Optional `injury_entries`. A fresh list skips normalized status `Out`. None skips nobody. The next row on that `event_id` wins. An event with no remaining row is absent |
| Events | `load_stored_top_reads` reads `injuries:nba:latest` after the picks cache. No warning on a missing, stale, malformed, or failed read. No BALLDONTLIE call |
| Contract | `TopRead` fields and nullability are unchanged. The description says an Out player is skipped |
| Startup | Display name `NBA Injury Snapshot Startup Refill`. Id, cron, and the fill rules are unchanged |
| QA | `backend/tests/test_spo135e_qa.py` applied with `git am`. Those five tests passed. No product change came out of them |

## Blast radius

`best_top_reads` has one production caller: `load_stored_top_reads`. That is called by `_events_with_top_reads` in `backend/app/api/nba.py`.

Responses that carry `top_read`:

| Response | How it gets `top_read` |
|---|---|
| `GET /api/nba/events` | `attach_top_reads` after `load_stored_top_reads` |
| `GET /api/nba/events/{event_id}` | One event from that same list |

`GET /api/wnba/events` builds `NBAEvent` and leaves `top_read` null. It does not call `best_top_reads`. WNBA daily picks still ignore the snapshot. The frontend `topReadSchema` is still `player`, `market`, `side`, `line`, `probability`. `top_read` is still nullable. No frontend file changed.

A name that used to win only because a Jr row was stripped still does not match. `Gary Trent Jr.` Out does not skip `Gary Trent`.

## Tests / Verification

Recorded fixtures only. No new fixture file. No live BALLDONTLIE or Odds API call. Gary Trent rows in the tests are a recorded Out entry with only `player` changed. The injury page has neither name. Historical rates in the tests come from the CSV double so one candidate is strictly better. Lines and book prices stay on the recorded player_points capture.

- `cd backend && python3 -m pytest tests -q --tb=line` → 1390 passed, 28 skipped, 6 xfailed, 0 failed.
- QA file `tests/test_spo135e_qa.py`: 5 passed. Nothing in that file required a product fix.
- Redis on localhost. Snapshot seeded by `refresh_nba_injuries_from_bdl` with a mocked transport over the recorded `player_injuries` page and a terminal copy of that page (190 stored rows). `GET /api/health` 200. `GET /api/nba/events?date=2026-11-10&regions=us&tz_offset=480` 200.

The picks cache for that request is the recorded player_points bookmakers. Only one description changed: the recorded Dyson Daniels 10.5 outcomes were stored under Dominick Barlow, the recorded Out row (team PHI). Matisse Thybulle 6.5 and Walker Kessler 14.5 kept their recorded names and points. Barlow's historical probability was 0.91, Thybulle's 0.72, Kessler's 0.80 on the next recorded event (`1df5ff8fe9c6d2dbff1d0ae176063b37`, Cavaliers at Hornets).

Lakers at Hawks (`07361a8381206817e27bd2697fad7479`) came back as Matisse Thybulle, `player_points`, over 6.5, probability 0.72. Dominick Barlow was not the top read. The Hornets game kept Walker Kessler, `player_points`, over 14.5, probability 0.8. `GET /api/nba/events/07361a8381206817e27bd2697fad7479` returned the same Thybulle top read. The startup log line used the new display name. The request did not call BALLDONTLIE.

## Open question

Doubtful. The cache stores it as Questionable and keeps `raw_status`. This PR does not skip a Doubtful player when choosing a top read. SPO-135h keeps the blend, the same as Questionable. Out still blocks the blend and is still skipped here.

## Follow-ups

- [x] Eason: Doubtful keeps a blend. Closed by SPO-135h.
- [ ] A same-slate Odds API capture paired with a same-slate BALLDONTLIE injury page. That needs live calls and waits on the key upgrade. This PR does not record it.
