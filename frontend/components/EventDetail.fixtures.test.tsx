import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EventDetail } from "@/components/EventDetail";
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
import wnbaEventsFixture from "@/test/fixtures/event/wnba-events.json";
import wnbaPicksFixture from "@/test/fixtures/event/wnba-daily-picks.json";
import wnbaSuggestFixture from "@/test/fixtures/event/wnba-suggest.json";
import wnbaHistoryFixture from "@/test/fixtures/event/wnba-history-wilson.json";
import wnbaLvaLineupFixture from "@/test/fixtures/event/wnba-lineup-lva.json";
import wnbaNylLineupFixture from "@/test/fixtures/event/wnba-lineup-nyl.json";
import wnbaNoVigFixture from "@/test/fixtures/event/wnba-no-vig-wilson.json";
import emptyCsvFixture from "@/test/fixtures/event/csv-players-empty.json";
import nbaDdEmptyFixture from "@/test/fixtures/event/nba-dd-history-empty.json";
import wnbaDdEmptyFixture from "@/test/fixtures/event/wnba-dd-history-empty.json";
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
const wnbaEvents = eventsResponseSchema.parse(wnbaEventsFixture);
const wnbaPicks = dailyPicksResponseSchema.parse(wnbaPicksFixture);
const wnbaSuggest = playerSuggestResponseSchema.parse(wnbaSuggestFixture);
const wnbaHistory = playerHistoryResponseSchema.parse(wnbaHistoryFixture);
const wnbaLvaLineup = teamLineupSchema.parse(wnbaLvaLineupFixture);
const wnbaNylLineup = teamLineupSchema.parse(wnbaNylLineupFixture);
const wnbaNoVig = noVigResponseSchema.parse(wnbaNoVigFixture);
const emptyCsv = csvPlayersResponseSchema.parse(emptyCsvFixture);
const nbaDdEmpty = playerDDHistoryResponseSchema.parse(nbaDdEmptyFixture);
const wnbaDdEmpty = playerDDHistoryResponseSchema.parse(wnbaDdEmptyFixture);
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
  getWNBAEvents: vi.fn(),
  getDailyPicks: vi.fn(),
  getWnbaDailyPicks: vi.fn(),
  getPlayerSuggestions: vi.fn(),
  getWNBAPlayerSuggestions: vi.fn(),
  getTeamLineup: vi.fn(),
  getWNBATeamLineup: vi.fn(),
  calculateNoVig: vi.fn(),
  calculateWNBANoVig: vi.fn(),
  getPlayerHistory: vi.fn(),
  getWNBAPlayerHistory: vi.fn(),
  getCSVPlayers: vi.fn(),
  getWNBACSVPlayers: vi.fn(),
  getPlayerDDHistory: vi.fn(),
  getWNBAPlayerDDHistory: vi.fn(),
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
    apiMocks.calculateNoVig.mockResolvedValue(nbaNoVig);
    apiMocks.calculateWNBANoVig.mockResolvedValue(wnbaNoVig);
    apiMocks.getPlayerHistory.mockResolvedValue(nbaHistory);
    apiMocks.getWNBAPlayerHistory.mockResolvedValue(wnbaHistory);
    apiMocks.getCSVPlayers.mockResolvedValue(emptyCsv);
    apiMocks.getWNBACSVPlayers.mockResolvedValue(emptyCsv);
    apiMocks.getPlayerDDHistory.mockResolvedValue(nbaDdEmpty);
    apiMocks.getWNBAPlayerDDHistory.mockResolvedValue(wnbaDdEmpty);
    apiMocks.useEventReads.mockReturnValue({ data: undefined });
    apiMocks.useEventBulkProps.mockReturnValue({ data: undefined });
  });

  it("reads the NBA game from the fixture payloads and opens the agent", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EventDetail league="nba" />, { withAgentWidget: true });

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
    expect(apiMocks.getWNBAEvents).not.toHaveBeenCalled();
    expect(apiMocks.calculateWNBANoVig).not.toHaveBeenCalled();
    expect(apiMocks.getWNBATeamLineup).not.toHaveBeenCalled();
    expect(apiMocks.getWNBAPlayerHistory).not.toHaveBeenCalled();

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
  });

  it("keeps a loading NBA read distinct from a player who has no read", async () => {
    apiMocks.useEventReads.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    renderWithProviders(<EventDetail league="nba" />);
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
    renderWithProviders(<EventDetail league="nba" />);
    expect(await screen.findByText("Reads failed.")).toBeInTheDocument();
    expect(screen.getByText("Props failed.")).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.queryByText("No read")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry reads" }));
    expect(refetch).toHaveBeenCalled();
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
    expect(apiMocks.getWnbaDailyPicks).toHaveBeenCalled();
    expect(apiMocks.getWNBAPlayerSuggestions).toHaveBeenCalled();
    expect(apiMocks.calculateWNBANoVig).toHaveBeenCalled();
    expect(apiMocks.getWNBAPlayerHistory).toHaveBeenCalled();
    expect(apiMocks.getWNBATeamLineup).toHaveBeenCalledWith("NYL", "2026-11-10");
    expect(apiMocks.getWNBATeamLineup).toHaveBeenCalledWith("LVA", "2026-11-10");
    expect(apiMocks.getEvents).not.toHaveBeenCalled();
    expect(apiMocks.getDailyPicks).not.toHaveBeenCalled();
    expect(apiMocks.getPlayerSuggestions).not.toHaveBeenCalled();
    expect(apiMocks.getTeamLineup).not.toHaveBeenCalled();
    expect(apiMocks.calculateNoVig).not.toHaveBeenCalled();
    expect(apiMocks.getPlayerHistory).not.toHaveBeenCalled();
    expect(apiMocks.getCSVPlayers).not.toHaveBeenCalled();
    expect(apiMocks.getPlayerDDHistory).not.toHaveBeenCalled();
    const hrefs = Array.from(document.querySelectorAll("a")).map((node) => node.getAttribute("href") ?? "");
    expect(hrefs.filter((href) => href.includes("/api/nba"))).toEqual([]);
    expect(hrefs.filter((href) => href.includes("/player/") && !href.includes("/wnba/player/"))).toEqual([]);
  });

  it("adds the stored side to the slip for that league", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EventDetail league="nba" />);
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
    expect(JSON.parse(window.localStorage.getItem("wnba_betslip_picks") ?? "[]")).toEqual([]);

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

  it("adds a WNBA read to the WNBA slip only", async () => {
    nav.eventId = "evt-lva-nyl";
    nav.player = "A'ja Wilson";
    nav.path = "/wnba/event/evt-lva-nyl";
    const user = userEvent.setup();
    renderWithProviders(<EventDetail league="wnba" />, { withAgentWidget: true });
    await user.click(await screen.findByRole("button", { name: "Add Over 22.5" }));
    await waitFor(() => {
      const picks = JSON.parse(window.localStorage.getItem("wnba_betslip_picks") ?? "[]");
      expect(picks).toEqual([
        expect.objectContaining({
          player_name: "A'ja Wilson",
          event_id: "evt-lva-nyl",
          metric: "points",
          threshold: 22.5,
          direction: "over",
          probability: 0.68,
        }),
      ]);
    });
    expect(JSON.parse(window.localStorage.getItem("betslip_picks") ?? "[]")).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Ask the agent" }));
    await waitFor(() => {
      const stored = JSON.parse(window.sessionStorage.getItem("agent_widget_state") ?? "{}");
      expect(stored.pageContext.route).toBe("/wnba/event/evt-lva-nyl");
      expect(stored.selectedPickContext.player_name).toBe("A'ja Wilson");
      expect(stored.selectedPickContext.probability).toBe(0.68);
    });
  });

  it("keeps the selected stat and line when the mobile tabs change", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EventDetail league="nba" />);
    await screen.findAllByRole("heading", { name: /celtics @ heat/i });
    await user.click(screen.getByRole("button", { name: "REB" }));
    await user.click(screen.getByRole("tab", { name: "Odds" }));
    const odds = screen.getByRole("heading", { name: "Sportsbook prices" }).closest("section");
    expect(odds?.className).not.toContain("max-md:hidden");
    expect(screen.getByTestId("our-read").parentElement?.className).toContain("max-md:hidden");
    expect(screen.queryByRole("tab", { name: "Filters" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Filters" }));
    const filters = screen.getByRole("dialog", { name: "Filter games" });
    await user.click(within(filters).getByRole("button", { name: "Raise line" }));
    expect(within(filters).getByText("19")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Game log" }));
    await user.click(screen.getByRole("tab", { name: "Our read" }));
    expect(screen.getByRole("button", { name: "REB" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("our-read").parentElement?.className).not.toContain("max-md:hidden");
    expect(within(screen.getByRole("dialog", { name: "Filter games" })).getByText("19")).toBeInTheDocument();
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
    renderWithProviders(<EventDetail league="nba" />);
    const chart = await screen.findByTestId("game-log-chart");
    expect(await within(chart).findByText("Points · 40 games")).toBeInTheDocument();
    const filters = screen.getByTestId("game-filters");
    await user.click(within(filters).getByRole("button", { name: "Last 20" }));
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
    renderWithProviders(<EventDetail league="nba" />);
    await user.click(await screen.findByRole("button", { name: "DD" }));
    const caption = await screen.findByText(/No-vig consensus yes/);
    expect(caption).toHaveTextContent(`No-vig consensus yes ${formatPercent(0.6755)}`);
  });

  it("prints the history rate with formatPercent on the log tiles", async () => {
    apiMocks.getPlayerHistory.mockResolvedValue(halfHistory);
    renderWithProviders(<EventDetail league="nba" />);
    expect((await screen.findAllByText(formatPercent(0.6755))).length).toBeGreaterThan(0);
    const tiles = Array.from(document.querySelectorAll(".font-mono.text-2xl")).map((node) => node.textContent);
    expect(tiles).toContain(formatPercent(0.6755));
    expect(tiles).not.toContain("67.5%");
  });

  it("labels the fourteen empty fields without a fake percent", async () => {
    apiMocks.getDailyPicks.mockResolvedValue(emptyPicks);
    apiMocks.getPlayerSuggestions.mockResolvedValue(emptySuggest);
    apiMocks.getPlayerHistory.mockResolvedValue(emptyHistory);
    apiMocks.calculateNoVig.mockResolvedValue(emptyNoVig);
    apiMocks.getTeamLineup.mockResolvedValue(null);
    renderWithProviders(<EventDetail league="nba" />);
    expect((await screen.findAllByText(/No posted line/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText("No read").length).toBeGreaterThan(0);
    expect(screen.getByText("No stored read for this player.")).toBeInTheDocument();
    expect(screen.getAllByText(/No-vig consensus is not on this response/).length).toBeGreaterThan(0);
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
