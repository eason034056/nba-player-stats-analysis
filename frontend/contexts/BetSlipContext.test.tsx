import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useBetSlip } from "@/contexts/BetSlipContext";
import { getTodayString } from "@/lib/utils";
import { clearBetSlip, createBetSlipPick, renderWithProviders } from "@/test/test-utils";

const LEGACY_EVENT_ID = "07361a8381206817e27bd2697fad7479";
const MIXED_CASE_LEGACY_EVENT_ID = "ABCDEF0123456789abcdef0123456789";
const LIVE_EVENT_ID = "184729";
const STALE_EVENT_ID = "not-on-slate";

const apiMocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, getEvents: apiMocks.getEvents };
});

function SlipIds() {
  const { picks } = useBetSlip();
  return <div data-testid="slip-ids">{picks.map((pick) => pick.event_id).join(",")}</div>;
}

function storedEventIds(): string[] {
  const raw = window.localStorage.getItem("betslip_picks");
  const parsed = JSON.parse(raw ?? "[]") as Array<{ event_id?: string }>;
  return parsed.map((pick) => pick.event_id ?? "");
}

function slate(eventIds: string[]) {
  return {
    date: getTodayString(),
    events: eventIds.map((event_id) => ({
      event_id,
      sport_key: "basketball_nba",
      home_team: "Miami Heat",
      away_team: "Oklahoma City Thunder",
      commence_time: "2026-11-25T00:00:00Z",
    })),
  };
}

describe("bet slip hydrate", () => {
  beforeEach(() => {
    clearBetSlip();
    window.localStorage.removeItem("wnba_betslip_picks");
    apiMocks.getEvents.mockReset();
  });

  it("drops a 32-hex event id and the retired slip key", async () => {
    window.localStorage.setItem("wnba_betslip_picks", "{not-json");
    window.localStorage.setItem(
      "betslip_picks",
      JSON.stringify([
        createBetSlipPick({ id: "legacy", event_id: LEGACY_EVENT_ID }),
        createBetSlipPick({ id: "legacy-upper", event_id: MIXED_CASE_LEGACY_EVENT_ID }),
        createBetSlipPick({ id: "live", event_id: LIVE_EVENT_ID }),
      ]),
    );
    apiMocks.getEvents.mockReturnValue(new Promise(() => {}));

    const { queryClient } = renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(screen.getByTestId("slip-ids").textContent).toBe(LIVE_EVENT_ID);
    });
    expect(queryClient.getQueryState(["events", getTodayString()])?.status).toBe("pending");
    expect(storedEventIds()).toEqual([LIVE_EVENT_ID]);
    expect(window.localStorage.getItem("wnba_betslip_picks")).toBeNull();
    expect(window.localStorage.getItem("betslip_picks")).not.toBeNull();
  });

  it("drops a pick that is not on today's events list and keeps one that is", async () => {
    window.localStorage.setItem(
      "betslip_picks",
      JSON.stringify([
        createBetSlipPick({ id: "legacy", event_id: LEGACY_EVENT_ID }),
        createBetSlipPick({ id: "stale", event_id: STALE_EVENT_ID }),
        createBetSlipPick({ id: "live", event_id: LIVE_EVENT_ID }),
      ]),
    );
    apiMocks.getEvents.mockResolvedValue(slate([LIVE_EVENT_ID]));

    const { queryClient } = renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(queryClient.getQueryState(["events", getTodayString()])?.status).toBe("success");
      expect(screen.getByTestId("slip-ids").textContent).toBe(LIVE_EVENT_ID);
    });
    expect(storedEventIds()).toEqual([LIVE_EVENT_ID]);
    expect(apiMocks.getEvents).toHaveBeenCalledWith(getTodayString());
  });

  it("does not drop a pick for missing events when the events request fails", async () => {
    window.localStorage.setItem(
      "betslip_picks",
      JSON.stringify([
        createBetSlipPick({ id: "legacy", event_id: LEGACY_EVENT_ID }),
        createBetSlipPick({ id: "stale", event_id: STALE_EVENT_ID }),
        createBetSlipPick({ id: "live", event_id: LIVE_EVENT_ID }),
      ]),
    );
    apiMocks.getEvents.mockRejectedValue(new Error("events down"));

    const { queryClient } = renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(queryClient.getQueryState(["events", getTodayString()])?.status).toBe("error");
      expect(screen.getByTestId("slip-ids").textContent).toBe(`${STALE_EVENT_ID},${LIVE_EVENT_ID}`);
    });
    expect(storedEventIds()).toEqual([STALE_EVENT_ID, LIVE_EVENT_ID]);
  });
});
