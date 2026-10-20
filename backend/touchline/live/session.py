"""MatchSession: one live match, end to end.

feed (replay at N× speed) ──> bus (queue | Event Hubs) ──> ingest
    ingest: StatsEngine → overlay cues (instant) → MomentDetector
            → Agent Framework workflow per moment (Memory, Explainer, Narrator,
              Guardian, Persona/Localizer, Publisher) → hub (WebSocket | Web PubSub)
    every 15 match-minutes: Tactician;  half/full time: Producer recaps
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from touchline.agents.blackboard import make_blackboard
from touchline.agents.context import build_context
from touchline.agents.guardian_rules import NameIndex
from touchline.agents.llm import LLM
from touchline.agents.runtime import AgentRuntime
from touchline.agents.specialists import (
    Explainer,
    Guardian,
    MemoryAgent,
    Narrator,
    Persona,
    Producer,
    Sub,
    Tactician,
)
from touchline.agents.workflow import Agents, Bundle, MomentJob, VerifiedNarration, build_moment_workflow
from touchline.azure_services import ContentSafety, SearchMemory, Translator
from touchline.config import Settings
from touchline.intel.moments import MomentDetector
from touchline.intel.overlay import CueBuilder
from touchline.live.bus import make_bus
from touchline.live.party import Party
from touchline.models import EventType, MatchEvent, Moment, OverlayCue, WireMessage
from touchline.sim.engine import MatchData
from touchline.stats.engine import StatsEngine

log = logging.getLogger(__name__)

DEFAULT_SUBS = [Sub("fan", "en"), Sub("analyst", "en")]
MAX_SUBS = 14
FRAME_HZ = 8.0


class MatchSession:
    def __init__(self, data: MatchData, settings: Settings, llm: LLM, hub) -> None:
        self.data = data
        self.meta = data.meta
        self.match_id = data.meta.match_id
        self.settings = settings
        self.hub = hub
        self.llm = llm
        self.speed = settings.demo_speed
        self.status = "ready"
        self.t = 0.0
        self.minute = 0
        self.blackboard = make_blackboard(self.match_id, settings)
        self.stats = StatsEngine(self.meta, data.tracking)
        self.detector = MomentDetector(self.stats, self.match_id)
        self.cues = CueBuilder(self.stats, self.match_id)
        self.rt = AgentRuntime(
            self.match_id,
            llm,
            self.blackboard,
            self.emit,
            clock=lambda: self.t,
            timeout_s=settings.llm_timeout_s,
            budget_usd=settings.max_cost_per_match_usd,
        )
        translator = Translator(settings)
        self.guardian = Guardian(self.rt, self.stats, NameIndex(self.meta), ContentSafety(settings))
        self.agents = Agents(
            memory=MemoryAgent(self.rt, self.stats, SearchMemory(settings)),
            explainer=Explainer(self.rt),
            narrator=Narrator(self.rt),
            guardian=self.guardian,
            persona=Persona(self.rt, self.guardian, translator, self.stats),
        )
        self.producer = Producer(self.rt, self.stats, self.guardian, translator)
        self.tactician = Tactician(self.rt, self.stats, self.guardian)
        self.party = Party()
        self.pending_reviews: dict[str, tuple[Any, Any, float]] = {}
        self.moments: list[Moment] = []
        self.insights: dict[str, str] = {}
        self.recent_cues: list[OverlayCue] = []
        self._sem = asyncio.Semaphore(4)
        self._tasks: set[asyncio.Task] = set()
        self._moment_tasks: set[asyncio.Task] = set()
        self._moment_seen: dict[str, float] = {}
        self.insight_latency_ms: list[float] = []
        self._resume = asyncio.Event()
        self._resume.set()
        self._task: asyncio.Task | None = None
        self._next_tactical = 15
        self._last_ids_frame = -999
        self._ids_version = -1
        self.bus = None
        self.started_wall: float | None = None

    # ------------------------------------------------------------------ public control

    async def start(self, speed: float | None = None) -> None:
        if speed:
            self.speed = max(0.25, min(speed, 60.0))
        if self._task is None:
            self.status = "live"
            self.started_wall = time.time()
            self._task = asyncio.create_task(self._run(), name=f"session-{self.match_id}")
        else:
            self.resume()
        await self._status()

    def pause(self) -> None:
        self._resume.clear()
        self.status = "paused"

    def resume(self) -> None:
        self._resume.set()
        if self.status == "paused":
            self.status = "live"

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.25, min(speed, 60.0))

    async def stop(self) -> None:
        for task in list(self._tasks) + ([self._task] if self._task else []):
            task.cancel()
        self.status = "stopped"

    def chaos(self, action: str, agent: str, seconds: float = 45.0) -> dict[str, Any]:
        f = self.rt.faults
        if action == "kill":
            f.kill(agent, seconds)
        elif action == "revive":
            f.revive(agent)
        elif action == "corrupt":
            f.corrupt_next.add(agent)
        else:
            raise ValueError(action)
        return {
            "action": action,
            "agent": agent,
            "killed": sorted(a for a in f.killed_until if f.is_killed(a)),
            "corrupt_next": sorted(f.corrupt_next),
        }

    # ------------------------------------------------------------------ messaging

    async def emit(self, msg: WireMessage) -> None:
        await self.hub.broadcast(msg)

    async def _send(self, kind: str, data: dict[str, Any], t: float | None = None) -> None:
        await self.emit(
            WireMessage(kind=kind, match_id=self.match_id, t=self.t if t is None else t, data=data)
        )  # type: ignore[arg-type]

    async def _status(self) -> None:
        await self._send("status", self.status_dict())

    def status_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "speed": self.speed,
            "t": round(self.t, 1),
            "minute": self.minute,
            "viewers": self.hub.viewer_count(self.match_id),
            "bus": getattr(self.bus, "kind", "—"),
            "hub": self.hub.kind,
            "llm": self.llm.provider,
            "model_fast": self.llm.model_name("fast"),
            "model_reasoning": self.llm.model_name("reasoning"),
            "totals": self.rt.totals,
            "pending_moments": len(self._moment_tasks),
            "llm_mode": self.llm.mode,
            "budget_usd": self.rt.budget_usd,
            "over_budget": self.rt.over_budget(),
            "insight_latency_ms": self._latency(),
        }

    def _latency(self) -> dict[str, float | int]:
        """Moment detected → explained, verified, personalised and published (wall-clock)."""
        xs = sorted(self.insight_latency_ms)
        if not xs:
            return {"n": 0, "p50": 0.0, "p95": 0.0}
        pick = lambda q: round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)  # noqa: E731
        return {"n": len(xs), "p50": pick(0.5), "p95": pick(0.95)}

    def _spawn(self, coro, moment: bool = False) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        if moment:
            self._moment_tasks.add(task)
            task.add_done_callback(self._moment_tasks.discard)
        task.add_done_callback(self._log_task_error)
        return task

    @staticmethod
    def _log_task_error(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception():
            log.exception("background task failed", exc_info=task.exception())

    # ------------------------------------------------------------------ subscriptions

    def subs(self) -> list[Sub]:
        subs = list(dict.fromkeys(DEFAULT_SUBS + sorted(self.hub.subs(self.match_id), key=lambda s: s.key)))
        return subs[:MAX_SUBS]

    def langs(self) -> list[str]:
        return list(dict.fromkeys(["en"] + [s.lang for s in self.subs()]))[:6]

    # ------------------------------------------------------------------ main loops

    async def _run(self) -> None:
        self.bus = make_bus(self.settings, self.match_id)
        await self.bus.start()
        feed = self._spawn(self._feed())
        ticker = self._spawn(self._ticker())
        try:
            async for ev in self.bus.consume():
                await self._on_event(ev)
        finally:
            feed.cancel()
            if self._moment_tasks:
                await asyncio.wait(list(self._moment_tasks), timeout=60)
            ticker.cancel()
            self.status = "finished"
            await self._send("stats", self.stats.snapshot())
            await self._status()

    async def _feed(self) -> None:
        """Replays the synthetic feed in real time × speed, as a live data provider would."""
        events = self.data.events
        i = 0
        last = time.monotonic()
        last_frame = 0.0
        while i < len(events):
            await self._resume.wait()
            now = time.monotonic()
            self.t += (now - last) * self.speed
            last = now
            while i < len(events) and events[i].t <= self.t:
                await self.bus.publish(events[i])
                i += 1
            if now - last_frame >= 1 / FRAME_HZ:
                last_frame = now
                await self._frame()
            await asyncio.sleep(0.02)
            if not self._resume.is_set():
                last = time.monotonic()
        await self.bus.close()

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            if self.status == "live":
                await self._send("stats", self.stats.snapshot())
                await self._status()

    async def _frame(self) -> None:
        tr = self.data.tracking
        if tr is None:
            return
        i = tr.index_at(self.t)
        p = tr.pos[i]
        pts = [
            None if p[s, 0] != p[s, 0] else [round(float(p[s, 0]), 1), round(float(p[s, 1]), 1)]
            for s in range(22)
        ]
        data: dict[str, Any] = {
            "i": i,
            "b": [round(float(tr.ball[i, 0]), 1), round(float(tr.ball[i, 1]), 1)],
            "p": pts,
        }
        version = sum(1 for fi, _, _ in tr.roster_changes if fi <= i)
        if version != self._ids_version or i - self._last_ids_frame > 16:
            data["ids"] = tr.ids_at(i)
            self._ids_version = version
            self._last_ids_frame = i
        await self._send("frame", data)

    # ------------------------------------------------------------------ ingest

    async def _on_event(self, ev: MatchEvent) -> None:
        score_before = (self.stats.score["home"], self.stats.score["away"])
        started = time.perf_counter()
        triggers = self.stats.ingest(ev)
        self.minute = ev.minute
        metrics = self.stats.event_metrics[ev.event_id].as_dict()
        await self._send("event", {**ev.model_dump(mode="json"), "metrics": metrics}, t=ev.t)
        for cue in self.cues.for_event(ev, triggers):
            await self._cue(cue)
        moments = self.detector.detect(ev, triggers)
        for mo in moments:
            self.moments.append(mo)
            await self.blackboard.put("moment", mo.moment_id, mo)
            self._moment_seen[mo.moment_id] = time.perf_counter()
            await self._send("moment", mo.model_dump(mode="json"), t=mo.t)
            await self.rt.trace(
                "spotter",
                "score moment",
                "ok",
                started,
                detail=f"{mo.title} → importance {mo.importance}",
                output_ref=mo.moment_id,
                handoff_to="memory",
            )
            ctx = build_context(mo, self.stats, score_before)
            self._spawn(self._process_moment(mo, ctx, ev.outcome), moment=True)
        if ev.minute >= self._next_tactical and ev.type not in {EventType.HALF_END, EventType.MATCH_END}:
            self._next_tactical += 15
            self._spawn(self._tactical())
        if ev.type == EventType.SHOT and ev.outcome == "goal":
            scorer = self.stats.player_name(ev.player_id)
            result = self.party.settle(
                ev.team, ev.minute, f"{scorer} ({self.stats.team_name(ev.team)}) {ev.minute}'"
            )
            await self._send("party", {"type": "settled", **result, "members": self.party.leaderboard()})
        elif ev.type == EventType.MATCH_END and self.party.picks:
            result = self.party.settle("none", ev.minute, "No more goals")
            await self._send("party", {"type": "settled", **result, "members": self.party.leaderboard()})
        if ev.type == EventType.HALF_END:
            self._spawn(self._recap("half_time"))
        elif ev.type == EventType.MATCH_END:
            self._spawn(self._recap("full_time"))

    async def _cue(self, cue: OverlayCue) -> None:
        self.recent_cues.append(cue)
        self.recent_cues = self.recent_cues[-60:]
        await self.blackboard.put("cue", cue.cue_id, cue)
        await self._send("cue", cue.model_dump(mode="json"), t=cue.t_in)

    async def _process_moment(self, mo: Moment, ctx, outcome: str | None) -> None:
        async with self._sem:
            backlog = len(self._moment_tasks) > 6
            if backlog and mo.importance < 45:
                await self.rt.trace(
                    "spotter",
                    "triage",
                    "skipped",
                    time.perf_counter(),
                    detail=f"backlog: deprioritised '{mo.title}' (importance {mo.importance})",
                    input_ref=mo.moment_id,
                )
                return
            job = MomentJob(ctx=ctx, outcome=outcome, subs=self.subs(), langs=self.langs())
            workflow = build_moment_workflow(self.agents, self._publish)
            result = await workflow.run(job)
            for req in result.get_request_info_events():
                # Workflow paused for a human producer (Agent Framework request_info).
                bundle = req.data.bundle
                self.pending_reviews[req.request_id] = (workflow, req.data, time.time())
                item = self._review_item(req.request_id, req.data)
                await self._send("review", {"type": "pending", **item})
                await self.rt.trace(
                    "publisher",
                    "await producer approval",
                    "skipped",
                    time.perf_counter(),
                    detail=f"'{mo.title}' held for human review ({req.data.reason})",
                    input_ref=bundle.insight.insight_id,
                    handoff_to="producer (human)",
                )

    # ------------------------------------------------------------------ human-in-the-loop review

    def _review_item(self, request_id: str, req) -> dict[str, Any]:
        b = req.bundle
        m = b.job.ctx.moment
        return {
            "request_id": request_id,
            "moment": m.model_dump(mode="json"),
            "text": b.insight.text,
            "cited": b.insight.cited_fact_ids,
            "model": b.insight.model,
            "reason": req.reason,
            "variants": len(b.variants),
        }

    def reviews(self) -> list[dict[str, Any]]:
        return [
            {**self._review_item(rid, req), "waiting_s": round(time.time() - ts, 1)}
            for rid, (_, req, ts) in self.pending_reviews.items()
        ]

    async def decide(
        self, request_id: str, approved: bool, editor: str = "producer", edited_text: str | None = None
    ) -> dict[str, Any]:
        from touchline.agents.workflow import ReviewDecision

        if request_id not in self.pending_reviews:
            raise KeyError(request_id)
        workflow, req, ts = self.pending_reviews.pop(request_id)
        started = time.perf_counter()
        result = await workflow.run(responses={request_id: ReviewDecision(approved, editor, edited_text)})
        outputs = [str(o) for o in result.get_outputs()]
        outcome = (
            "published"
            if any(o.startswith("insight:") for o in outputs)
            else (
                "edit rejected by Guardian"
                if any(o.startswith("edit-rejected") for o in outputs)
                else "rejected"
            )
        )
        await self.rt.trace(
            "publisher",
            f"producer decision: {outcome}",
            "ok" if outcome == "published" else "rejected",
            started,
            detail=f"{editor} after {time.time() - ts:.0f}s; {'; '.join(outputs)[:160]}",
            input_ref=request_id,
        )
        await self.blackboard.put(
            "audit",
            f"review:{request_id}",
            {
                "ref": request_id,
                "surface": "human review",
                "approved": outcome == "published",
                "reasons": outputs,
                "text": edited_text or req.bundle.insight.text,
                "cited": req.bundle.insight.cited_fact_ids,
                "editor": editor,
                "t": self.t,
            },
        )
        await self._send("review", {"type": "resolved", "request_id": request_id, "outcome": outcome})
        return {"request_id": request_id, "outcome": outcome, "outputs": outputs}

    async def _publish(self, item: Bundle | VerifiedNarration) -> None:
        if isinstance(item, Bundle):
            ins = item.insight
            moment = item.job.ctx.moment
            self.insights[moment.moment_id] = ins.text
            if moment.moment_id in self._moment_seen:
                self.insight_latency_ms.append(
                    (time.perf_counter() - self._moment_seen.pop(moment.moment_id)) * 1000
                )
            await self.blackboard.put("insight", ins.insight_id, ins)
            await self._send(
                "insight",
                {**ins.model_dump(mode="json"), "moment": moment.model_dump(mode="json")},
                t=moment.t,
            )
            headline = None
            for v in item.variants:
                key = Sub(v.mode, v.lang, v.focus_team, v.focus_player_id).key
                await self.blackboard.put(
                    "personalized", f"{moment.moment_id}:{key}", {**v.model_dump(mode="json"), "sub_key": key}
                )
                await self._send("personalized", {**v.model_dump(mode="json"), "sub_key": key}, t=moment.t)
                if v.mode == "fan" and v.lang == "en":
                    headline = v.headline
            card = self.cues.for_moment(moment, headline)
            if card:
                card.t_in = max(card.t_in, self.t + 0.2)
                card.t_out = card.t_in + 7.0
                await self._cue(card)
            await self.rt.trace(
                "publisher",
                "publish insight",
                "ok",
                time.perf_counter(),
                detail=f"{len(item.variants)} variants to viewers",
                input_ref=ins.insight_id,
            )
        else:
            for line in item.lines:
                await self.blackboard.put("commentary", line.line_id, line)
                await self._send("commentary", line.model_dump(mode="json"), t=line.t)

    async def _tactical(self) -> None:
        shift = await self.tactician.run()
        if shift:
            await self.blackboard.put("tactical", shift.shift_id, shift)
            await self._send("tactical", shift.model_dump(mode="json"))

    async def _recap(self, phase: str) -> None:
        await asyncio.sleep(0.5)
        pending = [t for t in self._moment_tasks if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=45)
        langs = [lang for lang in self.langs()][:3]
        recaps = await self.producer.run(phase, list(self.moments), dict(self.insights), langs)
        for rec in recaps:
            await self.blackboard.put("recap", rec.recap_id, rec)
            await self._send("recap", rec.model_dump(mode="json"))
        if phase == "full_time" and self.settings.logic_app_recap_url:
            await self._distribute(recaps[0].model_dump(mode="json"))

    async def _distribute(self, recap: dict[str, Any]) -> None:
        """Hand the full-time recap to an Azure Logic App (email / Teams distribution)."""
        import httpx

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(self.settings.logic_app_recap_url, json=recap)
                r.raise_for_status()
            await self.rt.trace("publisher", "distribute recap (Logic App)", "ok", started, detail="sent")
        except Exception as exc:
            await self.rt.trace(
                "publisher", "distribute recap (Logic App)", "error", started, detail=str(exc)
            )

    # ------------------------------------------------------------------ late-joiner state

    async def state(self, sub: Sub | None = None) -> dict[str, Any]:
        sub = sub or DEFAULT_SUBS[0]
        personalized = [
            p for p in await self.blackboard.list("personalized", 400) if p.get("sub_key") == sub.key
        ]
        commentary = [c for c in await self.blackboard.list("commentary", 400) if c.get("lang") == sub.lang]
        return {
            "meta": self.meta.model_dump(mode="json"),
            "status": self.status_dict(),
            "stats": self.stats.snapshot(),
            "moments": [m.model_dump(mode="json") for m in self.moments[-80:]],
            "insights": await self.blackboard.list("insight", 80),
            "personalized": personalized[-80:],
            "commentary": commentary[-80:],
            "cues": [c.model_dump(mode="json") for c in self.recent_cues if c.t_out >= self.t - 2],
            "recaps": await self.blackboard.list("recap", 10),
            "tactical": await self.blackboard.list("tactical", 20),
            "traces": await self.blackboard.list("trace", 150),
            "agents": self.rt.agent_status(),
            "ids": self.data.tracking.ids_at(self.data.tracking.index_at(self.t))
            if self.data.tracking is not None
            else [],
        }


class SessionManager:
    def __init__(self, settings: Settings, hub) -> None:
        self.settings = settings
        self.hub = hub
        self.llm = LLM(settings)
        self.sessions: dict[str, MatchSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, match_id: str, create: bool = True) -> MatchSession:
        if match_id in self.sessions:
            return self.sessions[match_id]
        if not create:
            raise KeyError(match_id)
        lock = self._locks.setdefault(match_id, asyncio.Lock())
        async with lock:
            if match_id not in self.sessions:
                from touchline.live.catalog import get_featured

                data = await asyncio.to_thread(get_featured, match_id)
                self.sessions[match_id] = MatchSession(data, self.settings, self.llm, self.hub)
        return self.sessions[match_id]

    async def restart(self, match_id: str) -> MatchSession:
        old = self.sessions.pop(match_id, None)
        if old:
            await old.stop()
        return await self.get(match_id)

    async def add(self, data: MatchData) -> MatchSession:
        session = MatchSession(data, self.settings, self.llm, self.hub)
        self.sessions[data.meta.match_id] = session
        return session
