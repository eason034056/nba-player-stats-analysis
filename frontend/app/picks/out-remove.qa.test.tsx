import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PicksPage from "@/app/picks/page";
import { dailyPicksResponseSchema, lineupsResponseSchema, type DailyPick } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import nbaLineupsFixture from "@/test/fixtures/picks/nba-lineups.json";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";

const NBA_KEY = "betslip_picks";

const base = dailyPicksResponseSchema.parse(nbaPicksFixture);
const lineups = lineupsResponseSchema.parse(nbaLineupsFixture);
const target = base.picks[0];

const apiMocks = vi.hoisted(() => ({
  getDailyPicks: vi.fn(),
  getLineups: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
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

function withStatus(status: string) {
  return dailyPicksResponseSchema.parse({
    ...nbaPicksFixture,
    picks: base.picks.map((pick) =>
      pick.player_name === target.player_name && pick.metric === target.metric
        ? { ...pick, injury_status: status }
        : pick,
    ),
  });
}

function seedSlip(pick: DailyPick) {
  window.localStorage.setItem(
    NBA_KEY,
    JSON.stringify([
      {
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
        id: `${pick.player_name}-${pick.metric}`,
        added_at: "2026-11-10T18:00:00.000Z",
      },
    ]),
  );
}

function storedNames(): string[] {
  const raw = window.localStorage.getItem(NBA_KEY);
  return raw ? (JSON.parse(raw) as Array<{ player_name: string }>).map((leg) => leg.player_name) : [];
}

async function findCard(name: string): Promise<HTMLElement> {
  const card = (await screen.findByText(name)).closest("article");
  expect(card).not.toBeNull();
  return card as HTMLElement;
}

describe("picks page: Out leg already in the slip", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    apiMocks.getLineups.mockResolvedValue(lineups);
  });

  it("removes the Out leg from the stored slip when Remove is clicked", async () => {
    const user = userEvent.setup();
    apiMocks.getDailyPicks.mockResolvedValue(withStatus("Out"));
    seedSlip(target);
    renderWithProviders(<PicksPage />);

    const card = await findCard(target.player_name);
    const remove = await within(card).findByRole("button", { name: `Remove ${target.player_name}` });
    expect(storedNames()).toEqual([target.player_name]);
    await user.click(remove);

    await waitFor(() => expect(storedNames()).toEqual([]));
  });

  it("offers no add control for an Out pick that is not in the slip", async () => {
    apiMocks.getDailyPicks.mockResolvedValue(withStatus("Out"));
    renderWithProviders(<PicksPage />);

    const card = await findCard(target.player_name);
    expect(within(card).queryByRole("button", { name: /add/i })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
    expect(storedNames()).toEqual([]);
  });

  it("keeps a Doubtful pick addable from the page", async () => {
    const user = userEvent.setup();
    apiMocks.getDailyPicks.mockResolvedValue(withStatus("Doubtful"));
    renderWithProviders(<PicksPage />);

    const card = await findCard(target.player_name);
    const adds = within(card).getAllByRole("button", { name: /add/i });
    await user.click(adds[0]);

    await waitFor(() => expect(storedNames()).toEqual([target.player_name]));
  });
});
