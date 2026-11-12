# Decision — NBA Doubtful counts as Questionable

- **Ticket:** SPO-135h
- **Date:** 2026-11-11
- **Status:** Accepted

## Context

The BALLDONTLIE cache stores Doubtful as `status="Questionable"` and keeps `raw_status="Doubtful"`. SPO-135c taught `injury_blocks_combined(status, raw_status)` to treat either word as Out. A cache Doubtful then had `combined_probability` null on daily picks and on NBA `/reads`, while `DailyPick.injury_status` stayed Questionable. `select_daily_picks` drops a null blend that is not Out, so that pick left the filtered board. Out stayed on the board with a null blend. `best_top_reads` already ignored Doubtful and skipped only Out.

WNBA injury words come from ESPN/CBS. A literal Doubtful there is not the cache's normalized Questionable. WNBA does not call `pick_signals`.

## Decision

1. For NBA, Doubtful is Questionable. A cache row (`status="Questionable"`, `raw_status="Doubtful"`) and a literal status word of Doubtful both keep `combined_probability`. The number is the same one a plain Questionable row gets from the same prices and the same history. `injury_status` on the pick stays `"Questionable"` for the cache row. Out still sets the blend to null on daily picks and on `/reads`.

2. The filtered board uses that number. The Doubtful pick stays when the blend clears the floor and leaves when it does not, the same as Questionable. Out still stays on the board with a null blend when the sample floor passes.

3. The rule lives in one place. `injury_blocks_combined` blocks only on Out, ignoring case and surrounding whitespace. Picks and `/reads` no longer pass `raw_status` into `build_nba_signals` or `combined_probability`. That argument is gone. `raw_status` stays on the Redis snapshot. The agent tool still returns the cache row, including `raw_status`. Response field names and nullability are unchanged.

4. WNBA is unchanged. Analysis still leaves `injury_status` and `combined_probability` null. The board still uses the historical rate. There is still no WNBA `/reads` route. A literal Doubtful word on a WNBA pick does not start a blend.

5. `best_top_reads` is unchanged. It still skips only a normalized status of Out.

## Alternatives

1. *Keep blocking Doubtful and teach the filter to see `raw_status`.* Rejected. Eason decided a Doubtful player stays on the board with a probability, the same as Questionable.
2. *Add `raw_status` to `DailyPick`.* Rejected. The board shows the normalized word. The source word stays on the snapshot for the agent payload and a later history table.
3. *Stop storing Doubtful as Questionable.* Rejected. The scorer's unresolved bucket is already Questionable / Day-To-Day. The cache shape stays.

## Tradeoff

A reader of the snapshot can still tell Doubtful from Questionable by `raw_status`. The pick, the reads payload, and the filtered board cannot. That is the decision: those surfaces treat them as the same status.
