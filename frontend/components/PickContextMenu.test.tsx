import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PickContextMenu } from "@/components/PickContextMenu";
import { renderWithProviders } from "@/test/test-utils";

const navigationMocks = vi.hoisted(() => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
}));

vi.mock("next/navigation", () => navigationMocks);

describe("PickContextMenu", () => {
  beforeEach(() => {
    navigationMocks.usePathname.mockReturnValue("/picks");
    navigationMocks.useRouter.mockReturnValue({
      push: vi.fn(),
    });
  });

  it("navigates to the detail page with a local date query", async () => {
    const user = userEvent.setup();
    const push = vi.fn();
    navigationMocks.useRouter.mockReturnValue({ push });

    renderWithProviders(
      <PickContextMenu
        pick={{
          player_name: "Stephen Curry",
          player_team: "Golden State Warriors",
          player_team_code: "GSW",
          event_id: "evt-1",
          home_team: "Los Angeles Lakers",
          away_team: "Golden State Warriors",
          commence_time: "2026-03-17T01:00:00Z",
          metric: "points",
          threshold: 28.5,
          direction: "over",
          probability: 0.72,
          n_games: 20,
          bookmakers_count: 5,
          all_lines: [28.5],
          has_projection: true,
          projected_value: 31.2,
          projected_minutes: 35,
          edge: 2.7,
          opponent_rank: 8,
          opponent_position_rank: 10,
          injury_status: null,
          lineup_confirmed: true,
        }}
      >
        <button type="button">Open Menu</button>
      </PickContextMenu>,
    );

    await user.pointer([
      {
        keys: "[MouseRight]",
        target: screen.getByRole("button", { name: /open menu/i }),
      },
    ]);
    await user.click(screen.getByRole("button", { name: /view details/i }));

    expect(push).toHaveBeenCalledWith(
      "/event/evt-1?date=2026-03-16&player=Stephen+Curry&market=player_points&threshold=28.5",
    );
  });
});
