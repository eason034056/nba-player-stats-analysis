# SPO-138e — Verify a walked season before marking it done

- **Ticket:** SPO-138e, the fifth of SPO-138a–g (the NBA history backfill, one layer per PR)
- **Branch:** `feature/SPO-138e-backfill-verify`
- **Base:** `dev`
- **Depends on:** SPO-138d (walker), merged into `dev`.

## Summary

`finish_season` checks a walked season against its checkpoints, then marks its shards `done`, or marks each shard with a problem as `error`. `verify_season` returns the same report without writing anything. Nothing calls them yet; the command is SPO-138f.

## Changes

| Area | Files | Change |
|---|---|---|
| Backfill | `backend/app/backfill/verify.py` | New. `verify_season`, `finish_season`, `SeasonReport`, `Problem` |
| Tests | `backend/tests/test_backfill_verify.py` | New. Database tests, including the 7 games recorded in SPO-138a where BDL's data is wrong |

## Why

- **`done` is final, so it has to be earned.** A `done` shard is never walked again. A season is marked done only when every check that a re-walk could fix passes:
  - every shard was walked to its last page;
  - each game type has as many games stored as were fetched, counted live, so a game that moved to a later type shows up;
  - stats lines stored + dropped + rejected equal lines fetched;
  - no line was dropped;
  - no line was refused.
- **A refused line blocks `done`.** A refused line is a spelling the normalizer cannot read yet. The fix is in code, followed by a re-walk. The rule exists because 2019-20 to 2021-22 were first marked done with 241 refused lines.
- **A failed check marks only its own shard `error`**, prefixed `verification:`. The other shards keep their status. A failed shard sends no request on the next run, because all its pages are stored; `--restart-season` re-walks it.
- **Gaps in BDL's own data are listed but do not block**, because a re-walk returns the same data:
  - final games with no lines;
  - the fewest and most lines per final game;
  - final games where a team's player points differ from its score;
  - final games where a team's minutes add up to under 230. A team plays at least 240, and seasons that send whole minutes round a team's total to 231–239. A team with no lines counts as 0 points and 0 minutes.
- In this PR the points and minutes checks are SQL inside `verify.py`. SPO-138g moves them into a view that `player_game_log` also reads, so the rule lives in one place.

## Tests / Verification

All runs use a throwaway `postgres:16-alpine`, with `DATABASE_URL` set explicitly to it.

- **Full backend suite** on this branch: `cd backend && DATABASE_URL=<throwaway db> python -m pytest -q` → 6 failed, 1930 passed, 30 skipped, 7 xfailed. The 6 failures are Terraform console tests: 3 in `test_spo132b_optional_vpc.py::TestVpcIdConsole` and 3 in `test_spo140_terraform_environments.py::TestNamePrefixConsole`. They fail the same way on a clean `origin/dev` checkout, because the local Terraform has no provider plugins installed (`terraform init` was not run). They are not from this PR.
- **Database tests** on this branch: `pytest tests/test_backfill_*.py tests/test_migration_*.py tests/test_bdl_*.py tests/test_db.py` → 266 passed, 5 skipped. The skips are the live tests.
- **Mutation checks:** the verify rules, 6 of 6 mutants caught (2026-11-18).
- **Fabrication scan:** PASS, checked by hand. Each test stores recorded pages. The 7 BDL gap games are recordings fetched by game id.
- **Frontend:** not touched.

## Follow-ups

- [ ] SPO-138f: the `python -m app.backfill` command that walks and verifies seasons.

## Progress notes (for the docs PR)

- SPO-138e: a walked season is marked `done` only after verification. BDL's own data gaps are listed and do not block.

---

**Ticket**: SPO-138e
**Branch**: `feature/SPO-138e-backfill-verify`
**Task summary**: `docs/task-summaries/SPO-138e-backfill-verify.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
