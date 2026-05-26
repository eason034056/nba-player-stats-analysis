/**
 * WnbaBetSlipContext.tsx — WNBA Bet Slip global state
 *
 * Phase 6 deliverable (SPO-37). Sister context to `BetSlipContext.tsx`.
 *
 * ⚠ Independence is the whole point of this file
 * ---------------------------------------------
 * SPO-29 architectural guardrail: "Two contexts, fully independent. Do not try
 * to be clever and put them in one store with a league discriminator."
 *
 * What that means in code:
 *   - Separate React Context (`WnbaBetSlipContext`, not the NBA one).
 *   - Separate `useState` slot — adding a WNBA leg never touches NBA state.
 *   - Separate localStorage key (`wnba_betslip_picks`). NBA reads/writes
 *     `betslip_picks`. The keys never collide; clearing one does not clear
 *     the other; uninstalling one phase will not corrupt the other.
 *   - Same `BetSlipPick` *type*. The shape of a pick is identical across
 *     leagues (player_name, metric, threshold, …). Type-reuse is not
 *     state-sharing — the data flowing through these contexts has different
 *     identities, even when it has the same fields.
 *
 * 💡 Why two separate localStorage keys instead of one keyed-by-league?
 * Because a single key would force every read/write to go through a league
 * discriminator, and a bug there would silently leak NBA picks into the WNBA
 * slip (or vice versa). Two keys = compiler/runtime can never confuse them.
 */

"use client";

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";

import type { BetSlipPick } from "./BetSlipContext";

// Re-export the type for callers that don't want to know the original lives
// in the NBA context file — keeps `import { useWnbaBetSlip, type BetSlipPick }
// from "@/contexts/WnbaBetSlipContext"` ergonomic.
export type { BetSlipPick };

/**
 * WnbaBetSlipContextType — Context value shape.
 *
 * Mirrors NBA's `BetSlipContextType` field-for-field so consumers can drop in
 * with minimal rewiring. The only API difference: this hook ONLY ever returns
 * picks added through WNBA flows; NBA picks live in `useBetSlip()`.
 */
interface WnbaBetSlipContextType {
  /** Current WNBA picks in the slip */
  picks: BetSlipPick[];
  /** Add a pick to the WNBA slip */
  addPick: (pick: Omit<BetSlipPick, "id" | "added_at">) => void;
  /** Remove a pick by id */
  removePick: (id: string) => void;
  /** Clear all WNBA picks */
  clearAll: () => void;
  /** Check whether a (player, metric) pair is already in the WNBA slip */
  isInSlip: (playerName: string, metric: string) => boolean;
  /** Current count — used by Navbar badge when path is under /wnba */
  count: number;
}

const WnbaBetSlipContext = createContext<WnbaBetSlipContextType | undefined>(
  undefined,
);

// ⚠ Must NOT match the NBA storage key. NBA uses "betslip_picks".
const STORAGE_KEY = "wnba_betslip_picks";

/**
 * WnbaBetSlipProvider — mount near the React root, alongside (NOT inside) the
 * NBA `BetSlipProvider`. Two siblings → independent state trees.
 */
export function WnbaBetSlipProvider({ children }: { children: ReactNode }) {
  const [picks, setPicks] = useState<BetSlipPick[]>([]);
  // 💡 isHydrated gate prevents the empty-on-mount state from overwriting a
  // populated localStorage value during the first render → save effect cycle.
  // Without this, opening a fresh tab would erase the saved slip on load.
  const [isHydrated, setIsHydrated] = useState(false);

  // Load from localStorage on mount (client-only — `localStorage` doesn't
  // exist during SSR, so this MUST be inside useEffect, not the initial state).
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          setPicks(parsed);
        }
      }
    } catch (error) {
      // ⚠ A corrupt localStorage entry must not crash the app — fall back to
      // an empty slip and keep moving. The user can always re-add picks.
      console.error("Failed to load WNBA betslip from localStorage:", error);
    }
    setIsHydrated(true);
  }, []);

  // Persist on every change AFTER hydration (see isHydrated comment above).
  useEffect(() => {
    if (isHydrated) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(picks));
      } catch (error) {
        console.error("Failed to save WNBA betslip to localStorage:", error);
      }
    }
  }, [picks, isHydrated]);

  // ID format mirrors NBA: `{player}-{metric}`. Direction is intentionally not
  // in the ID so the same player+metric can flip over↔under without producing
  // two duplicate rows — see PickContextMenu's "reverse bet" flow.
  const generateId = useCallback(
    (playerName: string, metric: string): string => {
      return `${playerName}-${metric}`;
    },
    [],
  );

  const addPick = useCallback(
    (pickData: Omit<BetSlipPick, "id" | "added_at">) => {
      const id = generateId(pickData.player_name, pickData.metric);
      setPicks((prev) => {
        if (prev.some((p) => p.id === id)) {
          return prev;
        }
        const newPick: BetSlipPick = {
          ...pickData,
          id,
          added_at: new Date().toISOString(),
        };
        return [...prev, newPick];
      });
    },
    [generateId],
  );

  const removePick = useCallback((id: string) => {
    setPicks((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const clearAll = useCallback(() => {
    setPicks([]);
  }, []);

  const isInSlip = useCallback(
    (playerName: string, metric: string): boolean => {
      const id = generateId(playerName, metric);
      return picks.some((p) => p.id === id);
    },
    [picks, generateId],
  );

  const value: WnbaBetSlipContextType = {
    picks,
    addPick,
    removePick,
    clearAll,
    isInSlip,
    count: picks.length,
  };

  return (
    <WnbaBetSlipContext.Provider value={value}>
      {children}
    </WnbaBetSlipContext.Provider>
  );
}

/**
 * useWnbaBetSlip — Hook for the WNBA slip.
 *
 * @throws if used outside a `<WnbaBetSlipProvider>`. The error message names
 *   the WNBA provider specifically so a developer who accidentally tries to
 *   read WNBA state from an NBA-only subtree gets a precise hint.
 */
export function useWnbaBetSlip(): WnbaBetSlipContextType {
  const context = useContext(WnbaBetSlipContext);
  if (context === undefined) {
    throw new Error(
      "useWnbaBetSlip must be used within a WnbaBetSlipProvider. " +
        "Make sure to wrap your app with <WnbaBetSlipProvider>.",
    );
  }
  return context;
}
