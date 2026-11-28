import { useEffect, useState } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BookmakerSelect } from "@/components/BookmakerSelect";
import { calculateNoVig } from "@/lib/api";
import { BOOKMAKERS, noVigResponseSchema } from "@/lib/schemas";
import { renderWithProviders } from "@/test/test-utils";
import noVigFixture from "@/test/fixtures/event/nba-no-vig-bam.json";
import notFoundFixture from "@/test/fixtures/event/http-404-malformed-event-id.json";
import eventsFixture from "@/test/fixtures/today/nba-events.json";

const noVig = noVigResponseSchema.parse(noVigFixture);
const FEATURED = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "BetRivers", "Fanatics"] as const;
const FEATURED_KEYS = ["draftkings", "fanduel", "betmgm", "caesars", "betrivers", "fanatics"] as const;

type Call = { url: string; body: string | null };

function installFetch() {
  const calls: Call[] = [];
  const fetchMock: typeof fetch = async (input, init) => {
    const url = String(input);
    const body = init?.body == null ? null : String(init.body);
    calls.push({ url, body });
    if (url.includes("/props/no-vig")) return Response.json(noVigFixture);
    if (url.includes("/events")) return Response.json(eventsFixture);
    return Response.json(notFoundFixture, { status: 404, statusText: "Not Found" });
  };
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function noVigBodies(calls: Call[]): Array<{ bookmakers: string[] | null }> {
  return calls
    .filter((call) => call.url.includes("/props/no-vig") && call.body)
    .map((call) => JSON.parse(call.body ?? "{}") as { bookmakers: string[] | null });
}

function assertRequestHasNoAlias(calls: Call[]) {
  for (const call of calls) {
    expect(call.url).not.toContain("bally_bet");
    expect(call.body ?? "").not.toContain("bally_bet");
    const params = new URL(call.url, "http://localhost").searchParams;
    params.forEach((value, key) => {
      expect(key).not.toBe("bally_bet");
      expect(value).not.toContain("bally_bet");
    });
  }
}

function BookPoster({ initial }: { initial: string[] }) {
  const [value, setValue] = useState(initial);
  useEffect(() => {
    void calculateNoVig({
      event_id: noVig.event_id,
      player_name: noVig.player_name,
      market: noVig.market,
      regions: "us",
      bookmakers: value.length > 0 ? value : null,
      odds_format: "american",
    });
  }, [value]);
  return <BookmakerSelect value={value} onChange={setValue} />;
}

describe("BookmakerSelect request keys", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows featured books as DraftKings through Fanatics", () => {
    renderWithProviders(<BookmakerSelect value={[]} onChange={() => {}} />);
    const featured = screen.getByRole("heading", { name: "Featured Platforms" }).nextElementSibling;
    expect(featured).not.toBeNull();
    expect(
      within(featured as HTMLElement)
        .getAllByRole("button")
        .map((button) => button.textContent?.trim()),
    ).toEqual([...FEATURED]);
    expect(FEATURED_KEYS).toEqual(
      FEATURED.map((name) => BOOKMAKERS.find((book) => book.name === name)?.key),
    );
  });

  it("posts ballybet when Bally Bet is selected and never puts bally_bet on the wire", async () => {
    const user = userEvent.setup();
    const calls = installFetch();
    renderWithProviders(<BookPoster initial={[]} />);

    await waitFor(() => {
      expect(noVigBodies(calls).some((body) => body.bookmakers === null)).toBe(true);
    });

    await user.click(screen.getByRole("button", { name: /other bookmakers \(4\)/i }));
    await user.click(screen.getByRole("button", { name: "Bally Bet" }));

    await waitFor(() => {
      const bodies = noVigBodies(calls);
      expect(bodies.some((body) => body.bookmakers?.includes("ballybet") === false && (body.bookmakers?.length ?? 0) > 0)).toBe(true);
    });
    const deselected = noVigBodies(calls).find((body) => Array.isArray(body.bookmakers));
    expect(deselected?.bookmakers).toEqual(BOOKMAKERS.map((book) => book.key).filter((key) => key !== "ballybet"));

    await user.click(screen.getByRole("button", { name: "Bally Bet" }));
    await waitFor(() => {
      expect(noVigBodies(calls).some((body) => body.bookmakers?.includes("ballybet"))).toBe(true);
    });
    assertRequestHasNoAlias(calls);
  });

  it("posts ballybet when the stored value is bally_bet", async () => {
    const calls = installFetch();
    renderWithProviders(<BookPoster initial={["bally_bet"]} />);

    await waitFor(() => {
      expect(noVigBodies(calls).at(-1)?.bookmakers).toEqual(["ballybet"]);
    });
    assertRequestHasNoAlias(calls);
  });
});
