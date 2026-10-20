"""Typed contracts shared by every service.

These models are the source of truth. JSON Schemas in /data/schema and the
TypeScript types in /web/lib/types.ts are generated from or kept in sync with them.

Pitch coordinates: metres, x in [0, 105], y in [0, 68].
The home team always attacks towards x = 105 (normalised, like most event feeds).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0

Side = Literal["home", "away"]


# --------------------------------------------------------------------------- roster


class Player(BaseModel):
    id: str
    name: str
    short_name: str
    number: int
    position: str  # GK, CB, FB, DM, CM, AM, W, ST
    pace: float = Field(ge=0, le=1)
    passing: float = Field(ge=0, le=1)
    finishing: float = Field(ge=0, le=1)
    defending: float = Field(ge=0, le=1)
    stamina: float = Field(ge=0, le=1)
    nationality: str = "—"


class TeamStyle(BaseModel):
    """How a team likes to play. Drives the simulator."""

    press: float = Field(0.5, ge=0, le=1, description="Pressing intensity")
    possession: float = Field(0.5, ge=0, le=1, description="Preference for short build-up")
    directness: float = Field(0.5, ge=0, le=1, description="Preference for long/forward passes")
    width: float = Field(0.5, ge=0, le=1)
    tempo: float = Field(0.5, ge=0, le=1)
    formation: str = "4-3-3"


class Team(BaseModel):
    id: str
    name: str
    short_name: str
    code: str  # 3 letters
    city: str
    primary: str  # hex colour
    secondary: str
    style: TeamStyle
    players: list[Player]  # first 11 = starters, rest = bench


# --------------------------------------------------------------------------- events


class EventType(StrEnum):
    KICKOFF = "kickoff"
    PASS = "pass"
    CARRY = "carry"
    DRIBBLE = "dribble"
    PRESSURE = "pressure"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    CLEARANCE = "clearance"
    SHOT = "shot"
    SAVE = "save"
    FOUL = "foul"
    CARD = "card"
    SUBSTITUTION = "substitution"
    BALL_OUT = "ball_out"
    CORNER = "corner"
    THROW_IN = "throw_in"
    GOAL_KICK = "goal_kick"
    FREE_KICK = "free_kick"
    HALF_END = "half_end"
    MATCH_END = "match_end"


class MatchEvent(BaseModel):
    """One synthetic match event, as it would arrive from a live data feed."""

    event_id: str
    match_id: str
    seq: int = Field(description="Monotonic order within the match")
    possession_id: int = Field(description="Possession chain this event belongs to")
    t: float = Field(
        description="Seconds of match clock since kickoff of first half (2nd half starts at 2700)"
    )
    period: Literal[1, 2]
    minute: int
    second: int
    duration: float = 0.0
    type: EventType
    team: Side
    player_id: str | None = None
    recipient_id: str | None = None
    x: float = 0.0
    y: float = 0.0
    end_x: float | None = None
    end_y: float | None = None
    outcome: str | None = None  # complete|incomplete|goal|saved|off_target|blocked|won|lost|yellow|red
    pass_type: str | None = None  # short|long|through|cross|switch|back
    body_part: str | None = None  # foot|head
    under_pressure: bool = False
    pressure_player_id: str | None = None
    opponents_in_lane: int = 0
    speed_kmh: float | None = Field(None, description="Ball speed for passes and shots")
    extra: dict[str, Any] = Field(default_factory=dict)


class TrackingFrame(BaseModel):
    """Positions at one instant. 5 Hz in the simulator."""

    t: float
    ball: tuple[float, float]
    home: list[tuple[float, float]]  # index aligned with on-pitch player ids
    away: list[tuple[float, float]]
    home_ids: list[str]
    away_ids: list[str]


class MatchMeta(BaseModel):
    match_id: str
    competition: str = "Touchline Synthetic League"
    season: str = "2026/27"
    matchday: int = 1
    venue: str
    kickoff_iso: str
    seed: int
    home: Team
    away: Team
    scenario: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- intelligence


class Fact(BaseModel):
    """A single verifiable number. The only way numbers reach an LLM."""

    fact_id: str
    kind: str  # e.g. xg, shot_speed, pass_difficulty, possession, ppda, momentum
    label: str
    value: float | int | str
    unit: str = ""
    team: Side | None = None
    player_id: str | None = None
    minute: int | None = None
    event_ids: list[str] = Field(default_factory=list)

    def display(self) -> str:
        return format_value(self.value, self.unit, self.kind)


XG_KINDS = {"xg", "xg_total", "xg_diff", "xg_chain"}


def format_value(value: float | int | str, unit: str = "", kind: str = "") -> str:
    """Single formatting rule used by agents, templates and the Guardian."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, int) or float(value).is_integer() and kind not in XG_KINDS:
        text = str(int(value))
    elif kind in XG_KINDS:
        text = f"{value:.2f}"
    elif abs(value) >= 10:
        text = f"{value:.0f}"
    else:
        text = f"{value:.1f}"
    if not unit:
        return text
    return f"{text}{unit}" if unit in {"%", "'"} else f"{text} {unit}"


class MomentType(StrEnum):
    GOAL = "goal"
    BIG_CHANCE = "big_chance"
    SHOT_ON_TARGET = "shot_on_target"
    SAVE = "save"
    RED_CARD = "red_card"
    YELLOW_CARD = "yellow_card"
    MOMENTUM_SWING = "momentum_swing"
    PRESSURE_SHIFT = "pressure_shift"
    CHAOS_SPIKE = "chaos_spike"
    SPRINT = "sprint"
    PASS_OF_MATCH = "pass_of_match"
    MILESTONE = "milestone"
    SUBSTITUTION = "substitution"
    PHASE = "phase"  # half time / full time


class Moment(BaseModel):
    moment_id: str
    match_id: str
    type: MomentType
    minute: int
    t: float
    team: Side | None = None
    player_id: str | None = None
    importance: int = Field(ge=0, le=100)
    title: str
    facts: list[Fact]
    event_ids: list[str] = Field(default_factory=list)


Mode = Literal["analyst", "fan", "club", "player"]


class Insight(BaseModel):
    """Canonical 'why it matters' explanation. Every number cites a fact."""

    insight_id: str
    moment_id: str
    match_id: str
    text: str
    cited_fact_ids: list[str]
    agent: str = "explainer"
    attempts: int = 1
    model: str = "offline"
    fallback: bool = False


class PersonalizedInsight(BaseModel):
    insight_id: str
    moment_id: str
    mode: Mode
    lang: str
    headline: str
    text: str
    cited_fact_ids: list[str]
    focus_team: Side | None = None
    focus_player_id: str | None = None


class CommentaryLine(BaseModel):
    line_id: str
    match_id: str
    t: float
    minute: int
    text: str
    tone: Literal["calm", "build", "excited", "somber"] = "calm"
    lang: str = "en"


class OverlayCue(BaseModel):
    """Timed, machine-readable instruction for a graphics renderer."""

    cue_id: str
    match_id: str
    template: Literal[
        "score_bug",
        "player_tag",
        "speed_badge",
        "shot_speed",
        "xg_popup",
        "pass_rating",
        "moment_card",
        "momentum_bar",
        "lower_third",
        "stat_compare",
    ]
    t_in: float
    t_out: float
    priority: int = Field(50, ge=0, le=100)
    data: dict[str, Any]
    moment_id: str | None = None


class Verdict(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    checked_numbers: list[str] = Field(default_factory=list)
    checked_names: list[str] = Field(default_factory=list)


class Recap(BaseModel):
    recap_id: str
    match_id: str
    phase: Literal["half_time", "full_time"]
    lang: str = "en"
    headline: str
    standfirst: str
    body_md: str
    key_moments: list[str]  # moment ids
    player_of_match: str | None = None
    potm_reason: str | None = None
    cited_fact_ids: list[str] = Field(default_factory=list)
    model: str = "offline"


class TacticalShift(BaseModel):
    shift_id: str
    match_id: str
    window: tuple[int, int]  # minutes
    team: Side
    kind: str  # press_up, press_drop, tempo_up, tempo_down, control, chaos
    summary: str
    facts: list[Fact]


class AgentTrace(BaseModel):
    """One unit of agent work, shown in the Control Room and sent to App Insights."""

    trace_id: str
    match_id: str
    agent: str
    action: str
    status: Literal["ok", "retry", "rejected", "fallback", "error", "skipped"]
    started_at: float
    latency_ms: float
    input_ref: str | None = None
    output_ref: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = "offline"
    detail: str = ""
    handoff_to: str | None = None


class Preferences(BaseModel):
    mode: Mode = "fan"
    lang: str = "en"
    club: Side | None = None
    player_id: str | None = None
    metric: str | None = None  # e.g. "xg", "pass_difficulty", "top_speed"


# --------------------------------------------------------------------------- wire


class WireMessage(BaseModel):
    """Envelope for everything pushed to clients."""

    kind: Literal[
        "hello",
        "frame",
        "event",
        "stats",
        "moment",
        "insight",
        "personalized",
        "commentary",
        "cue",
        "trace",
        "recap",
        "tactical",
        "status",
        "party",
        "review",
    ]
    match_id: str
    t: float
    data: dict[str, Any]
