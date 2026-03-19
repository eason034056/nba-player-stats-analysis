/**
 * PickContextMenu.tsx - Context Menu Component
 *
 * Provides a right-click context menu for Pick cards
 * Users can quickly add or remove a pick from the bet slip via right click
 *
 * Features:
 * - Show menu on right-click
 * - Add to bet slip / remove (toggle based on state)
 * - View detailed data (navigate to event page)
 * - Close menu by clicking outside or pressing ESC
 *
 * Usage:
 * ```tsx
 * <PickContextMenu pick={pickData}>
 *   <PickCard pick={pickData} />
 * </PickContextMenu>
 * ```
 */

"use client";

import React, { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Plus, Minus, ExternalLink, ClipboardList, ArrowLeftRight } from "lucide-react";
import { useBetSlip, type BetSlipPick } from "@/contexts/BetSlipContext";
import { buildEventDetailHref } from "@/lib/event-detail-link";
import { type DailyPick } from "@/lib/schemas";

// ==================== Type Definitions ====================

interface PickContextMenuProps {
  /** Child component (the card to wrap) */
  children: ReactNode;
  /** Pick data */
  pick: DailyPick;
}

interface MenuPosition {
  x: number;
  y: number;
}

// ==================== Helper Functions ====================

/**
 * metric → market mapping
 *
 * Converts a short metric key to the market key used by the API
 */
function metricToMarket(metric: string): string {
  switch (metric) {
    case "points": return "player_points";
    case "rebounds": return "player_rebounds";
    case "assists": return "player_assists";
    case "pra": return "player_points_rebounds_assists";
    default: return "player_points";
  }
}

// ==================== Component ====================

/**
 * PickContextMenu - Context menu component
 *
 * Wraps any child component to provide a right-click context menu
 */
export function PickContextMenu({ children, pick }: PickContextMenuProps) {
  const router = useRouter();
  const { picks, addPick, removePick, isInSlip } = useBetSlip();
  
  // Menu state
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition>({ x: 0, y: 0 });
  
  // Refs
  const menuRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  
  // Check if already in bet slip
  const isAdded = isInSlip(pick.player_name, pick.metric);

  // ==================== Reverse Bet Info ====================

  /**
   * reverseDirection
   *
   * If original direction is "over", reverse is "under", and vice versa.
   * Allows users to take the opposite bet based on current situations.
   */
  const reverseDirection = pick.direction === "over" ? "under" : "over";

  /**
   * reverseProbability
   *
   * Reverse probability = 1 - original probability
   * E.g.: Original Over 90% → Reverse (Under) 10%
   */
  const reverseProbability = 1 - pick.probability;

  /**
   * reverseDirectionLabel
   *
   * "over" → "Over", "under" → "Under"
   */
  const reverseDirectionLabel = reverseDirection === "over" ? "Over" : "Under";

  /**
   * existingPick - Existing pick in bet slip with same player+metric
   *
   * Used to determine if the pick in bet slip is original or reversed direction
   */
  const existingPick = picks.find(
    (p) => p.player_name === pick.player_name && p.metric === pick.metric
  );

  /**
   * isReversedInSlip - Has the reverse bet already been added to the slip
   *
   * True if the pick in bet slip is in the reverse direction.
   * Used to display current state in menu.
   */
  const isReversedInSlip = existingPick?.direction === reverseDirection;

  // ==================== Event Handlers ====================

  /**
   * Handle right-click event
   *
   * Show menu and position it at the mouse location
   */
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    // Compute menu position—ensure it doesn't overflow the viewport
    const x = e.clientX;
    const y = e.clientY;
    
    // Get window size
    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;
    
    // Estimated menu size (increased after adding reverse bet option)
    const menuWidth = 220;
    const menuHeight = 200;
    
    // Adjust position to avoid overflowing
    const adjustedX = x + menuWidth > windowWidth ? windowWidth - menuWidth - 10 : x;
    const adjustedY = y + menuHeight > windowHeight ? windowHeight - menuHeight - 10 : y;
    
    setPosition({ x: adjustedX, y: adjustedY });
    setIsOpen(true);
  }, []);

  /**
   * Close the menu
   */
  const closeMenu = useCallback(() => {
    setIsOpen(false);
  }, []);

  /**
   * Handle adding/removing from bet slip
   */
  const handleToggleBetSlip = useCallback(() => {
    if (isAdded) {
      // Remove
      removePick(`${pick.player_name}-${pick.metric}`);
    } else {
      // Add
      const betSlipPick: Omit<BetSlipPick, "id" | "added_at"> = {
        player_name: pick.player_name,
        player_team: pick.player_team || "",
        event_id: pick.event_id,
        home_team: pick.home_team,
        away_team: pick.away_team,
        commence_time: pick.commence_time,
        metric: pick.metric,
        threshold: pick.threshold,
        direction: pick.direction,
        probability: pick.probability,
        n_games: pick.n_games,
      };
      addPick(betSlipPick);
    }
    closeMenu();
  }, [isAdded, pick, addPick, removePick, closeMenu]);

  /**
   * Handle adding reverse bet
   *
   * handleAddReverseBet - Add the pick with the opposite direction to the bet slip
   *
   * Usage:
   * - If the data says 90% Under, but user wants to bet Over based on circumstances
   * - Right-click → Click "Bet Reverse: Over X.X" to add the reverse bet
   *
   * Logic:
   * 1. First remove any existing pick with same player+metric (regardless of direction)
   * 2. Add a new pick, with direction reversed and probability = (1 - original)
   *
   * Why removePick before addPick?
   * - Because pick ID is `player_name-metric` (doesn't include direction)
   * - So you can only have one pick per player+metric at a time
   * - removePick uses functional update (setPicks(prev => ...))
   * - addPick also uses functional update, so React applies them sequentially
   * - addPick will see the state after removal, so there is no conflict
   */
  const handleAddReverseBet = useCallback(() => {
    const id = `${pick.player_name}-${pick.metric}`;

    // Remove existing pick if any
    removePick(id);

    // Add reverse pick
    const betSlipPick: Omit<BetSlipPick, "id" | "added_at"> = {
      player_name: pick.player_name,
      player_team: pick.player_team || "",
      event_id: pick.event_id,
      home_team: pick.home_team,
      away_team: pick.away_team,
      commence_time: pick.commence_time,
      metric: pick.metric,
      threshold: pick.threshold,
      direction: reverseDirection,           // Opposite direction
      probability: reverseProbability,       // Opposite probability
      n_games: pick.n_games,
    };
    addPick(betSlipPick);
    closeMenu();
  }, [pick, reverseDirection, reverseProbability, addPick, removePick, closeMenu]);

  /**
   * Handle viewing detailed data
   *
   * Navigate to event details page
   */
  const handleViewDetails = useCallback(() => {
    const marketKey = metricToMarket(pick.metric);
    const href = buildEventDetailHref({
      eventId: pick.event_id,
      commenceTime: pick.commence_time,
      player: pick.player_name,
      market: marketKey,
      threshold: pick.threshold,
    });
    router.push(href);
    closeMenu();
  }, [pick, router, closeMenu]);

  // ==================== Effects ====================

  /**
   * Close menu when clicking outside
   */
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        closeMenu();
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        closeMenu();
      }
    };

    // Delay adding listeners to avoid immediate trigger
    const timeoutId = setTimeout(() => {
      document.addEventListener("click", handleClickOutside);
      document.addEventListener("keydown", handleEscape);
    }, 0);

    return () => {
      clearTimeout(timeoutId);
      document.removeEventListener("click", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [isOpen, closeMenu]);

  /**
   * Close menu on scroll
   */
  useEffect(() => {
    if (!isOpen) return;

    const handleScroll = () => {
      closeMenu();
    };

    window.addEventListener("scroll", handleScroll, true);
    return () => window.removeEventListener("scroll", handleScroll, true);
  }, [isOpen, closeMenu]);

  // ==================== Render ====================

  // Menu content (rendered to body via portal)
  const menuContent = isOpen && (
    <div
      ref={menuRef}
      className="fixed min-w-[200px] py-2 bg-white rounded-lg shadow-xl border-2 border-dark/10 animate-fade-in"
      style={{
        left: position.x,
        top: position.y,
        zIndex: 9999, // Very high z-index to ensure on top
      }}
    >
      {/* Menu Header */}
      <div className="px-4 py-2 border-b border-dark/10">
        <p className="text-sm font-bold text-dark truncate">
          {pick.player_name}
        </p>
        <p className="text-xs text-gray">
          {pick.metric.charAt(0).toUpperCase() + pick.metric.slice(1)} {pick.direction} {pick.threshold}
        </p>
      </div>

      {/* Menu Options */}
      <div className="py-1">
        {/* Add/Remove from bet slip */}
        <button
          onClick={handleToggleBetSlip}
          className={`
            w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium
            transition-colors duration-150
            ${isAdded
              ? "text-red hover:bg-red/10"
              : "text-dark hover:bg-dark/5"
            }
          `}
        >
          {isAdded ? (
            <>
              <Minus className="w-4 h-4" />
              <span>Remove from Bet Slip</span>
            </>
          ) : (
            <>
              <Plus className="w-4 h-4" />
              <span>Add to Bet Slip</span>
            </>
          )}
        </button>

        {/* Divider */}
        <div className="mx-3 my-1 border-t border-dark/10" />

        {/* Reverse bet */}
        <button
          onClick={handleAddReverseBet}
          className={`
            w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium
            transition-colors duration-150
            ${isReversedInSlip
              ? "text-orange-600 hover:bg-orange-50"
              : "text-dark hover:bg-dark/5"
            }
          `}
        >
          <ArrowLeftRight className="w-4 h-4" />
          <span className="flex-1 text-left">
            {isReversedInSlip
              ? `Reversed in Slip`
              : `Bet Reverse: ${reverseDirectionLabel} ${pick.threshold}`
            }
          </span>
          {/* Reverse probability hint (small text) */}
          <span className="text-xs text-gray opacity-70">
            {(reverseProbability * 100).toFixed(0)}%
          </span>
        </button>

        {/* Divider */}
        <div className="mx-3 my-1 border-t border-dark/10" />

        {/* View details */}
        <button
          onClick={handleViewDetails}
          className="w-full flex items-center gap-3 px-4 py-2.5 text-sm font-medium text-dark hover:bg-dark/5 transition-colors duration-150"
        >
          <ExternalLink className="w-4 h-4" />
          <span>View Details</span>
        </button>
      </div>

      {/* Already added hint */}
      {isAdded && (
        <div className="px-4 py-2 border-t border-dark/10">
          <p className={`text-xs flex items-center gap-1.5 ${isReversedInSlip ? "text-orange-600" : "text-green-600"}`}>
            {isReversedInSlip ? (
              <>
                <ArrowLeftRight className="w-3 h-3" />
                Reversed bet in slip ({reverseDirectionLabel} {pick.threshold})
              </>
            ) : (
              <>
                <ClipboardList className="w-3 h-3" />
                In your bet slip
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );

  return (
    <div ref={containerRef} onContextMenu={handleContextMenu} className="relative">
      {/* Wrapped child component */}
      {children}

      {/* Context menu - Rendered via Portal to document.body to avoid overlap issues */}
      {typeof window !== "undefined" && menuContent && createPortal(menuContent, document.body)}
    </div>
  );
}
