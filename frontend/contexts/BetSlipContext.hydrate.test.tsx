import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useBetSlip } from "@/contexts/BetSlipContext";
import { eventsResponseSchema } from "@/lib/schemas";
import { getLocalDateString, getTodayString } from "@/lib/utils";
import { clearBetSlip, createBetSlipPick, renderWithProviders } from "@/test/test-utils";
import bdlGames from "../../backend/tests/fixtures/same_slate/2026-11-22_OKC@MIA__bdl_games.json";
import emptyEventsFixture from "@/test/fixtures/today/nba-events-empty.json";

const emptyEvents = eventsResponseSchema.parse(emptyEventsFixture);
const bdlGameIds = bdlGames.response.data.map((game) => String(game.id));
const BDL_GAME_ID = bdlGameIds[0];
const HEX = "07361a8381206817e27bd2697fad7479";
const HEX_UPPER = "ABCDEF0123456789ABCDEF0123456789";

function tomorrowCommence(): string {
  const [year, month, day] = getTodayString().split("-").map(Number);
  return new Date(year, month - 1, day + 1, 19, 0, 0).toISOString();
}

function SlipIds() {
  const { picks } = useBetSlip();
  return <div data-testid="slip-ids">{picks.map((pick) => String(pick.event_id)).join(",")}</div>;
}

function seed(picks: unknown[]) {
  window.localStorage.setItem("betslip_picks", JSON.stringify(picks));
}

function storedIds(): string[] {
  const parsed = JSON.parse(window.localStorage.getItem("betslip_picks") ?? "[]") as Array<{
    event_id?: unknown;
  }>;
  return parsed.map((pick) => String(pick.event_id));
}

describe("bet slip hydrate without a slate filter", () => {
  beforeEach(() => {
    clearBetSlip();
    window.localStorage.removeItem("wnba_betslip_picks");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps a recorded BALLDONTLIE game id and a tomorrow commence time", async () => {
    expect(BDL_GAME_ID).toMatch(/^\d+$/);
    expect(Math.max(...bdlGameIds.map((id) => id.length))).toBeLessThan(32);
    const commence = tomorrowCommence();
    expect(getLocalDateString(commence)).not.toBe(getTodayString());
    seed([
      createBetSlipPick({ id: "bdl", event_id: BDL_GAME_ID, commence_time: bdlGames.response.data[0].date }),
      createBetSlipPick({
        id: "tomorrow",
        player_name: "Tomorrow Player",
        metric: "rebounds",
        event_id: "tomorrow-game",
        commence_time: commence,
      }),
      createBetSlipPick({ id: "legacy", event_id: HEX }),
    ]);

    renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(screen.getByTestId("slip-ids").textContent).toBe(`${BDL_GAME_ID},tomorrow-game`);
    });
    expect(storedIds()).toEqual([BDL_GAME_ID, "tomorrow-game"]);
  });

  it("does not clear the slip when the events list is empty or absent", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", (async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return Response.json(emptyEventsFixture);
    }) as typeof fetch);
    seed([
      createBetSlipPick({ id: "bdl", event_id: BDL_GAME_ID }),
      createBetSlipPick({ id: "tomorrow", event_id: "tomorrow-game", commence_time: tomorrowCommence() }),
    ]);

    const { queryClient } = renderWithProviders(<SlipIds />);
    queryClient.setQueryData(["events", getTodayString()], emptyEvents);
    queryClient.setQueryData(["events", "all"], emptyEvents);

    await waitFor(() => {
      expect(screen.getByTestId("slip-ids").textContent).toBe(`${BDL_GAME_ID},tomorrow-game`);
    });
    expect(calls.filter((url) => url.includes("/events"))).toEqual([]);
    expect(storedIds()).toEqual([BDL_GAME_ID, "tomorrow-game"]);
  });

  it("removes the retired wnba key and leaves the nba slip", async () => {
    window.localStorage.setItem("wnba_betslip_picks", JSON.stringify([{ id: "old" }]));
    seed([createBetSlipPick({ id: "bdl", event_id: BDL_GAME_ID })]);

    renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(window.localStorage.getItem("wnba_betslip_picks")).toBeNull();
    });
    expect(screen.getByTestId("slip-ids").textContent).toBe(BDL_GAME_ID);
    expect(window.localStorage.getItem("betslip_picks")).not.toBeNull();
  });

  it("drops a 32-character id only when it contains a letter a-f", async () => {
    const numeric32 = "1".repeat(32);
    const numeric31 = "1".repeat(31);
    const numeric33 = "1".repeat(33);
    const hex31 = "a".repeat(31);
    const hex33 = "b".repeat(33);
    seed([
      createBetSlipPick({ id: "upper", player_name: "Upper", metric: "points", event_id: HEX_UPPER }),
      createBetSlipPick({ id: "hex31", player_name: "H31", metric: "points", event_id: hex31 }),
      createBetSlipPick({ id: "hex33", player_name: "H33", metric: "points", event_id: hex33 }),
      createBetSlipPick({ id: "n32", player_name: "N32", metric: "points", event_id: numeric32 }),
      createBetSlipPick({ id: "n31", player_name: "N31", metric: "points", event_id: numeric31 }),
      createBetSlipPick({ id: "n33", player_name: "N33", metric: "points", event_id: numeric33 }),
      { ...createBetSlipPick({ id: "numeric-type", player_name: "Num", metric: "assists" }), event_id: Number(BDL_GAME_ID) },
      { ...createBetSlipPick({ id: "missing", player_name: "Missing", metric: "steals" }), event_id: null },
    ]);

    renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(screen.getByTestId("slip-ids").textContent).toBe(
        [hex31, hex33, numeric32, numeric31, numeric33, BDL_GAME_ID, "null"].join(","),
      );
    });
    expect(storedIds()).not.toContain(HEX_UPPER.toLowerCase());
    expect(storedIds()).toContain(numeric32);
  });
});
