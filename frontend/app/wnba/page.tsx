"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Search } from "lucide-react";

import { TodayBoard } from "@/components/TodayBoard";
import { getWNBACSVPlayers } from "@/lib/api";

/**
 * WNBA home. The slate matches the NBA Today board. The roster search
 * stays underneath so the historical player pages remain reachable.
 */
export default function WNBAHomePage() {
  const [playerQuery, setPlayerQuery] = useState("");
  const {
    data: playersData,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["wnba-csv-players"],
    queryFn: () => getWNBACSVPlayers(),
    staleTime: 5 * 60 * 1000,
  });

  const filteredPlayers = useMemo(() => {
    if (!playersData?.players) return [];
    if (!playerQuery.trim()) return playersData.players;
    const needle = playerQuery.trim().toLowerCase();
    return playersData.players.filter((player) =>
      player.toLowerCase().includes(needle),
    );
  }, [playersData?.players, playerQuery]);

  return (
    <div>
      <TodayBoard league="wnba" />
      <section className="mx-auto w-full max-w-[1200px] px-4 pb-10 md:px-8">
        <div className="mb-4 flex items-baseline justify-between gap-3">
          <h2 className="text-xl font-bold tracking-[-0.02em] text-ink">Players</h2>
          {!isLoading && !isError && (
            <span className="text-sm text-muted">
              {filteredPlayers.length}
              {playersData && filteredPlayers.length !== playersData.total
                ? ` of ${playersData.total}`
                : ""}
            </span>
          )}
        </div>
        <label className="mb-4 flex items-center gap-3 rounded-[20px] border border-line bg-white px-4 py-3">
          <Search className="h-5 w-5 text-brand" aria-hidden />
          <span className="sr-only">Find a player</span>
          <input
            type="search"
            value={playerQuery}
            onChange={(event) => setPlayerQuery(event.target.value)}
            placeholder="Type a name"
            className="w-full bg-transparent text-base text-ink outline-none placeholder:text-muted"
          />
        </label>
        {isError && (
          <p role="alert" className="rounded-[20px] border border-line bg-white px-4 py-5 text-sm text-ink">
            {error instanceof Error ? error.message : "Unable to fetch the WNBA player list."}
          </p>
        )}
        {isLoading && <p className="text-sm text-muted">Loading player list…</p>}
        {!isLoading && !isError && filteredPlayers.length === 0 && (
          <p className="rounded-[20px] border border-line bg-white px-4 py-5 text-sm text-muted">
            No players match your search.
          </p>
        )}
        {!isLoading && !isError && filteredPlayers.length > 0 && (
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {filteredPlayers.map((player) => (
              <li key={player}>
                <Link
                  href={`/wnba/player/${encodeURIComponent(player)}`}
                  className="flex items-center justify-between gap-3 rounded-[16px] border border-line bg-white px-4 py-3 text-ink hover:border-brand-soft"
                >
                  <span className="truncate font-medium">{player}</span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-muted" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
