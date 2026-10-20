"""touchline-mcp: Model Context Protocol server exposing live match intelligence.

Lets GitHub Copilot (agent mode), Claude or any MCP client query a running match:
"Why did Northbank lose control after 60'?" → tools below → verified answers.

Run:  python -m touchline.mcp_server            (stdio, for VS Code / Copilot)
      python -m touchline.mcp_server --http     (streamable HTTP on :8765)
Config: TOUCHLINE_API (default http://localhost:8000)
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP

API = os.environ.get("TOUCHLINE_API", "http://localhost:8000").rstrip("/")
mcp = FastMCP(
    "touchline",
    instructions=(
        "Live, explainable football match intelligence from synthetic data. Numbers returned by these tools are "
        "verified by Touchline's stats engine; quote them as-is. All clubs and players are fictional."
    ),
)


async def _get(path: str, **params: Any) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(API + path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(API + path, json=body)
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def list_matches() -> list[dict[str, Any]]:
    """List available matches with their status (ready, live, finished) and current minute."""
    return await _get("/api/matches")


@mcp.tool()
async def match_state(match_id: str = "demo") -> dict[str, Any]:
    """Score, minute, team stats (possession, xG, shots, PPDA, distance), momentum and Control vs Chaos index."""
    s = await _get(f"/api/matches/{match_id}/state")
    st = s["stats"]
    return {
        "status": s["status"]["status"],
        "minute": st["minute"],
        "score": st["score"],
        "home": s["meta"]["home"]["name"],
        "away": s["meta"]["away"]["name"],
        "home_stats": st["home"],
        "away_stats": st["away"],
        "momentum": st["momentum"],
        "control_vs_chaos": st["chaos"],
        "in_control": st["control"],
    }


@mcp.tool()
async def key_moments(match_id: str = "demo", min_importance: int = 55) -> list[dict[str, Any]]:
    """Key moments so far with importance (0-100), verified facts and the approved 'why it matters' text."""
    ms = await _get(f"/api/matches/{match_id}/moments", min_importance=min_importance)
    return [
        {
            "minute": m["minute"],
            "type": m["type"],
            "title": m["title"],
            "importance": m["importance"],
            "why": m.get("insight"),
            "facts": {f["fact_id"]: f"{f['label']}: {f['value']}{f['unit']}" for f in m["facts"]},
        }
        for m in ms
    ]


@mcp.tool()
async def events(
    match_id: str = "demo",
    from_minute: int = 0,
    to_minute: int = 120,
    type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Raw synthetic events (pass, shot, tackle, pressure, …) in a minute window, with computed metrics."""
    return await _get(
        f"/api/matches/{match_id}/events",
        from_minute=from_minute,
        to_minute=to_minute,
        type=type,
        limit=limit,
    )


@mcp.tool()
async def player(match_id: str, player_id: str) -> dict[str, Any]:
    """Live stats for one player (ids look like 'nbk-09'): distance, top speed, passes, xG, rating."""
    return await _get(f"/api/matches/{match_id}/players/{player_id}")


@mcp.tool()
async def fact(match_id: str, fact_id: str) -> dict[str, Any]:
    """Look up a cited fact (e.g. 'F182') and the source events behind it."""
    return await _get(f"/api/matches/{match_id}/facts/{fact_id}")


@mcp.tool()
async def ask(match_id: str, question: str, lang: str = "en") -> dict[str, Any]:
    """Ask Touchline's analyst agent a question; the answer's numbers are verified by the Guardian."""
    return await _post(f"/api/matches/{match_id}/ask", {"question": question, "lang": lang})


@mcp.tool()
async def agent_status(match_id: str = "demo") -> dict[str, Any]:
    """Multi-agent health: calls, latency, tokens, cost, rejections, open circuits, offline agents."""
    return await _get(f"/api/matches/{match_id}/agents/status")


@mcp.tool()
async def start_match(match_id: str = "demo", speed: float = 8) -> dict[str, Any]:
    """Kick off (or resume) a match replay at the given speed multiplier."""
    return await _post(f"/api/matches/{match_id}/start", {"speed": speed})


@mcp.tool()
async def generate_match(
    home: str = "nbk", away: str = "hbc", seed: int = 42, scenario: str | None = None
) -> dict[str, Any]:
    """Generate a new synthetic match. `scenario` is plain English, e.g. 'a comeback with a red card at 60'."""
    return await _post("/api/matches", {"home": home, "away": away, "seed": seed, "prompt": scenario})


def main() -> None:
    if "--http" in sys.argv:
        port = int(os.environ.get("MCP_PORT", "8765"))
        try:
            mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
        except TypeError:  # SDK 1.x configures host/port through settings
            mcp.settings.port = port
            mcp.settings.host = "0.0.0.0"
            mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
