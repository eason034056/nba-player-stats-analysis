import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EventDetail } from "@/components/EventDetail";
import { renderWithProviders } from "@/test/test-utils";
import nbaEventsFixture from "@/test/fixtures/event/nba-events.json";
import nbaPicksFixture from "@/test/fixtures/event/nba-daily-picks.json";
import nbaSuggestFixture from "@/test/fixtures/event/nba-suggest.json";
import nbaHistoryFixture from "@/test/fixtures/event/nba-history-bam.json";
import nbaLineupFixture from "@/test/fixtures/event/nba-lineup-mixed.json";
import nbaBosLineupFixture from "@/test/fixtures/event/nba-lineup-bos.json";
import nbaNoVigFixture from "@/test/fixtures/event/nba-no-vig-bam.json";

vi.mock("next/navigation", () => ({
  useParams: () => ({ eventId: "evt-mia-bos" }),
  usePathname: () => "/event/evt-mia-bos",
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => ({
    get: (key: string) => {
      if (key === "date") return "2026-11-10";
      if (key === "player") return "Bam Adebayo";
      if (key === "market") return "player_points";
      return null;
    },
  }),
}));

type SeenRequest = { url: string; body: string };

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

describe("NBA event page projection requests", () => {
  const seen: SeenRequest[] = [];

  afterEach(() => {
    vi.unstubAllGlobals();
    seen.length = 0;
  });

  it("does not request /api/nba/projections when a player is selected", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = requestUrl(input);
        const body = typeof init?.body === "string" ? init.body : "";
        seen.push({ url, body });
        const path = url.replace(/^.*(?=\/api\/)/, "");
        if (path.includes("/api/nba/projections")) {
          return Response.json({ detail: "Not Found" }, { status: 404 });
        }
        if (path.startsWith("/api/nba/events") && path.includes("/reads")) {
          return Response.json({
            event_id: "evt-mia-bos",
            market: "player_points",
            snapshot_at: "2026-11-10T18:00:00Z",
            source: "snapshot",
            reads: [],
          });
        }
        if (path.startsWith("/api/nba/events") && path.includes("/props")) {
          return Response.json({
            event_id: "evt-mia-bos",
            snapshot_at: "2026-11-10T18:00:00Z",
            data_age_seconds: 30,
            source: "snapshot",
            markets: [],
          });
        }
        if (path.startsWith("/api/nba/events")) return Response.json(nbaEventsFixture);
        if (path.startsWith("/api/nba/daily-picks")) return Response.json(nbaPicksFixture);
        if (path.startsWith("/api/nba/players/suggest")) return Response.json(nbaSuggestFixture);
        if (path.startsWith("/api/nba/player-history")) return Response.json(nbaHistoryFixture);
        if (path.startsWith("/api/nba/lineups/BOS")) return Response.json(nbaBosLineupFixture);
        if (path.startsWith("/api/nba/lineups/")) return Response.json(nbaLineupFixture);
        if (path.startsWith("/api/nba/props/no-vig")) return Response.json(nbaNoVigFixture);
        return Response.json({ detail: "Not Found" }, { status: 404 });
      }),
    );

    renderWithProviders(<EventDetail league="nba" />);
    expect(await screen.findByTestId("player-row-Tyler Herro")).toBeInTheDocument();
    await user.click(screen.getByTestId("player-row-Tyler Herro"));

    await waitFor(() => {
      expect(
        seen.some((request) => decodeURIComponent(request.url + request.body).includes("Tyler Herro")),
      ).toBe(true);
    });
    expect(seen.map((request) => request.url).join("\n")).not.toMatch(/\/api\/nba\/projections/);
  });
});
