import { useEffect } from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentWidget } from "@/contexts/AgentWidgetContext";
import { ApiError } from "@/lib/api";
import { clearBetSlip, renderWithProviders } from "@/test/test-utils";

const navigationMocks = vi.hoisted(() => ({
  usePathname: vi.fn(),
}));

const apiMocks = vi.hoisted(() => ({
  sendAgentChat: vi.fn(),
}));

vi.mock("next/navigation", () => navigationMocks);
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    sendAgentChat: apiMocks.sendAgentChat,
  };
});

function AgentHarness() {
  const { setPageContext, setSelectedPickContext } = useAgentWidget();

  useEffect(() => {
    setPageContext({
      route: "/picks",
      date: "2026-03-13",
      selected_teams: ["Golden State Warriors"],
    });
    setSelectedPickContext({
      player_name: "Stephen Curry",
      player_team: "Golden State Warriors",
      event_id: "evt-1",
      home_team: "Los Angeles Lakers",
      away_team: "Golden State Warriors",
      commence_time: "2026-03-13T02:00:00Z",
      metric: "points",
      threshold: 28.5,
      direction: "over",
      probability: 0.72,
      n_games: 20,
    });
  }, [setPageContext, setSelectedPickContext]);

  return null;
}

const singlePickResponse = {
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
};

describe("AgentWidget", () => {
  beforeEach(() => {
    clearBetSlip();
    window.sessionStorage.clear();
    navigationMocks.usePathname.mockReturnValue("/picks");
    apiMocks.sendAgentChat.mockReset();
    apiMocks.sendAgentChat.mockResolvedValue(singlePickResponse);
  });

  it("starts collapsed, opens from the launcher, and closes on Escape", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <AgentHarness />,
      { withAgentWidget: true },
    );

    expect(screen.queryByRole("dialog", { name: /betting agent/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /ask the board/i }));

    expect(screen.getByRole("dialog", { name: /betting agent/i })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /betting agent/i })).not.toBeInTheDocument();
    });
  });

  it("submits a quick action with selected pick context", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <AgentHarness />,
      { withAgentWidget: true },
    );

    await user.click(screen.getByRole("button", { name: /ask the board/i }));
    await user.click(screen.getByRole("button", { name: /should i bet this\\?/i }));

    await waitFor(() => {
      expect(apiMocks.sendAgentChat).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "analyze_pick",
          message: "Should I bet this?",
          context: expect.objectContaining({
            page: expect.objectContaining({
              route: "/picks",
              date: "2026-03-13",
            }),
            selected_pick: expect.objectContaining({
              player_name: "Stephen Curry",
            }),
          }),
        }),
      );
    });

    expect(await screen.findByText(/historical hit rate/i)).toBeInTheDocument();
  });

  it("rehydrates the previous thread from session storage", async () => {
    const user = userEvent.setup();

    const firstRender = renderWithProviders(
      <AgentHarness />,
      { withAgentWidget: true },
    );

    await user.click(screen.getByRole("button", { name: /ask the board/i }));
    await user.click(screen.getByRole("button", { name: /should i bet this\\?/i }));
    expect(await screen.findByText(/historical hit rate/i)).toBeInTheDocument();

    firstRender.unmount();

    renderWithProviders(
      <AgentHarness />,
      { withAgentWidget: true },
    );

    await user.click(screen.getByRole("button", { name: /ask the board/i }));

    expect(screen.getByText(/historical hit rate/i)).toBeInTheDocument();
  });

  it("shows an error state and retries the last request", async () => {
    const user = userEvent.setup();

    apiMocks.sendAgentChat
      .mockRejectedValueOnce(
        new ApiError(
          500,
          "Internal Server Error",
          "Agent chat failed: OPENAI_API_KEY is not configured.",
        ),
      )
      .mockResolvedValueOnce(singlePickResponse);

    renderWithProviders(
      <AgentHarness />,
      { withAgentWidget: true },
    );

    await user.click(screen.getByRole("button", { name: /ask the board/i }));
    await user.click(screen.getByRole("button", { name: /should i bet this\\?/i }));

    expect(
      await screen.findByText(/openai_api_key is not configured/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /retry last request/i }));

    await waitFor(() => {
      expect(apiMocks.sendAgentChat).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText(/historical hit rate/i)).toBeInTheDocument();
  });

  it("falls back to a generic message when the request error has no detail", async () => {
    const user = userEvent.setup();

    apiMocks.sendAgentChat
      .mockRejectedValueOnce(new Error("backend down"))
      .mockResolvedValueOnce(singlePickResponse);

    renderWithProviders(
      <AgentHarness />,
      { withAgentWidget: true },
    );

    await user.click(screen.getByRole("button", { name: /ask the board/i }));
    await user.click(screen.getByRole("button", { name: /should i bet this\\?/i }));

    expect(await screen.findByText(/could not reach the betting agent/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /retry last request/i }));

    await waitFor(() => {
      expect(apiMocks.sendAgentChat).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText(/historical hit rate/i)).toBeInTheDocument();
  });
});
