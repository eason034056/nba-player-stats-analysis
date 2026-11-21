"use client";

import {
  actionBarPercent,
  mobileOtherCopy,
  mobilePrimaryCopy,
  type OurReadModel,
} from "@/lib/event-page";
import { AGENT_CHAT_UI_ENABLED } from "@/lib/agent-chat-ui";
import { cn } from "@/lib/utils";

/**
 * Sticky mobile bar above the tab bar.
 * Prints the last name, the side, the line, and the floored blend beside a tier.
 * The other side prints 1 − combined_probability when that blend is on the seed.
 * History is only the label when the blend was missing and the rate is historical.
 */
export function EventActionBar({
  model,
  primaryInSlip,
  otherInSlip,
  onAddPrimary,
  onAddOther,
  onAsk,
}: {
  model: OurReadModel;
  primaryInSlip: boolean;
  otherInSlip: boolean;
  onAddPrimary: () => void;
  onAddOther: () => void;
  onAsk: () => void;
}) {
  const primary = model.primary;
  const mobile = primary ? mobilePrimaryCopy(primary, primaryInSlip, null, null) : null;
  const blend = actionBarPercent(primary);
  const other = model.other;
  const otherIsModel =
    typeof other?.combined_probability === "number" && Number.isFinite(other.combined_probability);
  const otherSide = other?.direction === "under" ? "Under" : "Over";
  return (
    <div
      data-testid="event-action-bar"
      className={cn(
        "fixed inset-x-0 bottom-[72px] z-30 flex flex-col gap-1 border-t border-line bg-white px-3 py-2.5 md:hidden",
      )}
    >
      <div className="flex gap-2">
      {primary && mobile ? (
        <button
          type="button"
          onClick={onAddPrimary}
          className={cn(
            "flex min-h-12 flex-1 items-center justify-center gap-2 rounded-[14px] px-3 text-sm font-bold",
            primaryInSlip ? "bg-accent text-accent-ink" : "bg-brand text-white",
          )}
        >
          <span>{mobile.label}</span>
          {blend ? <span className="font-mono">{blend}</span> : null}
        </button>
      ) : null}
      {other ? (
        <button
          type="button"
          onClick={onAddOther}
          className="min-h-12 rounded-[14px] border border-line-strong bg-white px-3 text-[13px] font-semibold text-ink"
        >
          {otherIsModel ? (
            <span>
              {otherInSlip ? `✓ ${otherSide} in slip` : mobileOtherCopy(other)}
            </span>
          ) : (
            <span className="flex flex-col items-center leading-tight">
              <span className="text-[9px] font-semibold uppercase tracking-[0.06em] text-muted">History</span>
              <span>
                {otherInSlip ? `✓ ${otherSide} in slip` : mobileOtherCopy(other)}
              </span>
            </span>
          )}
        </button>
      ) : null}
      {AGENT_CHAT_UI_ENABLED && !model.listedOut ? (
        <button
          type="button"
          onClick={onAsk}
          className="min-h-12 rounded-[14px] bg-brand-tint px-3.5 text-[13px] font-bold text-brand"
        >
          Ask
        </button>
      ) : null}
      </div>
    </div>
  );
}
