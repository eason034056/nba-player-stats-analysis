import { z } from "zod";

import type { BetSlipPick } from "@/contexts/BetSlipContext";
import type { DailyPick } from "@/lib/schemas";

export const agentActionSchema = z.enum([
  "general",
  "analyze_pick",
  "review_slip",
  "risk_check",
  "line_movement",
  "plain_english",
  "review_board",
]);

export type AgentAction = z.infer<typeof agentActionSchema>;

export const agentPageContextSchema = z.object({
  route: z.string().default("/"),
  date: z.string().nullable().optional(),
  selected_teams: z.array(z.string()).default([]),
});

export type AgentPageContext = z.infer<typeof agentPageContextSchema>;

export const agentPickContextSchema = z.object({
  player_name: z.string(),
  player_team: z.string().default(""),
  event_id: z.string(),
  home_team: z.string(),
  away_team: z.string(),
  commence_time: z.string(),
  metric: z.string(),
  threshold: z.number(),
  direction: z.string(),
  probability: z.number(),
  n_games: z.number(),
  projected_value: z.number().nullable().optional(),
  projected_minutes: z.number().nullable().optional(),
  edge: z.number().nullable().optional(),
});

export type AgentPickContext = z.infer<typeof agentPickContextSchema>;

export const agentRequestContextSchema = z.object({
  page: agentPageContextSchema.nullable().optional(),
  selected_pick: agentPickContextSchema.nullable().optional(),
  visible_picks: z.array(agentPickContextSchema).default([]),
  bet_slip: z.array(agentPickContextSchema).default([]),
});

export type AgentRequestContext = z.infer<typeof agentRequestContextSchema>;

export const agentQuickActionSchema = z.object({
  action: agentActionSchema,
  label: z.string(),
  prompt: z.string(),
});

export type AgentQuickAction = z.infer<typeof agentQuickActionSchema>;

export const agentLineupTeamContextSchema = z.object({
  team: z.string(),
  status: z.enum(["projected", "partial", "unavailable"]),
  confidence: z.enum(["high", "medium", "low"]).nullable().optional(),
  source_disagreement: z.boolean().default(false),
  updated_at: z.string().nullable().optional(),
  player_is_projected_starter: z.boolean().nullable().optional(),
  starters: z.array(z.string()).default([]),
});

export type AgentLineupTeamContext = z.infer<typeof agentLineupTeamContextSchema>;

export const agentLineupContextSchema = z.object({
  summary: z.string().default(""),
  freshness_risk: z.boolean().default(false),
  player_team: agentLineupTeamContextSchema.nullable().optional(),
  opponent_team: agentLineupTeamContextSchema.nullable().optional(),
});

export type AgentLineupContext = z.infer<typeof agentLineupContextSchema>;

export const agentVerdictEvidenceStatSchema = z.object({
  label: z.string(),
  value: z.string(),
  tone: z.enum(["positive", "neutral", "caution", "muted"]).nullable().optional(),
});

export type AgentVerdictEvidenceStat = z.infer<typeof agentVerdictEvidenceStatSchema>;

export const agentVerdictBreakdownSectionSchema = z.object({
  key: z.enum([
    "historical",
    "trend_role",
    "shooting",
    "variance",
    "schedule",
    "own_team_injuries",
    "lineup",
    "market",
    "projection",
  ]),
  label: z.string(),
  tone: z.enum(["support", "caution", "neutral", "unavailable"]),
  reliability: z.number().nullable().optional(),
  signal_note: z.string(),
  risk_note: z.string().nullable().optional(),
  stats: z.array(agentVerdictEvidenceStatSchema).default([]),
});

export type AgentVerdictBreakdownSection = z.infer<typeof agentVerdictBreakdownSectionSchema>;

export const agentVerdictBreakdownSchema = z.object({
  sections: z.array(agentVerdictBreakdownSectionSchema).default([]),
});

export type AgentVerdictBreakdown = z.infer<typeof agentVerdictBreakdownSchema>;

export const agentVerdictCardSchema = z.object({
  subject: z.string(),
  decision: z.enum(["over", "under", "avoid"]),
  confidence: z.number(),
  model_probability: z.number(),
  market_implied_probability: z.number().nullable().optional(),
  expected_value_pct: z.number().nullable().optional(),
  market_pricing_mode: z.string().default("unavailable"),
  queried_line: z.number().nullable().optional(),
  best_line: z.number().nullable().optional(),
  available_lines: z.array(z.number()).default([]),
  best_book: z.string().nullable().optional(),
  best_odds: z.number().nullable().optional(),
  summary: z.string(),
  breakdown: agentVerdictBreakdownSchema.nullable().optional(),
  reasons: z.array(z.string()).default([]),
  risk_factors: z.array(z.string()).default([]),
  lineup_context: agentLineupContextSchema.nullable().optional(),
  recommendation: z.enum(["keep", "recheck", "remove"]).nullable().optional(),
});

export type AgentVerdictCard = z.infer<typeof agentVerdictCardSchema>;

export const agentSlipReviewSchema = z.object({
  items: z.array(agentVerdictCardSchema).default([]),
  summary: z.string(),
  keep_count: z.number(),
  recheck_count: z.number(),
  remove_count: z.number(),
});

export type AgentSlipReview = z.infer<typeof agentSlipReviewSchema>;

export const agentChatResponseSchema = z.object({
  thread: z.string(),
  action: agentActionSchema,
  status: z.enum([
    "ok",
    "line_moved",
    "not_enough_market_data",
    "injury_context_missing",
    "insufficient_context",
    "error",
  ]),
  reply: z.string(),
  verdict: agentVerdictCardSchema.nullable().optional(),
  slip_review: agentSlipReviewSchema.nullable().optional(),
  quick_actions: z.array(agentQuickActionSchema).default([]),
});

export type AgentChatResponse = z.infer<typeof agentChatResponseSchema>;

export interface AgentChatRequest {
  thread: string;
  message: string;
  action: AgentAction;
  context?: AgentRequestContext;
}

export interface AgentThreadMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  action?: AgentAction;
  status?: AgentChatResponse["status"];
  quick_actions?: AgentQuickAction[];
  verdict?: AgentVerdictCard | null;
  slip_review?: AgentSlipReview | null;
}

export const createAgentPickContextFromDailyPick = (
  pick: DailyPick,
): AgentPickContext => ({
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
  projected_value: pick.projected_value ?? null,
  projected_minutes: pick.projected_minutes ?? null,
  edge: pick.edge ?? null,
});

export const createAgentPickContextFromBetSlip = (
  pick: BetSlipPick,
): AgentPickContext => ({
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
  projected_value: null,
  projected_minutes: null,
  edge: null,
});
