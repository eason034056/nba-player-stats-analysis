# Decision — remove the LangGraph, lineup RAG, and finetune trees

- **Ticket:** SPO-142b
- **Date:** 2026-11-21
- **Status:** Accepted

## Context

SPO-142a (#110, `5b65b58`) removed `POST /api/nba/agent/chat` and `POST /api/wnba/agent/chat`. It moved `open_close_from_snapshots` to `backend/app/services/snapshot_open_close.py` and left a re-export in `scripts/agents/evaluation/odds_history.py` so the walk-forward package could still import the same names.

On current `origin/dev` (that tip, which also contains #109 / `b5da8c5`) the following were still present:

- `scripts/agents/` (45 files), including `evaluation/fit_combined_platt.py` and `tests/fixtures/odds_api_*_head500.json`
- `nba_lineup_rag/` (40 files)
- `scripts/finetune/` (9 files)
- `scripts/dataset/` (4 files)
- `data/train.jsonl`, `data/train_full.jsonl`, `data/train_questions.jsonl`, `data/train_contexts.jsonl`, `data/eval.jsonl`, `data/test.jsonl`

The backend test suite does not import those trees, except `backend/tests/test_spo131_bdl_injuries.py`, which put `nba_lineup_rag` on `sys.path` and imported `NBA_TEAMS` from `src.config`. The same 30 abbreviations are the keys of `app.services.lineup_source_support.TEAM_ALIASES`.

## Decision

Delete the four trees and the six JSONL files listed above.

Keep, and do not move:

- `data/nba_player_game_logs.csv`
- `data/wnba_player_game_logs.csv`
- `data/star_players.json`
- `open_close_from_snapshots` in `backend/app/services/snapshot_open_close.py`
- `PLATT_A`, `PLATT_B`, and `FIT_SAMPLE` in `backend/app/services/pick_signal_constants.py`. The fitter is gone. The numbers stay at the last fit (NBA MED20, cutoff 2026-03-17, market prior 0.5).
- `docs/progress.md` (this PR does not edit it)
- The frontend Agent Widget and its tests
- The rest of `backend/app/services/`
- `backtest_report.md`. `docs/decisions/SPO-112/` and the historical task summaries still cite that checked-in report. The walk-forward command that wrote it is gone, and nothing else regenerates it.
- Root `.env` ignore, and the tracked files under `data/`. There is no root `data/` ignore. The `nba_lineup_rag/.env`, `nba_lineup_rag/data/`, RAG HTML/PDF, and `outputs/notebook_results_*.json` ignore lines existed only for that package and are removed. `.dockerignore` still excludes `data/*.jsonl` so a local file of that shape is not copied into the image.
- `openai` is dropped from `backend/requirements.txt`. Its only remaining importer was `scripts/dataset/03_generate_answers.py`.

`test_spo131_bdl_injuries.py` now compares the recorded standings abbreviations to `TEAM_ALIASES` only. It does not import the deleted package. `test_spo98_gaps.py` dropped `test_sample_context_team_is_latest_in_the_window`, which loaded `scripts/dataset/01_sample_contexts.py`. The roster checks in that class stay.

Historical files under `docs/task-summaries/`, older `docs/decisions/`, and `docs/research/` stay as records of the work they describe. `docs/dev-doc.md`, `docs/multi-agent-dev.md`, and `sample_outputs.md` keep their original bodies and gain a note that the paths are no longer entry points. `docs/new-function-dev-doc.md` and `env.example` do not name the removed trees.

## Consequences

There is no in-repo command that refits `PLATT_A` / `PLATT_B` or regenerates `backtest_report.md`. A later closing-line reader calls `app.services.snapshot_open_close`. The frontend chat widget is out of scope. SPO-138k is a separate branch and is not part of this change.
