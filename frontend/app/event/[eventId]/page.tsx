/**
 * event/[eventId]/page.tsx — NBA event detail.
 *
 * Thin wrapper. Layout and behavior live in <EventDetail>.
 */

"use client";

import { EventDetail } from "@/components/EventDetail";

export default function EventPage() {
  return <EventDetail />;
}
