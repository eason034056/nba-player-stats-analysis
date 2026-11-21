# SPO-142b — Remove agent, lineup RAG, and finetune trees

- **Ticket:** SPO-142b
- **Branch:** `feature/SPO-142b-remove-agent-trees`
- **Base:** `dev` at `5b65b58` (includes #109 `b5da8c5` and #110 `5b65b58`)

## Summary

This PR deletes the LangGraph package, the lineup RAG package, the finetune notebooks, and the dataset scripts. SPO-142a already removed the chat HTTP routes and moved `open_close_from_snapshots` into the backend. The six training and eval JSONL files under `data/` were still on `origin/dev` and are deleted. Game-log CSVs, `star_players.json`, the backend services, the frontend Agent Widget, and `docs/progress.md` stay. `backtest_report.md` stays because the SPO-112 decision and two task summaries still cite it.

## Changes

| Area | Files | Change |
|---|---|---|
| Agent tree | `scripts/agents/` (45 files) | Deleted, including `evaluation/fit_combined_platt.py` and `tests/fixtures/odds_api_*_head500.json` |
| Lineup RAG | `nba_lineup_rag/` (40 files) | Deleted |
| Finetune | `scripts/finetune/` (9 files) | Deleted |
| Dataset | `scripts/dataset/` (4 files) | Deleted |
| Training JSONL | `data/train.jsonl`, `data/train_full.jsonl`, `data/train_questions.jsonl`, `data/train_contexts.jsonl`, `data/eval.jsonl`, `data/test.jsonl` | All six were present on current `origin/dev`. Deleted. No other files under `data/` were removed |
| Injury test | `backend/tests/test_spo131_bdl_injuries.py` | Stopped importing `NBA_TEAMS` from `nba_lineup_rag`. Standings codes are compared to `TEAM_ALIASES` |
| Sampler test | `backend/tests/test_spo98_gaps.py` | Dropped `test_sample_context_team_is_latest_in_the_window`, which loaded `scripts/dataset/01_sample_contexts.py`. The roster checks in that class stay |
| Platt constants | `backend/app/services/pick_signal_constants.py` | Docstring only. `PLATT_A`, `PLATT_B`, and `FIT_SAMPLE` are unchanged |
| Open/close | `backend/app/services/snapshot_open_close.py` | Docstring only. The function stays where SPO-142a put it |
| Injury words | `backend/app/services/injury_status.py` | Docstring only |
| Dependencies | `backend/requirements.txt` | Removed `openai`. Its only remaining importer was `scripts/dataset/03_generate_answers.py` |
| Ignore rules | `.gitignore`, `.dockerignore` | Dropped ignore lines that existed only for `nba_lineup_rag/`. Root `.env` stays ignored. `data/` is not ignored. `data/*.jsonl` stays out of the image |
| Current docs | repo-root context document, `README.md`, `docs/deployment/vercel.md` | Point at the trees that remain, and say the chat routes and the four trees are gone |
| Historical specs | `docs/dev-doc.md`, `docs/multi-agent-dev.md`, `sample_outputs.md` | Short note at the top. Bodies kept |
| Decision | `docs/decisions/SPO-142/decision_20261121_remove-agent-trees.md` | New |
| Not edited | `docs/progress.md`, `frontend/`, `env.example`, `docs/new-function-dev-doc.md`, `backtest_report.md`, `docs/task-summaries/` other than this file | `env.example` and `docs/new-function-dev-doc.md` do not name the removed trees. `docs/progress.md` still does; this PR does not change it |

## Why

- The chat routes were the backend callers of the LangGraph package. Production picks, lineups, injuries, and odds snapshots do not import it. Leaving the trees on disk kept a second copy of `open_close_from_snapshots` and a test import of `nba_lineup_rag`.
- `open_close_from_snapshots` already lives in `backend/app/services/snapshot_open_close.py`. This PR does not move it again and does not change the function.
- `PLATT_A` and `PLATT_B` stay at the last fit. The fitter is deleted with `scripts/agents/`, as this ticket requires. There is no in-repo command that refits them.
- The sampler test was deleted instead of pointed at a new module. The product roster checks in the same class do not load the dataset script and stay.
- `backtest_report.md` is still named by `docs/decisions/SPO-112/decision_20261110_signal-verdicts-combined-probability.md`, `docs/task-summaries/SPO-107-harness-gametype-parity.md`, and `docs/task-summaries/SPO-112-signal-verdicts.md`. Deleting the report would leave those citations with nothing to open. The walk-forward CLI that wrote it is gone.
- Root `.env` is still the local secrets file. A root `data/` ignore would hide the tracked CSVs. The RAG-only patterns (`nba_lineup_rag/.env`, `nba_lineup_rag/data/`, the RAG HTML/PDF, `outputs/notebook_results_*.json`) do not match anything else in the repo.
- Historical task summaries, older decisions, and research notes are left as records. Rewriting them would make past tickets look like they never touched those paths.
- Frontend files are not edited. SPO-138k is not started. The SPO-138j follow-ups are not touched.

## Tests / Verification

Python 3.11.18. `pip install -r backend/requirements.txt` (51 packages; `openai` is not in the set). Postgres 16.15 on `127.0.0.1:5441` (not `5434`). Redis on `127.0.0.1:6379`. `ODDS_API_KEY` was a placeholder. `OPENAI_API_KEY` and `BALLDONTLIE_API_KEY` were unset.

`DATABASE_URL` was set explicitly to a local Postgres URL of the form `postgresql://<user>:<password>@127.0.0.1:5441/<db>`.

```bash
cd backend
DATABASE_URL='postgresql://<user>:<password>@127.0.0.1:5441/<db>' \
REDIS_URL='redis://127.0.0.1:6379' \
ODDS_API_KEY='<placeholder>' \
pytest --tb=line -q
```

- **Ruff** (`ruff==0.17.4`, `ruff check . --select E9,F63,F7,F82` in `backend/`): passed. `python -m compileall -q .` in `backend/` passed.
- **Backend pytest:** `1873 passed, 37 skipped, 6 xfailed` in 92.82s. Exit 0. A second run after the VPC check was `1873 passed, 37 skipped, 6 xfailed` in 92.27s.
- **`TestVpcIdConsole`:** 3 skipped. Reason: `terraform is not on PATH`. They did not fail in this run. The class is `skipif` when `terraform` is missing.
- **Integration:** SKIPPED (`RUN_INTEGRATION` unset). Those cases are inside the 37 skips.
- **Docker build:** not run. The daemon is not installed in this environment. The Dockerfile still copies `backend/` and `data/`. It does not copy `scripts/agents`.
- **Frontend:** not touched.

## Follow-ups

- [ ] `docs/progress.md` still names `scripts/agents/` and `nba_lineup_rag/`. This PR does not edit it. The progress note below is for the docs PR.
- [ ] The frontend Agent Widget remains. The chat routes it used to call are already gone.
- [ ] `PLATT_A` and `PLATT_B` have no refit command in the repo.
- [ ] SPO-138k is a separate branch and was not started here.

## Progress notes (for the docs PR)

- SPO-142b: removed `scripts/agents/`, `nba_lineup_rag/`, `scripts/finetune/`, `scripts/dataset/`, and the six training JSONL files under `data/`. Kept the game-log CSVs, `star_players.json`, `open_close_from_snapshots` in `backend/app/services/snapshot_open_close.py`, and the fitted Platt pair. Backend pytest is `1873 passed, 37 skipped, 6 xfailed`.

---

**Ticket**: SPO-142b
**Branch**: `feature/SPO-142b-remove-agent-trees`
**Task summary**: `docs/task-summaries/SPO-142b-remove-agent-trees.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
