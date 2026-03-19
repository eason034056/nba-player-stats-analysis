"use client";

import type { TeamLineup } from "@/lib/schemas";


interface LineupStatusBadgeProps {
  lineup?: TeamLineup | null;
  playerName: string;
  isLoading?: boolean;
  isError?: boolean;
}


const includesPlayer = (lineup: TeamLineup | null | undefined, playerName: string) => {
  const target = playerName.trim().toLowerCase();
  return (lineup?.starters || []).some((starter) => starter.trim().toLowerCase() === target);
};


export function LineupStatusBadge({
  lineup,
  playerName,
  isLoading = false,
  isError = false,
}: LineupStatusBadgeProps) {
  let label = "Lineup unavailable";
  let className = "bg-gray/10 text-gray";

  if (isLoading) {
    label = "Loading lineup";
  } else if (isError || !lineup) {
    label = "Lineup unavailable";
  } else if (lineup.status === "unavailable") {
    label = "Lineup unavailable";
  } else if (lineup.status !== "projected" || lineup.source_disagreement) {
    label = "Lineup moving";
    className = "bg-yellow-500/15 text-yellow-700";
  } else if (!includesPlayer(lineup, playerName)) {
    label = "Bench risk";
    className = "bg-red-500/10 text-red-600";
  } else {
    label = "Lineup aligned";
    className = "bg-green-500/10 text-green-700";
  }

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] ${className}`}
    >
      {label}
    </span>
  );
}
