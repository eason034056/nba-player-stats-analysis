import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResultsTable } from "@/components/ResultsTable";
import { formatPercent } from "@/lib/player-dd";
import { noVigResponseSchema, type BookmakerResult } from "@/lib/schemas";
import { formatVig } from "@/lib/utils";
import oneSided from "@/test/fixtures/event/nba-no-vig-dd-one-sided.json";
import mathFixture from "@/test/fixtures/event/nba-no-vig-math.json";
import { renderWithProviders } from "@/test/test-utils";

const math = noVigResponseSchema.parse(mathFixture);
const dd = noVigResponseSchema.parse(oneSided);

function implied(odds: number): number {
  if (odds === 0) return Number.NaN;
  if (odds < 0) return -odds / (-odds + 100);
  return 100 / (odds + 100);
}

function round4(value: number): number {
  return Number(value.toFixed(4));
}

function twoSided(overOdds: number, underOdds: number) {
  const over = implied(overOdds);
  const under = implied(underOdds);
  const sum = over + under;
  return {
    pOver: round4(over),
    pUnder: round4(under),
    vig: round4(sum - 1),
    fairOver: round4(over / sum),
    fairUnder: round4(under / sum),
  };
}

function textOf(row: HTMLElement): string {
  return row.textContent ?? "";
}

describe("sportsbook table matches the backend de-vig", () => {
  it("shows multiplicative fair percents and a real zero vig", () => {
    renderWithProviders(<ResultsTable data={math} />);
    for (const row of math.results) {
      const over = row.over_odds ?? 0;
      const under = row.under_odds ?? 0;
      const expected = twoSided(over, under);
      expect(row).toMatchObject({
        p_over_imp: expected.pOver,
        p_under_imp: expected.pUnder,
        vig: expected.vig,
        p_over_fair: expected.fairOver,
        p_under_fair: expected.fairUnder,
      });
      const rendered = screen.getByTestId(`result-row-${row.bookmaker}`);
      expect(within(rendered).getByTestId("result-yes-fair")).toHaveTextContent(
        formatPercent(expected.fairOver),
      );
      expect(within(rendered).getByTestId("result-no-fair")).toHaveTextContent(
        formatPercent(expected.fairUnder),
      );
      const body = textOf(rendered);
      expect(body).not.toMatch(/NaN|Infinity|undefined/);
      expect(formatVig(row.vig).startsWith("-")).toBe(false);
      expect(within(rendered).getByText(formatVig(row.vig))).toBeInTheDocument();
    }
    expect(within(screen.getByTestId("result-row-caesars")).getByText("0.0%")).toBeInTheDocument();
    expect(within(screen.getByTestId("result-row-pointsbet")).getByText("1%")).toBeInTheDocument();
    expect(within(screen.getByTestId("result-row-pointsbet")).getByText("99%")).toBeInTheDocument();
    expect(math.results.some((row) => row.over_odds === 0 || row.under_odds === 0)).toBe(false);
  });

  it("renders a dash when the vig is not finite", () => {
    expect(formatVig(Number.NaN)).toBe("—");
    expect(formatVig(Number.POSITIVE_INFINITY)).toBe("—");
    expect(formatVig(Number.NEGATIVE_INFINITY)).toBe("—");
    expect(formatVig(Number.NaN)).not.toBe("NaN%");
  });

  it("prints vig to one decimal, separate from the whole fair percent", () => {
    expect(formatVig(0.0476)).toBe("4.8%");
    expect(formatVig(0.055)).toBe("5.5%");
    expect(formatVig(0.0601)).toBe("6.0%");
    expect(formatVig(0.0476)).not.toBe(formatPercent(0.0476));
    renderWithProviders(<ResultsTable data={math} />);
    expect(within(screen.getByTestId("result-row-draftkings")).getByText("4.8%")).toBeInTheDocument();
  });

  it("dashes a yes-only double-double and uses the 4.5% single-leg prior", () => {
    const row = dd.results[0] as BookmakerResult;
    const yes = implied(row.yes_price ?? 0);
    const fair = yes / 1.045;
    expect(row.no_price).toBeNull();
    expect(row.under_odds).toBeNull();
    expect(row.p_no_imp).toBeNull();
    expect(row.p_under_imp).toBeNull();
    expect(row.vig).toBe(round4(0.045));
    expect(row.yes_fair_prob).toBe(round4(fair));
    expect(row.no_fair_prob).toBe(round4(1 - fair));
    renderWithProviders(<ResultsTable data={dd} />);
    const fanduel = screen.getByTestId("result-row-fanduel");
    expect(within(fanduel).getByTestId("result-no-price")).toHaveTextContent("—");
    expect(within(fanduel).getByTestId("result-no-implied")).toHaveTextContent("—");
    expect(within(fanduel).getByTestId("result-yes-fair")).toHaveTextContent(formatPercent(round4(fair)));
    expect(within(fanduel).getByTestId("result-yes-fair")).toHaveTextContent("68%");
    expect(within(fanduel).getByTestId("result-yes-fair")).not.toHaveTextContent("67%");
    expect(within(fanduel).getByText("4.5%")).toBeInTheDocument();
    expect(screen.getByTestId("result-line")).toHaveTextContent("Yes/No");
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
    expect(fanduel.textContent).not.toMatch(/NaN|Infinity|undefined/);
  });
});
