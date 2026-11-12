import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlayerRail } from "@/components/event/PlayerRail";
import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { slipTotals } from "@/lib/bet-slip-board";
import { eventPlayerRows } from "@/lib/event-page";
import { metricToMarket } from "@/lib/metric-to-market";
import { buildPickRows, injuryTagForPlayer, isOutPick, isPlayerOutInGame } from "@/lib/picks-board";
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

function picksBody(picks: DailyPick[]) {
  return { ...todayPicks, total_picks: picks.length, picks };
}

function rawOutPick(): DailyPick {
  return {
    ...bam,
    injury_status: "Questionable",
    injury_status_raw: "out",
    combined_probability: 0.6095,
    tier: null,
  };
}

function seasonPick(): DailyPick {
  return {
    ...bam,
    injury_status: "Out",
    injury_status_raw: "Out For Season",
    combined_probability: null,
    tier: null,
  };
}

function leg(pick: DailyPick) {
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
    n_games: pick.n_games,
  });
}

function shareCard(): HTMLElement {
  const title = screen.getByText("My NBA Picks");
  const card = title.parentElement?.parentElement;
  if (!card) throw new Error("missing share card");
  return card;
}

describe("a lowercase raw out is not a stored Out", () => {
  const pick = rawOutPick();

  beforeEach(() => {
    clearBetSlip();
    apiMocks.getLineups.mockResolvedValue(emptyLineups);
  });

  afterEach(() => {
    clearBetSlip();
  });

  it("does not block the pick", () => {
    expect(isOutPick(pick)).toBe(false);
    expect(isPlayerOutInGame([pick], pick.event_id, pick.player_name)).toBe(false);
  });

  it("keeps the percent on the share card, like the slip card above it", async () => {
    seedBetSlip([leg(pick)]);
    apiMocks.getDailyPicks.mockResolvedValue(picksBody([pick]));
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    expect(card).toHaveTextContent("60%");
    expect(within(card).getByText("Out")).toBeInTheDocument();
    expect(await screen.findByText("My NBA Picks")).toBeInTheDocument();
    await waitFor(() => expect(apiMocks.getDailyPicks).toHaveBeenCalled());
    const share = shareCard();
    expect(share).toHaveTextContent("60%");
    expect(within(share).getByText("Out")).toBeInTheDocument();
    expect(screen.queryByText(/leave out Out legs/)).not.toBeInTheDocument();
  });

  it("keeps the lean on the event rail", () => {
    const [row] = eventPlayerRows({
      suggested: [pick.player_name],
      picks: [pick],
      metric: metricToMarket(pick.metric),
      eventId: pick.event_id,
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "MIL",
      homeAbbr: "MIA",
      league: "nba",
    });
    expect(row.listedOut).toBe(false);
    expect(row.hasLean).toBe(true);
    expect(row.probability).toBe(0.6095);
    expect(row.leanText).toBe("O 60%");
    expect(row.injury).toEqual({ text: "Out", tone: "out" });
    renderWithProviders(
      <PlayerRail
        league="nba"
        rows={[row]}
        selected=""
        onSelect={vi.fn()}
        isLoading={false}
        isError={false}
        errorText={null}
        onRetry={vi.fn()}
      />,
    );
    const button = screen.getByRole("button", { name: /Bam Adebayo/ });
    expect(button).toHaveTextContent("O 60%");
    expect(within(button).getByText("Out")).toBeInTheDocument();
  });
});

describe("Out For Season stays excluded and keeps its raw word", () => {
  const pick = seasonPick();

  beforeEach(() => {
    clearBetSlip();
    apiMocks.getLineups.mockResolvedValue(emptyLineups);
  });

  afterEach(() => {
    clearBetSlip();
  });

  it("blocks the board row and shows the original word", () => {
    expect(isOutPick(pick)).toBe(true);
    const [row] = buildPickRows([pick], "nba", "2026-11-10");
    expect(row.dimmed).toBe(true);
    expect(row.probabilityText).toBe("");
    expect(row.tags.map((tag) => tag.text)).toContain("Out For Season");
  });

  it("leaves the leg out of the slip average", async () => {
    const saved = leg(pick);
    const totals = slipTotals([saved], new Set([saved.id]));
    expect(totals.summary.count).toBe(1);
    expect(totals.summary.averageText).toBe("—");
    seedBetSlip([saved]);
    apiMocks.getDailyPicks.mockResolvedValue(picksBody([pick]));
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    expect(within(card).getByText("Out For Season")).toBeInTheDocument();
    expect(card).not.toHaveTextContent("%");
    expect(await screen.findByText(/leave out Out legs/)).toBeInTheDocument();
  });
});

describe("one player with several rows", () => {
  it("lets a stored Out beat Doubtful, and Doubtful beat Questionable", () => {
    const out = { ...bam, injury_status: "Out", injury_status_raw: " OUT " };
    const doubtful = {
      ...bam,
      metric: "points",
      injury_status: "Questionable",
      injury_status_raw: "doubtful",
    };
    const questionable = {
      ...bam,
      metric: "assists",
      injury_status: "Questionable",
      injury_status_raw: "Questionable",
    };
    expect(injuryTagForPlayer([doubtful, out], bam.event_id, "  bam adebayo  ")).toEqual({
      text: "Out",
      tone: "out",
    });
    expect(injuryTagForPlayer([questionable, doubtful], ` ${bam.event_id} `, bam.player_name)).toEqual({
      text: "Doubtful",
      tone: "doubtful",
    });
    expect(
      injuryTagForPlayer([{ ...bam, ...{ injury_status: "Out", injury_status_raw: "Out For Season" } }], bam.event_id, bam.player_name),
    ).toEqual({ text: "Out For Season", tone: "neutral" });
  });
});

describe("Doubtful percent", () => {
  it("floors a 0.697 blend to 69% on the board and on Today", () => {
    const pick: DailyPick = {
      ...bam,
      injury_status: "Questionable",
      injury_status_raw: "Doubtful",
      combined_probability: 0.697,
      tier: "Playable",
    };
    expect(isOutPick(pick)).toBe(false);
    expect(buildPickRows([pick], "nba", "2026-11-10")[0]?.probabilityText).toBe("69%");
    expect(todayReads([pick], "nba", "2026-11-10")[0]?.probabilityText).toBe("69%");
  });
});
