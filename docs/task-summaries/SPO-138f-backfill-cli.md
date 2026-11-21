# SPO-138f — `python -m app.backfill`: NBA history 2000-01 to 2026-27 into Postgres

- **Ticket:** SPO-138f, the sixth of SPO-138a–g (the NBA history backfill, one layer per PR)
- **Branch:** `feature/SPO-138f-backfill-cli`
- **Base:** `dev`
- **Depends on:** SPO-138e (verify), merged into `dev`.

## Summary

This PR adds the command that walks seasons from resumable checkpoints and verifies each one before marking it `done`. It also records the result of running the command over all 27 seasons.

1. `python -m app.backfill 2000-2026 --dsn-env NBA_HISTORY_DATABASE_URL`, with `--dry-run`, `--restart-season`, and `--raw-dir`.
2. **The run.** All 27 seasons are loaded into a local Postgres: 34,650 games (33,659 final) and 885,873 stat lines (188,012 did-not-play), from 9,292 requests. No line was refused or dropped. Every past season is `done`; 2026-27 is reported.
3. `docs/decisions/SPO-138/backfill-plan.md`, the backfill plan. §B gives measured request counts for games and stats.

Nothing in the product reads these tables yet. RDS is not touched.

## Changes

| Area | Files | Change |
|---|---|---|
| Backfill | `backend/app/backfill/cli.py`, `__main__.py` | New. Season parsing, the run loop, the per-season report, exit codes |
| Tests | `backend/tests/test_backfill_cli.py` | New. The real client answered from recordings, on scratch databases |
| Docs | `docs/decisions/SPO-138/backfill-plan.md` | New. The backfill plan; §B measures games at 421 requests and stats at 8,871 |

## Why

- **Seasons are given as start years or ranges** (`2025` means 2025-26; `2000-2026`). A label such as `2000-01` is refused, and the error shows the form to use instead.
- **The current season is never marked done.** Its games are still being played, so it is walked from page one on every run and only reported. The season turns over on July 1.
- **`--restart-season` clears a season's checkpoints** so the season is walked again. Stored rows stay, because every write is an upsert.
- **A failed page stops the run, but a failed check does not.** A failed check is printed and the next season still runs. In either case the exit code is 1.
- **Secrets stay off the command line.** The DSN comes from the variable that `--dsn-env` names, and the key from `BALLDONTLIE_API_KEY`. Failures are printed with both masked.
- **Pace.** Requests are capped at 500 a minute in process. One walker sends one request at a time and reaches about 263 a minute, bound by latency. No request got a 429 in 14,788 requests over four runs. The games and stats walk takes about 35 minutes (`backfill-plan.md` §B).
- **`--dry-run` needs no database.** It reads every page of the given seasons from page one and prints what it read, including the lines the normalizer would refuse.
- **What the run found.** In 50 final games, BDL's lines do not add up to the game. Verify lists them without blocking `done`. SPO-138g decides what readers see.

## Tests / Verification

The test runs use a throwaway `postgres:16-alpine`, with `DATABASE_URL` set explicitly to it.

- **Full backend suite** on this branch: `cd backend && DATABASE_URL=<throwaway db> python -m pytest -q` → 6 failed, 1956 passed, 30 skipped, 7 xfailed. The 6 failures are Terraform console tests: 3 in `test_spo132b_optional_vpc.py::TestVpcIdConsole` and 3 in `test_spo140_terraform_environments.py::TestNamePrefixConsole`. They fail the same way on a clean `origin/dev` checkout, because the local Terraform has no provider plugins installed (`terraform init` was not run). They are not from this PR.
- **Database tests** on this branch: `pytest tests/test_backfill_*.py tests/test_migration_*.py tests/test_bdl_*.py tests/test_db.py` → 292 passed, 5 skipped. The skips are the live tests.
- **The run, local `nba_history` (postgres:16), 2026-11-17 and 18:**
  - every past season `done`, 2026-27 reported;
  - 0 refused, 0 dropped;
  - verify takes under 2 s for all 27 seasons;
  - a re-walk of 2014-15 to 2026-27 after the normalizer fixes sent 4,702 requests in 18 minutes.
- **Fabrication scan:** PASS, checked by hand. Every page the tests serve is a recording from SPO-138a.
- **Frontend:** not touched.

## Follow-ups

- [ ] SPO-138g: leave BDL's 50 broken games out of `player_game_log`.
- [ ] Upload `bdl-raw/` to the data bucket (Q2).
- [ ] Writers for opening props, opening odds, injuries, and lineups (`backfill-plan.md` §B estimates their requests).

## Progress notes (for the docs PR)

- SPO-138f: NBA history from 2000-01 to 2026-27 is loaded from BDL into the new schema on a local Postgres by `python -m app.backfill`, with each season verified (34,650 games, 885,873 stat lines). RDS is not migrated yet.

---

**Ticket**: SPO-138f
**Branch**: `feature/SPO-138f-backfill-cli`
**Task summary**: `docs/task-summaries/SPO-138f-backfill-cli.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
