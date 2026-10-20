"""Evaluation harness.

1. Synthetic data realism: season-level distributions vs published top-flight norms.
2. Grounding: share of published texts whose every number traces to a cited fact.
3. Single agent vs Touchline (only when a model is configured): one unconstrained
   LLM call per moment versus the Explainer → Guardian → rewrite pipeline, scored
   with the same Guardian rules (numeric accuracy, foreign names), latency and cost.

Writes docs/eval/report.md and docs/eval/results.json.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from typing import Any

from touchline.config import ROOT, get_settings
from touchline.season import SEASON_DIR

REFERENCE = {  # typical top-flight ranges (public analytics norms)
    "goals_per_match": (2.5, 3.0),
    "shots_per_match": (22, 28),
    "xg_per_shot": (0.09, 0.14),
    "home_win_pct": (40, 48),
    "draw_pct": (22, 30),
}


def realism() -> dict[str, Any]:
    p = SEASON_DIR / "matches.jsonl"
    if not p.exists():
        return {"error": "season not generated"}
    ms = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    goals = [sum(m["score"]) for m in ms]
    shots = [sum(m["shots"]) for m in ms]
    xg = sum(sum(m["xg"]) for m in ms)
    res = {
        "matches": len(ms),
        "goals_per_match": round(statistics.mean(goals), 2),
        "shots_per_match": round(statistics.mean(shots), 1),
        "xg_per_shot": round(xg / max(sum(shots), 1), 3),
        "home_win_pct": round(100 * sum(m["score"][0] > m["score"][1] for m in ms) / len(ms), 1),
        "draw_pct": round(100 * sum(m["score"][0] == m["score"][1] for m in ms) / len(ms), 1),
    }
    res["checks"] = {k: (lo <= res[k] <= hi, [lo, hi]) for k, (lo, hi) in REFERENCE.items()}
    return res


def grounding(match_ids: tuple[str, ...] = ("demo", "classic", "chaos")) -> dict[str, Any]:
    from touchline.agents.guardian_rules import TEMPLATE_CONSTANTS, verify_text
    from touchline.agents.templates import LANGS, render_personalized
    from touchline.intel.analysis import analysis_for

    total = ok = 0
    for mid in match_ids:
        a = analysis_for(mid)
        for m in a.moments:
            ctx = a.contexts[m.moment_id]
            for lang in LANGS:
                for mode in ("analyst", "fan", "club", "player"):
                    r = render_personalized(
                        ctx,
                        mode,
                        lang,
                        club="home",
                        focus_player_id=m.player_id,
                        focus_player_name=ctx.player,
                        outcome=a.outcomes[m.moment_id],
                    )
                    v = verify_text(
                        r.text,
                        r.cited,
                        a.stats.facts,
                        names=a.names,
                        extra_numbers=[m.minute, *TEMPLATE_CONSTANTS],
                    )
                    total += 1
                    ok += v.approved
    return {"texts": total, "grounded": ok, "grounded_pct": round(100 * ok / max(total, 1), 2)}


BASELINE_PROMPT = (
    "You are a football commentator. In one to three sentences, explain why this moment matters. "
    "Be specific and use statistics."
)


async def single_vs_multi(match_id: str = "demo", limit: int = 12) -> dict[str, Any]:
    from touchline.agents.guardian_rules import verify_text
    from touchline.agents.llm import LLM
    from touchline.intel.analysis import analysis_for

    llm = LLM(get_settings())
    if not llm.online:
        return {"skipped": "No model configured. Set FOUNDRY_PROJECT_ENDPOINT (or Azure OpenAI) and rerun."}
    from touchline.agents.specialists import PROMPTS

    a = analysis_for(match_id)
    moments = sorted(a.moments, key=lambda m: -m.importance)[:limit]
    base = {"ok": 0, "lat": [], "cost": 0.0}
    multi = {"ok": 0, "lat": [], "cost": 0.0, "rewrites": 0}
    for m in moments:
        ctx = a.contexts[m.moment_id]
        # Baseline: a single agent with the raw event description, no fact ids, no verification.
        t = time.perf_counter()
        r = await llm.complete(
            agent="baseline",
            instructions=BASELINE_PROMPT,
            prompt=json.dumps(
                {
                    "moment": m.title,
                    "minute": m.minute,
                    "team": ctx.team,
                    "player": ctx.player,
                    "score": f"{ctx.score[0]}-{ctx.score[1]}",
                }
            ),
        )
        base["lat"].append((time.perf_counter() - t) * 1000)
        base["cost"] += r.cost_usd
        base["ok"] += verify_text(
            r.text, [f.fact_id for f in ctx.facts], a.stats.facts, names=a.names, extra_numbers=[m.minute]
        ).approved
        # Touchline: Explainer with facts + Guardian + one rewrite.
        t = time.perf_counter()
        feedback = None
        approved = False
        for _attempt in (1, 2):
            payload = {**ctx.prompt_dict(), "guardian_feedback": feedback}
            r = await llm.complete(
                agent="explainer",
                instructions=PROMPTS["explainer"],
                prompt=json.dumps(payload, default=str),
                json_mode=True,
                max_tokens=300,
            )
            multi["cost"] += r.cost_usd
            try:
                d = r.json()
                v = verify_text(
                    d["text"],
                    d.get("cited_fact_ids", []),
                    a.stats.facts,
                    names=a.names,
                    extra_numbers=[m.minute],
                )
            except Exception:
                v = None
            if v is not None and v.approved:
                approved = True
                break
            feedback = v.reasons if v else ["Return valid JSON"]
            multi["rewrites"] += 1
        multi["lat"].append((time.perf_counter() - t) * 1000)
        multi["ok"] += approved
    n = len(moments)

    def summarise(d: dict[str, Any]) -> dict[str, Any]:
        return {
            "numeric_accuracy_pct": round(100 * d["ok"] / n, 1),
            "p50_latency_ms": round(statistics.median(d["lat"])),
            "cost_usd": round(d["cost"], 5),
            **({"rewrites": d["rewrites"]} if "rewrites" in d else {}),
        }

    return {
        "moments": n,
        "model": llm.model_name("fast"),
        "single_agent": summarise(base),
        "touchline": summarise(multi),
    }


def run() -> None:
    out_dir = ROOT / "docs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {
        "realism": realism(),
        "grounding": grounding(),
        "single_vs_multi": asyncio.run(single_vs_multi()),
    }
    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    r, g, s = results["realism"], results["grounding"], results["single_vs_multi"]
    lines = [
        "# Touchline evaluation report",
        "",
        "## 1. Synthetic data realism (380-match season)",
        "",
        "| Metric | Touchline | Reference range | Pass |",
        "|---|---|---|---|",
    ]
    for k, (passed, rng) in r.get("checks", {}).items():
        lines.append(
            f"| {k.replace('_', ' ')} | {r[k]} | {rng[0]}–{rng[1]} | {'PASS' if passed else 'CHECK'} |"
        )
    lines += [
        "",
        "## 2. Grounding of published text",
        "",
        f"{g['grounded']} of {g['texts']} texts ({g['grounded_pct']}%) passed the Guardian: every number traced to a cited fact "
        "(4 viewer modes × 6 languages × every moment of 3 matches).",
        "",
        "## 3. Single agent vs Touchline multi-agent pipeline",
        "",
    ]
    if "skipped" in s:
        lines.append(f"_{s['skipped']}_")
    else:
        lines += [
            f"Model: `{s['model']}`, {s['moments']} highest-importance moments of the demo match.",
            "",
            "| | Numeric accuracy | p50 latency | Cost |",
            "|---|---|---|---|",
            f"| Single agent | {s['single_agent']['numeric_accuracy_pct']}% | {s['single_agent']['p50_latency_ms']} ms | ${s['single_agent']['cost_usd']} |",
            f"| Touchline | {s['touchline']['numeric_accuracy_pct']}% | {s['touchline']['p50_latency_ms']} ms | ${s['touchline']['cost_usd']} |",
            "",
            f"Guardian-triggered rewrites: {s['touchline']['rewrites']}.",
        ]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
