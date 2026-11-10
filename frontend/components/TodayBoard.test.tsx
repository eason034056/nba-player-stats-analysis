import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TodayBoard } from "@/components/TodayBoard";
import { formatPercent } from "@/lib/player-dd";
import {
  dailyPicksResponseSchema,
  eventsResponseSchema,
  type DailyPicksResponse,
} from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import nbaEventsFixture from "@/test/fixtures/today/nba-events.json";
import nbaPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";
import nbaEventsEmptyFixture from "@/test/fixtures/today/nba-events-empty.json";
import nbaPicksEmptyFixture from "@/test/fixtures/today/nba-daily-picks-empty.json";
import nbaEventsPartialFixture from "@/test/fixtures/today/nba-events-partial.json";
import nbaPicksPartialFixture from "@/test/fixtures/today/nba-daily-picks-partial.json";
import nbaPicksCountFixture from "@/test/fixtures/today/nba-daily-picks-total-mismatch.json";
import nbaPicksCountMissingFixture from "@/test/fixtures/today/nba-daily-picks-count-missing.json";
import nbaPicksMissingDirectionFixture from "@/test/fixtures/today/nba-daily-picks-missing-direction.json";
import wnbaEventsFixture from "@/test/fixtures/today/wnba-events.json";
import wnbaPicksFixture from "@/test/fixtures/today/wnba-daily-picks.json";
import recordedNoVig from "@/test/fixtures/props-no-vig/player-double-double.json";

const nbaEvents = eventsResponseSchema.parse(nbaEventsFixture);
const nbaPicks = dailyPicksResponseSchema.parse(nbaPicksFixture);
const nbaEventsEmpty = eventsResponseSchema.parse(nbaEventsEmptyFixture);
const nbaPicksEmpty = dailyPicksResponseSchema.parse(nbaPicksEmptyFixture);
const nbaEventsPartial = eventsResponseSchema.parse(nbaEventsPartialFixture);
const nbaPicksCount = dailyPicksResponseSchema.parse(nbaPicksCountFixture);
const wnbaEvents = eventsResponseSchema.parse(wnbaEventsFixture);
const wnbaPicks = dailyPicksResponseSchema.parse(wnbaPicksFixture);

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

function impliedPercents(payload: typeof recordedNoVig): string[] {
  return payload.results.flatMap((row) => [
    formatPercent(row.p_over_imp),
    formatPercent(row.p_under_imp),
    formatPercent(row.p_over_fair),
    formatPercent(row.p_under_fair),
  ]);
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
    apiMocks.getEvents.mockResolvedValue(nbaEvents);
    apiMocks.getDailyPicks.mockResolvedValue(nbaPicks);

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByText("TUE · NOV 10 · 3 GAMES")).toBeInTheDocument();
    expect(within(web).queryByText(/NOV 11/)).not.toBeInTheDocument();
    expect(within(web).getByRole("link", { name: /all 3 picks/i })).toHaveAttribute("href", "/picks");

    const bam = within(web).getByRole("link", { name: /bam adebayo/i });
    expect(bam).toHaveTextContent("—");
    expect(bam).not.toHaveTextContent(formatPercent(nbaPicks.picks[0].probability));
    expect(bam).not.toHaveTextContent("Strong play");
    expect(bam).toHaveTextContent("Over 10.5 REB");
    expect(bam).toHaveTextContent("MIA @ MIL · 7:00 PM");
    expect(bam).not.toHaveTextContent("1:00 AM");
    expect(bam.getAttribute("href")).toContain("/event/heat-bucks");
    expect(bam.getAttribute("href")).toContain("player=Bam");
    expect(bam.getAttribute("href")).toContain("market=player_rebounds");
    expect(bam.getAttribute("href")).toContain("threshold=10.5");

    expect(within(web).getByRole("link", { name: /joel embiid/i })).toHaveTextContent("—");
    expect(within(web).getByRole("link", { name: /joel embiid/i })).not.toHaveTextContent("70.2%");
    expect(within(web).getByRole("link", { name: /tyrese haliburton/i })).not.toHaveTextContent("Playable");
    expect(within(web).getByText("Adebayo Over 10.5 REB")).toBeInTheDocument();
    expect(within(web).getByText("Embiid Over 29.5 PTS")).toBeInTheDocument();
    expect(within(web).getByText("No read on this game")).toBeInTheDocument();
    const mobile = screen.getByTestId("today-mobile");
    const chevron = within(mobile).getAllByText("›")[0];
    expect(chevron.className).toContain("text-muted");
    expect(chevron.className).not.toContain("B9B3C4");
    expect(within(web).queryByText("81%")).not.toBeInTheDocument();
    expect(within(web).queryByText(/chet holmgren/i)).not.toBeInTheDocument();
    for (const oddsPercent of impliedPercents(recordedNoVig)) {
      expect(within(web).queryByText(oddsPercent)).not.toBeInTheDocument();
    }
    expect(web).not.toHaveTextContent("NaN");
    expect(web).not.toHaveTextContent("undefined");
    expect(web).not.toHaveTextContent("null");

    expect(within(mobile).getByRole("link", { name: /see all 3 picks/i })).toHaveAttribute("href", "/picks");
    expect(within(mobile).getByRole("link", { name: /bam adebayo/i })).toHaveTextContent("—");
    expect(within(mobile).getByRole("link", { name: /bam adebayo/i })).not.toHaveTextContent("72.4%");

    expect(apiMocks.getEvents).toHaveBeenCalledWith("2026-11-10");
    expect(apiMocks.getDailyPicks).toHaveBeenCalledWith({ date: "2026-11-10" });
    expect(apiMocks.getWNBAEvents).not.toHaveBeenCalled();
    expect(apiMocks.getWnbaDailyPicks).not.toHaveBeenCalled();
  });

  it("shows empty states when the slate and the board have no rows", async () => {
    apiMocks.getEvents.mockResolvedValue(nbaEventsEmpty);
    apiMocks.getDailyPicks.mockResolvedValue(nbaPicksEmpty);

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
    apiMocks.getEvents.mockRejectedValueOnce(new Error("board down"));
    apiMocks.getDailyPicks.mockResolvedValue(nbaPicks);

    renderWithProviders(<TodayBoard league="nba" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load games.");
    expect(alert).toHaveTextContent("board down");
    expect(screen.queryByText("Bam Adebayo")).not.toBeInTheDocument();

    apiMocks.getEvents.mockResolvedValue(nbaEvents);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("today-web")).toHaveTextContent("Bam Adebayo");
  });

  it("does not print an object error when the games request rejects with a non-Error", async () => {
    apiMocks.getEvents.mockRejectedValueOnce("board down");
    apiMocks.getDailyPicks.mockResolvedValue(nbaPicksEmpty);

    renderWithProviders(<TodayBoard league="nba" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load games.");
    expect(alert).toHaveTextContent("The request failed.");
    expect(alert).not.toHaveTextContent("undefined");
    expect(alert).not.toHaveTextContent("[object Object]");
  });

  it("keeps the games and withholds percents when reads fail", async () => {
    apiMocks.getEvents.mockResolvedValue(nbaEvents);
    apiMocks.getDailyPicks.mockRejectedValue(new Error("picks down"));

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByText(/reads unavailable/i)).toHaveTextContent("picks down");
    expect(within(web).getAllByText("Top read unavailable").length).toBeGreaterThan(0);
    expect(within(web).getByText("Heat")).toBeInTheDocument();
    expect(within(web).queryByText("72.4%")).not.toBeInTheDocument();
    expect(within(web).queryByText("0.0%")).not.toBeInTheDocument();
    expect(within(web).getByRole("link", { name: /all picks/i })).toBeInTheDocument();
  });

  it("renders a blank clock and an em dash when probability and commence time are missing", async () => {
    apiMocks.getEvents.mockResolvedValue(nbaEventsPartial);
    apiMocks.getDailyPicks.mockResolvedValue(
      nbaPicksPartialFixture as unknown as DailyPicksResponse,
    );

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    const bam = within(web).getByRole("link", { name: /bam adebayo/i });
    expect(bam).toHaveTextContent("—");
    expect(bam).toHaveTextContent("MIA @ MIL");
    expect(bam).not.toHaveTextContent("AM");
    expect(bam).not.toHaveTextContent("PM");
    expect(web).not.toHaveTextContent("NaN");
    expect(web).not.toHaveTextContent("undefined");
    expect(web).not.toHaveTextContent("Pass");
    expect(web).not.toHaveTextContent("0.0%");
    expect(dailyPicksResponseSchema.safeParse(nbaPicksPartialFixture).success).toBe(false);
  });

  it("omits the count when total_picks is missing and still prints zero", async () => {
    apiMocks.getEvents.mockResolvedValue(nbaEventsEmpty);
    apiMocks.getDailyPicks.mockResolvedValue(
      nbaPicksCountMissingFixture as unknown as DailyPicksResponse,
    );

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByRole("link", { name: "All picks →" })).toBeInTheDocument();
    expect(web).not.toHaveTextContent("undefined");
    expect(within(web).queryByRole("link", { name: /all 0 picks/i })).not.toBeInTheDocument();
  });

  it("dashes a missing direction on the card", async () => {
    apiMocks.getEvents.mockResolvedValue(nbaEventsPartial);
    apiMocks.getDailyPicks.mockResolvedValue(
      nbaPicksMissingDirectionFixture as unknown as DailyPicksResponse,
    );

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByRole("link", { name: /bam adebayo/i })).toHaveTextContent("— 10.5 REB");
    expect(web).not.toHaveTextContent("undefined");
    expect(web).not.toHaveTextContent("null 10.5");
  });

  it("uses the API total_picks count instead of the number of rows on the card", async () => {
    apiMocks.getEvents.mockResolvedValue(nbaEvents);
    apiMocks.getDailyPicks.mockResolvedValue(nbaPicksCount);

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByRole("link", { name: /all 9 picks/i })).toHaveAttribute("href", "/picks");
    expect(within(web).getAllByRole("link", { name: /bam adebayo/i })).toHaveLength(1);
  });

  it("renders the WNBA board from the WNBA endpoints", async () => {
    apiMocks.getWNBAEvents.mockResolvedValue(wnbaEvents);
    apiMocks.getWnbaDailyPicks.mockResolvedValue(wnbaPicks);

    renderWithProviders(<TodayBoard league="wnba" />);

    const web = await screen.findByTestId("today-web");
    const wilson = within(web).getByRole("link", { name: /a'ja wilson/i });
    expect(wilson).toHaveTextContent("71.0%");
    expect(wilson).toHaveTextContent("LVA @ NYL");
    expect(wilson).not.toHaveTextContent("LAL");
    expect(wilson).not.toHaveTextContent("NYK");
    expect(wilson.getAttribute("href")).toContain("/wnba/event/aces-liberty");

    const stewart = within(web).getByRole("link", { name: /breanna stewart/i });
    expect(stewart).toHaveTextContent("67.6%");
    expect(stewart).not.toHaveTextContent("67.5%");
    expect(stewart).toHaveTextContent("SEA @ MIN");
    expect(stewart).not.toHaveTextContent("GSW");
    expect(within(web).getByText("Lynx")).toBeInTheDocument();
    expect(within(web).queryByText("Timberwolves")).not.toBeInTheDocument();
    expect(within(web).getByRole("link", { name: /all 2 picks/i })).toHaveAttribute("href", "/wnba/picks");
    const fanduelImplied = recordedNoVig.results.find(
      (row) => row.bookmaker === "fanduel",
    )?.p_over_imp;
    expect(formatPercent(fanduelImplied)).toBe("70.6%");
    expect(within(web).queryByText("70.6%")).not.toBeInTheDocument();
    expect(within(web).queryByText("71.4%")).not.toBeInTheDocument();

    expect(apiMocks.getEvents).not.toHaveBeenCalled();
    expect(apiMocks.getDailyPicks).not.toHaveBeenCalled();
    expect(apiMocks.getWNBAEvents).toHaveBeenCalledWith("2026-11-10");
    expect(apiMocks.getWnbaDailyPicks).toHaveBeenCalledWith({ date: "2026-11-10" });
  });
});
