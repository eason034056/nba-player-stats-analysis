import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EventDetail } from "@/components/EventDetail";
import type { NoVigResponse } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";

const navigationMocks = vi.hoisted(() => ({
  market: "player_threes",
}));

const apiMocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
  calculateNoVig: vi.fn(),
  getPlayerProjection: vi.fn(),
  getTeamLineup: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ eventId: "evt-1" }),
  usePathname: () => "/event/evt-1",
  useRouter: () => ({ back: vi.fn() }),
  useSearchParams: () => ({
    get: (key: string) => {
      if (key === "date") return "2026-03-16";
      if (key === "player") return "Nikola Jokic";
      if (key === "market") return navigationMocks.market;
      return null;
    },
  }),
}));

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
  TeamLogo: () => <span>logo</span>,
}));

vi.mock("@/components/PlayerInput", () => ({
  PlayerInput: () => <input aria-label="player input" />,
}));

vi.mock("@/components/BookmakerSelect", () => ({
  BookmakerSelect: () => <div>bookmaker select</div>,
}));

vi.mock("@/components/PlayerHistoryStats", () => ({
  PlayerHistoryStats: () => <div>player history stats</div>,
}));

vi.mock("@/components/TeamLineupPanel", () => ({
  TeamLineupPanel: () => <div>team lineup panel</div>,
}));

const projection = {
  player_name: "Nikola Jokic",
  team: "DEN",
  opponent: "LAL",
  points: 29.3,
  rebounds: 12.4,
  assists: 8.1,
  pra: 49.8,
  three_pointers_made: 1.2,
  steals: 1.4,
  free_throws_made: 5.5,
  field_goals_made: 11,
  r_a: 20.5,
  p_r: 41.7,
  p_a: 37.4,
};

function quote(market: string, line: number, extra: Record<string, unknown> = {}): NoVigResponse {
  return {
    event_id: "evt-1",
    player_name: "Nikola Jokic",
    market,
    results: [
      {
        bookmaker: "draftkings",
        line,
        over_odds: -110,
        under_odds: -110,
        p_over_imp: 0.52,
        p_under_imp: 0.52,
        vig: 0.04,
        p_over_fair: 0.5,
        p_under_fair: 0.5,
        fetched_at: "2026-05-08T12:00:00Z",
        ...extra,
      },
    ],
    consensus: { method: "mean", p_over_fair: 0.5, p_under_fair: 0.5 },
    message: null,
    fetched_at: "2026-05-08T12:00:00Z",
    data_age_seconds: 12,
  };
}

describe("EventDetail projection highlight", () => {
  beforeEach(() => {
    navigationMocks.market = "player_threes";
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
    apiMocks.getPlayerProjection.mockResolvedValue(projection);
    apiMocks.calculateNoVig.mockResolvedValue(quote("player_threes", 2.5, {
      line_is_synthetic: false,
      market_kind: "over_under",
    }));
  });

  it("highlights 3PM on its own card and does not edge a double-double against 0.5", async () => {
    const { unmount } = renderWithProviders(<EventDetail league="nba" />);

    expect(await screen.findByTestId("proj-card-threes")).toHaveAttribute(
      "data-highlighted",
      "true",
    );
    expect(screen.getByTestId("proj-card-points")).toHaveAttribute(
      "data-highlighted",
      "false",
    );
    expect(await screen.findByText(/Edge vs Line \(3PM/)).toBeInTheDocument();
    expect(screen.queryByText(/Edge vs Line \(Points/)).not.toBeInTheDocument();
    unmount();

    navigationMocks.market = "player_double_double";
    apiMocks.calculateNoVig.mockResolvedValue(
      quote("player_double_double", 0.5, {
        line_is_synthetic: true,
        market_kind: "binary",
        yes_price: -150,
        no_price: null,
        under_odds: null,
        p_under_imp: null,
        yes_fair_prob: 0.6,
        no_fair_prob: 0.4,
      }),
    );

    renderWithProviders(<EventDetail league="nba" />);
    expect(await screen.findByText("Yes/No")).toBeInTheDocument();
    expect(await screen.findByTestId("proj-card-points")).toHaveAttribute(
      "data-highlighted",
      "false",
    );
    expect(screen.getByTestId("proj-card-pra")).toHaveAttribute(
      "data-highlighted",
      "false",
    );
    expect(screen.queryByText(/Edge vs Line/)).not.toBeInTheDocument();
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
  });
});
