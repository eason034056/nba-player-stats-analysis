"use client";

import type { LeagueSegment } from "@/lib/event-detail-link";
import {
  webOtherCopy,
  webPrimaryCopy,
  type FairSplit,
  type OurReadModel,
  type ReadSignal,
  type SignalVerdict,
} from "@/lib/event-page";
import { cn } from "@/lib/utils";

const VERDICT_DOT: Record<SignalVerdict, string> = {
  supports: "bg-brand",
  against: "bg-against",
  neutral: "bg-tone-neutral",
};

const VERDICT_TEXT: Record<SignalVerdict, string> = {
  supports: "text-brand",
  against: "text-against",
  neutral: "text-muted",
};

const VERDICT_WORD: Record<SignalVerdict, string> = {
  supports: "Supports",
  against: "Against",
  neutral: "Neutral",
};

const TIER_CLASS = {
  strong: "bg-accent text-brand-ink",
  playable: "bg-brand text-white",
  lean: "bg-[#E3DAF3] text-brand",
  pass: "bg-[#E2E2E2] text-[#4A4458]",
} as const;

function SignalRow({ signal, showVerdict }: { signal: ReadSignal; showVerdict: boolean }) {
  const verdict = showVerdict ? signal.verdict : null;
  const dot = verdict ? VERDICT_DOT[verdict] : signal.value ? "bg-brand" : "bg-tone-neutral";
  const fill = verdict ? VERDICT_DOT[verdict] : "bg-brand";
  return (
    <div
      data-testid={`signal-${signal.key}`}
      className={cn(
        "flex flex-wrap items-center gap-x-6 gap-y-2.5 border-b border-divider py-3.5",
        showVerdict && "max-md:flex-nowrap max-md:gap-x-3",
      )}
    >
      <div
        data-testid={`signal-label-${signal.key}`}
        className={cn(
          "grid min-w-0 flex-1 grid-cols-[10px_minmax(0,1fr)] gap-3",
          showVerdict ? "md:basis-60" : "basis-60",
        )}
      >
        <span className={cn("mt-1.5 h-2.5 w-2.5 rounded-full", dot)} />
        <span className="min-w-0">
          <span className="block text-sm font-bold text-ink">{signal.label}</span>
          {signal.detail ? <span className="block text-[13px] text-muted">{signal.detail}</span> : null}
        </span>
      </div>
      <div className={cn("flex min-w-[200px] flex-1 items-center gap-3.5", showVerdict && "max-md:hidden")}>
        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-divider">
          {signal.meter != null ? (
            <span
              className={cn("block h-full rounded-full", fill)}
              style={{ width: `${Math.max(0, Math.min(100, signal.meter * 100))}%` }}
            />
          ) : null}
        </span>
        <span className="w-14 text-right font-mono text-sm font-bold text-ink">{signal.value ?? "—"}</span>
        {verdict ? (
          <span className={cn("hidden w-[72px] text-xs font-semibold md:inline", VERDICT_TEXT[verdict])}>
            {VERDICT_WORD[verdict]}
          </span>
        ) : null}
      </div>
      {showVerdict ? (
        <div
          data-testid={`signal-value-${signal.key}`}
          className="flex shrink-0 flex-col items-end text-right md:hidden"
        >
          <span className="font-mono text-[15px] font-bold text-ink">{signal.value ?? "—"}</span>
          {verdict ? (
            <span className={cn("text-[11px] font-semibold", VERDICT_TEXT[verdict])}>{VERDICT_WORD[verdict]}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function SplitBar({ bar, showSource }: { bar: FairSplit; showSource: boolean }) {
  return (
    <div data-testid="read-bar" className="flex flex-col gap-2">
      {showSource ? (
        <div className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">{bar.sourceLabel}</div>
      ) : null}
      <div className="flex justify-between font-mono text-sm font-bold">
        <span className="text-brand">
          {bar.overLabel} {bar.overText}
        </span>
        <span className="text-under-text">
          {bar.underLabel} {bar.underText}
        </span>
      </div>
      <div className="flex h-3.5 overflow-hidden rounded-full bg-under-bar max-md:h-3">
        <span
          className="h-full border-r-[3px] border-white bg-brand"
          style={{ width: `${bar.overWidth}%` }}
        />
      </div>
    </div>
  );
}

export function OurRead({
  model,
  isLoading,
  isError,
  errorText,
  primaryInSlip,
  otherInSlip,
  onAddPrimary,
  onAddOther,
  onAsk,
  league = "wnba",
}: {
  model: OurReadModel;
  isLoading: boolean;
  isError: boolean;
  errorText: string | null;
  primaryInSlip: boolean;
  otherInSlip: boolean;
  onAddPrimary: () => void;
  onAddOther: () => void;
  onAsk: () => void;
  league?: LeagueSegment;
}) {
  const nba = league === "nba";
  return (
    <section
      data-testid="our-read"
      className={cn(
        "flex flex-col",
        nba
          ? "gap-3 md:gap-[22px] md:rounded-[24px] md:border md:border-line md:bg-white md:px-7 md:py-5"
          : "gap-5 rounded-[24px] border border-line bg-white px-5 py-5 md:px-7",
      )}
    >
      <div
        className={cn(
          nba && "flex flex-col gap-3 rounded-[20px] border border-line bg-white p-[18px] md:contents",
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className={cn("text-xs font-bold uppercase tracking-[0.08em] text-muted", nba && "hidden md:block")}>
            3 · Our read
          </div>
          {model.tier ? (
            <span className={cn("rounded-full px-3 py-1.5 text-xs font-bold", TIER_CLASS[model.tier.name])}>
              {model.tier.label}
            </span>
          ) : null}
        </div>
        {isLoading ? (
          <p className="text-sm text-muted">Loading this read.</p>
        ) : (
          <>
            <div className="flex flex-col gap-2">
              {model.player ? (
                <div className="text-[15px] font-semibold text-muted">
                  {model.player}
                  {model.meta ? (
                    <>
                      <span className="md:hidden">{` · ${model.meta.split(",")[0]?.trim()}`}</span>
                      <span className="hidden md:inline">{` · ${model.meta}`}</span>
                    </>
                  ) : null}
                </div>
              ) : null}
              <div
                className={cn(
                  "font-bold leading-none tracking-[-0.035em] text-ink",
                  nba ? "text-[32px] md:text-[clamp(30px,5cqi,48px)]" : "text-3xl md:text-5xl",
                )}
              >
                {model.headlineLead}{" "}
                {model.headlineMarket ? <span className="text-brand-soft">{model.headlineMarket}</span> : null}
              </div>
              <p className={cn(nba ? "text-sm md:text-[15px]" : "text-[15px]", "text-ink")}>{model.caption}</p>
            </div>
            {isError ? <p className="text-sm font-semibold text-red">{errorText ?? "The odds request failed."}</p> : null}
            {model.bar ? <SplitBar bar={model.bar} showSource /> : null}
            <div className="hidden flex-wrap gap-2.5 md:flex">
              {nba &&
              model.other != null &&
              !(
                typeof model.other.combined_probability === "number" &&
                Number.isFinite(model.other.combined_probability)
              ) ? (
                <div className="w-full text-xs font-semibold uppercase tracking-[0.08em] text-muted">History</div>
              ) : null}
              {model.primary ? (
                <button
                  type="button"
                  onClick={onAddPrimary}
                  className={cn(
                    "min-h-[46px] rounded-full px-5 text-sm font-bold",
                    nba && primaryInSlip ? "bg-accent text-accent-ink" : "bg-brand text-white hover:bg-brand-deep",
                  )}
                >
                  {webPrimaryCopy(model.primary, primaryInSlip, league)}
                </button>
              ) : null}
              {model.other ? (
                <button
                  type="button"
                  onClick={onAddOther}
                  className="min-h-[46px] rounded-full border border-line-strong bg-white px-4 text-sm font-semibold text-ink"
                >
                  {webOtherCopy(model.other, otherInSlip, league)}
                </button>
              ) : model.player && model.primary ? (
                <p className="self-center text-xs text-muted">
                  The other side&apos;s hit rate is not on this response.
                </p>
              ) : null}
              <button
                type="button"
                onClick={onAsk}
                className="min-h-[46px] rounded-full bg-brand-tint px-4 text-sm font-semibold text-brand"
              >
                Ask the agent
              </button>
            </div>
          </>
        )}
      </div>
      {!isLoading && model.signals.length > 0 ? (
        <div
          className={cn(
            nba
              ? "rounded-[20px] border border-line bg-white px-4 md:rounded-none md:border-0 md:border-t md:border-divider md:bg-transparent md:px-0"
              : "border-t border-divider",
          )}
        >
          {model.signals.map((signal) => (
            <SignalRow key={signal.key} signal={signal} showVerdict={nba} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
