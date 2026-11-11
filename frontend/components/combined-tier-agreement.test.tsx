import type { ReactNode } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import type { BetSlipPick } from "@/contexts/BetSlipContext";
import { dailyPickSchema, lineupsResponseSchema, type DailyPick } from "@/lib/schemas";
import { clearBetSlip, renderWithProviders, seedBetSlip } from "@/test/test-utils";
import combinedFixture from "@/test/fixtures/spo-121b/combined-tier.json";
import nbaLineupsFixture from "@/test/fixtures/picks/nba-lineups.json";

const lineups = lineupsResponseSchema.parse(nbaLineupsFixture);
const sameCard = dailyPickSchema.parse(combinedFixture.sameCard);
const thybulle = dailyPickSchema.parse(combinedFixture.thybulle);
const lowBlend = dailyPickSchema.parse({
  ...combinedFixture.nullCombined,
  player_name: "Jrue Holiday",
  probability: 0.9,
  combined_probability: 0.5,
  tier: "Lean",
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/picks",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getLineups: vi.fn(async () => lineups),
  };
});

function boardProps(picks: DailyPick[]): DailyPicksBoardProps {
  return {
    league: "nba",
    selectedDate: "2026-11-10",
    onDateChange: vi.fn(),
    analyzedAt: "2026-11-10T18:00:00Z",
    isStale: false,
    picks,
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
    slipDirection: () => null,
    onToggleSlip: vi.fn(),
  };
}

function slipPick(pick: DailyPick): BetSlipPick {
  return {
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
    n_games: pick.n_games,
    added_at: "2026-11-10T18:00:00.000Z",
    tier: pick.tier,
    combined_probability: pick.combined_probability,
  };
}

describe("Picks and the Bet Slip agree", () => {
  beforeEach(() => {
    clearBetSlip();
  });

  it("prints 69% Playable for the same 0.697 pick on both surfaces", async () => {
    seedBetSlip([slipPick(sameCard)]);
    renderWithProviders(
      <>
        <DailyPicksBoard {...boardProps([sameCard])} />
        <BetSlipScreen />
      </>,
    );

    expect(await screen.findAllByText("69%")).toHaveLength(3);
    expect(screen.getAllByText("Playable").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("59% Lean")).not.toBeInTheDocument();
    expect(screen.getByText("avg. blend")).toBeInTheDocument();
    expect(screen.getAllByText("70%")).toHaveLength(2);
  });

  it("keeps a 0.73 blend on the Strong chip when the historical rate is 0.40", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DailyPicksBoard {...boardProps([thybulle, lowBlend])} />);

    expect(screen.getByText("Matisse Thybulle")).toBeInTheDocument();
    expect(screen.getByText("73%")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Strong ≥70%" }));
    expect(screen.getByText("Matisse Thybulle")).toBeInTheDocument();
    expect(screen.queryByText("Jrue Holiday")).not.toBeInTheDocument();
  });
});
