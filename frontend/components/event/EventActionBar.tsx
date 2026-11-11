"use client";

import {
  actionBarPercent,
  mobileOtherCopy,
  mobilePrimaryCopy,
  type OurReadModel,
} from "@/lib/event-page";
import type { LeagueSegment } from "@/lib/event-detail-link";
import { cn } from "@/lib/utils";

/**
 * Sticky mobile bar above the tab bar.
 * NBA prints the last name, the side, the line, and the floored blend beside a tier.
 * The other side is the historical rate and is the only control labeled History.
 * WNBA keeps the short "Add over" / "Under" labels.
 */
export function EventActionBar({
  league,
  model,
  primaryInSlip,
  otherInSlip,
  onAddPrimary,
  onAddOther,
  onAsk,
}: {
  league: LeagueSegment;
  model: OurReadModel;
  primaryInSlip: boolean;
  otherInSlip: boolean;
  onAddPrimary: () => void;
  onAddOther: () => void;
  onAsk: () => void;
}) {
  const nba = league === "nba";
  const primary = model.primary;
  const mobile = primary ? mobilePrimaryCopy(primary, primaryInSlip, null, null) : null;
  const blend = actionBarPercent(primary, league);
  return (
    <div
      data-testid="event-action-bar"
      className={cn(
        "fixed inset-x-0 bottom-[72px] z-30 border-t border-line bg-white px-3 py-2.5 md:hidden",
        nba ? "flex flex-col gap-1" : "flex gap-2",
      )}
    >
      <div className="flex gap-2">
      {primary && mobile ? (
        <button
          type="button"
          onClick={onAddPrimary}
          className={cn(
            "flex min-h-12 flex-1 items-center justify-center gap-2 rounded-[14px] px-3 text-sm font-bold",
            nba && primaryInSlip ? "bg-accent text-accent-ink" : "bg-brand text-white",
          )}
        >
          {nba ? (
            <>
              <span>{mobile.label}</span>
              {blend ? <span className="font-mono">{blend}</span> : null}
            </>
          ) : (
            <span>
              {primaryInSlip ? "In slip" : primary.direction === "under" ? "Add under" : "Add over"}
            </span>
          )}
        </button>
      ) : null}
      {model.other ? (
        <button
          type="button"
          onClick={onAddOther}
          className="min-h-12 rounded-[14px] border border-line-strong bg-white px-3 text-[13px] font-semibold text-ink"
        >
          {nba ? (
            <span className="flex flex-col items-center leading-tight">
              <span className="text-[9px] font-semibold uppercase tracking-[0.06em] text-muted">History</span>
              <span>
                {otherInSlip
                  ? `✓ ${model.other.direction === "under" ? "Under" : "Over"} in slip`
                  : mobileOtherCopy(model.other)}
              </span>
            </span>
          ) : model.other.direction === "under" ? (
            "Under"
          ) : (
            "Over"
          )}
        </button>
      ) : null}
      <button
        type="button"
        onClick={onAsk}
        className="min-h-12 rounded-[14px] bg-brand-tint px-3.5 text-[13px] font-bold text-brand"
      >
        Ask
      </button>
      </div>
    </div>
  );
}
