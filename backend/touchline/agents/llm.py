"""LLM access through Microsoft Agent Framework.

* `foundry`       → `FoundryChatClient` on a Microsoft Foundry project (Entra ID auth).
* `azure_openai`  → `OpenAIChatCompletionClient` against an Azure OpenAI endpoint.
* `openai`        → any OpenAI-compatible endpoint.
* `offline`       → no model; agents fall back to deterministic multilingual templates.

Two tiers are exposed: `fast` (explain, narrate, personalise) and `reasoning`
(tactics, recaps). Every call returns token usage so the Control Room can show
cost per agent and per match.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from touchline.config import Settings, get_settings

log = logging.getLogger(__name__)

Tier = Literal["fast", "reasoning"]


@dataclass
class LLMResult:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0

    def json(self) -> Any:
        return parse_json(self.text)


class LLMUnavailable(RuntimeError):
    pass


def parse_json(text: str) -> Any:
    """Tolerant JSON extraction (models sometimes wrap JSON in prose or code fences)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("No JSON object found in model output")


class LLM:
    """Thin facade over Agent Framework chat clients."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = self.settings.resolved_llm_provider
        self._clients: dict[Tier, Any] = {}
        self._agents: dict[tuple[Tier, str], Any] = {}
        if self.provider != "offline":
            try:
                self._build_clients()
            except Exception as exc:  # pragma: no cover - depends on cloud config
                log.warning(
                    "LLM provider %s unavailable (%s); falling back to offline templates", self.provider, exc
                )
                self.provider = "offline"

    @property
    def online(self) -> bool:
        return self.provider != "offline"

    def model_name(self, tier: Tier) -> str:
        if not self.online:
            return "offline-template"
        s = self.settings
        return s.foundry_model_fast if tier == "fast" else s.foundry_model_reasoning

    def _build_clients(self) -> None:
        s = self.settings
        if self.provider == "foundry":
            from agent_framework.foundry import FoundryChatClient
            from azure.identity import DefaultAzureCredential

            cred = DefaultAzureCredential()
            for tier in ("fast", "reasoning"):
                self._clients[tier] = FoundryChatClient(
                    project_endpoint=s.foundry_project_endpoint, model=self.model_name(tier), credential=cred
                )
        else:
            from agent_framework.openai import OpenAIChatCompletionClient

            for tier in ("fast", "reasoning"):
                kwargs: dict[str, Any] = {"model": self.model_name(tier)}
                if self.provider == "azure_openai":
                    kwargs |= {
                        "azure_endpoint": s.azure_openai_endpoint,
                        "api_version": s.azure_openai_api_version,
                    }
                    if s.azure_openai_api_key:
                        kwargs["api_key"] = s.azure_openai_api_key
                    else:
                        from azure.identity import DefaultAzureCredential

                        kwargs["credential"] = DefaultAzureCredential()
                else:
                    kwargs |= {"api_key": s.openai_api_key}
                    if s.openai_base_url:
                        kwargs["base_url"] = s.openai_base_url
                self._clients[tier] = OpenAIChatCompletionClient(**kwargs)

    def _agent(self, tier: Tier, name: str, instructions: str):
        from agent_framework import Agent

        key = (tier, name)
        if key not in self._agents:
            s = self.settings
            from touchline.foundry_ops import AGENT_TIERS, foundry_agent_name

            if self.provider == "foundry" and s.foundry_hosted_agents and name in AGENT_TIERS:
                # Managed in Foundry: instructions and model are versioned in the Foundry project.
                from agent_framework.foundry import FoundryAgent
                from azure.identity import DefaultAzureCredential

                self._agents[key] = FoundryAgent(
                    project_endpoint=s.foundry_project_endpoint,
                    agent_name=foundry_agent_name(name),
                    credential=DefaultAzureCredential(),
                )
            else:
                self._agents[key] = Agent(client=self._clients[tier], name=name, instructions=instructions)
        return self._agents[key]

    @property
    def mode(self) -> str:
        if self.provider == "foundry" and self.settings.foundry_hosted_agents:
            return "foundry-hosted-agents"
        return self.provider

    def _price(self, tier: Tier, tin: int, tout: int) -> float:
        s = self.settings
        if tier == "fast":
            return tin / 1000 * s.price_fast_in + tout / 1000 * s.price_fast_out
        return tin / 1000 * s.price_reasoning_in + tout / 1000 * s.price_reasoning_out

    async def complete(
        self,
        *,
        agent: str,
        instructions: str,
        prompt: str,
        tier: Tier = "fast",
        max_tokens: int = 400,
        temperature: float = 0.5,
        json_mode: bool = False,
    ) -> LLMResult:
        if not self.online:
            raise LLMUnavailable("offline")
        started = time.perf_counter()
        options: dict[str, Any] = {"max_tokens": max_tokens, "temperature": temperature}
        if json_mode:
            options["response_format"] = {"type": "json_object"}
        response = await self._agent(tier, agent, instructions).run(prompt, options=options)
        usage = getattr(response, "usage_details", None)
        tin = (
            int(getattr(usage, "input_token_count", None) or (usage or {}).get("input_token_count", 0) or 0)
            if usage
            else 0
        )
        tout = (
            int(getattr(usage, "output_token_count", None) or (usage or {}).get("output_token_count", 0) or 0)
            if usage
            else 0
        )
        return LLMResult(
            text=response.text or "",
            model=self.model_name(tier),
            tokens_in=tin,
            tokens_out=tout,
            latency_ms=(time.perf_counter() - started) * 1000,
            cost_usd=self._price(tier, tin, tout),
        )
