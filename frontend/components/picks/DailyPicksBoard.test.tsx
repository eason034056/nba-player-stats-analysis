import type { ReactNode } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { dailyPicksResponseSchema, lineupsResponseSchema } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import nbaPicksFixture from "@/test/fixtures/picks/nba-daily-picks.json";
import nbaPicksEmptyFixture from "@/test/fixtures/picks/nba-daily-picks-empty.json";
import nbaLineupsFixture from "@/test/fixtures/picks/nba-lineups.json";

const picks = dailyPicksResponseSchema.parse(nbaPicksFixture);
const empty = dailyPicksResponseSchema.parse(nbaPicksEmptyFixture);
const lineups = lineupsResponseSchema.parse(nbaLineupsFixture);

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/picks",
  useRouter: () => ({ push: vi.fn() }),
}));

function renderBoard(overrides: Partial<DailyPicksBoardProps> = {}) {
  const props: DailyPicksBoardProps = {
    league: "nba",
    selectedDate: "2026-11-10",
    onDateChange: vi.fn(),
    analyzedAt: picks.analyzed_at,
    isStale: false,
    picks: picks.picks,
    isLoading: false,
    isError: false,
    errorMessage: null,
    onRetry: vi.fn(),
    onReanalyze: vi.fn(),
    isReanalyzing: false,
    emptyMessage: null,
    minProbability: 0.65,
    teams: ["IND", "MIA", "PHI"],
    selectedTeams: new Set(),
    onToggleTeam: vi.fn(),
    onClearTeams: vi.fn(),
    teamFilterEmpty: false,
    lineupFor: (pick) =>
      lineups.lineups.find((lineup) => lineup.team === pick.player_team_code) ?? null,
    showLineup: true,
    isLineupLoading: false,
    isLineupError: false,
    slipDirection: () => null,
    onToggleSlip: vi.fn(),
    ...overrides,
  };
  return renderWithProviders(<DailyPicksBoard {...props} />);
}

describe("DailyPicksBoard", () => {
  it("shows fixture players and only the fields the payload includes", () => {
    renderBoard();

    expect(screen.getByRole("link", { name: "Bam Adebayo" })).toBeInTheDocument();
    expect(screen.getByText("Joel Embiid")).toBeInTheDocument();
    expect(screen.getByText("Tyrese Haliburton")).toBeInTheDocument();
    expect(screen.getByText("72.0%")).toBeInTheDocument();
    expect(screen.getByText("Proj 20.4")).toBeInTheDocument();
    expect(screen.getByText("Def #9")).toBeInTheDocument();
    expect(screen.getByText(/lineup aligned/i)).toBeInTheDocument();
    expect(screen.getByText("Playable")).toBeInTheDocument();
    expect(screen.queryByText("Chet Holmgren")).not.toBeInTheDocument();
    expect(screen.queryByText(/L10/)).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("text-yellow-600");
  });

  it("hides players that miss the confidence or market chip", async () => {
    const user = userEvent.setup();
    renderBoard();

    await user.click(screen.getByRole("button", { name: "Strong ≥70%" }));
    expect(screen.queryByText("Tyrese Haliburton")).not.toBeInTheDocument();
    expect(screen.getByText("Bam Adebayo")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "All" }));
    await user.click(screen.getByRole("button", { name: "AST" }));
    expect(screen.getByText("Tyrese Haliburton")).toBeInTheDocument();
    expect(screen.queryByText("Bam Adebayo")).not.toBeInTheDocument();
  });

  it("shows the empty message from the response", () => {
    renderBoard({
      picks: empty.picks,
      emptyMessage: empty.message,
      teams: [],
      showLineup: false,
    });

    expect(screen.getByRole("heading", { name: /no high-probability picks/i })).toBeInTheDocument();
    expect(screen.getByText(/no betting options with over 65%/i)).toBeInTheDocument();
    expect(screen.queryByText("Bam Adebayo")).not.toBeInTheDocument();
  });

  it("shows a loading state without player names", () => {
    renderBoard({ picks: [], isLoading: true, teams: [] });

    expect(screen.getByLabelText("Loading picks")).toBeInTheDocument();
    expect(screen.queryByText("Bam Adebayo")).not.toBeInTheDocument();
  });

  it("shows an error and retries", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    renderBoard({
      picks: [],
      isError: true,
      errorMessage: "board down",
      onRetry,
      teams: [],
    });

    expect(screen.getByRole("heading", { name: /load failed/i })).toBeInTheDocument();
    expect(screen.getByText("board down")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /click to retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
