import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { PlayerRail } from "@/components/event/PlayerRail";
import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { buildOurRead, eventPlayerRows } from "@/lib/event-page";
import { dailyPickSchema, dailyPicksResponseSchema, lineupsResponseSchema, type DailyPick } from "@/lib/schemas";
import { todayReads } from "@/lib/today-board";
import {
  clearBetSlip,
  createBetSlipPick,
  renderWithProviders,
  seedBetSlip,
} from "@/test/test-utils";
import emptyLineupsFixture from "@/test/fixtures/lineups/empty.json";
import rawInjuryFixture from "@/test/fixtures/picks/nba-daily-picks-raw-injury.json";
import todayPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";

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

function legFor(pick: DailyPick, probability: number) {
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
    probability,
    combined_probability: probability,
    tier: "Playable",
  });
}

function shareCard(): HTMLElement {
  return screen.getByText("novig · for research only").parentElement as HTMLElement;
}

function rows(pick: DailyPick, league: "nba" | "wnba" = "nba") {
  return eventPlayerRows({
    suggested: [pick.player_name],
    picks: [pick],
    metric: "player_points",
    eventId: pick.event_id,
    selectedName: "",
    postedLine: null,
    awayLineup: null,
    homeLineup: null,
    awayAbbr: "BOS",
    homeAbbr: "MIA",
    league,
  });
}

function renderRail(pick: DailyPick, league: "nba" | "wnba" = "nba") {
  renderWithProviders(
    <PlayerRail
      league={league}
      rows={rows(pick, league)}
      selected=""
      onSelect={vi.fn()}
      isLoading={false}
      isError={false}
      errorText={null}
      onRetry={vi.fn()}
    />,
  );
  return screen.getByRole("button", { name: new RegExp(pick.player_name) });
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

function count(text: string | null | undefined, needle: string): number {
  return (text ?? "").split(needle).length - 1;
}

beforeEach(() => {
  clearBetSlip();
  apiMocks.getLineups.mockResolvedValue(emptyLineups);
});

afterEach(() => {
  clearBetSlip();
});

describe("a raw out next to a stored Questionable", () => {
  // Synthetic. The backend stores a raw "out" as Out, so this pair is not a fixture row.
  const lowerOut: DailyPick = {
    ...doubtful,
    injury_status: "Questionable",
    injury_status_raw: "out",
  };

  it("shows the raw word and the percent on the slip leg and the share card", async () => {
    seedBetSlip([legFor(lowerOut, 0.6095)]);
    apiMocks.getDailyPicks.mockResolvedValue({ ...todayPicks, picks: [lowerOut] });
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    expect(await within(card).findByText("Out")).toBeInTheDocument();
    expect(card).toHaveTextContent("60%");
    expect(within(card).getByRole("button", { name: `Remove ${lowerOut.player_name}` })).toBeInTheDocument();
    expect(screen.queryByText(/leave out Out legs/)).not.toBeInTheDocument();
    expect(shareCard()).toHaveTextContent("60%");
  });

  it("shows the raw word and the lean on the rail", () => {
    const button = renderRail(lowerOut);
    expect(button).toHaveTextContent("Out");
    expect(button).toHaveTextContent(/O 60%/);
  });
});

describe("Out For Season keeps its raw word", () => {
  const season: DailyPick = { ...listedOut, injury_status_raw: "Out For Season" };

  it("on the slip leg and the share card, with the leg left out of the average", async () => {
    seedBetSlip([legFor(season, 0.7)]);
    apiMocks.getDailyPicks.mockResolvedValue({ ...todayPicks, picks: [season] });
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    expect(await within(card).findByText("Out For Season")).toBeInTheDocument();
    expect(card).not.toHaveTextContent("70%");
    expect(await screen.findByText(/leave out Out legs/)).toBeInTheDocument();
    expect(within(shareCard()).getByText("Out For Season")).toBeInTheDocument();
    expect(shareCard()).not.toHaveTextContent("70%");
  });

  it("on the rail and the event read", () => {
    const button = renderRail(season);
    expect(button).toHaveTextContent("Out For Season");
    expect(button).not.toHaveTextContent("%");
    const model = buildOurRead({
      player: season.player_name,
      marketName: "Points",
      market: "player_points",
      binary: false,
      eventId: season.event_id,
      homeTeam: season.home_team,
      awayTeam: season.away_team,
      commenceTime: season.commence_time,
      team: season.player_team_code ?? null,
      position: null,
      line: season.threshold,
      pick: season,
      consensus: null,
      last10: [],
      history: null,
      league: "nba",
    });
    expect(model.listedOut).toBe(true);
    expect(model.injury?.text).toBe("Out For Season");
  });
});

describe("screen-reader prefix", () => {
  it("is announced once per chip on the board, the rail, and the slip", async () => {
    const view = renderWithProviders(
      <DailyPicksBoard {...boardProps({ picks: [doubtful, listedOut] })} />,
    );
    const [first, second] = screen.getAllByRole("article");
    expect(count(first.textContent, "Injury:")).toBe(1);
    expect(count(first.textContent, "Doubtful")).toBe(1);
    expect(count(second.textContent, "Injury:")).toBe(1);
    expect(count(second.textContent, "Out")).toBe(1);
    view.unmount();

    const railView = renderWithProviders(
      <PlayerRail
        league="nba"
        rows={rows(listedOut)}
        selected=""
        onSelect={vi.fn()}
        isLoading={false}
        isError={false}
        errorText={null}
        onRetry={vi.fn()}
      />,
    );
    const out = screen.getByRole("button", { name: /Injury:\s*Out/ });
    expect(count(out.textContent, "Injury:")).toBe(1);
    expect(count(out.textContent?.replace(listedOut.player_name, ""), "Out")).toBe(1);
    railView.unmount();

    seedBetSlip([legFor(doubtful, 0.6095)]);
    apiMocks.getDailyPicks.mockResolvedValue({ ...todayPicks, picks: [doubtful] });
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    await within(card).findByText("Doubtful");
    expect(count(card.textContent, "Injury:")).toBe(1);
  });
});

describe("WNBA", () => {
  it("shows no injury chip or prefix on the board, the rail, or Today", () => {
    const wnbaQuiet: DailyPick = { ...doubtful, injury_status: null, injury_status_raw: null };
    renderWithProviders(<DailyPicksBoard {...boardProps({ league: "wnba", picks: [wnbaQuiet], teams: ["LVA"] })} />);
    const card = screen.getByRole("article");
    expect(card).not.toHaveTextContent("Injury:");
    const button = renderRail(wnbaQuiet, "wnba");
    expect(button).not.toHaveTextContent("Injury:");
    expect(todayReads([wnbaQuiet], "wnba", "2026-11-10")[0]?.injury).toBeNull();
  });
});

describe("percent floor", () => {
  it("floors 0.697 to 69% on a Doubtful slip leg and its share card", async () => {
    seedBetSlip([legFor(doubtful, 0.697)]);
    apiMocks.getDailyPicks.mockResolvedValue({
      ...todayPicks,
      picks: [{ ...doubtful, combined_probability: 0.697 }],
    });
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    await within(card).findByText("Doubtful");
    expect(card).toHaveTextContent("69%");
    expect(card).not.toHaveTextContent("70%");
    expect(shareCard()).toHaveTextContent("69%");
    expect(shareCard()).not.toHaveTextContent("70%");
  });
});
