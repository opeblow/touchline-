"""Match catalog and on-disk cache of generated matches (events + tracking)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from touchline.config import get_settings
from touchline.models import MatchEvent, MatchMeta
from touchline.sim.engine import MatchData, simulate_match
from touchline.sim.league import get_team
from touchline.sim.scenario import PRESETS, Scenario
from touchline.sim.tracking import Tracking

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogEntry:
    match_id: str
    home: str
    away: str
    seed: int
    preset: str
    title: str
    blurb: str


FEATURED: list[CatalogEntry] = [
    CatalogEntry(
        "demo",
        "nbk",
        "hbc",
        7,
        "comeback",
        "Northbank v Harbour City",
        "Bottom of the table against the leaders. 0-2 at the break, a red card, and a comeback.",
    ),
    CatalogEntry(
        "classic",
        "kmu",
        "rca",
        11,
        "classic",
        "Kingsmere United v Redcliff Athletic",
        "A tight, tactical match between two pressing sides.",
    ),
    CatalogEntry(
        "chaos",
        "stb",
        "crb",
        23,
        "chaos",
        "Stonebridge v Corran Bay",
        "End-to-end chaos: turnovers, cards and transitions.",
    ),
]


def _paths(match_id: str) -> tuple[Path, Path, Path]:
    d = get_settings().cache_dir / "matches"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{match_id}.meta.json", d / f"{match_id}.events.jsonl", d / f"{match_id}.tracking.npz"


def save_match(data: MatchData) -> None:
    meta_p, ev_p, tr_p = _paths(data.meta.match_id)
    meta_p.write_text(data.meta.model_dump_json(), encoding="utf-8")
    with ev_p.open("w", encoding="utf-8") as f:
        for e in data.events:
            f.write(e.model_dump_json() + "\n")
    if data.tracking is not None:
        tr = data.tracking
        np.savez_compressed(
            tr_p,
            hz=tr.hz,
            times=tr.times,
            ball=tr.ball,
            pos=tr.pos,
            changes=json.dumps(tr.roster_changes),
            initial=json.dumps(tr.initial_ids),
        )


def load_match(match_id: str) -> MatchData | None:
    meta_p, ev_p, tr_p = _paths(match_id)
    if not (meta_p.exists() and ev_p.exists()):
        return None
    meta = MatchMeta.model_validate_json(meta_p.read_text(encoding="utf-8"))
    events = [
        MatchEvent.model_validate_json(line) for line in ev_p.read_text(encoding="utf-8").splitlines() if line
    ]
    tracking = None
    if tr_p.exists():
        z = np.load(tr_p)
        tracking = Tracking(
            hz=float(z["hz"]),
            times=z["times"],
            ball=z["ball"],
            pos=z["pos"],
            roster_changes=[tuple(x) for x in json.loads(str(z["changes"]))],  # type: ignore[misc]
            initial_ids=json.loads(str(z["initial"])),
        )
    return MatchData(meta=meta, events=events, tracking=tracking)


def generate(
    match_id: str, home: str, away: str, seed: int, scenario: Scenario, matchday: int = 30
) -> MatchData:
    cached = load_match(match_id)
    if cached is not None:
        return cached
    log.info("Generating match %s (%s v %s, seed %s)", match_id, home, away, seed)
    data = simulate_match(
        get_team(home), get_team(away), seed=seed, scenario=scenario, match_id=match_id, matchday=matchday
    )
    save_match(data)
    return data


def get_featured(match_id: str) -> MatchData:
    entry = next((e for e in FEATURED if e.match_id == match_id), None)
    if entry is None:
        cached = load_match(match_id)
        if cached is None:
            raise KeyError(match_id)
        return cached
    return generate(entry.match_id, entry.home, entry.away, entry.seed, PRESETS[entry.preset])
