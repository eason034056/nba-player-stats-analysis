import { createRef } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AgentWidgetTranscript } from "@/components/agent-widget/AgentWidgetTranscript";
import { renderWithProviders } from "@/test/test-utils";


describe("AgentWidgetTranscript", () => {
  it("keeps the breakdown collapsed by default and renders all sections when expanded", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <AgentWidgetTranscript
        transcriptRef={createRef<HTMLDivElement>()}
        messages={[
          {
            id: "assistant-1",
            role: "assistant",
            text: "Expanded evidence is ready.",
            action: "analyze_pick",
            status: "ok",
            verdict: {
              subject: "Stephen Curry points over 28.5",
              decision: "over",
              confidence: 0.81,
              model_probability: 0.69,
              market_implied_probability: 0.57,
              expected_value_pct: 0.21,
              market_pricing_mode: "line_moved",
              queried_line: 28.5,
              best_line: 29.5,
              available_lines: [29.5, 30.5],
              best_book: "draftkings",
              best_odds: -110,
              summary: "Expanded evidence is ready.",
              breakdown: {
                sections: [
                  {
                    key: "historical",
                    label: "Historical",
                    tone: "support",
                    reliability: 0.82,
                    signal_note: "Historical data gives 69.0% to go over, with a mean of 30.12 versus a 28.50 line.",
                    risk_note: null,
                    stats: [
                      { label: "Query prob", value: "69.0%", tone: "positive" },
                    ],
                  },
                  {
                    key: "trend_role",
                    label: "Trend / Role",
                    tone: "support",
                    reliability: 0.71,
                    signal_note: "Recent form supports the over: last 5 average is 31.40, above the 28.50 line.",
                    risk_note: "Role blend leans on only 6 role-specific games.",
                    stats: [],
                  },
                  {
                    key: "shooting",
                    label: "Shooting",
                    tone: "neutral",
                    reliability: 0.6,
                    signal_note: "Shooting form is close to season baseline.",
                    risk_note: null,
                    stats: [],
                  },
                  {
                    key: "variance",
                    label: "Variance",
                    tone: "caution",
                    reliability: 0.77,
                    signal_note: "Outcome variance is high: CV 0.46 with a 20.00-39.00 10th-90th percentile range.",
                    risk_note: "High variance can overwhelm a thin edge.",
                    stats: [],
                  },
                  {
                    key: "schedule",
                    label: "Schedule",
                    tone: "neutral",
                    reliability: 0.55,
                    signal_note: "Schedule is neutral: this is not a back-to-back with 2 days rest.",
                    risk_note: null,
                    stats: [],
                  },
                  {
                    key: "own_team_injuries",
                    label: "Own-Team Injuries",
                    tone: "neutral",
                    reliability: 0.64,
                    signal_note: "No own-team injury swing stands out right now.",
                    risk_note: null,
                    stats: [],
                  },
                  {
                    key: "lineup",
                    label: "Lineup",
                    tone: "support",
                    reliability: 0.8,
                    signal_note: "Projected starters are aligned across both sources and the player's role looks stable.",
                    risk_note: null,
                    stats: [],
                  },
                  {
                    key: "market",
                    label: "Market",
                    tone: "caution",
                    reliability: 0.74,
                    signal_note: "The original 28.50 line is no longer available; the closest live line is 29.50.",
                    risk_note: "Same-line EV is gone until the original line returns.",
                    stats: [],
                  },
                  {
                    key: "projection",
                    label: "Projection",
                    tone: "unavailable",
                    reliability: null,
                    signal_note: "Projection input is disabled because the current feed is not trusted for betting decisions.",
                    risk_note: null,
                    stats: [{ label: "Status", value: "Disabled", tone: "muted" }],
                  },
                ],
              },
              reasons: [
                "Historical data gives 69.0% to go over, with a mean of 30.12 versus a 28.50 line.",
              ],
              risk_factors: ["Opponent pace could suppress volume."],
              recommendation: null,
            },
            quick_actions: [],
          },
        ]}
        starterActions={[]}
        isPending={false}
        error={null}
        onAction={vi.fn(async () => {})}
        onRetryLastRequest={vi.fn(async () => {})}
      />,
    );

    expect(screen.queryByText(/^Historical$/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /show breakdown/i }));

    expect(screen.getByText(/^Historical$/i)).toBeInTheDocument();
    expect(screen.getByText(/^Trend \/ Role$/i)).toBeInTheDocument();
    expect(screen.getByText(/^Projection$/i)).toBeInTheDocument();
    expect(screen.getAllByText(/^No material caution\.$/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/^Unavailable$/i)).toBeInTheDocument();
    expect(screen.getByText(/same-line ev is gone/i)).toBeInTheDocument();
  });
});
