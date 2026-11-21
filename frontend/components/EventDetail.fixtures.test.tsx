import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EventDetail } from "@/components/EventDetail";
import { AGENT_CHAT_UI_ENABLED } from "@/lib/agent-chat-ui";
import { formatPercent } from "@/lib/player-dd";
import {
  csvPlayersResponseSchema,
  dailyPicksResponseSchema,
  eventsResponseSchema,
  noVigResponseSchema,
  playerDDHistoryResponseSchema,
  playerHistoryResponseSchema,
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
import emptyCsvFixture from "@/test/fixtures/event/csv-players-empty.json";
import nbaDdEmptyFixture from "@/test/fixtures/event/nba-dd-history-empty.json";
import ddOneSidedFixture from "@/test/fixtures/event/nba-no-vig-dd-one-sided.json";
import halfHistoryFixture from "@/test/fixtures/event/nba-history-half-percent.json";
import emptyPicksFixture from "@/test/fixtures/event/nba-daily-picks-empty.json";
import emptySuggestFixture from "@/test/fixtures/event/nba-suggest-empty.json";
import emptyHistoryFixture from "@/test/fixtures/event/nba-history-empty.json";
import emptyNoVigFixture from "@/test/fixtures/event/nba-no-vig-empty.json";

const nbaEvents = eventsResponseSchema.parse(nbaEventsFixture);
const nbaPicks = dailyPicksResponseSchema.parse(nbaPicksFixture);
const nbaSuggest = playerSuggestResponseSchema.parse(nbaSuggestFixture);
const nbaHistory = playerHistoryResponseSchema.parse(nbaHistoryFixture);
const nbaLineup = teamLineupSchema.parse(nbaLineupFixture);
const nbaBosLineup = teamLineupSchema.parse(nbaBosLineupFixture);
const nbaNoVig = noVigResponseSchema.parse(nbaNoVigFixture);
const emptyCsv = csvPlayersResponseSchema.parse(emptyCsvFixture);
const nbaDdEmpty = playerDDHistoryResponseSchema.parse(nbaDdEmptyFixture);
const ddOneSided = noVigResponseSchema.parse(ddOneSidedFixture);
const halfHistory = playerHistoryResponseSchema.parse(halfHistoryFixture);
const emptyPicks = dailyPicksResponseSchema.parse(emptyPicksFixture);
const emptySuggest = playerSuggestResponseSchema.parse(emptySuggestFixture);
const emptyHistory = playerHistoryResponseSchema.parse(emptyHistoryFixture);
const emptyNoVig = noVigResponseSchema.parse(emptyNoVigFixture);

const nav = vi.hoisted(() => ({
  eventId: "evt-mia-bos",
  player: "Bam Adebayo",
  path: "/event/evt-mia-bos",
}));

const apiMocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
  getDailyPicks: vi.fn(),
  getPlayerSuggestions: vi.fn(),
  getTeamLineup: vi.fn(),
  calculateNoVig: vi.fn(),
  getPlayerHistory: vi.fn(),
  getCSVPlayers: vi.fn(),
  getPlayerDDHistory: vi.fn(),
  useEventReads: vi.fn(),
  useEventBulkProps: vi.fn(),
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
    window.localStorage.clear();
    window.sessionStorage.clear();
    for (const fn of Object.values(apiMocks)) fn.mockReset();
    nav.eventId = "evt-mia-bos";
    nav.player = "Bam Adebayo";
    nav.path = "/event/evt-mia-bos";
    apiMocks.getEvents.mockResolvedValue(nbaEvents);
    apiMocks.getDailyPicks.mockResolvedValue(nbaPicks);
    apiMocks.getPlayerSuggestions.mockResolvedValue(nbaSuggest);
    apiMocks.getTeamLineup.mockImplementation(async (team: string) =>
      team === "BOS" ? nbaBosLineup : nbaLineup,
    );
    apiMocks.calculateNoVig.mockResolvedValue(nbaNoVig);
    apiMocks.getPlayerHistory.mockResolvedValue(nbaHistory);
    apiMocks.getCSVPlayers.mockResolvedValue(emptyCsv);
    apiMocks.getPlayerDDHistory.mockResolvedValue(nbaDdEmpty);
    apiMocks.useEventReads.mockReturnValue({ data: undefined });
    apiMocks.useEventBulkProps.mockReturnValue({ data: undefined });
  });

  it("reads the NBA game from the fixture payloads", async () => {
    renderWithProviders(<EventDetail />, { withAgentWidget: true });

    expect(
      (await screen.findAllByRole("heading", { name: /celtics @ heat/i })).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("heading", { name: /boston celtics @ miami heat/i })).not.toBeInTheDocument();
    expect(await screen.findByText("BOS lineup confirmed")).toBeInTheDocument();
    expect(screen.getByText("MIA lineup projected")).toBeInTheDocument();
    expect(screen.getAllByText("Strong play").length).toBeGreaterThan(0);
    expect(screen.getByText(/O 72%/)).toBeInTheDocument();
    expect(screen.getByText("C · MIA")).toBeInTheDocument();
    expect(screen.getByText(/Historical hit rate 72%/)).toBeInTheDocument();
    expect(screen.getByText(/Combined probability/)).toBeInTheDocument();
    expect(screen.getAllByText("No read").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/7:30 PM ET/).length).toBeGreaterThan(0);
    expect(screen.getByText(/3 of 5 signals support the over\./)).toBeInTheDocument();
    expect(screen.getAllByText("Supports").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Neutral").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /ask the board/i })).not.toBeInTheDocument();

    if (AGENT_CHAT_UI_ENABLED) {
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Ask the agent" }));
      expect(screen.getByRole("button", { name: "Close betting agent" })).toBeInTheDocument();
      await waitFor(() => {
        const stored = JSON.parse(window.sessionStorage.getItem("agent_widget_state") ?? "{}");
        expect(stored.pageContext.route).toBe("/event/evt-mia-bos");
        expect(stored.selectedPickContext).toMatchObject({
          player_name: "Bam Adebayo",
          event_id: "evt-mia-bos",
          metric: "points",
          threshold: 18.5,
          direction: "over",
          probability: 0.72,
        });
      });
    } else {
      expect(screen.queryByRole("button", { name: "Ask the agent" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^ask$/i })).not.toBeInTheDocument();
    }
  });

  it("keeps a loading NBA read distinct from a player who has no read", async () => {
    apiMocks.useEventReads.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    renderWithProviders(<EventDetail />);
    const herro = await screen.findByTestId("player-row-Tyler Herro");
    expect(herro).toHaveTextContent("Loading");
    expect(herro).not.toHaveTextContent("No read");
    expect(screen.getByText("Loading reads.")).toBeInTheDocument();
    expect(screen.queryByText("No read")).not.toBeInTheDocument();
  });

  it("keeps a failed NBA read distinct from a player who has no read", async () => {
    const refetch = vi.fn();
    apiMocks.useEventReads.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("reads down"),
      refetch,
    });
    apiMocks.useEventBulkProps.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("props down"),
      refetch: vi.fn(),
    });
    const user = userEvent.setup();
    renderWithProviders(<EventDetail />);
    expect(await screen.findByText("Reads failed.")).toBeInTheDocument();
    expect(screen.getByText("Props failed.")).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.queryByText("No read")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry reads" }));
    expect(refetch).toHaveBeenCalled();
  });


  it("adds the stored side to the slip for that league", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EventDetail />);
    await user.click(await screen.findByRole("button", { name: "Add Over 18.5 to slip" }));
    await waitFor(() => {
      const picks = JSON.parse(window.localStorage.getItem("betslip_picks") ?? "[]");
      expect(picks).toEqual([
        expect.objectContaining({
          player_name: "Bam Adebayo",
          event_id: "evt-mia-bos",
          metric: "points",
          threshold: 18.5,
          direction: "over",
          probability: 0.72,
        }),
      ]);
    });
    expect(window.localStorage.getItem("wnba_betslip_picks")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Under instead (35%)" }));
    await waitFor(() => {
      const picks = JSON.parse(window.localStorage.getItem("betslip_picks") ?? "[]");
      expect(picks).toEqual([
        expect.objectContaining({
          player_name: "Bam Adebayo",
          metric: "points",
          threshold: 18.5,
          direction: "under",
          probability: 0.35,
        }),
      ]);
    });
  });


  it("keeps the selected stat and line when the mobile tabs change", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EventDetail />);
    await screen.findAllByRole("heading", { name: /celtics @ heat/i });
    await user.click(screen.getByRole("button", { name: "REB" }));
    await user.click(screen.getByRole("tab", { name: "Odds" }));
    const odds = screen.getByRole("heading", { name: "Sportsbook prices" }).closest("section");
    expect(odds?.className).not.toContain("max-md:hidden");
    expect(screen.getByTestId("our-read").parentElement?.className).toContain("max-md:hidden");
    expect(screen.queryByRole("tab", { name: "Filters" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Game log" }));
    const log = screen.getByTestId("game-log");
    const lineValue = () => within(log).getByRole("button", { name: "reset" }).parentElement;
    await user.click(within(log).getByRole("button", { name: "Raise line" }));
    expect(lineValue()).toHaveTextContent("19");
    await waitFor(() =>
      expect(apiMocks.getPlayerHistory).toHaveBeenCalledWith(expect.objectContaining({ threshold: 19 })),
    );
    await user.click(within(log).getByRole("button", { name: "Filters" }));
    const sheet = screen.getByRole("dialog", { name: "Filter games" });
    await user.click(within(sheet).getByRole("button", { name: "Bench" }));
    expect(within(log).getByRole("button", { name: "Filters · 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Our read" }));
    expect(screen.getByRole("button", { name: "REB" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("our-read").parentElement?.className).not.toContain("max-md:hidden");
    expect(lineValue()).toHaveTextContent("19");
  });

  it("asks history for the same line, range, and opponent the chart shows", async () => {
    apiMocks.getPlayerHistory.mockImplementation(async (request: { n: number; opponent?: string; threshold: number }) => {
      if (request.opponent === "PHI") {
        const games = nbaHistory.game_logs.filter((game) => game.opponent === "PHI").slice(0, 1);
        return { ...nbaHistory, n_games: 1, game_logs: games, opponent_filter: "PHI" };
      }
      if (request.n === 20) {
        return { ...nbaHistory, n_games: 7 };
      }
      return nbaHistory;
    });
    const user = userEvent.setup();
    renderWithProviders(<EventDetail />);
    const chart = await screen.findByTestId("game-log");
    expect(await within(chart).findByText("Points · 40 games")).toBeInTheDocument();
    const filters = screen.getByTestId("game-filters");
    await user.click(within(filters).getByRole("button", { name: "L20" }));
    expect(await within(chart).findByText("Points · 7 games")).toBeInTheDocument();
    expect(apiMocks.getPlayerHistory).toHaveBeenCalledWith(
      expect.objectContaining({ n: 20, threshold: 18.5, player: "Bam Adebayo", metric: "points" }),
    );
    await user.selectOptions(within(filters).getByRole("combobox", { name: "Opponent" }), "PHI");
    expect(await within(chart).findByText("Points · 1 game")).toBeInTheDocument();
    expect(apiMocks.getPlayerHistory).toHaveBeenCalledWith(
      expect.objectContaining({ opponent: "PHI", threshold: 18.5 }),
    );
    await user.click(within(filters).getByRole("button", { name: "Starter" }));
    await waitFor(() => {
      expect(apiMocks.getPlayerHistory).toHaveBeenCalledWith(
        expect.objectContaining({ is_starter: true, opponent: "PHI" }),
      );
    });
  });

  it("prints the stored fair percent, not a second toFixed pass", async () => {
    apiMocks.calculateNoVig.mockImplementation(async (request: { market: string }) =>
      request.market === "player_double_double" ? ddOneSided : nbaNoVig,
    );
    const user = userEvent.setup();
    renderWithProviders(<EventDetail />);
    await user.click(await screen.findByRole("button", { name: "DD" }));
    expect(await screen.findByText(`No-vig consensus ${formatPercent(0.6755)} yes`)).toBeInTheDocument();
  });

  it("prints the history rate with formatPercent on the log tiles", async () => {
    apiMocks.getPlayerHistory.mockResolvedValue(halfHistory);
    renderWithProviders(<EventDetail />);
    const over = await screen.findByTestId("log-tile-over");
    expect(over).toHaveTextContent(formatPercent(0.6755));
    expect(over).not.toHaveTextContent("67.5%");
  });

  it("labels the fourteen empty fields without a fake percent", async () => {
    apiMocks.getDailyPicks.mockResolvedValue(emptyPicks);
    apiMocks.getPlayerSuggestions.mockResolvedValue(emptySuggest);
    apiMocks.getPlayerHistory.mockResolvedValue(emptyHistory);
    apiMocks.calculateNoVig.mockResolvedValue(emptyNoVig);
    apiMocks.getTeamLineup.mockResolvedValue(null);
    renderWithProviders(<EventDetail />);
    expect((await screen.findAllByText(/No posted line/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText("No read").length).toBeGreaterThan(0);
    expect(screen.getByText("No stored read for this player.")).toBeInTheDocument();
    expect(screen.queryByText(/No-vig consensus \d/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Last-10 hit rate needs a posted line/)).not.toBeInTheDocument();
    expect(screen.queryByText(/3 of 5 signals/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/No bookmaker line right now/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Home and away are not on the game log/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Names only. Games missed are not on this response/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("BOS lineup confirmed").length).toBeGreaterThan(0);
    expect(screen.queryByText("Strong play")).not.toBeInTheDocument();
    expect(screen.queryByText(/supports|neutral|against|easy|tough/i)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/NaN|Infinity|undefined/);
    expect(document.body.textContent).not.toMatch(/0\.0%/);
  });
});
