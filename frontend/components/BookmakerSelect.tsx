/**
 * BookmakerSelect.tsx - Bookmaker Multi-Select Component (Minimal Design)
 * 
 * Design Philosophy:
 * - White cards with black borders
 * - Red/yellow accents for selection
 * - Clean checkbox interface
 */

"use client";

import { useState } from "react";
import { Check, Building2, ChevronDown, ChevronUp } from "lucide-react";
import { BOOKMAKERS, type BookmakerKey } from "@/lib/schemas";
import { cn } from "@/lib/utils";

// Grouped: Featured vs Others
const FEATURED_BOOKMAKERS = ["draftkings", "fanduel", "betmgm", "caesars", "espnbet", "bet365"];
const featuredBooks = BOOKMAKERS.filter(b => FEATURED_BOOKMAKERS.includes(b.key));
const otherBooks = BOOKMAKERS.filter(b => !FEATURED_BOOKMAKERS.includes(b.key));

interface BookmakerSelectProps {
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}

/**
 * BookmakerSelect Component
 */
export function BookmakerSelect({
  value,
  onChange,
  disabled = false,
}: BookmakerSelectProps) {
  const isAllSelected = value.length === 0;
  const [showOthers, setShowOthers] = useState(false);

  const toggleSelectAll = () => {
    if (isAllSelected) {
      onChange(featuredBooks.map(b => b.key));
    } else {
      onChange([]);
    }
  };

  const toggleBookmaker = (key: string) => {
    if (isAllSelected) {
      onChange(BOOKMAKERS.filter((b) => b.key !== key).map((b) => b.key));
    } else if (value.includes(key)) {
      const newValue = value.filter((v) => v !== key);
      if (newValue.length === BOOKMAKERS.length - 1) {
        onChange([]);
      } else {
        onChange(newValue);
      }
    } else {
      onChange([...value, key]);
    }
  };

  const isSelected = (key: string) => {
    return isAllSelected || value.includes(key);
  };

  return (
    <div className={cn(disabled && "opacity-50 pointer-events-none")}>
      {/* Label */}
      <label className="control-label mb-3">
        <Building2 className="h-4 w-4 text-red" />
        Bookmakers
      </label>

      {/* Select all button */}
      <button
        type="button"
        onClick={toggleSelectAll}
        className={cn(
          "mb-4 w-full rounded-full px-4 py-3",
          "flex items-center justify-between",
          "border transition-all duration-150 font-semibold",
          isAllSelected
            ? "control-segment-active"
            : "control-segment"
        )}
      >
        <span>{isAllSelected ? "✓ All Selected" : "Select All"}</span>
        {isAllSelected && <Check className="w-5 h-5" />}
      </button>

      {/* Featured bookmakers */}
      <div className="mb-4">
        <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-light">
          Featured Platforms
        </h4>
        <div className="grid grid-cols-2 gap-2">
          {featuredBooks.map((bookmaker) => {
            const selected = isSelected(bookmaker.key);

            return (
              <button
                key={bookmaker.key}
                type="button"
                onClick={() => toggleBookmaker(bookmaker.key)}
                className={cn(
                  selected ? "control-chip-active" : "control-chip",
                  "px-3 py-2.5 text-sm font-medium",
                  "flex items-center justify-between",
                )}
              >
                <span className="truncate text-inherit">{bookmaker.name}</span>
                {selected && (
                  <Check className="ml-2 h-4 w-4 shrink-0 text-green-300" />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Other bookmakers (collapsible) */}
      <div>
        <button
          type="button"
          onClick={() => setShowOthers(!showOthers)}
          className="mb-2 flex w-full items-center justify-between text-xs font-bold uppercase tracking-wider text-light transition-colors hover:text-dark"
        >
          <span>Other Bookmakers ({otherBooks.length})</span>
          {showOthers ? (
            <ChevronUp className="w-4 h-4" />
          ) : (
            <ChevronDown className="w-4 h-4" />
          )}
        </button>
        
        {showOthers && (
          <div className="grid grid-cols-2 gap-2 animate-fade-in">
            {otherBooks.map((bookmaker) => {
              const selected = isSelected(bookmaker.key);

              return (
                <button
                  key={bookmaker.key}
                  type="button"
                  onClick={() => toggleBookmaker(bookmaker.key)}
                  className={cn(
                    selected ? "control-chip-active" : "control-chip",
                    "px-3 py-2 text-xs",
                    "flex items-center justify-between",
                  )}
                >
                  <span className="truncate text-inherit">{bookmaker.name}</span>
                  {selected && (
                    <Check className="ml-1.5 h-3.5 w-3.5 shrink-0 text-green-300" />
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Selected count */}
      <p className="control-hint mt-4">
        {isAllSelected ? (
          <>Will query all {BOOKMAKERS.length} bookmakers</>
        ) : (
          <>Selected <span className="text-dark font-bold">{value.length}</span> / {BOOKMAKERS.length}</>
        )}
      </p>
    </div>
  );
}
