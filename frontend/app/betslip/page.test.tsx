import type { ReactNode } from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BetSlipPage from "@/app/betslip/page";
import {
  clearBetSlip,
  createBetSlipPick,
  renderWithProviders,
  seedBetSlip,
} from "@/test/test-utils";

const navigationMocks = vi.hoisted(() => ({
  usePathname: vi.fn(),
}));

const apiMocks = vi.hoisted(() => ({
  sendAgentChat: vi.fn(),
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

vi.mock("next/navigation", () => navigationMocks);
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    sendAgentChat: apiMocks.sendAgentChat,
  };
});

describe("BetSlipPage", () => {
  beforeEach(() => {
    clearBetSlip();
    window.sessionStorage.clear();
    navigationMocks.usePathname.mockReturnValue("/betslip");
    apiMocks.sendAgentChat.mockResolvedValue({
      thread: "thread-1",
      action: "review_slip",
      status: "ok",
      reply: "Slip review complete: keep 1, recheck 0, remove 0.",
      verdict: null,
      slip_review: {
        items: [
          {
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
            recommendation: "keep",
          },
        ],
        summary: "Slip review complete: keep 1, recheck 0, remove 0.",
        keep_count: 1,
        recheck_count: 0,
        remove_count: 0,
      },
      quick_actions: [],
    });
  });

  it("renders the empty state when no picks are saved", () => {
    renderWithProviders(<BetSlipPage />);

    expect(
      screen.getByRole("heading", { name: /your bet slip is empty/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /browse daily picks/i }),
    ).toBeInTheDocument();
  });

  it("renders saved picks and share actions", async () => {
    seedBetSlip([createBetSlipPick()]);

    renderWithProviders(<BetSlipPage />);

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { level: 2, name: /your picks/i }),
      ).toBeInTheDocument();
    });

    expect(screen.getAllByText("Stephen Curry")).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: /download png/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /copy to clipboard/i }),
    ).toBeInTheDocument();
  });

  it("reviews the current slip through the agent widget", async () => {
    const user = userEvent.setup();
    seedBetSlip([createBetSlipPick()]);

    renderWithProviders(<BetSlipPage />, { withAgentWidget: true });

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { level: 2, name: /your picks/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /review my slip/i }));

    expect(await screen.findByRole("dialog", { name: /betting agent/i })).toBeInTheDocument();
    expect(apiMocks.sendAgentChat).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "review_slip",
        context: expect.objectContaining({
          bet_slip: expect.arrayContaining([
            expect.objectContaining({
              player_name: "Stephen Curry",
            }),
          ]),
        }),
      }),
    );
  });
});
