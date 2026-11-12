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
import { giannisTopRead } from "@/test/fixtures/today/top-read";

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
    const eyebrow = within(web).getByTestId("today-hero-eyebrow");
    expect(eyebrow).toHaveTextContent("TUE · NOV 10 · 3 GAMES");
    expect(eyebrow.className).toContain("text-accent");
    expect(eyebrow.className).not.toMatch(/(?:^|\s)text-eyebrow(?:\s|$)/);
    expect(eyebrow.className).not.toContain("#7B4FC4");
    expect(eyebrow.className).not.toContain("#7b4fc4");
    expect(within(web).queryByText(/NOV 11/)).not.toBeInTheDocument();
    expect(within(web).getByRole("link", { name: /all 3 picks/i })).toHaveAttribute("href", "/picks");

    const bam = within(web).getByRole("link", { name: /bam adebayo/i });
    expect(bam).toHaveTextContent("72%");
    expect(bam).toHaveTextContent("Strong play");
    expect(bam).toHaveTextContent("Over 10.5 REB");
    expect(bam).toHaveTextContent("MIA @ MIL · 7:00 PM");
    expect(bam.className).toContain("bg-white/[0.08]");
    expect(bam.className).toContain("border-white/[0.16]");
    expect(bam.className).toContain("hover:bg-white/[0.14]");
    expect(within(web).getByText(/built from market prices, recent form, projection and matchup/i)).toBeInTheDocument();
    expect(within(web).getByText("Tap a game to check any player prop")).toBeInTheDocument();
    expect(within(web).queryByText(/open a game to check any player prop/i)).not.toBeInTheDocument();
    expect(bam).not.toHaveTextContent("1:00 AM");
    expect(bam.getAttribute("href")).toContain("/event/heat-bucks");
    expect(bam.getAttribute("href")).toContain("player=Bam");
    expect(bam.getAttribute("href")).toContain("market=player_rebounds");
    expect(bam.getAttribute("href")).toContain("threshold=10.5");

    expect(within(web).getByRole("link", { name: /joel embiid/i })).toHaveTextContent("70%");
    expect(within(web).getByRole("link", { name: /joel embiid/i })).not.toHaveTextContent("70.2%");
    expect(within(web).getByRole("link", { name: /tyrese haliburton/i })).toHaveTextContent("Playable");
    expect(within(web).getByText("Adebayo Over 10.5 REB")).toBeInTheDocument();
    expect(within(web).getByText("Embiid Over 29.5 PTS")).toBeInTheDocument();
    expect(within(web).getByText("No read on this game")).toBeInTheDocument();
    const mobile = screen.getByTestId("today-mobile");
    const chevron = within(mobile).getAllByText("›")[0];
    expect(chevron.className).toContain("text-muted");
    expect(chevron.className).not.toContain("B9B3C4");
    expect(within(web).queryByText("81%")).not.toBeInTheDocument();
    expect(within(web).queryByText(/chet holmgren/i)).not.toBeInTheDocument();
    const shownPickPercents = new Set(
      nbaPicks.picks.map((pick) => formatPercent(pick.probability)),
    );
    for (const oddsPercent of impliedPercents(recordedNoVig)) {
      if (oddsPercent === "—" || shownPickPercents.has(oddsPercent)) continue;
      expect(within(web).queryByText(oddsPercent)).not.toBeInTheDocument();
    }
    expect(web).not.toHaveTextContent("NaN");
    expect(web).not.toHaveTextContent("undefined");
    expect(web).not.toHaveTextContent("null");

    expect(within(mobile).getByRole("link", { name: /see all 3 picks/i })).toHaveAttribute("href", "/picks");
    const mobileBam = within(mobile).getByRole("link", { name: /bam adebayo/i });
    expect(mobileBam).toHaveTextContent("72%");
    expect(mobileBam).not.toHaveTextContent("72.4%");
    expect(mobileBam.className).toContain("bg-brand");
    expect(mobileBam.className).not.toContain("bg-white");
    expect(mobileBam.className).not.toContain("border");
    expect(within(mobile).queryByText(/built from market prices/i)).not.toBeInTheDocument();

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
    expect(screen.queryByText("72%")).not.toBeInTheDocument();
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
    expect(within(web).queryByText("72%")).not.toBeInTheDocument();
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
    expect(wilson).toHaveTextContent("71%");
    expect(wilson).toHaveTextContent("LVA @ NYL");
    expect(wilson).not.toHaveTextContent("LAL");
    expect(wilson).not.toHaveTextContent("NYK");
    expect(wilson.getAttribute("href")).toContain("/wnba/event/aces-liberty");

    const stewart = within(web).getByRole("link", { name: /breanna stewart/i });
    expect(stewart).toHaveTextContent("Playable");
    expect(stewart).toHaveTextContent("67%");
    expect(stewart).not.toHaveTextContent("68%");
    expect(stewart).not.toHaveTextContent("67.6%");
    expect(stewart).toHaveTextContent("SEA @ MIN");
    expect(stewart).not.toHaveTextContent("GSW");
    expect(within(web).getByText("Lynx")).toBeInTheDocument();
    expect(within(web).queryByText("Timberwolves")).not.toBeInTheDocument();
    expect(within(web).getByRole("link", { name: /all 2 picks/i })).toHaveAttribute("href", "/wnba/picks");
    const fanduelImplied = recordedNoVig.results.find(
      (row) => row.bookmaker === "fanduel",
    )?.p_over_imp;
    expect(formatPercent(fanduelImplied)).toBe("71%");
    expect(within(web).queryByText("70.6%")).not.toBeInTheDocument();
    expect(within(web).queryByText("71.4%")).not.toBeInTheDocument();

    expect(apiMocks.getEvents).not.toHaveBeenCalled();
    expect(apiMocks.getDailyPicks).not.toHaveBeenCalled();
    expect(apiMocks.getWNBAEvents).toHaveBeenCalledWith("2026-11-10");
    expect(apiMocks.getWnbaDailyPicks).toHaveBeenCalledWith({ date: "2026-11-10" });
  });

  it("uses top_read and the ET wall clock from the events payload", async () => {
    const withRead = eventsResponseSchema.parse({
      ...nbaEventsFixture,
      events: nbaEventsFixture.events.map((event, index) =>
        index === 0
          ? {
              ...event,
              commence_time_et: "2026-11-10T20:00:00-05:00",
              display_tz: "ET",
              lineup_status: { home: "confirmed", away: "projected" },
              top_read: giannisTopRead,
            }
          : event,
      ),
    });
    apiMocks.getEvents.mockResolvedValue(withRead);
    apiMocks.getDailyPicks.mockResolvedValue(nbaPicks);

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByRole("link", { name: /bam adebayo/i })).toHaveTextContent("MIA @ MIL · 8:00 PM");
    expect(within(web).getByRole("link", { name: /bam adebayo/i })).toHaveTextContent("72%");
    expect(within(web).getByText("Adebayo Over 10.5 REB")).toBeInTheDocument();
    expect(within(web).queryByText("Antetokounmpo Under 31.5 PTS")).not.toBeInTheDocument();
    expect(within(web).queryByText("81%")).not.toBeInTheDocument();
    expect(within(web).getByText("Embiid Over 29.5 PTS")).toBeInTheDocument();
    expect(within(web).queryByText(/lineup confirmed/i)).not.toBeInTheDocument();
  });

  it("keeps top_read on the game card when daily picks fail", async () => {
    const withRead = eventsResponseSchema.parse({
      ...nbaEventsFixture,
      events: nbaEventsFixture.events.map((event, index) =>
        index === 0
          ? {
              ...event,
              top_read: giannisTopRead,
            }
          : event,
      ),
    });
    apiMocks.getEvents.mockResolvedValue(withRead);
    apiMocks.getDailyPicks.mockRejectedValue(new Error("picks down"));

    renderWithProviders(<TodayBoard league="nba" />);

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByText("Antetokounmpo Under 31.5 PTS")).toBeInTheDocument();
    expect(within(web).queryByText("81%")).not.toBeInTheDocument();
    expect(within(web).getAllByText("Top read unavailable")).toHaveLength(2);
    expect(within(web).getByText(/reads unavailable/i)).toHaveTextContent("picks down");
    expect(within(web).queryByText("72%")).not.toBeInTheDocument();
  });
});
