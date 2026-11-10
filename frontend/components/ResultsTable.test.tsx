import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResultsTable } from "@/components/ResultsTable";
import { SINGLE_LEG_PRIOR_LABEL } from "@/lib/no-vig-display";
import { noVigResponseSchema, type NoVigResponse } from "@/lib/schemas";
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
});
