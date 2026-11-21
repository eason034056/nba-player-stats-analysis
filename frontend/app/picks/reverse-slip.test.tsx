import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PicksPage from "@/app/picks/page";
import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { formatPercent } from "@/lib/player-dd";
import { dailyPicksResponseSchema, lineupsResponseSchema } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import nbaLineupsFixture from "@/test/fixtures/picks/nba-lineups.json";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";

const NBA_KEY = "betslip_picks";
const RETIRED_SLIP_KEY = "wnba_betslip_picks";

const nba = dailyPicksResponseSchema.parse(nbaPicksFixture);
const lineups = lineupsResponseSchema.parse(nbaLineupsFixture);

const apiMocks = vi.hoisted(() => ({
  getDailyPicks: vi.fn(),
  getLineups: vi.fn(),
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
  usePathname: () => "/picks",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getDailyPicks: (...args: unknown[]) => apiMocks.getDailyPicks(...args),
    getLineups: (...args: unknown[]) => apiMocks.getLineups(...args),
    triggerDailyAnalysis: vi.fn(),
  };
});

function stored(
  key: string,
): Array<{ player_name?: string; direction?: string; probability?: number; rate_basis?: string }> {
  const raw = window.localStorage.getItem(key);
  return raw ? (JSON.parse(raw) as Array<{ player_name?: string; direction?: string; probability?: number }>) : [];
}

describe("reverse slip and league storage keys", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    apiMocks.getDailyPicks.mockResolvedValue(nba);
    apiMocks.getLineups.mockResolvedValue(lineups);
    window.localStorage.setItem(RETIRED_SLIP_KEY, "{not-json");
  });

  it("stores 1 minus the hit rate for the other side and shows that percent", async () => {
    const user = userEvent.setup();
    const bam = nba.picks[0];
    renderWithProviders(
      <>
        <PicksPage />
        <BetSlipScreen />
      </>,
    );

    const card = (await screen.findByRole("link", { name: "Bam Adebayo" })).closest("article");
    expect(card).not.toBeNull();
    if (!card) return;
    expect(within(card).getAllByRole("button").map((button) => button.textContent)).toEqual(["+ Slip"]);
    await user.pointer([{ keys: "[MouseRight]", target: card }]);
    await user.click(await screen.findByRole("button", { name: /Bet Reverse: Under 18\.5/ }));

    const shown = formatPercent(1 - bam.probability);
    expect(shown).toBe("28%");
    expect((await screen.findAllByText("Under 18.5 points")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(shown).length).toBeGreaterThan(0);
    expect(screen.queryByText("Pass")).not.toBeInTheDocument();

    await waitFor(() => {
      const legs = stored(NBA_KEY);
      expect(legs).toHaveLength(1);
      expect(legs[0]?.player_name).toBe("Bam Adebayo");
      expect(legs[0]?.direction).toBe("under");
      expect(legs[0]?.probability).toBe(1 - bam.probability);
      expect(legs[0]?.rate_basis).toBe("complement");
    });
    expect(window.localStorage.getItem(RETIRED_SLIP_KEY)).toBeNull();
    expect(window.localStorage.getItem("nba_betslip_picks")).toBeNull();
  });

  it("keeps the posted side's stored rate when the reverse control is not used", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PicksPage />);

    const card = (await screen.findByText("Joel Embiid")).closest("article");
    expect(card).not.toBeNull();
    if (!card) return;
    await user.click(within(card).getByRole("button", { name: "Add to Bet Slip" }));

    await waitFor(() => {
      const legs = stored(NBA_KEY);
      expect(legs[0]?.player_name).toBe("Joel Embiid");
      expect(legs[0]?.direction).toBe("over");
      expect(legs[0]?.probability).toBe(0.702);
    });
    expect(window.localStorage.getItem(RETIRED_SLIP_KEY)).toBeNull();
  });

});
