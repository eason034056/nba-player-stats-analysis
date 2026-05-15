# SPO-37 — WNBA Phase 6: independent betslip context + navbar/about polish

## Summary

Closes the loop on the WNBA experience. Adds a fully independent WNBA bet
slip (`WnbaBetSlipContext`), the `/wnba/betslip` page, a path-based
league-aware Navbar (title + bet-slip badge auto-switch), an About page
update that mentions WNBA, and right-click add-to-slip on `/wnba/picks` that
writes only to the WNBA slip.

With SPO-37 merged, all seven WNBA-rollout phases (SPO-31 → SPO-37) are done.

## Changes

| Layer | File | Purpose |
| ----- | ---- | ------- |
| Context | `frontend/contexts/WnbaBetSlipContext.tsx` (new) | Independent WNBA slip state. Separate `localStorage` key (`wnba_betslip_picks`). Reuses NBA's `BetSlipPick` *type* but never shares state. |
| Provider wiring | `frontend/app/providers.tsx` | Mount `WnbaBetSlipProvider` as a sibling of `BetSlipProvider`. Both are visible to the whole tree so the Navbar (and any consumer) can read both counts. |
| Page | `frontend/app/wnba/betslip/page.tsx` (new) | Sister of `/betslip/page.tsx`. Reads `useWnbaBetSlip`. Same remove / clearAll / share-image / clipboard / Web Share flow. Header labelled "WNBA". `View Details` links thread `league: "wnba"` into `buildEventDetailHref`. |
| Navbar | `frontend/components/Navbar.tsx` | New `isWnbaPath` helper. Calls both `useBetSlip` + `useWnbaBetSlip` unconditionally (React hook rules) and selects which count + which bet-slip link to render based on path. Title swaps to **No-Vig WNBA** under `/wnba/*`. |
| Add-to-slip | `frontend/components/PickContextMenu.tsx` | New `league?: "nba" \| "wnba"` prop (defaults to `"nba"` → NBA call sites unchanged). When `"wnba"`, the menu writes through `useWnbaBetSlip` and navigates "View Details" to `/wnba/event/<id>`. |
| WNBA picks | `frontend/app/wnba/picks/page.tsx` | Wraps each `PickCard` in `<PickContextMenu pick={pick} league="wnba">`. This is the surface the manual verification exercises. |
| About | `frontend/app/about/page.tsx` | New "NBA + WNBA Coverage" section with links to `/picks`, `/betslip`, `/wnba/picks`, `/wnba/betslip`. Hero copy now references WNBA. |

Two new files, six edits. No backend changes.

## Why

SPO-29 architectural guardrail (verbatim): "Two contexts, fully independent.
Do not try to be clever and put them in one store with a league discriminator
— owner has explicitly chosen full separation."

The whole point of Phase 6 is that adding a WNBA leg can never affect the
NBA slip (and vice versa). Implementation choices that enforce that:

- **Separate `localStorage` keys** (`betslip_picks` vs `wnba_betslip_picks`).
  A single key keyed by league would put us one off-by-one discriminator bug
  away from cross-contamination. Two keys = the compiler/runtime can't
  confuse them.
- **Separate React Context objects.** `useBetSlip` throws if called outside
  `BetSlipProvider`; `useWnbaBetSlip` throws if called outside
  `WnbaBetSlipProvider`. The error messages name their providers so a
  developer who accidentally consumes the wrong one gets a precise hint.
- **Navbar holds the only path-based league decision.** Per SPO-29:
  "Path-based active league inference is in the Navbar layer. Do not put
  league state in a root provider." That guarantee survives because the
  contexts themselves are league-blind — they just hold a list of picks.

Why `PickContextMenu` takes a `league` prop instead of two separate menu
components: the menu UI is identical across leagues — what differs is which
store it writes to and which event route "View Details" navigates to. A
`league` prop keeps the visual component single-source while still routing
state to two independent stores.

## Independence verification (manual)

> **Browser smoke is Sentinel's gate**, but the structural guarantee can be
> read off the code without running it:

| Action | Reads | Writes | Confirms |
| ------ | ----- | ------ | -------- |
| Right-click on a card on `/picks` → "Add to Bet Slip" | `useBetSlip` | `useBetSlip.addPick` → `localStorage["betslip_picks"]` | NBA-only |
| Right-click on a card on `/wnba/picks` → "Add to Bet Slip" | `useWnbaBetSlip` | `useWnbaBetSlip.addPick` → `localStorage["wnba_betslip_picks"]` | WNBA-only |
| Navbar badge under `/picks` | `nbaCount` | — | shows NBA count only |
| Navbar badge under `/wnba/picks` | `wnbaCount` | — | shows WNBA count only |
| Navbar title under `/wnba/*` | `isWnbaPath(pathname)` | — | "No-Vig WNBA" |
| Navbar title elsewhere | `isWnbaPath(pathname)` | — | "No-Vig NBA" |
| `/wnba/betslip` clearAll | `useWnbaBetSlip.clearAll` | only `localStorage["wnba_betslip_picks"]` | clears WNBA-only |

Recommended Sentinel smoke (Playwright):

1. Visit `/picks`, right-click a pick → "Add to Bet Slip". Confirm Navbar
   badge shows **1** with title "No-Vig NBA".
2. Visit `/wnba/picks`, right-click a pick → "Add to Bet Slip". Confirm
   Navbar badge changes to **1** (the WNBA count) and title to "No-Vig WNBA".
3. Visit `/betslip` directly — confirm exactly one pick listed (the NBA
   one), title "No-Vig NBA".
4. Visit `/wnba/betslip` — confirm exactly one pick listed (the WNBA one),
   title "No-Vig WNBA", header reads "My WNBA selections".
5. On `/wnba/betslip`, click "Clear All" → confirm `/betslip` still has the
   NBA pick (untouched).

## Tests

- `npx tsc --noEmit` — **clean** (full diff compiles).
- `npx next build` — produces same SSG prerender failures as `origin/dev`
  (`<Html> should not be imported outside of pages/_document` on `/`,
  `/picks`, `/about`, `/betslip`, `/wnba`, `/wnba/picks`, `/wnba/betslip`,
  `/404`, `/500`). **Pre-existing infra issue on `origin/dev` — verified
  by reproducing on a clean checkout — not introduced by this PR.** See
  memory `sentinel_preexisting_failure_handling.md`.

## Out-of-scope follow-ups (intentional)

These are deliberately deferred so SPO-37 stays Phase 6-shaped:

1. **WNBA agent "Review My Slip" button.** The NBA betslip page has a
   `submitAction({ action: "review_slip" })` button hooked to
   `sendAgentChat` (NBA endpoint, hardcoded). Phase 5c shipped the WNBA
   chat endpoint, but the widget action layer still defaults to NBA. Adding
   league routing to the widget action layer is its own ticket — out of
   scope here.
2. **WNBA lineup badges on `/wnba/betslip`.** `getLineups` only knows
   `/api/nba/lineups`. A `getWnbaLineups` is a ~10-line follow-up but not
   in the SPO-37 scope.

Neither omission affects the independence guarantee, which is the actual
acceptance criterion for Phase 6.

## Acceptance criteria

- [x] `WnbaBetSlipContext` exists; structurally parallel to NBA but
  state-independent (separate context object + separate `localStorage` key).
- [x] `/wnba/betslip` renders and persists across navigation within the WNBA
  namespace (uses its own `localStorage["wnba_betslip_picks"]`).
- [x] Navbar shows correct badge + title for the current league (path-based).
- [x] About page mentions WNBA (new "NBA + WNBA Coverage" section + cross-links).
- [x] Manual NBA + WNBA betslip independence verified — structural guarantee
  documented above; Sentinel browser smoke recommended steps listed.
- [x] Task summary at `docs/task-summaries/SPO-37-wnba-betslip-polish.md`.

## Reference

- Parent: SPO-29 · Orchestrator: SPO-30 · Blocker (resolved): SPO-36
- NBA betslip context: `frontend/contexts/BetSlipContext.tsx` (read for
  structural mirror, not for state sharing).
- Readability post-fix precedent: SPO-26 in-slip card commit `665423b`.
- Memory `sentinel_browser_smoke_required.md` — Sentinel should run a
  Playwright smoke (steps above).
- Memory `sentinel_preexisting_failure_handling.md` — `next build` SSG
  prerender failures reproduce on `origin/dev` and are not blocking.
