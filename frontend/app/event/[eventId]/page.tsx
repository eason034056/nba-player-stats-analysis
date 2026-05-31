/**
 * event/[eventId]/page.tsx — NBA Event Detail / No-Vig Calculator
 *
 * SPO-83 Phase 0: this page is now a thin wrapper. All layout + behavior lives
 * in the league-parametrized <EventDetail> shared component, which the WNBA
 * sister route (`app/wnba/event/[eventId]/page.tsx`) also renders. NBA is the
 * reference design — see docs/decisions/SPO-82/decision_20260531_wnba-parity-approach.md.
 */

"use client";

import { EventDetail } from "@/components/EventDetail";

export default function EventPage() {
  return <EventDetail league="nba" />;
}
