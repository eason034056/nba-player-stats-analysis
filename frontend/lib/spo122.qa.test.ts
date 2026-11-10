import { afterEach, describe, expect, it, vi } from "vitest";

import { getPlayerHistory, getWNBAPlayerHistory } from "@/lib/api";
import { eventPlayerRows, eventTeammates } from "@/lib/event-page";
import { dailyPicksResponseSchema, teamLineupSchema, type DailyPick } from "@/lib/schemas";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import nbaHistoryFixture from "@/test/fixtures/event/nba-history-bam.json";

const basePick = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];

function pick(overrides: Partial<DailyPick> = {}): DailyPick {
  return { ...basePick, ...overrides };
}

function lineup(team: string, starters: string[], bench: string[] = []) {
  return teamLineupSchema.parse({
    date: "2026-11-10",
    team,
    status: "projected",
    confidence: "medium",
    starters,
    bench_candidates: bench,
  });
}

const rowArgs = {
  metric: "player_points",
  eventId: "bos-phi",
  selectedName: "",
  postedLine: null,
  awayAbbr: "BOS",
  homeAbbr: "PHI",
  league: "nba" as const,
};

describe("SPO-122 event label with a blank backend team", () => {
  it("leaves a blank pick team unlabeled instead of borrowing a side", () => {
    const rows = eventPlayerRows({
      ...rowArgs,
      suggested: ["Anfernee Simons"],
      picks: [
        pick({
          player_name: "Anfernee Simons",
          player_team: "",
          player_team_code: "",
          event_id: "bos-phi",
          home_team: "Philadelphia 76ers",
          away_team: "Boston Celtics",
        }),
      ],
      awayLineup: null,
      homeLineup: null,
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].team).toBeNull();
    expect(rows[0].hasLean).toBe(true);
  });

  it("keeps a pick club that is in the game when there is no lineup", () => {
    const rows = eventPlayerRows({
      ...rowArgs,
      suggested: [],
      picks: [
        pick({
          player_name: "Derrick White",
          player_team: "Celtics",
          player_team_code: "BOS",
          event_id: "bos-phi",
        }),
      ],
      awayLineup: null,
      homeLineup: null,
    });
    expect(rows[0].team).toBe("BOS");
  });

  it("does not pick a side for a name on both lineups", () => {
    const rows = eventPlayerRows({
      ...rowArgs,
      suggested: ["Same Name"],
      picks: [],
      awayLineup: lineup("BOS", ["Same Name"]),
      homeLineup: lineup("PHI", ["Same Name"]),
    });
    expect(rows[0].team).toBeNull();
  });
});

describe("SPO-122 eventTeammates", () => {
  it("returns history only when the player is on both lineups", () => {
    expect(
      eventTeammates({
        player: "Same Name",
        awayLineup: lineup("BOS", ["Same Name", "Derrick White"]),
        homeLineup: lineup("PHI", ["Same Name", "Tyrese Maxey"]),
        historyTeammates: ["History Mate"],
      }),
    ).toEqual(["History Mate"]);
  });

  it("appends only the player's own side and keeps history order", () => {
    expect(
      eventTeammates({
        player: "anfernee simons",
        awayLineup: lineup("BOS", ["Derrick White"], ["Anfernee Simons", "Sam Hauser"]),
        homeLineup: lineup("PHI", ["Tyrese Maxey", "Joel Embiid"]),
        historyTeammates: ["Jayson Tatum", "derrick white "],
      }),
    ).toEqual(["Jayson Tatum", "derrick white", "Sam Hauser"]);
  });

  it("drops the player from history and lineup in any case or spacing", () => {
    const mates = eventTeammates({
      player: "Anfernee Simons",
      awayLineup: lineup("BOS", [" ANFERNEE SIMONS ", "Derrick White"]),
      homeLineup: null,
      historyTeammates: ["anfernee simons", "Jayson Tatum", "", "  "],
    });
    expect(mates).toEqual(["Jayson Tatum", "Derrick White"]);
  });

  it("returns an empty list when scoped history is empty and no lineup has the player", () => {
    expect(
      eventTeammates({
        player: "Anfernee Simons",
        awayLineup: lineup("BOS", ["Derrick White"]),
        homeLineup: lineup("PHI", ["Tyrese Maxey"]),
        historyTeammates: [],
      }),
    ).toEqual([]);
  });

  it("uses the lineup alone when the scoped history is empty", () => {
    expect(
      eventTeammates({
        player: "Anfernee Simons",
        awayLineup: lineup("BOS", ["Derrick White", "Derrick White"], ["Anfernee Simons"]),
        homeLineup: null,
        historyTeammates: [],
      }),
    ).toEqual(["Derrick White"]);
  });
});

describe("SPO-122 player-history query", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubFetch() {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(nbaHistoryFixture), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  function sentParams(fetchMock: ReturnType<typeof stubFetch>): URLSearchParams {
    const url = String((fetchMock.mock.calls[0] as unknown[])[0]);
    return new URL(url).searchParams;
  }

  it("sends both event clubs and the tip on the NBA route", async () => {
    const fetchMock = stubFetch();
    await getPlayerHistory({
      player: "Anfernee Simons",
      metric: "points",
      threshold: 9.5,
      home_team: "Philadelphia 76ers",
      away_team: "Boston Celtics",
      as_of: "2026-11-11T01:10:00Z",
    });
    const params = sentParams(fetchMock);
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain("/api/nba/player-history?");
    expect(params.get("home_team")).toBe("Philadelphia 76ers");
    expect(params.get("away_team")).toBe("Boston Celtics");
    expect(params.get("as_of")).toBe("2026-11-11T01:10:00Z");
  });

  it("omits blank event fields so the player page keeps every stint", async () => {
    const fetchMock = stubFetch();
    await getPlayerHistory({
      player: "Anfernee Simons",
      metric: "points",
      threshold: 9.5,
      home_team: "",
      away_team: "",
      as_of: "",
    });
    const params = sentParams(fetchMock);
    expect(params.has("home_team")).toBe(false);
    expect(params.has("away_team")).toBe(false);
    expect(params.has("as_of")).toBe(false);
  });

  it("sends the event clubs on the WNBA route too", async () => {
    const fetchMock = stubFetch();
    await getWNBAPlayerHistory({
      player: "Napheesa Collier",
      metric: "points",
      threshold: 20.5,
      home_team: "Minnesota Lynx",
      away_team: "Chicago Sky",
    });
    const url = String((fetchMock.mock.calls[0] as unknown[])[0]);
    expect(url).toContain("/api/wnba/player-history?");
    const params = new URL(url).searchParams;
    expect(params.get("home_team")).toBe("Minnesota Lynx");
    expect(params.get("away_team")).toBe("Chicago Sky");
    expect(params.has("as_of")).toBe(false);
  });
});
