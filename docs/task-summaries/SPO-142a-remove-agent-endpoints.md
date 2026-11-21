# SPO-142a — Remove backend agent endpoints

- **Ticket:** SPO-142a
- **Branch:** `feature/SPO-142a-remove-agent-endpoints`
- **Base:** `dev` at `6d9fa0a` (includes #98–#105; #99 is already on `dev`)

## Summary

This PR removes the two agent chat routes and everything in the backend that exists only to serve them. `POST /api/nba/agent/chat` and `POST /api/wnba/agent/chat` are gone, along with the chat service, the chat models, and the router registration. Backend tests that import `scripts/agents` are deleted where they are coupled, not rewritten. `open_close_from_snapshots` now lives in the backend so a later closing-line reader can call it after the agent tree is gone. The `scripts/agents` tree itself stays. `fit_combined_platt.py` stays. `PLATT_A` and `PLATT_B` are unchanged.

## Changes

| Area | Files | Change |
|---|---|---|
| Routes | `backend/app/api/agent.py`, `backend/app/api/wnba_agent.py`, `backend/app/main.py` | Deleted both chat routers and their `include_router` lines |
| Chat stack | `backend/app/services/agent_chat.py`, `backend/app/models/agent_chat.py` | Deleted |
| Open/close | `backend/app/services/snapshot_open_close.py` | New. The old `evaluation.odds_history` module, including `open_close_from_snapshots` |
| Shim | `scripts/agents/evaluation/odds_history.py` | Re-exports the backend module so the walk-forward package still imports the same names while that tree remains |
| Pure chat tests | `test_agent_chat.py`, `test_agent_chat_wnba.py`, `test_agent_planner.py` | Deleted |
| Whole coupled files | `test_role_conditioned_scoring.py`, `test_lineup_player_context.py`, `test_spo131_qa3.py` | Deleted. Every case imported agent tools |
| Coupled cases, product cases kept | `test_spo98_gaps.py`, `test_spo98_team_and_names.py`, `test_spo104_qa_review.py`, `test_spo117_snapshot_writer.py`, `test_spo131_bdl_injuries.py`, `test_spo131_qa.py`, `test_spo131_qa2.py`, `test_spo135a_slate_date.py`, `test_spo135c_bdl_injury_status.py`, `test_spo135c_qa.py`, `test_spo135i_doubtful_kept.py` | Deleted only the cases that import `scripts/agents`. The two open/close checks now import `app.services.snapshot_open_close` |
| CI | `.github/workflows/ci.yml` | Removed the `walk-forward-guard` job and the `OPENAI_API_KEY` value on `backend-test` |
| Image | `backend/Dockerfile`, `.dockerignore`, `docker-compose.yml` | Stopped copying `scripts/agents`. Dropped the compose `OPENAI_API_KEY` line. The build context no longer un-ignores `scripts/` |
| Env example | `env.example` | Removed the Agent Chat `OPENAI_API_KEY` block |
| Dependencies | `backend/requirements.txt` | Removed `langgraph`, `langchain-openai`, and `langsmith`. Kept `openai`, `beautifulsoup4`, and `lxml`. Added a direct `requests==2.34.2` pin |

## Why

- The chat routes are the only backend callers of the LangGraph package. Production picks, lineups, injuries, and odds snapshots do not import it.
- `open_close_from_snapshots` is the reducer a later closing-line ticket needs. Leaving it under `scripts/agents` would delete it with that tree. The two QA checks that already lock its behavior (a null under is skipped; the Bovada ladder collapses to the main line) stay, and they import the backend copy.
- Coupled tests were deleted instead of pointed at a new module. A mixed test that called an agent tool was removed as a whole, including any product asserts in that same function. Product tests in the same files that never import `scripts/agents` stay. That includes the BDL injury cache, the page cap, and the Doubtful status buckets.
- Survey follow-up on `6d9fa0a`: after the inventory at `837f982`, #99 and the slate-date work added more imports. Those are `test_spo135a` (`test_agent_lineup_date_is_the_us_slate`), `test_spo135c` (`test_wnba_agent_injury_path_still_scrapes`), `test_spo135c_qa` (`test_picks_reads_and_nba_agent_tools_do_not_construct_bdl_client`), and `test_spo135i` (the scorecard case and the agent availability case). The status-bucket case in `test_spo135i` does not import the agent tree and stays.
- `openai` stays in `backend/requirements.txt` because `scripts/dataset/03_generate_answers.py` still imports it. `scripts/dataset` is not deleted in this PR. `nba_lineup_rag/.env.example` still documents `OPENAI_API_KEY` for that tree. The compose file and `env.example` block were labeled for Agent Chat and are the copies this PR removes.
- `requests` was not pinned. `lineup_provider_rotowire.py` and `lineup_provider_rotogrinders.py` import it, and a fresh install received it only through `langgraph` / `langchain-openai` (resolved `requests==2.34.2`). Removing those packages made `import requests` fail at collection. The pin is the version that tree resolved to.
- `beautifulsoup4` and `lxml` stay. `lineup_provider_rotowire.py` imports `bs4`.
- `PLATT_A` and `PLATT_B` are not edited. `scripts/agents/evaluation/fit_combined_platt.py` is not deleted.
- Frontend files are not edited. #64 was not touched.

## Tests / Verification

Python 3.11.18, `pip install -r backend/requirements.txt`. `langgraph` does not import in that environment. `DATABASE_URL` was set to a throwaway Postgres 16 on `127.0.0.1:5441` (not `5434`). Redis was local on port 6379. `ODDS_API_KEY` was a placeholder. `OPENAI_API_KEY` was unset.

- **Ruff** (`ruff==0.17.4`, `ruff check . --select E9,F63,F7,F82` in `backend/`): passed. `python -m compileall -q .` in `backend/` passed.
- **Backend pytest, tree present:** `1838 passed, 37 skipped, 6 xfailed` in 90.15s. Exit 0.
- **Backend pytest with `scripts/agents` moved aside, then moved back:** same counts, `1838 passed, 37 skipped, 6 xfailed` in 89.99s. Exit 0. `scripts/agents/graph.py` was confirmed present after the restore. This is the check that `backend-test` does not need that tree on disk.
- **Shim:** with the tree present, `evaluation.odds_history.open_close_from_snapshots` is the same function object as `app.services.snapshot_open_close.open_close_from_snapshots`.
- **Mutation, then restored:** feeding a missing under price through as `-110` failed `test_open_close_skips_a_null_under_without_raising` and left the ladder test passing. Returning the raw ladder from `_main_line_per_snapshot` failed `test_open_close_uses_the_main_line_not_the_bovada_ladder` and left the null-under test passing. The file was copied back and compared equal to the pre-mutation copy.
- **`TestVpcIdConsole`:** 3 skipped. `terraform` is not on PATH, and the class is `skipif` on that. They did not fail in this run.
- **Dependency search:** `langgraph`, `langchain_openai`, and `langsmith` are imported under `scripts/agents/` and `nba_lineup_rag/`, not under `backend/app/`. `from openai import OpenAI` remains in `scripts/dataset/03_generate_answers.py`. `from bs4 import BeautifulSoup` remains in `lineup_provider_rotowire.py`.
- **Integration:** SKIPPED (`RUN_INTEGRATION` unset).
- **Fabrication scan:** PASS. The kept open/close test reads Over/Under prices from the recorded `odds_api_event_odds__player_points.json`. No new hand-typed odds body.
- **Frontend:** not touched.
- **Docker build:** not run here. The daemon is not installed in this environment. The Dockerfile no longer has `COPY scripts/agents`.

## Follow-ups

- [ ] SPO-142b deletes `scripts/agents/`, `nba_lineup_rag/`, and the fine-tune trees. Move `fit_combined_platt.py` first if combined-probability constants should still be refit; this PR leaves the file where it is.
- [ ] Frontend chat UI stays out of this PR. The widget is already behind the flag from the later frontend work.
- [ ] Docs that still describe the chat routes (`README.md`, the repo context doc, `docs/deployment/vercel.md`) are unchanged here.
- [ ] #64 was left alone. If that branch is still open, its edits to `agent.py` / `wnba_agent.py` / `test_agent_chat.py` will not apply.

## Progress notes (for the docs PR)

- SPO-142a: removed `POST /api/nba/agent/chat` and `POST /api/wnba/agent/chat`, the chat service, and the backend tests that import `scripts/agents`. `open_close_from_snapshots` now lives in `backend/app/services/snapshot_open_close.py`. The `scripts/agents` tree is still in the repo. Backend pytest is `1838 passed, 37 skipped, 6 xfailed` with that tree moved aside.

---

**Ticket**: SPO-142a
**Branch**: `feature/SPO-142a-remove-agent-endpoints`
**Task summary**: `docs/task-summaries/SPO-142a-remove-agent-endpoints.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
