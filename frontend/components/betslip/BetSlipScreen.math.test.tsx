import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import type { BetSlipPick } from "@/contexts/BetSlipContext";
import { lineupsResponseSchema, dailyPicksResponseSchema, type DailyPick } from "@/lib/schemas";
import { clearBetSlip, renderWithProviders, seedBetSlip } from "@/test/test-utils";
import nbaLineupsFixture from "@/test/fixtures/picks/nba-lineups.json";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";

const picks = dailyPicksResponseSchema.parse(nbaPicksFixture).picks;
const lineups = lineupsResponseSchema.parse(nbaLineupsFixture);

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

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getLineups: vi.fn(async () => lineups),
  };
});

function slipPick(pick: DailyPick, probability = pick.probability): BetSlipPick {
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
    probability,
    n_games: pick.n_games,
    added_at: "2026-11-10T18:00:00.000Z",
  };
}

describe("BetSlipScreen stored-rate math", () => {
  beforeEach(() => {
    clearBetSlip();
  });

  it("recomputes the product after a leg is removed", async () => {
    const user = userEvent.setup();
    const [bam, , hali] = picks;
    seedBetSlip([slipPick(bam), slipPick(hali)]);

    renderWithProviders(<BetSlipScreen />);

    expect(await screen.findByText("49%")).toBeInTheDocument();
    expect(screen.getByText("70%")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove Tyrese Haliburton" }));

    expect(screen.queryByText("49%")).not.toBeInTheDocument();
    expect(screen.queryByText("Tyrese Haliburton")).not.toBeInTheDocument();
    expect(screen.getAllByText("72%").length).toBeGreaterThan(0);
    expect(screen.queryByText("70%")).not.toBeInTheDocument();
    const summary = screen.getByText("avg. probability").parentElement;
    expect(summary).not.toBeNull();
    if (!summary) return;
    expect(within(summary.parentElement as HTMLElement).getByText("1")).toBeInTheDocument();
  });

  it("floors a stored 0.6755 total to 67%", async () => {
    seedBetSlip([slipPick(picks[0], 0.6755)]);

    renderWithProviders(<BetSlipScreen />);

    const summary = (await screen.findByText("avg. probability")).parentElement?.parentElement;
    expect(summary).not.toBeNull();
    expect(within(summary as HTMLElement).getAllByText("67%")).toHaveLength(2);
    expect(within(summary as HTMLElement).queryByText("68%")).not.toBeInTheDocument();
    expect(screen.queryByText(/NaN|Infinity/)).not.toBeInTheDocument();
  });

  it("dashes the summary when the slip is empty after the last leg is removed", async () => {
    const user = userEvent.setup();
    seedBetSlip([slipPick(picks[0])]);
    renderWithProviders(<BetSlipScreen />);

    expect((await screen.findAllByText("72%")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Remove Bam Adebayo" }));

    expect(screen.getByRole("heading", { name: /nothing saved yet/i })).toBeInTheDocument();
    expect(screen.queryByText("72%")).not.toBeInTheDocument();
    expect(screen.queryByText("all hit")).not.toBeInTheDocument();
  });
});
