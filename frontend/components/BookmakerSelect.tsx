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
      <label className="block text-sm font-bold text-dark mb-3">
        <Building2 className="inline w-4 h-4 mr-1.5" />
        Bookmakers
      </label>

      {/* Select all button */}
      <button
        type="button"
        onClick={toggleSelectAll}
        className={cn(
          "w-full mb-4 px-4 py-3 rounded-lg",
          "flex items-center justify-between",
          "border-2 transition-all duration-150 font-semibold",
          isAllSelected
            ? "bg-yellow border-yellow text-dark"
            : "bg-white border-dark/20 text-gray hover:border-dark"
        )}
      >
        <span>{isAllSelected ? "✓ All Selected" : "Select All"}</span>
        {isAllSelected && <Check className="w-5 h-5" />}
      </button>

      {/* Featured bookmakers */}
      <div className="mb-4">
        <h4 className="text-xs font-bold text-gray mb-2 uppercase tracking-wider">
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
                  "px-3 py-2.5 rounded-lg text-sm font-medium",
                  "flex items-center justify-between",
                  "border-2 transition-all duration-150",
                  selected
                    ? "bg-dark border-dark text-white"
                    : "bg-white border-dark/20 text-dark hover:border-dark"
                )}
              >
                <span className="truncate">{bookmaker.name}</span>
                {selected && (
                  <Check className="w-4 h-4 text-green-400 shrink-0 ml-2" />
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
          className="flex items-center justify-between w-full mb-2 text-xs font-bold text-gray hover:text-dark transition-colors uppercase tracking-wider"
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
                    "px-3 py-2 rounded-lg text-xs",
                    "flex items-center justify-between",
                    "border-2 transition-all duration-150",
                    selected
                      ? "bg-dark border-dark text-white"
                      : "bg-white border-dark/20 text-gray hover:border-dark hover:text-dark"
                  )}
                >
                  <span className="truncate">{bookmaker.name}</span>
                  {selected && (
                    <Check className="w-3.5 h-3.5 text-green-400 shrink-0 ml-1.5" />
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Selected count */}
      <p className="mt-4 text-xs text-gray">
        {isAllSelected ? (
          <>Will query all {BOOKMAKERS.length} bookmakers</>
        ) : (
          <>Selected <span className="text-dark font-bold">{value.length}</span> / {BOOKMAKERS.length}</>
        )}
      </p>
    </div>
  );
}
