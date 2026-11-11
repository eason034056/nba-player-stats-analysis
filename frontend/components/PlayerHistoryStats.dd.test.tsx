import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlayerHistoryStats } from "@/components/PlayerHistoryStats";
import wilsonHistory from "@/test/fixtures/player-dd-history/wilson.json";
import recordedNoVig from "@/test/fixtures/props-no-vig/player-double-double.json";
import { renderWithProviders } from "@/test/test-utils";

describe("PlayerHistoryStats double-double wiring", () => {
  it("loads the WNBA tile from the event id and does not call the continuous history route", async () => {
    const historyFn = vi.fn().mockResolvedValue(wilsonHistory);
    const oddsFn = vi.fn().mockResolvedValue(recordedNoVig);
    const continuousHistory = vi.fn();

    renderWithProviders(
      <PlayerHistoryStats
        eventId="wnba-evt"
        initialPlayer="A'ja Wilson"
        initialMarket="player_double_double"
        cacheNamespace="wnba"
        getCSVPlayersFn={vi.fn().mockResolvedValue({ players: [], total: 0 })}
        getPlayerHistoryFn={continuousHistory}
        getPlayerDDHistoryFn={historyFn}
        calculateNoVigFn={oddsFn}
      />,
    );

    expect(await screen.findByText("47%")).toBeInTheDocument();
    expect(screen.getByText("26 of 55 games")).toBeInTheDocument();
    expect(screen.getByText("-250")).toBeInTheDocument();
    expect(screen.getByText("+200")).toBeInTheDocument();
    expect(historyFn).toHaveBeenCalledWith({ player: "A'ja Wilson" });
    expect(oddsFn).toHaveBeenCalledWith(
      expect.objectContaining({
        event_id: "wnba-evt",
        player_name: "A'ja Wilson",
        market: "player_double_double",
      }),
    );
    expect(continuousHistory).not.toHaveBeenCalled();
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it(
    "uses the WNBA no-vig route when cacheNamespace is wnba and no odds client is passed",
    async () => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/player-dd-history")) return Response.json(wilsonHistory);
        if (url.includes("/props/no-vig")) return Response.json(recordedNoVig);
        if (url.includes("/csv/players")) {
          return Response.json({ players: ["A'ja Wilson"], total: 1 });
        }
        return Response.json({ detail: url }, { status: 500 });
      });
      vi.stubGlobal("fetch", fetchMock);

      renderWithProviders(
        <PlayerHistoryStats
          eventId="wnba-evt"
          initialPlayer="A'ja Wilson"
          initialMarket="player_double_double"
          cacheNamespace="wnba"
        />,
      );

      expect(await screen.findByText("47%")).toBeInTheDocument();
      const urls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(urls.some((url) => url.includes("/api/wnba/player-dd-history"))).toBe(true);
      expect(urls.some((url) => url.includes("/api/wnba/props/no-vig"))).toBe(true);
      expect(urls.some((url) => url.includes("/api/nba/props/no-vig"))).toBe(false);
    },
  );
});
