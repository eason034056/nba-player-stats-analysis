import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { PlayerRail } from "@/components/event/PlayerRail";
import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { eventPlayerRows } from "@/lib/event-page";
import { dailyPickSchema, dailyPicksResponseSchema, lineupsResponseSchema, type DailyPick } from "@/lib/schemas";
import { todayReads } from "@/lib/today-board";
import { clearBetSlip, createBetSlipPick, renderWithProviders, seedBetSlip } from "@/test/test-utils";
import emptyLineupsFixture from "@/test/fixtures/lineups/empty.json";
import rawInjuryFixture from "@/test/fixtures/picks/nba-daily-picks-raw-injury.json";
import todayPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";
import wnbaPicksFixture from "@/test/fixtures/today/wnba-daily-picks.json";

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
const emptyLineups = lineupsResponseSchema.parse(emptyLineupsFixture);
const [doubtful, listedOut] = rawInjuryFixture.picks.map((pick) => dailyPickSchema.parse(pick));
const wilson = dailyPicksResponseSchema.parse(wnbaPicksFixture).picks[0];

// Tailwind is not loaded in jsdom, so read the opacity utility the user would see
// and multiply it up the tree. 1 means full strength.
function effectiveOpacity(el: Element | null): number {
  let value = 1;
  for (let node: Element | null = el; node; node = node.parentElement) {
    const match = /(?:^|\s)opacity-(\d+)(?:\s|$)/.exec(node.getAttribute("class") ?? "");
    if (match) value *= Number(match[1]) / 100;
  }
  return Math.round(value * 100) / 100;
}

function chip(scope: HTMLElement): HTMLElement {
  const found = scope.querySelector("[data-injury-tone]");
  expect(found).not.toBeNull();
  return found as HTMLElement;
}

function legFor(pick: DailyPick) {
  return createBetSlipPick({
    id: `${pick.player_name}-${pick.metric}`,
    player_name: pick.player_name,
    event_id: pick.event_id,
    player_team: pick.player_team,
    home_team: pick.home_team,
    away_team: pick.away_team,
    commence_time: pick.commence_time,
    metric: pick.metric,
    threshold: pick.threshold,
    probability: 0.7,
    combined_probability: 0.7,
    tier: "Playable",
  });
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
    minProbability: 0.5,
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

beforeEach(() => {
  clearBetSlip();
  apiMocks.getLineups.mockResolvedValue(emptyLineups);
});

afterEach(() => {
  clearBetSlip();
});

describe("Out card fade on the picks board", () => {
  it("fades the name and prop, keeps the chip and Remove at full strength, and leaves other cards alone", () => {
    renderWithProviders(
      <DailyPicksBoard
        {...boardProps({
          picks: [doubtful, listedOut],
          slipDirection: (pick) => (pick.player_name === listedOut.player_name ? pick.direction : null),
        })}
      />,
    );
    const cards = screen.getAllByRole("article");
    const outCard = cards.find((card) => card.textContent?.includes(listedOut.player_name)) as HTMLElement;
    const liveCard = cards.find((card) => card.textContent?.includes(doubtful.player_name)) as HTMLElement;

    expect(effectiveOpacity(within(outCard).getByRole("link", { name: listedOut.player_name }))).toBe(0.6);
    expect(effectiveOpacity(within(outCard).getByTestId("pick-prop").firstElementChild)).toBe(0.6);
    expect(effectiveOpacity(chip(outCard))).toBe(1);
    expect(chip(outCard)).toHaveTextContent("Out");
    expect(
      effectiveOpacity(within(outCard).getByRole("button", { name: `Remove ${listedOut.player_name}` })),
    ).toBe(1);

    expect(effectiveOpacity(within(liveCard).getByRole("link", { name: doubtful.player_name }))).toBe(1);
    expect(effectiveOpacity(chip(liveCard))).toBe(1);
  });
});

describe("Out leg fade on the slip", () => {
  it("fades the name, keeps the Out chip and Remove at full strength, and leaves a live leg alone", async () => {
    seedBetSlip([legFor(listedOut), legFor(doubtful)]);
    apiMocks.getDailyPicks.mockResolvedValue({ ...todayPicks, picks: [listedOut, doubtful] });
    renderWithProviders(<BetSlipScreen />);

    const outRemove = await screen.findByRole("button", { name: `Remove ${listedOut.player_name}` });
    const outLeg = outRemove.closest("article") as HTMLElement;
    await within(outLeg).findByText("Out");
    expect(effectiveOpacity(within(outLeg).getByText(listedOut.player_name))).toBe(0.6);
    expect(effectiveOpacity(chip(outLeg))).toBe(1);
    expect(effectiveOpacity(outRemove)).toBe(1);

    const liveLeg = screen
      .getByRole("button", { name: `Remove ${doubtful.player_name}` })
      .closest("article") as HTMLElement;
    expect(effectiveOpacity(within(liveLeg).getByText(doubtful.player_name))).toBe(1);
  });
});

describe("WNBA rows that carry injury words", () => {
  const loud: DailyPick = { ...wilson, injury_status: "Out", injury_status_raw: "Out For Season" };

  // The rail and Today gate the chip on league. The board does not (same as dev), and WNBA rows arrive with null words.
  it("show no injury chip on the rail or Today", () => {
    const rows = eventPlayerRows({
      suggested: [loud.player_name],
      picks: [loud],
      metric: "player_points",
      eventId: loud.event_id,
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "NYL",
      homeAbbr: "LVA",
      league: "wnba",
    });
    expect(rows.every((row) => row.injury == null)).toBe(true);
    renderWithProviders(
      <PlayerRail
        league="wnba"
        rows={rows}
        selected=""
        onSelect={vi.fn()}
        isLoading={false}
        isError={false}
        errorText={null}
        onRetry={vi.fn()}
      />,
    );
    const button = screen.getByRole("button", { name: new RegExp(loud.player_name) });
    expect(button).not.toHaveTextContent("Injury:");
    expect(button.querySelector("[data-injury-tone]")).toBeNull();

    expect(todayReads([{ ...wilson, injury_status_raw: "Doubtful" }], "wnba", "2026-11-10")[0]?.injury).toBeNull();
  });
});
