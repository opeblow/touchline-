"""Enterprise and Foundry controls: spend cap, operator key, rate limits, Foundry evaluator, Functions app."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from touchline.agents.blackboard import Blackboard
from touchline.agents.llm import LLM
from touchline.agents.runtime import AgentRuntime
from touchline.config import Settings


def _rt(budget: float) -> AgentRuntime:
    async def emit(msg):
        return None

    return AgentRuntime(
        "t",
        LLM(Settings(llm_provider="offline")),
        Blackboard("t"),
        emit,
        clock=lambda: 0.0,
        budget_usd=budget,
    )


def test_spend_cap_switches_agents_to_verified_templates():
    rt = _rt(budget=0.01)
    rt.totals["cost_usd"] = 0.02

    async def call():
        raise AssertionError("model must not be called once over budget")

    value, status, detail = asyncio.run(rt.guarded("explainer", call, lambda: "template"))
    assert value == "template" and status == "fallback" and "budget" in detail


def test_operator_key_protects_control_actions(monkeypatch):
    from touchline.api import main

    monkeypatch.setattr(main.settings, "control_api_key", "s3cret")
    with TestClient(main.app) as c:
        assert c.post("/api/matches/demo/pause").status_code == 401
        assert c.post("/api/matches/demo/chaos", json={"action": "corrupt"}).status_code == 401
        ok = c.post(
            "/api/matches/demo/review-policy", json={"enabled": False}, headers={"x-touchline-key": "s3cret"}
        )
        assert ok.status_code == 200
        assert c.get("/api/health").json()["operator_key_required"] is True


def test_ask_is_rate_limited(monkeypatch):
    from touchline.api import main

    monkeypatch.setattr(main.settings, "ask_rate_per_minute", 2)
    main._ask_hits.clear()
    with TestClient(main.app) as c:
        codes = [
            c.post("/api/matches/demo/ask", json={"question": "Who is fastest?"}).status_code
            for _ in range(3)
        ]
    assert codes[:2] == [200, 200] and codes[2] == 429


def test_guardian_as_foundry_evaluator():
    from agent_framework import AgentResponse, LocalEvaluator, Message, evaluate_agent

    from touchline.foundry_ops import _queries, numeric_grounding

    q = _queries("demo", 1)[0]
    fact = json.loads(q)["facts"][0]
    good = AgentResponse(
        messages=[Message("assistant", [json.dumps({"text": f"Key number: {fact['display']}."})])]
    )
    bad = AgentResponse(messages=[Message("assistant", [json.dumps({"text": "Key number: 987 km/h."})])])

    class Agent:
        id = name = "a"
        description = ""

        async def run(self, *a, **k):
            return good

        def create_session(self, **k):
            return None

    res = asyncio.run(
        evaluate_agent(
            agent=Agent(), queries=[q, q], responses=[good, bad], evaluators=LocalEvaluator(numeric_grounding)
        )
    )
    assert res[0].passed == 1 and res[0].failed == 1


@pytest.mark.skipif(
    importlib.util.find_spec("azure.functions") is None, reason="azure-functions not installed"
)
def test_functions_app_bindings():
    path = Path(__file__).resolve().parents[2] / "functions" / "function_app.py"
    spec = importlib.util.spec_from_file_location("function_app", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fns = {f.get_function_name(): {b.type for b in f.get_bindings()} for f in mod.app.get_functions()}
    assert fns["archive_events"] == {"eventHubTrigger", "cosmosDB"}
    assert "timerTrigger" in fns["nightly_season"]
    assert "httpTrigger" in fns["health"]
