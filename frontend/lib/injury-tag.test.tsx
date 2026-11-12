import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InjuryStatusTag } from "@/components/InjuryStatusTag";
import { BetSlipScreen } from "@/components/betslip/BetSlipScreen";
import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { OUT_LEGS_NOTE, slipSummaryCaption } from "@/lib/bet-slip-board";
import { buildOurRead, eventPlayerRows } from "@/lib/event-page";
import { INJURY_WORDS, canonicalInjuryTag, injuryTag } from "@/lib/injury-tag";
import { injuryTagForPlayer, isOutPick, isPlayerOutInGame } from "@/lib/picks-board";
import {
  dailyPickSchema,
  dailyPicksResponseSchema,
  lineupsResponseSchema,
  propReadSchema,
  teamLineupSchema,
  topReadSchema,
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
import rawInjuryFixture from "@/test/fixtures/picks/nba-daily-picks-raw-injury.json";
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

const todayPicks = dailyPicksResponseSchema.parse(todayPicksFixture);
const emptyLineups = lineupsResponseSchema.parse(emptyLineupsFixture);
const [doubtful, listedOut, wnbaQuiet, lowerOut] = rawInjuryFixture.picks.map((pick) =>
  dailyPickSchema.parse(pick),
);

function channel(hex: string, index: number): number {
  const raw = parseInt(hex.replace("#", "").slice(index, index + 2), 16) / 255;
  return raw <= 0.04045 ? raw / 12.92 : ((raw + 0.055) / 1.055) ** 2.4;
}

function chipColors(chip: Element): { fg: string; bg: string } {
  const className = chip.getAttribute("class") ?? "";
  const background = className.match(/bg-\[(#[0-9A-Fa-f]{6})\]/)?.[1];
  const foreground = className.includes("text-white")
    ? "#FFFFFF"
    : className.match(/text-\[(#[0-9A-Fa-f]{6})\]/)?.[1];
  if (!background || !foreground) {
    throw new Error(`rendered chip has no colour classes: ${className}`);
  }
  return { fg: foreground, bg: background };
}

function toneOf(label: HTMLElement): string | null {
  return label.closest("[data-injury-tone]")?.getAttribute("data-injury-tone") ?? null;
}

function isGreen(hex: string): boolean {
  const red = parseInt(hex.slice(1, 3), 16);
  const green = parseInt(hex.slice(3, 5), 16);
  const blue = parseInt(hex.slice(5, 7), 16);
  return green > red && green > blue;
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

    const picks = rawInjuryFixture.picks.map((pick) => dailyPickSchema.parse(pick));
    expect(picks.map((pick) => [pick.player_name, pick.injury_status, pick.injury_status_raw, pick.combined_probability])).toEqual([
      ["Bam Adebayo", "Questionable", "Doubtful", 0.6095],
      ["Jimmy Butler", "Out", "Out", null],
      ["A'ja Wilson", null, null, null],
      ["Tyler Herro", "Questionable", "out", 0.6095],
    ]);
    expect(isOutPick(lowerOut)).toBe(false);
    expect(lowerOut.injury_status_raw).toBe("out");
    expect(injuryTag(lowerOut.injury_status_raw, lowerOut.injury_status)).toEqual({ text: "Out", tone: "out" });
    expect(injuryTag(wnbaQuiet.injury_status_raw, wnbaQuiet.injury_status)).toBeNull();
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
      const view = renderWithProviders(<InjuryStatusTag tag={canonicalInjuryTag(word.tone)} />);
      const label = screen.getByText(word.label);
      const chip = label.closest("[data-injury-tone]");
      if (!chip) throw new Error("chip missing");
      expect(chip).toHaveAttribute("data-injury-tone", word.tone);
      const prefix = chip.firstElementChild;
      expect(prefix?.textContent).toContain("Injury:");
      expect(prefix?.classList.contains("sr-only")).toBe(true);
      const colors = chipColors(chip);
      const pair = `${colors.fg}/${colors.bg}`;
      expect(seen.has(pair)).toBe(false);
      seen.add(pair);
      expect(contrast(colors.fg, colors.bg)).toBeGreaterThanOrEqual(4.5);
      if (word.tone === "probable") {
        expect(chip.className).toContain("border-dotted");
        expect(isGreen(colors.fg)).toBe(false);
        expect(isGreen(colors.bg)).toBe(false);
      }
      view.unmount();
    }
    renderWithProviders(<InjuryStatusTag tag={{ text: "GTD", tone: "neutral" }} />);
    const neutral = screen.getByText("GTD").closest("[data-injury-tone]");
    if (!neutral) throw new Error("neutral chip missing");
    const neutralColors = chipColors(neutral);
    expect(contrast(neutralColors.fg, neutralColors.bg)).toBeGreaterThanOrEqual(4.5);
  });
});

describe("Doubtful does not block", () => {
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
    expect(toneOf(chip)).toBe("doubtful");
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
    const quiet = wnbaQuiet;
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
    id: "Bam Adebayo-points",
    player_name: doubtful.player_name,
    event_id: doubtful.event_id,
    player_team: doubtful.player_team,
    home_team: doubtful.home_team,
    away_team: doubtful.away_team,
    commence_time: doubtful.commence_time,
    metric: doubtful.metric,
    threshold: doubtful.threshold,
    probability: 0.6095,
    combined_probability: 0.6095,
    tier: "Playable",
  });

  const outLeg = createBetSlipPick({
    id: "Jimmy Butler-points",
    player_name: listedOut.player_name,
    event_id: listedOut.event_id,
    player_team: listedOut.player_team,
    home_team: listedOut.home_team,
    away_team: listedOut.away_team,
    commence_time: listedOut.commence_time,
    metric: listedOut.metric,
    threshold: listedOut.threshold,
    probability: 0.7,
    combined_probability: 0.7,
    tier: null,
  });

  beforeEach(() => {
    clearBetSlip();
    apiMocks.getLineups.mockResolvedValue(emptyLineups);
  });

  afterEach(() => {
    clearBetSlip();
  });

  it("prints the sentence on the slip when an Out leg is in the average's exclusion", async () => {
    seedBetSlip([outLeg]);
    apiMocks.getDailyPicks.mockResolvedValue({
      ...todayPicks,
      picks: [listedOut],
    });
    renderWithProviders(<BetSlipScreen />);
    expect(await screen.findByText(/Avg and all hit leave out Out legs/)).toBeInTheDocument();
    const card = await screen.findByRole("article");
    expect(toneOf(within(card).getByText("Out"))).toBe("out");
    expect(card).not.toHaveTextContent("%");
    expect(injuryTagForPlayer([listedOut], listedOut.event_id, listedOut.player_name)?.text).toBe("Out");
  });

  it("omits the sentence when every leg is still in the average", async () => {
    seedBetSlip([leg]);
    apiMocks.getDailyPicks.mockResolvedValue({
      ...todayPicks,
      picks: [doubtful],
    });
    renderWithProviders(<BetSlipScreen />);
    const card = await screen.findByRole("article");
    expect(toneOf(within(card).getByText("Doubtful"))).toBe("doubtful");
    expect(card).toHaveTextContent("60%");
    await waitFor(() => expect(apiMocks.getDailyPicks).toHaveBeenCalled());
    expect(screen.queryByText(/leave out Out legs/)).not.toBeInTheDocument();
  });
});
