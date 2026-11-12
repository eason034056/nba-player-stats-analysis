# SPO-135h — NBA Doubtful counts as Questionable

- Ticket: SPO-135h
- Branch: `feature/SPO-135h-doubtful-as-questionable`
- Base: `dev`
- Stacks on PR #79, which stacks on #77, #72, and #69. After those squash-merge, `git merge origin/dev` on this branch.

## Summary

NBA treats a BALLDONTLIE Doubtful the same as Questionable. The cache still stores `status="Questionable"` and `raw_status="Doubtful"`. Daily picks and `/reads` keep `combined_probability`. The filtered board keeps the row when that number clears the floor and drops it when it does not. `injury_status` on the pick stays `"Questionable"`.

Out still nulls the blend on picks and on `/reads`, and Out still stays on the board with a null blend. `best_top_reads` still skips only Out.

WNBA is unchanged. A literal Doubtful word still leaves `injury_status` and `combined_probability` null, the board still uses the historical rate, and there is still no WNBA reads route.

## Why

For NBA, Doubtful keeps its combined probability and stays on the board. The stack through #79 did the opposite: `injury_blocks_combined` treated the source word like Out, so the blend was null and the filter dropped the row with the other null blends. Only top read already ignored Doubtful.

## Changes

| Area | What changed |
|---|---|
| Blend | `injury_blocks_combined` blocks only on Out. A literal Doubtful word keeps a number |
| Picks and `/reads` | They no longer pass `raw_status` into the signal builder. The snapshot still stores it |
| Board | A cache Doubtful is kept or dropped on the blend, the same as Questionable. Out still stays with a null blend |
| Agent | Unchanged. The tool still returns the cache row, including `raw_status`. The scorer still reads `status`, which is already Questionable |
| WNBA | Unchanged |
| Docs | `docs/decisions/SPO-135/decision_20261111_doubtful-as-questionable.md`. The earlier Doubtful notes in SPO-131, SPO-135c, SPO-135e, and SPO-135g point here |

## Blast radius

`injury_blocks_combined` callers:

| Caller | NBA | WNBA |
|---|---|---|
| `combined_probability` / `build_nba_signals` | Doubtful keeps a number. Out still returns null | Does not call this module |
| `select_daily_picks` | Out still stays with a null blend. A cache Doubtful follows the blend floor | The WNBA branch does not call the blocker. The board still uses the historical rate |

`raw_status` readers:

| Reader | NBA | WNBA |
|---|---|---|
| `normalize_bdl_injuries` | Still writes the source word. The cache shape is unchanged | WNBA does not use this cache |
| Daily picks and `/reads` | No longer read it for the blend | They never did |
| `scripts/agents/tools/historical.py` | Still returns the cache row, so `raw_status` is still on the agent payload. Scoring uses `status` | Scrape rows have no `raw_status`. A literal Doubtful is still outside the Out / Questionable / Day-To-Day sets |

`injury_status` readers:

| Reader | NBA | WNBA |
|---|---|---|
| Daily picks | Still the normalized word. A cache Doubtful is still `"Questionable"`. The blend for that word is no longer null | Still null. Analysis still ignores the snapshot |
| `/reads` | Out still nulls the blend. Doubtful now keeps a number | No reads route |
| `best_top_reads` | Still skips only normalized Out. Doubtful is not skipped | Does not load the snapshot |
| `scripts/agents/scoring.py` and `agent_chat.py` | Still read the normalized `status` / chemistry `injury_status`. A stored Doubtful is already Questionable, so the agent output does not change | A literal Doubtful is still not Out, Questionable, or Day-To-Day |
| `lineup_provider_rotowire.py` | Not this snapshot | WNBA lineup scrape. Unchanged |

## Tests / Verification

Recorded fixtures only. No live BALLDONTLIE or Odds API call. The odds capture is `odds_api_event_odds__player_points.json` (event `07361a8381206817e27bd2697fad7479`). Only two descriptions change: Matisse Thybulle becomes Jaylon Tyson, Walker Kessler becomes Dominick Barlow. The injury page is the recorded `player_injuries` page. One recorded Questionable row, Jaylon Tyson, is set to Doubtful. Dominick Barlow stays the recorded Out row. The refresh uses a mocked transport and writes `injuries:nba:latest` in Redis. The second page is empty so the walk stops. Postgres is not running. The reads query is stubbed with the relabeled capture.

`cd backend && python -m pytest tests -q --tb=line`

1415 passed, 33 skipped, 6 xfailed, 0 failed.

Redis check, trimmed. Jaylon stays on the board with a number and `injury_status` Questionable. Barlow stays on the board with a null blend. Dyson, who is not on the injury page, keeps a number and a null status. `top_read` is Jaylon, because Barlow is Out and is skipped.

```
SEEDED {"Dominick Barlow": {"raw_status": "Out", "status": "Out"}, "Jaylon Tyson": {"raw_status": "Doubtful", "status": "Questionable"}}
points_picks:
  Dyson Daniels    injury_status=null          combined_probability=0.743  over 10.5
  Jaylon Tyson     injury_status=Questionable  combined_probability=0.7022 over 6.5
  Dominick Barlow  injury_status=Out           combined_probability=null   under 14.5
reads:
  Dominick Barlow  combined_probability=null
  Dyson Daniels    combined_probability=0.743
  Jaylon Tyson     combined_probability=0.7022
top_read: Jaylon Tyson player_points over 6.5 probability 0.8485
detail top_read: same
```

## Follow-ups

- [ ] A same-slate Odds API capture paired with a same-slate BALLDONTLIE injury page. That needs live calls and waits on the key upgrade.
