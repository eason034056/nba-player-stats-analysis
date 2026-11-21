import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EventActionBar } from "@/components/event/EventActionBar";
import { OurRead } from "@/components/event/OurRead";
import { buildOurRead, buildReadSignals } from "@/lib/event-page";
import { dailyPicksResponseSchema } from "@/lib/schemas";
import wnbaPicksFixture from "@/test/fixtures/event/wnba-daily-picks.json";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("next/navigation", () => ({
  usePathname: () => "/event/wnba-1",
}));

vi.mock("@/lib/agent-chat-ui", () => ({
  AGENT_CHAT_UI_ENABLED: true,
}));

const wilsonPick = dailyPicksResponseSchema.parse(wnbaPicksFixture).picks[0];

const model = buildOurRead({
  player: "A'ja Wilson",
  marketName: "Points",
  market: "player_points",
  binary: false,
  eventId: "wnba-1",
  homeTeam: "Las Vegas Aces",
  awayTeam: "New York Liberty",
  commenceTime: "2026-11-11T00:00:00Z",
  team: "LVA",
  position: null,
  line: wilsonPick.threshold,
  pick: wilsonPick,
  consensus: null,
  last10: [],
  history: null,
  league: "wnba",
});

describe("event ask controls with the agent chat UI on", () => {
  it("asks the agent", async () => {
    const onAsk = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <OurRead
        model={model}
        isLoading={false}
        isError={false}
        errorText={null}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={vi.fn()}
        onAddOther={vi.fn()}
        onAsk={onAsk}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Ask the agent" }));
    expect(onAsk).toHaveBeenCalled();
    expect(buildReadSignals({
      binary: false,
      line: null,
      consensus: null,
      last10: [],
      history: null,
      pick: null,
      market: "player_points",
    }).every((signal) => signal.value === null)).toBe(true);
  });

  it("asks from the mobile bar", async () => {
    const onAsk = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <EventActionBar
        league="nba"
        model={model}
        primaryInSlip={false}
        otherInSlip={false}
        onAddPrimary={vi.fn()}
        onAddOther={vi.fn()}
        onAsk={onAsk}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^ask$/i }));
    expect(onAsk).toHaveBeenCalled();
  });
});
