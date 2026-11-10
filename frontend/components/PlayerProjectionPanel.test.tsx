import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlayerProjectionPanel } from "@/components/PlayerProjectionPanel";
import type { PlayerProjection } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";

const projection = {
  player_name: "Nikola Jokic",
  team: "DEN",
  opponent: "LAL",
  points: 29.3,
  rebounds: 12.4,
  assists: 8.1,
  pra: 49.8,
  three_pointers_made: 1.2,
  steals: 1.4,
  free_throws_made: 5.5,
  field_goals_made: 11,
  r_a: 20.5,
  p_r: 41.7,
  p_a: 37.4,
} as PlayerProjection;

function highlighted(key: string): string | null {
  return screen.getByTestId(`proj-card-${key}`).getAttribute("data-highlighted");
}

describe("PlayerProjectionPanel highlights", () => {
  it("highlights the matching projection card and skips the edge when the metric has no card", () => {
    const { rerender } = renderWithProviders(
      <PlayerProjectionPanel projection={projection} metric="threes" threshold={2.5} />,
    );

    expect(highlighted("threes")).toBe("true");
    expect(highlighted("points")).toBe("false");
    expect(highlighted("pra")).toBe("false");
    expect(screen.getByText(/Edge vs Line \(3PM/)).toBeInTheDocument();
    expect(screen.queryByText(/Edge vs Line \(Points/)).not.toBeInTheDocument();

    rerender(
      <PlayerProjectionPanel projection={projection} metric="ra" threshold={18.5} />,
    );
    expect(highlighted("ra")).toBe("true");
    expect(highlighted("pra")).toBe("false");
    expect(screen.getByText(/Edge vs Line \(R\+A/)).toBeInTheDocument();

    rerender(
      <PlayerProjectionPanel projection={projection} metric="ftm" threshold={4.5} />,
    );
    expect(highlighted("ftm")).toBe("true");
    expect(highlighted("points")).toBe("false");

    rerender(
      <PlayerProjectionPanel projection={projection} metric="fgm" threshold={9.5} />,
    );
    expect(highlighted("fgm")).toBe("true");

    rerender(
      <PlayerProjectionPanel projection={projection} metric="steals" threshold={1.5} />,
    );
    expect(highlighted("steals")).toBe("true");
    expect(highlighted("points")).toBe("false");

    rerender(
      <PlayerProjectionPanel projection={projection} metric={null} threshold={0.5} />,
    );
    for (const key of ["points", "rebounds", "assists", "pra", "threes", "steals", "ftm", "fgm", "ra", "pr", "pa"]) {
      expect(highlighted(key)).toBe("false");
    }
    expect(screen.queryByText(/Edge vs Line/)).not.toBeInTheDocument();
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
  });
});
