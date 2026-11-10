import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlayerDDTile } from "@/components/PlayerDDTile";
import { ResultsTable } from "@/components/ResultsTable";
import { SINGLE_LEG_PRIOR_LABEL } from "@/lib/no-vig-display";
import { noVigResponseSchema, type BookmakerResult, type NoVigResponse } from "@/lib/schemas";
import jokicHistory from "@/test/fixtures/player-dd-history/jokic.json";
import recordedNoVig from "@/test/fixtures/props-no-vig/player-double-double.json";
import oneSidedNoVig from "@/test/fixtures/props-no-vig/player-double-double-one-sided.json";
import { renderWithProviders } from "@/test/test-utils";

function renderTable(data: NoVigResponse) {
  return renderWithProviders(<ResultsTable data={data} />);
}

describe("ResultsTable double-double rows", () => {
  it("shows a double-double as Yes/No and dashes a null under price", () => {
    const legacy = noVigResponseSchema.parse(recordedNoVig);
    const { unmount } = renderTable(legacy);

    expect(screen.getAllByTestId("result-line").map((cell) => cell.textContent)).toEqual([
      "Yes/No",
      "Yes/No",
    ]);
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Yes Odds" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "No Odds" })).toBeInTheDocument();

    const fanduel = screen.getByTestId("result-row-fanduel");
    expect(within(fanduel).getByTestId("result-yes-price")).toHaveTextContent("-240");
    expect(within(fanduel).getByTestId("result-no-price")).toHaveTextContent("—");
    expect(within(fanduel).getByTestId("result-no-implied")).toHaveTextContent("—");
    expect(within(fanduel).getByTestId("result-no-fair")).toHaveTextContent("32.5%");
    expect(within(fanduel).getAllByText(SINGLE_LEG_PRIOR_LABEL).length).toBeGreaterThan(0);

    const draftkings = screen.getByTestId("result-row-draftkings");
    expect(within(draftkings).getByTestId("result-no-price")).toHaveTextContent("+200");
    expect(within(draftkings).queryByText(SINGLE_LEG_PRIOR_LABEL)).not.toBeInTheDocument();
    expect(screen.getByTestId("odds-age")).toHaveTextContent(
      "Odds response is 12 seconds old. Fetched at 2026-05-08T12:00:00Z.",
    );
    unmount();

    const next = noVigResponseSchema.parse(oneSidedNoVig);
    expect(next.results[1]?.under_odds).toBeNull();
    expect(next.results[1]?.p_under_imp).toBeNull();
    expect(next.results[1]?.no_price).toBeNull();
    expect(next.results[1]?.line_is_synthetic).toBe(true);
    expect(next.results[1]?.market_kind).toBe("binary");
    expect(next.fetched_at).toBe("2026-05-08T12:00:00Z");
    expect(next.data_age_seconds).toBe(12);

    renderTable(next);
    const nextFanduel = screen.getByTestId("result-row-fanduel");
    expect(within(nextFanduel).getByTestId("result-line")).toHaveTextContent("Yes/No");
    expect(within(nextFanduel).getByTestId("result-no-price")).toHaveTextContent("—");
    expect(within(nextFanduel).getByTestId("result-no-implied")).toHaveTextContent("—");
    expect(within(nextFanduel).getByTestId("result-no-fair")).toHaveTextContent("32.5%");
    expect(within(nextFanduel).getAllByText(SINGLE_LEG_PRIOR_LABEL).length).toBeGreaterThan(0);
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
  });

  it("still shows an over/under line and both prices", () => {
    const parsed = noVigResponseSchema.parse({
      event_id: "evt-ou",
      player_name: "Stephen Curry",
      market: "player_points",
      results: [
        {
          bookmaker: "draftkings",
          line: 24.5,
          over_odds: -110,
          under_odds: -110,
          p_over_imp: 0.5238,
          p_under_imp: 0.5238,
          vig: 0.0476,
          p_over_fair: 0.5,
          p_under_fair: 0.5,
          fetched_at: "2026-05-08T12:00:00Z",
        },
      ],
      consensus: { method: "mean", p_over_fair: 0.5, p_under_fair: 0.5 },
      message: null,
    });

    renderTable(parsed);
    expect(screen.getByTestId("result-line")).toHaveTextContent("24.5");
    expect(screen.getByRole("columnheader", { name: "Over Odds" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Under Odds" })).toBeInTheDocument();
    expect(screen.getByTestId("result-yes-price")).toHaveTextContent("-110");
    expect(screen.getByTestId("result-no-price")).toHaveTextContent("-110");
    expect(screen.queryByText("Yes/No")).not.toBeInTheDocument();
    expect(screen.queryByText(SINGLE_LEG_PRIOR_LABEL)).not.toBeInTheDocument();
  });

  it("shows how old the odds are from fetched_at and data_age_seconds", () => {
    const parsed = noVigResponseSchema.parse({
      ...recordedNoVig,
      fetched_at: "2026-11-10T03:00:00Z",
      data_age_seconds: 47,
      debug_trace: "strip-me",
    });
    expect(parsed.fetched_at).toBe("2026-11-10T03:00:00Z");
    expect(parsed.data_age_seconds).toBe(47);
    expect("debug_trace" in parsed).toBe(false);

    renderTable(parsed);
    expect(screen.getByTestId("odds-age")).toHaveTextContent(
      "Odds response is 47 seconds old. Fetched at 2026-11-10T03:00:00Z.",
    );
  });

  it("renders 0.6755 as 67.6% in ResultsTable and PlayerDDTile", async () => {
    const parsed = noVigResponseSchema.parse({
      event_id: "evt-round",
      player_name: "Nikola Jokic",
      market: "player_double_double",
      results: [
        binaryRow("fanduel", {
          over_odds: -240,
          under_odds: 200,
          no_price: 200,
          p_under_imp: 0.3245,
          p_over_fair: 0.6755,
          p_under_fair: 0.3245,
          yes_price: -240,
          yes_fair_prob: 0.6755,
          no_fair_prob: 0.3245,
          uses_prior: false,
        }),
      ],
      consensus: {
        method: "mean",
        p_over_fair: 0.6755,
        p_under_fair: 0.3245,
        p_yes_fair: 0.6755,
        p_no_fair: 0.3245,
        consensus_uses_prior: false,
      },
      message: null,
    });

    const { unmount } = renderTable(parsed);
    expect(screen.getByTestId("result-yes-fair")).toHaveTextContent("67.6%");
    unmount();

    renderWithProviders(
      <PlayerDDTile
        playerName="Nikola Jokic"
        league="nba"
        eventId="evt-round"
        getPlayerDDHistoryFn={() => Promise.resolve(jokicHistory)}
        calculateNoVigFn={() => Promise.resolve(parsed)}
      />,
    );
    const fanduel = await screen.findByRole("article", { name: /fanduel/i });
    expect(within(fanduel).getByText("67.6%")).toBeInTheDocument();
  });

  it("prefers uses_prior when it is present and falls back when it is absent", () => {
    const flagged = noVigResponseSchema.parse(
      ddBody([
        binaryRow("fanduel", {
          under_odds: 200,
          no_price: 200,
          p_under_imp: 0.3333,
          uses_prior: true,
        }),
      ]),
    );
    const { unmount } = renderTable(flagged);
    const flaggedRow = screen.getByTestId("result-row-fanduel");
    expect(within(flaggedRow).getAllByText(SINGLE_LEG_PRIOR_LABEL).length).toBeGreaterThan(0);
    expect(within(flaggedRow).getByTestId("result-no-price")).toHaveTextContent("—");
    unmount();

    const suppressed = noVigResponseSchema.parse(
      ddBody([
        binaryRow("fanduel", {
          under_odds: null,
          no_price: null,
          p_under_imp: null,
          uses_prior: false,
        }),
      ], { consensus_uses_prior: false }),
    );
    const { unmount: unmountSuppressed } = renderTable(suppressed);
    expect(within(screen.getByTestId("result-row-fanduel")).queryByText(SINGLE_LEG_PRIOR_LABEL)).not.toBeInTheDocument();
    expect(screen.queryByTestId("consensus-prior")).not.toBeInTheDocument();
    unmountSuppressed();

    const absent = noVigResponseSchema.parse(
      ddBody([
        binaryRow("fanduel", {
          under_odds: null,
          no_price: null,
          p_under_imp: null,
        }),
      ]),
    );
    expect(absent.results[0]?.uses_prior).toBeUndefined();
    renderTable(absent);
    expect(
      within(screen.getByTestId("result-row-fanduel")).getAllByText(SINGLE_LEG_PRIOR_LABEL).length,
    ).toBeGreaterThan(0);
  });

  it("labels a mixed consensus when any book used the prior", () => {
    const mixed = noVigResponseSchema.parse(recordedNoVig);
    expect(mixed.consensus?.consensus_uses_prior).toBeUndefined();
    renderTable(mixed);

    expect(within(screen.getByTestId("result-row-draftkings")).queryByText(SINGLE_LEG_PRIOR_LABEL)).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId("result-row-fanduel")).getAllByText(SINGLE_LEG_PRIOR_LABEL).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByTestId("consensus-prior").map((node) => node.textContent)).toEqual([
      SINGLE_LEG_PRIOR_LABEL,
      SINGLE_LEG_PRIOR_LABEL,
    ]);
  });

  it("reads consensus_uses_prior from the consensus object and from the envelope", () => {
    const onObject = noVigResponseSchema.parse(
      ddBody(
        [
          binaryRow("draftkings", { under_odds: 200, no_price: 200, uses_prior: false }),
          binaryRow("fanduel", { under_odds: 180, no_price: 180, uses_prior: false }),
        ],
        {
          consensus: {
            method: "mean",
            p_over_fair: 0.68,
            p_under_fair: 0.32,
            p_yes_fair: 0.68,
            p_no_fair: 0.32,
            consensus_uses_prior: true,
            consensus_prior_book_count: 1,
          },
        },
      ),
    );
    const { unmount } = renderTable(onObject);
    expect(screen.getAllByTestId("consensus-prior")[0]).toHaveTextContent(
      "includes 1 book on the 4.5% single-leg prior",
    );
    expect(within(screen.getByTestId("result-row-draftkings")).queryByText(SINGLE_LEG_PRIOR_LABEL)).not.toBeInTheDocument();
    expect(within(screen.getByTestId("result-row-fanduel")).queryByText(SINGLE_LEG_PRIOR_LABEL)).not.toBeInTheDocument();
    unmount();

    const onEnvelope = noVigResponseSchema.parse(
      ddBody(
        [binaryRow("draftkings", { under_odds: 200, no_price: 200, uses_prior: false })],
        {
          consensus_uses_prior: true,
          consensus_prior_book_count: 2,
        },
      ),
    );
    expect(onEnvelope.consensus?.consensus_uses_prior).toBeUndefined();
    expect(onEnvelope.consensus_uses_prior).toBe(true);
    renderTable(onEnvelope);
    expect(screen.getAllByTestId("consensus-prior")[0]).toHaveTextContent(
      "includes 2 books on the 4.5% single-leg prior",
    );
  });
});

function binaryRow(
  bookmaker: string,
  overrides: Partial<BookmakerResult> = {},
): BookmakerResult {
  return {
    bookmaker,
    line: 0.5,
    over_odds: -240,
    under_odds: null,
    p_over_imp: 0.7059,
    p_under_imp: null,
    vig: 0.045,
    p_over_fair: 0.6755,
    p_under_fair: 0.3245,
    yes_price: -240,
    no_price: null,
    p_yes_imp: 0.7059,
    p_no_imp: null,
    yes_fair_prob: 0.6755,
    no_fair_prob: 0.3245,
    line_is_synthetic: true,
    market_kind: "binary",
    ...overrides,
  };
}

function ddBody(
  results: BookmakerResult[],
  extra: Record<string, unknown> = {},
) {
  return {
    event_id: "evt-prior",
    player_name: "Nikola Jokic",
    market: "player_double_double",
    results,
    consensus: {
      method: "mean",
      p_over_fair: 0.6755,
      p_under_fair: 0.3245,
      p_yes_fair: 0.6755,
      p_no_fair: 0.3245,
    },
    message: null,
    ...extra,
  };
}
