"""End-to-end Agent Framework workflow, including the online path with a scripted model."""

import json

import pytest

from touchline.agents.blackboard import Blackboard
from touchline.agents.context import build_context
from touchline.agents.guardian_rules import NameIndex
from touchline.agents.llm import LLM, LLMResult
from touchline.agents.runtime import AgentRuntime
from touchline.agents.specialists import Explainer, Guardian, MemoryAgent, Narrator, Persona, Sub
from touchline.agents.workflow import Agents, Bundle, MomentJob, build_moment_workflow
from touchline.azure_services import ContentSafety, SearchMemory, Translator
from touchline.config import Settings
from touchline.intel.moments import MomentDetector
from touchline.stats.engine import StatsEngine


class ScriptedLLM(LLM):
    """Online-looking LLM: the Explainer's first draft invents a number; the rewrite is grounded."""

    def __init__(self):
        super().__init__(Settings(llm_provider="offline"))
        self.provider = "scripted"
        self.calls: list[str] = []

    async def complete(self, *, agent, instructions, prompt, tier="fast", **_):
        self.calls.append(agent)
        data = json.loads(prompt)
        facts = data["facts"]
        first = facts[0]
        if agent == "explainer":
            if data.get("guardian_feedback"):
                text = f"That matters: {first['label']} was {first['display']}."
            else:
                text = f"That matters: {first['label']} was 999."  # hallucinated
            body = {"text": text, "cited_fact_ids": [first["id"]]}
        elif agent == "narrator":
            body = {"text": f"{data['minute']}' What a moment!", "tone": "excited", "cited_fact_ids": []}
        else:  # persona
            body = {
                "headline": "Big moment",
                "text": f"{first['display']} says it all.",
                "cited_fact_ids": [first["id"]],
            }
        return LLMResult(
            text=json.dumps(body), model="scripted", tokens_in=100, tokens_out=40, cost_usd=0.0001
        )


async def _run_first_goal(match, llm):
    stats = StatsEngine(match.meta)
    md = MomentDetector(stats, match.meta.match_id)
    for e in match.events:
        before = (stats.score["home"], stats.score["away"])
        moments = md.detect(e, stats.ingest(e))
        goal = next((m for m in moments if m.type.value == "goal"), None)
        if goal:
            break
    traces, published = [], []

    async def emit(msg):
        if msg.kind == "trace":
            traces.append(msg.data)

    bb = Blackboard(match.meta.match_id)
    rt = AgentRuntime(match.meta.match_id, llm, bb, emit, clock=lambda: stats.t)
    settings = Settings(llm_provider="offline")
    guardian = Guardian(rt, stats, NameIndex(match.meta), ContentSafety(settings))
    agents = Agents(
        memory=MemoryAgent(rt, stats, SearchMemory(settings)),
        explainer=Explainer(rt),
        narrator=Narrator(rt),
        guardian=guardian,
        persona=Persona(rt, guardian, Translator(settings), stats),
    )

    async def publish(item):
        published.append(item)

    job = MomentJob(
        ctx=build_context(goal, stats, before),
        outcome="goal",
        subs=[Sub("fan", "en"), Sub("analyst", "es"), Sub("club", "ja", "home")],
        langs=["en", "es"],
    )
    result = await build_moment_workflow(agents, publish).run(job)
    return result, traces, published, rt


@pytest.mark.asyncio
async def test_offline_workflow_publishes_verified_variants(comeback):
    result, traces, published, rt = await _run_first_goal(comeback, LLM(Settings(llm_provider="offline")))
    bundles = [p for p in published if isinstance(p, Bundle)]
    assert len(bundles) == 1 and len(bundles[0].variants) == 3
    assert {v.lang for v in bundles[0].variants} == {"en", "es", "ja"}
    agents = {t["agent"] for t in traces}
    assert {"memory", "explainer", "guardian", "persona", "narrator"} <= agents
    assert rt.totals["rejections"] == 0
    assert any(o.startswith("insight:") for o in result.get_outputs())


@pytest.mark.asyncio
async def test_guardian_rejects_hallucination_and_explainer_rewrites(comeback):
    llm = ScriptedLLM()
    result, traces, published, rt = await _run_first_goal(comeback, llm)
    statuses = [(t["agent"], t["status"]) for t in traces]
    assert ("guardian", "rejected") in statuses
    assert ("explainer", "retry") in statuses
    bundle = next(p for p in published if isinstance(p, Bundle))
    assert "999" not in bundle.insight.text and bundle.insight.attempts == 2
    assert rt.totals["tokens_in"] > 0 and llm.calls.count("explainer") == 2


@pytest.mark.asyncio
async def test_killed_agent_falls_back(comeback):
    llm = ScriptedLLM()
    stats_before = None
    _ = stats_before
    # Kill the explainer: output must still be published, via verified template.
    from touchline.agents import runtime as rt_mod

    orig = rt_mod.Faults.is_killed
    rt_mod.Faults.is_killed = lambda self, agent: agent == "explainer"
    try:
        result, traces, published, rt = await _run_first_goal(comeback, llm)
    finally:
        rt_mod.Faults.is_killed = orig
    bundle = next(p for p in published if isinstance(p, Bundle))
    assert bundle.insight.model == "offline-template"
    assert any(t["agent"] == "explainer" and t["status"] == "fallback" for t in traces)


@pytest.mark.asyncio
async def test_human_review_pauses_and_resumes(comeback):
    """Agent Framework request_info: a goal waits for a producer; edits are re-verified by the Guardian."""
    from touchline.agents.workflow import ReviewDecision, ReviewPolicy

    stats = StatsEngine(comeback.meta)
    md = MomentDetector(stats, comeback.meta.match_id)
    goal = before = None
    for e in comeback.events:
        before = (stats.score["home"], stats.score["away"])
        goal = next((m for m in md.detect(e, stats.ingest(e)) if m.type.value == "goal"), None)
        if goal:
            break

    async def emit(msg):
        return None

    settings = Settings(llm_provider="offline")
    rt = AgentRuntime(comeback.meta.match_id, LLM(settings), Blackboard("t"), emit, clock=lambda: stats.t)
    guardian = Guardian(rt, stats, NameIndex(comeback.meta), ContentSafety(settings))
    agents = Agents(
        memory=MemoryAgent(rt, stats, SearchMemory(settings)),
        explainer=Explainer(rt),
        narrator=Narrator(rt),
        guardian=guardian,
        persona=Persona(rt, guardian, Translator(settings), stats),
        review=ReviewPolicy(enabled=True, min_importance=90),
    )
    published = []

    async def publish(item):
        published.append(item)

    def job():
        return MomentJob(
            ctx=build_context(goal, stats, before), outcome="goal", subs=[Sub("fan", "en")], langs=["en"]
        )

    # 1. Paused, nothing published yet.
    wf = build_moment_workflow(agents, publish)
    res = await wf.run(job())
    reqs = res.get_request_info_events()
    assert len(reqs) == 1 and not any(isinstance(p, Bundle) for p in published)
    # 2. A human edit with an invented number is blocked by the Guardian.
    res2 = await wf.run(responses={reqs[0].request_id: ReviewDecision(True, "ed", "A 99 metre screamer.")})
    assert any(str(o).startswith("edit-rejected") for o in res2.get_outputs())
    assert not any(isinstance(p, Bundle) for p in published)
    # 3. A fresh run approved without edits is published.
    wf2 = build_moment_workflow(agents, publish)
    r = (await wf2.run(job())).get_request_info_events()[0]
    res3 = await wf2.run(responses={r.request_id: ReviewDecision(True, "ed")})
    assert any(str(o).startswith("insight:") for o in res3.get_outputs())
    assert any(isinstance(p, Bundle) for p in published)
