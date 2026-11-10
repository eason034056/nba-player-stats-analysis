"use client";

import type { FairSplit, OurReadModel, ReadSignal } from "@/lib/event-page";
import { cn } from "@/lib/utils";

const TIER_CLASS = {
  strong: "bg-accent text-brand-ink",
  playable: "bg-brand text-white",
  lean: "bg-[#E3DAF3] text-brand",
  pass: "bg-[#E2E2E2] text-[#4A4458]",
} as const;

function SignalRow({ signal }: { signal: ReadSignal }) {
  return (
    <div
      data-testid={`signal-${signal.key}`}
      className="flex flex-wrap items-center gap-x-6 gap-y-2.5 border-b border-[#EEEBF2] py-3.5"
    >
      <div className="grid min-w-0 flex-1 basis-60 grid-cols-[10px_minmax(0,1fr)] gap-3">
        <span
          className={cn(
            "mt-1.5 h-2.5 w-2.5 rounded-full",
            signal.value ? "bg-brand" : "bg-[#B9B3C4]",
          )}
        />
        <span className="min-w-0">
          <span className="block text-sm font-bold text-ink">{signal.label}</span>
          <span className="block text-[13px] text-muted">{signal.detail}</span>
        </span>
      </div>
      <div className="flex min-w-[200px] flex-1 items-center gap-3.5">
        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#EEEBF2]">
          {signal.meter != null ? (
            <span
              className="block h-full rounded-full bg-brand"
              style={{ width: `${Math.max(0, Math.min(100, signal.meter * 100))}%` }}
            />
          ) : null}
        </span>
        <span className="w-14 text-right font-mono text-sm font-bold text-ink">
          {signal.value ?? "—"}
        </span>
      </div>
    </div>
  );
}

function SplitBar({ bar }: { bar: FairSplit }) {
  return (
    <div data-testid="read-bar" className="flex flex-col gap-2">
      <div className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">{bar.sourceLabel}</div>
      <div className="flex justify-between font-mono text-sm font-bold">
        <span className="text-brand">
          {bar.overLabel} {bar.overText}
        </span>
        <span className="text-[#5B3A99]">
          {bar.underLabel} {bar.underText}
        </span>
      </div>
      <div className="flex h-3.5 overflow-hidden rounded-full bg-[#C9B4EE]">
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
}) {
  return (
    <section
      data-testid="our-read"
      className="flex flex-col gap-5 rounded-[24px] border border-line bg-white px-5 py-5 md:px-7"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs font-bold uppercase tracking-[0.08em] text-muted">3 · Our read</div>
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
                {model.meta ? ` · ${model.meta}` : ""}
              </div>
            ) : null}
            <div className="text-3xl font-bold leading-none tracking-[-0.035em] text-ink md:text-5xl">
              {model.headlineLead}{" "}
              {model.headlineMarket ? (
                <span className="text-brand-soft">{model.headlineMarket}</span>
              ) : null}
            </div>
            <p className="text-[15px] text-ink">{model.caption}</p>
          </div>
          {isError ? <p className="text-sm font-semibold text-red">{errorText ?? "The odds request failed."}</p> : null}
          {model.bar ? <SplitBar bar={model.bar} /> : null}
          <div className="hidden flex-wrap gap-2.5 md:flex">
            {model.primary ? (
              <button
                type="button"
                onClick={onAddPrimary}
                className="min-h-[46px] rounded-full bg-brand px-5 text-sm font-bold text-white hover:bg-brand-deep"
              >
                {primaryInSlip
                  ? `In slip · ${model.primary.direction === "under" ? "Under" : "Over"}`
                  : `Add ${model.primary.direction === "under" ? "Under" : "Over"} ${model.primary.threshold}`}
              </button>
            ) : null}
            {model.other ? (
              <button
                type="button"
                onClick={onAddOther}
                className="min-h-[46px] rounded-full border border-[#D3CCDF] bg-white px-4 text-sm font-semibold text-ink"
              >
                {otherInSlip
                  ? "Other side in slip"
                  : `${model.other.direction === "under" ? "Under" : "Over"} ${model.other.threshold}`}
              </button>
            ) : (
              model.player && model.primary ? (
                <p className="self-center text-xs text-muted">
                  The other side&apos;s hit rate is not on this response.
                </p>
              ) : null
            )}
            <button
              type="button"
              onClick={onAsk}
              className="min-h-[46px] rounded-full bg-brand-tint px-4 text-sm font-semibold text-brand"
            >
              Ask the agent
            </button>
          </div>
          {model.signals.length > 0 ? (
            <div className="border-t border-[#EEEBF2]">
              {model.signals.map((signal) => (
                <SignalRow key={signal.key} signal={signal} />
              ))}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
