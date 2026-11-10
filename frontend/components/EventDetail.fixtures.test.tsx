import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EventDetail } from "@/components/EventDetail";
import {
  dailyPicksResponseSchema,
  eventsResponseSchema,
  noVigResponseSchema,
  playerHistoryResponseSchema,
  playerProjectionSchema,
  playerSuggestResponseSchema,
  teamLineupSchema,
} from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import nbaEventsFixture from "@/test/fixtures/event/nba-events.json";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import nbaSuggestFixture from "@/test/fixtures/event/nba-suggest.json";
import nbaHistoryFixture from "@/test/fixtures/event/nba-history-bam.json";
import nbaLineupFixture from "@/test/fixtures/event/nba-lineup-mixed.json";
import nbaBosLineupFixture from "@/test/fixtures/event/nba-lineup-bos.json";
import nbaNoVigFixture from "@/test/fixtures/event/nba-no-vig-bam.json";
import nbaProjectionFixture from "@/test/fixtures/event/nba-projection-bam.json";
import wnbaEventsFixture from "@/test/fixtures/event/wnba-events.json";
import wnbaPicksFixture from "@/test/fixtures/event/wnba-daily-picks.json";
import wnbaSuggestFixture from "@/test/fixtures/event/wnba-suggest.json";
import wnbaHistoryFixture from "@/test/fixtures/event/wnba-history-wilson.json";
import wnbaLvaLineupFixture from "@/test/fixtures/event/wnba-lineup-lva.json";
import wnbaNylLineupFixture from "@/test/fixtures/event/wnba-lineup-nyl.json";
import wnbaNoVigFixture from "@/test/fixtures/event/wnba-no-vig-wilson.json";

const nbaEvents = eventsResponseSchema.parse(nbaEventsFixture);
const nbaPicks = dailyPicksResponseSchema.parse(nbaPicksFixture);
const nbaSuggest = playerSuggestResponseSchema.parse(nbaSuggestFixture);
const nbaHistory = playerHistoryResponseSchema.parse(nbaHistoryFixture);
const nbaLineup = teamLineupSchema.parse(nbaLineupFixture);
const nbaBosLineup = teamLineupSchema.parse(nbaBosLineupFixture);
const nbaNoVig = noVigResponseSchema.parse(nbaNoVigFixture);
const nbaProjection = playerProjectionSchema.parse(nbaProjectionFixture);
const wnbaEvents = eventsResponseSchema.parse(wnbaEventsFixture);
const wnbaPicks = dailyPicksResponseSchema.parse(wnbaPicksFixture);
const wnbaSuggest = playerSuggestResponseSchema.parse(wnbaSuggestFixture);
const wnbaHistory = playerHistoryResponseSchema.parse(wnbaHistoryFixture);
const wnbaLvaLineup = teamLineupSchema.parse(wnbaLvaLineupFixture);
const wnbaNylLineup = teamLineupSchema.parse(wnbaNylLineupFixture);
const wnbaNoVig = noVigResponseSchema.parse(wnbaNoVigFixture);

const nav = vi.hoisted(() => ({
  eventId: "evt-mia-bos",
  player: "Bam Adebayo",
  path: "/event/evt-mia-bos",
}));

const apiMocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
  getWNBAEvents: vi.fn(),
  getDailyPicks: vi.fn(),
  getWnbaDailyPicks: vi.fn(),
  getPlayerSuggestions: vi.fn(),
  getWNBAPlayerSuggestions: vi.fn(),
  getTeamLineup: vi.fn(),
  getWNBATeamLineup: vi.fn(),
  getPlayerProjection: vi.fn(),
  calculateNoVig: vi.fn(),
  calculateWNBANoVig: vi.fn(),
  getPlayerHistory: vi.fn(),
  getWNBAPlayerHistory: vi.fn(),
  getCSVPlayers: vi.fn(),
  getWNBACSVPlayers: vi.fn(),
  getPlayerDDHistory: vi.fn(),
  getWNBAPlayerDDHistory: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ eventId: nav.eventId }),
  usePathname: () => nav.path,
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => ({
    get: (key: string) => {
      if (key === "date") return "2026-11-10";
      if (key === "player") return nav.player;
      if (key === "market") return "player_points";
      return null;
    },
  }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...apiMocks };
});

describe("EventDetail fixtures", () => {
  beforeEach(() => {
    for (const fn of Object.values(apiMocks)) fn.mockReset();
    nav.eventId = "evt-mia-bos";
    nav.player = "Bam Adebayo";
    nav.path = "/event/evt-mia-bos";
    apiMocks.getEvents.mockResolvedValue(nbaEvents);
    apiMocks.getWNBAEvents.mockResolvedValue(wnbaEvents);
    apiMocks.getDailyPicks.mockResolvedValue(nbaPicks);
    apiMocks.getWnbaDailyPicks.mockResolvedValue(wnbaPicks);
    apiMocks.getPlayerSuggestions.mockResolvedValue(nbaSuggest);
    apiMocks.getWNBAPlayerSuggestions.mockResolvedValue(wnbaSuggest);
    apiMocks.getTeamLineup.mockImplementation(async (team: string) =>
      team === "BOS" ? nbaBosLineup : nbaLineup,
    );
    apiMocks.getWNBATeamLineup.mockImplementation(async (team: string) =>
      team === "NYL" ? wnbaNylLineup : wnbaLvaLineup,
    );
    apiMocks.getPlayerProjection.mockResolvedValue(nbaProjection);
    apiMocks.calculateNoVig.mockResolvedValue(nbaNoVig);
    apiMocks.calculateWNBANoVig.mockResolvedValue(wnbaNoVig);
    apiMocks.getPlayerHistory.mockResolvedValue(nbaHistory);
    apiMocks.getWNBAPlayerHistory.mockResolvedValue(wnbaHistory);
    apiMocks.getCSVPlayers.mockResolvedValue({ players: [], total: 0 });
    apiMocks.getWNBACSVPlayers.mockResolvedValue({ players: [], total: 0 });
    apiMocks.getPlayerDDHistory.mockResolvedValue({
      player: "Bam Adebayo",
      n_games: 0,
      dd_games: 0,
      prob_dd: null,
    });
    apiMocks.getWNBAPlayerDDHistory.mockResolvedValue({
      player: "A'ja Wilson",
      n_games: 0,
      dd_games: 0,
      prob_dd: null,
    });
  });

  it("reads the NBA game from the fixture payloads and opens the agent", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EventDetail league="nba" />, { withAgentWidget: true });

    expect(
      await screen.findByRole("heading", { name: /boston celtics @ miami heat/i }),
    ).toBeInTheDocument();
    expect(await screen.findByText("BOS lineup confirmed")).toBeInTheDocument();
    expect(screen.getByText("MIA lineup projected")).toBeInTheDocument();
    expect(screen.getByText("Strong play")).toBeInTheDocument();
    expect(screen.getByText("O 72.0%")).toBeInTheDocument();
    expect(screen.getAllByText("No read").length).toBeGreaterThan(0);
    expect(screen.queryByText(/supports|neutral|against/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ask the board/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Ask the agent" }));
    expect(screen.getByRole("button", { name: "Close betting agent" })).toBeInTheDocument();
  });

  it("reads the WNBA game from the WNBA fixtures", async () => {
    nav.eventId = "evt-lva-nyl";
    nav.player = "A'ja Wilson";
    nav.path = "/wnba/event/evt-lva-nyl";
    renderWithProviders(<EventDetail league="wnba" />, { withAgentWidget: true });

    expect(
      await screen.findByRole("heading", { name: /new york liberty @ las vegas aces/i }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Projection is not available for WNBA.")).toBeInTheDocument();
    expect(screen.getByText("Playable")).toBeInTheDocument();
    expect(await screen.findByText("LVA lineup confirmed")).toBeInTheDocument();
    expect(screen.getByText("NYL lineup projected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ask the board/i })).not.toBeInTheDocument();
    expect(apiMocks.getWNBAEvents).toHaveBeenCalled();
    expect(apiMocks.getPlayerProjection).not.toHaveBeenCalled();
  });
});
