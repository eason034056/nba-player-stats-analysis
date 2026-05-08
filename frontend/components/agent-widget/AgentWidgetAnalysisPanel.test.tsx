import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentWidgetAnalysisPanel } from "@/components/agent-widget/AgentWidgetAnalysisPanel";
import { renderWithProviders } from "@/test/test-utils";


describe("AgentWidgetAnalysisPanel", () => {
  it("renders lineup context from the verdict payload", () => {
    renderWithProviders(
      <AgentWidgetAnalysisPanel
        pageContext={{
          route: "/picks",
          date: "2026-03-13",
          selected_teams: ["GSW"],
        }}
        selectedPickContext={{
          player_name: "Stephen Curry",
          player_team: "GSW",
          event_id: "evt-1",
          home_team: "LAL",
          away_team: "GSW",
          commence_time: "2026-03-13T02:00:00Z",
          metric: "points",
          threshold: 28.5,
          direction: "over",
          probability: 0.72,
          n_games: 20,
        }}
        lastAssistantMessage={{
          id: "assistant-1",
          role: "assistant",
          text: "Lineup support is stable and role looks secure.",
          action: "analyze_pick",
          status: "ok",
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
            summary: "Lineup support is stable and role looks secure.",
            breakdown: {
              sections: [
                {
                  key: "historical",
                  label: "Historical",
                  tone: "support",
                  reliability: 0.84,
                  signal_note:
                    "Historical data gives 69.0% to go over, with a mean of 30.12 versus a 28.50 line.",
                  risk_note: null,
                  stats: [
                    {
                      label: "Query prob",
                      value: "69.0%",
                      tone: "positive",
                    },
                  ],
                },
                {
                  key: "trend_role",
                  label: "Trend / Role",
                  tone: "support",
                  reliability: 0.7,
                  signal_note:
                    "Recent form supports the over: last 5 average is 31.40, above the 28.50 line.",
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
                  reliability: 0.75,
                  signal_note:
                    "Outcome variance is high: CV 0.46 with a 20.00-39.00 10th-90th percentile range.",
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
                  reliability: 0.68,
                  signal_note: "No own-team injury swing stands out right now.",
                  risk_note: null,
                  stats: [],
                },
                {
                  key: "lineup",
                  label: "Lineup",
                  tone: "support",
                  reliability: 0.8,
                  signal_note:
                    "Projected starters are aligned across both sources and the player's role looks stable.",
                  risk_note: null,
                  stats: [],
                },
                {
                  key: "market",
                  label: "Market",
                  tone: "support",
                  reliability: 0.72,
                  signal_note:
                    "Market prices the over at 57.0% on the 28.50 line, best price at DraftKings (-110).",
                  risk_note: "Priced edge is thin even with a same-line quote.",
                  stats: [
                    {
                      label: "Market prob",
                      value: "57.0%",
                      tone: "positive",
                    },
                  ],
                },
                {
                  key: "projection",
                  label: "Projection",
                  tone: "unavailable",
                  reliability: null,
                  signal_note:
                    "Projection input is disabled because the current feed is not trusted for betting decisions.",
                  risk_note: null,
                  stats: [
                    {
                      label: "Status",
                      value: "Disabled",
                      tone: "muted",
                    },
                  ],
                },
              ],
            },
            reasons: [],
            risk_factors: ["Opponent pace could suppress volume."],
            lineup_context: {
              summary: "Projected starters are aligned across both sources.",
              freshness_risk: false,
              player_team: {
                team: "GSW",
                status: "projected",
                confidence: "high",
                source_disagreement: false,
                updated_at: "2026-03-13T00:20:00Z",
                player_is_projected_starter: true,
                starters: ["Stephen Curry", "Buddy Hield", "Andrew Wiggins", "Draymond Green", "Trayce Jackson-Davis"],
              },
              opponent_team: {
                team: "LAL",
                status: "partial",
                confidence: "low",
                source_disagreement: true,
                updated_at: "2026-03-13T00:15:00Z",
                player_is_projected_starter: null,
                starters: ["Austin Reaves", "LeBron James"],
              },
            },
          },
          quick_actions: [],
        }}
        slipCount={1}
        isDesktop={true}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText(/^lineup context$/i)).toBeInTheDocument();
    expect(screen.getByText(/^breakdown$/i)).toBeInTheDocument();
    expect(screen.getByText(/^historical$/i)).toBeInTheDocument();
    expect(screen.getByText(/^projection$/i)).toBeInTheDocument();
    expect(screen.getByText(/^unavailable$/i)).toBeInTheDocument();
    expect(screen.getAllByText(/^no material caution\.$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/projected starters are aligned/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/player team/i)).toBeInTheDocument();
    expect(screen.getByText(/opponent team/i)).toBeInTheDocument();
  });
});
