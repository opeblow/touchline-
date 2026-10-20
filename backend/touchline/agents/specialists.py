"""The specialist agents.

Each agent has one job, a typed output, an LLM path (Microsoft Foundry via Agent
Framework) and a deterministic fallback path. All outputs that contain language
pass through the Guardian before anything is published.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from dataclasses import dataclass
from importlib import resources
from typing import Any

from touchline.agents.context import MomentContext
from touchline.agents.guardian_rules import TEMPLATE_CONSTANTS, NameIndex, verify_text
from touchline.agents.runtime import AgentRuntime
from touchline.agents.templates import (
    LANGS,
    render_commentary,
    render_explanation,
    render_personalized,
)
from touchline.azure_services import ContentSafety, SearchMemory, Translator
from touchline.models import (
    CommentaryLine,
    EventType,
    Fact,
    Insight,
    Mode,
    Moment,
    MomentType,
    PersonalizedInsight,
    Recap,
    Side,
    TacticalShift,
    Verdict,
)
from touchline.season import get_season_memory
from touchline.sim.scenario import Scenario, parse_scenario_text
from touchline.sim.shape import to_attacking
from touchline.stats.engine import StatsEngine, other

LANG_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "pt": "Portuguese",
    "ar": "Arabic",
    "ja": "Japanese",
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
    "ko": "Korean",
    "zh-Hans": "Chinese (Simplified)",
    "hi": "Hindi",
    "sw": "Swahili",
    "tr": "Turkish",
    "id": "Indonesian",
    "pl": "Polish",
    "yo": "Yoruba",
}


def load_prompt(name: str) -> str:
    return resources.files("touchline.agents").joinpath(f"prompts/{name}.md").read_text(encoding="utf-8")


PROMPTS = {
    n: load_prompt(n) for n in ("explainer", "narrator", "persona", "producer", "tactician", "scenario")
}


@dataclass(frozen=True)
class Sub:
    """A personalisation target requested by at least one connected viewer."""

    mode: Mode
    lang: str
    club: Side | None = None
    player_id: str | None = None

    @property
    def key(self) -> str:
        return f"{self.mode}:{self.lang}:{self.club or '-'}:{self.player_id or '-'}"


def corrupt_numbers(text: str) -> str:
    """Fault injection for the live demo: change the first number so the Guardian must catch it."""
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        return text + " That was the 7th such chance."
    raw = m.group(0)
    wrong = f"{float(raw) * 1.7 + 3.13:.2f}" if "." in raw else str(int(raw) + 17)
    return text[: m.start()] + wrong + text[m.end() :]


# =============================================================================== Guardian


class Guardian:
    name = "guardian"

    def __init__(self, rt: AgentRuntime, stats: StatsEngine, names: NameIndex, safety: ContentSafety) -> None:
        self.rt, self.stats, self.names, self.safety = rt, stats, names, safety

    async def check(
        self,
        text: str,
        cited: list[str],
        *,
        minute: int,
        template: bool,
        surface: str,
        ref: str,
        handoff_ok: str | None = None,
        handoff_reject: str | None = None,
        trace: bool = True,
        max_chars: int = 480,
    ) -> Verdict:
        started = time.perf_counter()
        extra: list[float] = [float(minute)] + (list(TEMPLATE_CONSTANTS) if template else [])
        verdict = verify_text(
            text, cited, self.stats.facts, names=self.names, extra_numbers=extra, max_chars=max_chars
        )
        if verdict.approved and self.safety.enabled:
            safe, cats = await self.safety.screen(text)
            if not safe:
                verdict.approved = False
                verdict.reasons.append(f"Azure AI Content Safety flagged: {', '.join(cats)}")
        await self.rt.blackboard.put(
            "audit",
            f"{ref}:{surface}:{int(time.time() * 1000)}",
            {
                "ref": ref,
                "surface": surface,
                "approved": verdict.approved,
                "reasons": verdict.reasons,
                "text": text,
                "cited": cited,
                "t": self.rt.clock(),
            },
        )
        if trace:
            detail = "approved" if verdict.approved else "; ".join(verdict.reasons)
            await self.rt.trace(
                self.name,
                f"verify {surface}",
                "ok" if verdict.approved else "rejected",
                started,
                detail=detail,
                input_ref=ref,
                handoff_to=handoff_ok if verdict.approved else handoff_reject,
            )
        return verdict


# =============================================================================== Memory


class MemoryAgent:
    """Adds season context (league goals, table position, form) as new verified facts."""

    name = "memory"

    def __init__(self, rt: AgentRuntime, stats: StatsEngine, search: SearchMemory) -> None:
        self.rt, self.stats, self.search = rt, stats, search
        self.local = get_season_memory()

    async def run(self, ctx: MomentContext) -> list[Fact]:
        started = time.perf_counter()
        m = ctx.moment
        md = self.stats.meta.matchday - 1
        facts: list[Fact] = []
        source = "azure-ai-search" if self.search.enabled else "local season store"
        if m.type in {MomentType.GOAL} and m.player_id:
            profile = None
            if self.search.enabled:
                doc = await self.search.lookup(f"{m.player_id}-md{md:02d}")
                if doc:
                    profile = {"g": doc.get("goals", 0), "apps": doc.get("apps", 0)}
            if profile is None and self.local.available:
                profile = self.local.player_as_of(m.player_id, md)
            if profile is not None:
                total = int(profile.get("g", 0)) + self.stats.pstats[m.player_id].goals
                facts.append(
                    self.stats.fact(
                        "season_goals",
                        f"{ctx.player} league goals this season",
                        total,
                        team=m.team,
                        player_id=m.player_id,
                    )
                )
        if m.type in {MomentType.GOAL, MomentType.PHASE, MomentType.RED_CARD} and self.local.available:
            sides: list[Side] = [m.team] if m.team else ["home", "away"]
            for side in sides:
                team = self.stats.meta.home if side == "home" else self.stats.meta.away
                row = self.local.team_as_of(team.id, md)
                if row:
                    facts.append(
                        self.stats.fact(
                            "league_position",
                            f"{team.short_name} league position before kick-off",
                            row["pos"],
                            team=side,
                        )
                    )
                    facts.append(
                        self.stats.fact(
                            "form", f"{team.short_name} last five results", row["form"], team=side
                        )
                    )
        await self.rt.trace(
            self.name,
            "recall",
            "ok" if facts else "skipped",
            started,
            detail=f"{len(facts)} season facts from {source}",
            input_ref=m.moment_id,
            handoff_to="explainer",
        )
        return facts


# =============================================================================== Explainer


class Explainer:
    name = "explainer"

    def __init__(self, rt: AgentRuntime) -> None:
        self.rt = rt

    def template(self, ctx: MomentContext, outcome: str | None, attempt: int) -> Insight:
        r = render_explanation(ctx, "en", outcome)
        return Insight(
            insight_id=f"{ctx.moment.moment_id}-I{attempt}",
            moment_id=ctx.moment.moment_id,
            match_id=ctx.moment.match_id,
            text=r.text,
            cited_fact_ids=r.cited,
            attempts=attempt,
            model="offline-template",
            fallback=self.rt.llm.online,
        )

    async def run(
        self,
        ctx: MomentContext,
        outcome: str | None,
        attempt: int = 1,
        feedback: list[str] | None = None,
        force_template: bool = False,
    ) -> Insight:
        started = time.perf_counter()
        result = None
        if self.rt.llm.online and not force_template:

            async def call():
                payload = {**ctx.prompt_dict(), "guardian_feedback": feedback or None}
                res = await self.rt.llm.complete(
                    agent=self.name,
                    instructions=PROMPTS["explainer"],
                    prompt=json.dumps(payload, ensure_ascii=False, default=str),
                    tier="fast",
                    json_mode=True,
                    max_tokens=300,
                    temperature=0.4,
                )
                data = res.json()
                ins = Insight(
                    insight_id=f"{ctx.moment.moment_id}-I{attempt}",
                    moment_id=ctx.moment.moment_id,
                    match_id=ctx.moment.match_id,
                    text=str(data["text"]).strip(),
                    cited_fact_ids=[str(x) for x in data.get("cited_fact_ids", [])],
                    attempts=attempt,
                    model=res.model,
                )
                return ins, res

            (insight, result), status, detail = await self.rt.guarded(
                self.name, call, lambda: (self.template(ctx, outcome, attempt), None)
            )
        else:
            insight, status = self.template(ctx, outcome, attempt), "fallback" if force_template else "ok"
            detail = (
                "Guardian rejected twice → verified template" if force_template else "offline template writer"
            )
            if not self.rt.llm.online and not force_template:
                insight.fallback = False
            if self.rt.faults.is_killed(self.name) and not force_template:
                status, detail = "fallback", "agent offline (chaos test) → template fallback"
        if self.rt.faults.take_corruption(self.name):
            insight.text = corrupt_numbers(insight.text)
            detail = "FAULT INJECTED: a wrong number was written into this draft"
        trace_status = "retry" if attempt > 1 and status == "ok" else status
        await self.rt.trace(
            self.name,
            "explain" if attempt == 1 else f"rewrite (attempt {attempt})",
            trace_status,
            started,
            result=result,
            detail=detail or insight.text[:140],
            input_ref=ctx.moment.moment_id,
            output_ref=insight.insight_id,
            handoff_to="guardian",
        )
        return insight


# =============================================================================== Narrator


class Narrator:
    name = "narrator"

    def __init__(self, rt: AgentRuntime) -> None:
        self.rt = rt

    async def run(self, ctx: MomentContext, outcome: str | None, langs: list[str]) -> list[CommentaryLine]:
        started = time.perf_counter()
        lines: list[CommentaryLine] = []
        results = []
        status, detail = "ok", ""

        async def one(lang: str) -> CommentaryLine:
            nonlocal status, detail

            def fb() -> tuple[CommentaryLine, Any]:
                text, tone = render_commentary(
                    ctx, lang if lang in LANGS else "en", outcome, seed=hash(ctx.moment.moment_id)
                )
                return CommentaryLine(
                    line_id=f"{ctx.moment.moment_id}-N-{lang}",
                    match_id=ctx.moment.match_id,
                    t=ctx.moment.t,
                    minute=ctx.moment.minute,
                    text=text,
                    tone=tone,  # type: ignore[arg-type]
                    lang=lang,
                ), None

            if not self.rt.llm.online:
                line, _ = fb()
                return line

            async def call():
                payload = {**ctx.prompt_dict(), "lang": LANG_NAMES.get(lang, lang)}
                res = await self.rt.llm.complete(
                    agent=self.name,
                    instructions=PROMPTS["narrator"],
                    prompt=json.dumps(payload, ensure_ascii=False, default=str),
                    tier="fast",
                    json_mode=True,
                    max_tokens=120,
                    temperature=0.8,
                )
                data = res.json()
                tone = data.get("tone", "calm")
                line = CommentaryLine(
                    line_id=f"{ctx.moment.moment_id}-N-{lang}",
                    match_id=ctx.moment.match_id,
                    t=ctx.moment.t,
                    minute=ctx.moment.minute,
                    text=str(data["text"]).strip(),
                    tone=tone if tone in {"calm", "build", "excited", "somber"} else "calm",
                    lang=lang,
                )
                line.__dict__["_cited"] = [str(x) for x in data.get("cited_fact_ids", [])]
                return line, res

            (line, res), st, det = await self.rt.guarded(self.name, call, fb)
            if res is not None:
                results.append(res)
            if st != "ok":
                status, detail = st, det
            return line

        lines = list(await asyncio.gather(*(one(lang) for lang in langs)))
        merged = None
        if results:
            from touchline.agents.llm import LLMResult

            merged = LLMResult(
                text="",
                model=results[0].model,
                tokens_in=sum(r.tokens_in for r in results),
                tokens_out=sum(r.tokens_out for r in results),
                latency_ms=max(r.latency_ms for r in results),
                cost_usd=sum(r.cost_usd for r in results),
            )
        await self.rt.trace(
            self.name,
            "commentate",
            status,
            started,
            result=merged,
            detail=detail or f"{len(lines)} languages: {lines[0].text[:90] if lines else ''}",
            input_ref=ctx.moment.moment_id,
            handoff_to="guardian",
        )
        return lines


# =============================================================================== Persona & Localizer


class Persona:
    name = "persona"

    def __init__(
        self, rt: AgentRuntime, guardian: Guardian, translator: Translator, stats: StatsEngine
    ) -> None:
        self.rt, self.guardian, self.translator, self.stats = rt, guardian, translator, stats

    def _focus_name(self, pid: str | None) -> str | None:
        return self.stats.players[pid].name if pid and pid in self.stats.players else None

    def _template(self, ctx: MomentContext, sub: Sub, outcome: str | None) -> tuple[str, str, list[str]]:
        r = render_personalized(
            ctx,
            sub.mode,
            sub.lang if sub.lang in LANGS else "en",
            club=sub.club,
            focus_player_id=sub.player_id,
            focus_player_name=self._focus_name(sub.player_id),
            outcome=outcome,
        )
        return r.headline, r.text, r.cited

    async def _one(
        self, ctx: MomentContext, insight: Insight, sub: Sub, outcome: str | None
    ) -> tuple[PersonalizedInsight, str, Any]:
        m = ctx.moment
        how = "template"
        result = None
        headline = text = ""
        cited: list[str] = []
        if (
            self.rt.llm.online
            and not self.rt.faults.is_killed(self.name)
            and not self.rt.breaker(self.name).is_open
        ):
            try:
                payload = {
                    **ctx.prompt_dict(),
                    "canonical_insight": insight.text,
                    "mode": sub.mode,
                    "lang_name": LANG_NAMES.get(sub.lang, sub.lang),
                    "club": (ctx.home if sub.club == "home" else ctx.away) if sub.club else None,
                    "focus_player": self._focus_name(sub.player_id),
                }
                result = await asyncio.wait_for(
                    self.rt.llm.complete(
                        agent=self.name,
                        instructions=PROMPTS["persona"],
                        prompt=json.dumps(payload, ensure_ascii=False, default=str),
                        tier="fast",
                        json_mode=True,
                        max_tokens=260,
                        temperature=0.6,
                    ),
                    timeout=self.rt.timeout_s,
                )
                data = result.json()
                headline, text = str(data.get("headline", "")).strip(), str(data["text"]).strip()
                cited = [str(x) for x in data.get("cited_fact_ids", [])]
                v = await self.guardian.check(
                    text,
                    cited,
                    minute=m.minute,
                    template=False,
                    surface=f"persona {sub.mode}/{sub.lang}",
                    ref=insight.insight_id,
                    trace=False,
                )
                how = "llm" if v.approved else "llm-rejected"
                self.rt.breaker(self.name).success()
            except Exception:
                self.rt.breaker(self.name).failure()
                how = "llm-error"
        if how != "llm":
            if sub.lang not in LANGS and self.translator.enabled:
                headline_en, text_en, cited = self._template(
                    ctx, Sub(sub.mode, "en", sub.club, sub.player_id), outcome
                )
                protect = [
                    ctx.player,
                    ctx.team,
                    ctx.opponent,
                    ctx.home,
                    ctx.away,
                    self._focus_name(sub.player_id),
                ]
                try:
                    headline = await self.translator.translate(headline_en, sub.lang, protect)  # type: ignore[arg-type]
                    text = await self.translator.translate(text_en, sub.lang, protect)  # type: ignore[arg-type]
                    how = "translator" if how == "template" else how + "→translator"
                except Exception:
                    headline, text = headline_en, text_en
            else:
                headline, text, cited = self._template(ctx, sub, outcome)
                how = "template" if how == "template" else how + "→template"
        variant = PersonalizedInsight(
            insight_id=insight.insight_id,
            moment_id=m.moment_id,
            mode=sub.mode,
            lang=sub.lang,
            headline=headline,
            text=text,
            cited_fact_ids=cited,
            focus_team=sub.club,
            focus_player_id=sub.player_id,
        )
        return variant, how, result

    async def run(
        self, ctx: MomentContext, insight: Insight, subs: list[Sub], outcome: str | None
    ) -> list[PersonalizedInsight]:
        started = time.perf_counter()
        if self.rt.faults.is_killed(self.name):
            pass  # _one() falls back to templates per variant
        outs = await asyncio.gather(*(self._one(ctx, insight, s, outcome) for s in subs))
        variants = [o[0] for o in outs]
        hows = [o[1] for o in outs]
        results = [o[2] for o in outs if o[2] is not None]
        merged = None
        if results:
            from touchline.agents.llm import LLMResult

            merged = LLMResult(
                text="",
                model=results[0].model,
                tokens_in=sum(r.tokens_in for r in results),
                tokens_out=sum(r.tokens_out for r in results),
                latency_ms=max(r.latency_ms for r in results),
                cost_usd=sum(r.cost_usd for r in results),
            )
        rejected = sum("rejected" in h for h in hows)
        status = "fallback" if self.rt.faults.is_killed(self.name) or rejected else "ok"
        summary = ", ".join(sorted({f"{s.mode}/{s.lang}" for s in subs}))
        detail = f"{len(variants)} variants ({summary})" + (
            f"; {rejected} rejected by Guardian → template" if rejected else ""
        )
        if self.rt.faults.is_killed(self.name):
            detail = "agent offline (chaos test) → template variants; " + detail
        await self.rt.trace(
            self.name,
            "personalise + localise",
            status,
            started,
            result=merged,
            detail=detail,
            input_ref=insight.insight_id,
            handoff_to="publisher",
        )
        return variants


# =============================================================================== Producer (recaps)


class Producer:
    name = "producer"

    def __init__(
        self, rt: AgentRuntime, stats: StatsEngine, guardian: Guardian, translator: Translator
    ) -> None:
        self.rt, self.stats, self.guardian, self.translator = rt, stats, guardian, translator

    def _facts(self, phase: str) -> dict[str, Fact]:
        s = self.stats
        h, a = s.meta.home.short_name, s.meta.away.short_name
        poss = s.possession_pct()
        f = {
            "score": s.fact("score", "Score", f"{s.score['home']}-{s.score['away']}"),
            "xg_h": s.fact("xg_total", f"{h} xG", round(s.tstats["home"].xg, 2), team="home"),
            "xg_a": s.fact("xg_total", f"{a} xG", round(s.tstats["away"].xg, 2), team="away"),
            "sh_h": s.fact("shots", f"{h} shots", s.tstats["home"].shots, team="home"),
            "sh_a": s.fact("shots", f"{a} shots", s.tstats["away"].shots, team="away"),
            "poss_h": s.fact("possession", f"{h} possession", poss["home"], "%", team="home"),
            "ppda_h": s.fact("ppda", f"{h} PPDA", round(s.tstats["home"].ppda, 1), team="home"),
            "ppda_a": s.fact("ppda", f"{a} PPDA", round(s.tstats["away"].ppda, 1), team="away"),
        }
        return f

    def _goals(self) -> list[tuple[int, Side, str, str]]:
        out = []
        for e in self.stats.events:
            if e.type == EventType.SHOT and e.outcome == "goal":
                out.append((e.minute, e.team, self.stats.player_name(e.player_id), e.event_id))
        return out

    def _offline(
        self, phase: str, facts: dict[str, Fact], moments: list[Moment], insights: dict[str, str]
    ) -> Recap:
        s = self.stats
        h, a = s.meta.home.short_name, s.meta.away.short_name
        hs, as_ = s.score["home"], s.score["away"]
        goals = self._goals()
        cited = [f.fact_id for f in facts.values()]
        max_def = getattr(s, "_max_deficit", {"home": 0, "away": 0})
        if hs == as_:
            headline = (
                f"{h} and {a} share the points"
                if phase == "full_time"
                else f"All square at the break between {h} and {a}"
            )
        else:
            w, lo = (h, a) if hs > as_ else (a, h)
            wside: Side = "home" if hs > as_ else "away"
            if phase == "full_time" and max_def.get(wside, 0) >= 2:
                headline = f"{w} complete a stunning comeback against {lo}"
            elif abs(hs - as_) >= 3:
                headline = (
                    f"{w} run riot against {lo}"
                    if phase == "full_time"
                    else f"{w} in total control at half time"
                )
            else:
                headline = f"{w} edge {lo}" if phase == "full_time" else f"{w} lead {lo} at the break"
        xg_h, xg_a = float(facts["xg_h"].value), float(facts["xg_a"].value)
        better = h if xg_h > xg_a else a
        standfirst = (
            f"{h} {facts['score'].value} {a}. On expected goals it was {facts['xg_h'].display()} to "
            f"{facts['xg_a'].display()}, with {better} creating the better chances."
        )
        paras = []
        first = [g for g in goals if g[0] <= 45]
        second = [g for g in goals if g[0] > 45]

        def goal_list(gs: list[tuple[int, Side, str, str]]) -> str:
            return "; ".join(
                f"{name} ({h if side == 'home' else a}, {minute}')" for minute, side, name, _ in gs
            )

        if first:
            paras.append(f"**First half.** Goals: {goal_list(first)}.")
        else:
            paras.append("**First half.** No goals before the break.")
        if phase == "full_time":
            turning = [
                m
                for m in moments
                if m.type in {MomentType.RED_CARD, MomentType.MOMENTUM_SWING, MomentType.PRESSURE_SHIFT}
                and m.moment_id in insights
            ]
            if turning:
                bits = []
                for m in turning[:3]:
                    bits.append(f"{m.minute}': {insights[m.moment_id]}")
                    cited += [f.fact_id for f in m.facts]
                paras.append("**Turning points.** " + " ".join(bits))
            paras.append(
                "**Second half.** "
                + (f"Goals: {goal_list(second)}." if second else "No goals after the break.")
            )
        paras.append(
            f"**The numbers.** Shots {facts['sh_h'].display()} to {facts['sh_a'].display()}; {h} had "
            f"{facts['poss_h'].display()} possession. PPDA {facts['ppda_h'].display()} for {h} and "
            f"{facts['ppda_a'].display()} for {a}, where lower means a more aggressive press."
        )
        potm_id = s.player_of_match()
        potm_reason = None
        if potm_id:
            ps = s.pstats[potm_id]
            rf = s.fact("rating", f"{s.player_name(potm_id)} match rating", ps.rating(), player_id=potm_id)
            parts = [f"a {rf.display()} rating"]
            cited.append(rf.fact_id)
            if ps.goals:
                gf = s.fact("player_goals", f"{s.player_name(potm_id)} goals", ps.goals, player_id=potm_id)
                parts.append(f"{gf.display()} goal{'s' if ps.goals > 1 else ''}")
                cited.append(gf.fact_id)
            if ps.passes >= 20:
                pf = s.fact(
                    "pass_accuracy",
                    f"{s.player_name(potm_id)} pass accuracy",
                    round(ps.pass_accuracy),
                    "%",
                    player_id=potm_id,
                )
                parts.append(f"{pf.display()} passing accuracy")
                cited.append(pf.fact_id)
            dist = s.fact(
                "distance",
                f"{s.player_name(potm_id)} distance",
                round(ps.distance_m / 1000, 1),
                "km",
                player_id=potm_id,
            )
            if ps.distance_m > 0:
                parts.append(f"{dist.display()} covered")
                cited.append(dist.fact_id)
            potm_reason = f"{s.player_name(potm_id)}: " + ", ".join(parts) + "."
        return Recap(
            recap_id=f"{s.meta.match_id}-{phase}-en",
            match_id=s.meta.match_id,
            phase=phase,  # type: ignore[arg-type]
            lang="en",
            headline=headline,
            standfirst=standfirst,
            body_md="\n\n".join(paras),
            key_moments=[m.moment_id for m in sorted(moments, key=lambda m: -m.importance)[:6]],
            player_of_match=potm_id,
            potm_reason=potm_reason,
            cited_fact_ids=sorted(set(cited)),
            model="offline-template",
        )

    async def run(
        self, phase: str, moments: list[Moment], insights: dict[str, str], langs: list[str]
    ) -> list[Recap]:
        started = time.perf_counter()
        facts = self._facts(phase)
        base = self._offline(phase, facts, moments, insights)
        recaps: list[Recap] = []
        result = None
        status, detail = "ok", "offline recap writer"
        if self.rt.llm.online:

            async def call(lang: str):
                payload = {
                    "phase": phase,
                    "lang_name": LANG_NAMES.get(lang, lang),
                    "home": self.stats.meta.home.short_name,
                    "away": self.stats.meta.away.short_name,
                    "facts": [
                        {"id": f.fact_id, "label": f.label, "display": f.display()}
                        for f in list(facts.values())
                        + [self.stats.facts[i] for i in base.cited_fact_ids if i in self.stats.facts]
                    ],
                    "goals": [{"minute": g[0], "team": g[1], "scorer": g[2]} for g in self._goals()],
                    "key_moments": [
                        {"minute": m.minute, "title": m.title, "explanation": insights.get(m.moment_id)}
                        for m in moments
                        if m.importance >= 55
                    ],
                    "player_of_match": self.stats.player_name(base.player_of_match),
                }
                res = await self.rt.llm.complete(
                    agent=self.name,
                    instructions=PROMPTS["producer"],
                    prompt=json.dumps(payload, ensure_ascii=False, default=str),
                    tier="reasoning",
                    json_mode=True,
                    max_tokens=900,
                    temperature=0.5,
                )
                d = res.json()
                rec = base.model_copy(
                    update={
                        "recap_id": f"{self.stats.meta.match_id}-{phase}-{lang}",
                        "lang": lang,
                        "headline": d["headline"],
                        "standfirst": d["standfirst"],
                        "body_md": d["body_md"],
                        "potm_reason": d.get("potm_reason"),
                        "cited_fact_ids": [str(x) for x in d.get("cited_fact_ids", [])],
                        "model": res.model,
                    }
                )
                return rec, res

            for lang in langs:
                (rec, res), st, det = await self.rt.guarded(
                    self.name, lambda lang=lang: call(lang), lambda: (base, None), timeout_s=40
                )
                if res is not None:
                    result = res
                    full = " ".join([rec.headline, rec.standfirst, rec.body_md, rec.potm_reason or ""])
                    v = await self.guardian.check(
                        full,
                        rec.cited_fact_ids,
                        minute=90,
                        template=False,
                        surface=f"recap {lang}",
                        ref=rec.recap_id,
                        max_chars=4000,
                        handoff_ok="publisher",
                        handoff_reject="producer",
                    )
                    if not v.approved:
                        rec, st, det = base, "fallback", "Guardian rejected recap → verified template"
                if st != "ok":
                    status, detail = st, det
                recaps.append(rec)
        else:
            recaps.append(base)
            for lang in langs:
                if lang != "en" and self.translator.enabled:
                    protect = [p.name for p in self.stats.players.values()] + [
                        self.stats.meta.home.short_name,
                        self.stats.meta.away.short_name,
                    ]
                    with contextlib.suppress(Exception):
                        recaps.append(
                            base.model_copy(
                                update={
                                    "recap_id": f"{base.recap_id[:-3]}-{lang}",
                                    "lang": lang,
                                    "headline": await self.translator.translate(base.headline, lang, protect),
                                    "standfirst": await self.translator.translate(
                                        base.standfirst, lang, protect
                                    ),
                                    "body_md": await self.translator.translate(base.body_md, lang, protect),
                                    "potm_reason": await self.translator.translate(
                                        base.potm_reason or "", lang, protect
                                    ),
                                    "model": "azure-ai-translator",
                                }
                            )
                        )
        await self.rt.trace(
            self.name,
            f"recap {phase.replace('_', ' ')}",
            status,
            started,
            result=result,
            detail=f"{len(recaps)} recap(s): {recaps[0].headline}" if status == "ok" else detail,
            output_ref=recaps[0].recap_id,
            handoff_to="publisher",
        )
        return recaps


# =============================================================================== Tactician


class Tactician:
    name = "tactician"

    def __init__(self, rt: AgentRuntime, stats: StatsEngine, guardian: Guardian) -> None:
        self.rt, self.stats, self.guardian = rt, stats, guardian
        self._seq = 0

    def _window(self, side: Side, t0: float, t1: float) -> dict[str, float]:
        evs = [e for e in self.stats.events if t0 <= e.t < t1]
        opp = other(side)
        passes = [e for e in evs if e.type == EventType.PASS]
        own = [e for e in passes if e.team == side]
        opp_build = sum(1 for e in passes if e.team == opp and to_attacking(e.x, e.y, opp)[0] < 63)
        defs = sum(
            1
            for e in evs
            if e.team == side
            and e.type in {EventType.TACKLE, EventType.INTERCEPTION, EventType.FOUL}
            and to_attacking(e.x, e.y, side)[0] > 42
        )
        mins = max((t1 - t0) / 60, 1)
        xg = sum(
            self.stats.event_metrics[e.event_id].xg or 0
            for e in evs
            if e.type == EventType.SHOT and e.team == side
        )
        return {
            "possession": 100 * len(own) / len(passes) if passes else 50.0,
            "ppda": opp_build / defs if defs else float(opp_build),
            "tempo": len(own) / mins,
            "xg": xg,
        }

    async def run(self) -> TacticalShift | None:
        s = self.stats
        t1 = s.t
        if t1 < 1800:
            return None
        started = time.perf_counter()
        best: tuple[float, Side, str, dict, dict] | None = None
        for side in ("home", "away"):
            a, b = self._window(side, t1 - 1800, t1 - 900), self._window(side, t1 - 900, t1)  # type: ignore[arg-type]
            cands = []
            if a["ppda"] >= 5 and b["ppda"] <= 0.65 * a["ppda"]:
                cands.append((a["ppda"] / max(b["ppda"], 0.5), "press_up"))
            if b["ppda"] >= 1.6 * max(a["ppda"], 2):
                cands.append((b["ppda"] / max(a["ppda"], 1), "press_drop"))
            if b["possession"] - a["possession"] >= 10:
                cands.append(((b["possession"] - a["possession"]) / 8, "control"))
            if b["tempo"] >= 1.3 * max(a["tempo"], 1):
                cands.append((b["tempo"] / max(a["tempo"], 1), "tempo_up"))
            if b["xg"] - a["xg"] >= 0.5:
                cands.append((1 + (b["xg"] - a["xg"]) * 2, "threat_up"))
            for score, kind in cands:
                if best is None or score > best[0]:
                    best = (score, side, kind, a, b)  # type: ignore[assignment]
        if best is None:
            await self.rt.trace(
                self.name,
                "scan 15-minute windows",
                "skipped",
                started,
                detail="no significant tactical change",
            )
            return None
        _, side, kind, a, b = best
        name = s.team_name(side)
        m0, m1 = max(int((t1 - 1800) // 60), 0), int(t1 // 60)
        metric = {
            "press_up": "ppda",
            "press_drop": "ppda",
            "control": "possession",
            "tempo_up": "tempo",
            "threat_up": "xg",
        }[kind]
        unit = {"ppda": "", "possession": "%", "tempo": " passes/min", "xg": ""}[metric]
        label = {"ppda": "PPDA", "possession": "possession", "tempo": "passes per minute", "xg": "xG"}[metric]
        kind_fact = "xg_total" if metric == "xg" else metric
        f_prev = s.fact(
            kind_fact,
            f"{name} {label}, minutes {m0}-{m0 + 15}",
            round(a[metric], 2 if metric == "xg" else 1),
            unit.strip() if unit != "%" else "%",
            team=side,
        )
        f_now = s.fact(
            kind_fact,
            f"{name} {label}, minutes {m0 + 15}-{m1}",
            round(b[metric], 2 if metric == "xg" else 1),
            unit.strip() if unit != "%" else "%",
            team=side,
        )
        offline = {
            "press_up": f"{name} have pressed far more aggressively in the last 15 minutes: PPDA down from {f_prev.display()} to {f_now.display()}. Expect more turnovers high up the pitch.",
            "press_drop": f"{name} have dropped off: PPDA up from {f_prev.display()} to {f_now.display()}. They are inviting pressure and protecting space behind.",
            "control": f"{name} have taken hold of the ball: possession up from {f_prev.display()} to {f_now.display()} over the last 15 minutes.",
            "tempo_up": f"{name} have sped the game up: {f_now.display()} compared with {f_prev.display()} in the previous 15 minutes.",
            "threat_up": f"{name} are creating far better chances: {f_now.display()} xG in the last 15 minutes against {f_prev.display()} before.",
        }[kind]
        summary, cited, result, status = offline, [f_prev.fact_id, f_now.fact_id], None, "ok"
        if self.rt.llm.online:

            async def call():
                payload = {
                    "team": name,
                    "shift": kind,
                    "facts": [
                        {"id": f.fact_id, "label": f.label, "display": f.display()} for f in (f_prev, f_now)
                    ],
                }
                res = await self.rt.llm.complete(
                    agent=self.name,
                    instructions=PROMPTS["tactician"],
                    prompt=json.dumps(payload),
                    tier="reasoning",
                    json_mode=True,
                    max_tokens=200,
                    temperature=0.4,
                )
                d = res.json()
                return (str(d["summary"]), [str(x) for x in d.get("cited_fact_ids", [])]), res

            ((summary, cited), result), status, _ = await self.rt.guarded(
                self.name, call, lambda: ((offline, cited), None)
            )
            v = await self.guardian.check(
                summary,
                cited,
                minute=m1,
                template=False,
                surface="tactical",
                ref=f"tactical-{m1}",
                trace=False,
            )
            if not v.approved:
                summary, cited, status = offline, [f_prev.fact_id, f_now.fact_id], "fallback"
        self._seq += 1
        shift = TacticalShift(
            shift_id=f"{s.meta.match_id}-T{self._seq}",
            match_id=s.meta.match_id,
            window=(m0, m1),
            team=side,
            kind=kind,
            summary=summary,
            facts=[f_prev, f_now],
        )
        await self.rt.trace(
            self.name,
            "detect tactical shift",
            status,
            started,
            result=result,
            detail=summary[:160],
            output_ref=shift.shift_id,
            handoff_to="publisher",
        )
        return shift


# =============================================================================== Scenario Director


class ScenarioDirector:
    name = "scenario"

    def __init__(self, rt: AgentRuntime | None, llm) -> None:
        self.rt, self.llm = rt, llm

    async def run(self, request: str) -> tuple[Scenario, str]:
        if self.llm.online:
            try:
                res = await asyncio.wait_for(
                    self.llm.complete(
                        agent=self.name,
                        instructions=PROMPTS["scenario"],
                        prompt=request,
                        tier="fast",
                        json_mode=True,
                        max_tokens=400,
                        temperature=0.3,
                    ),
                    timeout=20,
                )
                return Scenario.model_validate(res.json()), res.model
            except Exception:
                pass
        return parse_scenario_text(request), "offline-parser"
