# SPO-138c — Backfill writer: one BDL page and its checkpoint in one transaction

- **Ticket:** SPO-138c, the third of SPO-138a–g (the NBA history backfill, one layer per PR)
- **Branch:** `feature/SPO-138c-backfill-writer`
- **Base:** `dev`
- **Depends on:** SPO-138a (client and normalizer) and SPO-138b (schema), both merged into `dev`.

## Summary

`write_games_page` and `write_stats_page` store one BDL page in the SPO-138b tables. In the same transaction they move the shard's checkpoint past that page. Nothing calls them yet; the walker is SPO-138d.

## Changes

| Area | Files | Change |
|---|---|---|
| Backfill | `backend/app/backfill/__init__.py`, `writer.py` | New. `write_games_page`, `write_stats_page`, `PageWrite`, `GAME_TYPE_BY_SEASON_TYPE`, `season_label` |
| Tests | `backend/tests/test_backfill_writer.py` | New. Database tests on scratch databases, fed with SPO-138a's recordings |

## Why

- **A page and its checkpoint commit together.** After a crash, either both are there or neither is. A resumed walk never skips a page.
- **Every insert is an upsert on the natural key**, so a replayed page adds no row. `rows_written` is set from `count(*)`, so a replay cannot inflate it either.
- **A game's type is the type its page was requested with.** BDL's names are translated with `GAME_TYPE_BY_SEASON_TYPE`: `regular` → `regular_season`, `playin` → `play_in`, `ist` → `cup_championship`. A test ties `SEASON_TYPES`, the translation, and `CANONICAL_GAME_TYPES` together.
- **One bad line does not stop a season.**
  - A row that `normalize_stat_row` refuses is skipped and counted.
  - A line whose game is not stored is dropped and counted, instead of failing the page on the foreign key. Every game type is stored, so any drop is unexpected, and SPO-138e blocks `done` on it.
- **A page that cannot be right is refused whole.**
  - A row from another season refuses the page before any SQL runs.
  - A value the database refuses, such as a team that is not stored, rolls back the page together with its checkpoint.
- **Fetched, dropped, and rejected rows are counted inside the page's transaction**, so each page is counted once. SPO-138e checks stored + dropped + rejected = fetched.
- **The last page leaves the cursor NULL and the shard `in_progress`.** A shard becomes `done` only after its season is verified (SPO-138e).
- **Players come only from kept rows.** The raw `min` string is kept next to `seconds_played`, so a minutes spelling can be checked again later.

## Tests / Verification

All runs use a throwaway `postgres:16-alpine`, with `DATABASE_URL` set explicitly to it.

- **Full backend suite** on this branch: `cd backend && DATABASE_URL=<throwaway db> python -m pytest -q` → 6 failed, 1900 passed, 30 skipped, 7 xfailed. The 6 failures are Terraform console tests: 3 in `test_spo132b_optional_vpc.py::TestVpcIdConsole` and 3 in `test_spo140_terraform_environments.py::TestNamePrefixConsole`. They fail the same way on a clean `origin/dev` checkout, because the local Terraform has no provider plugins installed (`terraform init` was not run). They are not from this PR.
- **Database tests** on this branch: `pytest tests/test_backfill_writer.py tests/test_migration_*.py tests/test_bdl_*.py tests/test_db.py` → 236 passed, 5 skipped. The skips are the live tests.
- **Fabrication scan:** PASS, checked by hand. Each test stores pages recorded in SPO-138a. A test that needs a bad row changes a copy of a recorded one.
- **Frontend:** not touched.

## Follow-ups

- [ ] SPO-138d: the walker that fetches pages and hands them to this writer.

## Progress notes (for the docs PR)

- SPO-138c: the backfill writer stores one BDL games or stats page and its checkpoint in one transaction, with upserts on natural keys.

---

**Ticket**: SPO-138c
**Branch**: `feature/SPO-138c-backfill-writer`
**Task summary**: `docs/task-summaries/SPO-138c-backfill-writer.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
