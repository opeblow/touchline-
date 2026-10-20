"""Synthetic season generator and season memory.

`generate_season()` simulates a full double round-robin (20 clubs, 38 matchdays,
380 matches) in parallel and writes:

  data/season/matches.jsonl      one line per match (result, xG, shots, possession)
  data/season/events/<id>.jsonl  full event stream per match (optional)
  data/season/players.json       per-player season totals by matchday
  data/season/table.json         league table after each matchday

The live demo match is scheduled on matchday 30, so the Memory agent knows
everything that happened in matchdays 1–29.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any

from touchline.config import ROOT
from touchline.models import EventType
from touchline.sim.league import build_league
from touchline.sim.scenario import Scenario

log = logging.getLogger(__name__)
SEASON_DIR = ROOT / "data" / "season"


def round_robin(n: int = 20) -> list[list[tuple[int, int]]]:
    """Circle method → 2*(n-1) matchdays, home/away mirrored in the second half."""
    teams = list(range(n))
    rounds = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = teams[i], teams[n - 1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rounds.append(pairs)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return rounds + [[(b, a) for a, b in rnd] for rnd in rounds]


def _simulate_one(args: tuple[int, int, int, int, bool]) -> dict[str, Any]:
    from touchline.sim.engine import simulate_match
    from touchline.stats.engine import StatsEngine

    matchday, hi, ai, seed, keep_events = args
    league = build_league()
    home, away = league[hi], league[ai]
    rng_chaos = (seed * 7919 % 100) / 100
    scenario = Scenario(tempo=0.35 + 0.3 * rng_chaos, chaos=0.15 + 0.4 * ((seed * 104729) % 100) / 100)
    data = simulate_match(
        home,
        away,
        seed=seed,
        scenario=scenario,
        matchday=matchday,
        match_id=f"s27-md{matchday:02d}-{home.code.lower()}-{away.code.lower()}",
        with_tracking=False,
    )
    stats = StatsEngine(data.meta)
    for ev in data.events:
        stats.ingest(ev)
    snap = stats.snapshot()
    players = {}
    for pid, ps in stats.pstats.items():
        if ps.touches == 0:
            continue
        players[pid] = {
            "g": ps.goals,
            "a": ps.assists,
            "xg": round(ps.xg, 3),
            "sh": ps.shots,
            "p": ps.passes,
            "pc": ps.passes_completed,
            "t": ps.tackles + ps.interceptions,
            "r": ps.rating(),
        }
    out = {
        "match_id": data.meta.match_id,
        "matchday": matchday,
        "home": home.id,
        "away": away.id,
        "score": snap["score"],
        "xg": [snap["home"]["xg"], snap["away"]["xg"]],
        "shots": [snap["home"]["shots"], snap["away"]["shots"]],
        "possession": [snap["home"]["possession"], snap["away"]["possession"]],
        "players": players,
        "goals": [
            {"minute": e.minute, "team": e.team, "player": e.player_id}
            for e in data.events
            if e.type == EventType.SHOT and e.outcome == "goal"
        ],
    }
    if keep_events:
        out["events"] = [e.model_dump(mode="json") for e in data.events]
    return out


def generate_season(
    matchdays: int = 38, workers: int | None = None, keep_events: bool = False, out_dir: Path = SEASON_DIR
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    schedule = round_robin(20)[:matchdays]
    jobs = [
        (md + 1, h, a, 1000 * (md + 1) + i, keep_events)
        for md, rnd in enumerate(schedule)
        for i, (h, a) in enumerate(rnd)
    ]
    log.info("Simulating %d matches", len(jobs))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = sorted(
            pool.map(_simulate_one, jobs, chunksize=4), key=lambda r: (r["matchday"], r["match_id"])
        )
    if keep_events:
        ev_dir = out_dir / "events"
        ev_dir.mkdir(exist_ok=True)
        for r in results:
            with (ev_dir / f"{r['match_id']}.jsonl").open("w", encoding="utf-8") as f:
                for e in r.pop("events"):
                    f.write(json.dumps(e) + "\n")
    with (out_dir / "matches.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({k: v for k, v in r.items() if k != "players"}) + "\n")
    # Per-player cumulative totals by matchday (so memory can answer "as of matchday N").
    totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "apps": 0,
            "g": 0,
            "a": 0,
            "xg": 0.0,
            "sh": 0,
            "p": 0,
            "pc": 0,
            "t": 0,
            "r_sum": 0.0,
            "by_md": {},
        }
    )
    table: dict[str, dict[str, int]] = {
        t.id: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0} for t in build_league()
    }
    tables_by_md: dict[int, list[dict[str, Any]]] = {}
    form: dict[str, list[str]] = defaultdict(list)
    for md in range(1, matchdays + 1):
        for r in (x for x in results if x["matchday"] == md):
            h, a = r["home"], r["away"]
            hg, ag = r["score"]
            for team, gf, ga in ((h, hg, ag), (a, ag, hg)):
                row = table[team]
                row["p"] += 1
                row["gf"] += gf
                row["ga"] += ga
                res = "W" if gf > ga else "D" if gf == ga else "L"
                row["w" if res == "W" else "d" if res == "D" else "l"] += 1
                row["pts"] += 3 if res == "W" else 1 if res == "D" else 0
                form[team].append(res)
            for pid, s in r["players"].items():
                t = totals[pid]
                t["apps"] += 1
                for k in ("g", "a", "sh", "p", "pc", "t"):
                    t[k] += s[k]
                t["xg"] = round(t["xg"] + s["xg"], 3)
                t["r_sum"] += s["r"]
                t["by_md"][md] = {"g": t["g"], "a": t["a"], "apps": t["apps"]}
        ordered = sorted(
            table.items(), key=lambda kv: (-kv[1]["pts"], -(kv[1]["gf"] - kv[1]["ga"]), -kv[1]["gf"])
        )
        tables_by_md[md] = [
            {"pos": i + 1, "team": tid, **row, "form": "".join(form[tid][-5:])}
            for i, (tid, row) in enumerate(ordered)
        ]
    (out_dir / "players.json").write_text(json.dumps(totals), encoding="utf-8")
    (out_dir / "table.json").write_text(json.dumps(tables_by_md), encoding="utf-8")
    (out_dir / "README.md").write_text(
        "# Touchline synthetic season 2026/27\n\n"
        f"{len(results)} simulated matches across {matchdays} matchdays of a fictional 20-club league.\n"
        "All clubs and players are invented. Generated by `touchline season`.\n",
        encoding="utf-8",
    )
    return out_dir


class SeasonMemory:
    """Local season memory (Azure AI Search provides the same interface in the cloud)."""

    def __init__(self, directory: Path = SEASON_DIR) -> None:
        self.available = (directory / "players.json").exists()
        self.players: dict[str, Any] = {}
        self.tables: dict[str, Any] = {}
        if self.available:
            self.players = json.loads((directory / "players.json").read_text(encoding="utf-8"))
            self.tables = json.loads((directory / "table.json").read_text(encoding="utf-8"))

    def player_as_of(self, player_id: str, matchday: int) -> dict[str, Any] | None:
        p = self.players.get(player_id)
        if not p:
            return None
        mds = [int(m) for m in p["by_md"] if int(m) <= matchday]
        if not mds:
            return {"g": 0, "a": 0, "apps": 0}
        return p["by_md"][str(max(mds))]

    def team_as_of(self, team_id: str, matchday: int) -> dict[str, Any] | None:
        table = self.tables.get(str(matchday))
        if not table:
            return None
        return next((row for row in table if row["team"] == team_id), None)


@lru_cache(maxsize=1)
def get_season_memory() -> SeasonMemory:
    return SeasonMemory()
