# SPO-137a — NBA picks expose the BALLDONTLIE injury word

- Ticket: SPO-137a
- Branch: `feature/SPO-137a-injury-status-raw`
- Base: `dev`
- Stacks on PR #81 (`feature/SPO-135h-doubtful-as-questionable` at `ddf33e2`). The diff includes that unmerged stack until those PRs squash-merge. After that, `git merge origin/dev` on this branch. Do not push this work back onto the 135h branch.

## Summary

NBA daily picks now return BALLDONTLIE's status word as `injury_status_raw` beside `injury_status`. The raw word is copied from the same matched snapshot row, with no case change and no trimming, so a stored Doubtful stays `injury_status="Questionable"` and `injury_status_raw="Doubtful"`. Both fields are null together when the snapshot is missing, stale, or malformed, or when the name is missing or ambiguous. A stored payload that omits the new field still validates, and the raw value is null. WNBA leaves both fields null.

Out still blocks. Doubtful does not. `build_nba_signals` still takes only `injury_status`. `raw_status` stays on the Redis snapshot (`injuries:nba:latest`) and is not passed back into the blend.

NBA cache keys moved so a payload built under the old Doubtful rule, or a payload without `injury_status_raw`, is not read. Daily picks use `daily_picks:nba:v2:{date}:tz{offset}` (15 min). Event reads use `nba:event-reads:v2:{event_id}:m={market}` (60 s). WNBA keys stay `daily_picks:wnba:{date}:tz{offset}`.

The Doubtful-to-Questionable mapping came via Lead. Code and decision notes describe the rule only.

## Why

`injury_status` is the word the scorer and the board already understand. The source word was on the snapshot as `raw_status` and was not on the pick, so a client could not tell a stored Doubtful from a stored Questionable. Copying that word onto the pick keeps the two facts on one row. Blocking stays on the normalized word, where only Out blocks, so the raw field is not an input to `build_nba_signals`.

A 15-minute daily-picks document and a 60-second event-reads document can still be the body from before this field, and from before Doubtful stopped blocking. A new key version is the way those bodies are never read. Putting `v2` after `nba` keeps the existing league flush `daily_picks:nba:*`. WNBA has no injury snapshot on the pick, so its key and its flush stay as they are.

A legacy document that still arrives without the field must validate. There is no validator that rejects a pick with `injury_status` set and `injury_status_raw` missing.

## Changes

| Area | What changed |
|---|---|
| `DailyPick` | `injury_status_raw: Optional[str] = None`. `injury_status` description points at it |
| Writer | `matched_injury_words` reads `status` and `raw_status` from the matched snapshot row. NBA picks copy both. WNBA leaves both null |
| Blend | Unchanged. `build_nba_signals` still has no `raw_status` parameter. Only Out blocks |
| NBA daily-picks cache | Key is `daily_picks:nba:v2:{date}:tz{offset}`. Readers, the analysis writer, `load_stored_top_reads`, and `DELETE /api/nba/daily-picks/cache` use it. The delete also drops the previous unversioned NBA key and the pre-league keys |
| NBA flush | `clear_daily_picks_cache(league="nba")` is still `daily_picks:nba:*`, which matches v2 and the previous NBA key, and does not match WNBA |
| Event reads | `event_reads_cache_key` is `nba:event-reads:v2:...`. The reader and the writer both call that function. v1 is not read |
| WNBA | Key, flush, and both injury fields stay as they were. Both fields are null |
| Wording | The mapping comment and the same sentences in the SPO-131 and SPO-135 decisions, and in the SPO-131 and SPO-135h task summaries, describe the rule without naming who decided it or where |
| QA tests | `backend/tests/test_spo135h_qa.py` from the #81 patch, applied with `git am` |

## Blast radius

`injury_status_raw` is only on `DailyPick`. PropRead, TopRead, TeamLineup, NBAEvent, BulkPropPlayer, and BotPick do not carry `injury_status`, and they did not gain the raw field. `/reads` still uses the normalized word only to null `combined_probability` for Out. It does not serialize either field. `player_projections.injury_status` in `db.py` is unused. No migration.

| Surface | NBA | WNBA |
|---|---|---|
| `GET /api/nba/daily-picks` and `POST /api/nba/daily-picks/trigger` | Both fields. A matched Doubtful is Questionable plus raw Doubtful. Out is Out plus raw Out, blend null. Missing or ambiguous name is null plus null | — |
| `GET /api/wnba/daily-picks` and `POST /api/wnba/daily-picks/trigger` | — | Both fields null. Analysis still ignores the snapshot |
| `GET /api/nba/events/{event_id}/reads` | No injury fields on the body. Cache key is now v2, so a v1 body is not read | No reads route |
| Bot picks, lineups, props | Unchanged | Unchanged |
| Frontend `dailyPickSchema` | Zod strips an unknown key, so the new field is ignored until the schema adds it | Same |

Stale cache (QA should-fix from #81, folded here):

| Key | Before | After | Who reads and writes it |
|---|---|---|---|
| NBA daily picks, 15 min | `daily_picks:nba:{date}:tz{offset}` | `daily_picks:nba:v2:{date}:tz{offset}` | `daily_picks_cache_key`. Analysis `get`/`set`, `load_stored_top_reads`, `DELETE /api/nba/daily-picks/cache` |
| NBA event reads, 60 s | `nba:event-reads:v1:{event_id}:m={market\|*}` | `nba:event-reads:v2:...` | `event_reads_cache_key`. `get_event_reads` is the only reader and writer. No separate `delete_pattern` |
| WNBA daily picks | `daily_picks:wnba:{date}:tz{offset}` | Unchanged | `daily_picks_cache_key("wnba", ...)`. `DELETE /api/wnba/daily-picks/cache` still calls `clear_daily_picks_cache(league="wnba")` |

`clear_daily_picks_cache(league="nba")` still deletes `daily_picks:nba:*`. That pattern matches the v2 key and the previous unversioned NBA key. It does not match `daily_picks:wnba:*`. Lineup refresh and the CSV downloader call that NBA flush. The date-scoped NBA delete also deletes the previous NBA key and the two pre-league keys, so one clear drops what a reader used to see and what it sees now.

Comment rewrite (QA nit): `nba_injuries._mapped_status` no longer names who chose the mapping or the chat it came from. The same sentences in `docs/decisions/SPO-131/decision_20261111_bdl-injury-cache.md`, `docs/decisions/SPO-135/decision_20261111_doubtful-as-questionable.md`, `docs/task-summaries/SPO-131-bdl-injuries.md`, and `docs/task-summaries/SPO-135h-doubtful-as-questionable.md` now state the rule. The decision came via Lead. `docs/decisions/spo-121-bulk-reads/decision_20261110_bulk-reads-and-combined-tier.md` now names the v2 event-reads key.

QA test patch: `pr81_qa_tests1.patch` was applied with `git am`. The commit author is eason034056. Its assertions check the blend, the board floor, and `top_read`. They construct `DailyPick` with `injury_status` only, which defaults `injury_status_raw` to null, and they do not assert that the raw field is absent. Nothing in that file conflicted with the new field, so there is no follow-up commit that edits those assertions.

## Tests / Verification

Recorded fixtures only. No live BALLDONTLIE or Odds API call. Odds shells are `odds_api_event_odds__player_points.json`. Injury words come from `player_injuries__page1.json` via `_entry`. Route samples use that odds capture with one description relabeled, a stub CSV, and a fresh in-process injury cache.

`cd backend && python3 -m pytest tests -q --tb=line`

1475 passed, 33 skipped, 6 xfailed, 0 failed.

Integration test: SKIPPED (env unset). Fabrication scan: PASS. The new tests do not invent an injury word. They read the recorded page.

OpenAPI, `DailyPick` only. No schema name added or removed. No path added or removed.

- `injury_status` description gains the sentence "The source word is injury_status_raw."
- New property `injury_status_raw` (`string | null`, default null). Description: copied from the same snapshot row, no case change and no trimming. Null in the same cases as `injury_status`. A stored payload that omits the field validates as null.

Trimmed route samples (TestClient, fixture-backed, stub CSV `p_over` 0.72). The Doubtful blend on this capture is 0.6095, under the default 0.65 floor, so the default published board drops him. Out stays on that board.

`GET /api/nba/daily-picks?date=2026-11-10&tz_offset=480&min_probability=0.5&min_games=5`

```json
{"player_name":"Malik Dia","metric":"points","direction":"over","threshold":10.5,"injury_status":"Questionable","injury_status_raw":"Doubtful","combined_probability":0.6095,"lineup_confirmed":null}
```

`POST /api/nba/daily-picks/trigger?date=2026-11-10&tz_offset=480` with the recorded Out row as the relabeled player. `total_picks` is 1.

```json
{"player_name":"Dominick Barlow","metric":"points","direction":"over","threshold":10.5,"injury_status":"Out","injury_status_raw":"Out","combined_probability":null,"lineup_confirmed":null}
```

`GET /api/wnba/daily-picks` and `POST /api/wnba/daily-picks/trigger`, same date and offset, Doubtful row present in a snapshot the WNBA path does not read:

```json
{"player_name":"Malik Dia","metric":"points","direction":"over","threshold":10.5,"injury_status":null,"injury_status_raw":null,"combined_probability":null,"lineup_confirmed":null}
```

## Follow-ups

- Frontend `dailyPickSchema` does not yet declare `injury_status_raw`. Zod strips it.
- `docs/progress.md` still says Out / Doubtful null the blend. The replacement row is in the PR body. This ticket does not edit that file.
