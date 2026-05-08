"use client";

import type {
  AgentVerdictBreakdown as AgentVerdictBreakdownData,
  AgentVerdictBreakdownSection,
  AgentVerdictEvidenceStat,
} from "@/lib/agent-chat";
import { cn } from "@/lib/utils";

type BreakdownColumns = "one" | "two";

interface AgentVerdictBreakdownProps {
  breakdown?: AgentVerdictBreakdownData | null;
  columns?: BreakdownColumns;
  emptyMessage?: string;
  className?: string;
}

const sectionToneStyles: Record<AgentVerdictBreakdownSection["tone"], string> = {
  support: "border-emerald-400/20 bg-emerald-400/6",
  caution: "border-amber-300/20 bg-amber-300/8",
  neutral: "border-white/8 bg-white/4",
  unavailable: "border-white/6 bg-white/[0.03]",
};

const toneBadgeStyles: Record<AgentVerdictBreakdownSection["tone"], string> = {
  support: "border-emerald-400/25 bg-emerald-400/12 text-emerald-200",
  caution: "border-amber-300/25 bg-amber-300/12 text-amber-100",
  neutral: "border-white/10 bg-white/6 text-light",
  unavailable: "border-white/8 bg-white/4 text-gray",
};

const statToneStyles: Record<NonNullable<AgentVerdictEvidenceStat["tone"]>, string> = {
  positive: "border-emerald-400/20 bg-emerald-400/8 text-emerald-100",
  neutral: "border-white/10 bg-white/6 text-light",
  caution: "border-amber-300/20 bg-amber-300/8 text-amber-100",
  muted: "border-white/8 bg-white/[0.03] text-gray",
};

const formatReliability = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(value)) {
    return "Reliability n/a";
  }

  return `${Math.round(value * 100)}% reliability`;
};

const formatToneLabel = (tone: AgentVerdictBreakdownSection["tone"]) => {
  if (tone === "unavailable") {
    return "Unavailable";
  }

  return tone.charAt(0).toUpperCase() + tone.slice(1);
};

const StatChip = ({ stat }: { stat: AgentVerdictEvidenceStat }) => (
  <div
    className={cn(
      "rounded-full border px-3 py-1.5 text-[11px] leading-none",
      stat.tone ? statToneStyles[stat.tone] : statToneStyles.neutral,
    )}
  >
    <span className="mr-1.5 uppercase tracking-[0.18em] text-[9px] opacity-75">{stat.label}</span>
    <span>{stat.value}</span>
  </div>
);

const BreakdownCard = ({ section }: { section: AgentVerdictBreakdownSection }) => (
  <article
    className={cn(
      "rounded-[18px] border px-4 py-3 shadow-[0_16px_40px_rgba(2,8,20,0.2)]",
      sectionToneStyles[section.tone],
    )}
  >
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-[0.22em] text-light">{section.label}</p>
        <p className="mt-1 text-xs text-gray">{formatReliability(section.reliability)}</p>
      </div>
      <span
        className={cn(
          "rounded-full border px-2.5 py-1 text-[10px] uppercase tracking-[0.18em]",
          toneBadgeStyles[section.tone],
        )}
      >
        {formatToneLabel(section.tone)}
      </span>
    </div>

    <div className="mt-3 space-y-3">
      <div>
        <p className="text-[10px] uppercase tracking-[0.18em] text-light">Signal</p>
        <p className="mt-1 text-sm text-dark">{section.signal_note}</p>
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-[0.18em] text-light">Risk</p>
        <p className={cn("mt-1 text-sm", section.risk_note ? "text-dark" : "text-gray")}>
          {section.risk_note ?? "No material caution."}
        </p>
      </div>

      {section.stats.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {section.stats.map((stat) => (
            <StatChip key={`${section.key}-${stat.label}-${stat.value}`} stat={stat} />
          ))}
        </div>
      ) : null}
    </div>
  </article>
);

export const AgentVerdictBreakdown = ({
  breakdown,
  columns = "two",
  emptyMessage = "Breakdown is unavailable for this verdict.",
  className,
}: AgentVerdictBreakdownProps) => {
  if (!breakdown || breakdown.sections.length === 0) {
    return (
      <div className="rounded-[18px] border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-gray">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div
      className={cn(
        columns === "two"
          ? "grid grid-cols-1 gap-3 xl:grid-cols-2"
          : "space-y-3",
        className,
      )}
    >
      {breakdown.sections.map((section) => (
        <BreakdownCard key={section.key} section={section} />
      ))}
    </div>
  );
};
