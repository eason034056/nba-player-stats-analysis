import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OurRead } from "@/components/event/OurRead";
import { buildOurRead } from "@/lib/event-page";
import { dailyPicksResponseSchema } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";

const bam = dailyPicksResponseSchema.parse(nbaPicksFixture).picks[0];

describe("NBA signal rows", () => {
  it("keeps the value and verdict in a shrink-0 column on mobile", () => {
    const model = buildOurRead({
      player: "Evan Mobley",
      marketName: "Points",
      market: "player_points",
      binary: false,
      eventId: "evt-cle-orl",
      homeTeam: "Orlando Magic",
      awayTeam: "Cleveland Cavaliers",
      commenceTime: "2026-11-12T00:00:00Z",
      team: "CLE",
      position: "PF",
      line: 21.5,
      pick: {
        ...bam,
        player_name: "Evan Mobley",
        direction: "under",
        threshold: 21.5,
        combined_probability: 0.67,
        signals: [
          {
            key: "market",
            label: "Market price",
            value: "62%",
            verdict: "supports",
          },
        ],
      },
      consensus: null,
      last10: [],
      history: null,
      league: "nba",
    });

    renderWithProviders(
      <OurRead
        league="nba"
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

    const row = screen.getByTestId("signal-market");
    expect(row.className).toContain("max-md:flex-nowrap");
    const label = screen.getByTestId("signal-label-market");
    expect(label.className).toContain("min-w-0");
    expect(label.className).toContain("flex-1");
    expect(label.className).toContain("md:basis-60");
    expect(label.className).not.toMatch(/(?:^|\s)basis-60(?:\s|$)/);
    const value = screen.getByTestId("signal-value-market");
    expect(value.className).toContain("shrink-0");
    expect(value.className).toContain("items-end");
    expect(value.className).toContain("md:hidden");
    expect(value).toHaveTextContent("62%");
    expect(value).toHaveTextContent("Supports");
  });
});
