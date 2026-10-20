"""Offline analysis pass over a whole match (no LLM, deterministic, cached).

Used for: the landing-page highlight clip, post-match recaps on demand, dataset
exports, and the evaluation harness that compares agent output with templates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from touchline.agents.context import MomentContext, build_context
from touchline.agents.guardian_rules import TEMPLATE_CONSTANTS, NameIndex, verify_text
from touchline.agents.specialists import corrupt_numbers
from touchline.agents.templates import render_explanation, render_personalized
from touchline.intel.moments import MomentDetector
from touchline.intel.overlay import CueBuilder
from touchline.models import Moment, MomentType, OverlayCue
from touchline.sim.engine import MatchData
from touchline.stats.engine import StatsEngine


@dataclass
class MatchAnalysis:
    data: MatchData
    stats: StatsEngine
    moments: list[Moment] = field(default_factory=list)
    contexts: dict[str, MomentContext] = field(default_factory=dict)
    outcomes: dict[str, str | None] = field(default_factory=dict)
    cues: list[OverlayCue] = field(default_factory=list)
    names: NameIndex | None = None

    def insight(self, moment_id: str, lang: str = "en") -> str:
        return render_explanation(self.contexts[moment_id], lang, self.outcomes[moment_id]).text


def analyze(data: MatchData) -> MatchAnalysis:
    stats = StatsEngine(data.meta, data.tracking)
    detector = MomentDetector(stats, data.meta.match_id)
    cues = CueBuilder(stats, data.meta.match_id)
    out = MatchAnalysis(data=data, stats=stats, names=NameIndex(data.meta))
    for ev in data.events:
        before = (stats.score["home"], stats.score["away"])
        triggers = stats.ingest(ev)
        out.cues += cues.for_event(ev, triggers)
        for m in detector.detect(ev, triggers):
            out.moments.append(m)
            out.contexts[m.moment_id] = build_context(m, stats, before)
            out.outcomes[m.moment_id] = ev.outcome
    return out


@lru_cache(maxsize=8)
def analysis_for(match_id: str) -> MatchAnalysis:
    from touchline.live.catalog import get_featured

    return analyze(get_featured(match_id))


def _frames(data: MatchData, t0: float, t1: float, step: int = 1) -> list[dict[str, Any]]:
    tr = data.tracking
    if tr is None:
        return []
    i0, i1 = tr.index_at(t0), tr.index_at(t1)
    out = []
    for i in range(i0, i1 + 1, step):
        p = tr.pos[i]
        out.append(
            {
                "t": round(float(tr.times[i]), 2),
                "b": [round(float(tr.ball[i, 0]), 1), round(float(tr.ball[i, 1]), 1)],
                "p": [
                    None if math.isnan(p[s, 0]) else [round(float(p[s, 0]), 1), round(float(p[s, 1]), 1)]
                    for s in range(22)
                ],
            }
        )
    return out


def clip(
    match_id: str,
    moment_type: str = "goal",
    index: int = -1,
    lang: str = "en",
    before_s: float = 14.0,
    after_s: float = 6.0,
) -> dict[str, Any]:
    """A short, real-data highlight: frames + cues + the moment explained in every mode."""
    a = analysis_for(match_id)
    candidates = [m for m in a.moments if m.type.value == moment_type] or [
        m for m in a.moments if m.importance >= 60
    ]
    m = candidates[index if -len(candidates) <= index < len(candidates) else -1]
    ctx = a.contexts[m.moment_id]
    t0, t1 = m.t - before_s, m.t + after_s
    tr = a.data.tracking
    ids = tr.ids_at(tr.index_at(m.t)) if tr is not None else []
    modes = {}
    for mode in ("analyst", "fan", "club", "player"):
        r = render_personalized(
            ctx,
            mode,
            lang,
            club=m.team,
            focus_player_id=m.player_id,
            focus_player_name=ctx.player,
            outcome=a.outcomes[m.moment_id],
        )
        modes[mode] = {"headline": r.headline, "text": r.text, "cited": r.cited}
    canonical = render_explanation(ctx, "en", a.outcomes[m.moment_id])
    # A real Guardian verdict on a deliberately corrupted draft, for the "nothing is made up" demo.
    bad = corrupt_numbers(canonical.text)
    bad_v = verify_text(
        bad, canonical.cited, a.stats.facts, names=a.names, extra_numbers=[m.minute, *TEMPLATE_CONSTANTS]
    )
    good_v = verify_text(
        canonical.text,
        canonical.cited,
        a.stats.facts,
        names=a.names,
        extra_numbers=[m.minute, *TEMPLATE_CONSTANTS],
    )
    meta = a.data.meta
    players = {
        p.id: {"name": p.name, "short": p.short_name, "number": p.number}
        for t in (meta.home, meta.away)
        for p in t.players
    }
    return {
        "moment": m.model_dump(mode="json"),
        "facts": {f.fact_id: {"label": f.label, "display": f.display()} for f in ctx.facts},
        "modes": modes,
        "guardian": {
            "draft": bad,
            "draft_verdict": bad_v.model_dump(),
            "final": canonical.text,
            "final_verdict": good_v.model_dump(),
        },
        "frames": _frames(a.data, t0, t1),
        "ids": ids,
        "players": players,
        "home": {"code": meta.home.code, "name": meta.home.short_name, "color": meta.home.primary},
        "away": {"code": meta.away.code, "name": meta.away.short_name, "color": meta.away.primary},
        "cues": [c.model_dump(mode="json") for c in a.cues if t0 <= c.t_in <= t1 + 1],
        "score_after": [ctx.score[0], ctx.score[1]],
    }


def summary(match_id: str) -> dict[str, Any]:
    a = analysis_for(match_id)
    snap = a.stats.snapshot()
    return {
        "match_id": match_id,
        "events": len(a.data.events),
        "frames": len(a.data.tracking) if a.data.tracking is not None else 0,
        "moments": len(a.moments),
        "facts": len(a.stats.facts),
        "cues": len(a.cues),
        "score": snap["score"],
        "home": snap["home"],
        "away": snap["away"],
        "key_moments": [
            {
                "minute": m.minute,
                "type": m.type.value,
                "title": m.title,
                "importance": m.importance,
                "why": a.insight(m.moment_id),
            }
            for m in a.moments
            if m.importance >= 55 and m.type != MomentType.PHASE
        ],
        "momentum_series": snap["momentum_series"],
    }
