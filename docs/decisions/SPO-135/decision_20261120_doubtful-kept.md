# Decision — The NBA injury cache keeps Doubtful

- **Ticket:** SPO-135i (provisional number; Paperclip was offline when this was written)
- **Date:** 2026-11-20
- **Status:** Accepted (Eason)

## Context

Since SPO-131, `normalize_bdl_injuries` stored BALLDONTLIE's Doubtful as `status="Questionable"` and kept the source word only on `raw_status`. SPO-135h then made the product treat Doubtful like Questionable: it keeps the blend, and only Out blocks.

SPO-138 decided that `injury_snapshots.status` stores BDL's word, with Doubtful kept (`docs/decisions/SPO-138/decision_20261120_read-layer-and-ml-inputs.md`, item 7). The player-props model's teammate-absence feature needs to tell Doubtful from Questionable. Eason asked for the Redis cache to store the same word, so the cache and the history table do not disagree.

## Decision

1. `doubtful`, in any case or spacing, is stored as `Doubtful` in `injuries:nba:latest`. The other cache rules do not change: blank and unknown words are still stored as Questionable, a leading "out" is Out, and Available is dropped.
2. Product behavior does not change.
   - Doubtful keeps the same `combined_probability` as a Questionable row, because `injury_blocks_combined` and `frontend/lib/picks-board.ts` block only on Out.
   - The card label does not change, because `frontend/lib/injury-tag.ts` already shows the raw word.
   - `DailyPick.injury_status` now reads Doubtful instead of Questionable for those rows.
3. The agents that compared statuses against an exact list now call one helper in `backend/app/services/injury_status.py`:
   - `is_unresolved_injury`: Doubtful, Questionable, or Day-To-Day.
   - `is_out_or_unresolved`: the same set plus Out.

   The callers are `scripts/agents/scoring.py`, `scripts/agents/tools/historical.py`, and `backend/app/services/agent_chat.py`. Without the helper, a Doubtful teammate would read as healthy in the scorecard.
4. `injury_status.py` imports nothing, so `scoring.py` can import it without Redis or settings. `scoring.py` puts `backend/` at the end of `sys.path` if it is missing, the same bootstrap `historical.py` uses.
5. The Redis key is not renamed. The next 30-minute refresh rewrites the whole snapshot. A snapshot written before deploy still says Questionable for those rows, which is today's behavior.

## Alternatives

- *Keep the merge and read `raw_status` where Doubtful matters.* Rejected. Two fields would carry the same fact, and the cache would disagree with `injury_snapshots.status`.
- *Leave the readers' lists alone.* Rejected. `scoring.py` would drop a Doubtful teammate from its unresolved-injury check, a silent change in agent verdicts.
- *Map Doubtful to Out.* Rejected. That changes the product, and SPO-135h chose to keep Doubtful on the board.

## Tradeoff

A reader that matches statuses exactly must use the helper, or it will miss Doubtful. `test_spo135i_doubtful_kept.py` covers the scorecard and the availability signal. With the old lists put back, both tests fail.
