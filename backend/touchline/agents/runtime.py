"""Agent runtime: reliability policies, fault injection and tracing.

Every agent call goes through `AgentRuntime.call()`, which applies:
  * a timeout per call,
  * a circuit breaker per agent (3 consecutive failures → open for 30 s → fallback),
  * deliberate fault injection for the live "chaos" demo (kill an agent, or make
    the Explainer state a wrong number so the Guardian can catch it),
and records an `AgentTrace` for the Control Room, the audit log and OpenTelemetry.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from touchline.agents.blackboard import Blackboard
from touchline.agents.llm import LLM, LLMResult
from touchline.models import AgentTrace, WireMessage

log = logging.getLogger(__name__)
T = TypeVar("T")

try:  # OpenTelemetry is optional; App Insights is wired in touchline.telemetry
    from opentelemetry import trace as otel_trace

    _tracer = otel_trace.get_tracer("touchline.agents")
except Exception:  # pragma: no cover
    _tracer = None


class AgentKilled(RuntimeError):
    """Raised when chaos mode has taken an agent offline."""


@dataclass
class CircuitBreaker:
    threshold: int = 3
    cooldown_s: float = 30.0
    failures: int = 0
    open_until: float = 0.0

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self.open_until

    def success(self) -> None:
        self.failures = 0

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.open_until = time.monotonic() + self.cooldown_s
            self.failures = 0


@dataclass
class Faults:
    killed_until: dict[str, float] = field(default_factory=dict)
    corrupt_next: set[str] = field(default_factory=set)

    def kill(self, agent: str, seconds: float = 45.0) -> None:
        self.killed_until[agent] = time.monotonic() + seconds

    def revive(self, agent: str) -> None:
        self.killed_until.pop(agent, None)

    def is_killed(self, agent: str) -> bool:
        return time.monotonic() < self.killed_until.get(agent, 0.0)

    def take_corruption(self, agent: str) -> bool:
        if agent in self.corrupt_next:
            self.corrupt_next.discard(agent)
            return True
        return False


Emit = Callable[[WireMessage], Awaitable[None]]


class AgentRuntime:
    """Shared services for all agents working on one match."""

    def __init__(
        self,
        match_id: str,
        llm: LLM,
        blackboard: Blackboard,
        emit: Emit,
        clock: Callable[[], float],
        timeout_s: float = 12.0,
    ) -> None:
        self.match_id = match_id
        self.llm = llm
        self.blackboard = blackboard
        self.emit = emit
        self.clock = clock  # match clock (seconds of play) for timestamps
        self.timeout_s = timeout_s
        self.breakers: dict[str, CircuitBreaker] = {}
        self.faults = Faults()
        self.totals = {
            "calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "rejections": 0,
            "retries": 0,
            "fallbacks": 0,
        }
        self.per_agent: dict[str, dict[str, float]] = {}

    def breaker(self, agent: str) -> CircuitBreaker:
        return self.breakers.setdefault(agent, CircuitBreaker())

    def agent_status(self) -> dict[str, dict[str, Any]]:
        out = {}
        for name, stats in self.per_agent.items():
            b = self.breaker(name)
            out[name] = {
                **stats,
                "circuit": "open" if b.is_open else "closed",
                "killed": self.faults.is_killed(name),
            }
        return out

    async def trace(
        self,
        agent: str,
        action: str,
        status: str,
        started: float,
        *,
        result: LLMResult | None = None,
        detail: str = "",
        input_ref: str | None = None,
        output_ref: str | None = None,
        handoff_to: str | None = None,
    ) -> AgentTrace:
        latency = (time.perf_counter() - started) * 1000
        tr = AgentTrace(
            trace_id=uuid.uuid4().hex[:12],
            match_id=self.match_id,
            agent=agent,
            action=action,
            status=status,  # type: ignore[arg-type]
            started_at=round(self.clock(), 2),
            latency_ms=round(latency if result is None else max(latency, result.latency_ms), 1),
            input_ref=input_ref,
            output_ref=output_ref,
            tokens_in=result.tokens_in if result else 0,
            tokens_out=result.tokens_out if result else 0,
            cost_usd=round(result.cost_usd, 6) if result else 0.0,
            model=result.model if result else ("offline-template" if not self.llm.online else "rules"),
            detail=detail[:300],
            handoff_to=handoff_to,
        )
        self.totals["calls"] += 1
        self.totals["tokens_in"] += tr.tokens_in
        self.totals["tokens_out"] += tr.tokens_out
        self.totals["cost_usd"] += tr.cost_usd
        if status == "rejected":
            self.totals["rejections"] += 1
        if status == "retry":
            self.totals["retries"] += 1
        if status == "fallback":
            self.totals["fallbacks"] += 1
        a = self.per_agent.setdefault(
            agent, {"calls": 0, "errors": 0, "latency_ms_total": 0.0, "tokens": 0, "cost_usd": 0.0}
        )
        a["calls"] += 1
        a["latency_ms_total"] += tr.latency_ms
        a["tokens"] += tr.tokens_in + tr.tokens_out
        a["cost_usd"] += tr.cost_usd
        if status in {"error", "fallback"}:
            a["errors"] += 1
        await self.blackboard.put("trace", tr.trace_id, tr)
        await self.emit(
            WireMessage(
                kind="trace", match_id=self.match_id, t=tr.started_at, data=tr.model_dump(mode="json")
            )
        )
        if _tracer is not None:
            with _tracer.start_as_current_span(f"agent.{agent}.{action}") as span:
                span.set_attribute("agent.name", agent)
                span.set_attribute("agent.status", status)
                span.set_attribute("match.id", self.match_id)
                span.set_attribute("gen_ai.usage.input_tokens", tr.tokens_in)
                span.set_attribute("gen_ai.usage.output_tokens", tr.tokens_out)
                span.set_attribute("touchline.latency_ms", tr.latency_ms)
        return tr

    async def guarded(
        self,
        agent: str,
        fn: Callable[[], Awaitable[T]],
        fallback: Callable[[], T] | None,
        timeout_s: float | None = None,
    ) -> tuple[T, str, str]:
        """Run `fn` with kill-switch, circuit breaker and timeout.

        Returns (value, status, detail) where status is ok | fallback.
        """
        breaker = self.breaker(agent)
        if self.faults.is_killed(agent):
            if fallback is None:
                raise AgentKilled(agent)
            breaker.failure()
            return fallback(), "fallback", "agent offline (chaos test) → template fallback"
        if breaker.is_open:
            if fallback is None:
                raise AgentKilled(agent)
            return fallback(), "fallback", "circuit open → template fallback"
        try:
            value = await asyncio.wait_for(fn(), timeout=timeout_s or self.timeout_s)
            breaker.success()
            return value, "ok", ""
        except Exception as exc:
            breaker.failure()
            if fallback is None:
                raise
            reason = "timeout" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__
            log.info("%s failed (%s); using fallback", agent, reason)
            return fallback(), "fallback", f"{reason} → template fallback"
