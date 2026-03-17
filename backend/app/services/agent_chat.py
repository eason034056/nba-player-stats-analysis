from __future__ import annotations

import json
import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.models.agent_chat import (
    AgentAction,
    AgentChatRequest,
    AgentChatResponse,
    AgentLineupContext,
    AgentLineupTeamContext,
    AgentPickContext,
    AgentQuickAction,
    AgentSlipReview,
    AgentStatus,
    AgentVerdictBreakdown,
    AgentVerdictBreakdownSection,
    AgentVerdictCard,
    AgentVerdictEvidenceStat,
)

GraphRunner = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

logger = logging.getLogger(__name__)

_BOOKMAKER_LABELS = {
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "draftkings": "DraftKings",
    "espnbet": "ESPN BET",
    "fanduel": "FanDuel",
    "fanatics": "Fanatics",
}

_BREAKDOWN_SECTION_ORDER = (
    "historical",
    "trend_role",
    "shooting",
    "variance",
    "schedule",
    "own_team_injuries",
    "lineup",
    "market",
    "projection",
)

_BREAKDOWN_SECTION_LABELS = {
    "historical": "Historical",
    "trend_role": "Trend / Role",
    "shooting": "Shooting",
    "variance": "Variance",
    "schedule": "Schedule",
    "own_team_injuries": "Own-Team Injuries",
    "lineup": "Lineup",
    "market": "Market",
    "projection": "Projection",
}


def _resolve_agents_dir(service_file: Path) -> Path:
    resolved = service_file.resolve()

    for base in resolved.parents:
        candidate = base / "scripts" / "agents"
        if candidate.is_dir():
            return candidate

    raise FileNotFoundError(
        f"Could not locate scripts/agents relative to {resolved}"
    )


_AGENTS_DIR = _resolve_agents_dir(Path(__file__))
_PROJECT_ROOT = _AGENTS_DIR.parent.parent


class AgentChatService:
    def __init__(self, graph_runner: GraphRunner | None = None):
        self._graph_runner = graph_runner or self._run_graph_query

    async def handle_chat(self, request: AgentChatRequest) -> AgentChatResponse:
        thread = request.thread
        quick_actions = self._default_quick_actions()

        if request.action == "review_slip":
            return await self._handle_slip_review(request, thread, quick_actions)
        if request.action == "review_board":
            return await self._handle_board_review(request, thread, quick_actions)

        pick = request.context.selected_pick if request.context else None
        message = request.message.strip()

        if request.action in {"analyze_pick", "risk_check", "line_movement", "plain_english"} and pick is None:
            return AgentChatResponse(
                thread=thread,
                action=request.action,
                status="insufficient_context",
                reply="Pick context is missing. Use an Ask Agent button on a pick or board card first.",
                quick_actions=quick_actions,
            )

        if not message and pick is None:
            return AgentChatResponse(
                thread=thread,
                action=request.action,
                status="insufficient_context",
                reply="Tell me which pick or slip to analyze so I can price the bet cleanly.",
                quick_actions=quick_actions,
            )

        query = self._build_query(request.action, message, request)
        event_context = self._build_event_context(request, pick)

        try:
            result = await self._graph_runner(query, event_context)
        except Exception:
            return AgentChatResponse(
                thread=thread,
                action=request.action,
                status="error",
                reply="The agent could not finish the analysis right now. Try again in a moment.",
                quick_actions=quick_actions,
            )

        verdict = self._map_verdict(result, pick)
        status = self._derive_status(result)
        self._log_market_pricing(pick, verdict)

        return AgentChatResponse(
            thread=thread,
            action=request.action,
            status=status,
            reply=self._build_reply(status, verdict.summary),
            verdict=verdict,
            quick_actions=quick_actions,
        )

    async def _handle_slip_review(
        self,
        request: AgentChatRequest,
        thread: str,
        quick_actions: list[AgentQuickAction],
    ) -> AgentChatResponse:
        bet_slip = request.context.bet_slip if request.context else []
        if not bet_slip:
            return AgentChatResponse(
                thread=thread,
                action=request.action,
                status="insufficient_context",
                reply="Your bet slip is empty, so there is nothing to review yet.",
                quick_actions=quick_actions,
            )

        items: list[AgentVerdictCard] = []
        for pick in bet_slip[:6]:
            query = self._build_pick_query("Should I keep this bet in my slip?", pick, request)
            try:
                result = await self._graph_runner(query, self._build_event_context(request, pick))
            except Exception:
                continue

            verdict = self._map_verdict(result, pick)
            verdict.recommendation = self._classify_recommendation(
                pick.direction,
                verdict.decision,
                result.get("scorecard", {}).get("eligible_for_bet", False),
            )
            items.append(verdict)

        keep_count = sum(item.recommendation == "keep" for item in items)
        recheck_count = sum(item.recommendation == "recheck" for item in items)
        remove_count = sum(item.recommendation == "remove" for item in items)

        review = AgentSlipReview(
            items=items,
            summary=(
                f"Slip review complete: keep {keep_count}, recheck {recheck_count}, "
                f"remove {remove_count}."
            ),
            keep_count=keep_count,
            recheck_count=recheck_count,
            remove_count=remove_count,
        )

        return AgentChatResponse(
            thread=thread,
            action=request.action,
            status="ok",
            reply=review.summary,
            slip_review=review,
            quick_actions=quick_actions,
        )

    async def _handle_board_review(
        self,
        request: AgentChatRequest,
        thread: str,
        quick_actions: list[AgentQuickAction],
    ) -> AgentChatResponse:
        visible_picks = request.context.visible_picks if request.context else []
        if not visible_picks:
            return AgentChatResponse(
                thread=thread,
                action=request.action,
                status="insufficient_context",
                reply="Board context is missing. Refresh the board and try Review Board again.",
                quick_actions=quick_actions,
            )

        candidates: list[tuple[AgentVerdictCard, AgentStatus]] = []
        for pick in visible_picks[:6]:
            query = self._build_pick_query(
                "Review this candidate and identify the cleanest board bet.",
                pick,
                request,
            )
            try:
                result = await self._graph_runner(query, self._build_event_context(request, pick))
            except Exception:
                continue

            candidates.append((self._map_verdict(result, pick), self._derive_status(result)))

        if not candidates:
            return AgentChatResponse(
                thread=thread,
                action=request.action,
                status="error",
                reply="The agent could not finish the board review right now. Try again in a moment.",
                quick_actions=quick_actions,
            )

        verdict, status = max(
            candidates,
            key=lambda item: (
                item[0].market_pricing_mode == "exact_line",
                item[0].expected_value_pct if item[0].expected_value_pct is not None else float("-inf"),
                item[0].confidence,
            ),
        )
        summary = self._build_reply(status, verdict.summary)
        reply = f"Cleanest board bet right now is {verdict.subject}. {summary}".strip()

        return AgentChatResponse(
            thread=thread,
            action=request.action,
            status=status,
            reply=reply,
            verdict=verdict,
            quick_actions=quick_actions,
        )

    def _build_query(
        self,
        action: AgentAction,
        message: str,
        request: AgentChatRequest,
    ) -> str:
        pick = request.context.selected_pick if request.context else None
        if pick is None:
            return self._with_page_context(message, request)

        focus_prompt = {
            "analyze_pick": "Should I bet this?",
            "risk_check": "What is the biggest risk with this bet?",
            "line_movement": "Summarize line movement and pricing risk for this bet.",
            "plain_english": "Explain this bet in plain English.",
            "review_board": "Review this board context and identify the cleanest bet.",
            "general": message or "Should I bet this?",
            "review_slip": message or "Review this slip leg.",
        }.get(action, message or "Should I bet this?")

        return self._build_pick_query(focus_prompt, pick, request)

    def _build_event_context(
        self,
        request: AgentChatRequest,
        pick: AgentPickContext | None,
    ) -> dict[str, Any]:
        page = request.context.page if request.context else None
        event_context: dict[str, Any] = {
            "action": request.action,
            "route": page.route if page else "",
            "date": page.date if page else "",
            "selected_teams": list(page.selected_teams) if page and page.selected_teams else [],
        }

        if pick is not None:
            event_context.update(
                {
                    "event_id": pick.event_id,
                    "player_name": pick.player_name,
                    "player_team": pick.player_team,
                    "metric": pick.metric,
                    "threshold": pick.threshold,
                    "direction": pick.direction,
                    "home_team": pick.home_team,
                    "away_team": pick.away_team,
                    "selected_pick": pick.model_dump(mode="json"),
                }
            )

        if request.context and request.context.visible_picks:
            event_context["visible_picks"] = [
                visible_pick.model_dump(mode="json")
                for visible_pick in request.context.visible_picks
            ]

        return event_context

    def _build_pick_query(
        self,
        prompt: str,
        pick: AgentPickContext,
        request: AgentChatRequest,
    ) -> str:
        date = request.context.page.date if request.context and request.context.page else ""
        teams = (
            ", ".join(request.context.page.selected_teams)
            if request.context and request.context.page and request.context.page.selected_teams
            else ""
        )
        details = (
            f"{pick.player_name} {pick.direction} {pick.threshold} {pick.metric}. "
            f"Matchup: {pick.away_team} @ {pick.home_team}. "
        )
        if date:
            details += f"Date: {date}. "
        if teams:
            details += f"Filtered teams: {teams}. "
        return f"{prompt} {details}".strip()

    def _with_page_context(self, message: str, request: AgentChatRequest) -> str:
        page = request.context.page if request.context else None
        if page is None:
            return message
        parts = [message]
        if page.route:
            parts.append(f"Current route: {page.route}.")
        if page.date:
            parts.append(f"Date: {page.date}.")
        if page.selected_teams:
            parts.append(f"Selected teams: {', '.join(page.selected_teams)}.")
        return " ".join(part for part in parts if part).strip()

    def _map_verdict(
        self,
        result: dict[str, Any],
        pick: AgentPickContext | None,
    ) -> AgentVerdictCard:
        final = result.get("final_decision", {})
        summary = str(final.get("summary", "")).strip() or "Analysis completed."
        scorecard = result.get("scorecard", {})
        lineup_context = self._extract_lineup_context(scorecard, final)
        breakdown = self._build_verdict_breakdown(result, pick, lineup_context)
        return AgentVerdictCard(
            subject=self._format_subject(pick),
            decision=scorecard.get("decision", final.get("decision", "avoid")),
            confidence=float(scorecard.get("confidence", final.get("confidence", 0.0)) or 0.0),
            model_probability=float(
                scorecard.get("model_probability", final.get("model_probability", 0.0)) or 0.0
            ),
            market_implied_probability=(
                float(scorecard["market_implied_probability"])
                if scorecard.get("market_implied_probability") is not None
                else None
            ),
            expected_value_pct=(
                float(scorecard["expected_value_pct"])
                if scorecard.get("expected_value_pct") is not None
                else None
            ),
            market_pricing_mode=str(
                scorecard.get("market_pricing_mode", final.get("market_pricing_mode", "unavailable"))
            ),
            queried_line=(
                float(scorecard["queried_line"])
                if scorecard.get("queried_line") is not None
                else None
            ),
            best_line=(
                float(scorecard["best_line"])
                if scorecard.get("best_line") is not None
                else None
            ),
            available_lines=list(scorecard.get("available_lines") or final.get("available_lines") or []),
            best_book=scorecard.get("best_book", final.get("best_book")),
            best_odds=scorecard.get("best_odds", final.get("best_odds")),
            summary=summary,
            breakdown=breakdown,
            reasons=self._build_legacy_reasons(breakdown, final),
            risk_factors=list(final.get("risk_factors") or result.get("critic_notes") or []),
            lineup_context=lineup_context,
        )

    def _extract_lineup_context(
        self,
        scorecard: dict[str, Any],
        final: dict[str, Any],
    ) -> AgentLineupContext | None:
        raw = scorecard.get("lineup_context") or final.get("lineup_context")
        if not isinstance(raw, dict):
            return None

        def _map_team(payload: Any) -> AgentLineupTeamContext | None:
            if not isinstance(payload, dict):
                return None
            team = str(payload.get("team", "")).strip()
            status = str(payload.get("status", "")).strip()
            if not team or not status:
                return None
            return AgentLineupTeamContext(
                team=team,
                status=status,  # type: ignore[arg-type]
                confidence=payload.get("confidence"),
                source_disagreement=bool(payload.get("source_disagreement")),
                updated_at=payload.get("updated_at"),
                player_is_projected_starter=payload.get("player_is_projected_starter"),
                starters=list(payload.get("starters") or []),
            )

        return AgentLineupContext(
            summary=str(raw.get("summary", "")).strip(),
            freshness_risk=bool(raw.get("freshness_risk")),
            player_team=_map_team(raw.get("player_team")),
            opponent_team=_map_team(raw.get("opponent_team")),
        )

    def _build_verdict_breakdown(
        self,
        result: dict[str, Any],
        pick: AgentPickContext | None,
        lineup_context: AgentLineupContext | None,
    ) -> AgentVerdictBreakdown:
        scorecard = result.get("scorecard", {}) or {}
        final = result.get("final_decision", {}) or {}
        context = scorecard.get("query_aligned_context") or final.get("query_aligned_context") or {}
        historical_signals = result.get("historical_signals", {}) or {}
        market_signals = result.get("market_signals", {}) or {}

        query_side = str(
            (context.get("query_side") if isinstance(context, dict) else "")
            or (pick.direction if pick else "")
            or scorecard.get("direction")
            or "over"
        ).lower()
        if query_side not in {"over", "under"}:
            query_side = "over"

        historical_ctx = context.get("historical") if isinstance(context, dict) else {}
        trend_ctx = context.get("trend") if isinstance(context, dict) else {}
        market_ctx = context.get("market") if isinstance(context, dict) else {}
        schedule_ctx = context.get("schedule") if isinstance(context, dict) else {}
        injuries_ctx = context.get("injuries") if isinstance(context, dict) else {}

        sections = [
            self._build_historical_section(
                query_side,
                historical_ctx if isinstance(historical_ctx, dict) else {},
                historical_signals.get("get_base_stats") or {},
                historical_signals.get("get_role_conditioned_base_stats") or {},
            ),
            self._build_trend_role_section(
                query_side,
                trend_ctx if isinstance(trend_ctx, dict) else {},
                historical_ctx if isinstance(historical_ctx, dict) else {},
                historical_signals.get("get_trend_analysis") or {},
                historical_signals.get("get_role_conditioned_base_stats") or {},
            ),
            self._build_shooting_section(
                query_side,
                historical_signals.get("get_shooting_profile") or {},
            ),
            self._build_variance_section(
                historical_signals.get("get_variance_profile") or {},
            ),
            self._build_schedule_section(
                query_side,
                schedule_ctx if isinstance(schedule_ctx, dict) else {},
                historical_signals.get("get_schedule_context") or {},
            ),
            self._build_own_team_injuries_section(
                query_side,
                injuries_ctx if isinstance(injuries_ctx, dict) else {},
                historical_signals.get("auto_teammate_impact") or {},
                historical_signals.get("get_own_team_injury_report") or {},
            ),
            self._build_lineup_section(
                historical_signals.get("get_player_lineup_context") or {},
                historical_signals.get("get_own_team_projected_lineup") or {},
                historical_signals.get("get_opponent_projected_lineup") or {},
                lineup_context,
            ),
            self._build_market_section(
                query_side,
                market_ctx if isinstance(market_ctx, dict) else {},
                scorecard,
                market_signals.get("get_current_market") or {},
                market_signals.get("get_market_quote_for_line") or {},
                market_signals.get("get_bookmaker_spread") or {},
            ),
            self._build_projection_section(),
        ]
        return AgentVerdictBreakdown(sections=sections)

    def _build_legacy_reasons(
        self,
        breakdown: AgentVerdictBreakdown | None,
        final: dict[str, Any],
    ) -> list[str]:
        if breakdown is not None:
            reasons = [
                section.signal_note.strip()
                for section in breakdown.sections
                if section.tone != "unavailable" and section.signal_note.strip()
            ]
            if reasons:
                return reasons[:3]
        return self._extract_reasons(final)

    def _build_section(
        self,
        key: str,
        tone: str,
        signal_note: str,
        *,
        reliability: float | None = None,
        risk_note: str | None = None,
        stats: list[AgentVerdictEvidenceStat] | None = None,
    ) -> AgentVerdictBreakdownSection:
        normalized_tone = tone if tone in {"support", "caution", "neutral", "unavailable"} else "neutral"
        normalized_reliability = None
        if isinstance(reliability, (int, float)):
            normalized_reliability = max(0.0, min(float(reliability), 1.0))
        return AgentVerdictBreakdownSection(
            key=key,  # type: ignore[arg-type]
            label=_BREAKDOWN_SECTION_LABELS[key],
            tone=normalized_tone,  # type: ignore[arg-type]
            reliability=normalized_reliability,
            signal_note=signal_note.strip(),
            risk_note=risk_note.strip() if isinstance(risk_note, str) and risk_note.strip() else None,
            stats=stats or [],
        )

    def _build_stat(
        self,
        label: str,
        value: str | None,
        tone: str | None = None,
    ) -> AgentVerdictEvidenceStat | None:
        if value is None:
            return None
        clean_value = str(value).strip()
        if not clean_value:
            return None
        normalized_tone = tone if tone in {"positive", "neutral", "caution", "muted"} else None
        return AgentVerdictEvidenceStat(
            label=label,
            value=clean_value,
            tone=normalized_tone,  # type: ignore[arg-type]
        )

    def _build_historical_section(
        self,
        query_side: str,
        historical_ctx: dict[str, Any],
        base_signal: dict[str, Any],
        role_signal: dict[str, Any],
    ) -> AgentVerdictBreakdownSection:
        probability = historical_ctx.get("query_probability")
        mean = historical_ctx.get("mean")
        threshold = historical_ctx.get("threshold")
        sample_size = self._safe_int(base_signal.get("sample_size"))
        role_weight = historical_ctx.get("role_weight")
        role_sample_size = self._safe_int(historical_ctx.get("role_sample_size"))
        reliability = self._average_reliability(
            base_signal.get("reliability"),
            role_signal.get("reliability"),
        )

        if probability is None or mean is None or threshold is None:
            return self._build_section(
                "historical",
                "unavailable",
                "Historical baseline is unavailable for this pick.",
                reliability=self._average_reliability(base_signal.get("reliability")),
                stats=self._collect_stats(
                    self._build_stat("Sample", self._format_sample(sample_size), self._sample_stat_tone(sample_size)),
                ),
            )

        risk_note = None
        if role_weight and role_sample_size and role_weight > 0 and role_sample_size < 8:
            risk_note = f"Role-conditioned sample is still thin at {role_sample_size} games."
        elif sample_size is not None and sample_size < 10:
            risk_note = f"Historical sample is light at {sample_size} games."
        elif abs(float(probability) - 0.5) < 0.05:
            risk_note = "Historical edge is narrow relative to the line."

        return self._build_section(
            "historical",
            self._tone_from_probability(probability),
            self._format_historical_reason(historical_ctx, query_side)
            or "Historical context is available but incomplete.",
            reliability=reliability,
            risk_note=risk_note,
            stats=self._collect_stats(
                self._build_stat(
                    "Query prob",
                    self._format_probability(probability),
                    self._probability_stat_tone(probability),
                ),
                self._build_stat(
                    "Mean vs line",
                    f"{self._format_decimal(mean)} vs {self._format_decimal(threshold)}",
                    self._line_alignment_stat_tone(query_side, mean, threshold),
                ),
                self._build_stat(
                    "Sample",
                    self._format_sample(sample_size),
                    self._sample_stat_tone(sample_size),
                ),
            ),
        )

    def _build_trend_role_section(
        self,
        query_side: str,
        trend_ctx: dict[str, Any],
        historical_ctx: dict[str, Any],
        trend_signal: dict[str, Any],
        role_signal: dict[str, Any],
    ) -> AgentVerdictBreakdownSection:
        recent_average = trend_ctx.get("recent_average")
        season_average = trend_ctx.get("season_average")
        role_weight = historical_ctx.get("role_weight")
        role_sample_size = self._safe_int(historical_ctx.get("role_sample_size"))
        alignment = str(trend_ctx.get("signal_alignment") or "neutral")

        if recent_average is None and season_average is None:
            return self._build_section(
                "trend_role",
                "unavailable",
                "Recent form and role trend are unavailable.",
                reliability=self._average_reliability(trend_signal.get("reliability"), role_signal.get("reliability")),
            )

        threshold = historical_ctx.get("threshold")
        signal_note = self._format_trend_reason(trend_ctx, historical_ctx, query_side)
        role_note = None
        if role_weight and role_weight > 0 and role_sample_size:
            role_name = str(historical_ctx.get("role") or "role-based").replace("_", " ")
            role_note = (
                f" Role blend uses the {role_name} sample at {float(role_weight) * 100:.0f}% weight "
                f"({role_sample_size} games)."
            )
        if not signal_note:
            signal_note = "Trend and role context are present but incomplete."
        if role_note:
            signal_note = f"{signal_note}{role_note}"

        risk_note = None
        if alignment == "against_query_side":
            risk_note = f"Recent form is moving against the {query_side}."
        elif role_weight and role_sample_size and role_weight > 0 and role_sample_size < 8:
            risk_note = f"Role blend leans on only {role_sample_size} role-specific games."

        tone = "neutral"
        if alignment == "supports_query_side":
            tone = "support"
        elif alignment == "against_query_side":
            tone = "caution"

        return self._build_section(
            "trend_role",
            tone,
            signal_note,
            reliability=self._average_reliability(trend_signal.get("reliability"), role_signal.get("reliability")),
            risk_note=risk_note,
            stats=self._collect_stats(
                self._build_stat(
                    "Last 5 avg",
                    self._format_decimal_or_none(recent_average),
                    self._line_alignment_stat_tone(query_side, recent_average, threshold),
                ),
                self._build_stat(
                    "Season avg",
                    self._format_decimal_or_none(season_average),
                    "neutral",
                ),
                self._build_stat(
                    "Role weight",
                    self._format_weight_or_sample(role_weight, role_sample_size),
                    "neutral",
                ),
            ),
        )

    def _build_shooting_section(
        self,
        query_side: str,
        shooting_signal: dict[str, Any],
    ) -> AgentVerdictBreakdownSection:
        details = shooting_signal.get("details") or {}
        season = details.get("season") or {}
        last_5 = details.get("last_5") or {}
        fg_diff = details.get("fg_diff")
        if not season and not last_5:
            return self._build_section(
                "shooting",
                "unavailable",
                "Shooting context is unavailable.",
                reliability=self._average_reliability(shooting_signal.get("reliability")),
            )

        tone = "neutral"
        if isinstance(fg_diff, (int, float)):
            if float(fg_diff) > 0.03:
                tone = "support" if query_side == "over" else "caution"
            elif float(fg_diff) < -0.03:
                tone = "support" if query_side == "under" else "caution"

        signal_note = "Shooting form is close to season baseline."
        if isinstance(fg_diff, (int, float)) and abs(float(fg_diff)) >= 0.01:
            trend_word = "hotter" if float(fg_diff) > 0 else "colder"
            signal_note = (
                f"Shooting form runs {trend_word} than the season baseline: last 5 FG% is "
                f"{self._format_percent(last_5.get('fg_pct'))} versus {self._format_percent(season.get('fg_pct'))}."
            )

        flags = details.get("flags") or []
        risk_note = None
        if "hot_shooting_regression_risk" in flags:
            risk_note = "Recent efficiency spike could regress from this baseline."
        elif "cold_shooting_bounce_back" in flags:
            risk_note = "Recent efficiency dip could bounce back quickly."
        elif "fta_spike_aggression" in flags:
            risk_note = "Free-throw volume is elevated relative to season norms."

        return self._build_section(
            "shooting",
            tone,
            signal_note,
            reliability=self._average_reliability(shooting_signal.get("reliability")),
            risk_note=risk_note,
            stats=self._collect_stats(
                self._build_stat(
                    "Last 5 FG%",
                    self._format_percent(last_5.get("fg_pct")),
                    "positive" if tone == "support" else ("caution" if tone == "caution" else "neutral"),
                ),
                self._build_stat("Season FG%", self._format_percent(season.get("fg_pct")), "neutral"),
                self._build_stat("FG diff", self._format_signed_decimal(fg_diff, 3), self._delta_tone(fg_diff)),
            ),
        )

    def _build_variance_section(
        self,
        variance_signal: dict[str, Any],
    ) -> AgentVerdictBreakdownSection:
        details = variance_signal.get("details") or {}
        cv = details.get("cv")
        if cv is None:
            return self._build_section(
                "variance",
                "unavailable",
                "Variance profile is unavailable.",
                reliability=self._average_reliability(variance_signal.get("reliability")),
            )

        tone = "neutral"
        if float(cv) > 0.4:
            tone = "caution"
        elif float(cv) < 0.25:
            tone = "support"

        signal_note = (
            f"{'Outcome variance is high' if tone == 'caution' else 'Distribution is relatively stable'}: "
            f"CV {self._format_decimal(cv)} with a {self._format_decimal(details.get('p10'))}-"
            f"{self._format_decimal(details.get('p90'))} 10th-90th percentile range."
        )
        risk_note = "High variance can overwhelm a thin edge." if tone == "caution" else None

        return self._build_section(
            "variance",
            tone,
            signal_note,
            reliability=self._average_reliability(variance_signal.get("reliability")),
            risk_note=risk_note,
            stats=self._collect_stats(
                self._build_stat("CV", self._format_decimal(cv), "caution" if tone == "caution" else "neutral"),
                self._build_stat("P10", self._format_decimal_or_none(details.get("p10")), "neutral"),
                self._build_stat("P90", self._format_decimal_or_none(details.get("p90")), "neutral"),
            ),
        )

    def _build_schedule_section(
        self,
        query_side: str,
        schedule_ctx: dict[str, Any],
        schedule_signal: dict[str, Any],
    ) -> AgentVerdictBreakdownSection:
        details = schedule_signal.get("details") or {}
        is_back_to_back = schedule_ctx.get("is_back_to_back")
        days_rest = details.get("days_rest")
        if is_back_to_back is None and days_rest is None:
            return self._build_section(
                "schedule",
                "unavailable",
                "Schedule context is unavailable.",
                reliability=self._average_reliability(schedule_signal.get("reliability")),
            )

        tone = "neutral"
        if bool(is_back_to_back):
            tone = "support" if query_side == "under" else "caution"

        signal_note = self._format_schedule_reason(schedule_ctx, query_side) or "Schedule context is neutral."
        if days_rest is not None:
            signal_note = f"{signal_note[:-1]} with {int(days_rest)} day{'s' if int(days_rest) != 1 else ''} rest."

        risk_note = None
        if bool(is_back_to_back):
            risk_note = (
                "Back-to-back workload can change minute ceilings quickly."
                if query_side == "over"
                else "Back-to-back is still a soft context signal, not a standalone edge."
            )

        avg_minutes_by_rest = details.get("avg_minutes_by_rest") or {}
        relevant_minutes = avg_minutes_by_rest.get("b2b") if bool(is_back_to_back) else avg_minutes_by_rest.get("normal")
        relevant_label = "B2B avg min" if bool(is_back_to_back) else "Normal rest min"

        return self._build_section(
            "schedule",
            tone,
            signal_note,
            reliability=self._average_reliability(schedule_signal.get("reliability")),
            risk_note=risk_note,
            stats=self._collect_stats(
                self._build_stat("Days rest", self._format_days_rest(days_rest), "neutral"),
                self._build_stat("Back-to-back", "Yes" if bool(is_back_to_back) else "No", "caution" if bool(is_back_to_back) else "neutral"),
                self._build_stat(relevant_label, self._format_decimal_or_none(relevant_minutes), "neutral"),
            ),
        )

    def _build_own_team_injuries_section(
        self,
        query_side: str,
        injuries_ctx: dict[str, Any],
        teammate_signal: dict[str, Any],
        own_report: dict[str, Any],
    ) -> AgentVerdictBreakdownSection:
        report_details = own_report.get("details") or {}
        report_injuries = report_details.get("injuries") or []
        chemistry_rows = ((teammate_signal.get("details") or {}).get("teammate_chemistry") or [])
        out_players = [str(player).strip() for player in injuries_ctx.get("out_players") or [] if str(player).strip()]
        questionable_players = [
            str(player).strip()
            for player in injuries_ctx.get("questionable_players") or []
            if str(player).strip()
        ]

        top_impact: dict[str, Any] | None = None
        impact_shift = 0.0
        for row in chemistry_rows:
            status = str(row.get("injury_status") or "")
            if status not in {"Out", "Questionable", "Day-To-Day"}:
                continue
            shift = -float(row.get("chemistry_delta") or 0.0)
            if top_impact is None or abs(shift) > abs(impact_shift):
                top_impact = row
                impact_shift = shift

        has_report_context = bool(report_injuries) or own_report.get("signal") in {"neutral", "caution"}
        if not has_report_context and not out_players and not questionable_players and not chemistry_rows:
            return self._build_section(
                "own_team_injuries",
                "unavailable",
                "Own-team injury context is unavailable.",
                reliability=self._average_reliability(own_report.get("reliability"), teammate_signal.get("reliability")),
            )

        tone = "neutral"
        signal_note = "No own-team injury swing stands out right now."
        if top_impact is not None and abs(impact_shift) >= 0.25:
            affected_side = "over" if impact_shift > 0 else "under"
            tone = "support" if affected_side == query_side else "caution"
            signal_note = (
                f"Own-team injuries lean to the {affected_side}: without {top_impact.get('star')}, "
                f"this player shifts by {self._format_signed_decimal(impact_shift)}."
            )
        elif out_players:
            signal_note = (
                f"Own-team injuries are active: teammates out include {', '.join(out_players[:3])}."
            )
            tone = "neutral"
        elif questionable_players:
            signal_note = (
                f"Injury context is still moving with questionable teammates {', '.join(questionable_players[:3])}."
            )
            tone = "caution"

        risk_note = None
        if questionable_players:
            risk_note = (
                f"Questionable teammates {', '.join(questionable_players[:3])} can still change the role context."
            )
        elif len(out_players) >= 2:
            risk_note = "Multiple teammates are already out, which can reshape the rotation quickly."

        return self._build_section(
            "own_team_injuries",
            tone,
            signal_note,
            reliability=self._average_reliability(own_report.get("reliability"), teammate_signal.get("reliability")),
            risk_note=risk_note,
            stats=self._collect_stats(
                self._build_stat("Out", str(len(out_players)), "neutral"),
                self._build_stat("Questionable", str(len(questionable_players)), "caution" if questionable_players else "neutral"),
                self._build_stat(
                    "Top swing",
                    self._format_top_impact(top_impact, impact_shift),
                    self._impact_shift_tone(query_side, impact_shift) if top_impact is not None else "muted",
                ),
            ),
        )

    def _build_lineup_section(
        self,
        player_lineup_signal: dict[str, Any],
        own_team_lineup_signal: dict[str, Any],
        opponent_lineup_signal: dict[str, Any],
        lineup_context: AgentLineupContext | None,
    ) -> AgentVerdictBreakdownSection:
        player_details = player_lineup_signal.get("details") or {}
        own_details = own_team_lineup_signal.get("details") or {}
        opponent_details = opponent_lineup_signal.get("details") or {}
        player_is_projected_starter = player_details.get("player_is_projected_starter")
        source_disagreement = bool(player_details.get("source_disagreement"))
        freshness_risk = bool(player_details.get("freshness_risk")) or bool(getattr(lineup_context, "freshness_risk", False))

        if not lineup_context and not player_details and not own_details and not opponent_details:
            return self._build_section(
                "lineup",
                "unavailable",
                "Lineup context is unavailable.",
                reliability=self._average_reliability(player_lineup_signal.get("reliability")),
            )

        tone = "neutral"
        if player_is_projected_starter is True and not source_disagreement and not freshness_risk:
            tone = "support"
        elif player_is_projected_starter is False or source_disagreement or freshness_risk:
            tone = "caution"

        signal_note = (
            lineup_context.summary
            if lineup_context and lineup_context.summary
            else "Lineup context is available but incomplete."
        )
        risk_note = None
        if player_is_projected_starter is False:
            risk_note = "Player is outside the projected starting five."
        elif source_disagreement:
            risk_note = "Free lineup sources still disagree on the projected starters."
        elif freshness_risk:
            risk_note = "Lineup snapshot is stale and should be treated as a soft signal."

        player_confidence = getattr(lineup_context.player_team, "confidence", None) if lineup_context and lineup_context.player_team else own_details.get("confidence")
        opponent_confidence = getattr(lineup_context.opponent_team, "confidence", None) if lineup_context and lineup_context.opponent_team else opponent_details.get("confidence")
        status_value = (
            getattr(lineup_context.player_team, "status", None)
            if lineup_context and lineup_context.player_team
            else own_details.get("status")
        )

        return self._build_section(
            "lineup",
            tone,
            signal_note,
            reliability=self._average_reliability(player_lineup_signal.get("reliability"), own_team_lineup_signal.get("reliability")),
            risk_note=risk_note,
            stats=self._collect_stats(
                self._build_stat("Player team", self._format_confidence(player_confidence), self._confidence_stat_tone(player_confidence)),
                self._build_stat("Opponent", self._format_confidence(opponent_confidence), self._confidence_stat_tone(opponent_confidence)),
                self._build_stat(
                    "Status",
                    self._format_lineup_status(status_value, freshness_risk),
                    "caution" if freshness_risk or source_disagreement else "neutral",
                ),
            ),
        )

    def _build_market_section(
        self,
        query_side: str,
        market_ctx: dict[str, Any],
        scorecard: dict[str, Any],
        market_signal: dict[str, Any],
        market_quote_signal: dict[str, Any],
        bookmaker_spread_signal: dict[str, Any],
    ) -> AgentVerdictBreakdownSection:
        pricing_mode = str(market_ctx.get("pricing_mode") or "unavailable")
        ev_pct = scorecard.get("expected_value_pct")
        spread_details = bookmaker_spread_signal.get("details") or {}
        line_spread = spread_details.get("line_spread")

        tone = "unavailable"
        if pricing_mode == "exact_line":
            tone = "neutral"
            if isinstance(ev_pct, (int, float)) and float(ev_pct) >= 0.01:
                tone = "support"
            elif isinstance(ev_pct, (int, float)) and float(ev_pct) < 0:
                tone = "caution"
        elif pricing_mode == "line_moved":
            tone = "caution"

        signal_note = self._format_market_reason(market_ctx, query_side) or "Market context is unavailable."
        risk_note = None
        if pricing_mode == "line_moved":
            risk_note = "Same-line EV is gone until the original line returns."
        elif pricing_mode == "unavailable":
            risk_note = "No same-line quote means this is analysis only, not a priced bet."
        elif isinstance(line_spread, (int, float)) and float(line_spread) > 1:
            risk_note = "Books disagree materially on the current live line."
        elif isinstance(ev_pct, (int, float)) and abs(float(ev_pct)) < 0.03:
            risk_note = "Priced edge is thin even with a same-line quote."

        best_stat = self._build_stat(
            "Best odds",
            self._format_odds(market_ctx.get("best_odds")),
            "positive" if tone == "support" else ("caution" if tone == "caution" else "neutral"),
        )
        if isinstance(line_spread, (int, float)) and float(line_spread) > 0:
            best_stat = self._build_stat("Book spread", self._format_decimal(line_spread), "caution" if float(line_spread) > 1 else "neutral")

        return self._build_section(
            "market",
            tone,
            signal_note,
            reliability=self._average_reliability(market_quote_signal.get("reliability"), market_signal.get("reliability")),
            risk_note=risk_note,
            stats=self._collect_stats(
                self._build_stat(
                    "Market prob",
                    self._format_probability_or_na(market_ctx.get("query_probability")),
                    self._probability_stat_tone(market_ctx.get("query_probability")),
                ),
                self._build_stat(
                    "Best line",
                    self._format_decimal_or_none(market_ctx.get("best_line")),
                    "neutral",
                ),
                best_stat,
            ),
        )

    def _build_projection_section(self) -> AgentVerdictBreakdownSection:
        return self._build_section(
            "projection",
            "unavailable",
            "Projection input is disabled because the current feed is not trusted for betting decisions.",
            stats=self._collect_stats(
                self._build_stat("Status", "Disabled", "muted"),
            ),
        )

    def _extract_reasons(self, final: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        dimensions = final.get("dimensions") or {}
        for key in ("historical", "trend_role", "market", "schedule", "own_team_injuries"):
            detail = (dimensions.get(key) or {}).get("detail")
            if isinstance(detail, str) and detail.strip():
                reasons.append(detail.strip())
            if len(reasons) == 3:
                break

        if not reasons and final.get("summary"):
            reasons.append(str(final["summary"]).strip())

        return reasons[:3]

    def _format_historical_reason(
        self,
        historical_ctx: dict[str, Any],
        query_side: str,
    ) -> str | None:
        probability = historical_ctx.get("query_probability")
        mean = historical_ctx.get("mean")
        threshold = historical_ctx.get("threshold")
        if probability is None or mean is None or threshold is None or not query_side:
            return None

        return (
            f"Historical data gives {self._format_probability(probability)} to go {query_side}, "
            f"with a mean of {self._format_decimal(mean)} versus a {self._format_decimal(threshold)} line."
        )

    def _format_trend_reason(
        self,
        trend_ctx: dict[str, Any],
        historical_ctx: dict[str, Any],
        query_side: str,
    ) -> str | None:
        recent_average = trend_ctx.get("recent_average")
        threshold = historical_ctx.get("threshold")
        alignment = str(trend_ctx.get("signal_alignment") or "neutral")
        if recent_average is None or threshold is None or not query_side:
            return None

        phrase = {
            "supports_query_side": f"Recent form supports the {query_side}",
            "against_query_side": f"Recent form works against the {query_side}",
        }.get(alignment, f"Recent form is neutral for the {query_side}")

        if abs(float(recent_average) - float(threshold)) < 1e-9:
            line_relation = "in line with"
        elif float(recent_average) > float(threshold):
            line_relation = "above"
        else:
            line_relation = "below"

        return (
            f"{phrase}: last 5 average is {self._format_decimal(recent_average)}, "
            f"{line_relation} the {self._format_decimal(threshold)} line."
        )

    def _format_market_reason(
        self,
        market_ctx: dict[str, Any],
        query_side: str,
    ) -> str | None:
        pricing_mode = str(market_ctx.get("pricing_mode") or "unavailable")
        queried_line = market_ctx.get("queried_line")
        if pricing_mode == "exact_line":
            probability = market_ctx.get("query_probability")
            if probability is None or queried_line is None or not query_side:
                return None
            book = self._format_bookmaker_name(market_ctx.get("best_book"))
            odds = market_ctx.get("best_odds")
            if book and isinstance(odds, int):
                return (
                    f"Market prices the {query_side} at {self._format_probability(probability)} "
                    f"on the {self._format_decimal(queried_line)} line, best price at {book} ({odds:+d})."
                )
            return (
                f"Market prices the {query_side} at {self._format_probability(probability)} "
                f"on the {self._format_decimal(queried_line)} line."
            )

        if pricing_mode == "line_moved":
            best_line = market_ctx.get("best_line")
            if queried_line is None or best_line is None:
                return "The original line is no longer available in the live market."
            return (
                f"The original {self._format_decimal(queried_line)} line is no longer available; "
                f"the closest live line is {self._format_decimal(best_line)}."
            )

        return "No exact same-line market quote is available, so EV is not priced."

    def _format_injury_reason(self, injuries_ctx: dict[str, Any]) -> str | None:
        out_players = [str(player).strip() for player in injuries_ctx.get("out_players") or [] if str(player).strip()]
        questionable_players = [
            str(player).strip()
            for player in injuries_ctx.get("questionable_players") or []
            if str(player).strip()
        ]
        if questionable_players:
            names = ", ".join(questionable_players[:3])
            return f"Injury context is still moving: questionable teammates {names} may change the role context."
        if out_players:
            names = ", ".join(out_players[:3])
            return f"Own-team injuries matter here: teammates out include {names}."
        return None

    def _format_schedule_reason(self, schedule_ctx: dict[str, Any], query_side: str) -> str | None:
        is_back_to_back = schedule_ctx.get("is_back_to_back")
        if is_back_to_back is None or not query_side:
            return None
        if bool(is_back_to_back):
            if query_side == "under":
                return "Schedule supports the under: this is a back-to-back."
            return "Schedule works against the over: this is a back-to-back."
        return "Schedule is neutral: this is not a back-to-back."

    def _safe_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _average_reliability(self, *values: Any) -> float | None:
        candidates: list[float] = []
        for value in values:
            if isinstance(value, (int, float)):
                candidates.append(max(0.0, min(float(value), 1.0)))
        if not candidates:
            return None
        return round(sum(candidates) / len(candidates), 3)

    def _collect_stats(
        self,
        *stats: AgentVerdictEvidenceStat | None,
    ) -> list[AgentVerdictEvidenceStat]:
        return [stat for stat in stats if stat is not None]

    def _tone_from_probability(self, probability: Any) -> str:
        if not isinstance(probability, (int, float)):
            return "unavailable"
        if float(probability) >= 0.55:
            return "support"
        if float(probability) <= 0.45:
            return "caution"
        return "neutral"

    def _probability_stat_tone(self, probability: Any) -> str:
        if not isinstance(probability, (int, float)):
            return "muted"
        if float(probability) >= 0.55:
            return "positive"
        if float(probability) <= 0.45:
            return "caution"
        return "neutral"

    def _line_alignment_stat_tone(self, query_side: str, value: Any, threshold: Any) -> str:
        if not isinstance(value, (int, float)) or not isinstance(threshold, (int, float)):
            return "muted"
        if query_side == "under":
            return "positive" if float(value) < float(threshold) else "caution"
        return "positive" if float(value) > float(threshold) else "caution"

    def _sample_stat_tone(self, sample_size: int | None) -> str:
        if sample_size is None:
            return "muted"
        if sample_size >= 20:
            return "positive"
        if sample_size < 10:
            return "caution"
        return "neutral"

    def _delta_tone(self, value: Any) -> str:
        if not isinstance(value, (int, float)):
            return "muted"
        if float(value) > 0:
            return "positive"
        if float(value) < 0:
            return "caution"
        return "neutral"

    def _impact_shift_tone(self, query_side: str, shift: float) -> str:
        if shift == 0:
            return "neutral"
        if (shift > 0 and query_side == "over") or (shift < 0 and query_side == "under"):
            return "positive"
        return "caution"

    def _confidence_stat_tone(self, confidence: Any) -> str:
        normalized = str(confidence or "").lower()
        if normalized == "high":
            return "positive"
        if normalized == "low":
            return "caution"
        if normalized == "medium":
            return "neutral"
        return "muted"

    def _format_percent(self, value: Any) -> str | None:
        if not isinstance(value, (int, float)):
            return None
        return f"{float(value) * 100:.1f}%"

    def _format_probability_or_na(self, value: Any) -> str:
        formatted = self._format_percent(value)
        return formatted or "N/A"

    def _format_decimal_or_none(self, value: Any) -> str | None:
        if not isinstance(value, (int, float)):
            return None
        return self._format_decimal(value)

    def _format_probability(self, value: Any) -> str:
        return f"{float(value) * 100:.1f}%"

    def _format_decimal(self, value: Any) -> str:
        return f"{float(value):.2f}"

    def _format_signed_decimal(self, value: Any, digits: int = 2) -> str | None:
        if not isinstance(value, (int, float)):
            return None
        sign = "+" if float(value) > 0 else ""
        return f"{sign}{float(value):.{digits}f}"

    def _format_sample(self, sample_size: int | None) -> str | None:
        if sample_size is None:
            return None
        return f"{sample_size} games"

    def _format_weight_or_sample(self, role_weight: Any, role_sample_size: int | None) -> str | None:
        if isinstance(role_weight, (int, float)) and float(role_weight) > 0:
            return f"{float(role_weight) * 100:.0f}%"
        if role_sample_size is not None:
            return f"{role_sample_size} games"
        return None

    def _format_days_rest(self, days_rest: Any) -> str | None:
        if not isinstance(days_rest, (int, float)):
            return None
        numeric = int(days_rest)
        return f"{numeric} day{'s' if numeric != 1 else ''}"

    def _format_confidence(self, confidence: Any) -> str | None:
        normalized = str(confidence or "").strip().lower()
        if not normalized:
            return None
        return normalized.capitalize()

    def _format_lineup_status(self, status: Any, freshness_risk: bool) -> str | None:
        normalized = str(status or "").strip().lower()
        if not normalized and not freshness_risk:
            return None
        status_label = normalized.replace("_", " ").capitalize() if normalized else "Unknown"
        if freshness_risk:
            return f"{status_label} / stale"
        return status_label

    def _format_top_impact(self, top_impact: dict[str, Any] | None, shift: float) -> str | None:
        if top_impact is None:
            return "No clear swing"
        name = str(top_impact.get("star") or "").strip() or "Teammate"
        formatted_shift = self._format_signed_decimal(shift)
        if not formatted_shift:
            return f"Without {name}"
        return f"{formatted_shift} without {name}"

    def _format_odds(self, odds: Any) -> str | None:
        if not isinstance(odds, int):
            return None
        return f"{odds:+d}"

    def _format_bookmaker_name(self, book: Any) -> str | None:
        if not book:
            return None
        key = str(book).strip().lower()
        if not key:
            return None
        if key in _BOOKMAKER_LABELS:
            return _BOOKMAKER_LABELS[key]
        return " ".join(part.capitalize() for part in key.replace("-", "_").split("_"))

    def _format_subject(self, pick: AgentPickContext | None) -> str:
        if pick is None:
            return "Current board"
        return f"{pick.player_name} {pick.metric} {pick.direction} {pick.threshold}"

    def _derive_status(self, result: dict[str, Any]) -> AgentStatus:
        flags = result.get("scorecard", {}).get("data_quality_flags") or []
        if "line_moved" in flags:
            return "line_moved"
        if "no_market_data" in flags:
            return "not_enough_market_data"
        if "unresolved_teammate_injury" in flags or any(
            str(flag).startswith("teammates_questionable") for flag in flags
        ):
            return "injury_context_missing"
        return "ok"

    def _build_reply(self, status: AgentStatus, summary: str) -> str:
        if status == "line_moved":
            return (
                "Market is still available, but the live line has moved from this pick. "
                f"{summary}"
            ).strip()
        if status == "not_enough_market_data":
            return f"Not enough current market data yet. {summary}".strip()
        if status == "injury_context_missing":
            return f"Injury context is still moving. {summary}".strip()
        return summary

    def _log_market_pricing(
        self,
        pick: AgentPickContext | None,
        verdict: AgentVerdictCard,
    ) -> None:
        logger.info(
            "agent_market_pricing %s",
            json.dumps(
                {
                    "event_id": pick.event_id if pick else "",
                    "pricing_mode": verdict.market_pricing_mode,
                    "queried_line": verdict.queried_line,
                    "available_lines": verdict.available_lines,
                },
                sort_keys=True,
            ),
        )

    def _classify_recommendation(
        self,
        pick_direction: str,
        decision: str,
        eligible_for_bet: bool,
    ) -> str:
        if decision == pick_direction and eligible_for_bet:
            return "keep"
        if decision == "avoid" or not eligible_for_bet:
            return "recheck"
        return "remove"

    def _default_quick_actions(self) -> list[AgentQuickAction]:
        return [
            AgentQuickAction(
                action="analyze_pick",
                label="Should I bet this?",
                prompt="Should I bet this?",
            ),
            AgentQuickAction(
                action="risk_check",
                label="Biggest risk",
                prompt="What is the biggest risk?",
            ),
            AgentQuickAction(
                action="review_slip",
                label="Compare with my slip",
                prompt="Compare with my slip",
            ),
            AgentQuickAction(
                action="line_movement",
                label="Line movement",
                prompt="Summarize line movement",
            ),
            AgentQuickAction(
                action="plain_english",
                label="Plain English",
                prompt="Explain in plain English",
            ),
        ]

    async def _run_graph_query(self, query: str, event_context: dict[str, Any]) -> dict[str, Any]:
        graph_app = self._get_graph_app()
        initial_state = {
            "messages": [],
            "user_query": query,
            "parsed_query": {},
            "event_context": event_context,
            "availability": {},
            "historical_signals": {},
            "projection_signals": {},
            "market_signals": {},
            "scorecard": {},
            "data_quality_flags": [],
            "critic_notes": [],
            "final_decision": {},
            "audit_log": [],
            "iteration": 0,
        }
        return await graph_app.ainvoke(initial_state)

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_graph_app():
        if str(_AGENTS_DIR) not in sys.path:
            sys.path.insert(0, str(_AGENTS_DIR))
        from graph import compile_graph

        return compile_graph()


agent_chat_service = AgentChatService()
