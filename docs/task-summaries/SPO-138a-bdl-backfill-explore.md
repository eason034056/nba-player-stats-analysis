# SPO-138a — BDL season walks: games and stats by season, one shape per stats row

- **Ticket:** SPO-138a, the first of SPO-138a–g (the NBA history backfill, one layer per PR)
- **Branch:** `feature/SPO-138a-bdl-backfill-explore`
- **Base:** `dev`
- **Depends on:** nothing. SPO-138b is independent of this PR; either can merge first.

## Summary

The BDL client can walk a whole season, and every stats row it returns comes out in one shape, whatever the season. This is the fetch layer of the SPO-138 backfill. Nothing calls it yet; the backfill command is SPO-138f.

1. `BdlClient.list_games(seasons=, season_type=)` and `list_stats(seasons=)`.
2. `normalize_stat_row` in `bdl_stats.py`: one did-not-play rule, every minutes spelling, percentages as 0–1 fractions. An unknown spelling raises instead of being guessed.
3. `scripts/explore_bdl_backfill.py` and 32 recordings under `backend/tests/fixtures/bdl/`.

## Changes

| Area | Files | Change |
|---|---|---|
| BDL client | `backend/app/services/bdl_client.py` | `list_games(seasons=, season_type=)`, `list_stats(seasons=)`, public `SEASON_TYPES`, `rate_limit_ceiling` |
| Stats rows | `backend/app/services/bdl_stats.py` | New. `normalize_stat_row`, `parse_minutes`, `BdlStatLine` |
| Exploration | `scripts/explore_bdl_backfill.py` | New. Probes season pages, later cursors, and single games by id; saves fixtures |
| Fixtures | `backend/tests/fixtures/bdl/` | 32 recordings: season pages for each game type, later stats pages with new spellings, empty and HTTP 400 answers, and 7 games where BDL's data is wrong (SPO-138e and g use them) |
| Tests | `test_bdl_stats.py` (new), `test_bdl_client.py` (extended) | Unit tests on the recordings; 4 live integration tests |

## Why

- **One did-not-play rule.** A row is did-not-play when nothing in it shows court time: no seconds, no stat, and `plus_minus` zero or null. BDL's spelling changes by season: `min` is null, `""`, `"0:00"`, `"00"`, or `"0"`, with `plus_minus` null or 0. If those rows were read as played, the 2025-26 rows from 2025-12-23 on would show 30.5 players a game, against about 21 in every other season. The cost: a player on court for a few seconds who recorded nothing and left with the score level also reads as did-not-play (28 to 62 rows a season in 2019-20 to 2024-25).
- **`team_id` is the team in that game**, not `player.team_id`, which is the player's team today.
- **Percentages are 0–1 fractions.** A shot type never taken is null, because several seasons send 0 there and 0 of 0 is not 0%. The 2019-20 to 2021-22 play-in games send a 0–100 scale. All 584 of those values equal 100 × made / attempted, so a value over 1 is divided by 100. Anything outside both scales is refused.
- **An unknown spelling is refused, not guessed.** `normalize_stat_row` raises `BdlStatRowError`. The writer skips and counts the line (SPO-138c), and a refused line keeps its season from `done` (SPO-138e).
- **`season_type` is requested, not inferred.** The `/v1/games` object does not say its type. `postseason` is true for the 2019-20 bubble play-in and false for 2025-26, so it cannot classify games. The backfill therefore walks each season once per type: `regular`, `playoffs`, `playin`, `ist`. Any other value, preseason included, raises before a request is sent.
- **A rate ceiling.** `rate_limit_ceiling` caps the per-minute budget at the lower of the observed (or configured) limit and the ceiling. The backfill passes 500, which leaves the rest of the 600/min key free for callers outside this process.
- **External API rules (CLAUDE.md).** The exploration script, the recorded fixtures, and the live tests ship together with the client change. Every unit test loads a recording. A test that needs a bad row changes a copy of a recorded one.

## Tests / Verification

- **Full backend suite** on this branch: `cd backend && env -u DATABASE_URL .venv/bin/python -m pytest -q` → 3 failed, 1676 passed, 67 skipped, 6 xfailed, in 45.57s. The 3 failures are `tests/test_spo132b_optional_vpc.py::TestVpcIdConsole`, which fail the same way on `origin/dev` in the same checkout (pre-existing, not from this PR).
- **Integration (`RUN_INTEGRATION=1`)**, run on this branch 2026-11-20: 5 passed. They cover the `list_games` smoke test, `list_stats` by season, `list_games` by season type, and the play-in and Cup final (one test, two parameters). The smoke test needs a local Redis for the rate limiter; this run used a throwaway `redis:7-alpine` container.
- **BDL tests** on this branch (`tests/test_bdl_*`): 95 passed, 5 skipped, in 1.09s (the skips are the live tests, run above with `RUN_INTEGRATION=1`)
- **Mutation checks:** the normalizer rules, 9 of 9 mutants caught (2026-11-18).
- **Fabrication scan:** PASS, checked by hand. Every new unit test loads a recording from `tests/fixtures/bdl/`, saved by `scripts/explore_bdl_backfill.py`, and no key is in any recording.
- **Frontend:** not touched.

## CI

`langsmith==0.14.17` is pinned next to `langchain-openai` in `backend/requirements.txt`. The same pin is in `scripts/agents/requirements_agents.txt` (the walk-forward job installs that file) and `nba_lineup_rag/requirements.txt`, which also install LangChain without a pin. langsmith 0.15.x fails to import under pydantic 2.8.0 (`FeedbackConfigSchema` NameError), so pytest exited before any test ran. pydantic stays at 2.8.0.

Fresh Python 3.11 venv, `pip install -r backend/requirements.txt`: `import langsmith.utils` succeeds (langsmith 0.14.17, pydantic 2.8.0). Backend suite: 1674 passed, 72 skipped, 6 xfailed, in 22.60s. The walk-forward job's four files, after installing both requirements files (still langsmith 0.14.17 and pydantic 2.8.0): 29 passed, in 23.79s.

## Follow-ups

- [ ] SPO-138b to g, in order: schema, writer, walker, verify, the backfill command, the gap view.
- [ ] ML: the 2025-26 playoffs and play-in send no did-not-play rows. Take availability from injuries and lineups.

## Progress notes (for the docs PR)

- SPO-138a: the BDL client walks games and stats by season (games also by season type), and every stats row is normalized to one shape.

---

**Ticket**: SPO-138a
**Branch**: `feature/SPO-138a-bdl-backfill-explore`
**Task summary**: `docs/task-summaries/SPO-138a-bdl-backfill-explore.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
