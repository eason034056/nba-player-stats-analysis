# SPO-20 — Frontend Phase 3: 12-tile selector + DD binary tile + FTM/FGM empty-state UX

**Status:** Implemented on `feature/SPO-20-frontend-stat-expansion`; awaiting Eason squash-merge into `dev`.
**Parent epic:** [SPO-10](/SPO/issues/SPO-10) — event-page-stat-expansion (Phase 3 — frontend implementation).
**Plan:** [SPO-11 plan v3](/SPO/issues/SPO-11#document-plan), revision `43a01f18-f724-430a-b352-b4e81d3ede5f`.
**Predecessors:** [SPO-16](/SPO/issues/SPO-16) (commit `0e11d14`) + [SPO-17](/SPO/issues/SPO-17) (commit `4f250b4`) + [SPO-18](/SPO/issues/SPO-18) (commit `5ff02e2`).
**Branch:** `feature/SPO-20-frontend-stat-expansion` from `origin/dev`.

---

## What shipped

Frontend-only. Backend untouched (`git diff --name-only origin/dev...HEAD | grep ^backend/` empty).

### `frontend/lib/schemas.ts`

- `HISTORY_METRICS` extended 4 → **12** (matches `csv_player_history.CONTINUOUS_METRIC_EXTRACTORS` plus `dd` for binary path).
- `playerProjectionSchema` gains `r_a`, `p_r`, `p_a` (matching SPO-17's `normalize_projection()`). **Intentionally no `dd` field** (decision §4 step 4 — DD has no Phase-1 ML projection).
- `METRIC_DISPLAY_NAMES` map gains entries for the 8 new metrics.

### `frontend/components/MarketSelect.tsx`

- 4 → **12** tiles, each carrying `group: "single" | "combo" | "binary"`.
- Vertical-stacked groups with English headers ("Single Stats" / "Combo" / "Binary"). Picked over tabs because cross-group comparison (PTS vs PRA vs DD) is the interaction we want to support.
- New helpers exported: `getMarketGroup(key)` and `isBinaryMarket(key)` so downstream dispatches on `group`, not on string-matched keys.
- Icons sourced from `lucide-react@^0.469.0` (`Crosshair`, `Hand`, `HandMetal`, `CircleDot`, `Sparkles`, `Combine`, `Layers`, `Award`) — verified to exist in installed package, not assumed.
- `aria-pressed` contract preserved on every tile.

### `frontend/components/PlayerHistoryStats.tsx`

- `marketToHistoryMetric` / `historyMetricToMarket` extended from 4 → 12 (round-trip for all new keys).
- `getProjectionValueForMetric` covers all 12 metrics; **DD intentionally returns `null`** (no Phase-1 projection).
- New helper `isBinaryHistoryMetric(metric)` centralizes DD dispatch.
- TanStack `getPlayerHistory` query is **disabled** when `metric === "dd"` — the `/player-history` endpoint speaks Over/Under only.
- `fetchOddsAndSetThreshold` early-returns for binary metrics (never fetches the `0.5` sentinel as a "threshold").
- The threshold input shows a "Not applicable (binary outcome)" placeholder when DD is selected — never a fake `point` value.
- Loading spinner suppressed on the binary path.

### `frontend/components/PlayerDDTile.tsx` (new)

DD outcome panel. Contract:
- **Yes price** (American odds) — formatted `+N` / `-N`, or `—` when null.
- **Yes implied probability** — vig-laden, derived from price.
- **Yes fair probability** — single-leg de-vigged, OR explicit `"vig prior unavailable" / "fair-prob withheld (not fabricated)"` when null.
- **Historical P(DD = 1)** — `prob_dd` from `csv_player_history.player_dd_history()` once exposed.
- **Edge bar** — historical P(DD=1) vs fair (or implied) Yes prob, color-coded.
- **Footer** — explicit "ML projection N/A — Phase 2" plus DD definition (≥2 of {PTS, REB, AST, STL, BLK} ≥ 10). Pending-data states surfaced in copy when fields are null (NOT zeros).

Anti-hallucination guards: never substitutes a number for null `yes_fair_prob`, never fabricates a `point`, never derives a Phase-1 ML projection from marginals.

### `frontend/components/ResultsTable.tsx`

When `results: []`, panel renders:
> **No bookmaker line right now**
> No bookmaker has posted `<market>` for this game. Historical and projection panels remain available below; the odds tile lights up automatically on the next snapshot fetch when inventory appears.

Crucially, no `point` value is rendered when bookmakers is empty — the empty-state card returns before reaching any line-rendering code. Addresses the FTM / FGM empty-inventory case explicitly.

### `frontend/app/event/[eventId]/page.tsx`

`projectionMetric` switch widened to all 12 markets. New metrics fall through to the closest single stat (`PlayerProjectionPanel` only highlights one of `{points, rebounds, assists, pra}`; widening that highlight set is intentional out-of-scope). The projection chart's reference line in `PlayerHistoryStats` still uses `getProjectionValueForMetric` for the new metrics, so the actual numeric projection is correct.

### `frontend/components/control-readability.test.tsx`

Two new test cases:
- `"renders the SPO-20 12-tile selector with Single/Combo/Binary groups"` — asserts 12 buttons, 3 group headers, binary group has exactly 1 tile.
- `"flags the DD binary tile as selected via aria-pressed when chosen"` — asserts active class + aria-pressed contract for the DD selection.

Pre-existing tests unchanged.

### `.gitignore` (incidental but mechanically inseparable)

Discovered during this work: root `.gitignore` line 27 (`lib/`, the Python eggs convention) was sweeping up the entire Next.js `frontend/lib/` directory. Result: `schemas.ts`, `api.ts`, `utils.ts`, `team-logos.ts`, `event-detail-link.ts`, `agent-chat.ts` had **never been tracked by git** despite being import targets for every tracked frontend component. Fix: append `!frontend/lib/` and `!frontend/lib/**` exceptions; backfill the working-tree contents into the initial commit on this branch. Without this fix, my SPO-20 schema changes would silently drop from the PR diff. **Eason should review the backfilled files for accuracy** — they are the current local working-tree contents that the frontend already runs against, so functionally nothing changes, but they have never been through code review.

---

## Acceptance criteria — verification

| Criterion | Status |
|---|---|
| `MarketSelect.tsx` has 12 entries with `group` field; renders three visual groups | ✅ asserted in `control-readability.test.tsx` |
| All 8 new market keys round-trip via mappings | ✅ inverse switches in `PlayerHistoryStats.tsx` |
| `getProjectionValueForMetric` handles all 12 metrics; DD returns null | ✅ explicit comment + null branch |
| DD selection renders binary tile shape (no O/U chart) | ✅ `isBinaryHistoryMetric` gates O/U render; DD tile renders instead |
| FTM / FGM tiles render historical + projection normally; odds panel shows "no bookmaker line" | ⚠ partial — empty-state UX wired, but historical query is blocked by backend gap (§Backend gap below) |
| No hardcoded `point` fallback values (grep test) | ✅ |
| `lib/schemas.ts` has 12 `HISTORY_METRICS` entries + `r_a, p_r, p_a` projection fields (NOT `dd`) | ✅ |
| `control-readability.test.tsx` extended for 12-tile + Binary group | ✅ 2 new cases, all 39 tests pass |
| No backend code touched | ✅ |

`npm test` 39/39 pass. `npx tsc --noEmit` clean. `npm run lint` clean.

---

## Backend gap — escalated to CTO (recommend SPO-22 follow-up)

While SPO-16 expanded `csv_player_history.CONTINUOUS_METRIC_EXTRACTORS` and added `csv_player_history.player_dd_history()`, **the public API surface was not updated to match**:

1. **`backend/app/api/nba.py:659`** — `valid_metrics = ["points", "assists", "rebounds", "pra"]` is hardcoded. Any request with `metric=threes_made / steals / ftm / fgm / ra / pr / pa / dd` returns `400 Invalid metric`. Blocks 8 of 12 frontend tiles from receiving historical data.
2. **No `/player-dd-history` endpoint exists.** `csv_player_history.player_dd_history()` is reachable from service code but has no FastAPI route.
3. **`/props/no-vig` does not surface DD outcomes.** The endpoint's parser only recognizes `Over`/`Under`; DD's Yes/No outcomes get silently filtered (`results: []`). DD odds are ingested into `odds_line_snapshots` by SPO-16's `_parse_binary_market` but no API endpoint reads them back out.

**Why missed:** SPO-16's tests cover snapshot/persistence and `csv_player_history.player_dd_history()` in isolation, but no test exercises `/player-history` or `/props/no-vig` HTTP routes with new metric keys. Backend "expanded to 12 markets" is true at the service layer; API surface is still 4-markets-and-Over/Under-only.

**Impact on this PR:** the 8 new tiles render the empty-state UI when clicked — historical data shows "Load Failed" via existing error UX, no-vig shows "No bookmaker line right now". This is functionally OK to ship today (no fabricated data, no crashes), but it is not the experience SPO-20 §5 anticipates. Recommend SPO-22 follow-up: expand `valid_metrics`, add `/player-dd-history` route, add binary-aware path in `/props/no-vig` (or new `/props/dd`), one curl-verified integration test per route.

---

## Trade-offs

1. **Vertical-stacked groups vs tabs.** Picked stacked. More vertical real estate, but cross-group comparison (PTS vs PRA vs DD) is the point.
2. **DD as separate component (`PlayerDDTile.tsx`).** Keeps `PlayerHistoryStats` focused on Over/Under flow; DD's contract is its own surface.
3. **`PlayerProjectionPanel` highlight set NOT widened.** Out of scope; new metrics fall through to closest single stat.
4. **Empty-state copy is English-only.** No i18n layer in repo; punted per issue §6.
5. **Gitignore fix bundled.** Mechanically inseparable from making my schema changes survive the round-trip to `origin/dev`. Called out explicitly in the PR description.

---

## How to verify locally

```bash
git checkout feature/SPO-20-frontend-stat-expansion
cd frontend
npm test          # → 39 passed
npx tsc --noEmit  # → clean
npm run lint      # → clean
npm run dev       # → /event/<id>, click each of the 12 tiles
```

For the original 4 markets, user-facing flow unchanged. For the 8 new markets, expect graceful empty-states until the SPO-22 backend gap is closed.
