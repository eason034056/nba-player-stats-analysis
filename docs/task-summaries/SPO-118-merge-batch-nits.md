# SPO-118 — Review follow-ups from #43, #45, and #46

- Ticket: SPO-118
- Branch: `feature/SPO-118-merge-batch-nits` (from `origin/dev` at `63d309e`)
- Base: `dev`

## Summary

Small review leftovers after #43 (one vote per book), #45 (NBA field enrichment), and #46 (bulk props) landed on `dev`. NBA backend only. WNBA routes and WNBA daily-picks behavior are unchanged.

`DailyAnalysisService` calls `csv_service.latest_position` directly. Rank source fields on `DailyPick` are asserted, including a fully invalidated `sportsdata_invalid` row. The events list covers a cache hit, a failed top-read join, and a logged lineup-peek failure. Bulk props vote with `daily_analysis._main_book_line` instead of a second copy. A spliced rung no longer keeps the first row's vig. The slowapi limiter falls back to memory when Redis is down and still answers the props route.

## Changes

| Area | File | Change |
|---|---|---|
| Position | `backend/app/services/daily_analysis.py` | NBA picks call `latest_position` directly. |
| Position test | `backend/tests/test_spo111_qa_review.py` | The bare CSV double defines `latest_position`. |
| Rank labels | `backend/app/models/schemas.py` | Both `*_source` fields say `sportsdata_invalid` invalidates the whole row. |
| Rank tests | `backend/tests/test_spo113_field_enrichment.py` | Daily pick asserts all six rank source/season/note fields, plus a fully invalidated row. |
| Rank test name | `backend/tests/test_spo113_qa_review.py` | The out-of-range rank test is named for the clear-and-invalidate check. |
| Events | `backend/app/api/nba.py` | A failed `peek_lineups` is logged with `logger.warning` and the exception. The event list still returns. |
| Events tests | `backend/tests/test_spo113_field_enrichment.py` | Cache hit, top-read load failure, and lineup-peek failure. |
| Main line | `backend/app/services/bulk_props.py` | The local vote algorithm is gone. The point comes from `daily_analysis._main_book_line`. A spliced copy takes the rung's line and prices, not the first row's vig. |
| Main line test | `backend/tests/test_spo114_qa_review.py` | Spliced Over/Under does not keep the first row's vig or fair probabilities. |
| Rate limit | `backend/app/middleware/rate_limit.py` | `swallow_errors=True` and `in_memory_fallback_enabled=True`. |
| Rate limit test | `backend/tests/test_spo114_qa_review.py` | `GET /api/nba/events/{id}/props` still returns the snapshot when limiter storage raises. |
| Docs | `docs/task-summaries/SPO-118-merge-batch-nits.md` | This summary. |

## Why

`getattr` / `callable` hid a missing `latest_position`. A rename would have turned every NBA position null and no test would have failed. The direct call fails loud. The one test double that is not a `CSVPlayerHistoryService` or a `MagicMock` now has the method.

`sportsdata_invalid` is not a label on one rank. `fill_null_defense_ranks` clears both ranks when either vendor value is outside 1..30, and it does not fill either from the CSV. The schema text now says that. The daily-pick test passes all six fields through the single `DailyPick` constructor, and a second case checks the invalidated shape: both ranks null, both sources `sportsdata_invalid`, seasons and notes null.

The events cache stores the Odds API shape. `top_read`, the ET clock, and lineup confirmation are joined on the way out, including on a hit. If the daily-picks read raises, the list still returns and the lineup fields are still filled. A lineup-cache failure used to become an empty map with no log. It is now a warning with the exception, and the clock is still set. `lineup_status` stays null for both clubs, which is the same empty-map result as before.

#46 kept a second `_main_book_line` because #43 was not on `dev` yet. Both are on `dev` now. The shared helper returns the point. Bulk props still returns a stored row, because the response needs the book and the prices. When Over and Under at that point come from different rows, the copy sets line and odds from the rung and does not copy `vig` or the fair probabilities off the first row. Those numbers belong to that row's own prices. A row that already has both kept prices is returned unchanged, so a normal capture (one row per book) is the same.

The props route uses the same Redis-backed limiter as the rest of the app. A down Redis used to raise out of slowapi before the handler read Postgres. `in_memory_fallback_enabled` keeps the configured limits in process memory. `swallow_errors` covers a failure of that fallback so the handler still runs. This is process-local: two app instances do not share the fallback counters. That is the degradation while Redis is down, not a second distributed limiter.

## Tests

- `cd backend && pytest -q`: 988 passed, 23 skipped, 6 xfailed. `test_agent_chat_endpoint_validates_action_and_uses_service` and `test_lineups_api_returns_team_count` passed in this run. They used to fail when slowapi could not reach Redis. The limiter now falls back instead of raising.
- New or extended cases: direct `latest_position`, six rank fields, invalidated rank row, events cache hit, top-read failure, lineup-peek warning, spliced rung, props route with limiter storage down.
- No live Odds API, SportsData, RotoWire, or RotoGrinders call. Recorded fixtures only, plus internal stored-row dicts.
- WNBA files were not edited.

## Follow-ups

- The snapshot writer still stores one row per book per capture, so the spliced-rung path does not run on rows the writer emits today.
- In-memory rate-limit fallback is per process. It is not a shared counter across instances.
