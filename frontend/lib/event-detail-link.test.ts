import { describe, expect, it } from "vitest";

import { buildEventDetailHref } from "@/lib/event-detail-link";

describe("buildEventDetailHref", () => {
  it("keeps an explicit date when one is provided", () => {
    expect(
      buildEventDetailHref({
        eventId: "evt-1",
        date: "2026-03-16",
      }),
    ).toBe("/event/evt-1?date=2026-03-16");
  });

  it("derives a local date from commence time when date is omitted", () => {
    expect(
      buildEventDetailHref({
        eventId: "evt-1",
        commenceTime: "2026-03-17T01:00:00Z",
        player: "Stephen Curry",
        market: "player_points",
        threshold: 28.5,
      }),
    ).toBe(
      "/event/evt-1?date=2026-03-16&player=Stephen+Curry&market=player_points&threshold=28.5",
    );
  });
});
