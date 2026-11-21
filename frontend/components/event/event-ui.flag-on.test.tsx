import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EventActionBar } from "@/components/event/EventActionBar";
import { OurRead } from "@/components/event/OurRead";
import { buildOurRead, buildReadSignals } from "@/lib/event-page";
import { dailyPicksResponseSchema } from "@/lib/schemas";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import { renderWithProviders } from "@/test/test-utils";

vi.mock("next/navigation", () => ({
  usePathname: () => "/event/evt-mia-bos",
}));

vi.mock("@/lib/agent-chat-ui", () => ({
  AGENT_CHAT_UI_ENABLED: true,
}));

const bamPick = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];

const model = buildOurRead({
  player: bamPick.player_name,
  marketName: "Points",
  market: "player_points",
  binary: false,
  eventId: bamPick.event_id,
  homeTeam: bamPick.home_team,
  awayTeam: bamPick.away_team,
  commenceTime: bamPick.commence_time,
  team: bamPick.player_team,
  position: null,
  line: bamPick.threshold,
  pick: bamPick,
  consensus: null,
  last10: [],
  history: null,
  league: "nba",
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
