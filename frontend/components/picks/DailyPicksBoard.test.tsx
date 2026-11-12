import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
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

function boardProps(overrides: Partial<DailyPicksBoardProps> = {}): DailyPicksBoardProps {
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
  return props;
}

function renderBoard(overrides: Partial<DailyPicksBoardProps> = {}) {
  return renderWithProviders(<DailyPicksBoard {...boardProps(overrides)} />);
}

describe("DailyPicksBoard", () => {
  it("shows fixture players and only the fields the payload includes", () => {
    renderBoard();

    expect(screen.getByRole("link", { name: "Bam Adebayo" })).toBeInTheDocument();
    expect(screen.getByText("Joel Embiid")).toBeInTheDocument();
    expect(screen.getByText("Tyrese Haliburton")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.queryByText("72%")).not.toBeInTheDocument();
    expect(screen.queryByText("72.0%")).not.toBeInTheDocument();
    expect(screen.getByText("Proj 20.4")).toBeInTheDocument();
    expect(screen.getByText("Def #9")).toBeInTheDocument();
    expect(screen.getByText(/lineup aligned/i)).toBeInTheDocument();
    expect(screen.queryByText("Playable")).not.toBeInTheDocument();
    expect(screen.queryByText("Chet Holmgren")).not.toBeInTheDocument();
    expect(screen.queryByText(/L10/)).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("text-yellow-600");
  });

  it("shows an em dash when the player team is empty", () => {
    const blank = {
      ...picks.picks[0],
      player_name: "Anfernee Simons",
      player_team: "",
      player_team_code: "",
      home_team: "Philadelphia 76ers",
      away_team: "Boston Celtics",
    };
    renderBoard({ picks: [blank], teams: [] });
    expect(screen.getByText("Anfernee Simons")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/^PHI$/)).not.toBeInTheDocument();
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

  it("keeps the playable band below 70% and stacks the card on a narrow layout", async () => {
    const user = userEvent.setup();
    renderBoard();

    const card = screen.getByRole("link", { name: "Bam Adebayo" }).closest("article");
    expect(card?.className).toContain("flex-col");
    expect(card?.className).toContain("md:flex-row");
    const confidence = screen.getByRole("group", { name: "Confidence" });
    expect(confidence.className).toContain("overflow-x-auto");
    expect(confidence.className).toContain("md:flex-wrap");

    await user.click(screen.getByRole("button", { name: /Playable 65/ }));
    expect(screen.getByText("Tyrese Haliburton")).toBeInTheDocument();
    expect(screen.queryByText("Bam Adebayo")).not.toBeInTheDocument();
    expect(screen.queryByText("Joel Embiid")).not.toBeInTheDocument();
  });

  it("clears the confidence chip when the date changes", async () => {
    const user = userEvent.setup();
    const { rerender } = renderBoard();

    await user.click(screen.getByRole("button", { name: "Strong ≥70%" }));
    expect(screen.queryByText("Tyrese Haliburton")).not.toBeInTheDocument();

    rerender(<DailyPicksBoard {...boardProps({ selectedDate: "2026-11-11" })} />);

    expect(screen.getByText("Tyrese Haliburton")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  });

  it("renders no projection, edge, minutes, injury, or lineup when those fields are null", () => {
    const blank = {
      ...picks.picks[0],
      tier: "Strong play" as const,
      combined_probability: 0.72,
      has_projection: false,
      projected_value: null,
      projected_minutes: null,
      edge: null,
      injury_status: null,
      lineup_confirmed: null,
    };
    renderBoard({ picks: [blank], teams: ["MIA"], showLineup: false });
    const card = screen.getByRole("article");
    expect(card).toHaveTextContent("Bam Adebayo");
    expect(card).toHaveTextContent("72%");
    expect(card.textContent ?? "").not.toMatch(/Proj|Edge|\bmin\b|NaN|—|Questionable|Lineup|Projection|Injury/);
  });

  it("renders an Out or Questionable tag and no lineup-confirmed tag", () => {
    const marked = {
      ...picks.picks[0],
      tier: "Strong play" as const,
      combined_probability: 0.72,
      has_projection: false,
      projected_value: null,
      projected_minutes: null,
      edge: null,
      injury_status: "Questionable",
      lineup_confirmed: true,
    };
    renderBoard({ picks: [marked], teams: ["MIA"], showLineup: false });
    expect(screen.getByText("Questionable")).toBeInTheDocument();
    expect(screen.queryByText("Lineup confirmed")).not.toBeInTheDocument();
  });

  it("dims an Out pick at the end with no bar, percent, or slip, and leaves Questionable unchanged", async () => {
    const user = userEvent.setup();
    const base = picks.picks[0];
    const out = {
      ...base,
      player_name: "Jimmy Butler",
      tier: null,
      combined_probability: null,
      probability: 0.91,
      has_projection: false,
      projected_value: null,
      projected_minutes: null,
      edge: null,
      injury_status: "Out",
      lineup_confirmed: null,
    };
    const questionable = {
      ...base,
      injury_status: "Questionable",
      tier: "Playable" as const,
      combined_probability: 0.74,
      probability: 0.66,
      lineup_confirmed: true as const,
    };
    const onToggleSlip = vi.fn();
    renderBoard({
      picks: [out, questionable],
      teams: ["MIA"],
      showLineup: true,
      onToggleSlip,
      onAddReverse: vi.fn(),
      onAsk: vi.fn(),
    });

    expect(screen.getByText("picks").previousElementSibling).toHaveTextContent("1");
    expect(screen.getByText("strong").previousElementSibling).toHaveTextContent("1");

    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent("Bam Adebayo");
    expect(cards[0]).toHaveTextContent("74%");
    expect(cards[0]).toHaveTextContent("Questionable");
    expect(within(cards[0]).getByRole("button", { name: "Add to Bet Slip" })).toBeInTheDocument();

    expect(cards[1]).toHaveTextContent("Jimmy Butler");
    expect(cards[1]).toHaveTextContent("Out");
    expect(cards[1]).not.toHaveTextContent("%");
    expect(cards[1]).not.toHaveTextContent("—");
    expect(cards[1]).not.toHaveTextContent("Lineup");
    expect(cards[1]).not.toHaveTextContent("Def");
    expect(cards[1].querySelector("a")).toHaveAttribute("href", expect.stringContaining("/event/"));
    expect(within(cards[1]).queryByRole("button")).not.toBeInTheDocument();
    expect(onToggleSlip).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Strong ≥70%" }));
    expect(screen.queryByText("Jimmy Butler")).not.toBeInTheDocument();
    expect(screen.getByText("Bam Adebayo")).toBeInTheDocument();
  });
});
