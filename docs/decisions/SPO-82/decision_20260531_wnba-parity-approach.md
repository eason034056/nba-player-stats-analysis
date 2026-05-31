# Decision — WNBA→NBA analysis-page parity approach

- **Epic:** [SPO-82](/SPO/issues/SPO-82) — WNBA analysis pages parity (parent [SPO-81](/SPO/issues/SPO-81))
- **Date:** 2026-05-31
- **Author:** CTO
- **Status:** Accepted (drives Phase 0)

## Context

Owner reports WNBA analysis pages diverge visually/structurally from NBA. NBA is the
reference design. Grounding scan of `frontend/` (line counts as a divergence proxy) shows
the WNBA routes were forked from NBA and then simplified:

| Surface | NBA route | WNBA route | NBA LOC | WNBA LOC |
|---|---|---|---|---|
| Picks (core analysis page) | `app/picks/page.tsx` | `app/wnba/picks/page.tsx` | 1120 | 362 |
| Event detail | `app/event/[eventId]/page.tsx` | `app/wnba/event/[eventId]/page.tsx` | 418 | 293 |
| Home | `app/page.tsx` | `app/wnba/page.tsx` | 231 | 355 |
| Player detail | _(none)_ | `app/wnba/player/[name]/page.tsx` | — | 424 |

Two non-trivial choices are embedded in this epic.

## Decision 1 — Parametrize shared components by `league`, do not keep forking

**Chosen:** Extract the NBA page bodies into league-agnostic components that take a
`league: 'nba' | 'wnba'` prop (and route league-specific data through the typed API client
in `frontend/lib/api/`). Both the NBA root routes and `/wnba/*` routes render the same
components. WNBA-specific data gaps are handled inside the shared component, not by a fork.

**Alternatives considered:**
1. *Copy NBA JSX into the WNBA pages (fork-sync).* Rejected — reintroduces drift the moment
   either side changes; this is exactly how the current divergence happened.
2. *Server-side league abstraction only, keep two page trees.* Rejected — duplicated layout/
   styling still drifts; the complaint is visual/structural, which lives in the components.

**Tradeoffs:** Parametrizing is more upfront refactor and a wider blast radius (touches NBA
render path → regression risk). Mitigated by Sentinel QA proving no NBA regression and by
landing one vertical slice first (see Phase 0) before doing the large picks page.

## Decision 2 — Unsupported sections render a labeled empty state, not dropped

**Chosen:** Where a section exists in NBA but WNBA genuinely lacks the data (missing stat
category, no projection source, etc.), render a clearly-labeled "not available for WNBA"
empty/placeholder state in the same slot rather than removing the section.

**Rationale:** The epic's goal is structural parity — a user switching leagues should see the
same shape. Dropping sections recreates divergence. Empty states preserve layout parity and
make the data gap explicit instead of silent.

**Alternatives considered:**
1. *Drop unsupported sections entirely.* Rejected as the default — breaks structural parity,
   the exact thing we're fixing. Reserved only for cases where an empty state is nonsensical
   (Forge flags those back to CEO per the epic's escalation rule).
2. *Hide via feature flag per league.* Rejected for now — adds config surface; revisit only if
   the unsupported set is large.

**Escalation:** Forge follows the empty-state default. Genuinely ambiguous cases (e.g. a whole
section that makes no sense for WNBA) are surfaced to CEO in the task summary, not silently
decided.

## Open question (NOT decided here — for CEO)

WNBA has a `player/[name]` analysis page; NBA has **no** equivalent route. This is reverse
asymmetry: NBA is the reference, but the reference lacks this page. Options: (a) leave the
WNBA player page as additive and untouched, (b) port a matching player page to NBA in a later
phase, (c) treat it out of scope. **Default for Phase 0: leave it untouched and document it**;
ask CEO which direction they want before spending a phase on it.

## Impact

- Phase 0 (Forge): full delta audit of all NBA vs WNBA analysis surfaces **+** refactor the
  **event detail** page (smaller, pattern-setting slice) into a league-parametrized shared
  component. Establishes the reuse pattern and the empty-state convention for later phases.
- Later phases (created one at a time after each lands in `origin/dev`): picks page (largest),
  home page, player-page reconciliation pending CEO answer on the open question.
- No backend changes expected; data already flows via `frontend/lib/api/`.

## Links

- Epic: [SPO-82](/SPO/issues/SPO-82)
- Conventions: `/Users/wuyusen/Documents/bet/CLAUDE.md` (Next.js/TypeScript patterns)
