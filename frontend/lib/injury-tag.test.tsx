import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InjuryStatusTag } from "@/components/InjuryStatusTag";
import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { OUT_LEGS_NOTE, slipSummaryCaption } from "@/lib/bet-slip-board";
import { buildOurRead, eventPlayerRows } from "@/lib/event-page";
import {
  INJURY_WORDS,
  NEUTRAL_PAINT,
  canonicalInjuryTag,
  injuryPaint,
  injuryTag,
} from "@/lib/injury-tag";
import { injuryTagForPlayer, isOutPick, isPlayerOutInGame } from "@/lib/picks-board";
import {
  dailyPickSchema,
  dailyPicksResponseSchema,
  lineupsResponseSchema,
  propReadSchema,
  teamLineupSchema,
  topReadSchema,
  type DailyPick,
} from "@/lib/schemas";
import { todayReads } from "@/lib/today-board";
import {
  clearBetSlip,
  createBetSlipPick,
  renderWithProviders,
  seedBetSlip,
} from "@/test/test-utils";
import emptyLineupsFixture from "@/test/fixtures/lineups/empty.json";
import boardFixture from "@/test/fixtures/picks/nba-daily-picks.json";
import todayPicksFixture from "@/test/fixtures/today/nba-daily-picks.json";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/betslip",
  useRouter: () => ({ push: vi.fn() }),
}));

const apiMocks = vi.hoisted(() => ({
  getDailyPicks: vi.fn(),
  getLineups: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, ...apiMocks };
});

const boardPick = dailyPicksResponseSchema.parse(boardFixture).picks[0];
const todayPicks = dailyPicksResponseSchema.parse(todayPicksFixture);
const emptyLineups = lineupsResponseSchema.parse(emptyLineupsFixture);
const bam = todayPicks.picks[0];

// Samples from the settled DailyPick contract. The card floors 0.6095 to 60%.
const doubtfulSample = {
  injury_status: "Questionable",
  injury_status_raw: "Doubtful",
  combined_probability: 0.6095,
};
const outSample = {
  injury_status: "Out",
  injury_status_raw: "Out",
  combined_probability: null,
};
const wnbaInjurySample = {
  injury_status: null,
  injury_status_raw: null,
};

function channel(hex: string, index: number): number {
  const raw = parseInt(hex.replace("#", "").slice(index, index + 2), 16) / 255;
  return raw <= 0.04045 ? raw / 12.92 : ((raw + 0.055) / 1.055) ** 2.4;
}

function contrast(foreground: string, background: string): number {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

function luminance(hex: string): number {
  return 0.2126 * channel(hex, 0) + 0.7152 * channel(hex, 2) + 0.0722 * channel(hex, 4);
}

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

describe("injury tag text", () => {
  it.each(INJURY_WORDS.map((word) => [word.label, word.tone] as const))(
    "shows %s for the canonical word and for a spaced, any-case spelling",
    (label, tone) => {
      const spaced = `  ${label.toUpperCase()}  `;
      expect(injuryTag(spaced, null)).toEqual({ text: label, tone });
      expect(injuryTag(null, label)).toEqual({ text: label, tone });
    },
  );

  it("prefers the raw word over the stored status", () => {
    expect(injuryTag("Doubtful", "Questionable")).toEqual({ text: "Doubtful", tone: "doubtful" });
    expect(injuryTag("Day-To-Day", "Questionable")?.text).toBe("Day-To-Day");
  });

  it("keeps the raw word on DailyPick and off reads, lineups, and top_read", () => {
    expect(Object.hasOwn(dailyPickSchema.shape, "injury_status_raw")).toBe(true);
    expect(Object.hasOwn(propReadSchema.shape, "injury_status_raw")).toBe(false);
    expect(Object.hasOwn(teamLineupSchema.shape, "injury_status_raw")).toBe(false);
    expect(Object.hasOwn(topReadSchema.shape, "injury_status_raw")).toBe(false);

    const doubtful = dailyPickSchema.parse({ ...boardPick, ...doubtfulSample });
    expect(doubtful.injury_status).toBe("Questionable");
    expect(doubtful.injury_status_raw).toBe("Doubtful");
    expect(doubtful.combined_probability).toBe(0.6095);

    const out = dailyPickSchema.parse({ ...boardPick, ...outSample });
    expect(out.injury_status_raw).toBe("Out");
    expect(out.combined_probability).toBeNull();

    const quiet = dailyPickSchema.parse({ ...boardPick, ...wnbaInjurySample });
    expect(quiet.injury_status).toBeNull();
    expect(quiet.injury_status_raw).toBeNull();
    expect(injuryTag(quiet.injury_status_raw, quiet.injury_status)).toBeNull();
  });

  it("treats a missing raw field as null and falls back to the status", () => {
    const parsed = dailyPickSchema.parse({ ...boardFixture.picks[0], injury_status: "Probable" });
    expect(parsed.injury_status_raw ?? null).toBeNull();
    expect(injuryTag(parsed.injury_status_raw, parsed.injury_status)).toEqual({
      text: "Probable",
      tone: "probable",
    });
  });

  it("shows an unknown word trimmed, and nothing for null, blank, or Active", () => {
    expect(injuryTag("  GTD  ", "Questionable")).toEqual({ text: "GTD", tone: "neutral" });
    expect(injuryTag(null, "Out (knee)")).toEqual({ text: "Out (knee)", tone: "neutral" });
    expect(injuryTag("day to day", null)).toEqual({ text: "day to day", tone: "neutral" });
    expect(injuryTag(null, null)).toBeNull();
    expect(injuryTag(undefined, undefined)).toBeNull();
    expect(injuryTag("   ", "Out")).toBeNull();
    expect(injuryTag("", "Questionable")).toBeNull();
    expect(injuryTag(" Active ", "Out")).toBeNull();
    expect(injuryTag(null, "active")).toBeNull();
  });
});

describe("injury tag style", () => {
  it("gives each status its own chip and keeps small-text contrast at 4.5:1", () => {
    const seen = new Set<string>();
    for (const word of INJURY_WORDS) {
      const paint = injuryPaint(word.tone);
      expect(paint.chip).not.toBe(NEUTRAL_PAINT.chip);
      expect(seen.has(paint.chip)).toBe(false);
      seen.add(paint.chip);
      expect(contrast(paint.fg, paint.bg)).toBeGreaterThanOrEqual(4.5);
      const view = renderWithProviders(<InjuryStatusTag tag={canonicalInjuryTag(word.tone)} />);
      const chip = screen.getByText(word.label);
      expect(chip).toHaveAttribute("data-injury-tone", word.tone);
      expect(chip.className).toContain(paint.bg);
      view.unmount();
    }
    expect(contrast(NEUTRAL_PAINT.fg, NEUTRAL_PAINT.bg)).toBeGreaterThanOrEqual(4.5);
    renderWithProviders(<InjuryStatusTag tag={{ text: "GTD", tone: "neutral" }} />);
    expect(screen.getByText("GTD").className).toContain(NEUTRAL_PAINT.bg);
  });
});

describe("Doubtful does not block", () => {
  const doubtful: DailyPick = {
    ...boardPick,
    player_name: "Bam Adebayo",
    tier: null,
    ...doubtfulSample,
  };

  it("keeps a percent, a slip control, and Ask", () => {
    expect(isOutPick(doubtful)).toBe(false);
    expect(isPlayerOutInGame([doubtful], doubtful.event_id, doubtful.player_name)).toBe(false);
    renderWithProviders(
      <DailyPicksBoard
        {...boardProps({
          picks: [doubtful],
          onAsk: vi.fn(),
        })}
      />,
    );
    const card = screen.getByRole("article");
    const chip = within(card).getByText("Doubtful");
    expect(chip).toHaveAttribute("data-injury-tone", "doubtful");
    expect(card).toHaveTextContent("60%");
    expect(within(card).getByRole("button", { name: "Add to Bet Slip" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Ask Agent about Bam Adebayo" })).toBeInTheDocument();
    expect(card).not.toHaveTextContent("Questionable");
  });

  it("shows the same Doubtful chip on the event rail, the read, and Today", () => {
    const [row] = eventPlayerRows({
      suggested: [doubtful.player_name],
      picks: [doubtful],
      metric: "player_points",
      eventId: doubtful.event_id,
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "MIL",
      homeAbbr: "MIA",
      league: "nba",
    });
    expect(row.injury).toEqual({ text: "Doubtful", tone: "doubtful" });
    expect(row.leanText).not.toBe("Out");
    expect(row.hasLean).toBe(true);

    const model = buildOurRead({
      player: doubtful.player_name,
      marketName: "Points",
      market: "player_points",
      binary: false,
      eventId: doubtful.event_id,
      homeTeam: doubtful.home_team,
      awayTeam: doubtful.away_team,
      commenceTime: doubtful.commence_time,
      team: doubtful.player_team_code ?? null,
      position: null,
      line: doubtful.threshold,
      pick: doubtful,
      consensus: null,
      last10: [],
      history: null,
      league: "nba",
    });
    expect(model.listedOut).toBe(false);
    expect(model.injury).toEqual({ text: "Doubtful", tone: "doubtful" });
    expect(model.primary).not.toBeNull();

    const [read] = todayReads([doubtful], "nba", "2026-11-10");
    expect(read.player).toBe("Bam Adebayo");
    expect(read.injury).toEqual({ text: "Doubtful", tone: "doubtful" });
    expect(read.probabilityText).toBe("60%");
  });

  it("does not put an injury chip on a WNBA row", () => {
    const quiet: DailyPick = { ...doubtful, ...wnbaInjurySample };
    const railArgs = {
      suggested: [quiet.player_name],
      picks: [quiet],
      metric: "player_points" as const,
      eventId: quiet.event_id,
      selectedName: "",
      postedLine: null,
      awayLineup: null,
      homeLineup: null,
      awayAbbr: "MIL",
      homeAbbr: "MIA",
      league: "wnba" as const,
    };
    expect(eventPlayerRows(railArgs)[0]?.injury).toBeNull();
    expect(todayReads([quiet], "wnba", "2026-11-10")[0]?.injury).toBeNull();
    expect(eventPlayerRows({ ...railArgs, picks: [doubtful] })[0]?.injury).toBeNull();
  });
});

describe("slip caption", () => {
  it("adds the Out-leg sentence only when a leg is left out", () => {
    expect(slipSummaryCaption("blend", false)).not.toContain(OUT_LEGS_NOTE);
    expect(slipSummaryCaption("blend", true)).toContain(OUT_LEGS_NOTE);
    expect(slipSummaryCaption("stored", true).endsWith(OUT_LEGS_NOTE)).toBe(true);
  });

  const leg = createBetSlipPick({
    id: "Bam Adebayo-rebounds",
    player_name: "Bam Adebayo",
    event_id: bam.event_id,
    player_team: bam.player_team,
    home_team: bam.home_team,
    away_team: bam.away_team,
    commence_time: bam.commence_time,
    metric: "rebounds",
    threshold: 10.5,
    probability: 0.6095,
    combined_probability: 0.6095,
    tier: "Playable",
  });

  beforeEach(() => {
    clearBetSlip();
    apiMocks.getLineups.mockResolvedValue(emptyLineups);
  });

  afterEach(() => {
    clearBetSlip();
  });

  it("prints the sentence on the slip when an Out leg is in the average's exclusion", async () => {
    seedBetSlip([leg]);
    apiMocks.getDailyPicks.mockResolvedValue({
      ...todayPicks,
      picks: [{ ...bam, tier: null, ...outSample }],
    });
    renderWithProviders(<BetSlipScreen />);
    expect(await screen.findByText(/Avg and all hit leave out Out legs/)).toBeInTheDocument();
    const card = await screen.findByRole("article");
    expect(within(card).getByText("Out")).toHaveAttribute("data-injury-tone", "out");
    expect(within(card).getByText("Out").closest(".opacity-60")).toBeNull();
    expect(card.querySelector(".opacity-60")).not.toBeNull();
    expect(injuryTagForPlayer([{ ...bam, injury_status: "Out" }], bam.event_id, bam.player_name)?.tone).toBe("out");
  });

  it("omits the sentence when every leg is still in the average", async () => {
    seedBetSlip([leg]);
    apiMocks.getDailyPicks.mockResolvedValue({
      ...todayPicks,
      picks: [{ ...bam, tier: null, ...doubtfulSample }],
    });
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    expect(within(card).getByText("Doubtful")).toHaveAttribute("data-injury-tone", "doubtful");
    expect(card).toHaveTextContent("60%");
    await waitFor(() => expect(apiMocks.getDailyPicks).toHaveBeenCalled());
    expect(screen.queryByText(/leave out Out legs/)).not.toBeInTheDocument();
  });
});
