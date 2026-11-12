import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { buildOurRead, eventPlayerRows } from "@/lib/event-page";
import { buildPickRows, countStrong, isOutPick, pickTags, sortPicks } from "@/lib/picks-board";
import { dailyPicksResponseSchema, eventsResponseSchema, type DailyPick } from "@/lib/schemas";
import { todayGames, todayReads } from "@/lib/today-board";
import { renderWithProviders } from "@/test/test-utils";
import boardFixture from "@/test/fixtures/picks/nba-daily-picks.json";
import todayPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";
import todayEventsFixture from "@/test/fixtures/today/nba-events.json";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/picks",
  useRouter: () => ({ push: vi.fn() }),
}));

const boardPick = dailyPicksResponseSchema.parse(boardFixture).picks[0];
const todayPicks = dailyPicksResponseSchema.parse(todayPicksFixture);
const todayEvents = eventsResponseSchema.parse(todayEventsFixture);
const [bam, embiid] = todayPicks.picks;

function withStatus(pick: DailyPick, status: string | null | undefined): DailyPick {
  return { ...pick, injury_status: status as string | null };
}

const OUT_VARIANTS = ["Out", "out", "OUT", " Out ", "\tout\n"];
const NOT_OUT = ["Out (knee)", "Questionable", "Doubtful", "Probable", "Day-To-Day", "day to day", "Active", "", null, undefined];

describe("Out tag and Out exclusion read the same status", () => {
  it.each([...OUT_VARIANTS, ...NOT_OUT])("agree for %j", (status) => {
    const pick = withStatus(bam, status);
    const tagged = pickTags(pick).some((tag) => tag.text === "Out");
    expect(isOutPick(pick)).toBe(tagged);

    const [row] = buildPickRows([pick], "nba", todayPicks.date);
    expect(row.dimmed).toBe(tagged);
    expect(todayReads([pick], "nba", todayPicks.date).length === 0).toBe(tagged);
  });

  it("treats every spelling of Out as Out, and nothing else", () => {
    for (const status of OUT_VARIANTS) expect(isOutPick({ injury_status: status })).toBe(true);
    for (const status of NOT_OUT) expect(isOutPick({ injury_status: status })).toBe(false);
  });
});

describe("Doubtful, Questionable, and no status still count as reads", () => {
  it.each(["Doubtful", "Questionable", null])("%j keeps its percent, tier, and strong count", (status) => {
    const pick = withStatus({ ...bam, tier: "Strong play", combined_probability: 0.724 }, status);
    const [row] = buildPickRows([pick], "nba", todayPicks.date);
    expect(row.dimmed).toBe(false);
    expect(row.probabilityText).toBe("72%");
    expect(row.tierName).toBe("strong");
    expect(countStrong([pick], "nba")).toBe(1);
    expect(todayReads([pick], "nba", todayPicks.date)[0]?.player).toBe("Bam Adebayo");
  });

  it("floors a 0.697 blend to 69% on the board and on Today for a Questionable pick", () => {
    const pick = withStatus({ ...bam, tier: "Playable", combined_probability: 0.697 }, "Questionable");
    expect(buildPickRows([pick], "nba", todayPicks.date)[0].probabilityText).toBe("69%");
    expect(todayReads([pick], "nba", todayPicks.date)[0]?.probabilityText).toBe("69%");
  });

  it("keeps a Doubtful player's event read and rail row", () => {
    const pick = withStatus({ ...bam, tier: "Strong play", combined_probability: 0.724 }, "Doubtful");
    const [row] = eventPlayerRows({
      suggested: [pick.player_name],
      picks: [pick],
      metric: pick.metric === "rebounds" ? "player_rebounds" : pick.metric,
      eventId: pick.event_id,
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "MIL",
      homeAbbr: "MIA",
      league: "nba",
    });
    expect(row.leanText).not.toBe("Out");
    expect(row.hasLean).toBe(true);
    expect(row.probability).not.toBeNull();
  });
});

describe("an Out pick across surfaces", () => {
  const out = withStatus({ ...bam, tier: "Strong play", combined_probability: 0.95, probability: 0.95 }, " OUT ");

  it("sorts last even with the highest rate, and never counts as strong", () => {
    expect(sortPicks([out, embiid], "nba").map((pick) => pick.player_name)).toEqual(["Joel Embiid", "Bam Adebayo"]);
    expect(countStrong([out, embiid], "nba")).toBe(1);
  });

  it("is not tonight's top read, even with a stale Strong tier", () => {
    const [heat] = todayGames(todayEvents.events, [out], "nba", todayPicks.date);
    expect(heat.topText).toBeNull();
    expect(heat.topProbabilityText).toBeNull();
    expect(todayReads([out, embiid], "nba", todayPicks.date).map((card) => card.player)).toEqual(["Joel Embiid"]);
  });

  it("has no tier, percent, or slip seed on the event page", () => {
    const model = buildOurRead({
      player: out.player_name,
      marketName: "Rebounds",
      market: "player_rebounds",
      binary: false,
      eventId: out.event_id,
      homeTeam: out.home_team,
      awayTeam: out.away_team,
      commenceTime: out.commence_time,
      team: out.player_team_code ?? null,
      position: null,
      line: out.threshold,
      pick: out,
      consensus: null,
      last10: [],
      history: null,
      league: "nba",
    });
    expect(model.tier).toBeNull();
    expect(model.primary).toBeNull();
    expect(model.other).toBeNull();
    expect(model.leanProbability).toBeNull();
    expect(`${model.headlineLead} ${model.caption}`).not.toMatch(/\d%/);
  });
});

function boardProps(overrides: Partial<DailyPicksBoardProps>): DailyPicksBoardProps {
  return {
    league: "nba",
    selectedDate: "2026-11-10",
    onDateChange: vi.fn(),
    analyzedAt: null,
    isStale: false,
    picks: [],
    isLoading: false,
    isError: false,
    errorMessage: null,
    onRetry: vi.fn(),
    onReanalyze: vi.fn(),
    isReanalyzing: false,
    emptyMessage: null,
    minProbability: 0.65,
    teams: ["MIA"],
    selectedTeams: new Set(),
    onToggleTeam: vi.fn(),
    onClearTeams: vi.fn(),
    teamFilterEmpty: false,
    lineupFor: () => null,
    showLineup: false,
    isLineupLoading: false,
    isLineupError: false,
    slipDirection: () => null,
    onToggleSlip: vi.fn(),
    ...overrides,
  };
}

describe("DailyPicksBoard with an Out pick", () => {
  it("offers a remove control, and no reverse or Ask, for an Out pick that is already in the slip", () => {
    const out = withStatus({ ...boardPick, player_name: "Jimmy Butler" }, "out");
    const onToggleSlip = vi.fn();
    const onAddReverse = vi.fn();
    const onAsk = vi.fn();
    renderWithProviders(
      <DailyPicksBoard
        {...boardProps({
          picks: [out],
          slipDirection: () => out.direction,
          onToggleSlip,
          onAddReverse,
          onAsk,
        })}
      />,
    );
    const card = screen.getByRole("article");
    expect(card).toHaveTextContent("Jimmy Butler");
    expect(card).toHaveTextContent("Out");
    expect(card).not.toHaveTextContent("%");
    expect(card).not.toHaveTextContent("In slip");
    expect(within(card).getByRole("button", { name: "Remove Jimmy Butler" })).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /ask agent about/i })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /under|over/i })).not.toBeInTheDocument();
    expect(screen.getByText("picks").previousElementSibling).toHaveTextContent("0");
    expect(screen.getByText("strong").previousElementSibling).toHaveTextContent("0");
  });

  it("opens no context menu on an Out card, but still opens one on a Questionable card", async () => {
    const user = userEvent.setup();
    const out = withStatus({ ...boardPick, player_name: "Jimmy Butler" }, "OUT");
    const questionable = withStatus({ ...boardPick, player_name: "Bam Adebayo" }, "Questionable");
    renderWithProviders(<DailyPicksBoard {...boardProps({ picks: [out, questionable] })} />);

    await user.pointer([{ keys: "[MouseRight]", target: screen.getByText("Jimmy Butler") }]);
    expect(screen.queryByRole("button", { name: /view details/i })).not.toBeInTheDocument();

    await user.pointer([{ keys: "[MouseRight]", target: screen.getByText("Bam Adebayo") }]);
    expect(screen.getByRole("button", { name: /view details/i })).toBeInTheDocument();
  });

  it("shows a lower-case Out under All only, and a Doubtful pick under Strong with its own tag", async () => {
    const user = userEvent.setup();
    const out = withStatus({ ...boardPick, player_name: "Jimmy Butler", tier: "Strong play", combined_probability: 0.9 }, "out");
    const doubtful = withStatus(
      { ...boardPick, player_name: "Bam Adebayo", tier: "Strong play", combined_probability: 0.724 },
      "Doubtful",
    );
    renderWithProviders(<DailyPicksBoard {...boardProps({ picks: [out, doubtful] })} />);

    const cards = screen.getAllByRole("article");
    expect(cards.map((card) => within(card).queryByText("Jimmy Butler") != null)).toEqual([false, true]);
    expect(cards[0]).toHaveTextContent("Doubtful");
    expect(cards[0]).toHaveTextContent("72%");

    await user.click(screen.getByRole("button", { name: "Strong ≥70%" }));
    expect(screen.queryByText("Jimmy Butler")).not.toBeInTheDocument();
    expect(screen.getByText("Bam Adebayo")).toBeInTheDocument();
  });
});
