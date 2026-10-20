"""Microsoft Agent Framework workflow for one key moment.

    Memory ──> Explainer ──> Guardian ──(approved)──> Persona/Localizer ──> Publisher
       │           ^            │
       │           └─(rejected)─┘   (one rewrite with Guardian feedback, then a
       │                              verified template — never an unchecked text)
       └──> Narrator ──> Guardian ──(approved)──> Publisher

Agents share state through the Match Blackboard and hand off typed messages
along the edges. A fresh workflow instance is built per moment, so moments are
processed concurrently without sharing mutable workflow state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler, response_handler

from touchline.agents.context import MomentContext
from touchline.agents.specialists import Explainer, Guardian, MemoryAgent, Narrator, Persona, Sub
from touchline.models import CommentaryLine, Insight, PersonalizedInsight, Verdict

MAX_ATTEMPTS = 2


# ----------------------------------------------------------------------------- messages


@dataclass
class MomentJob:
    ctx: MomentContext
    outcome: str | None
    subs: list[Sub]
    langs: list[str]


@dataclass
class Draft:
    job: MomentJob
    insight: Insight
    attempt: int


@dataclass
class Verified:
    job: MomentJob
    insight: Insight


@dataclass
class Rejected:
    job: MomentJob
    insight: Insight
    verdict: Verdict
    attempt: int


@dataclass
class NarrationDraft:
    job: MomentJob
    lines: list[CommentaryLine]


@dataclass
class VerifiedNarration:
    job: MomentJob
    lines: list[CommentaryLine]


@dataclass
class Bundle:
    job: MomentJob
    insight: Insight
    variants: list[PersonalizedInsight] = field(default_factory=list)


@dataclass
class ReviewPolicy:
    """Human-in-the-loop: moments at or above `min_importance` wait for a producer's approval."""

    enabled: bool = False
    min_importance: int = 90


@dataclass
class ReviewRequest:
    bundle: Bundle
    reason: str


@dataclass
class ReviewDecision:
    approved: bool
    editor: str = "producer"
    edited_text: str | None = None


@dataclass
class Agents:
    memory: MemoryAgent
    explainer: Explainer
    narrator: Narrator
    guardian: Guardian
    persona: Persona
    review: ReviewPolicy = field(default_factory=ReviewPolicy)


Publish = Callable[[Bundle | VerifiedNarration], Awaitable[None]]


# ----------------------------------------------------------------------------- executors


class MemoryExecutor(Executor):
    def __init__(self, agents: Agents) -> None:
        super().__init__(id="memory")
        self.agents = agents

    @handler
    async def recall(self, job: MomentJob, ctx: WorkflowContext[MomentJob]) -> None:
        job.ctx.memory = await self.agents.memory.run(job.ctx)
        await ctx.send_message(job)


class ExplainerExecutor(Executor):
    def __init__(self, agents: Agents) -> None:
        super().__init__(id="explainer")
        self.agents = agents

    @handler
    async def explain(self, job: MomentJob, ctx: WorkflowContext[Draft]) -> None:
        insight = await self.agents.explainer.run(job.ctx, job.outcome, attempt=1)
        await ctx.send_message(Draft(job, insight, 1))

    @handler
    async def rewrite(self, rejected: Rejected, ctx: WorkflowContext[Draft]) -> None:
        attempt = rejected.attempt + 1
        force_template = rejected.attempt >= MAX_ATTEMPTS
        insight = await self.agents.explainer.run(
            rejected.job.ctx,
            rejected.job.outcome,
            attempt=attempt,
            feedback=rejected.verdict.reasons,
            force_template=force_template,
        )
        await ctx.send_message(Draft(rejected.job, insight, attempt))


class NarratorExecutor(Executor):
    def __init__(self, agents: Agents) -> None:
        super().__init__(id="narrator")
        self.agents = agents

    @handler
    async def narrate(self, job: MomentJob, ctx: WorkflowContext[NarrationDraft]) -> None:
        lines = await self.agents.narrator.run(job.ctx, job.outcome, job.langs)
        await ctx.send_message(NarrationDraft(job, lines))


class GuardianExecutor(Executor):
    def __init__(self, agents: Agents) -> None:
        super().__init__(id="guardian")
        self.agents = agents

    @handler
    async def check_insight(self, draft: Draft, ctx: WorkflowContext[Verified | Rejected]) -> None:
        m = draft.job.ctx.moment
        verdict = await self.agents.guardian.check(
            draft.insight.text,
            draft.insight.cited_fact_ids,
            minute=m.minute,
            template=draft.insight.model == "offline-template",
            surface="insight",
            ref=draft.insight.insight_id,
            handoff_ok="persona",
            handoff_reject="explainer",
        )
        if verdict.approved:
            await ctx.send_message(Verified(draft.job, draft.insight))
        elif draft.attempt > MAX_ATTEMPTS:
            # Even the template failed (should not happen): publish nothing rather than an unverified text.
            return
        else:
            await ctx.send_message(Rejected(draft.job, draft.insight, verdict, draft.attempt))

    @handler
    async def check_narration(self, draft: NarrationDraft, ctx: WorkflowContext[VerifiedNarration]) -> None:
        m = draft.job.ctx.moment
        approved: list[CommentaryLine] = []
        for i, line in enumerate(draft.lines):
            cited = line.__dict__.get("_cited") or [f.fact_id for f in draft.job.ctx.facts]
            v = await self.agents.guardian.check(
                line.text,
                cited,
                minute=m.minute,
                template="_cited" not in line.__dict__,
                surface=f"commentary {line.lang}",
                ref=line.line_id,
                handoff_ok="publisher",
                trace=i == 0,
                max_chars=220,
            )
            if v.approved:
                approved.append(line)
        if approved:
            await ctx.send_message(VerifiedNarration(draft.job, approved))


class PersonaExecutor(Executor):
    def __init__(self, agents: Agents) -> None:
        super().__init__(id="persona")
        self.agents = agents

    @handler
    async def personalise(self, verified: Verified, ctx: WorkflowContext[Bundle]) -> None:
        job = verified.job
        variants = await self.agents.persona.run(job.ctx, verified.insight, job.subs, job.outcome)
        await ctx.send_message(Bundle(job, verified.insight, variants))


class PublisherExecutor(Executor):
    def __init__(self, publish: Publish, agents: Agents) -> None:
        super().__init__(id="publisher")
        self.publish = publish
        self.agents = agents

    @handler
    async def publish_bundle(self, bundle: Bundle, ctx: WorkflowContext[None, str]) -> None:
        m = bundle.job.ctx.moment
        policy = self.agents.review
        if policy.enabled and m.importance >= policy.min_importance:
            # Pause this workflow until a human producer approves, edits or rejects it.
            await ctx.request_info(
                ReviewRequest(bundle, f"importance {m.importance} ≥ {policy.min_importance}"),
                ReviewDecision,
                request_id=bundle.insight.insight_id,
            )
            return
        await self.publish(bundle)
        await ctx.yield_output(f"insight:{bundle.insight.insight_id}")

    @response_handler
    async def on_review(
        self, original: ReviewRequest, decision: ReviewDecision, ctx: WorkflowContext[None, str]
    ) -> None:
        bundle = original.bundle
        m = bundle.job.ctx.moment
        if not decision.approved:
            await ctx.yield_output(f"rejected:{bundle.insight.insight_id}")
            return
        if decision.edited_text and decision.edited_text.strip() != bundle.insight.text:
            # Human edits are verified by the same Guardian as model output.
            verdict = await self.agents.guardian.check(
                decision.edited_text,
                bundle.insight.cited_fact_ids,
                minute=m.minute,
                template=False,
                surface=f"human edit ({decision.editor})",
                ref=bundle.insight.insight_id,
                handoff_ok="publisher",
            )
            if not verdict.approved:
                await ctx.yield_output(
                    f"edit-rejected:{bundle.insight.insight_id}:{'; '.join(verdict.reasons)}"
                )
                return
            bundle.insight.text = decision.edited_text.strip()
            bundle.insight.agent = f"explainer + {decision.editor}"
            for v in bundle.variants:
                if v.mode == "analyst" and v.lang == "en":
                    v.text = bundle.insight.text
        await self.publish(bundle)
        await ctx.yield_output(f"insight:{bundle.insight.insight_id}")

    @handler
    async def publish_narration(self, narration: VerifiedNarration, ctx: WorkflowContext[None, str]) -> None:
        await self.publish(narration)
        await ctx.yield_output(f"commentary:{narration.job.ctx.moment.moment_id}")


# ----------------------------------------------------------------------------- graph


def build_moment_workflow(agents: Agents, publish: Publish):
    memory = MemoryExecutor(agents)
    explainer = ExplainerExecutor(agents)
    narrator = NarratorExecutor(agents)
    guardian = GuardianExecutor(agents)
    persona = PersonaExecutor(agents)
    publisher = PublisherExecutor(publish, agents)
    return (
        WorkflowBuilder(
            name="touchline-moment",
            description="Explain, verify, personalise and publish one moment",
            start_executor=memory,
        )
        .add_fan_out_edges(memory, [explainer, narrator])
        .add_edge(explainer, guardian)
        .add_edge(narrator, guardian)
        .add_edge(guardian, persona, condition=lambda m: isinstance(m, Verified))
        .add_edge(guardian, explainer, condition=lambda m: isinstance(m, Rejected))
        .add_edge(guardian, publisher, condition=lambda m: isinstance(m, VerifiedNarration))
        .add_edge(persona, publisher)
        .build()
    )


GRAPH = {
    "nodes": [
        {"id": "memory", "label": "Memory", "role": "Season context from Azure AI Search"},
        {"id": "explainer", "label": "Explainer", "role": "Why it matters, cites facts"},
        {"id": "narrator", "label": "Narrator", "role": "Live commentary lines"},
        {"id": "guardian", "label": "Guardian", "role": "Fact-check, names, safety"},
        {"id": "persona", "label": "Persona + Localizer", "role": "4 modes × any language"},
        {"id": "publisher", "label": "Publisher", "role": "Blackboard + Web PubSub"},
        {"id": "tactician", "label": "Tactician", "role": "15-minute tactical windows"},
        {"id": "producer", "label": "Producer", "role": "Half-time and full-time recaps"},
        {"id": "spotter", "label": "Moment Spotter", "role": "Scores events 0-100"},
    ],
    "edges": [
        ["spotter", "memory"],
        ["memory", "explainer"],
        ["memory", "narrator"],
        ["explainer", "guardian"],
        ["narrator", "guardian"],
        ["guardian", "persona"],
        ["guardian", "explainer"],
        ["guardian", "publisher"],
        ["persona", "publisher"],
        ["tactician", "publisher"],
        ["producer", "guardian"],
    ],
}
