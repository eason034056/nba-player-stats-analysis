import type {
  AgentAction,
  AgentPageContext,
  AgentPickContext,
  AgentQuickAction,
  AgentThreadMessage,
} from "@/lib/agent-chat";

interface CatalogAction extends AgentQuickAction {
  requiresPick?: boolean;
  requiresSlip?: boolean;
}

export interface AgentContextSummary {
  eyebrow: string;
  title: string;
  description: string;
}

const ACTION_CATALOG: CatalogAction[] = [
  {
    action: "analyze_pick",
    label: "Ask for verdict",
    prompt: "Should I bet this?",
    requiresPick: true,
  },
  {
    action: "risk_check",
    label: "Biggest risk",
    prompt: "What is the biggest risk?",
    requiresPick: true,
  },
  {
    action: "line_movement",
    label: "Line movement",
    prompt: "Summarize line movement",
    requiresPick: true,
  },
  {
    action: "plain_english",
    label: "Plain English",
    prompt: "Explain in plain English",
    requiresPick: true,
  },
  {
    action: "review_slip",
    label: "Compare with slip",
    prompt: "Compare with my slip",
    requiresSlip: true,
  },
];

const getCatalogAction = (action: AgentAction) =>
  ACTION_CATALOG.find((item) => item.action === action);

const isAvailableAction = (
  action: CatalogAction | AgentQuickAction,
  selectedPickContext: AgentPickContext | null,
  slipCount: number,
) => {
  const catalogAction = getCatalogAction(action.action);
  if (catalogAction?.requiresPick && !selectedPickContext) {
    return false;
  }

  if (catalogAction?.requiresSlip && slipCount === 0) {
    return false;
  }

  return true;
};

const dedupeActions = (actions: AgentQuickAction[]) => {
  const seen = new Set<AgentAction>();
  return actions.filter((action) => {
    if (seen.has(action.action)) {
      return false;
    }

    seen.add(action.action);
    return true;
  });
};

const buildFallbackPrimaryActions = (
  selectedPickContext: AgentPickContext | null,
  slipCount: number,
  lastAssistantAction?: AgentAction,
) => {
  if (!selectedPickContext && slipCount > 0) {
    return ACTION_CATALOG.filter(
      (item) => item.action === "review_slip" || item.action === "plain_english",
    );
  }

  if (!selectedPickContext) {
    return ACTION_CATALOG.filter((item) => item.action === "plain_english");
  }

  if (lastAssistantAction === "analyze_pick") {
    return ACTION_CATALOG.filter((item) =>
      ["risk_check", "line_movement", "plain_english"].includes(item.action),
    );
  }

  if (lastAssistantAction === "risk_check") {
    return ACTION_CATALOG.filter((item) =>
      ["analyze_pick", "line_movement", "plain_english"].includes(item.action),
    );
  }

  if (lastAssistantAction === "line_movement") {
    return ACTION_CATALOG.filter((item) =>
      ["analyze_pick", "risk_check", "plain_english"].includes(item.action),
    );
  }

  return ACTION_CATALOG.filter((item) =>
    ["analyze_pick", "risk_check", "line_movement"].includes(item.action),
  );
};

const formatTeamMatchup = (pick: AgentPickContext) =>
  `${pick.away_team} at ${pick.home_team}`;

export const getLastAssistantMessage = (messages: AgentThreadMessage[]) =>
  [...messages].reverse().find((message) => message.role === "assistant");

export const getContextSummary = (
  pageContext: AgentPageContext,
  selectedPickContext: AgentPickContext | null,
  slipCount: number,
  lastAssistantMessage?: AgentThreadMessage,
): AgentContextSummary => {
  if (selectedPickContext) {
    return {
      eyebrow: "Current pick",
      title: `${selectedPickContext.player_name} ${selectedPickContext.metric} ${selectedPickContext.direction} ${selectedPickContext.threshold}`,
      description: formatTeamMatchup(selectedPickContext),
    };
  }

  if (slipCount > 0) {
    return {
      eyebrow: "Slip context",
      title: `${slipCount} saved picks`,
      description:
        lastAssistantMessage?.slip_review?.summary ??
        `${slipCount} legs ready for review`,
    };
  }

  const filterCount = pageContext.selected_teams.length;
  return {
    eyebrow: "Board context",
    title: pageContext.date ? `Board for ${pageContext.date}` : "Current board",
    description:
      filterCount > 0
        ? `${filterCount} active filter${filterCount > 1 ? "s" : ""}`
        : "Ask about the board, a matchup, or a market move",
  };
};

export const getSuggestionSets = ({
  selectedPickContext,
  slipCount,
  messages,
}: {
  selectedPickContext: AgentPickContext | null;
  slipCount: number;
  messages: AgentThreadMessage[];
}) => {
  const lastAssistantMessage = getLastAssistantMessage(messages);
  const backendActions = (lastAssistantMessage?.quick_actions ?? []).filter((action) =>
    isAvailableAction(action, selectedPickContext, slipCount),
  );
  const fallbackPrimary = buildFallbackPrimaryActions(
    selectedPickContext,
    slipCount,
    lastAssistantMessage?.action,
  ).filter((action) =>
    isAvailableAction(action, selectedPickContext, slipCount),
  );
  const primaryActions = dedupeActions(
    backendActions.length > 0 ? backendActions : fallbackPrimary,
  ).slice(0, 3);
  const templateActions = dedupeActions(
    ACTION_CATALOG.filter((action) =>
      isAvailableAction(action, selectedPickContext, slipCount),
    ),
  ).filter(
    (action) => !primaryActions.some((primary) => primary.action === action.action),
  );

  return {
    starterActions: primaryActions.slice(0, 3),
    primaryActions,
    templateActions,
  };
};

export const formatPct = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(value)) {
    return "N/A";
  }

  return `${(value * 100).toFixed(1)}%`;
};

export const formatSignedPct = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(value)) {
    return "N/A";
  }

  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(1)}%`;
};
