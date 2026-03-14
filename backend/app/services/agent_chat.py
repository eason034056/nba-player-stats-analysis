from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from app.models.agent_chat import (
    AgentAction,
    AgentChatRequest,
    AgentChatResponse,
    AgentPickContext,
    AgentQuickAction,
    AgentSlipReview,
    AgentStatus,
    AgentVerdictCard,
)

GraphRunner = Callable[[str], dict[str, Any]]


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

    def handle_chat(self, request: AgentChatRequest) -> AgentChatResponse:
        thread = request.thread
        quick_actions = self._default_quick_actions()

        if request.action == "review_slip":
            return self._handle_slip_review(request, thread, quick_actions)

        pick = request.context.selected_pick if request.context else None
        message = request.message.strip()

        if request.action != "general" and pick is None:
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

        try:
            result = self._graph_runner(query)
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

        return AgentChatResponse(
            thread=thread,
            action=request.action,
            status=status,
            reply=self._build_reply(status, verdict.summary),
            verdict=verdict,
            quick_actions=quick_actions,
        )

    def _handle_slip_review(
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
                result = self._graph_runner(query)
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
        return AgentVerdictCard(
            subject=self._format_subject(pick),
            decision=final.get("decision", "avoid"),
            confidence=float(final.get("confidence", 0.0) or 0.0),
            model_probability=float(final.get("model_probability", 0.0) or 0.0),
            market_implied_probability=(
                float(final["market_implied_probability"])
                if final.get("market_implied_probability") is not None
                else None
            ),
            expected_value_pct=float(final.get("expected_value_pct", 0.0) or 0.0),
            summary=summary,
            reasons=self._extract_reasons(final),
            risk_factors=list(final.get("risk_factors") or result.get("critic_notes") or []),
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

    def _format_subject(self, pick: AgentPickContext | None) -> str:
        if pick is None:
            return "Current board"
        return f"{pick.player_name} {pick.metric} {pick.direction} {pick.threshold}"

    def _derive_status(self, result: dict[str, Any]) -> AgentStatus:
        flags = result.get("scorecard", {}).get("data_quality_flags") or []
        if "no_market_data" in flags:
            return "not_enough_market_data"
        if "unresolved_teammate_injury" in flags or any(
            str(flag).startswith("teammates_questionable") for flag in flags
        ):
            return "injury_context_missing"
        return "ok"

    def _build_reply(self, status: AgentStatus, summary: str) -> str:
        if status == "not_enough_market_data":
            return f"Not enough current market data yet. {summary}".strip()
        if status == "injury_context_missing":
            return f"Injury context is still moving. {summary}".strip()
        return summary

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

    def _run_graph_query(self, query: str) -> dict[str, Any]:
        graph_app = self._get_graph_app()
        initial_state = {
            "messages": [],
            "user_query": query,
            "parsed_query": {},
            "event_context": {},
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
        return graph_app.invoke(initial_state)

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_graph_app():
        if str(_AGENTS_DIR) not in sys.path:
            sys.path.insert(0, str(_AGENTS_DIR))
        from graph import compile_graph

        return compile_graph()


agent_chat_service = AgentChatService()
