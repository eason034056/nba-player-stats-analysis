import type { ReactNode } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PicksPage from "@/app/picks/page";
import { clearBetSlip, renderWithProviders } from "@/test/test-utils";

const apiMocks = vi.hoisted(() => ({
  getDailyPicks: vi.fn(),
  triggerDailyAnalysis: vi.fn(),
  sendAgentChat: vi.fn(),
}));

const navigationMocks = vi.hoisted(() => ({
  usePathname: vi.fn(),
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
  ...navigationMocks,
  useRouter: () => ({
    push: vi.fn(),
  }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    ...apiMocks,
  };
});

describe("PicksPage", () => {
  beforeEach(() => {
    clearBetSlip();
    window.sessionStorage.clear();
    navigationMocks.usePathname.mockReturnValue("/picks");

    apiMocks.getDailyPicks.mockResolvedValue({
      date: "2026-03-12",
      analyzed_at: "2026-03-12T00:00:00.000Z",
      total_picks: 1,
      picks: [
        {
          player_name: "Stephen Curry",
          player_team: "Golden State Warriors",
          event_id: "evt-1",
          home_team: "Los Angeles Lakers",
          away_team: "Golden State Warriors",
          commence_time: "2026-03-12T02:00:00Z",
          metric: "points",
          threshold: 28.5,
          direction: "over",
          probability: 0.72,
          n_games: 20,
          bookmakers_count: 6,
          all_lines: [28.5],
          has_projection: true,
          projected_value: 31.2,
          projected_minutes: 35,
          edge: 2.7,
          opponent_rank: 8,
          opponent_position_rank: 10,
          injury_status: null,
          lineup_confirmed: true,
        },
      ],
      stats: {
        total_events: 6,
        total_players: 84,
        total_props: 320,
        high_prob_count: 1,
        analysis_duration_seconds: 1.8,
      },
      message: null,
    });
    apiMocks.triggerDailyAnalysis.mockResolvedValue(null);
    apiMocks.sendAgentChat.mockResolvedValue({
      thread: "thread-1",
      action: "analyze_pick",
      status: "ok",
      reply: "Model edge is supported by historical hit rate and favorable pricing.",
      verdict: {
        subject: "Stephen Curry points over 28.5",
        decision: "over",
        confidence: 0.81,
        model_probability: 0.69,
        market_implied_probability: 0.57,
        expected_value_pct: 0.21,
        summary: "Model edge is supported by historical hit rate and favorable pricing.",
        reasons: [
          "Hit rate has stayed above the required threshold.",
          "Best available price still shows a clean edge.",
        ],
        risk_factors: ["Opponent pace could suppress volume."],
        recommendation: null,
      },
      slip_review: null,
      quick_actions: [],
    });
  });

  it("shows a visible add-to-slip action for each pick card", async () => {
    renderWithProviders(<PicksPage />);

    expect(await screen.findByText("Stephen Curry")).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: /add to bet slip/i }),
    ).toBeInTheDocument();
  });

  it("opens the widget from a pick card and sends the selected pick context", async () => {
    const user = userEvent.setup();

    renderWithProviders(<PicksPage />, { withAgentWidget: true });

    expect(await screen.findByText("Stephen Curry")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /ask agent about stephen curry/i }));

    expect(await screen.findByRole("dialog", { name: /betting agent/i })).toBeInTheDocument();
    expect(apiMocks.sendAgentChat).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "analyze_pick",
        context: expect.objectContaining({
          selected_pick: expect.objectContaining({
            player_name: "Stephen Curry",
          }),
        }),
      }),
    );
  });
});
