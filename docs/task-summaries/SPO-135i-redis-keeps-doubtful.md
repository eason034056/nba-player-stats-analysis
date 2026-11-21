# SPO-135i — The NBA injury cache keeps Doubtful

- **Ticket:** SPO-135i (provisional number; Paperclip was offline, so the ticket is not created yet)
- **Branch:** `feature/SPO-135i-redis-keeps-doubtful`
- **Base:** `dev`
- **Depends on:** nothing. Independent of SPO-138i (#98).
- **Supersedes:** SPO-135h's storage rule (`decision_20261111_doubtful-as-questionable.md`)

## Summary

`injuries:nba:latest` now stores BALLDONTLIE's Doubtful as `Doubtful` instead of `Questionable`. The product behaves as before: Doubtful keeps the Questionable blend, and only Out blocks. The card already showed the raw word.

Three agent readers compared statuses against a hard-coded list that had no Doubtful in it. Without a fix, a Doubtful teammate would read as healthy. They now call one helper in a new module, `app/services/injury_status.py`, which imports nothing.

## Changes

| Area | Files | Change |
|---|---|---|
| Cache | `backend/app/services/nba_injuries.py` | `doubtful` → `Doubtful`; docstrings |
| Shared words | `backend/app/services/injury_status.py` | New. `UNRESOLVED_INJURY_STATUSES`, `is_unresolved_injury`, `is_out_or_unresolved` |
| Agents | `scripts/agents/scoring.py`, `scripts/agents/tools/historical.py`, `backend/app/services/agent_chat.py` | Use the helper instead of literal lists. `scoring.py` puts `backend/` at the end of `sys.path` if it is missing |
| Comments | `nba.py`, `schemas.py` (API field description), `daily_analysis.py`, `event_reads.py`, `pick_signals.py`, `frontend/lib/injury-tag.ts` | Stop saying Doubtful is stored as Questionable |
| Tests | `test_spo135i_doubtful_kept.py` (new) and 11 updated SPO-131/135/137a files | New: status buckets, the availability signal, scorecard parity. Updated: the stored word is Doubtful; every assertion that the blend is unchanged is kept |
| Docs | `docs/decisions/SPO-135/decision_20261120_doubtful-kept.md` (new); supersede notes in two SPO-135 decisions | |

## Why

- **One word everywhere.** `injury_snapshots.status` (SPO-138 §1.7) stores BDL's word. The cache now agrees, and the model can tell Doubtful from Questionable.
- **The helper is the fix, not a cleanup.** `scoring.py` checked `status in ("Questionable", "Day-To-Day")`. A cached Doubtful would have skipped the unresolved-injury flag and the teammate adjustment.
- **`injury_status.py` imports nothing.** `scoring.py` also runs in the evaluation harness. Importing `nba_injuries` would pull in Redis and settings.
- **No key rename.** Each refresh rewrites the whole snapshot. A pre-deploy snapshot still says Questionable, which is today's behavior.

## Tests / Verification

- **Injury-related backend files** (SPO-130 through 137, `test_bdl_client.py`, `test_pick_signals.py`, `test_agent_chat*.py`, `test_role_conditioned_scoring.py`, `test_spo104_qa_review.py`, plus the new file): 571 passed, 9 skipped, 6 xfailed. The baseline before the change was 561 passed.
- **Mutation check:** with the literal lists put back in `scoring.py` and `historical.py`, `test_the_scorecard_treats_doubtful_like_questionable` and `test_a_doubtful_player_reads_as_caution` fail.
- **Full backend suite** (`DATABASE_URL=""`, so DB tests skip; this PR touches no SQL): 1752 passed, 126 skipped, 6 xfailed, 3 failed. The 3 failures are `test_spo132b_optional_vpc.py::TestVpcIdConsole`, the Terraform console tests, and they fail the same way on a clean `origin/dev` checkout.
- **Agents suite** (`scripts/agents/tests`): 114 passed, the same count as before the change.
- **Local setup notes:**
  - `fakeredis==2.26.2` (already in `backend/requirements.txt`) was missing from the local venv and was installed.
  - `nba_lineup_rag/src/config.py` calls a bare `load_dotenv()`. It walks up and loads the repo-root `.env`, whose `DATABASE_URL` is a remote host, so the conftest guard skipped every test until `DATABASE_URL` was set explicitly.
- **Frontend:** comment-only change in `injury-tag.ts`. No tests run.

## Follow-ups

- [ ] `nba_lineup_rag/src/config.py`: load its own `.env` by explicit path instead of a bare `load_dotenv()`, so pytest never picks up the root `.env` `DATABASE_URL`.
- [ ] The `injury_snapshots` writer stores the same word (SPO-138 §1.7).

## Progress notes (for the docs PR)

- SPO-135i: the NBA injury cache keeps Doubtful; agent readers share `injury_status.is_unresolved_injury`.
