/**
 * wnba/event/[eventId]/page.tsx — WNBA Event Detail / No-Vig Calculator
 *
 * SPO-83 Phase 0: WNBA→NBA analysis-page parity. This page is now a thin
 * wrapper over the league-parametrized <EventDetail> shared component — the
 * exact same component the NBA route renders — so the two pages can no longer
 * drift in structure or styling (the divergence this epic exists to fix).
 *
 * Sections WNBA genuinely lacks data for today (player projection, team
 * lineups) render a labeled "not available for WNBA" empty state inside
 * <EventDetail> rather than being dropped, preserving structural parity.
 * Player history IS available for WNBA (`getWNBAPlayerHistory`), so that
 * section is wired for real. See the decision log:
 * docs/decisions/SPO-82/decision_20260531_wnba-parity-approach.md.
 */

"use client";

import { EventDetail } from "@/components/EventDetail";

export default function WNBAEventPage() {
  return <EventDetail league="wnba" />;
}
