"use client";

import { SINGLE_LEG_PRIOR_LABEL } from "@/lib/no-vig-display";
import type { NoVigResponse } from "@/lib/schemas";
import { sportsbookPrices } from "@/lib/sportsbook-prices";
import { cn, getMarketDisplayName } from "@/lib/utils";

export function SportsbookPrices({
  data,
  isLoading,
  isError,
  errorText,
  className,
}: {
  data: NoVigResponse | null;
  isLoading: boolean;
  isError: boolean;
  errorText: string | null;
  className?: string;
}) {
  const model = !isLoading && data && data.results.length > 0 ? sportsbookPrices(data) : null;
  const side = model?.binary ? "yes" : "over";

  return (
    <section
      data-testid="odds-panel"
      className={cn(
        "flex min-w-0 max-w-full flex-col gap-2.5 rounded-[20px] border border-line bg-white p-4 md:gap-3 md:rounded-[24px] md:p-7",
        className,
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2.5">
        <h3 className="text-[17px] font-bold text-ink md:text-lg">Sportsbook prices</h3>
        {model ? (
          <>
            {model.postedLine ? <p className="text-xs text-muted md:hidden">Line {model.postedLine}</p> : null}
            <p className="text-[13px] text-muted max-md:hidden">
              {model.consensus ? `No-vig consensus ${model.consensus} ${side}` : "No consensus on this response."}
            </p>
          </>
        ) : null}
      </div>

      {isLoading ? (
        <div aria-busy="true" aria-label="Loading prices" className="flex flex-col gap-2">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="skeleton h-9 w-full rounded-xl" />
          ))}
        </div>
      ) : null}

      {!isLoading && isError ? (
        <p className="text-sm font-semibold text-red">{errorText ?? "Prices failed to load."}</p>
      ) : null}

      {!isLoading && !isError && data && data.results.length === 0 ? (
        <div className="rounded-2xl bg-[#F7F6F9] px-4 py-5 text-sm text-muted">
          <p className="font-semibold text-ink">No bookmaker line right now</p>
          <p className="mt-1">
            No book has posted {getMarketDisplayName(data.market)} for this game. The game log stays
            available, and prices show up on the next odds snapshot.
          </p>
          {data.message ? <p className="mt-2 text-xs">Backend note: {data.message}</p> : null}
        </div>
      ) : null}

      {model ? (
        <>
          {model.consensus ? (
            <div className="flex items-center justify-between gap-3 rounded-[14px] bg-brand-tint p-3 md:hidden">
              <span className="text-[13px] font-semibold text-brand">No-vig consensus {side}</span>
              <span className="font-mono text-xl font-bold text-brand">{model.consensus}</span>
            </div>
          ) : null}
          {model.priorCaption ? (
            <p data-testid="consensus-prior" className="text-xs text-muted">
              {model.priorCaption}
            </p>
          ) : null}
          <table className="w-full table-fixed border-collapse">
            <thead>
              <tr className="border-b border-[#EEEBF2] text-[11px] uppercase tracking-[0.06em] text-muted md:text-xs md:tracking-[0.08em]">
                <th scope="col" className="py-1.5 text-left font-bold md:py-2">
                  Book
                </th>
                {model.binary ? null : (
                  <th scope="col" className="w-[17%] text-right font-bold max-md:hidden">
                    Line
                  </th>
                )}
                <th scope="col" className="w-[58px] text-right font-bold md:w-[17%]">
                  {model.yesLabel}
                </th>
                <th scope="col" className="w-[58px] text-right font-bold md:w-[17%]">
                  {model.noLabel}
                </th>
                <th scope="col" className="w-12 text-right font-bold md:w-[17%]">
                  Fair<span className="max-md:hidden"> {side}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {model.rows.map((row) => (
                <tr
                  key={row.bookmaker}
                  data-testid={`price-row-${row.bookmaker}`}
                  className="font-mono text-[13px] font-semibold text-ink"
                >
                  <td className="py-1 pr-2 font-sans">
                    <div className="truncate text-sm font-bold">{row.book}</div>
                    <div className="text-[11px] font-medium text-muted">
                      vig {row.vig}
                      {row.offLine ? <span className="md:hidden"> · line {row.line}</span> : null}
                      {row.prior ? ` · ${SINGLE_LEG_PRIOR_LABEL}` : null}
                    </div>
                  </td>
                  {model.binary ? null : <td className="text-right max-md:hidden">{row.line}</td>}
                  <td className="text-right">{row.yes}</td>
                  <td className="text-right">{row.no}</td>
                  <td className="text-right font-bold text-brand">{row.fair}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {model.updated ? <p className="text-xs text-muted">{model.updated}</p> : null}
        </>
      ) : null}
    </section>
  );
}
