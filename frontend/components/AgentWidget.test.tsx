import { useEffect } from "react";
import { screen, waitFor, within } from "@testing-library/react";
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

const createMatchMediaResult = (query: string, matches: boolean) => ({
  matches,
  media: query,
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  dispatchEvent: vi.fn(),
});

const mockViewport = (isDesktop: boolean) => {
  vi.mocked(window.matchMedia).mockImplementation((query: string) =>
    createMatchMediaResult(query, isDesktop && query === "(min-width: 1024px)"),
  );
};

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
    market_pricing_mode: "exact_line",
    queried_line: 28.5,
    best_line: 28.5,
    available_lines: [28.5],
    best_book: "draftkings",
    best_odds: -110,
    summary: "Model edge is supported by historical hit rate and favorable pricing.",
    reasons: [
      "Hit rate has stayed above the required threshold.",
      "Best available price still shows a clean edge.",
    ],
    risk_factors: ["Opponent pace could suppress volume."],
    recommendation: null,
  },
  slip_review: null,
  quick_actions: [
    {
      action: "risk_check",
      label: "Biggest risk",
      prompt: "What is the biggest risk?",
    },
    {
      action: "line_movement",
      label: "Line movement",
      prompt: "Summarize line movement",
    },
  ],
};

const openWidget = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("button", { name: /ask the board/i }));
  return screen.getByRole("dialog", { name: /betting agent/i });
};

describe("AgentWidget", () => {
  beforeEach(() => {
    clearBetSlip();
    window.sessionStorage.clear();
    navigationMocks.usePathname.mockReturnValue("/picks");
    apiMocks.sendAgentChat.mockReset();
    apiMocks.sendAgentChat.mockResolvedValue(singlePickResponse);
    mockViewport(true);
  });

  it("starts collapsed, opens from the launcher, and closes on Escape in panel mode", async () => {
    const user = userEvent.setup();

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    expect(
      screen.queryByRole("dialog", { name: /betting agent/i }),
    ).not.toBeInTheDocument();

    await openWidget(user);

    expect(
      screen.getByRole("dialog", { name: /betting agent/i }),
    ).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: /betting agent/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("shows a compact pick summary, starter actions, and expands into workspace", async () => {
    const user = userEvent.setup();

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    const dialog = await openWidget(user);

    expect(within(dialog).getByText(/^Current pick$/i)).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Stephen Curry points over 28.5/i),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/^Route /i)).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /ask for verdict/i }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /biggest risk/i }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: /compare with slip/i }),
    ).not.toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: /expand workspace/i }),
    );

    expect(
      screen.getByRole("button", { name: /return to panel/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /show analysis/i })).toBeInTheDocument();
  });

  it("submits a starter action with selected pick context and hides suggestions until the tray is opened", async () => {
    const user = userEvent.setup();

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    const dialog = await openWidget(user);

    await user.click(
      within(dialog).getByRole("button", { name: /ask for verdict/i }),
    );

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

    expect((await screen.findAllByText(/historical hit rate/i)).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", { name: /biggest risk/i }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /suggestions/i }));

    expect(screen.getByRole("button", { name: /biggest risk/i })).toBeInTheDocument();
    expect(screen.getByText(/more prompts/i)).toBeInTheDocument();
  });

  it("supports a compact composer without an expand control and newline-aware submit", async () => {
    const user = userEvent.setup();

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    await openWidget(user);

    const composer = screen.getByRole("textbox", { name: /message betting agent/i });
    expect(
      screen.getByRole("log", { name: /betting agent transcript/i }),
    ).toHaveClass("app-scrollbar");
    expect(
      screen.queryByRole("button", { name: /expand composer|collapse composer/i }),
    ).not.toBeInTheDocument();

    await user.type(composer, "First line");
    await user.keyboard("{Shift>}{Enter}{/Shift}Second line");

    expect(composer).toHaveValue("First line\nSecond line");

    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(apiMocks.sendAgentChat).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "general",
          message: "First line\nSecond line",
        }),
      );
    });

    const transcript = screen.getByRole("log", { name: /betting agent transcript/i });
    const userBubble = within(transcript)
      .getAllByText((_, element) => {
        const text = element?.textContent ?? "";
        return text.includes("First line") && text.includes("Second line");
      })
      .find((element) => element.className.includes("w-fit"));

    expect(userBubble).toBeDefined();
    expect(userBubble).toHaveClass("ml-auto", "w-fit", "max-w-[85%]");
  });

  it("locks body scroll while the widget is open and restores it when closed", async () => {
    const user = userEvent.setup();

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    expect(document.body.style.overflow).toBe("");

    await openWidget(user);

    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(document.body.style.overflow).toBe("");
    });
  });

  it("contains transcript scrolling inside the widget", async () => {
    const user = userEvent.setup();

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    await openWidget(user);

    expect(
      screen.getByRole("log", { name: /betting agent transcript/i }),
    ).toHaveClass("overscroll-contain");
  });

  it("opens analysis in workspace and rehydrates workspace mode with the prior thread", async () => {
    const user = userEvent.setup();

    const firstRender = renderWithProviders(<AgentHarness />, {
      withAgentWidget: true,
    });

    const dialog = await openWidget(user);
    await user.click(
      within(dialog).getByRole("button", { name: /expand workspace/i }),
    );
    expect(screen.getByRole("dialog", { name: /betting agent/i })).toHaveClass(
      "max-w-6xl",
    );
    await user.click(screen.getByRole("button", { name: /show analysis/i }));
    await user.click(screen.getByRole("button", { name: /ask for verdict/i }));

    expect(
      await screen.findByRole("heading", { name: /market snapshot/i }),
    ).toBeInTheDocument();
    expect((await screen.findAllByText(/historical hit rate/i)).length).toBeGreaterThan(0);

    firstRender.unmount();

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    expect(screen.getByRole("button", { name: /return to panel/i })).toBeInTheDocument();
    expect((await screen.findAllByText(/historical hit rate/i)).length).toBeGreaterThan(0);
  });

  it("shows analysis as a bottom sheet on mobile workspace", async () => {
    const user = userEvent.setup();
    mockViewport(false);

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    const dialog = await openWidget(user);
    await user.click(
      within(dialog).getByRole("button", { name: /expand workspace/i }),
    );
    await user.click(screen.getByRole("button", { name: /show analysis/i }));

    expect(
      screen.getByRole("dialog", { name: /betting agent analysis/i }),
    ).toBeInTheDocument();
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

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    const dialog = await openWidget(user);
    await user.click(
      within(dialog).getByRole("button", { name: /ask for verdict/i }),
    );

    expect(
      await screen.findByText(/openai_api_key is not configured/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /retry last request/i }));

    await waitFor(() => {
      expect(apiMocks.sendAgentChat).toHaveBeenCalledTimes(2);
    });
    expect((await screen.findAllByText(/historical hit rate/i)).length).toBeGreaterThan(0);
  });

  it("falls back to a generic message when the request error has no detail", async () => {
    const user = userEvent.setup();

    apiMocks.sendAgentChat
      .mockRejectedValueOnce(new Error("backend down"))
      .mockResolvedValueOnce(singlePickResponse);

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    await openWidget(user);

    const composer = screen.getByRole("textbox", { name: /message betting agent/i });
    await user.type(composer, "Should I bet this?");
    await user.keyboard("{Enter}");

    expect(
      await screen.findByText(/could not reach the betting agent/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /retry last request/i }));

    await waitFor(() => {
      expect(apiMocks.sendAgentChat).toHaveBeenCalledTimes(2);
    });
    expect((await screen.findAllByText(/historical hit rate/i)).length).toBeGreaterThan(0);
  });

  it("shows line-moved market context in the analysis panel", async () => {
    const user = userEvent.setup();

    apiMocks.sendAgentChat.mockResolvedValueOnce({
      ...singlePickResponse,
      status: "line_moved",
      reply: "Market is still available, but the live line has moved from this pick.",
      verdict: {
        ...singlePickResponse.verdict,
        decision: "avoid",
        market_implied_probability: null,
        expected_value_pct: null,
        market_pricing_mode: "line_moved",
        queried_line: 28.5,
        best_line: 27.5,
        available_lines: [27.5, 28.0],
        best_book: "fanduel",
        best_odds: -108,
        summary: "The live market still exists, but the quoted line has moved away from the original pick.",
      },
    });

    renderWithProviders(<AgentHarness />, { withAgentWidget: true });

    const dialog = await openWidget(user);
    await user.click(
      within(dialog).getByRole("button", { name: /expand workspace/i }),
    );
    await user.click(screen.getByRole("button", { name: /show analysis/i }));
    await user.click(screen.getByRole("button", { name: /ask for verdict/i }));

    expect((await screen.findAllByText(/line moved/i)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/original 28.5/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/live 27.5/i).length).toBeGreaterThan(0);
  });
});
