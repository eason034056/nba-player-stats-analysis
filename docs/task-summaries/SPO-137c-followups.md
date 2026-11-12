# SPO-137c — NBA flush also drops pre-league daily-picks keys

- Ticket: SPO-137c
- Branch: `feature/SPO-137c-followups`
- Base: `dev` at `5d2c443`

## Summary

`CacheService.clear_daily_picks_cache("nba")` now deletes the pre-SPO-35 keys `daily_picks:{date}:tz{offset}` and `daily_picks:{date}` as well as `daily_picks:nba:*`. The extra pattern is `daily_picks:[0-9]*`, so the segment after `daily_picks:` must start with a digit. `daily_picks:wnba:*` and `daily_picks:nba:*` do not match it. `clear_daily_picks_cache("wnba")` is still only `daily_picks:wnba:*`. `clear_daily_picks_cache()` with no league is still `daily_picks:*`.

`DELETE /api/nba/daily-picks/cache` is unchanged. It still deletes four keys for one date and one offset. The service sweep deletes every NBA key and every pre-league key, which is a wider observable result, and the existing route test patches `cache_service.delete`.

Five deferred QA patches landed. Three were reverted after their tests failed against behavior that has already changed, or against a request the stub does not intercept.

## Changes

| Area | What changed |
|---|---|
| NBA flush | `clear_daily_picks_cache("nba")` deletes `daily_picks:nba:*` and then `daily_picks:[0-9]*`. The counts are added. |
| WNBA flush | Still `daily_picks:wnba:*` only. |
| No league | Still `daily_picks:*`. |
| Docstring | Describes the digit pattern, why it does not overlap WNBA, and that `delete_pattern` forwards the pattern as Redis `SCAN MATCH`. |
| DELETE route | Left as the four explicit keys. A full NBA sweep would also drop other dates, and `test_nba_cache_route_deletes_the_versioned_key` asserts `cache_service.delete`. |
| Tests | `backend/tests/test_cache.py` seeds the five keys and checks NBA, WNBA, and the no-league clear. |
| QA patches | See Tests. Product code was not edited to make an old assertion pass. |

## Why

Before SPO-35, NBA daily picks lived at `daily_picks:{date}:tz{offset}` and `daily_picks:{date}`. SPO-35 moved new writes to `daily_picks:{league}:{date}:tz{offset}`, and SPO-137a moved NBA reads to `daily_picks:nba:v2:{date}:tz{offset}`. The date-scoped DELETE route already removes the old keys for one date. Lineup refresh and the NBA CSV downloader only call `clear_daily_picks_cache("nba")`, which was `daily_picks:nba:*` and left the pre-league keys in place until the 15-minute TTL.

A glob of `daily_picks:*` on the NBA path would also delete `daily_picks:wnba:*`. `daily_picks:[0-9]*` matches a date and does not match a league name. `delete_pattern` passes that string to `scan_iter(match=...)`. Redis `SCAN MATCH` treats `[0-9]` as one digit. The cache tests' fake uses `fnmatch.fnmatch`, which does the same, so the tests did not need a Python filter.

Switching the DELETE route over to this method would stop being date-scoped. One call would remove every NBA board and every pre-league key, including other offsets. The route stays on its own key list.

## Blast radius

`rg clear_daily_picks_cache` callers:

| Caller | Argument | After this change |
|---|---|---|
| `backend/app/services/csv_downloader.py` (`_update_caches`) | `league="nba"` | NBA CSV refresh. Also drops pre-league keys. Does not match `daily_picks:wnba:*`. |
| `backend/app/services/lineup_service.py` (`fetch_and_store`) | `league="nba"` always, including `wnba_lineup_service` | Same NBA keys as before, plus pre-league keys. Still does not match `daily_picks:wnba:*`. |
| `backend/app/api/wnba.py` (`clear_wnba_daily_picks_cache`) | `league="wnba"` | Still only `daily_picks:wnba:*`. Does not clear more. |
| `backend/app/api/daily_picks.py` | Does not call the service method | Four keys for one date and one offset. Unchanged. |

`backend/app/services/scheduler.py` does not call `clear_daily_picks_cache`. The WNBA lineup job calls `wnba_lineup_service.fetch_and_store`, which hits the lineup row above. That path is WNBA, and it now deletes more than it did: the pre-league date keys, which have no league segment. It still does not delete WNBA boards. Passing `league=self.league` there would start clearing `daily_picks:wnba:*` on a WNBA lineup refresh. That call was left as `league="nba"`.

No other production caller passes `"nba"`.

## Tests / Verification

Reproduction, before the flush change (`tests/test_cache.py`):

```
F..
assert deleted == 4
E   assert 2 == 4
Deleted 2 cache entries (pattern: daily_picks:nba:*)
FAILED test_nba_clear_drops_legacy_date_keys_and_keeps_wnba
1 failed, 2 passed
```

The two that already passed were the WNBA clear and `league=None`. After the change:

```
test_nba_clear_drops_legacy_date_keys_and_keeps_wnba PASSED
test_wnba_clear_drops_only_the_wnba_key PASSED
test_clear_without_league_drops_every_daily_picks_key PASSED
3 passed
```

Seeded keys: `daily_picks:2026-11-11:tz-360`, `daily_picks:2026-11-11`, `daily_picks:nba:v2:2026-11-11:tz-360`, `daily_picks:nba:2026-11-11:tz-360`, `daily_picks:wnba:2026-11-11:tz-360`. NBA deletes the four NBA or legacy keys and keeps the WNBA key. WNBA deletes only the WNBA key. `None` deletes all five and leaves `events:nba:2026-11-11:us`.

`test_nba_flush_clears_versioned_keys_and_leaves_wnba` still passes. It does not seed pre-league keys, so the NBA clear still reports 2.

QA patches, applied with `git am` in this order. `pr47`, `pr68`, and `pr73` were plain diffs with no `From` or `Subject`. Those three were wrapped in a mailbox header so `git am` could keep an author of eason034056. The other five already had subjects, and those subjects were kept. A failing file was reverted with `git revert`, not amended.

| Patch | Result |
|---|---|
| pr47 `test_spo118_qa_review.py` | Landed. 2 passed. Limiter fallback still returns 429 past the props limit. A NaN stored line is not the vote. |
| pr52 `test_spo121_qa_review.py` | Landed. File: 36 passed. New class `TestRosterTeamOnEvent`. |
| pr54 `test_spo123_qa_review.py` | Dropped. `test_omitted_date_and_offset_use_taipei_default` expects the events list to fill an omitted date with today UTC (`2026-11-10` under its frozen clock) and looks for `events:nba:2026-11-10:us:tz480`. SPO-135a sets that omitted date with `nba_slate_date()` (America/New_York). The freeze does not cover that clock, and the list key present was `events:nba:2026-11-11:us:tz480`. Product code was not changed. Revert: `49ccb59`. |
| pr59 `test_spo126_qa_team_codes_and_provider.py` | Landed. 21 passed. |
| pr65 `test_spo132b_optional_vpc.py` | Landed. 8 passed, 3 skipped. Terraform is not on PATH, so `TestVpcIdConsole` skipped. It did not fail. |
| pr68 `test_spo135a_slate_date.py` | Dropped. `test_event_detail_omitted_date_is_the_callers_local_day` got 200 from the detail route and the local date `2026-11-10`, then `GET /api/nba/events` returned 401. Patching `app.api.nba.get_events` replaces the name the detail handler calls. FastAPI already bound the list route to the original function, so the list request reached The Odds API. Product code was not changed to make that stub apply. Revert: `d699d80`. |
| pr73 `test_spo132e_qa_verify_edges.py` | Landed. 4 skipped. Postgres is not reachable, so the existing helper skips. It did not fail. |
| pr83 `test_spo137a_qa.py` | Dropped. `test_nba_flush_leaves_pre_league_and_wnba_keys` asserts `clear_daily_picks_cache("nba")` deletes 2 and leaves the pre-league keys. This ticket deletes those keys on purpose (`assert 4 == 2`). The other three tests in the file passed (glob, DELETE's four keys, event-reads v1). The whole commit was reverted so the old flush pin is not in the suite. Revert: `7181ac6`. |

Test names added and kept:

- `test_nba_clear_drops_legacy_date_keys_and_keeps_wnba`
- `test_wnba_clear_drops_only_the_wnba_key`
- `test_clear_without_league_drops_every_daily_picks_key`
- `test_fallback_still_enforces_the_props_limit_when_redis_is_down`
- `test_non_finite_stored_line_never_becomes_the_vote`
- `TestRosterTeamOnEvent`: `test_missing_home_or_away_falls_back_to_the_log_club`, `test_trade_date_uses_the_club_on_that_day`, `test_trade_date_does_not_reuse_the_older_stint`, `test_last_game_before_the_trade_keeps_the_old_club`, `test_does_not_reuse_an_older_stint_when_facing_the_former_club`, `test_abbreviation_event_clubs_canonicalise`, `test_cache_document_keeps_clubs_off_the_public_body`, `test_cache_without_clubs_falls_back_to_the_log_club`
- `test_every_nba_spelling_resolves_to_one_code`, `test_compact_forms_still_resolve`, `test_bare_city_is_not_guessed`, `test_g_league_affiliates_do_not_borrow_the_parent_code`, `test_wnba_full_names_never_land_on_an_nba_code`, `test_recorded_sparks_stay_wnba`, `test_unknown_league_still_raises`, `test_concrete_providers_accept_the_abstract_parameters`, `test_the_odds_api_provider_still_constructs`, `test_frozen_defaults_and_derived_values`
- `test_unset_is_null_and_does_not_error`, `test_valid_ids_are_accepted`, `test_invalid_ids_are_rejected` (skipped here; terraform is not on PATH)
- `test_uuid_id_table_never_reports_ok_after_a_query_error`, `test_uuid_id_table_with_zero_sequences_verifies` (skipped here; Postgres is not reachable)

`cd backend && python -m pytest tests -q`

1556 passed, 68 skipped, 6 xfailed, 0 failed.

Integration test: SKIPPED (env unset). Fabrication scan: PASS. The new cache test writes string markers into an in-memory fake. It does not invent an external API body. The landed QA files use recorded fixtures or local schema and script checks.

No OpenAPI change. No schema added or removed. No path added or removed.

## Follow-ups

- Re-apply the three pr83 tests that still match the code (the `daily_picks:nba:*` glob, the four DELETE keys, and the event-reads v1 miss) without `test_nba_flush_leaves_pre_league_and_wnba_keys`.
- `fetch_and_store` on `wnba_lineup_service` still calls `clear_daily_picks_cache(league="nba")`. It now also drops pre-league keys. It still does not drop WNBA keys. Do not switch that argument to `self.league` without deciding that a WNBA lineup refresh should clear WNBA boards.
- Run `TestVpcIdConsole` where `terraform` is on PATH. Run `test_spo132e_qa_verify_edges.py` where Postgres is reachable.
- `docs/progress.md` still says the #52 QA cases and the SPO-118 QA file are unapplied, and that the events list fills an omitted date with today UTC. This ticket does not edit that file. The replacement notes are in the PR body.
