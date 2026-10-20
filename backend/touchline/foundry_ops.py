"""Microsoft Foundry operations: managed agents and evaluations.

1. Agents as managed Foundry assets
   `register` publishes every Touchline prompt (agents/prompts/*.md) as a versioned
   Foundry prompt agent ("touchline-explainer", "touchline-narrator", ...). With
   FOUNDRY_HOSTED_AGENTS=true the runtime calls those Foundry agents through
   Agent Framework's FoundryAgent, so producers can tune an agent's instructions or
   model in the Foundry portal, version it and roll back, without redeploying.

2. Evaluations
   `evaluate` runs the Explainer and a single-agent baseline over the same match
   moments and scores both with Foundry's built-in evaluators (groundedness,
   relevance, coherence, task adherence) plus Touchline's Guardian as a custom local
   evaluator (numeric grounding). Results are visible in the Foundry portal and
   written to docs/eval/foundry.json.

    python -m touchline.foundry_ops register
    python -m touchline.foundry_ops evaluate --match demo --limit 12
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from typing import Any

from agent_framework import evaluator

from touchline.agents.guardian_rules import extract_numbers
from touchline.config import ROOT, get_settings

AGENT_TIERS = {
    "explainer": "fast",
    "narrator": "fast",
    "persona": "fast",
    "scenario": "fast",
    "producer": "reasoning",
    "tactician": "reasoning",
}
BASELINE = (
    "You are a football commentator. In one to three sentences, explain why this moment matters. "
    "Be specific and use statistics."
)


def foundry_agent_name(agent: str) -> str:
    return f"touchline-{agent}"


# ----------------------------------------------------------------------------- custom evaluator


def _allowed_from_query(query: str) -> set[float]:
    """Numbers a response may contain: every fact value in the query, plus the minute."""
    try:
        payload = json.loads(query[query.index("{") :])
    except (ValueError, json.JSONDecodeError):
        return set(extract_numbers(query))
    allowed = {0.0, 1.0, float(payload.get("minute", 0))}
    for f in payload.get("facts", []):
        allowed |= set(extract_numbers(str(f.get("display", ""))))
        allowed |= set(extract_numbers(str(f.get("value", ""))))
    return allowed


def _response_text(response: str) -> str:
    try:
        return str(json.loads(response[response.index("{") : response.rindex("}") + 1]).get("text", response))
    except (ValueError, json.JSONDecodeError):
        return response


@evaluator(name="touchline_numeric_grounding")
def numeric_grounding(query: str, response: str) -> dict[str, Any]:
    """Touchline's Guardian rule as a Foundry-compatible evaluator: every number must come from a fact."""
    allowed = _allowed_from_query(query)
    nums = extract_numbers(_response_text(response))
    bad = [n for n in nums if not any(abs(n - a) <= (0.051 if n < 10 else 0.51) for a in allowed)]
    return {
        "passed": not bad,
        "score": 1.0 if not bad else 0.0,
        "reason": "all numbers grounded" if not bad else f"ungrounded: {bad[:5]}",
    }


# ----------------------------------------------------------------------------- registration


def _project_client():
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    s = get_settings()
    if not s.foundry_project_endpoint:
        raise SystemExit("Set FOUNDRY_PROJECT_ENDPOINT")
    return AIProjectClient(endpoint=s.foundry_project_endpoint, credential=DefaultAzureCredential())


def register() -> list[dict[str, str]]:
    from azure.ai.projects.models import PromptAgentDefinition

    from touchline.agents.specialists import PROMPTS

    s = get_settings()
    client = _project_client()
    out = []
    for agent, tier in AGENT_TIERS.items():
        model = s.foundry_model_fast if tier == "fast" else s.foundry_model_reasoning
        instructions = PROMPTS[agent]
        digest = hashlib.sha256(instructions.encode()).hexdigest()[:12]
        v = client.agents.create_version(
            agent_name=foundry_agent_name(agent),
            definition=PromptAgentDefinition(model=model, instructions=instructions),
            description=f"Touchline {agent} agent ({tier} tier)",
            metadata={"app": "touchline", "prompt_sha": digest, "tier": tier},
        )
        out.append(
            {"agent": foundry_agent_name(agent), "version": str(getattr(v, "version", "?")), "model": model}
        )
        print(f"registered {foundry_agent_name(agent)} v{getattr(v, 'version', '?')} on {model}")
    return out


# ----------------------------------------------------------------------------- evaluation


def _queries(match_id: str, limit: int) -> list[str]:
    from touchline.intel.analysis import analysis_for

    a = analysis_for(match_id)
    top = sorted(a.moments, key=lambda m: -m.importance)[:limit]
    return [json.dumps(a.contexts[m.moment_id].prompt_dict(), ensure_ascii=False, default=str) for m in top]


async def evaluate(match_id: str = "demo", limit: int = 12) -> dict[str, Any]:
    from agent_framework import Agent, LocalEvaluator, evaluate_agent
    from agent_framework.foundry import FoundryChatClient, FoundryEvals
    from azure.identity import DefaultAzureCredential

    from touchline.agents.specialists import PROMPTS

    s = get_settings()
    if not s.foundry_project_endpoint:
        raise SystemExit("Set FOUNDRY_PROJECT_ENDPOINT")
    client = FoundryChatClient(
        project_endpoint=s.foundry_project_endpoint,
        model=s.foundry_model_fast,
        credential=DefaultAzureCredential(),
    )
    queries = _queries(match_id, limit)
    evaluators = [
        LocalEvaluator(numeric_grounding),
        FoundryEvals(
            client=client,
            evaluators=[
                FoundryEvals.GROUNDEDNESS,
                FoundryEvals.RELEVANCE,
                FoundryEvals.COHERENCE,
                FoundryEvals.TASK_ADHERENCE,
            ],
        ),
    ]
    results: dict[str, Any] = {}
    for label, instructions in (
        ("single_agent_baseline", BASELINE),
        ("touchline_explainer", PROMPTS["explainer"]),
    ):
        agent = Agent(client=client, name=label, instructions=instructions)
        runs = await evaluate_agent(
            agent=agent, queries=queries, evaluators=evaluators, eval_name=f"touchline-{label}-{match_id}"
        )
        results[label] = [_summarise(r) for r in runs]
    out = ROOT / "docs" / "eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "foundry.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(json.dumps(results, indent=2, default=str))
    return results


def _summarise(r: Any) -> dict[str, Any]:
    """EvalResults → plain dict (provider, pass counts, per-evaluator scores, Foundry portal link)."""
    keys = (
        "provider",
        "passed",
        "failed",
        "total",
        "all_passed",
        "per_evaluator",
        "result_counts",
        "report_url",
        "eval_id",
        "run_id",
        "status",
    )
    return {k: getattr(r, k, None) for k in keys}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="touchline.foundry_ops")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("register")
    e = sub.add_parser("evaluate")
    e.add_argument("--match", default="demo")
    e.add_argument("--limit", type=int, default=12)
    args = ap.parse_args(argv)
    if args.cmd == "register":
        register()
    else:
        asyncio.run(evaluate(args.match, args.limit))


if __name__ == "__main__":
    main(sys.argv[1:])
