# Decision — Read tier cutoffs for DailyPick

- **Ticket:** SPO-111
- **Date:** 2026-11-10
- **Status:** Accepted

## Context

The No-Vig redesign needs a tier on each stored NBA pick: Strong play, Playable, Lean, or null below Lean. The same number has to be the storage floor for candidates that the daily-picks query can ask for.

`readTier` exists on Frontend PR #39 in `frontend/lib/today-board.ts`. That branch is not on `dev` yet. The helper buckets a probability the API already computed: `strong` at >= 0.70, `playable` at >= 0.65, `lean` at >= 0.56, and `pass` below 0.56. The display labels are "Strong play", "Playable", "Lean only", and "Pass". The picks page on `dev` still paints two buckets inside the current board: `getProbabilityLevel` returns high at probability >= 0.70 and medium for the rest of the rows it renders. Those rows are themselves at or above 0.65, because that is what the API used to return.

## Decision

One table is the cutoff list. `read_tier` in `backend/app/services/daily_analysis.py` walks it from the top and stops at the first match.

| Tier | Rule |
|---|---|
| Strong play | probability >= 0.70 |
| Playable | probability >= 0.65 and < 0.70 |
| Lean | probability >= 0.56 and < 0.65 |
| null | probability < 0.56, probability missing, or probability not finite (`NaN`, `Infinity`) |

```python
READ_TIER_CUTOFFS = (
    ("Strong play", 0.70),
    ("Playable", 0.65),
    ("Lean", 0.56),
)
```

`LEAN_PROBABILITY_FLOOR` is the last cutoff in that tuple, so the storage floor and the Lean label cannot drift apart.

The 0.70, 0.65, and 0.56 cuts are the same numbers `readTier` uses (`strong` / `playable` / `lean`; below that is `pass`). The API `tier` strings are `"Strong play"`, `"Playable"`, and `"Lean"`. Below 0.56 the API sends null, which is the `pass` bucket on the frontend. The picks page on `dev` uses the same 0.70 and 0.65 splits.

`read_tier` returns null when the probability is not finite. `Infinity >= 0.70` is true in Python, so without that check `Infinity` would be labeled `"Strong play"`. Frontend `readTier` already returns null for non-finite values. The same check drops a non-finite probability or line out of `top_read` instead of letting `NaN` replace a real pick (`NaN <= x` is false). A pick whose metric is missing or not in the market map is also left off `top_read`, so the join does not emit an empty `market`.

A pick whose chosen side is at least 0.65 stays on the published board. The default NBA analysis stores a row that misses 0.65 when a side still clears 0.56. The query default remains 0.65, so that row appears only when the client asks for it.

## Why this and not a second copy of the numbers

A helper with the three floors written out as separate `if` statements would let the label and the storage floor diverge the first time one of them is edited. The tuple is the only list of names and floors. The label strings are the API values (`"Strong play"`, `"Playable"`, `"Lean"`).

## What this does not decide

SPO-112 can add signal verdicts and `combined_probability` on `DailyPick`. Those fields are not part of this tier. `tier` stays a function of the chosen side's historical probability only.

WNBA storage is unchanged. The shared `DailyPick` model will serialize `tier` when a WNBA pick is built, using this same table, and WNBA still does not store rows below 0.65.
