"use client";

import {
  mobileOtherCopy,
  mobilePrimaryCopy,
  type OurReadModel,
} from "@/lib/event-page";
import type { LeagueSegment } from "@/lib/event-detail-link";
import { cn } from "@/lib/utils";

/**
 * Sticky mobile bar above the tab bar.
 * NBA prints the last name, the side, the line, and the tiered percent.
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
  const mobile = primary ? mobilePrimaryCopy(primary, primaryInSlip, nba ? model.tier : null, model.leanProbability) : null;
  return (
    <div
      data-testid="event-action-bar"
      className="fixed inset-x-0 bottom-[72px] z-30 flex gap-2 border-t border-line bg-white px-3 py-2.5 md:hidden"
    >
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
              {mobile.prob ? <span className="font-mono">{mobile.prob}</span> : null}
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
          {nba
            ? otherInSlip
              ? `✓ ${model.other.direction === "under" ? "Under" : "Over"} in slip`
              : mobileOtherCopy(model.other)
            : model.other.direction === "under"
              ? "Under"
              : "Over"}
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
  );
}
