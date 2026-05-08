import type { ReactNode } from "react";
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EventList } from "@/components/EventList";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("EventList", () => {
  it("preserves the selected date in event detail links", () => {
    renderWithProviders(
      <EventList
        {...({
          events: [
            {
              event_id: "evt-1",
              sport_key: "basketball_nba",
              home_team: "Los Angeles Lakers",
              away_team: "Golden State Warriors",
              commence_time: "2026-03-17T01:00:00Z",
            },
          ],
          selectedDate: "2026-03-16",
        } as React.ComponentProps<typeof EventList>)}
      />,
    );

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/event/evt-1?date=2026-03-16",
    );
  });
});
