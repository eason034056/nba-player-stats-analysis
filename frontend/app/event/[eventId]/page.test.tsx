import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EventPage from "@/app/event/[eventId]/page";
import { eventsResponseSchema } from "@/lib/schemas";
import routeEventsFixture from "@/test/fixtures/event/nba-events-route-date.json";
import { renderWithProviders } from "@/test/test-utils";

const routeEvents = eventsResponseSchema.parse(routeEventsFixture);

const navigationMocks = vi.hoisted(() => ({
  useParams: vi.fn(),
  usePathname: vi.fn(),
  useRouter: vi.fn(),
  useSearchParams: vi.fn(),
}));

const apiMocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
  calculateNoVig: vi.fn(),
  getTeamLineup: vi.fn(),
}));

vi.mock("next/navigation", () => navigationMocks);
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getEvents: apiMocks.getEvents,
    calculateNoVig: apiMocks.calculateNoVig,
    getTeamLineup: apiMocks.getTeamLineup,
  };
});

vi.mock("@/components/TeamLogo", () => ({
  TeamLogo: ({ teamName }: { teamName: string }) => <span>{teamName}</span>,
}));

vi.mock("@/components/PlayerInput", () => ({
  PlayerInput: () => <input aria-label="player input" />,
}));

vi.mock("@/components/BookmakerSelect", () => ({
  BookmakerSelect: () => <div>bookmaker select</div>,
}));

vi.mock("@/components/MarketSelect", async () => {
  const actual = await vi.importActual<typeof import("@/components/MarketSelect")>(
    "@/components/MarketSelect",
  );
  return {
    ...actual,
    MarketSelect: () => <div>market select</div>,
  };
});

vi.mock("@/components/ResultsTable", () => ({
  ResultsTable: () => <div>results table</div>,
}));

vi.mock("@/components/PlayerHistoryStats", () => ({
  PlayerHistoryStats: () => <div>player history stats</div>,
}));

vi.mock("@/components/TeamLineupPanel", () => ({
  TeamLineupPanel: () => <div>team lineup panel</div>,
}));

describe("EventPage", () => {
  beforeEach(() => {
    navigationMocks.useParams.mockReturnValue({ eventId: "evt-1" });
    navigationMocks.usePathname.mockReturnValue("/event/evt-1");
    navigationMocks.useRouter.mockReturnValue({ back: vi.fn() });
    navigationMocks.useSearchParams.mockReturnValue({
      get: (key: string) => {
        if (key === "date") {
          return "2026-03-16";
        }

        return null;
      },
    });

    apiMocks.getEvents.mockResolvedValue(routeEvents);
    apiMocks.getTeamLineup.mockResolvedValue(null);
    apiMocks.calculateNoVig.mockResolvedValue(null);
  });

  it("uses the route date when fetching events for the detail page", async () => {
    renderWithProviders(<EventPage />);

    expect(
      (await screen.findAllByRole("heading", { name: /warriors @ lakers/i })).length,
    ).toBeGreaterThan(0);
    expect(apiMocks.getEvents).toHaveBeenCalledWith("2026-03-16");
    expect(
      screen.queryByText(/game information not found/i),
    ).not.toBeInTheDocument();
  });
});
