import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TodayBoard } from "@/components/TodayBoard";
import type { DailyPick, NBAEvent } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";

const apiMocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
  getDailyPicks: vi.fn(),
  getWNBAEvents: vi.fn(),
  getWnbaDailyPicks: vi.fn(),
}));

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

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...apiMocks };
});

function event(overrides: Partial<NBAEvent> = {}): NBAEvent {
  return {
    event_id: "heat-bucks",
    sport_key: "basketball_nba",
    home_team: "Milwaukee Bucks",
    away_team: "Miami Heat",
    commence_time: "2026-11-11T01:00:00Z",
    ...overrides,
  };
}

function pick(overrides: Partial<DailyPick> = {}): DailyPick {
  return {
    player_name: "Bam Adebayo",
    player_team: "Heat",
    player_team_code: "MIA",
    event_id: "heat-bucks",
    home_team: "Milwaukee Bucks",
    away_team: "Miami Heat",
    commence_time: "2026-11-11T01:00:00Z",
    metric: "rebounds",
    threshold: 10.5,
    direction: "over",
    probability: 0.724,
    n_games: 22,
    bookmakers_count: 4,
    all_lines: [10.5],
    has_projection: false,
    ...overrides,
  };
}

const nbaEvents = [
  event(),
  event({
    event_id: "sixers-nets",
    home_team: "Brooklyn Nets",
    away_team: "Philadelphia 76ers",
    commence_time: "2026-11-11T00:00:00Z",
  }),
  event({
    event_id: "magic-hornets",
    home_team: "Charlotte Hornets",
    away_team: "Orlando Magic",
    commence_time: "2026-11-11T00:30:00Z",
  }),
];

const nbaPicks = [
  pick(),
  pick({
    player_name: "Joel Embiid",
    player_team: "76ers",
    player_team_code: "PHI",
    event_id: "sixers-nets",
    home_team: "Brooklyn Nets",
    away_team: "Philadelphia 76ers",
    commence_time: "2026-11-11T00:00:00Z",
    metric: "points",
    threshold: 29.5,
    probability: 0.702,
    all_lines: [29.5],
  }),
  pick({
    player_name: "Tyrese Haliburton",
    player_team: "Pacers",
    player_team_code: "IND",
    event_id: "sixers-nets",
    home_team: "Brooklyn Nets",
    away_team: "Philadelphia 76ers",
    commence_time: "2026-11-11T00:00:00Z",
    metric: "assists",
    threshold: 9.5,
    probability: 0.681,
    all_lines: [9.5],
  }),
];

function boardPayload(events: NBAEvent[], picks: DailyPick[]) {
  return {
    events: {
      date: "2026-11-10",
      events,
    },
    picks: {
      date: "2026-11-10",
      analyzed_at: "2026-11-10T18:00:00Z",
      total_picks: picks.length,
      picks,
    },
  };
}

describe("TodayBoard", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-10T18:00:00-06:00"));
    apiMocks.getEvents.mockReset();
    apiMocks.getDailyPicks.mockReset();
    apiMocks.getWNBAEvents.mockReset();
    apiMocks.getWnbaDailyPicks.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders tonight's reads and each game's top read from the API", async () => {
    const payload = boardPayload(nbaEvents, nbaPicks);
    apiMocks.getEvents.mockResolvedValue(payload.events);
    apiMocks.getDailyPicks.mockResolvedValue(payload.picks);

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByText("TUE · NOV 10 · 3 GAMES")).toBeInTheDocument();
    expect(within(web).getByRole("link", { name: /all 3 picks/i })).toHaveAttribute("href", "/picks");

    const bam = within(web).getByRole("link", { name: /bam adebayo/i });
    expect(bam).toHaveTextContent("72.4%");
    expect(bam).toHaveTextContent("Strong play");
    expect(bam).toHaveTextContent("Over 10.5 REB");
    expect(bam).toHaveTextContent("MIA @ MIL · 7:00 PM");
    expect(bam.getAttribute("href")).toContain("/event/heat-bucks");
    expect(bam.getAttribute("href")).toContain("player=Bam");
    expect(bam.getAttribute("href")).toContain("market=player_rebounds");
    expect(bam.getAttribute("href")).toContain("threshold=10.5");

    expect(within(web).getByRole("link", { name: /joel embiid/i })).toHaveTextContent("70.2%");
    expect(within(web).getByRole("link", { name: /tyrese haliburton/i })).toHaveTextContent("Playable");
    expect(within(web).getByText("Adebayo Over 10.5 REB")).toBeInTheDocument();
    expect(within(web).getByText("Embiid Over 29.5 PTS")).toBeInTheDocument();
    expect(within(web).getByText("No read on this game")).toBeInTheDocument();
    expect(within(web).queryByText("81%")).not.toBeInTheDocument();
    expect(within(web).queryByText(/chet holmgren/i)).not.toBeInTheDocument();

    const mobile = screen.getByTestId("today-mobile");
    expect(within(mobile).getByRole("link", { name: /see all 3 picks/i })).toHaveAttribute("href", "/picks");
    expect(within(mobile).getByRole("link", { name: /bam adebayo/i })).toHaveTextContent("72.4%");
  });

  it("shows empty states when the slate and the board have no rows", async () => {
    const payload = boardPayload([], []);
    apiMocks.getEvents.mockResolvedValue(payload.events);
    apiMocks.getDailyPicks.mockResolvedValue(payload.picks);

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByText("No games on this date.")).toBeInTheDocument();
    expect(within(web).getByText("No reads on tonight's board.")).toBeInTheDocument();
    expect(within(web).getByRole("link", { name: /all 0 picks/i })).toBeInTheDocument();
    expect(within(web).queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("shows a loading state without player names", () => {
    apiMocks.getEvents.mockReturnValue(new Promise(() => {}));
    apiMocks.getDailyPicks.mockReturnValue(new Promise(() => {}));

    renderWithProviders(<TodayBoard league="nba" />);

    expect(screen.getByTestId("today-loading")).toHaveTextContent("Loading tonight's board");
    expect(screen.queryByText("Bam Adebayo")).not.toBeInTheDocument();
    expect(screen.queryByText("72.4%")).not.toBeInTheDocument();
  });

  it("shows an error and retries the games request", async () => {
    const user = userEvent.setup();
    const payload = boardPayload(nbaEvents, nbaPicks);
    apiMocks.getEvents.mockRejectedValueOnce(new Error("board down"));
    apiMocks.getDailyPicks.mockResolvedValue(payload.picks);

    renderWithProviders(<TodayBoard league="nba" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load games.");
    expect(alert).toHaveTextContent("board down");
    expect(screen.queryByText("Bam Adebayo")).not.toBeInTheDocument();

    apiMocks.getEvents.mockResolvedValue(payload.events);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("today-web")).toHaveTextContent("Bam Adebayo");
  });

  it("keeps the games and withholds percents when reads fail", async () => {
    apiMocks.getEvents.mockResolvedValue(boardPayload(nbaEvents, []).events);
    apiMocks.getDailyPicks.mockRejectedValue(new Error("picks down"));

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByText(/reads unavailable/i)).toHaveTextContent("picks down");
    expect(within(web).getAllByText("Top read unavailable").length).toBeGreaterThan(0);
    expect(within(web).getByText("Heat")).toBeInTheDocument();
    expect(within(web).queryByText("72.4%")).not.toBeInTheDocument();
    expect(within(web).queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("renders the WNBA board from the WNBA endpoints", async () => {
    apiMocks.getWNBAEvents.mockResolvedValue({
      date: "2026-11-10",
      events: [
        event({
          event_id: "aces-liberty",
          sport_key: "basketball_wnba",
          away_team: "Las Vegas Aces",
          home_team: "New York Liberty",
        }),
      ],
    });
    apiMocks.getWnbaDailyPicks.mockResolvedValue({
      date: "2026-11-10",
      analyzed_at: "2026-11-10T18:00:00Z",
      total_picks: 1,
      picks: [
        pick({
          player_name: "A'ja Wilson",
          player_team: "Aces",
          player_team_code: "LVA",
          event_id: "aces-liberty",
          away_team: "Las Vegas Aces",
          home_team: "New York Liberty",
          metric: "points",
          threshold: 22.5,
          probability: 0.71,
        }),
      ],
    });

    renderWithProviders(<TodayBoard league="wnba" />);

    const web = await screen.findByTestId("today-web");
    const wilson = within(web).getByRole("link", { name: /a'ja wilson/i });
    expect(wilson).toHaveTextContent("71.0%");
    expect(wilson).toHaveTextContent("LVA @ NYL");
    expect(wilson.getAttribute("href")).toContain("/wnba/event/aces-liberty");
    expect(within(web).getByRole("link", { name: /all 1 picks/i })).toHaveAttribute("href", "/wnba/picks");
    expect(apiMocks.getEvents).not.toHaveBeenCalled();
    expect(apiMocks.getWNBAEvents).toHaveBeenCalled();
  });
});
