"use client";

import { AlertTriangle, CheckCircle2, Clock3, Users } from "lucide-react";

import { TeamLogo } from "@/components/TeamLogo";
import type { TeamLineup } from "@/lib/schemas";


interface TeamLineupPanelProps {
  lineup?: TeamLineup | null;
  isLoading?: boolean;
  title?: string;
}


const formatUpdatedAt = (value?: string | null) => {
  if (!value) return "No refresh time";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "No refresh time";
  return parsed.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
};


export function TeamLineupPanel({
  lineup,
  isLoading = false,
  title = "Lineup Status",
}: TeamLineupPanelProps) {
  if (isLoading) {
    return (
      <div className="card">
        <div className="mb-4 h-6 w-32 rounded-full bg-dark/10" />
        <div className="space-y-3">
          {[0, 1, 2, 3, 4].map((index) => (
            <div key={index} className="h-10 rounded-[16px] bg-dark/10" />
          ))}
        </div>
      </div>
    );
  }

  if (!lineup) {
    return (
      <div className="card">
        <p className="text-xs uppercase tracking-[0.22em] text-light">{title}</p>
        <div className="mt-4 rounded-[18px] border border-red/20 bg-red/5 px-4 py-4 text-sm text-red-700">
          Lineup unavailable for this team right now.
        </div>
      </div>
    );
  }

  const isUnavailable = lineup.status === "unavailable";
  const hasDisagreement = lineup.source_disagreement;
  const isIncomplete = lineup.status === "partial" && !hasDisagreement;

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <TeamLogo teamName={lineup.team} size={36} />
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-light">{title}</p>
            <h3 className="mt-1 text-lg font-semibold text-dark">{lineup.team}</h3>
            <p className="text-sm text-gray">
              {lineup.home_or_away === "HOME" ? "vs" : "at"} {lineup.opponent}
            </p>
          </div>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] ${
            lineup.confidence === "high"
              ? "bg-green-500/10 text-green-700"
              : lineup.confidence === "medium"
                ? "bg-yellow-500/15 text-yellow-700"
                : "bg-red-500/10 text-red-700"
          }`}
        >
          {lineup.confidence}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-gray">
        <span className="inline-flex items-center gap-1 rounded-full border border-dark/10 px-2.5 py-1">
          <Clock3 className="h-3.5 w-3.5" />
          Updated {formatUpdatedAt(lineup.updated_at)}
        </span>
        <span className="inline-flex items-center gap-1 rounded-full border border-dark/10 px-2.5 py-1">
          <Users className="h-3.5 w-3.5" />
          {lineup.sources.length} sources
        </span>
      </div>

      {isUnavailable ? (
        <div className="mt-4 rounded-[18px] border border-red/20 bg-red/5 px-4 py-3 text-sm text-dark">
          <div className="flex items-center gap-2 font-semibold text-red-700">
            <AlertTriangle className="h-4 w-4" />
            <span>Lineup unavailable</span>
          </div>
          <p className="mt-2 text-gray">
            Free lineup sources do not have a usable projected starting five for this team yet.
          </p>
        </div>
      ) : hasDisagreement ? (
        <div className="mt-4 rounded-[18px] border border-yellow-500/20 bg-yellow-500/10 px-4 py-3 text-sm text-dark">
          <div className="flex items-center gap-2 font-semibold text-yellow-800">
            <AlertTriangle className="h-4 w-4" />
            <span>Lineup still moving</span>
          </div>
          <p className="mt-2 text-gray">
            Free lineup sources are not fully aligned yet, so treat this rotation signal as provisional.
          </p>
        </div>
      ) : isIncomplete ? (
        <div className="mt-4 rounded-[18px] border border-yellow-500/20 bg-yellow-500/10 px-4 py-3 text-sm text-dark">
          <div className="flex items-center gap-2 font-semibold text-yellow-800">
            <AlertTriangle className="h-4 w-4" />
            <span>Lineup incomplete</span>
          </div>
          <p className="mt-2 text-gray">
            Free lineup sources are incomplete right now, so treat this rotation signal as provisional.
          </p>
        </div>
      ) : (
        <div className="mt-4 rounded-[18px] border border-green-500/20 bg-green-500/10 px-4 py-3 text-sm text-dark">
          <div className="flex items-center gap-2 font-semibold text-green-700">
            <CheckCircle2 className="h-4 w-4" />
            <span>Lineup aligned</span>
          </div>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {lineup.starters.length > 0 ? (
          lineup.starters.map((starter, index) => (
            <div
              key={`${lineup.team}-${starter}`}
              className="flex items-center justify-between rounded-[16px] border border-white/8 bg-white/5 px-4 py-3 text-sm"
            >
              <span className="font-semibold text-dark">{starter}</span>
              <span className="text-xs uppercase tracking-[0.16em] text-light">Starter {index + 1}</span>
            </div>
          ))
        ) : (
          <div className="rounded-[16px] border border-white/8 bg-white/5 px-4 py-3 text-sm text-gray">
            No projected starters available yet.
          </div>
        )}
      </div>
    </div>
  );
}
