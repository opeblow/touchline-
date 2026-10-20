"""End-to-end test of the whole product against a fresh server.

Starts the API (which also serves the built web app) on a free port, then exercises every
surface: REST, WebSocket live match with several personalised viewers, overlay cues, agents,
Guardian, chaos tests, human review (Agent Framework request_info), watch party, Ask, A2A,
MCP, auto-eventing, scenario generation and recaps. Writes docs/e2e/report.md.

    cd backend && ../.venv/Scripts/python tests/e2e/run_e2e.py
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[3]
PY = sys.executable
RESULTS: list[tuple[str, str, bool, str]] = []  # (area, check, ok, detail)


def check(area: str, name: str, ok: bool, detail: Any = "") -> bool:
    RESULTS.append((area, name, bool(ok), str(detail)[:220]))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {area} · {name} {('— ' + str(detail)[:160]) if detail != '' else ''}",
        flush=True,
    )
    return bool(ok)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def main() -> int:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PUBLIC_BASE_URL": base, "DEMO_SPEED": "8"}
    server = subprocess.Popen(
        [PY, "-m", "uvicorn", "touchline.api.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT / "backend",
        env=env,
    )
    t_start = time.time()
    try:
        async with httpx.AsyncClient(base_url=base, timeout=120) as c:
            for _ in range(120):
                try:
                    if (await c.get("/api/health")).status_code == 200:
                        break
                except httpx.HTTPError:
                    await asyncio.sleep(0.5)
            await run_all(c, base)
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
    write_report(time.time() - t_start)
    return 0 if all(r[2] for r in RESULTS) else 1


async def run_all(c: httpx.AsyncClient, base: str) -> None:
    # ------------------------------------------------------------ platform
    h = (await c.get("/api/health")).json()
    check("Platform", "health", h.get("ok"), h)
    check("Platform", "synthetic season loaded", h.get("season"), "")
    league = (await c.get("/api/league")).json()
    check("Data innovation", "20 fictional clubs", len(league) == 20, len(league))
    table = (await c.get("/api/season/table?matchday=29")).json()
    check("Data innovation", "season table after matchday 29", len(table) == 20, table[0] if table else "")
    seas = (await c.get("/api/season/matches")).json()
    check("Data innovation", "380-match synthetic season", len(seas) == 380, len(seas))
    for name in ("event", "overlay", "insight", "personalized", "moment", "recap", "trace", "fact"):
        r = await c.get(f"/api/schema/{name}")
        check("Render", f"JSON schema: {name}", r.status_code == 200 and "properties" in r.json())
    for path in ("/", "/live", "/overlay", "/control", "/recap", "/studio"):
        r = await c.get(path)
        check("Web", f"page {path}", r.status_code == 200 and "<html" in r.text.lower(), r.status_code)
    r = await c.get("/models/Soldier.glb")
    check("Web", "3D player model served", r.status_code == 200 and r.content[:4] == b"glTF", len(r.content))

    # ------------------------------------------------------------ offline analysis + clip
    a = (await c.get("/api/matches/demo/analysis")).json()
    check("Ingest", "demo match events", a["events"] > 1200, a["events"])
    check("Ingest", "5 Hz tracking frames", a["frames"] > 25000, a["frames"])
    check("Interpret", "facts registered", a["facts"] > 100, a["facts"])
    check("Interpret", "final score of scripted comeback", a["score"] == [3, 2], a["score"])
    clip = (await c.get("/api/matches/demo/clip?type=goal&index=-1&lang=es")).json()
    check("Personalise", "4 modes for one moment", set(clip["modes"]) == {"analyst", "fan", "club", "player"})
    check(
        "Personalise",
        "modes are genuinely different",
        len({m["text"] for m in clip["modes"].values()}) >= 3,
        [m["text"][:50] for m in clip["modes"].values()],
    )
    check(
        "Explain",
        "Guardian rejects corrupted draft",
        not clip["guardian"]["draft_verdict"]["approved"],
        clip["guardian"]["draft_verdict"]["reasons"],
    )
    check("Explain", "Guardian approves grounded text", clip["guardian"]["final_verdict"]["approved"])

    # ------------------------------------------------------------ data studio
    r = await c.post(
        "/api/matches",
        json={"home": "kmu", "away": "ash", "seed": 99, "prompt": "a comeback with a red card at 60'"},
    )
    gen = r.json()
    check(
        "Data innovation",
        "scenario director builds a match from words",
        r.status_code == 200 and gen["events"] > 1000,
        {k: gen.get(k) for k in ("events", "frames")}
        | {"beats": len(gen.get("scenario", {}).get("beats", []))},
    )
    ae = (await c.get("/api/matches/demo/autoevent?from_minute=62&minutes=2")).json()
    check(
        "Auto-eventing",
        "ball detected from pixels",
        ae["ball_detection_rate"] > 0.85,
        ae["ball_detection_rate"],
    )
    check(
        "Auto-eventing",
        "players detected per frame",
        ae["players_detected_per_frame"] > 15,
        ae["players_detected_per_frame"],
    )
    check(
        "Auto-eventing",
        "passes detected and scored vs truth",
        ae["passes_detected"] > 0 and ae["precision"] > 0,
        {
            k: ae[k]
            for k in ("passes_truth", "passes_detected", "precision", "recall", "median_speed_error_kmh")
        },
    )

    # ------------------------------------------------------------ live match
    await c.post("/api/matches/demo/restart")
    await c.post("/api/matches/demo/review-policy", json={"enabled": True, "min_importance": 95})
    viewers = {
        "fan:es": "mode=fan&lang=es",
        "analyst:en": "mode=analyst&lang=en",
        "player:ja": "mode=player&lang=ja&player_id=nbk-09",
        "club:fr": "mode=club&lang=fr&club=home",
        "fan:ar": "mode=fan&lang=ar",
    }
    got: dict[str, list[dict]] = collections.defaultdict(list)
    stop = asyncio.Event()

    async def viewer(key: str, q: str, party: tuple[str, str] | None = None) -> None:
        ws_url = (
            base.replace("http", "ws")
            + f"/ws/matches/demo?{q}&frames={'true' if key == 'fan:es' else 'false'}"
        )
        async with websockets.connect(ws_url, max_size=2**22) as ws:
            if party:
                await ws.send(
                    json.dumps({"type": "join", "name": party[0], "provider": "guest", "member_id": party[0]})
                )
                await asyncio.sleep(0.3)
                await ws.send(json.dumps({"type": "predict", "pick": party[1]}))
                await ws.send(json.dumps({"type": "chat", "text": f"{party[0]} is here"}))
                await ws.send(json.dumps({"type": "react", "emoji": "🔥"}))
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1)
                except TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    return
                got[key].append(json.loads(raw))

    tasks = [
        asyncio.create_task(
            viewer(
                k, q, ("Ada", "away") if k == "fan:es" else ("Bayo", "home") if k == "analyst:en" else None
            )
        )
        for k, q in viewers.items()
    ]
    await asyncio.sleep(1.5)
    await c.post("/api/matches/demo/start", json={"speed": 45})
    t0 = time.time()
    chaos_done = review_done = False
    reviewed = None
    while time.time() - t0 < 600:
        st = (await c.get("/api/matches/demo")).json()["status"]
        if not chaos_done and st["minute"] >= 8:
            await c.post("/api/matches/demo/chaos", json={"action": "corrupt", "agent": "explainer"})
            await c.post("/api/matches/demo/chaos", json={"action": "kill", "agent": "persona", "seconds": 8})
            chaos_done = True
        rv = (await c.get("/api/matches/demo/reviews")).json()
        if rv["pending"] and not review_done:
            item = rv["pending"][0]
            res = (
                await c.post(
                    f"/api/matches/demo/reviews/{item['request_id']}",
                    json={"approved": True, "editor": "e2e-producer"},
                )
            ).json()
            reviewed = (item["moment"]["title"], res["outcome"])
            review_done = True
            await c.post("/api/matches/demo/review-policy", json={"enabled": False, "min_importance": 95})
        if st["status"] == "finished":
            break
        await asyncio.sleep(1)
    await asyncio.sleep(3)
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    wall = time.time() - t0
    check("Live", "full match replayed", st["status"] == "finished", f"{wall:.0f}s wall at 45x")

    allmsgs = [m for msgs in got.values() for m in msgs]
    kinds = collections.Counter(m["kind"] for m in got["fan:es"])
    check("Ingest", "events streamed live", kinds["event"] > 1000, kinds["event"])
    check("Render", "tracking frames streamed", kinds["frame"] > 100, kinds["frame"])
    check("Interpret", "live stats snapshots", kinds["stats"] > 10, kinds["stats"])
    cues = [m["data"] for m in got["fan:es"] if m["kind"] == "cue"]
    templates = {c["template"] for c in cues}
    need = {
        "score_bug",
        "shot_speed",
        "xg_popup",
        "speed_badge",
        "player_tag",
        "moment_card",
        "momentum_bar",
        "stat_compare",
        "lower_third",
    }
    check("Render", "overlay cue templates", need <= templates, sorted(templates))
    check("Render", "cues timed (t_out > t_in)", all(c["t_out"] > c["t_in"] for c in cues), len(cues))
    check(
        "Player identification",
        "name tags with player names",
        any(c["template"] == "player_tag" and c["data"].get("name") for c in cues),
    )
    check(
        "Player identification",
        "speed/distance badges on thresholds",
        any(c["template"] == "speed_badge" for c in cues),
    )
    moments = [m["data"] for m in got["fan:es"] if m["kind"] == "moment"]
    mtypes = collections.Counter(m["type"] for m in moments)
    check("Explain", "key moments detected", len(moments) > 20, dict(mtypes))
    check("Explain", "all 5 goals + red card detected", mtypes["goal"] == 5 and mtypes["red_card"] >= 1)
    check(
        "Explainability",
        "control vs chaos / pressing / momentum moments",
        mtypes["chaos_spike"] + mtypes["pressure_shift"] + mtypes["momentum_swing"] >= 2,
        {k: mtypes[k] for k in ("chaos_spike", "pressure_shift", "momentum_swing")},
    )
    check("Pass quality", "pass of the match (difficulty rating)", mtypes["pass_of_match"] >= 1)
    evs = [m["data"] for m in got["fan:es"] if m["kind"] == "event"]
    passes = [e for e in evs if e["type"] == "pass"]
    check(
        "Pass quality",
        "distance + difficulty on every pass",
        all("difficulty" in e["metrics"] and "distance_m" in e["metrics"] for e in passes),
        len(passes),
    )
    shots = [e for e in evs if e["type"] == "shot"]
    check(
        "Speed metrics",
        "shot speed + xG on every shot",
        all("ball_speed_kmh" in e["metrics"] and "xg" in e["metrics"] for e in shots),
        [round(e["metrics"]["ball_speed_kmh"]) for e in shots[:6]],
    )
    check("Speed metrics", "ball speed on passes", all("ball_speed_kmh" in e["metrics"] for e in passes))
    check("Ingest", "pressure events", any(e["type"] == "pressure" for e in evs))
    check(
        "Ingest",
        "possession changes (interceptions/tackles)",
        any(e["type"] in ("interception", "tackle") for e in evs),
    )

    insights = [m["data"] for m in allmsgs if m["kind"] == "insight"]
    check(
        "Explain",
        "insights cite facts",
        insights and all(i["cited_fact_ids"] for i in insights),
        len(insights),
    )
    for key in viewers:
        mode, lang = key.split(":")
        pers = [m["data"] for m in got[key] if m["kind"] == "personalized"]
        check(
            "Personalise",
            f"{key} receives own variants",
            pers and all(p["mode"] == mode and p["lang"] == lang for p in pers),
            f"{len(pers)} · {pers[0]['text'][:70] if pers else ''}",
        )
        comm = [m["data"] for m in got[key] if m["kind"] == "commentary"]
        check(
            "Multi-language",
            f"commentary in {lang}",
            comm and all(x["lang"] == lang for x in comm),
            comm[0]["text"][:70] if comm else "",
        )
    player_focus = [
        m["data"]
        for m in got["player:ja"]
        if m["kind"] == "personalized" and m["data"].get("focus_player_id") == "nbk-09"
    ]
    check(
        "Personalise",
        "player-focus mode tied to the followed player",
        len(player_focus) > 0,
        len(player_focus),
    )
    tact = [m["data"] for m in got["analyst:en"] if m["kind"] == "tactical"]
    check(
        "Explainability",
        "tactical shift notes (Tactician)",
        len(tact) >= 2,
        [t["summary"][:60] for t in tact[:2]],
    )
    recaps = [m["data"] for m in got["analyst:en"] if m["kind"] == "recap"]
    phases = {r["phase"] for r in recaps}
    check(
        "Narrative",
        "half-time + full-time recaps",
        {"half_time", "full_time"} <= phases,
        [r["headline"] for r in recaps],
    )
    ft = next((r for r in recaps if r["phase"] == "full_time"), None)
    check(
        "Narrative",
        "player of the match with reason",
        bool(ft and ft["potm_reason"]),
        ft["potm_reason"] if ft else "",
    )
    check(
        "Narrative",
        "milestones / season context",
        mtypes["milestone"] >= 1 or any("season" in i["text"] for i in insights),
        mtypes["milestone"],
    )

    traces = [m["data"] for m in got["analyst:en"] if m["kind"] == "trace"]
    agents = {t["agent"] for t in traces}
    check(
        "Multi-agent",
        "all agents active",
        {
            "spotter",
            "memory",
            "explainer",
            "narrator",
            "guardian",
            "persona",
            "publisher",
            "tactician",
            "producer",
        }
        <= agents,
        sorted(agents),
    )
    rej = [t for t in traces if t["agent"] == "guardian" and t["status"] == "rejected"]
    check(
        "Multi-agent", "Guardian caught injected wrong number", len(rej) >= 1, rej[0]["detail"] if rej else ""
    )
    check(
        "Multi-agent",
        "Explainer rewrote after rejection",
        any(t["agent"] == "explainer" and t["status"] == "retry" for t in traces),
    )
    check(
        "Multi-agent",
        "killed agent fell back, feed kept flowing",
        any(t["agent"] == "persona" and t["status"] == "fallback" for t in traces),
    )
    check(
        "Enterprise",
        "human review paused and approved via Agent Framework",
        reviewed is not None and reviewed[1] == "published",
        reviewed,
    )
    audit = (await c.get("/api/matches/demo/audit?limit=5000")).json()
    check("Enterprise", "audit trail for every check", len(audit) > 50, len(audit))
    status = (await c.get("/api/matches/demo/agents/status")).json()
    check(
        "Enterprise",
        "per-agent telemetry (calls, latency, errors)",
        status["totals"]["calls"] > 100,
        status["totals"],
    )

    # ------------------------------------------------------------ fact traceability
    if insights:
        fid = insights[-1]["cited_fact_ids"][0]
        f = (await c.get(f"/api/matches/demo/facts/{fid}")).json()
        check(
            "Explain",
            "citation resolves to a fact (+ source events)",
            f["fact"]["fact_id"] == fid,
            f["display"],
        )

    # ------------------------------------------------------------ watch party
    party = [m["data"] for m in got["fan:es"] if m["kind"] == "party"]
    ptypes = collections.Counter(p["type"] for p in party)
    check(
        "Watch party",
        "join / presence / chat / reactions",
        ptypes["welcome"] and ptypes["chat"] >= 1 and ptypes["react"] >= 1,
        dict(ptypes),
    )
    settled = [p for p in party if p["type"] == "settled"]
    check(
        "Watch party",
        "predictions settled by live goals",
        len(settled) >= 1,
        [(s["label"], s["winners"]) for s in settled[:2]],
    )

    # ------------------------------------------------------------ ask, A2A, MCP
    ans = (await c.post("/api/matches/demo/ask", json={"question": "Who is the fastest player?"})).json()
    check("Ask", "verified tool-based answer", ans["verified"] and ans["tools"], ans["answer"][:100])
    card = (await c.get("/a2a/.well-known/agent-card.json")).json()
    check("A2A", "agent card published", card.get("name") == "Touchline Analyst")
    try:
        from agent_framework.a2a import A2AAgent

        reply = await A2AAgent(url=f"{base}/a2a/", name="e2e").run("match:demo Who deserves to be winning?")
        check("A2A", "agent-to-agent call answered", bool(reply.text), reply.text[:100])
    except Exception as exc:  # pragma: no cover
        check("A2A", "agent-to-agent call answered", False, exc)
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=PY,
            args=["-m", "touchline.mcp_server"],
            cwd=str(ROOT / "backend"),
            env={**os.environ, "TOUCHLINE_API": base},
        )
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            check(
                "MCP", "tools exposed", {"match_state", "key_moments", "ask", "events"} <= set(tools), tools
            )
            res = await s.call_tool("match_state", {"match_id": "demo"})
            body = json.loads(res.content[0].text)
            check("MCP", "match_state via MCP", body["score"] == [3, 2], body["score"])
    except Exception as exc:  # pragma: no cover
        check("MCP", "MCP stdio session", False, repr(exc))


def write_report(seconds: float) -> None:
    out = ROOT / "docs" / "e2e"
    out.mkdir(parents=True, exist_ok=True)
    passed = sum(r[2] for r in RESULTS)
    lines = [
        "# Touchline end-to-end test report",
        "",
        f"**{passed} / {len(RESULTS)} checks passed** in {seconds:.0f} s (fresh server, offline mode, demo match replayed at 45×).",
        "",
        "Run it yourself: `cd backend && ../.venv/Scripts/python tests/e2e/run_e2e.py`",
        "",
        "| Area | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for area, name, ok, detail in RESULTS:
        lines.append(f"| {area} | {name} | {'✅' if ok else '❌'} | {detail.replace('|', '/')} |")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(RESULTS)} passed → docs/e2e/report.md")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
