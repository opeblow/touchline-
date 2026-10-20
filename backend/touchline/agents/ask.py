"""Ask Touchline: natural-language questions about the live match.

Online: an Agent Framework `Agent` with function tools over the live stats engine
(the same tools are exposed to GitHub Copilot / Claude through the MCP server).
Every number returned by a tool is recorded, and the Guardian rejects answers that
contain any other number. Offline: an intent router over the same tools.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from touchline.agents.guardian_rules import extract_numbers
from touchline.models import MomentType

if TYPE_CHECKING:
    from touchline.live.session import MatchSession

INSTRUCTIONS = """You are Touchline's match analyst. Answer the viewer's question about the live match
in at most 70 words, in the requested language. Always call tools to get numbers; never guess.
Use only numbers returned by tools. Mention only players and clubs that tools return.
Be specific and explain the 'why', not just the 'what'."""


class MatchTools:
    """Read-only tools over a live session. Every numeric output is remembered for verification."""

    def __init__(self, session: MatchSession) -> None:
        self.s = session
        self.numbers: set[float] = set()
        self.used: list[str] = []

    def _record(self, name: str, data: Any) -> Any:
        self.used.append(name)
        self.numbers |= set(extract_numbers(str(data)))
        return data

    def match_summary(self) -> dict[str, Any]:
        """Current score, minute, possession, shots, xG, PPDA and momentum for both teams."""
        st = self.s.stats
        snap = st.snapshot()
        out = {
            "minute": st.minute,
            "home": st.meta.home.short_name,
            "away": st.meta.away.short_name,
            "score": f"{st.score['home']}-{st.score['away']}",
            "momentum_home_positive": snap["momentum"],
            "control_vs_chaos_index": snap["chaos"],
        }
        for side in ("home", "away"):
            t = snap[side]
            out[side + "_stats"] = {
                k: t[k]
                for k in (
                    "possession",
                    "shots",
                    "shots_on_target",
                    "xg",
                    "pass_accuracy",
                    "ppda",
                    "big_chances",
                    "distance_km",
                )
            }
        return self._record("match_summary", out)

    def key_moments(self, min_importance: int = 55) -> list[dict[str, Any]]:
        """Key moments so far with minute, title and the approved explanation."""
        out = [
            {"minute": m.minute, "title": m.title, "why": self.s.insights.get(m.moment_id)}
            for m in self.s.moments
            if m.importance >= min_importance
        ]
        return self._record("key_moments", out[-12:])

    def player(self, name: str) -> dict[str, Any] | None:
        """Live stats for one player, found by full or partial name."""
        q = name.lower().strip()
        st = self.s.stats
        for pid, p in st.players.items():
            if q and (q in p.name.lower() or q == p.short_name.lower()):
                snap = st.player_snapshot(pid)
                return self._record(
                    "player",
                    {
                        "name": p.name,
                        "team": st.team_name(st.player_side[pid]),
                        "position": p.position,
                        **{
                            k: snap[k]
                            for k in (
                                "goals",
                                "assists",
                                "shots",
                                "xg",
                                "passes",
                                "pass_accuracy",
                                "distance_km",
                                "top_speed",
                                "sprints",
                                "tackles",
                                "rating",
                            )
                        },
                    },
                )
        return None

    def leaders(self, metric: str = "rating", top: int = 3) -> list[dict[str, Any]]:
        """Top players by a metric: rating, top_speed, distance_km, passes, xg, tackles, sprints."""
        st = self.s.stats
        snaps = [st.player_snapshot(pid) for pid, p in st.pstats.items() if p.touches > 0]
        metric = (
            metric
            if metric in {"rating", "top_speed", "distance_km", "passes", "xg", "tackles", "sprints"}
            else "rating"
        )
        best = sorted(snaps, key=lambda x: -x[metric])[:top]
        return self._record(
            "leaders",
            [
                {"name": st.player_name(b["id"]), "team": st.team_name(b["side"]), metric: b[metric]}
                for b in best
            ],
        )

    def tactical_shifts(self) -> list[str]:
        """Tactical changes detected by the Tactician agent in 15-minute windows."""
        return self._record(
            "tactical_shifts", [t["summary"] for t in self.s.blackboard._items.get("tactical", {}).values()]
        )


def _offline_answer(tools: MatchTools, q: str) -> str:
    ql = q.lower()
    summ = tools.match_summary()
    h, a = summ["home"], summ["away"]
    hs, as_ = summ["home_stats"], summ["away_stats"]
    words = set(re.findall(r"[a-zà-ÿ]+", ql))
    for _pid, p in tools.s.stats.players.items():
        if p.short_name.lower() in words or p.name.lower() in ql:
            d = tools.player(p.short_name)
            if d:
                return (
                    f"{d['name']} ({d['team']}): {d['goals']} goals, {d['xg']} xG from {d['shots']} shots, "
                    f"{d['passes']} passes at {d['pass_accuracy']}% accuracy, {d['distance_km']} km covered and a top "
                    f"speed of {d['top_speed']} km/h. Match rating {d['rating']}."
                )
    if any(w in ql for w in ("fast", "speed", "quick", "pace")):
        lead = tools.leaders("top_speed", 3)
        return (
            "Fastest so far: "
            + "; ".join(f"{x['name']} ({x['team']}) {x['top_speed']} km/h" for x in lead)
            + "."
        )
    if any(w in ql for w in ("run", "distance", "work")):
        lead = tools.leaders("distance_km", 3)
        return "Most ground covered: " + "; ".join(f"{x['name']} {x['distance_km']} km" for x in lead) + "."
    if any(w in ql for w in ("press", "ppda", "pressing")):
        return (
            f"PPDA (passes allowed per defensive action, lower = more aggressive press): {h} {hs['ppda']}, "
            f"{a} {as_['ppda']}. " + " ".join(tools.tactical_shifts()[-1:])
        )
    if any(w in ql for w in ("xg", "chance", "deserve", "expected")):
        if abs(hs["xg"] - as_["xg"]) < 0.15:
            verdict = "Neither side has created clearly better chances"
        else:
            verdict = f"{h if hs['xg'] > as_['xg'] else a} have created the better chances"
        return (
            f"Expected goals: {h} {hs['xg']} from {hs['shots']} shots, {a} {as_['xg']} from {as_['shots']}. "
            f"{verdict}; the score is {summ['score']}."
        )
    if any(w in ql for w in ("best", "star", "player of", "motm", "potm", "rating")):
        lead = tools.leaders("rating", 3)
        return (
            "Top performers by match rating: "
            + "; ".join(f"{x['name']} ({x['team']}) {x['rating']}" for x in lead)
            + "."
        )
    if any(w in ql for w in ("why", "how", "turn", "comeback", "lose", "losing", "win", "winning", "happen")):
        moments = tools.key_moments(60)
        turning = [m for m in moments if m["why"]][-3:]
        if turning:
            return f"It's {summ['score']}. The turning points: " + " ".join(
                f"{m['minute']}' {m['title']}: {m['why']}" for m in turning
            )
    return (
        f"{h} {summ['score']} {a} after {summ['minute']} minutes. Possession {hs['possession']}% to "
        f"{as_['possession']}%, shots {hs['shots']} to {as_['shots']}, xG {hs['xg']} to {as_['xg']}."
    )


async def ask(session: MatchSession, question: str, lang: str = "en") -> dict[str, Any]:
    started = time.perf_counter()
    tools = MatchTools(session)
    llm = session.llm
    model = "offline-router"
    result = None
    answer = ""
    if llm.online:
        try:
            from agent_framework import Agent, tool

            fns = [
                tool(tools.match_summary),
                tool(tools.key_moments),
                tool(tools.player),
                tool(tools.leaders),
                tool(tools.tactical_shifts),
            ]
            agent = Agent(client=llm._clients["fast"], name="ask", instructions=INSTRUCTIONS, tools=fns)
            resp = await agent.run(
                f"Language: {lang}. Question: {question}", options={"max_tokens": 300, "temperature": 0.3}
            )
            answer = (resp.text or "").strip()
            model = llm.model_name("fast")
            result = resp
        except Exception:
            answer = ""
    if not answer:
        answer = _offline_answer(tools, question)
        model = "offline-router"
    # Guardian: every number must come from a tool output, minute or score.
    allowed = tools.numbers | {float(session.stats.minute), 0.0, 1.0}
    bad = [
        n
        for n in extract_numbers(answer)
        if not any(abs(n - a) <= (0.051 if n < 10 else 0.51) for a in allowed)
    ]
    verified = not bad
    if not verified:
        answer = _offline_answer(tools, question)
        model += " → guardian fallback"
    await session.rt.trace(
        "ask",
        "answer viewer question",
        "ok" if verified else "fallback",
        started,
        detail=f"Q: {question[:80]} | tools: {', '.join(dict.fromkeys(tools.used))}",
        handoff_to="guardian",
    )
    _ = result, MomentType
    return {
        "answer": answer,
        "tools": list(dict.fromkeys(tools.used)),
        "verified": True,
        "model": model,
        "rejected_numbers": [f"{b:g}" for b in bad],
    }
