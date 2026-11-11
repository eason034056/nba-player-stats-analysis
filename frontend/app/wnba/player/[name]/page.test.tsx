import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WNBAPlayerPage from "@/app/wnba/player/[name]/page";
import {
  calculateWNBANoVig,
  getWNBAPlayerDDHistory,
  getWNBAPlayerHistory,
} from "@/lib/api";
import wilsonHistory from "@/test/fixtures/player-dd-history/wilson.json";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("next/navigation", () => ({
  useParams: () => ({ name: "A%27ja%20Wilson" }),
  usePathname: () => "/wnba/player/A%27ja%20Wilson",
  useRouter: () => ({ back: vi.fn(), push: vi.fn() }),
  useSearchParams: () => ({ get: () => null }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getWNBAPlayerHistory: vi.fn(),
    getWNBAPlayerDDHistory: vi.fn(),
    calculateWNBANoVig: vi.fn(),
    getPlayerDDHistory: vi.fn(),
    calculateNoVig: vi.fn(),
  };
});

describe("WNBA player page double-double tile", () => {
  beforeEach(() => {
    vi.mocked(getWNBAPlayerHistory).mockResolvedValue({
      player: "A'ja Wilson",
      metric: "points",
      threshold: 15.5,
      n_games: 0,
      p_over: null,
      p_under: null,
      equal_count: 0,
      message: "No qualifying games for this query.",
      histogram: [],
      game_logs: [],
      opponents: [],
      teammates: [],
    });
    vi.mocked(getWNBAPlayerDDHistory).mockResolvedValue(wilsonHistory);
    vi.mocked(calculateWNBANoVig).mockResolvedValue({
      event_id: "should-not-run",
      player_name: "A'ja Wilson",
      market: "player_double_double",
      results: [],
      message: null,
    });
  });

  it("renders double-double history without an event and shows the odds empty state", async () => {
    renderWithProviders(<WNBAPlayerPage />);

    expect(await screen.findByText("47%")).toBeInTheDocument();
    expect(screen.getByText("26 of 55 games")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Live Yes/No prices need a game. Open this player from an event to load posted odds.",
      ),
    ).toBeInTheDocument();
    expect(getWNBAPlayerDDHistory).toHaveBeenCalledWith({ player: "A'ja Wilson" });
    expect(calculateWNBANoVig).not.toHaveBeenCalled();
    expect(screen.getByTestId("wnba-player-dd")).toBeInTheDocument();
  });
});
