import type { ReactNode } from "react";
import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DailyPicksBoard, type DailyPicksBoardProps } from "@/components/picks/DailyPicksBoard";
import { OurRead } from "@/components/event/OurRead";
import { buildOurRead } from "@/lib/event-page";
import { pickTags } from "@/lib/picks-board";
import { dailyPicksResponseSchema, type DailyPick } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
// Serialized by backend PR #69 (e5ee1e5): DailyPicksResponse.model_dump_json()
// with DailyPick defaults and build_nba_signals(projected_value=None).
// Every projection, edge, minutes, injury, and lineup field is null.
import spo135Fixture from "@/test/fixtures/picks/nba-daily-picks-spo135.json";

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

const NULL_FIELDS = [
  "projected_value",
  "projected_minutes",
  "edge",
  "injury_status",
  "lineup_confirmed",
] as const;

function parsed() {
  return dailyPicksResponseSchema.parse(spo135Fixture);
}

function boardProps(picks: DailyPick[]): DailyPicksBoardProps {
  return {
    league: "nba",
    selectedDate: "2026-11-11",
    onDateChange: vi.fn(),
    analyzedAt: "2026-11-11T12:00:00Z",
    isStale: false,
    picks,
    isLoading: false,
    isError: false,
    errorMessage: null,
    onRetry: vi.fn(),
    onReanalyze: vi.fn(),
    isReanalyzing: false,
    emptyMessage: null,
    minProbability: 0,
    teams: [],
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
  };
}

function nbaRead(pick: DailyPick, league: "nba" | "wnba" = "nba") {
  return buildOurRead({
    player: pick.player_name,
    marketName: "Points",
    market: "player_points",
    binary: false,
    eventId: pick.event_id,
    homeTeam: pick.home_team,
    awayTeam: pick.away_team,
    commenceTime: pick.commence_time,
    team: null,
    position: null,
    line: pick.threshold,
    pick,
    consensus: null,
    last10: [],
    history: null,
    league,
  });
}

function renderRead(model: ReturnType<typeof nbaRead>, league: "nba" | "wnba") {
  return renderWithProviders(
    <OurRead
      league={league}
      model={model}
      isLoading={false}
      isError={false}
      errorText={null}
      primaryInSlip={false}
      otherInSlip={false}
      onAddPrimary={() => {}}
      onAddOther={() => {}}
      onAsk={() => {}}
    />,
  );
}

describe("QA: the #69 daily-picks response parses", () => {
  it("keeps explicit nulls instead of failing the parse", () => {
    const result = dailyPicksResponseSchema.safeParse(spo135Fixture);
    expect(result.success).toBe(true);
    const picks = result.success ? result.data.picks : [];
    expect(picks).toHaveLength(2);
    for (const pick of picks) {
      expect(pick.has_projection).toBe(false);
      for (const field of NULL_FIELDS) expect(pick[field]).toBeNull();
    }
  });

  it.each(NULL_FIELDS)("a pick whose %s is null still parses", (field) => {
    const raw = structuredClone(spo135Fixture) as { picks: Record<string, unknown>[] };
    raw.picks[0][field] = null;
    expect(dailyPicksResponseSchema.safeParse(raw).success).toBe(true);
  });
});

describe("QA: null fields render no tag on the picks board", () => {
  it("builds no projection, edge, minutes, injury, or lineup tag", () => {
    for (const pick of parsed().picks) {
      const text = pickTags(pick)
        .map((tag) => tag.text)
        .join(" | ");
      expect(text).not.toMatch(/Proj|Edge|\bmin\b|NaN|Healthy|Confirmed|confirmed|Lineup|null|undefined|\b0\b/);
    }
  });

  it("shows the floored blend and no misleading text on either card", () => {
    renderWithProviders(<DailyPicksBoard {...boardProps(parsed().picks)} />);
    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(2);
    // combined_probability 0.7956 with tier Strong play floors to 79%.
    expect(within(cards[0]).getByText("79%")).toBeInTheDocument();
    expect(cards[0].textContent ?? "").not.toContain("80%");
    for (const card of cards) {
      expect(card.textContent ?? "").not.toMatch(/NaN|Healthy|Lineup confirmed|Lineup unconfirmed|Proj |Edge |undefined|null/);
    }
  });
});

describe("QA: projection row on the read", () => {
  it("hides the null NBA projection row and keeps the other four signals", () => {
    const pick = parsed().picks[0];
    renderRead(nbaRead(pick), "nba");
    expect(screen.queryByTestId("signal-projection")).not.toBeInTheDocument();
    for (const key of ["market", "last10", "history", "defense"]) {
      expect(screen.getByTestId(`signal-${key}`)).toBeInTheDocument();
    }
  });

  it("shows the NBA projection row again once the backend writes a value", () => {
    const pick = parsed().picks[0];
    const withValue: DailyPick = {
      ...pick,
      has_projection: true,
      projected_value: 20.4,
      edge: 1.9,
      signals: (pick.signals ?? []).map((signal) =>
        signal.key === "projection" ? { ...signal, value: "20.4", verdict: "supports" } : signal,
      ),
    };
    renderRead(nbaRead(withValue), "nba");
    expect(screen.getByTestId("signal-projection")).toHaveTextContent("20.4");
  });

  it("a pick with no signals says so instead of counting zero", () => {
    const herro = parsed().picks[1];
    const model = nbaRead(herro);
    expect(model.signals).toEqual([]);
    expect(model.caption).toContain("Signal verdicts are not on this response.");
    expect(model.caption).not.toMatch(/\b0 of\b/);
  });

  it("WNBA still lists its projection row with the not-available note", () => {
    const pick = parsed().picks[0];
    const wnbaPick: DailyPick = { ...pick, signals: null, tier: null, combined_probability: null };
    renderRead(nbaRead(wnbaPick, "wnba"), "wnba");
    expect(screen.getByTestId("signal-projection")).toHaveTextContent("Projection is not available for WNBA.");
  });
});
