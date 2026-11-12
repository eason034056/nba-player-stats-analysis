import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { slipTotals } from "@/lib/bet-slip-board";
import { isPlayerOutInGame } from "@/lib/picks-board";
import {
  dailyPicksResponseSchema,
  eventsResponseSchema,
  lineupsResponseSchema,
  type DailyPick,
} from "@/lib/schemas";
import { todayGames, todayReads } from "@/lib/today-board";
import { getLocalDateString } from "@/lib/utils";
import {
  clearBetSlip,
  createBetSlipPick,
  createTestQueryClient,
  renderWithProviders,
  seedBetSlip,
} from "@/test/test-utils";
import boardFixture from "@/test/fixtures/picks/nba-daily-picks.json";
import todayPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";
import todayEventsFixture from "@/test/fixtures/today/nba-events.json";
import emptyLineupsFixture from "@/test/fixtures/lineups/empty.json";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/betslip",
  useRouter: () => ({ push: vi.fn() }),
}));

const apiMocks = vi.hoisted(() => ({
  getDailyPicks: vi.fn(),
  getLineups: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...apiMocks };
});

const todayPicks = dailyPicksResponseSchema.parse(todayPicksFixture);
const todayEvents = eventsResponseSchema.parse(todayEventsFixture);
const emptyLineups = lineupsResponseSchema.parse(emptyLineupsFixture);
const boardPick = dailyPicksResponseSchema.parse(boardFixture).picks[0];
const [bam, embiid] = todayPicks.picks;
const heat = todayEvents.events.find((event) => event.event_id === bam.event_id)!;
const sixers = todayEvents.events.find((event) => event.event_id === embiid.event_id)!;

function outRow(pick: DailyPick, overrides: Partial<DailyPick> = {}): DailyPick {
  return { ...pick, tier: null, combined_probability: null, injury_status: "Out", ...overrides };
}

function picksBody(picks: DailyPick[]) {
  return { ...todayPicks, total_picks: picks.length, picks };
}

function leg(pick: DailyPick, overrides: Parameters<typeof createBetSlipPick>[0] = {}) {
  return createBetSlipPick({
    id: `${pick.player_name}-${pick.metric}`,
    player_name: pick.player_name,
    player_team: pick.player_team,
    event_id: pick.event_id,
    home_team: pick.home_team,
    away_team: pick.away_team,
    commence_time: pick.commence_time,
    metric: pick.metric,
    threshold: pick.threshold,
    direction: pick.direction,
    probability: pick.probability,
    combined_probability: pick.combined_probability ?? null,
    tier: pick.tier ?? null,
    ...overrides,
  });
}

function summaryValue(label: string): string {
  return screen.getByText(label).previousElementSibling?.textContent ?? "";
}

describe("isPlayerOutInGame keys on game and player", () => {
  const out = outRow(bam);

  it("matches the same player in the same game on any market, ignoring case and space", () => {
    expect(isPlayerOutInGame([out], bam.event_id, "Bam Adebayo")).toBe(true);
    expect(isPlayerOutInGame([out], ` ${bam.event_id} `, "  bam adebayo ")).toBe(true);
  });

  it("does not block a same-name player in another game, a different player, or blank input", () => {
    expect(isPlayerOutInGame([out], embiid.event_id, "Bam Adebayo")).toBe(false);
    expect(isPlayerOutInGame([out], bam.event_id, "Bam Adebayo Jr.")).toBe(false);
    expect(isPlayerOutInGame([out], "", "Bam Adebayo")).toBe(false);
    expect(isPlayerOutInGame([out], bam.event_id, "  ")).toBe(false);
  });

  it("is not set by Doubtful, Questionable, or a null status", () => {
    for (const status of ["Doubtful", "Questionable", null]) {
      expect(isPlayerOutInGame([{ ...bam, injury_status: status }], bam.event_id, bam.player_name)).toBe(false);
    }
  });
});

describe("Today keeps a same-name player in another game", () => {
  it("shows the other game's top read and pick when the Out row is in a different game", () => {
    const outHere = outRow(bam);
    const elsewhere = { ...embiid, player_name: "Bam Adebayo" };
    const events = eventsResponseSchema.parse({
      date: todayPicks.date,
      events: [
        { ...heat, top_read: { player: "Bam Adebayo", market: "player_points", side: "over", line: 14.5, probability: 0.7 } },
        { ...sixers, top_read: { player: "Bam Adebayo", market: "player_points", side: "over", line: 29.5, probability: 0.7 } },
      ],
    }).events;

    const games = todayGames(events, [outHere], "nba", todayPicks.date);
    expect(games.find((game) => game.eventId === heat.event_id)?.topText ?? null).toBeNull();
    expect(games.find((game) => game.eventId === sixers.event_id)?.topText).toBe("Adebayo Over 29.5 PTS");

    const reads = todayReads([outHere, elsewhere], "nba", todayPicks.date);
    expect(reads.map((card) => card.player)).toEqual(["Bam Adebayo"]);
    expect(reads[0]?.href).toContain(embiid.event_id);
  });
});

describe("slip totals with Out legs", () => {
  const live = leg(embiid, { combined_probability: 0.695, probability: 0.695, tier: "Playable" });
  const live2 = leg({ ...embiid, player_name: "Tyrese Maxey" }, { combined_probability: 0.699, probability: 0.699, tier: "Playable" });
  const out = leg(bam, { combined_probability: 0.95, probability: 0.95 });

  it("floors the recomputed average and all-hit over the live legs only", () => {
    const totals = slipTotals([out, live, live2], new Set([out.id]));
    expect(totals.basis).toBe("blend");
    expect(totals.summary.count).toBe(3);
    expect(totals.summary.averageText).toBe("69%");
    expect(totals.summary.allHitText).toBe("48%");
  });

  it("prints a dash, not NaN or 0%, when every leg is Out", () => {
    const totals = slipTotals([out], new Set([out.id]));
    expect(totals.summary.count).toBe(1);
    expect(totals.summary.averageText).toBe("—");
    expect(totals.summary.allHitText).toBe("—");
  });

  it("matches the old totals when no leg is Out", () => {
    expect(slipTotals([live, live2], new Set())).toEqual(slipTotals([live, live2]));
  });
});

describe("BetSlipScreen Out lookup", () => {
  beforeEach(() => {
    clearBetSlip();
    apiMocks.getDailyPicks.mockReset();
    apiMocks.getLineups.mockReset();
    apiMocks.getLineups.mockResolvedValue(emptyLineups);
  });

  afterEach(() => {
    clearBetSlip();
  });

  it("asks for each leg's local commence date, once per date", async () => {
    const other = { ...embiid, commence_time: "2026-11-14T00:30:00Z", event_id: "later-game" };
    seedBetSlip([leg(bam), leg(embiid), leg(other)]);
    apiMocks.getDailyPicks.mockResolvedValue(picksBody([]));

    renderWithProviders(<BetSlipScreen />);

    await waitFor(() => expect(apiMocks.getDailyPicks).toHaveBeenCalledTimes(2));
    const dates = apiMocks.getDailyPicks.mock.calls.map(([request]) => request?.date).sort();
    expect(dates).toEqual(
      [getLocalDateString(bam.commence_time), getLocalDateString(other.commence_time)].sort(),
    );
  });

  it("reuses the board's cached ['daily-picks', date] body without a new request", async () => {
    const client = createTestQueryClient();
    const date = getLocalDateString(bam.commence_time)!;
    client.setQueryData(["daily-picks", date], picksBody([outRow(bam, { metric: "points", threshold: 14.5 })]));
    seedBetSlip([leg(bam), leg(embiid)]);

    renderWithProviders(<BetSlipScreen />, { queryClient: client });

    const card = (await screen.findAllByRole("article")).find((item) => within(item).queryByText("Bam Adebayo"))!;
    expect(card).toHaveTextContent("Out");
    expect(within(card).getByRole("button", { name: "Remove Bam Adebayo" })).toHaveTextContent("Remove");
    expect(apiMocks.getDailyPicks).not.toHaveBeenCalled();
    expect(summaryValue("avg. blend")).toBe("70%");
  });

  it("keeps a leg normal when the picks request fails", async () => {
    seedBetSlip([leg(bam), leg(embiid)]);
    apiMocks.getDailyPicks.mockRejectedValue(new Error("picks down"));

    renderWithProviders(<BetSlipScreen />);

    await waitFor(() => expect(apiMocks.getDailyPicks).toHaveBeenCalled());
    const cards = await screen.findAllByRole("article");
    expect(cards).toHaveLength(2);
    for (const card of cards) expect(card).not.toHaveTextContent(/\bOut\b/);
    expect(summaryValue("avg. blend")).toBe("71%");
  });

  it("does not mark a leg Out when the Out row is the same name in another game", async () => {
    seedBetSlip([leg(bam)]);
    apiMocks.getDailyPicks.mockResolvedValue(picksBody([outRow(bam, { event_id: embiid.event_id })]));

    renderWithProviders(<BetSlipScreen />);

    await waitFor(() => expect(apiMocks.getDailyPicks).toHaveBeenCalled());
    const card = await screen.findByRole("article");
    expect(card).not.toHaveTextContent(/\bOut\b/);
    expect(card).toHaveTextContent("72%");
  });

  it("labels the Out leg on the share card and leaves stored legs unchanged", async () => {
    seedBetSlip([leg(bam), leg(embiid)]);
    const before = window.localStorage.getItem("betslip_picks");
    apiMocks.getDailyPicks.mockResolvedValue(picksBody([outRow(bam)]));

    renderWithProviders(<BetSlipScreen />);

    const share = (await screen.findByText("novig · for research only")).parentElement!;
    await waitFor(() => expect(within(share).getByText("Out")).toBeInTheDocument());
    expect(share).toHaveTextContent("Joel Embiid");
    expect(share).toHaveTextContent("70%");
    expect(share).not.toHaveTextContent("72%");
    expect(JSON.parse(window.localStorage.getItem("betslip_picks") ?? "[]")).toEqual(JSON.parse(before ?? "[]"));
  });

  it("shows the empty slip after the last Out leg is removed", async () => {
    const user = userEvent.setup();
    seedBetSlip([leg(bam)]);
    apiMocks.getDailyPicks.mockResolvedValue(picksBody([outRow(bam)]));

    renderWithProviders(<BetSlipScreen />);

    const remove = await screen.findByRole("button", { name: "Remove Bam Adebayo" });
    await waitFor(() => expect(remove).toHaveTextContent("Remove"));
    expect(summaryValue("avg. probability")).toBe("—");
    expect(summaryValue("all hit")).toBe("—");
    await user.click(remove);
    expect(await screen.findByText("Nothing saved yet")).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem("betslip_picks") ?? "[]")).toEqual([]);
  });
});

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

describe("board Remove on an Out card already in the slip", () => {
  it("is the card's only control, and sends that pick to the slip toggle", async () => {
    const user = userEvent.setup();
    const out = { ...boardPick, player_name: "Jimmy Butler", injury_status: "OUT" };
    const onToggleSlip = vi.fn();
    renderWithProviders(
      <DailyPicksBoard
        {...boardProps({ picks: [out], slipDirection: () => out.direction, onToggleSlip })}
      />,
    );

    const card = screen.getByRole("article");
    const buttons = within(card).getAllByRole("button");
    expect(buttons.map((button) => button.getAttribute("aria-label"))).toEqual(["Remove Jimmy Butler"]);
    await user.click(buttons[0]);
    expect(onToggleSlip).toHaveBeenCalledTimes(1);
    expect(onToggleSlip.mock.calls[0][0]).toMatchObject({ player_name: "Jimmy Butler", metric: out.metric });
  });
});
