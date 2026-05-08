import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EventPage from "@/app/event/[eventId]/page";
import { renderWithProviders } from "@/test/test-utils";

const navigationMocks = vi.hoisted(() => ({
  useParams: vi.fn(),
  usePathname: vi.fn(),
  useRouter: vi.fn(),
  useSearchParams: vi.fn(),
}));

const apiMocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
  calculateNoVig: vi.fn(),
  getPlayerProjection: vi.fn(),
  getTeamLineup: vi.fn(),
}));

vi.mock("next/navigation", () => navigationMocks);
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getEvents: apiMocks.getEvents,
    calculateNoVig: apiMocks.calculateNoVig,
    getPlayerProjection: apiMocks.getPlayerProjection,
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

vi.mock("@/components/MarketSelect", () => ({
  MarketSelect: () => <div>market select</div>,
}));

vi.mock("@/components/ResultsTable", () => ({
  ResultsTable: () => <div>results table</div>,
}));

vi.mock("@/components/PlayerHistoryStats", () => ({
  PlayerHistoryStats: () => <div>player history stats</div>,
}));

vi.mock("@/components/PlayerProjectionPanel", () => ({
  PlayerProjectionPanel: () => <div>player projection panel</div>,
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

    apiMocks.getEvents.mockResolvedValue({
      date: "2026-03-16",
      events: [
        {
          event_id: "evt-1",
          sport_key: "basketball_nba",
          home_team: "Los Angeles Lakers",
          away_team: "Golden State Warriors",
          commence_time: "2026-03-17T01:00:00Z",
        },
      ],
    });
    apiMocks.getTeamLineup.mockResolvedValue(null);
    apiMocks.getPlayerProjection.mockResolvedValue(null);
    apiMocks.calculateNoVig.mockResolvedValue(null);
  });

  it("uses the route date when fetching events for the detail page", async () => {
    renderWithProviders(<EventPage />);

    expect(
      await screen.findByRole("heading", { name: /golden state warriors/i }),
    ).toBeInTheDocument();
    expect(apiMocks.getEvents).toHaveBeenCalledWith("2026-03-16");
    expect(
      screen.queryByText(/game information not found/i),
    ).not.toBeInTheDocument();
  });
});
