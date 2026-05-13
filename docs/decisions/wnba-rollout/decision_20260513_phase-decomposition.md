# Decision: WNBA rollout phase decomposition (SPO-29 → SPO-30 orchestration)

- **Date:** 2026-05-13
- **Epic:** wnba-rollout
- **Author:** CTO
- **Tickets:** [SPO-29](/SPO/issues/SPO-29) (epic, CEO-owned) · [SPO-30](/SPO/issues/SPO-30) (orchestrator, CTO)
- **Status:** Active

## Chosen path — pre-decompose all 7 phases with `blockedByIssueIds` chains

Create seven sibling phase tickets under [SPO-29](/SPO/issues/SPO-29) in one batch:

| Phase | Title | Initial assignee | Start state | Blocker chain |
|---|---|---|---|---|
| 0 | Odds API WNBA market verification | Scout | `todo` | _(none — scope-gate)_ |
| 1 | WNBA CSV service + read-only stats page | Forge | `todo` | _(none — parallel with 0)_ |
| 2 | WNBA odds + no-vig | Forge | `blocked` | Phase 0 |
| 3 | WNBA daily picks (incl. DB schema audit) | Forge | `blocked` | Phase 2 |
| 4 | WNBA lineup ingestion (RotoWire + RotoGrinders) | Scout → Forge | `blocked` | Phase 0 _(Scout pipeline serialization)_ |
| 5 | WNBA agent (LangGraph league-awareness) | Forge | `blocked` | Phase 1 + Phase 2 + Phase 4 |
| 6 | WNBA betslip + navbar/about polish | Forge | `blocked` | Phase 5 |

Each child of [SPO-29](/SPO/issues/SPO-29) (sibling of SPO-30), goal `912a09d6-a527-4408-8e2c-bf4acda64ea3`, with task-aware description that quotes the relevant SPO-29 phase block verbatim.

## Alternatives considered

### Alt A — Create Phase 0 only, gate-out remaining (default CTO policy)

My AGENTS.md says: _"Do **NOT** decompose an epic into all phases up front. Create Phase 0 only. Stop."_

- **Pros:** Matches default cadence; if Phase 0 fails (no WNBA props on Odds API), nothing else needs cancelling. Conservative owner pacing.
- **Cons:** Loses the explicitly-parallel Phase 0 + Phase 1 wedge (~1.5 days). Defeats CEO's stated automation goal: _"Apply `blockedByIssueIds` so dependent phases auto-wake."_ Owner has already approved the full decomposition in SPO-29 — re-asking permission per phase is owner-pacing overhead they explicitly waived.

### Alt B — Create Phase 0 + Phase 1 only, then dynamically add per close

- **Pros:** Captures parallel wedge while still gating Phase 2-6.
- **Cons:** Phase close events do not auto-wake CTO unless I put myself in a blocker chain (semantic abuse — orchestrator isn't blocked by individual phases). I'd have to either set up explicit comment-mention hand-offs or rely on Forge/Sentinel reassigning back to me, both of which add coordination overhead. CEO explicitly chose the auto-wake-via-blocker pattern in SPO-30 — overriding that adds friction without owner benefit.

## Trade-offs

- **What I lose:** Strict one-phase-at-a-time visibility on the board. Five extra tickets exist immediately in `blocked` status. If Gate 1 fires (Phase 0 finds no WNBA props), I have to cancel Phases 2/3/5 (Phase 1 still ships standalone read-only stats, Phase 4 lineup still ships standalone, Phase 6 collapses with 5).
- **What I gain:** Auto-wake on phase close fires Forge/Scout directly via `issue_blockers_resolved` — zero CTO heartbeat overhead per phase boundary. Phase ordering is encoded in the dependency graph and survives misclicks. Phase 0 + 1 + (Scout queued on 4) maximises the day-1 parallel wedge.
- **Reversibility:** Cancellation cost is O(5 tickets × ~30 s API patch) = negligible. Pre-creation is cheap to undo.

## Impact

- **Owner-visible:** seven `SPO-31…SPO-37` rows appear on the board immediately. `docs/progress.md` Phase-tickets-in-flight section grows to 7 rows (5 `blocked`, 2 `todo`).
- **Agent dispatch:** Scout wakes on Phase 0 (`issue_assigned`). Forge wakes on Phase 1 (`issue_assigned`). After Phase 0 closes: Forge wakes on Phase 2 (`issue_blockers_resolved`) AND Scout wakes on Phase 4 (`issue_blockers_resolved`). Cascade continues automatically.
- **Anti-hallucination policy:** Phase 0 (curl-evidence Odds API verification) and Phase 4 (sample-HTML pull from RotoWire/RotoGrinders) are research-first per `CLAUDE.md § External API Wrappers`. Both have Scout as initial assignee, both require committed `scripts/explore_*` artifacts.
- **Escalation gates** (per [SPO-30](/SPO/issues/SPO-30) mandate, owned by CEO):
  1. Phase 0 returns "no WNBA player props" → CTO cancels Phase 2/3/5; reassigns SPO-29 to CEO `in_review` with scope-change proposal.
  2. Phase 3 DB audit requires destructive migration → Phase 3 goes `blocked`; CTO comments SPO-29.
  3. Phase 5 NBA regression test fails → Phase 5 goes `blocked`; CTO comments SPO-29.
  4. Any phase blows estimate >50% → CTO flags in `docs/progress.md` + comments SPO-29.

## Why this deviates from default CTO phase-gating

Default CTO policy ("one phase at a time, create Phase 0 only") exists to prevent two failure modes:

1. **Premature decomposition before the plan is owner-validated.** Not the case here — SPO-29 has a v3-equivalent owner-approved decomposition with explicit phase boundaries, dependency edges, and time estimates baked in. The plan went through CEO triage; owner already chose Option B scope and accepted parallel `/wnba/*` routing.
2. **Owner pacing — the user (Eason) is learning and bulk dispatch breaks cadence.** Not the case here either: owner explicitly asked for the auto-wake-via-blocker pattern in the SPO-30 mandate ("Apply `blockedByIssueIds` so dependent phases auto-wake"), so they have already accepted the cadence implications.

Pre-decomposition is the right call **when and only when** both (1) plan is owner-approved and (2) owner has explicitly requested it. Both conditions are met. Returning to default Phase-0-only would amount to ignoring an explicit instruction.

## Links

- Parent plan: [SPO-29](/SPO/issues/SPO-29) (Owner Eason)
- Orchestrator: [SPO-30](/SPO/issues/SPO-30) (this CTO)
- Routing: `CLAUDE.md § Agent Routing Table`
- Anti-hallucination policy: `CLAUDE.md § External API Wrappers`
