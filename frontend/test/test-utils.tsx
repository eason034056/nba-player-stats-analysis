import type { ReactElement, ReactNode } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AgentWidget } from "@/components/AgentWidget";
import { AgentWidgetProvider } from "@/contexts/AgentWidgetContext";
import { BetSlipProvider, type BetSlipPick } from "@/contexts/BetSlipContext";

const STORAGE_KEY = "betslip_picks";

export function seedBetSlip(picks: BetSlipPick[]) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(picks));
}

export function clearBetSlip() {
  window.localStorage.removeItem(STORAGE_KEY);
}

export function createBetSlipPick(
  overrides: Partial<BetSlipPick> = {},
): BetSlipPick {
  return {
    id: "Stephen Curry-points",
    player_name: "Stephen Curry",
    player_team: "Los Angeles Lakers",
    event_id: "evt-1",
    home_team: "Los Angeles Lakers",
    away_team: "Golden State Warriors",
    commence_time: "2026-03-12T02:00:00Z",
    metric: "points",
    threshold: 28.5,
    direction: "over",
    probability: 0.72,
    n_games: 20,
    added_at: "2026-03-12T00:00:00.000Z",
    ...overrides,
  };
}

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  {
    queryClient = createTestQueryClient(),
    withAgentWidget = false,
  }: {
    queryClient?: QueryClient;
    withAgentWidget?: boolean;
  } = {},
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <BetSlipProvider>
          <AgentWidgetProvider>
            {children}
            {withAgentWidget ? <AgentWidget /> : null}
          </AgentWidgetProvider>
        </BetSlipProvider>
      </QueryClientProvider>
    );
  }

  return {
    queryClient,
    ...render(ui, { wrapper: Wrapper }),
  };
}
