# SPO-138d — Backfill walker and the raw page cache

- **Ticket:** SPO-138d, the fourth of SPO-138a–g (the NBA history backfill, one layer per PR)
- **Branch:** `feature/SPO-138d-backfill-walker`
- **Base:** `dev`
- **Depends on:** SPO-138c (writer), merged into `dev`.

## Summary

`walk_season` walks one season's BDL pages into the core tables through the SPO-138c writer, and keeps every raw page on disk. `preview_season` reads the same pages without a database. Nothing calls either yet; the command is SPO-138f.

## Changes

| Area | Files | Change |
|---|---|---|
| Backfill | `backend/app/backfill/walker.py` | New. `season_shards`, `walk_season`, `preview_season`, `iter_pages` |
| Backfill | `backend/app/backfill/raw_cache.py` | New. `RawCache`: each fetched page gzipped under `bdl-raw/` |
| Tests | `backend/tests/test_backfill_walker.py`, `backfill_support.py` | New. The real `BdlClient` answered from SPO-138a's recordings |
| Repo | `.gitignore` | `bdl-raw/` at any depth |

## Why

- **A season is five shards, walked in order:** games once per `season_type` (`regular`, `playoffs`, `playin`, `ist`), then stats. Stats go last because their rows need their games already stored.
- **Each shard starts where its checkpoint says.** That is page one when nothing is stored, the stored cursor otherwise, and no request at all once every page is stored.
- **A shard ends on a page with no `next_cursor`**, or on an empty page even when BDL still sends a cursor.
- **A failed page stops the run, and the rerun resumes there.** The shard is marked `error` with the message, outside the page's rolled-back transaction. Its cursor still names the failed page.
- **Every raw page is kept.**
  - A page is saved before it is written, so the page that broke a walk can still be read.
  - Files are named by the requested cursor, so a resumed walk rewrites the same file instead of adding one. Each file is written to a `.partial` name and then renamed into place.
  - Pages hold no key, because the key travels in a header.
  - The kept pages later let the audit of BDL's errors (SPO-138g) run over 885,873 lines without a single API call.
- **`preview_season` is the dry run.** It reads every page from page one and counts the stats lines the normalizer would refuse. It needs no DSN and writes no checkpoint. `iter_pages` is the paging loop shared by the walk and the preview.
- **Tests use the real client.** `tests/backfill_support.py` answers the real `BdlClient` from recordings routed by path, `season_type`, and cursor. A request with no recording fails the test.

## Tests / Verification

All runs use a throwaway `postgres:16-alpine`, with `DATABASE_URL` set explicitly to it.

- **Full backend suite** on this branch: `cd backend && DATABASE_URL=<throwaway db> python -m pytest -q` → 6 failed, 1911 passed, 30 skipped, 7 xfailed. The 6 failures are Terraform console tests: 3 in `test_spo132b_optional_vpc.py::TestVpcIdConsole` and 3 in `test_spo140_terraform_environments.py::TestNamePrefixConsole`. They fail the same way on a clean `origin/dev` checkout, because the local Terraform has no provider plugins installed (`terraform init` was not run). They are not from this PR.
- **Database tests** on this branch: `pytest tests/test_backfill_*.py tests/test_migration_*.py tests/test_bdl_*.py tests/test_db.py` → 247 passed, 5 skipped. The skips are the live tests.
- **Fabrication scan:** PASS, checked by hand. Every page a test serves is a recording from SPO-138a, or a changed copy of one.
- **Frontend:** not touched.

## Follow-ups

- [ ] SPO-138e: verify a walked season before its shards are marked `done`.
- [ ] Upload `bdl-raw/` to the data bucket (Q2). Raw pages stay local for now.

## Progress notes (for the docs PR)

- SPO-138d: the backfill walker resumes each season's five shards from their checkpoints, and every raw BDL page is kept gzipped under `bdl-raw/`.

---

**Ticket**: SPO-138d
**Branch**: `feature/SPO-138d-backfill-walker`
**Task summary**: `docs/task-summaries/SPO-138d-backfill-walker.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
