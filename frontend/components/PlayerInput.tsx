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
        <label className="block text-sm font-bold text-dark mb-2">
          <Search className="inline w-4 h-4 mr-1.5" />
          Search Player
        </label>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray" />
          
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
              "input pl-10 pr-10",
              disabled && "opacity-50 cursor-not-allowed"
            )}
          />

          {isLoadingSearch && (
            <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-red animate-spin" />
          )}
        </div>

        {/* Dropdown */}
        {isOpen && filteredPlayers.length > 0 && (
          <ul
            ref={listRef}
            className="absolute z-50 w-full mt-2 bg-white border-2 border-dark rounded-lg max-h-60 overflow-auto"
          >
            {filteredPlayers.map((player, index) => (
              <li
                key={player}
                onClick={() => selectPlayer(player)}
                className={cn(
                  "px-4 py-3 cursor-pointer flex items-center gap-3 transition-colors duration-100",
                  index === highlightedIndex
                    ? "bg-yellow text-dark"
                    : "text-dark hover:bg-cream"
                )}
              >
                <User className="w-4 h-4 text-gray" />
                <span className="font-medium">{player}</span>
              </li>
            ))}
          </ul>
        )}

        {/* No results */}
        {isOpen && value.length >= 2 && !isLoadingSearch && filteredPlayers.length === 0 && (
          <div className="absolute z-50 w-full mt-2 px-4 py-3 bg-white border-2 border-dark rounded-lg">
            <p className="text-sm text-gray">
              No matching players found
            </p>
          </div>
        )}
      </div>

      {/* All players list */}
      <div>
        <label className="block text-sm font-bold text-dark mb-2">
          <Users className="inline w-4 h-4 mr-1.5" />
          All Players (Click to Select)
        </label>

        {isLoadingAll ? (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {[...Array(9)].map((_, i) => (
              <div key={i} className="skeleton h-10 rounded-lg" />
            ))}
          </div>
        ) : allPlayerList.length > 0 ? (
          <div className="max-h-64 overflow-y-auto rounded-lg border-2 border-dark/20 bg-white p-2">
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
                      "px-3 py-2 rounded-lg text-sm text-left",
                      "flex items-center gap-2",
                      "transition-all duration-150 border-2",
                      "focus:outline-none",
                      isSelected
                        ? "bg-red border-red text-white"
                        : "bg-white border-dark/20 text-dark hover:border-dark",
                      disabled && "opacity-50 cursor-not-allowed"
                    )}
                  >
                    <User className={cn(
                      "w-3.5 h-3.5 shrink-0",
                      isSelected ? "text-white" : "text-gray"
                    )} />
                    <span className="truncate font-medium">{player}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="px-4 py-8 text-center bg-white rounded-lg border-2 border-dark/20">
            <Users className="w-10 h-10 text-gray mx-auto mb-2" />
            <p className="text-sm text-gray">
              No player data available for this game yet
            </p>
          </div>
        )}

        {allPlayerList.length > 0 && (
          <p className="mt-2 text-xs text-gray">
            {allPlayerList.length} players have Props data for this stat type
          </p>
        )}
      </div>
    </div>
  );
}
