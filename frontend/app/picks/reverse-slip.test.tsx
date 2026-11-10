import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PicksPage from "@/app/picks/page";
import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { useWnbaBetSlip } from "@/contexts/WnbaBetSlipContext";
import { formatPercent } from "@/lib/player-dd";
import { dailyPicksResponseSchema, lineupsResponseSchema, type DailyPick } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import nbaLineupsFixture from "@/test/fixtures/picks/nba-lineups.json";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";
import wnbaPicksFixture from "@/test/fixtures/today/wnba-daily-picks.json";

const NBA_KEY = "betslip_picks";
const WNBA_KEY = "wnba_betslip_picks";

const nba = dailyPicksResponseSchema.parse(nbaPicksFixture);
const lineups = lineupsResponseSchema.parse(nbaLineupsFixture);
const wnbaPicks = dailyPicksResponseSchema.parse(wnbaPicksFixture).picks;
const wilson = wnbaPicks[0];
const stewart = wnbaPicks[1];

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

function slipBody(pick: DailyPick, probability = pick.probability) {
  return {
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
  };
}

function WnbaAdder() {
  const wnba = useWnbaBetSlip();
  return (
    <button type="button" onClick={() => stewart && wnba.addPick(slipBody(stewart))}>
      Add WNBA leg
    </button>
  );
}

function stored(key: string): Array<{ player_name?: string; direction?: string; probability?: number }> {
  const raw = window.localStorage.getItem(key);
  return raw ? (JSON.parse(raw) as Array<{ player_name?: string; direction?: string; probability?: number }>) : [];
}

describe("reverse slip and league storage keys", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    apiMocks.getDailyPicks.mockResolvedValue(nba);
    apiMocks.getLineups.mockResolvedValue(lineups);
    window.localStorage.setItem(
      WNBA_KEY,
      JSON.stringify([
        {
          ...slipBody(wilson),
          id: `${wilson.player_name}-${wilson.metric}`,
          added_at: "2026-11-10T18:00:00.000Z",
        },
      ]),
    );
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
    await user.click(within(card).getByRole("button", { name: "Add Under" }));

    const shown = formatPercent(1 - bam.probability);
    expect(shown).toBe("28.0%");
    expect((await screen.findAllByText("Under 18.5 points")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(shown).length).toBeGreaterThan(0);
    expect(screen.getByText("Pass")).toBeInTheDocument();

    await waitFor(() => {
      const legs = stored(NBA_KEY);
      expect(legs).toHaveLength(1);
      expect(legs[0]?.player_name).toBe("Bam Adebayo");
      expect(legs[0]?.direction).toBe("under");
      expect(legs[0]?.probability).toBe(1 - bam.probability);
    });
    expect(stored(WNBA_KEY).map((leg) => leg.player_name)).toEqual(["A'ja Wilson"]);
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
    expect(stored(WNBA_KEY).map((leg) => leg.player_name)).toEqual(["A'ja Wilson"]);
  });

  it("leaves the NBA slip key unchanged when a WNBA leg is added", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      NBA_KEY,
      JSON.stringify([
        {
          ...slipBody(nba.picks[0]),
          id: "Bam Adebayo-points",
          added_at: "2026-11-10T18:00:00.000Z",
        },
      ]),
    );

    renderWithProviders(<WnbaAdder />);
    await user.click(screen.getByRole("button", { name: "Add WNBA leg" }));

    await waitFor(() => {
      expect(stored(WNBA_KEY).map((leg) => leg.player_name)).toEqual([
        "A'ja Wilson",
        "Breanna Stewart",
      ]);
    });
    expect(stored(NBA_KEY).map((leg) => leg.player_name)).toEqual(["Bam Adebayo"]);
    expect(window.localStorage.getItem("nba_betslip_picks")).toBeNull();
  });
});
