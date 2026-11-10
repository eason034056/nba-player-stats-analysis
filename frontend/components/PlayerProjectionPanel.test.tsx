import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlayerProjectionPanel } from "@/components/PlayerProjectionPanel";
import { playerProjectionSchema, type PlayerProjection } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import rankFixture from "@/test/fixtures/projections/opponent-defense-rank.json";

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

  it("treats rank 1 as the weakest defense and the highest rank as the strongest", () => {
    const weakest = playerProjectionSchema.parse(rankFixture.weakest);
    const strongest = playerProjectionSchema.parse(rankFixture.strongest);
    const missing = playerProjectionSchema.parse(rankFixture.missing);

    const { rerender } = renderWithProviders(
      <PlayerProjectionPanel projection={weakest} metric="points" threshold={18.5} />,
    );
    const easy = screen.getByText("Easy #1");
    expect(easy).toHaveClass("text-green-700");
    expect(screen.queryByText("Hard #1")).not.toBeInTheDocument();

    rerender(
      <PlayerProjectionPanel projection={strongest} metric="points" threshold={29.5} />,
    );
    const hard = screen.getByText("Hard #30");
    expect(hard).toHaveClass("text-red");
    expect(screen.queryByText("Easy #30")).not.toBeInTheDocument();

    rerender(
      <PlayerProjectionPanel projection={missing} metric="points" threshold={9.5} />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/Easy #|Avg #|Hard #/)).not.toBeInTheDocument();
  });

  it("keeps the 10/11 and 20/21 cuts, and still labels 0 and 31", () => {
    const base = playerProjectionSchema.parse(rankFixture.weakest);
    const cases: Array<[number, string, string]> = [
      [10, "Easy #10", "text-green-700"],
      [11, "Avg #11", "text-yellow-700"],
      [20, "Avg #20", "text-yellow-700"],
      [21, "Hard #21", "text-red"],
      [0, "Easy #0", "text-green-700"],
      [31, "Hard #31", "text-red"],
    ];

    const { rerender } = renderWithProviders(
      <PlayerProjectionPanel projection={{ ...base, opponent_rank: 10 }} metric="points" threshold={18.5} />,
    );
    for (const [rank, label, color] of cases) {
      rerender(
        <PlayerProjectionPanel
          projection={{ ...base, opponent_rank: rank }}
          metric="points"
          threshold={18.5}
        />,
      );
      expect(screen.getByText(label)).toHaveClass(color);
    }

    // The projection schema does not clamp the documented 1-30 range.
    expect(playerProjectionSchema.parse({ ...rankFixture.weakest, opponent_rank: 0 }).opponent_rank).toBe(0);
    expect(playerProjectionSchema.parse({ ...rankFixture.weakest, opponent_rank: 31 }).opponent_rank).toBe(31);
    expect(
      playerProjectionSchema.parse({ ...rankFixture.weakest, opponent_rank: Number.POSITIVE_INFINITY }).opponent_rank,
    ).toBe(Number.POSITIVE_INFINITY);

    rerender(
      <PlayerProjectionPanel
        projection={{ ...base, opponent_rank: Number.NaN }}
        metric="points"
        threshold={18.5}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/Easy #|Avg #|Hard #/)).not.toBeInTheDocument();

    rerender(
      <PlayerProjectionPanel
        projection={{ ...base, opponent_rank: Number.POSITIVE_INFINITY }}
        metric="points"
        threshold={18.5}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/Easy #|Avg #|Hard #/)).not.toBeInTheDocument();
  });
});
