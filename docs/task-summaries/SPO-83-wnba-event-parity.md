# SPO-83 — WNBA event-detail parity + league-param pattern + full audit

**Phase 0 of [SPO-82](/SPO/issues/SPO-82)** (WNBA→NBA analysis-page parity). NBA is the reference design.
Decision log: `docs/decisions/SPO-82/decision_20260531_wnba-parity-approach.md`.

## Summary

Killed the NBA/WNBA event-detail fork. Extracted the NBA event-detail body into a single
league-parametrized shared component `<EventDetail league="nba" | "wnba">`; both
`app/event/[eventId]` and `app/wnba/event/[eventId]` are now thin wrappers over it. This
establishes the reuse pattern + empty-state convention that later phases (picks, home) follow.
Also delivered the **full delta audit of all four analysis surfaces** (below) to scope those phases.

## Changes

| File | Change |
|---|---|
| `frontend/components/EventDetail.tsx` | **New.** Single event-detail layout. Per-league `LEAGUE_CONFIG` (endpoints, labels, cache namespace) + two capability flags (`supportsLineup`, `supportsProjection`) for genuine WNBA data gaps. |
| `frontend/components/SectionUnavailable.tsx` | **New.** Reusable labeled "not available for WNBA" empty state. Establishes the Decision-2 convention so later phases reuse identical wording/styling instead of dropping sections. |
| `frontend/components/PlayerHistoryStats.tsx` | Added optional league-parametrized fetch-fn props (`getCSVPlayersFn` / `getPlayerHistoryFn` / `calculateNoVigFn`) + `cacheNamespace`, all **defaulted to the NBA functions** so existing NBA callers are behaviorally byte-identical. Query keys namespaced to stop NBA/WNBA cache collisions in one session. |
| `frontend/app/event/[eventId]/page.tsx` | Reduced to `<EventDetail league="nba" />` wrapper. |
| `frontend/app/wnba/event/[eventId]/page.tsx` | Reduced to `<EventDetail league="wnba" />` wrapper. |

## Why

The two pages were forked then drifted (NBA 418 LOC → WNBA 293, with lineup / projection /
history sections silently dropped). A shared component driven by a `league` prop makes drift
**structurally impossible** — there is exactly one layout. League differences live in data
(`LEAGUE_CONFIG`) and in two explicit capability flags, not in divergent JSX. (Decision 1.)

WNBA-genuine data gaps render a labeled empty state in the same slot rather than vanishing, so
a user switching leagues sees the same page shape and the gap is explicit, not silent. (Decision 2.)

## Full delta audit — all NBA vs WNBA analysis surfaces

Line counts are a divergence proxy; section deltas below are grounded in the source.

### 1. Event detail — `app/event/[eventId]` (418) vs `app/wnba/event/[eventId]` (293) — **FIXED THIS PHASE**

| Section | NBA (reference) | WNBA before | WNBA after (this PR) |
|---|---|---|---|
| Back link | "Back to Events" | "Back to WNBA" | "Back to WNBA" (label via config) |
| Event workspace + "How to read" | ✓ | ✓ (step 3 copy differs) | ✓ (step 3 copy via config) |
| **Lineup Status** (2× `TeamLineupPanel`) | ✓ | ✗ dropped | ✓ labeled empty state (no WNBA lineup endpoint) |
| MarketSelect / PlayerInput / BookmakerSelect | ✓ | ✓ | ✓ (PlayerInput routed to WNBA suggest + `wnba` cache ns) |
| Calculate button | wide centered, "…Probability" | full-width, "…No-Vig" | NBA style (reference) |
| Error card | ✓ | ✓ (variant) | NBA style (reference) |
| ResultsTable | always (with `isLoading`) | only when `result`, custom header | NBA style: always, with `isLoading` |
| **"What is No-Vig?" explainer** | ✓ | ✗ dropped | ✓ (league-agnostic, restored) |
| **PlayerProjectionPanel** | ✓ | ✗ dropped | ✓ labeled empty state (no WNBA projection endpoint) |
| **PlayerHistoryStats** | ✓ | ✗ dropped | ✓ **wired for real** via `getWNBAPlayerHistory` |

### 2. Picks / core analysis — `app/picks/page.tsx` (1120) vs `app/wnba/picks/page.tsx` (362) — *later phase*

Largest surface, largest delta. NBA-only sections absent from WNBA: **Review Board** + board-status
workflow, **`LineupStatusBadge`** per pick, **`PickContextMenu`** richness, **Ask Agent** widget entry,
**Filter by Team** + multi-filter panel. WNBA picks is a slimmed list ("Hi-prob picks", "Props scanned",
"Players", load-error state) without the review/board/lineup/agent layers. Deferred — this is the biggest
phase and is gated separately.

### 3. Home — `app/page.tsx` (231) vs `app/wnba/page.tsx` (355) — *later phase*

**Reverse asymmetry on size:** WNBA home is *larger*. Both share `DatePicker` + `EventList` + Refresh +
"Selected day". NBA home has a structured 3-step "How to read / Take your best reads further" explainer
(Step 1/2/3, "Choose a game", "Examine the player market", "Go to matchup"). WNBA home diverges in its
intro/hero composition. Net: home needs reconciliation but is not a simple "WNBA is missing sections"
case — flagging for per-section review when its phase opens.

### 4. Player detail — `app/wnba/player/[name]/page.tsx` (424) — **NBA has no equivalent (reverse asymmetry)**

Left untouched this phase per the decision log. See Open Question.

## Genuine WNBA data-shape gaps (documented, not silently dropped)

Grounded in `frontend/lib/api.ts`:
- **No WNBA projection endpoint** — only `getPlayerProjection` (NBA). → projection slot = empty state.
- **No WNBA lineup endpoint** — only `getTeamLineup` / `getLineups` (NBA). → lineup slot = empty state.
- **WNBA history DOES exist** (`getWNBAPlayerHistory`, `getWNBACSVPlayers`) → history wired for real, not empty-stated.

None of these empty states is nonsensical, so none is escalated to CEO (per Decision 2's escalation rule).

## Open question (flagged, NOT decided — for CEO via CTO)

NBA has **no** `player/[name]` page but WNBA does (`app/wnba/player/[name]/page.tsx`, 424 LOC). Reverse
asymmetry: the reference design lacks this page. Left untouched this phase. CTO is asking CEO whether to
(a) leave WNBA player page additive, (b) port a matching NBA player page in a later phase, or (c) treat it
out of scope. No code action taken.

## Tests / verification

- `npx tsc --noEmit` — **clean** (exit 0).
- Browser smoke (Playwright, events endpoint mocked): both routes render with **0 page errors / 0 hydration
  errors**; `currentEvent` resolves; the new lineup + projection empty-state branches exercise cleanly.
- Screenshots in `docs/task-summaries/SPO-83-screenshots/`: `before-wnba-event.png` (slim fork),
  `after-wnba-event.png` (parity, with both empty states), `after-nba-event.png` (reference, unchanged).
- **Pre-existing infra failure (NOT this change):** the jsdom page test `app/event/[eventId]/page.test.tsx`
  cannot start its vitest worker — `@csstools/css-calc` `ERR_REQUIRE_ESM`. This breaks on `origin/dev` too
  (every jsdom test does). Flagged for Sentinel; node-env tests are unaffected.

## Follow-ups

- Sentinel: full QA (`npm test` + `pytest` + fabrication scan) on this branch. Note the pre-existing jsdom
  infra failure above — reproduce on `origin/dev` before treating as a regression. A real-backend browser
  smoke would populate the lineup/projection panels (the mock returns `{}`, so panels show their own
  empty/error fallbacks here).
- Later phases (one at a time, gated by CTO after this lands in `origin/dev`): picks (#2 above, largest),
  home (#3, reconcile), player page pending CEO answer.
