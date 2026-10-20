"""Scenario scripting: tell the simulator what kind of match to produce.

A Scenario is plain data, so it can come from the Data Studio UI, a test, or the
Scenario Director agent (an LLM turning "a comeback with a red card at 60'" into beats).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from touchline.models import Side


class Beat(BaseModel):
    minute: int = Field(ge=1, le=94)
    kind: Literal["goal", "red_card", "yellow_card", "momentum"]
    team: Side
    duration: int = Field(10, description="Minutes a momentum beat lasts")


class Scenario(BaseModel):
    tempo: float = Field(0.5, ge=0, le=1)
    chaos: float = Field(0.3, ge=0, le=1, description="Turnovers, fouls and transitions")
    beats: list[Beat] = Field(default_factory=list)
    label: str = "Open match"


PRESETS: dict[str, Scenario] = {
    "classic": Scenario(label="Classic: tight, tactical", tempo=0.5, chaos=0.3),
    "comeback": Scenario(
        label="Comeback: 0-2 down, a red card flips it",
        tempo=0.6,
        chaos=0.45,
        beats=[
            Beat(minute=18, kind="goal", team="away"),
            Beat(minute=37, kind="goal", team="away"),
            Beat(minute=52, kind="momentum", team="home", duration=30),
            Beat(minute=58, kind="red_card", team="away"),
            Beat(minute=63, kind="goal", team="home"),
            Beat(minute=74, kind="goal", team="home"),
            Beat(minute=88, kind="goal", team="home"),
        ],
    ),
    "chaos": Scenario(label="End-to-end chaos", tempo=0.85, chaos=0.85),
    "siege": Scenario(
        label="Siege: one-way traffic",
        tempo=0.55,
        chaos=0.2,
        beats=[Beat(minute=5, kind="momentum", team="home", duration=80)],
    ),
}


_NUM = re.compile(r"(\d{1,2})\s*(?:'|min|minute|’)")


def parse_scenario_text(text: str) -> Scenario:
    """Offline Scenario Director: keyword parser used when no LLM is configured."""
    t = text.lower()
    for key, preset in PRESETS.items():
        if key in t and len(t.split()) <= 3:
            return preset
    scenario = Scenario(label=text.strip()[:80] or "Custom scenario")
    if any(w in t for w in ("chaos", "wild", "end-to-end", "crazy")):
        scenario.chaos, scenario.tempo = 0.85, 0.8
    if any(w in t for w in ("tight", "cagey", "tactical", "boring")):
        scenario.chaos, scenario.tempo = 0.15, 0.35
    minutes = [int(m) for m in _NUM.findall(t)]
    away_first = "away" in t or "harbour" in t
    if "comeback" in t:
        trailing: Side = "away" if away_first else "home"
        leading: Side = "home" if trailing == "away" else "away"
        scenario.beats += [
            Beat(minute=20, kind="goal", team=leading),
            Beat(minute=40, kind="goal", team=leading),
            Beat(minute=55, kind="momentum", team=trailing, duration=30),
            Beat(minute=65, kind="goal", team=trailing),
            Beat(minute=78, kind="goal", team=trailing),
            Beat(minute=89, kind="goal", team=trailing),
        ]
    if "red" in t:
        minute = minutes[0] if minutes else 60
        offender: Side = "away" if "home" not in t else "home"
        scenario.beats.append(Beat(minute=max(1, min(minute, 90)), kind="red_card", team=offender))
    if "siege" in t or "dominat" in t:
        scenario.beats.append(Beat(minute=3, kind="momentum", team="home", duration=85))
    scenario.beats.sort(key=lambda b: b.minute)
    return scenario
