import { afterEach, describe, expect, it, vi } from "vitest";

import {
  calculateNoVig,
  calculateWNBANoVig,
  getPlayerDDHistory,
  getWNBAPlayerDDHistory,
} from "@/lib/api";
import wilsonHistory from "@/test/fixtures/player-dd-history/wilson.json";
import recordedNoVig from "@/test/fixtures/props-no-vig/player-double-double.json";

const API_ORIGIN = "/api/backend";

function jsonResponse(body: unknown): Response {
  return Response.json(body);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("double-double client routes", () => {
  it("calls the NBA history and no-vig routes on the configured origin", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/player-dd-history")) return jsonResponse(wilsonHistory);
      return jsonResponse(recordedNoVig);
    });
    vi.stubGlobal("fetch", fetchMock);

    await getPlayerDDHistory({ player: "A'ja Wilson", season: "2024" });
    await calculateNoVig({
      event_id: "evt-1",
      player_name: "A'ja Wilson",
      market: "player_double_double",
      regions: "us",
      bookmakers: null,
      odds_format: "american",
    });

    const historyUrl = String(fetchMock.mock.calls[0]?.[0]);
    const oddsCall = fetchMock.mock.calls[1];
    const oddsUrl = String(oddsCall?.[0]);
    const oddsInit = oddsCall?.[1] as RequestInit | undefined;

    expect(historyUrl.startsWith(`${API_ORIGIN}/api/nba/player-dd-history?`)).toBe(true);
    expect(historyUrl).toContain("player=A%27ja+Wilson");
    expect(historyUrl).toContain("season=2024");
    expect(historyUrl).not.toContain("threshold");
    expect(historyUrl).not.toContain("/api/wnba/");
    expect(oddsUrl).toBe(`${API_ORIGIN}/api/nba/props/no-vig`);
    expect(oddsInit?.method).toBe("POST");
    expect(JSON.parse(String(oddsInit?.body))).toMatchObject({
      event_id: "evt-1",
      player_name: "A'ja Wilson",
      market: "player_double_double",
      regions: "us",
      bookmakers: null,
      odds_format: "american",
    });
    expect(JSON.parse(String(oddsInit?.body))).not.toHaveProperty("threshold");
  });

  it("calls the WNBA history and no-vig routes, not the NBA ones", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/player-dd-history")) return jsonResponse(wilsonHistory);
      return jsonResponse(recordedNoVig);
    });
    vi.stubGlobal("fetch", fetchMock);

    const history = await getWNBAPlayerDDHistory({ player: "A'ja Wilson" });
    const odds = await calculateWNBANoVig({
      event_id: "wnba-evt",
      player_name: "A'ja Wilson",
      market: "player_double_double",
      regions: "us",
      bookmakers: null,
      odds_format: "american",
    });

    const historyUrl = String(fetchMock.mock.calls[0]?.[0]);
    const oddsUrl = String(fetchMock.mock.calls[1]?.[0]);

    expect(history.player).toBe("A'ja Wilson");
    expect(history.prob_dd).toBe(0.4727);
    expect(history.n_games).toBe(55);
    expect(odds.results[1]?.no_price).toBeNull();
    expect(odds.results[1]?.no_fair_prob).toBe(0.3245);
    expect(historyUrl.startsWith(`${API_ORIGIN}/api/wnba/player-dd-history?`)).toBe(true);
    expect(historyUrl).not.toContain("/api/nba/");
    expect(historyUrl).not.toContain("threshold");
    expect(oddsUrl).toBe(`${API_ORIGIN}/api/wnba/props/no-vig`);
  });
});
