import type { ReactNode } from "react";
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { complementHitRateLabel } from "@/lib/bet-slip-board";
import { dailyPicksResponseSchema, lineupsResponseSchema } from "@/lib/schemas";
import { clearBetSlip, createBetSlipPick, renderWithProviders, seedBetSlip } from "@/test/test-utils";
import nbaLineupsFixture from "@/test/fixtures/picks/nba-lineups.json";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";

const picks = dailyPicksResponseSchema.parse(nbaPicksFixture);
const lineups = lineupsResponseSchema.parse(nbaLineupsFixture);
const bam = picks.picks[0];
const caption = "Under hit rate 28% (1 − Over 72%)";

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
  usePathname: () => "/picks",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getLineups: vi.fn(async () => lineups),
  };
});

function boardProps(overrides: Partial<DailyPicksBoardProps> = {}): DailyPicksBoardProps {
  return {
    league: "nba",
    selectedDate: "2026-11-10",
    onDateChange: vi.fn(),
    analyzedAt: picks.analyzed_at,
    isStale: false,
    picks: picks.picks,
    isLoading: false,
    isError: false,
    errorMessage: null,
    onRetry: vi.fn(),
    onReanalyze: vi.fn(),
    isReanalyzing: false,
    emptyMessage: null,
    minProbability: 0.65,
    teams: [],
    selectedTeams: new Set(),
    onToggleTeam: vi.fn(),
    onClearTeams: vi.fn(),
    teamFilterEmpty: false,
    showLineup: false,
    isLineupLoading: false,
    isLineupError: false,
    slipDirection: () => "under",
    onToggleSlip: vi.fn(),
    ...overrides,
  };
}

describe("complement hit-rate label", () => {
  beforeEach(() => {
    clearBetSlip();
  });

  it("names a reverse add as 1 minus the other side's hit rate", () => {
    expect(
      complementHitRateLabel({ direction: "under", probability: 0.28, rate_basis: "complement" }),
    ).toBe(caption);
    expect(
      complementHitRateLabel({ direction: "under", probability: 0.28 }),
    ).toBeNull();
    expect(
      complementHitRateLabel({ direction: "under", probability: 0.6755, rate_basis: "complement" }),
    ).toBe("Under hit rate 67% (1 − Over 32%)");
  });

  it("shows the caption on the slip and keeps avg and all-hit as stored hit rates", async () => {
    seedBetSlip([
      createBetSlipPick({
        id: "Bam Adebayo-points",
        player_name: "Bam Adebayo",
        player_team: "Heat",
        metric: "points",
        threshold: 18.5,
        direction: "under",
        probability: 1 - bam.probability,
        rate_basis: "complement",
      }),
    ]);

    renderWithProviders(<BetSlipScreen />);

    expect((await screen.findAllByText(caption)).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Under 18.5 points").length).toBeGreaterThan(0);
    expect(screen.getByText("avg. probability")).toBeInTheDocument();
    expect(screen.getByText("all hit")).toBeInTheDocument();
    expect(screen.getByText(/avg and all hit use the stored hit rates/i)).toBeInTheDocument();
    expect(screen.getByText(/not a de-vigged price/i)).toBeInTheDocument();
  });

  it("shows the same caption on the picks card for a reverse-added leg", () => {
    renderWithProviders(
      <DailyPicksBoard
        {...boardProps({
          slipCaption: (pick) =>
            pick.player_name === bam.player_name ? caption : null,
        })}
      />,
    );

    expect(screen.getByText(caption)).toBeInTheDocument();
    expect(screen.getByText("Over 18.5 points")).toBeInTheDocument();
  });
});
