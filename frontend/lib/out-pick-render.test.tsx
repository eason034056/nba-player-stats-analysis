import type { ReactNode } from "react";
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OurRead } from "@/components/event/OurRead";
import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { buildOurRead } from "@/lib/event-page";
import { dailyPicksResponseSchema, type DailyPick } from "@/lib/schemas";
import { clearBetSlip, createBetSlipPick, renderWithProviders, seedBetSlip } from "@/test/test-utils";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";

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
    getLineups: vi.fn(async () => ({
      date: "2026-11-11",
      team_count: 0,
      fetched_at: null,
      cache_state: "miss",
      lineups: [],
    })),
  };
});

const base = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];

function outPick(): DailyPick {
  return {
    ...base,
    player_name: "Jimmy Butler",
    injury_status: "Out",
    lineup_confirmed: null,
    tier: null,
    combined_probability: null,
    has_projection: false,
    projected_value: null,
    projected_minutes: null,
    edge: null,
    signals: null,
  };
}

function assertNoBrokenPercent(text: string) {
  expect(text).not.toMatch(/NaN/);
  expect(text).not.toMatch(/(^|[^0-9])0%/);
}

describe("an Out pick with a null blend", () => {
  it("renders the event read as an em dash", () => {
    const pick = outPick();
    const model = buildOurRead({
      player: pick.player_name,
      marketName: "Points",
      market: "player_points",
      binary: false,
      eventId: pick.event_id,
      homeTeam: pick.home_team,
      awayTeam: pick.away_team,
      commenceTime: pick.commence_time,
      team: pick.player_team_code,
      position: null,
      line: pick.threshold,
      pick,
      consensus: null,
      last10: [],
      history: null,
      league: "nba",
    });
    renderWithProviders(
      <OurRead
        league="nba"
        model={model}
        isLoading={false}
        isError={false}
        errorText={null}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={() => {}}
        onAddOther={() => {}}
        onAsk={() => {}}
      />,
    );
    const read = screen.getByTestId("our-read");
    expect(read).toHaveTextContent("Combined probability —.");
    assertNoBrokenPercent(read.textContent ?? "");
  });

  it("renders the slip pill as an em dash", async () => {
    clearBetSlip();
    const pick = outPick();
    seedBetSlip([
      createBetSlipPick({
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
        tier: null,
        combined_probability: null,
      }),
    ]);
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    expect(card).toHaveTextContent("Jimmy Butler");
    expect(card).toHaveTextContent("—");
    assertNoBrokenPercent(card.textContent ?? "");
    expect(screen.getByText("avg. probability").previousElementSibling).toHaveTextContent("72%");
  });
});
