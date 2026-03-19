import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LineupStatusBadge } from "@/components/LineupStatusBadge";
import { renderWithProviders } from "@/test/test-utils";


describe("LineupStatusBadge", () => {
  it("does not show bench risk when lineup is only partial", () => {
    renderWithProviders(
      <LineupStatusBadge
        playerName="Stephen Curry"
        lineup={{
          date: "2026-03-16",
          team: "GSW",
          opponent: "LAL",
          home_or_away: "AWAY",
          status: "partial",
          starters: ["Stephen Curry", "Buddy Hield", "J. Butler", "D. Green", "Q. Post"],
          bench_candidates: [],
          sources: ["rotowire", "rotogrinders"],
          source_disagreement: false,
          confidence: "low",
          updated_at: "2026-03-16T18:00:00.000Z",
          source_snapshots: {
            rotowire: {
              team: "GSW",
              opponent: "LAL",
              home_or_away: "AWAY",
              status: "expected",
              starters: ["Stephen Curry", "Buddy Hield", "J. Butler", "D. Green", "Q. Post"],
              bench_candidates: [],
            },
          },
        }}
      />,
    );

    expect(screen.getByText(/lineup moving/i)).toBeInTheDocument();
    expect(screen.queryByText(/bench risk/i)).not.toBeInTheDocument();
  });
});
