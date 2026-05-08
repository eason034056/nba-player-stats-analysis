import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TeamLineupPanel } from "@/components/TeamLineupPanel";
import { renderWithProviders } from "@/test/test-utils";


describe("TeamLineupPanel", () => {
  it("renders starters and a warning state for partial lineups", () => {
    renderWithProviders(
      <TeamLineupPanel
        lineup={{
          date: "2026-03-16",
          team: "GSW",
          opponent: "LAL",
          home_or_away: "AWAY",
          status: "partial",
          starters: ["Stephen Curry", "Andrew Wiggins"],
          bench_candidates: ["Brandin Podziemski"],
          sources: ["rotowire"],
          source_disagreement: true,
          confidence: "low",
          updated_at: "2026-03-16T17:40:00.000Z",
          source_snapshots: {
            rotowire: {
              team: "GSW",
              opponent: "LAL",
              home_or_away: "AWAY",
              status: "projected",
              starters: ["Stephen Curry", "Andrew Wiggins"],
              bench_candidates: [],
            },
          },
        }}
      />,
    );

    expect(screen.getByText("GSW")).toBeInTheDocument();
    expect(screen.getByText(/lineup still moving/i)).toBeInTheDocument();
    expect(screen.getByText("Stephen Curry")).toBeInTheDocument();
    expect(screen.getByText("Andrew Wiggins")).toBeInTheDocument();
  });

  it("renders an incomplete warning for partial lineups without source disagreement", () => {
    renderWithProviders(
      <TeamLineupPanel
        lineup={{
          date: "2026-03-16",
          team: "LAL",
          opponent: "HOU",
          home_or_away: "AWAY",
          status: "partial",
          starters: ["Luka Doncic", "Austin Reaves", "LeBron James"],
          bench_candidates: [],
          sources: ["rotowire"],
          source_disagreement: false,
          confidence: "low",
          updated_at: "2026-03-16T17:40:00.000Z",
          source_snapshots: {
            rotowire: {
              team: "LAL",
              opponent: "HOU",
              home_or_away: "AWAY",
              status: "projected",
              starters: ["Luka Doncic", "Austin Reaves", "LeBron James"],
              bench_candidates: [],
            },
          },
        }}
      />,
    );

    expect(screen.getByText(/lineup incomplete/i)).toBeInTheDocument();
    expect(screen.getByText(/free lineup sources are incomplete right now/i)).toBeInTheDocument();
  });
});
