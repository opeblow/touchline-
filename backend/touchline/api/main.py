"""Touchline API: REST + realtime for the web app, the overlay renderer and the MCP server."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from touchline import __version__
from touchline.agents.ask import ask
from touchline.agents.specialists import ScenarioDirector, Sub
from touchline.agents.workflow import GRAPH
from touchline.azure_services import ContentSafety
from touchline.config import ROOT, get_settings
from touchline.live.catalog import FEATURED, generate
from touchline.live.hub import Client, make_hub
from touchline.live.party import REACTIONS
from touchline.live.session import SessionManager
from touchline.season import SEASON_DIR, get_season_memory
from touchline.sim.league import build_league
from touchline.sim.scenario import PRESETS
from touchline.telemetry import configure

log = logging.getLogger("touchline.api")
settings = get_settings()
configure(settings)
hub = make_hub(settings)
manager = SessionManager(settings, hub)
safety = ContentSafety(settings)
WEB_DIR = ROOT / "web" / "out"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the featured demo match in the background so the first visitor doesn't wait.
    asyncio.create_task(manager.get("demo"))
    yield


app = FastAPI(
    title="Touchline API",
    version=__version__,
    lifespan=lifespan,
    description="Explainable, personalised match intelligence from synthetic football events.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------------- enterprise controls


def require_operator(x_touchline_key: str | None = Header(None)) -> None:
    """Control actions (start, chaos, approvals, generation) need the operator key when one is configured."""
    if settings.control_api_key and x_touchline_key != settings.control_api_key:
        raise HTTPException(401, "Operator key required (header x-touchline-key)")


OPERATOR = [Depends(require_operator)]
_ask_hits: dict[str, list[float]] = {}


def rate_limit_ask(request: Request) -> None:
    import time as _t

    key = request.client.host if request.client else "anon"
    now = _t.time()
    hits = [h for h in _ask_hits.get(key, []) if now - h < 60]
    if len(hits) >= settings.ask_rate_per_minute:
        raise HTTPException(429, "Too many questions; try again in a minute")
    _ask_hits[key] = hits + [now]


# A2A: Touchline's analyst agent, discoverable by other agents at /a2a/.well-known/agent-card.json
try:
    from touchline.a2a_server import build_a2a_app

    app.mount("/a2a", build_a2a_app(manager))
except Exception as exc:  # pragma: no cover - optional dependency
    log.warning("A2A endpoint disabled: %s", exc)


# ----------------------------------------------------------------------------- models


class StartRequest(BaseModel):
    speed: float | None = Field(None, ge=0.25, le=60)


class ChaosRequest(BaseModel):
    action: Literal["kill", "revive", "corrupt"]
    agent: Literal["explainer", "narrator", "persona", "guardian", "memory", "producer", "tactician"] = (
        "explainer"
    )
    seconds: float = Field(45, ge=5, le=600)


class CreateMatchRequest(BaseModel):
    home: str = "nbk"
    away: str = "hbc"
    seed: int = Field(42, ge=0, le=10_000_000)
    preset: str | None = None
    prompt: str | None = Field(None, max_length=400)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=300)
    lang: str = "en"


class SubRequest(BaseModel):
    mode: Literal["analyst", "fan", "club", "player"] = "fan"
    lang: str = "en"
    club: Literal["home", "away"] | None = None
    player_id: str | None = None


# ----------------------------------------------------------------------------- health & catalog


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": __version__,
        "llm": manager.llm.mode,
        "hub": hub.kind,
        "mode": settings.touchline_mode,
        "season": get_season_memory().available,
        "operator_key_required": bool(settings.control_api_key),
        "budget_usd_per_match": settings.max_cost_per_match_usd,
    }


@app.get("/api/matches")
async def list_matches() -> list[dict[str, Any]]:
    out = []
    for e in FEATURED:
        s = manager.sessions.get(e.match_id)
        out.append(
            {
                "match_id": e.match_id,
                "title": e.title,
                "blurb": e.blurb,
                "home": e.home,
                "away": e.away,
                "preset": e.preset,
                "status": s.status if s else "ready",
                "minute": s.minute if s else 0,
            }
        )
    for mid, s in manager.sessions.items():
        if mid not in {e.match_id for e in FEATURED}:
            out.append(
                {
                    "match_id": mid,
                    "title": f"{s.meta.home.name} v {s.meta.away.name}",
                    "blurb": s.meta.scenario.get("label", "Custom scenario"),
                    "home": s.meta.home.id,
                    "away": s.meta.away.id,
                    "preset": "custom",
                    "status": s.status,
                    "minute": s.minute,
                }
            )
    return out


@app.post("/api/matches", dependencies=OPERATOR)
async def create_match(req: CreateMatchRequest) -> dict[str, Any]:
    """Data Studio: generate a new synthetic match, optionally from a natural-language scenario."""
    ids = {t.id for t in build_league()}
    if req.home not in ids or req.away not in ids or req.home == req.away:
        raise HTTPException(400, "Pick two different clubs from /api/league")
    director_model = None
    if req.prompt:
        scenario, director_model = await ScenarioDirector(None, manager.llm).run(req.prompt)
    else:
        scenario = PRESETS.get(req.preset or "classic", PRESETS["classic"])
    match_id = f"custom-{req.home}-{req.away}-{req.seed}-{uuid.uuid4().hex[:4]}"
    data = await asyncio.to_thread(generate, match_id, req.home, req.away, req.seed, scenario)
    await manager.add(data)
    h, a = data.final_score()
    return {
        "match_id": match_id,
        "scenario": scenario.model_dump(),
        "scenario_model": director_model,
        "events": len(data.events),
        "frames": len(data.tracking) if data.tracking else 0,
        "preview_score": None if req.prompt is None else [h, a],
    }


@app.get("/api/presets")
async def presets() -> dict[str, Any]:
    return {k: v.model_dump() for k, v in PRESETS.items()}


@app.get("/api/league")
async def league() -> list[dict[str, Any]]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "short_name": t.short_name,
            "code": t.code,
            "primary": t.primary,
            "secondary": t.secondary,
            "style": t.style.model_dump(),
        }
        for t in build_league()
    ]


# ----------------------------------------------------------------------------- match


async def _session(match_id: str):
    try:
        return await manager.get(match_id)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown match '{match_id}'") from exc


@app.get("/api/matches/{match_id}")
async def match_meta(match_id: str) -> dict[str, Any]:
    s = await _session(match_id)
    return {"meta": s.meta.model_dump(mode="json"), "status": s.status_dict()}


@app.get("/api/matches/{match_id}/state")
async def match_state(
    match_id: str, mode: str = "fan", lang: str = "en", club: str | None = None, player_id: str | None = None
) -> dict[str, Any]:
    s = await _session(match_id)
    sub = Sub(mode, lang, club if club in ("home", "away") else None, player_id or None)  # type: ignore[arg-type]
    return await s.state(sub)


@app.post("/api/matches/{match_id}/start", dependencies=OPERATOR)
async def start(match_id: str, req: StartRequest | None = None) -> dict[str, Any]:
    s = await _session(match_id)
    if s.status == "finished":
        s = await manager.restart(match_id)
    await s.start(req.speed if req else None)
    return s.status_dict()


@app.post("/api/matches/{match_id}/pause", dependencies=OPERATOR)
async def pause(match_id: str) -> dict[str, Any]:
    s = await _session(match_id)
    s.pause()
    return s.status_dict()


@app.post("/api/matches/{match_id}/resume", dependencies=OPERATOR)
async def resume(match_id: str) -> dict[str, Any]:
    s = await _session(match_id)
    s.resume()
    return s.status_dict()


@app.post("/api/matches/{match_id}/speed", dependencies=OPERATOR)
async def speed(match_id: str, req: StartRequest) -> dict[str, Any]:
    s = await _session(match_id)
    s.set_speed(req.speed or settings.demo_speed)
    return s.status_dict()


@app.post("/api/matches/{match_id}/restart", dependencies=OPERATOR)
async def restart(match_id: str) -> dict[str, Any]:
    s = await manager.restart(match_id)
    return s.status_dict()


@app.post("/api/matches/{match_id}/chaos", dependencies=OPERATOR)
async def chaos(match_id: str, req: ChaosRequest) -> dict[str, Any]:
    s = await _session(match_id)
    return s.chaos(req.action, req.agent, req.seconds)


@app.post("/api/matches/{match_id}/ask", dependencies=[Depends(rate_limit_ask)])
async def ask_match(match_id: str, req: AskRequest) -> dict[str, Any]:
    s = await _session(match_id)
    return await ask(s, req.question, req.lang)


@app.post("/api/matches/{match_id}/subscribe")
async def subscribe(match_id: str, req: SubRequest) -> dict[str, Any]:
    """Register a personalisation target (used by Web PubSub clients) and get a connection URL."""
    s = await _session(match_id)
    sub = Sub(req.mode, req.lang, req.club, req.player_id)
    hub.register_remote(match_id, sub)
    url = hub.client_url(match_id, sub, uuid.uuid4().hex) if hasattr(hub, "client_url") else None
    return {
        "sub_key": sub.key,
        "webpubsub_url": url,
        "viewers": hub.viewer_count(match_id),
        "status": s.status,
    }


@app.get("/api/matches/{match_id}/events")
async def events(
    match_id: str,
    from_minute: int = 0,
    to_minute: int = 200,
    type: str | None = None,
    limit: int = Query(500, le=5000),
) -> list[dict[str, Any]]:
    s = await _session(match_id)
    evs = [
        e for e in s.stats.events if from_minute <= e.minute <= to_minute and (type is None or e.type == type)
    ]
    return [
        {**e.model_dump(mode="json"), "metrics": s.stats.event_metrics[e.event_id].as_dict()}
        for e in evs[-limit:]
    ]


@app.get("/api/matches/{match_id}/full-events")
async def full_events(match_id: str) -> list[dict[str, Any]]:
    """The complete synthetic event stream (dataset export), regardless of replay position."""
    s = await _session(match_id)
    return [e.model_dump(mode="json") for e in s.data.events]


@app.get("/api/matches/{match_id}/moments")
async def moments(match_id: str, min_importance: int = 0) -> list[dict[str, Any]]:
    s = await _session(match_id)
    return [
        {**m.model_dump(mode="json"), "insight": s.insights.get(m.moment_id)}
        for m in s.moments
        if m.importance >= min_importance
    ]


class ReviewPolicyRequest(BaseModel):
    enabled: bool
    min_importance: int = Field(90, ge=0, le=100)


class ReviewDecisionRequest(BaseModel):
    approved: bool
    editor: str = Field("producer", max_length=60)
    edited_text: str | None = Field(None, max_length=600)


@app.get("/api/matches/{match_id}/reviews")
async def reviews(match_id: str) -> dict[str, Any]:
    """Human-in-the-loop: insights paused by the Agent Framework workflow, awaiting a producer."""
    s = await _session(match_id)
    p = s.agents.review
    return {"policy": {"enabled": p.enabled, "min_importance": p.min_importance}, "pending": s.reviews()}


@app.post("/api/matches/{match_id}/review-policy", dependencies=OPERATOR)
async def review_policy(match_id: str, req: ReviewPolicyRequest) -> dict[str, Any]:
    s = await _session(match_id)
    s.agents.review.enabled = req.enabled
    s.agents.review.min_importance = req.min_importance
    return {"enabled": req.enabled, "min_importance": req.min_importance}


@app.post("/api/matches/{match_id}/reviews/{request_id}", dependencies=OPERATOR)
async def review_decide(match_id: str, request_id: str, req: ReviewDecisionRequest) -> dict[str, Any]:
    s = await _session(match_id)
    try:
        return await s.decide(request_id, req.approved, req.editor, req.edited_text)
    except KeyError as exc:
        raise HTTPException(404, "No pending review with that id") from exc


@app.get("/api/matches/{match_id}/party")
async def party_state(match_id: str) -> dict[str, Any]:
    s = await _session(match_id)
    return s.party.state()


@app.get("/api/matches/{match_id}/players/{player_id}")
async def player(match_id: str, player_id: str) -> dict[str, Any]:
    s = await _session(match_id)
    if player_id not in s.stats.pstats:
        raise HTTPException(404, "Unknown player")
    p = s.stats.players[player_id]
    return {"player": p.model_dump(), **s.stats.player_snapshot(player_id)}


@app.get("/api/matches/{match_id}/clip")
async def match_clip(match_id: str, type: str = "goal", index: int = -1, lang: str = "en") -> dict[str, Any]:
    """Real-data highlight for the landing page: frames, overlay cues and the moment in every mode."""
    from touchline.intel.analysis import clip

    try:
        return await asyncio.to_thread(clip, match_id, type, index, lang)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown match '{match_id}'") from exc


_autoevent_cache: dict[tuple[str, int, int], dict[str, Any]] = {}


@app.get("/api/matches/{match_id}/autoevent")
async def autoevent(
    match_id: str, from_minute: int = Query(60, ge=0, le=95), minutes: int = Query(3, ge=1, le=10)
) -> dict[str, Any]:
    """Auto-eventing from synthetic video: detect passes and ball speed from pixels, scored vs ground truth."""
    from touchline.autoevent import run

    key = (match_id, from_minute, minutes)
    if key not in _autoevent_cache:
        s = await _session(match_id)
        _autoevent_cache[key] = await asyncio.to_thread(run, s.data, from_minute, from_minute + minutes)
    return _autoevent_cache[key]


@app.get("/api/matches/{match_id}/analysis")
async def match_analysis(match_id: str) -> dict[str, Any]:
    """Whole-match offline analysis (deterministic): totals, key moments and explanations."""
    from touchline.intel.analysis import summary

    try:
        return await asyncio.to_thread(summary, match_id)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown match '{match_id}'") from exc


@app.get("/api/matches/{match_id}/facts/{fact_id}")
async def fact(match_id: str, fact_id: str) -> dict[str, Any]:
    s = await _session(match_id)
    f = s.stats.facts.get(fact_id)
    if not f:
        raise HTTPException(404, "Unknown fact")
    evs = [s.stats.by_id[e].model_dump(mode="json") for e in f.event_ids if e in s.stats.by_id]
    return {"fact": f.model_dump(mode="json"), "display": f.display(), "events": evs}


@app.get("/api/matches/{match_id}/{kind}")
async def blackboard_list(
    match_id: str,
    kind: Literal["traces", "audit", "recaps", "insights", "commentary", "tactical", "cues"],
    limit: int = 200,
) -> list[dict[str, Any]]:
    s = await _session(match_id)
    key = {"traces": "trace", "recaps": "recap", "insights": "insight", "cues": "cue"}.get(kind, kind)
    return await s.blackboard.list(key, limit)


@app.get("/api/matches/{match_id}/agents/status")
async def agent_status(match_id: str) -> dict[str, Any]:
    s = await _session(match_id)
    return {
        "agents": s.rt.agent_status(),
        "totals": s.rt.totals,
        "llm": manager.llm.provider,
        "killed": [a for a in s.rt.faults.killed_until if s.rt.faults.is_killed(a)],
        "corrupt_next": sorted(s.rt.faults.corrupt_next),
    }


@app.get("/api/agents/graph")
async def agent_graph() -> dict[str, Any]:
    return GRAPH


# ----------------------------------------------------------------------------- season & schemas


@app.get("/api/season/table")
async def season_table(matchday: int = 29) -> list[dict[str, Any]]:
    mem = get_season_memory()
    if not mem.available:
        raise HTTPException(404, "Season not generated. Run: touchline season")
    return mem.tables.get(str(matchday), [])


@app.get("/api/season/matches")
async def season_matches(limit: int = 400) -> list[dict[str, Any]]:
    p = SEASON_DIR / "matches.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()[:limit]]


@app.get("/api/schema/{name}")
async def schema(
    name: Literal["event", "overlay", "insight", "personalized", "moment", "recap", "trace", "fact"],
):
    from touchline import models

    model = {
        "event": models.MatchEvent,
        "overlay": models.OverlayCue,
        "insight": models.Insight,
        "personalized": models.PersonalizedInsight,
        "moment": models.Moment,
        "recap": models.Recap,
        "trace": models.AgentTrace,
        "fact": models.Fact,
    }[name]
    return JSONResponse(model.model_json_schema())


# ----------------------------------------------------------------------------- realtime


@app.websocket("/ws/matches/{match_id}")
async def ws_match(
    websocket: WebSocket,
    match_id: str,
    mode: str = "fan",
    lang: str = "en",
    club: str | None = None,
    player_id: str | None = None,
    frames: bool = True,
):
    await websocket.accept()
    try:
        session = await manager.get(match_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    sub = Sub(
        mode if mode in ("analyst", "fan", "club", "player") else "fan",
        lang,  # type: ignore[arg-type]
        club if club in ("home", "away") else None,
        player_id or None,
    )  # type: ignore[arg-type]
    client = Client(ws=websocket, sub=sub, wants_frames=frames)
    hub.add(match_id, client)
    await websocket.send_text(
        json.dumps(
            {
                "kind": "hello",
                "match_id": match_id,
                "t": session.t,
                "data": {"sub_key": sub.key, **session.status_dict()},
            }
        )
    )

    async def writer():
        while True:
            payload = await client.queue.get()
            await websocket.send_text(payload)

    async def reader():
        while True:
            msg = await websocket.receive_text()
            try:
                body = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if body.get("type") == "prefs":
                hub.remove(match_id, client)
                client.sub = Sub(
                    body.get("mode", "fan"),
                    body.get("lang", "en"),
                    body.get("club") or None,
                    body.get("player_id") or None,
                )
                hub.add(match_id, client)
                await websocket.send_text(
                    json.dumps(
                        {
                            "kind": "hello",
                            "match_id": match_id,
                            "t": session.t,
                            "data": {"sub_key": client.sub.key, **session.status_dict()},
                        }
                    )
                )
            elif body.get("type") == "frames":
                client.wants_frames = bool(body.get("on", True))
            elif body.get("type") == "join":
                member = session.party.join(
                    str(body.get("name", "Guest")),
                    str(body.get("provider", "guest")),
                    body.get("member_id"),
                    body.get("club"),
                )
                client.member_id = member.member_id
                await websocket.send_text(
                    json.dumps(
                        {
                            "kind": "party",
                            "match_id": match_id,
                            "t": session.t,
                            "data": {
                                "type": "welcome",
                                "me": member.public(),
                                **session.party.state(member.member_id),
                            },
                        }
                    )
                )
                await session._send("party", {"type": "presence", "members": session.party.leaderboard()})
            elif getattr(client, "member_id", None) and client.member_id in session.party.members:
                member = session.party.members[client.member_id]
                kind = body.get("type")
                if kind == "chat" and session.party.throttled(member, settings.chat_min_interval_s):
                    await websocket.send_text(
                        json.dumps(
                            {
                                "kind": "party",
                                "match_id": match_id,
                                "t": session.t,
                                "data": {"type": "blocked", "reason": "Slow down a little"},
                            }
                        )
                    )
                elif kind == "chat":
                    ok, text = session.party.screen(str(body.get("text", "")))
                    if ok and safety.enabled:
                        ok, cats = await safety.screen(text, threshold=2)
                        text = text if ok else "Message blocked by Azure AI Content Safety"
                    if ok:
                        msg = session.party.add_chat(member, text, session.minute)
                        await session._send("party", {"type": "chat", "message": msg})
                    else:
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "kind": "party",
                                    "match_id": match_id,
                                    "t": session.t,
                                    "data": {"type": "blocked", "reason": text},
                                }
                            )
                        )
                elif kind == "react" and body.get("emoji") in REACTIONS:
                    await session._send(
                        "party", {"type": "react", "emoji": body["emoji"], "member": member.public()}
                    )
                elif kind == "predict":
                    session.party.predict(member, str(body.get("pick")))
                    await session._send(
                        "party",
                        {"type": "tally", "round": session.party.round, "tally": session.party.tally()},
                    )

    tasks = [asyncio.create_task(writer()), asyncio.create_task(reader())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        hub.remove(match_id, client)
        if getattr(client, "member_id", None):
            session.party.leave(client.member_id)
            await session._send("party", {"type": "presence", "members": session.party.leaderboard()})


# ----------------------------------------------------------------------------- web app (static export)

if WEB_DIR.exists():
    app.mount("/_next", StaticFiles(directory=WEB_DIR / "_next"), name="next")

    @app.get("/{path:path}", include_in_schema=False)
    async def web(path: str):
        root = WEB_DIR.resolve()
        for c in (WEB_DIR / path, WEB_DIR / f"{path}.html", WEB_DIR / path / "index.html"):
            rc = c.resolve()
            if rc.is_file() and (root in rc.parents or rc.parent == root):
                return FileResponse(rc)
        return FileResponse(
            WEB_DIR / "404.html" if (WEB_DIR / "404.html").exists() else WEB_DIR / "index.html"
        )
