import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TodayBoard } from "@/components/TodayBoard";
import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { EventActionBar } from "@/components/event/EventActionBar";
import { OurRead } from "@/components/event/OurRead";
import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { slipTotals } from "@/lib/bet-slip-board";
import { buildOurRead } from "@/lib/event-page";
import { formatTierPercent } from "@/lib/player-dd";
import { dailyPicksResponseSchema, eventsResponseSchema, lineupsResponseSchema, type DailyPick } from "@/lib/schemas";
import { todayGames, todayReads } from "@/lib/today-board";
import { clearBetSlip, createBetSlipPick, createTestQueryClient, renderWithProviders, seedBetSlip } from "@/test/test-utils";
import emptyLineupsFixture from "@/test/fixtures/lineups/empty.json";
import boardFixture from "@/test/fixtures/picks/nba-daily-picks.json";
import todayEventsFixture from "@/test/fixtures/today/nba-events.json";
import todayPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn() }),
}));

const apiMocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
  getDailyPicks: vi.fn(),
  getLineups: vi.fn(),
  getWNBAEvents: vi.fn(),
  getWnbaDailyPicks: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...apiMocks };
});

const todayPicks = dailyPicksResponseSchema.parse(todayPicksFixture);
const todayEvents = eventsResponseSchema.parse(todayEventsFixture);
const emptyLineups = lineupsResponseSchema.parse(emptyLineupsFixture);
const boardPick = dailyPicksResponseSchema.parse(boardFixture).picks[0];
const [bam] = todayPicks.picks;
const heat = todayEvents.events[0];

function picksResponse(picks: DailyPick[]) {
  return { ...todayPicks, total_picks: picks.length, picks };
}

function withStatus(pick: DailyPick, status: string | null): DailyPick {
  return { ...pick, injury_status: status };
}

function jimmyPoints(): DailyPick {
  return {
    ...bam,
    player_name: "Jimmy Butler",
    metric: "points",
    threshold: 22.5,
    direction: "over",
    probability: 0.7,
    tier: "Strong play",
    combined_probability: 0.88,
    injury_status: null,
  };
}

function jimmyReboundsOut(): DailyPick {
  return {
    ...jimmyPoints(),
    metric: "rebounds",
    threshold: 6.5,
    probability: 0.91,
    tier: null,
    combined_probability: null,
    injury_status: "Out",
  };
}

const butlerTopRead = {
  player: "Jimmy Butler",
  market: "player_points",
  side: "over" as const,
  line: 22.5,
  probability: 0.88,
};

function heatWithButlerRead() {
  return eventsResponseSchema.parse({
    date: todayPicks.date,
    events: [{ ...heat, top_read: butlerTopRead }],
  }).events;
}

function readArgs(pick: DailyPick, listedOut = false) {
  return {
    player: pick.player_name,
    marketName: "Points",
    market: "player_points",
    binary: false,
    eventId: pick.event_id,
    homeTeam: pick.home_team,
    awayTeam: pick.away_team,
    commenceTime: pick.commence_time,
    team: pick.player_team_code ?? null,
    position: null,
    line: pick.threshold,
    pick,
    consensus: null,
    last10: [],
    history: null,
    league: "nba" as const,
    listedOut,
  };
}

function boardProps(overrides: Partial<DailyPicksBoardProps>): DailyPicksBoardProps {
  return {
    league: "nba",
    selectedDate: "2026-11-10",
    onDateChange: vi.fn(),
    analyzedAt: null,
    isStale: false,
    picks: [],
    isLoading: false,
    isError: false,
    errorMessage: null,
    onRetry: vi.fn(),
    onReanalyze: vi.fn(),
    isReanalyzing: false,
    emptyMessage: null,
    minProbability: 0.65,
    teams: ["MIA"],
    selectedTeams: new Set(),
    onToggleTeam: vi.fn(),
    onClearTeams: vi.fn(),
    teamFilterEmpty: false,
    lineupFor: () => null,
    showLineup: false,
    isLineupLoading: false,
    isLineupError: false,
    slipDirection: () => null,
    onToggleSlip: vi.fn(),
    ...overrides,
  };
}

describe("Today top read blocks an Out player on every line", () => {
  it("drops an API top_read when the player is Out on another market", () => {
    const events = heatWithButlerRead();
    const [game] = todayGames(events, [jimmyReboundsOut(), withStatus(bam, null)], "nba", todayPicks.date);
    expect(game.topText).toBe("Adebayo Over 10.5 REB");
    expect(game.topText).not.toContain("Butler");
    expect(game.topSource).toBe("picks");
  });

  it("drops the player's other line from tonight's reads", () => {
    const reads = todayReads(
      [jimmyPoints(), jimmyReboundsOut(), withStatus(bam, "Questionable")],
      "nba",
      todayPicks.date,
    );
    expect(reads.map((card) => card.player)).toEqual(["Bam Adebayo"]);
  });

  it("keeps a Doubtful player on the top read", () => {
    const doubtful = withStatus({ ...bam, tier: "Strong play", combined_probability: 0.724 }, "Doubtful");
    const [game] = todayGames([heat], [doubtful], "nba", todayPicks.date);
    expect(game.topText).toContain("Adebayo");
    expect(game.topSource).toBe("picks");
  });
});

describe("top read fallback when picks are missing", () => {
  it("keeps the events top_read when no injury rows were loaded", () => {
    const [game] = todayGames(heatWithButlerRead(), [], "nba", todayPicks.date);
    expect(game.topSource).toBe("event");
    expect(game.topText).toBe("Butler Over 22.5 PTS");
    expect(game.topProbabilityText).toBeNull();
  });

  it("drops that top_read when the last picks body says the player is Out on another market", () => {
    const [game] = todayGames(heatWithButlerRead(), [], "nba", todayPicks.date, [jimmyReboundsOut()]);
    expect(game.topText).toBeNull();
    expect(game.topProbabilityText).toBeNull();
    expect(game.tier).toBeNull();
    expect(game.topSource).toBe("none");
  });

  it("uses a failed refetch's last picks body and does not show the Out player", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-10T18:00:00-06:00"));
    const client = createTestQueryClient();
    const payload = picksResponse([jimmyReboundsOut()]);
    apiMocks.getEvents.mockResolvedValue({
      date: "2026-11-10",
      events: heatWithButlerRead(),
    });
    apiMocks.getDailyPicks.mockResolvedValueOnce(payload).mockRejectedValue(new Error("picks down"));

    renderWithProviders(<TodayBoard league="nba" />, { queryClient: client });

    const web = await screen.findByTestId("today-web");
    expect(within(web).getByText("No read on this game")).toBeInTheDocument();
    await client.invalidateQueries({ queryKey: ["daily-picks", "2026-11-10"] });
    expect(await within(web).findByText("Top read unavailable")).toBeInTheDocument();
    expect(within(web).queryByText(/butler/i)).not.toBeInTheDocument();
    vi.useRealTimers();
  });
});

describe("event read for a listed Out player", () => {
  it("replaces the em dash caption and hides Ask on the selected Out pick", () => {
    const model = buildOurRead(readArgs(jimmyReboundsOut()));
    expect(model.caption).toBe("Listed Out. No model read.");
    expect(model.listedOut).toBe(true);
    expect(model.primary).toBeNull();
    renderWithProviders(
      <>
        <OurRead
          league="nba"
          model={model}
          isLoading={false}
          isError={false}
          errorText={null}
          primaryInSlip={false}
          otherInSlip={false}
          onAddPrimary={vi.fn()}
          onAddOther={vi.fn()}
          onAsk={vi.fn()}
        />
        <EventActionBar
          league="nba"
          model={model}
          primaryInSlip={false}
          otherInSlip={false}
          onAddPrimary={vi.fn()}
          onAddOther={vi.fn()}
          onAsk={vi.fn()}
        />
      </>,
    );
    expect(screen.getAllByText("Listed Out. No model read.").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /ask/i })).not.toBeInTheDocument();
  });

  it("uses the same caption when a different line is selected and another line is Out", () => {
    const model = buildOurRead(readArgs(jimmyPoints(), true));
    expect(model.caption).toBe("Listed Out. No model read.");
    expect(model.primary).toBeNull();
    expect(model.tier).toBeNull();
  });
});

describe("slip average leaves an Out leg out", () => {
  const jimmy = createBetSlipPick({
    id: "Jimmy Butler-points",
    player_name: "Jimmy Butler",
    event_id: bam.event_id,
    probability: 0.7,
    combined_probability: 0.88,
    tier: "Strong play",
    metric: "points",
    threshold: 22.5,
  });
  const adebayo = createBetSlipPick({
    id: "Bam Adebayo-points",
    player_name: "Bam Adebayo",
    event_id: bam.event_id,
    probability: 0.66,
    combined_probability: 0.66,
    tier: "Playable",
    metric: "points",
    threshold: 20.5,
  });

  it("keeps the saved count and averages only the live legs", () => {
    const totals = slipTotals([jimmy, adebayo], new Set([jimmy.id]));
    expect(totals.summary.count).toBe(2);
    expect(totals.summary.averageText).toBe(formatTierPercent(0.66));
    expect(totals.summary.allHitText).toBe(formatTierPercent(0.66));
    expect(totals.basis).toBe("blend");
  });

  beforeEach(() => {
    clearBetSlip();
    apiMocks.getLineups.mockResolvedValue(emptyLineups);
    apiMocks.getDailyPicks.mockResolvedValue(
      picksResponse([jimmyReboundsOut(), withStatus(bam, "Questionable")]),
    );
  });

  afterEach(() => {
    clearBetSlip();
  });

  it("shows the Out leg with a remove control and leaves it out of the average", async () => {
    const user = userEvent.setup();
    seedBetSlip([
      { ...jimmy, commence_time: "2026-11-11T01:00:00Z" },
      { ...adebayo, player_name: "Bam Adebayo", commence_time: "2026-11-11T01:00:00Z" },
    ]);
    renderWithProviders(<BetSlipScreen />);

    const jimmyCard = (await screen.findAllByRole("article")).find((card) =>
      within(card).queryByText("Jimmy Butler"),
    );
    expect(jimmyCard).toBeDefined();
    expect(jimmyCard).toHaveTextContent("Out");
    expect(jimmyCard).not.toHaveTextContent("88%");
    expect(within(jimmyCard as HTMLElement).getByRole("button", { name: "Remove Jimmy Butler" })).toBeInTheDocument();
    expect(screen.getByText("avg. blend").previousElementSibling).toHaveTextContent("66%");

    await user.click(screen.getByRole("button", { name: "Remove Jimmy Butler" }));
    expect(screen.queryByText("Jimmy Butler")).not.toBeInTheDocument();
  });
});

describe("picks board remove control for an Out pick already in the slip", () => {
  it("shows Remove instead of add, and no Ask", async () => {
    const user = userEvent.setup();
    const out = withStatus({ ...boardPick, player_name: "Jimmy Butler" }, "out");
    const onToggleSlip = vi.fn();
    renderWithProviders(
      <DailyPicksBoard
        {...boardProps({
          picks: [out],
          slipDirection: () => out.direction,
          onToggleSlip,
        })}
      />,
    );
    const card = screen.getByRole("article");
    expect(card).toHaveTextContent("Out");
    expect(within(card).getByRole("button", { name: "Remove Jimmy Butler" })).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /ask/i })).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent("In slip");
    await user.click(within(card).getByRole("button", { name: "Remove Jimmy Butler" }));
    expect(onToggleSlip).toHaveBeenCalledWith(out);
  });

  it("shows no slip control when the Out pick is not in the slip", () => {
    const out = withStatus({ ...boardPick, player_name: "Jimmy Butler" }, "Out");
    renderWithProviders(<DailyPicksBoard {...boardProps({ picks: [out] })} />);
    expect(within(screen.getByRole("article")).queryByRole("button")).not.toBeInTheDocument();
  });
});
