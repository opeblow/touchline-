"""A2A (Agent-to-Agent) endpoint for Touchline's match analyst.

Any A2A-compatible agent (another team's broadcast agent, a Copilot Studio agent, a
Foundry agent) can discover Touchline via its Agent Card and ask questions about a
live match. Mounted by the API at /a2a; the card is at /a2a/.well-known/agent-card.json.
"""

from __future__ import annotations

import re
from typing import Any

from agent_framework import AgentResponse, BaseAgent, Message

from touchline.config import get_settings

MATCH_RE = re.compile(r"\bmatch[:= ]([a-z0-9-]+)", re.I)


class TouchlineAnalystAgent(BaseAgent):
    """Agent Framework agent wrapping Touchline's verified match Q&A."""

    def __init__(self, manager) -> None:
        super().__init__(
            id="touchline-analyst",
            name="Touchline Analyst",
            description="Answers questions about a live synthetic football match with verified numbers.",
        )
        self._manager = manager

    async def run(self, messages: Any = None, *, stream: bool = False, session: Any = None, **kwargs: Any):
        from touchline.agents.ask import ask

        text = ""
        msgs = messages if isinstance(messages, list) else [messages] if messages is not None else []
        for m in msgs:
            text = m if isinstance(m, str) else getattr(m, "text", "") or text
        match = MATCH_RE.search(text)
        match_id = match.group(1) if match else "demo"
        question = MATCH_RE.sub("", text).strip() or "What is happening in the match?"
        session_obj = await self._manager.get(match_id)
        result = await ask(session_obj, question)
        reply = Message("assistant", [result["answer"]], author_name=self.name)
        response = AgentResponse(
            messages=[reply],
            agent_id=self.id,
            additional_properties={"tools": result["tools"], "verified": result["verified"]},
        )
        if stream:

            async def _one():
                from agent_framework import AgentResponseUpdate

                yield AgentResponseUpdate(contents=reply.contents, role="assistant")

            return _one()
        return response


def build_a2a_app(manager):
    """Starlette app serving the Agent Card and JSON-RPC endpoint."""
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
    from agent_framework.a2a import A2AExecutor
    from starlette.applications import Starlette

    base = get_settings().public_base_url.rstrip("/")
    card = AgentCard(
        name="Touchline Analyst",
        description="Explainable match intelligence: ask about score, xG, pressing, momentum, players. "
        "Prefix with 'match:<id>' to choose a match (default: demo). Numbers are verified.",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(url=f"{base}/a2a/", protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        skills=[
            AgentSkill(
                id="match-qa",
                name="Match Q&A",
                description="Verified answers about a live match",
                tags=["football", "analytics", "explainability"],
                examples=["match:demo Why did the momentum change?", "Who is the fastest player?"],
            )
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=A2AExecutor(TouchlineAnalystAgent(manager)),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    return Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")])
