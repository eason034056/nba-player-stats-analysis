import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EventDetail } from "@/components/EventDetail";
import {
  csvPlayersResponseSchema,
  dailyPicksResponseSchema,
  eventsResponseSchema,
} from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import eventsFixture from "@/test/fixtures/event/nba-events.json";
import emptyPicksFixture from "@/test/fixtures/event/nba-daily-picks-empty.json";
import emptyCsvFixture from "@/test/fixtures/event/csv-players-empty.json";
import notFoundFixture from "@/test/fixtures/event/http-404-malformed-event-id.json";
import noVigFixture from "@/test/fixtures/event/nba-no-vig-bam.json";

const events = eventsResponseSchema.parse(eventsFixture);
const emptyPicks = dailyPicksResponseSchema.parse(emptyPicksFixture);
const emptyCsv = csvPlayersResponseSchema.parse(emptyCsvFixture);
const HEX = "07361a8381206817e27bd2697fad7479";

const calls: Array<{ url: string; method: string; body: string | null }> = [];

function notFound(): Response {
  return Response.json(notFoundFixture, { status: 404, statusText: "Not Found" });
}

function installFetch() {
  calls.length = 0;
  const fetchMock: typeof fetch = async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body == null ? null : String(init.body);
    calls.push({ url, method, body });
    if (url.includes(`/events/${HEX}/reads`) || url.includes(`/events/${HEX}/props`)) return notFound();
    if (url.includes("/players/suggest") && url.includes(HEX)) return notFound();
    if (url.includes("/props/no-vig")) return notFound();
    if (url.includes("/daily-picks")) return Response.json(emptyPicksFixture);
    if (url.includes("/csv/players")) return Response.json(emptyCsvFixture);
    if (url.includes("/player-dd-history")) return Response.json(emptyCsvFixture);
    if (url.includes("/player-history")) return Response.json(emptyPicksFixture);
    if (url.includes("/events?")) return Response.json(eventsFixture);
    return notFound();
  };
  vi.stubGlobal("fetch", fetchMock);
}

vi.mock("next/navigation", () => ({
  useParams: () => ({ eventId: HEX }),
  usePathname: () => `/event/${HEX}`,
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => ({
    get: (key: string) => {
      if (key === "date") return events.date;
      if (key === "player") return noVigFixture.player_name;
      if (key === "market") return noVigFixture.market;
      return null;
    },
  }),
}));

describe("legacy hex event link", () => {
  beforeEach(() => {
    window.localStorage.clear();
    installFetch();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows not-found copy when the hex id 404s and is missing from the events list", async () => {
    expect(events.events.map((event) => event.event_id)).not.toContain(HEX);
    expect(emptyPicks.picks).toEqual([]);
    expect(emptyCsv.players).toEqual([]);

    renderWithProviders(<EventDetail />);

    expect((await screen.findAllByText("Game information not found")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Reads failed.")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Props failed.")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("API Error: 404 Not Found")).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBeGreaterThan(0);

    await waitFor(() => {
      expect(calls.some((call) => call.url.includes(`/events/${HEX}/reads`))).toBe(true);
      expect(calls.some((call) => call.url.includes(`/events/${HEX}/props`))).toBe(true);
      expect(calls.some((call) => call.url.includes("/props/no-vig") && call.body?.includes(HEX))).toBe(true);
    });
    const list = calls.find((call) => call.url.includes("/events?"));
    expect(list?.url).toContain(`date=${events.date}`);
    expect(list?.url).not.toContain(`/events/${HEX}`);
    for (const call of calls.filter((item) => item.url.includes(HEX) || item.body?.includes(HEX))) {
      const onHexRoute =
        call.url.includes("/reads") ||
        call.url.includes("/props") ||
        call.url.includes("/suggest") ||
        call.url.includes("/props/no-vig");
      expect(onHexRoute).toBe(true);
    }
  });
});
