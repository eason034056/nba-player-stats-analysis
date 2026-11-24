import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useBetSlip } from "@/contexts/BetSlipContext";
import { clearBetSlip, createBetSlipPick, renderWithProviders } from "@/test/test-utils";

const LEGACY_EVENT_ID = "07361a8381206817e27bd2697fad7479";
const MIXED_CASE_LEGACY_EVENT_ID = "ABCDEF0123456789abcdef0123456789";
const DIGIT_EVENT_ID = "184729";
const LATER_EVENT_ID = "tomorrow-game";

function SlipIds() {
  const { picks } = useBetSlip();
  return <div data-testid="slip-ids">{picks.map((pick) => pick.event_id).join(",")}</div>;
}

function storedEventIds(): string[] {
  const raw = window.localStorage.getItem("betslip_picks");
  const parsed = JSON.parse(raw ?? "[]") as Array<{ event_id?: string }>;
  return parsed.map((pick) => pick.event_id ?? "");
}

function seed(picks: ReturnType<typeof createBetSlipPick>[]) {
  window.localStorage.setItem("betslip_picks", JSON.stringify(picks));
}

describe("bet slip hydrate", () => {
  beforeEach(() => {
    clearBetSlip();
    window.localStorage.removeItem("wnba_betslip_picks");
  });

  it("drops a 32-hex event id", async () => {
    seed([
      createBetSlipPick({ id: "legacy", event_id: LEGACY_EVENT_ID }),
      createBetSlipPick({ id: "legacy-upper", event_id: MIXED_CASE_LEGACY_EVENT_ID }),
      createBetSlipPick({ id: "digit", event_id: DIGIT_EVENT_ID }),
    ]);

    renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(screen.getByTestId("slip-ids").textContent).toBe(DIGIT_EVENT_ID);
    });
    expect(storedEventIds()).toEqual([DIGIT_EVENT_ID]);
  });

  it("keeps a non-hex pick for an event that is not on today's slate", async () => {
    seed([createBetSlipPick({ id: "later", event_id: LATER_EVENT_ID })]);

    renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(screen.getByTestId("slip-ids").textContent).toBe(LATER_EVENT_ID);
    });
    expect(storedEventIds()).toEqual([LATER_EVENT_ID]);
  });

  it("keeps a digit-only event id", async () => {
    seed([createBetSlipPick({ id: "digit", event_id: DIGIT_EVENT_ID })]);

    renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(screen.getByTestId("slip-ids").textContent).toBe(DIGIT_EVENT_ID);
    });
    expect(storedEventIds()).toEqual([DIGIT_EVENT_ID]);
  });

  it("removes the retired wnba slip key", async () => {
    window.localStorage.setItem("wnba_betslip_picks", "{not-json");
    seed([createBetSlipPick({ id: "digit", event_id: DIGIT_EVENT_ID })]);

    renderWithProviders(<SlipIds />);

    await waitFor(() => {
      expect(window.localStorage.getItem("wnba_betslip_picks")).toBeNull();
    });
    expect(screen.getByTestId("slip-ids").textContent).toBe(DIGIT_EVENT_ID);
    expect(window.localStorage.getItem("betslip_picks")).not.toBeNull();
  });
});
