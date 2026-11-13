import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { PlayerRail } from "@/components/event/PlayerRail";
import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { eventPlayerRows } from "@/lib/event-page";
import { injuryTagForPlayer, isOutPick, isPlayerOutInGame } from "@/lib/picks-board";
import { dailyPicksResponseSchema, lineupsResponseSchema, type DailyPick } from "@/lib/schemas";
import { todayReads } from "@/lib/today-board";
import {
  clearBetSlip,
  createBetSlipPick,
  renderWithProviders,
  seedBetSlip,
} from "@/test/test-utils";
import emptyLineupsFixture from "@/test/fixtures/lineups/empty.json";
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
const bam = todayPicks.picks[0];

// The backend stores any word containing "Out" as Out and keeps the source word raw.
// A word without a capital "Out" is stored as Questionable, so the raw word and the
// stored status can disagree. Blocking must follow injury_status only.
function withWords(pick: DailyPick, status: string | null, raw: string | null): DailyPick {
  return { ...pick, tier: null, injury_status: status, injury_status_raw: raw };
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

function railRows(pick: DailyPick) {
  return eventPlayerRows({
    suggested: [pick.player_name],
    picks: [pick],
    metric: "player_rebounds",
    eventId: pick.event_id,
    selectedName: "",
    postedLine: null,
    awayLineup: null,
    homeLineup: null,
    awayAbbr: "MIL",
    homeAbbr: "MIA",
    league: "nba",
  });
}

const slipLeg = createBetSlipPick({
  id: "Bam Adebayo-rebounds",
  player_name: "Bam Adebayo",
  event_id: bam.event_id,
  player_team: bam.player_team,
  home_team: bam.home_team,
  away_team: bam.away_team,
  commence_time: bam.commence_time,
  metric: "rebounds",
  threshold: 10.5,
  probability: 0.6095,
  combined_probability: 0.6095,
  tier: "Playable",
});

function shareCard(): HTMLElement {
  const footer = screen.getByText("novig · for research only");
  return footer.parentElement as HTMLElement;
}

describe("a raw Out word on a pick the backend did not store as Out", () => {
  const disagree = withWords({ ...bam, combined_probability: 0.6095 }, "Questionable", "out");

  it("does not block the pick", () => {
    expect(isOutPick(disagree)).toBe(false);
    expect(isPlayerOutInGame([disagree], disagree.event_id, disagree.player_name)).toBe(false);
  });

  it("keeps the percent on the share card, like the slip card above it", async () => {
    clearBetSlip();
    apiMocks.getLineups.mockResolvedValue(emptyLineups);
    apiMocks.getDailyPicks.mockResolvedValue({ ...todayPicks, picks: [disagree] });
    seedBetSlip([slipLeg]);
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    expect(card).toHaveTextContent("60%");
    expect(screen.queryByText(/leave out Out legs/)).not.toBeInTheDocument();
    expect(within(shareCard()).getByText(/60%/)).toBeInTheDocument();
    clearBetSlip();
  });

  it("keeps the lean on the event rail", () => {
    const rows = railRows(disagree);
    expect(rows[0].hasLean).toBe(true);
    renderWithProviders(
      <PlayerRail
        league="nba"
        rows={rows}
        selected=""
        onSelect={vi.fn()}
        isLoading={false}
        isError={false}
        errorText={null}
        onRetry={vi.fn()}
      />,
    );
    const button = screen.getByRole("button", { name: /Bam Adebayo/ });
    expect(button).toHaveTextContent(rows[0].leanText);
  });
});

describe("Out For Season, stored as Out", () => {
  const season = withWords({ ...bam, combined_probability: null }, "Out", "Out For Season");

  it("blocks the pick and shows the BDL word on the board", () => {
    expect(isOutPick(season)).toBe(true);
    renderWithProviders(<DailyPicksBoard {...boardProps({ picks: [season] })} />);
    const card = screen.getByRole("article");
    expect(within(card).getByText("Out For Season")).toBeInTheDocument();
    expect(card).not.toHaveTextContent("%");
    expect(within(card).queryByRole("button", { name: /ask agent about/i })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Add to Bet Slip" })).not.toBeInTheDocument();
  });

  it("leaves the leg out of the slip average", async () => {
    clearBetSlip();
    apiMocks.getLineups.mockResolvedValue(emptyLineups);
    apiMocks.getDailyPicks.mockResolvedValue({ ...todayPicks, picks: [season] });
    seedBetSlip([slipLeg]);
    renderWithProviders(<BetSlipScreen />);
    expect(await screen.findByText(/Avg and all hit leave out Out legs/)).toBeInTheDocument();
    const card = await screen.findByRole("article");
    expect(card).not.toHaveTextContent("60%");
    clearBetSlip();
  });
});

describe("one player with several rows in a game", () => {
  it("lets an Out row win over a Doubtful row, and Doubtful win over Questionable", () => {
    const doubtful = withWords(bam, "Questionable", "Doubtful");
    const questionable = withWords({ ...bam, metric: "assists" }, "Questionable", "Questionable");
    const out = withWords({ ...bam, metric: "points" }, "Out", "Out");
    expect(injuryTagForPlayer([questionable, doubtful], bam.event_id, bam.player_name)?.text).toBe("Doubtful");
    expect(isPlayerOutInGame([questionable, doubtful], bam.event_id, bam.player_name)).toBe(false);
    expect(injuryTagForPlayer([doubtful, out], bam.event_id, ` ${bam.player_name.toUpperCase()} `)?.text).toBe("Out");
    expect(isPlayerOutInGame([doubtful, out], bam.event_id, bam.player_name)).toBe(true);
    expect(injuryTagForPlayer([doubtful], "other-event", bam.player_name)).toBeNull();
  });
});

describe("Doubtful percent still floors", () => {
  it("shows 69% for 0.697 on the board and on Today", () => {
    const doubtful = withWords({ ...bam, combined_probability: 0.697 }, "Questionable", "Doubtful");
    renderWithProviders(<DailyPicksBoard {...boardProps({ picks: [doubtful], minProbability: 0.5 })} />);
    const card = screen.getByRole("article");
    expect(card).toHaveTextContent("69%");
    expect(card).not.toHaveTextContent("70%");
    expect(within(card).getByText("Doubtful")).toBeInTheDocument();
    expect(todayReads([doubtful], "nba", "2026-11-10")[0]?.probabilityText).toBe("69%");
  });
});

beforeEach(() => {
  apiMocks.getLineups.mockResolvedValue(emptyLineups);
});

afterEach(() => {
  clearBetSlip();
});
