/**
 * PlayerInput.tsx - Player Input Component (Minimal Design)
 * 
 * Design Philosophy:
 * - Clean input with black borders
 * - Red for selected state
 * - Yellow for highlights
 */

"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, User, Loader2, Users } from "lucide-react";
import { getPlayerSuggestions } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { MarketKey } from "./MarketSelect";

interface PlayerInputProps {
  eventId: string;
  market?: MarketKey;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/**
 * PlayerInput Component
 */
export function PlayerInput({
  eventId,
  market = "player_points",
  value,
  onChange,
  disabled = false,
}: PlayerInputProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Get all players
  const { data: allPlayers, isLoading: isLoadingAll } = useQuery({
    queryKey: ["allPlayers", eventId, market],
    queryFn: () => getPlayerSuggestions(eventId, "", market),
    enabled: !!eventId,
    staleTime: 60 * 1000,
  });

  // Get search suggestions
  const { data: suggestions, isLoading: isLoadingSearch } = useQuery({
    queryKey: ["playerSuggestions", eventId, market, value],
    queryFn: () => getPlayerSuggestions(eventId, value, market),
    enabled: !!eventId && value.length >= 1,
    staleTime: 30 * 1000,
  });

  const allPlayerList = allPlayers?.players || [];
  const filteredPlayers = suggestions?.players || [];

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value;
    onChange(newValue);
    setIsOpen(true);
    setHighlightedIndex(-1);
  };

  const selectPlayer = useCallback((playerName: string) => {
    onChange(playerName);
    setIsOpen(false);
    setHighlightedIndex(-1);
    inputRef.current?.blur();
  }, [onChange]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || filteredPlayers.length === 0) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightedIndex((prev) =>
          prev < filteredPlayers.length - 1 ? prev + 1 : prev
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case "Enter":
        e.preventDefault();
        if (highlightedIndex >= 0) {
          selectPlayer(filteredPlayers[highlightedIndex]);
        }
        break;
      case "Escape":
        setIsOpen(false);
        break;
    }
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        inputRef.current &&
        !inputRef.current.contains(e.target as Node) &&
        listRef.current &&
        !listRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (highlightedIndex >= 0 && listRef.current) {
      const items = listRef.current.querySelectorAll("li");
      items[highlightedIndex]?.scrollIntoView({ block: "nearest" });
    }
  }, [highlightedIndex]);

  return (
    <div className="space-y-4">
      {/* Search input */}
      <div className="relative">
        <label className="control-label mb-2">
          <Search className="h-4 w-4 text-red" />
          Search Player
        </label>

        <div className="relative">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-light" />

          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={handleInputChange}
            onFocus={() => setIsOpen(true)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder="Enter player name, e.g., Stephen Curry"
            className={cn(
              "control-input pl-12 pr-11",
              disabled && "cursor-not-allowed opacity-50"
            )}
          />

          {isLoadingSearch && (
            <Loader2 className="absolute right-4 top-1/2 h-5 w-5 -translate-y-1/2 animate-spin text-red" />
          )}
        </div>

        {/* Dropdown */}
        {isOpen && filteredPlayers.length > 0 && (
          <ul
            ref={listRef}
            className="control-popover absolute z-50 mt-2 max-h-60 w-full"
          >
            {filteredPlayers.map((player, index) => (
              <li
                key={player}
                onClick={() => selectPlayer(player)}
                className={cn(
                  "control-option flex items-center gap-3 px-4 py-3",
                  index === highlightedIndex
                    ? "control-option-active"
                    : "text-dark"
                )}
              >
                <User className="h-4 w-4 text-light" />
                <span className="font-medium text-inherit">{player}</span>
              </li>
            ))}
          </ul>
        )}

        {/* No results */}
        {isOpen && value.length >= 2 && !isLoadingSearch && filteredPlayers.length === 0 && (
          <div className="control-popover absolute z-50 mt-2 w-full px-4 py-3">
            <p className="text-sm text-light">
              No matching players found
            </p>
          </div>
        )}
      </div>

      {/* All players list */}
      <div>
        <label className="control-label mb-2">
          <Users className="h-4 w-4 text-red" />
          All Players (Click to Select)
        </label>

        {isLoadingAll ? (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {[...Array(9)].map((_, i) => (
              <div key={i} className="skeleton h-10 rounded-lg" />
            ))}
          </div>
        ) : allPlayerList.length > 0 ? (
          <div className="control-popover max-h-64 p-2">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {allPlayerList.map((player) => {
                const isSelected = value === player;
                return (
                  <button
                    key={player}
                    type="button"
                    onClick={() => selectPlayer(player)}
                    disabled={disabled}
                    className={cn(
                      isSelected ? "control-chip-active" : "control-chip",
                      "px-3 py-2 text-left",
                      "flex items-center gap-2",
                      disabled && "cursor-not-allowed opacity-50"
                    )}
                  >
                    <User className={cn(
                      "h-3.5 w-3.5 shrink-0",
                      isSelected ? "text-white" : "text-light"
                    )} />
                    <span className="truncate font-medium text-inherit">{player}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="control-popover px-4 py-8 text-center">
            <Users className="mx-auto mb-2 h-10 w-10 text-light" />
            <p className="text-sm text-light">
              No player data available for this game yet
            </p>
          </div>
        )}

        {allPlayerList.length > 0 && (
          <p className="control-hint mt-2">
            {allPlayerList.length} players have Props data for this stat type
          </p>
        )}
      </div>
    </div>
  );
}
