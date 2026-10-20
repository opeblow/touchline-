"""Incremental stats engine.

Feed it events in order with `ingest()`. It keeps team, player, physical and
rhythm statistics up to date, registers every number it produces as a `Fact`
with a stable id, and returns `Trigger`s when something crosses a threshold
(sprint speed, distance milestone, pass count milestone…).

Nothing in here calls an LLM. Every number on screen comes from this module.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from touchline.models import EventType, Fact, MatchEvent, MatchMeta, Player, Side
from touchline.sim.shape import to_attacking
from touchline.stats.models import expected_goals, pass_difficulty, threat_value

SPRINT_KMH = 25.2
TOP_SPEED_ALERT_KMH = 32.0
DISTANCE_MILESTONES_KM = (5.0, 10.0)
PASS_MILESTONES = (50, 75, 100)
BIG_CHANCE_XG = 0.3


def other(side: Side) -> Side:
    return "away" if side == "home" else "home"


@dataclass
class Trigger:
    kind: str  # sprint, distance_milestone, pass_milestone, first_goal, brace, hat_trick
    t: float
    minute: int
    team: Side
    player_id: str
    facts: list[Fact]
    event_ids: list[str] = field(default_factory=list)


@dataclass
class PlayerStats:
    player_id: str
    side: Side
    passes: int = 0
    passes_completed: int = 0
    difficulty_sum: float = 0.0
    hardest_completed: int = 0
    hardest_completed_event: str | None = None
    progressive_passes: int = 0
    key_passes: int = 0
    assists: int = 0
    shots: int = 0
    shots_on_target: int = 0
    goals: int = 0
    xg: float = 0.0
    tackles: int = 0
    interceptions: int = 0
    pressures: int = 0
    dribbles_won: int = 0
    fouls: int = 0
    yellow: int = 0
    red: int = 0
    touches: int = 0
    distance_m: float = 0.0
    top_speed_kmh: float = 0.0
    sprints: int = 0
    minutes_on: float = 0.0
    on_pitch: bool = True

    @property
    def pass_accuracy(self) -> float:
        return 100.0 * self.passes_completed / self.passes if self.passes else 0.0

    @property
    def avg_difficulty(self) -> float:
        return self.difficulty_sum / self.passes if self.passes else 0.0

    def rating(self) -> float:
        r = 6.0
        r += 0.9 * self.goals + 0.6 * self.assists + 0.15 * self.key_passes
        r += 0.3 * self.xg + 0.025 * self.progressive_passes
        r += 0.07 * (self.tackles + self.interceptions) + 0.06 * self.dribbles_won
        r += 0.015 * (self.pass_accuracy - 82) if self.passes >= 15 else 0
        r -= 0.3 * self.yellow + 1.5 * self.red
        return round(min(max(r, 3.0), 10.0), 1)


@dataclass
class TeamStats:
    side: Side
    passes: int = 0
    passes_completed: int = 0
    final_third_passes: int = 0
    shots: int = 0
    shots_on_target: int = 0
    goals: int = 0
    xg: float = 0.0
    big_chances: int = 0
    corners: int = 0
    fouls: int = 0
    yellow: int = 0
    red: int = 0
    tackles: int = 0
    interceptions: int = 0
    pressures: int = 0
    opp_passes_in_build_up: int = 0  # for PPDA (opponent passes in their own 60%)
    def_actions_high: int = 0  # our tackles/interceptions/fouls in the opponent's 60%
    threat: float = 0.0

    @property
    def pass_accuracy(self) -> float:
        return 100.0 * self.passes_completed / self.passes if self.passes else 0.0

    @property
    def ppda(self) -> float:
        return self.opp_passes_in_build_up / self.def_actions_high if self.def_actions_high else 0.0


@dataclass
class EventMetrics:
    event_id: str
    distance_m: float | None = None
    forward_m: float | None = None
    difficulty: int | None = None
    xg: float | None = None
    ball_speed_kmh: float | None = None
    threat_added: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None and k != "event_id"}


class StatsEngine:
    def __init__(self, meta: MatchMeta, tracking=None) -> None:
        self.meta = meta
        self.tracking = tracking
        self.players: dict[str, Player] = {p.id: p for t in (meta.home, meta.away) for p in t.players}
        self.player_side: dict[str, Side] = {p.id: "home" for p in meta.home.players} | {
            p.id: "away" for p in meta.away.players
        }
        self.pstats: dict[str, PlayerStats] = {
            pid: PlayerStats(pid, side) for pid, side in self.player_side.items()
        }
        for p in meta.home.players[11:] + meta.away.players[11:]:
            self.pstats[p.id].on_pitch = False
        self.tstats: dict[Side, TeamStats] = {"home": TeamStats("home"), "away": TeamStats("away")}
        self.facts: dict[str, Fact] = {}
        self.event_metrics: dict[str, EventMetrics] = {}
        self.events: list[MatchEvent] = []
        self.by_id: dict[str, MatchEvent] = {}
        self.score: dict[Side, int] = {"home": 0, "away": 0}
        self.t = 0.0
        self.minute = 0
        self.period = 1
        self._fact_seq = 0
        self._last_possession: tuple[int, Side] | None = None
        self.possessions: dict[Side, int] = {"home": 0, "away": 0}
        self.turnovers: deque[tuple[float, Side]] = deque()
        self.window_events: deque[MatchEvent] = deque()
        self.momentum_series: list[tuple[float, float]] = []  # (t, -100..100, + = home)
        self._mom_value = 0.0
        self._mom_t = 0.0
        self.threat_minute: dict[int, dict[Side, float]] = defaultdict(lambda: {"home": 0.0, "away": 0.0})
        self.chaos_series: list[tuple[float, float, Side | None]] = []
        self._last_chain_pass: dict[int, MatchEvent] = {}
        self._frame_ptr = 0
        self._dist_milestones: dict[str, int] = defaultdict(int)
        self._sprinting: dict[int, float] = {}
        self._speed_alerted: set[str] = set()
        self._match_top_speed = 0.0
        self._dist_first: set[float] = set()
        self._max_deficit: dict[Side, int] = {"home": 0, "away": 0}
        self._run = np.zeros(22, dtype=int)
        self._slot_ids: list[str | None] = tracking.initial_ids[:] if tracking is not None else []
        self._roster_ptr = 0

    # ------------------------------------------------------------------ facts

    def fact(
        self,
        kind: str,
        label: str,
        value: float | int | str,
        unit: str = "",
        *,
        team: Side | None = None,
        player_id: str | None = None,
        event_ids: list[str] | None = None,
        minute: int | None = None,
    ) -> Fact:
        self._fact_seq += 1
        if isinstance(value, float):
            value = round(value, 3 if kind.startswith("xg") else 1)
        f = Fact(
            fact_id=f"F{self._fact_seq}",
            kind=kind,
            label=label,
            value=value,
            unit=unit,
            team=team,
            player_id=player_id,
            minute=self.minute if minute is None else minute,
            event_ids=event_ids or [],
        )
        self.facts[f.fact_id] = f
        return f

    def team_name(self, side: Side) -> str:
        return (self.meta.home if side == "home" else self.meta.away).short_name

    def player_name(self, pid: str | None) -> str:
        return self.players[pid].name if pid and pid in self.players else "Unknown"

    # ------------------------------------------------------------------ physical (tracking)

    def _advance_tracking(self, t: float) -> list[Trigger]:
        tr = self.tracking
        if tr is None:
            return []
        triggers: list[Trigger] = []
        end = tr.index_at(t)
        if end <= self._frame_ptr:
            return []
        fi = self._frame_ptr + 1  # frames up to _frame_ptr are already counted
        while fi <= end:
            while self._roster_ptr < len(tr.roster_changes) and tr.roster_changes[self._roster_ptr][0] <= fi:
                _, slot, pid = tr.roster_changes[self._roster_ptr]
                self._slot_ids[slot] = pid
                self._run[slot] = 0
                self._roster_ptr += 1
            nxt = (
                tr.roster_changes[self._roster_ptr][0]
                if self._roster_ptr < len(tr.roster_changes)
                else end + 1
            )
            stop = min(end, nxt - 1)
            triggers += self._physical_chunk(fi, stop)
            fi = stop + 1
        self._frame_ptr = end
        return triggers

    def _physical_chunk(self, fi: int, stop: int) -> list[Trigger]:
        """Vectorised distance / speed / sprint update for frames fi..stop (constant roster)."""
        tr = self.tracking
        seg = tr.pos[fi - 1 : stop + 1]
        step = np.linalg.norm(np.diff(seg, axis=0), axis=2)  # (k, 22)
        step = np.where(np.isfinite(step) & (step <= 3.0), step, 0.0)  # drop teleports (subs entering)
        speed = step * tr.hz * 3.6
        k = step.shape[0]
        # Sprint = speed ≥ 25.2 km/h held for ≥ 1 s. Run-length per slot, carried across chunks.
        above = speed >= SPRINT_KMH
        idx = np.arange(k)[:, None]
        last_zero = np.maximum.accumulate(np.where(above, -1, idx), axis=0)
        run = np.where(last_zero == -1, idx + 1 + self._run[None, :], idx - last_zero)
        run = np.where(above, run, 0)
        need = int(tr.hz)  # frames in one second
        new_sprints = (run == need).sum(axis=0)
        self._run = run[-1].copy()
        dist = step.sum(axis=0)
        vmax = speed.max(axis=0)
        argv = speed.argmax(axis=0)
        triggers: list[Trigger] = []
        for slot, pid in enumerate(self._slot_ids):
            if pid is None:
                continue
            ps = self.pstats[pid]
            ps.distance_m += float(dist[slot])
            ps.sprints += int(new_sprints[slot])
            v = float(vmax[slot])
            if v > ps.top_speed_kmh:
                ps.top_speed_kmh = v
            side = self.player_side[pid]
            first_time = v >= TOP_SPEED_ALERT_KMH and pid not in self._speed_alerted and self.minute > 2
            record = v >= TOP_SPEED_ALERT_KMH and v > self._match_top_speed + 0.3 and self.minute > 2
            if v > self._match_top_speed:
                self._match_top_speed = v
            if first_time or record:
                self._speed_alerted.add(pid)
                f = self.fact(
                    "top_speed",
                    f"{self.player_name(pid)} top speed",
                    round(v, 1),
                    "km/h",
                    team=side,
                    player_id=pid,
                )
                triggers.append(
                    Trigger("sprint", float(tr.times[fi + int(argv[slot])]), self.minute, side, pid, [f])
                )
            km = ps.distance_m / 1000
            for mark in DISTANCE_MILESTONES_KM:
                if km >= mark and mark not in self._dist_first:
                    self._dist_first.add(mark)
                    f = self.fact(
                        "distance",
                        f"{self.player_name(pid)} distance covered",
                        mark,
                        "km",
                        team=side,
                        player_id=pid,
                    )
                    triggers.append(
                        Trigger("distance_milestone", float(tr.times[stop]), self.minute, side, pid, [f])
                    )
        return triggers

    def measured_ball_speed(self, ev: MatchEvent) -> float | None:
        """Average ball speed over the flight: path length / flight time (from ball trajectory)."""
        if ev.end_x is None or ev.end_y is None or ev.duration <= 0:
            return ev.speed_kmh
        dist = math.hypot(ev.end_x - ev.x, ev.end_y - ev.y)
        return round(dist / ev.duration * 3.6, 1)

    # ------------------------------------------------------------------ ingest

    def ingest(self, ev: MatchEvent) -> list[Trigger]:
        self.events.append(ev)
        self.by_id[ev.event_id] = ev
        self.t = ev.t
        self.minute = ev.minute
        self.period = ev.period
        triggers = self._advance_tracking(ev.t)
        side, opp = ev.team, other(ev.team)
        ts, os_ = self.tstats[side], self.tstats[opp]
        ps = self.pstats.get(ev.player_id) if ev.player_id else None
        m = EventMetrics(ev.event_id)
        ax, ay = to_attacking(ev.x, ev.y, side)

        # possession tracking
        if ev.type in {EventType.PASS, EventType.CARRY, EventType.SHOT, EventType.DRIBBLE}:
            key = (ev.possession_id, side)
            if self._last_possession != key:
                if self._last_possession is not None and self._last_possession[1] != side:
                    self.turnovers.append((ev.t, side))
                self._last_possession = key
                self.possessions[side] += 1

        if ps and ev.type not in {EventType.SUBSTITUTION, EventType.CARD, EventType.FOUL, EventType.PRESSURE}:
            ps.touches += 1

        if ev.type == EventType.PASS:
            eax, eay = to_attacking(ev.end_x or ev.x, ev.end_y or ev.y, side)
            dist = math.hypot(eax - ax, eay - ay)
            fwd = eax - ax
            diff = pass_difficulty(
                dist,
                fwd,
                under_pressure=ev.under_pressure,
                opponents_in_lane=ev.opponents_in_lane,
                pass_type=ev.pass_type,
            )
            m.distance_m, m.forward_m, m.difficulty = round(dist, 1), round(fwd, 1), diff
            m.ball_speed_kmh = self.measured_ball_speed(ev)
            ts.passes += 1
            if ps:
                ps.passes += 1
                ps.difficulty_sum += diff
            if ax < 63:
                os_.opp_passes_in_build_up += 1
            complete = ev.outcome == "complete"
            if complete:
                ts.passes_completed += 1
                if eax > 70:
                    ts.final_third_passes += 1
                gain = max(threat_value(eax, eay) - threat_value(ax, ay), 0.0)
                m.threat_added = round(gain, 4)
                self._add_threat(side, gain, ev.t)
                if ps:
                    ps.passes_completed += 1
                    if fwd >= 10 and eax > 52:
                        ps.progressive_passes += 1
                    if diff > ps.hardest_completed:
                        ps.hardest_completed = diff
                        ps.hardest_completed_event = ev.event_id
                self._last_chain_pass[ev.possession_id] = ev
                if ps and ps.passes in PASS_MILESTONES:
                    f = self.fact(
                        "passes",
                        f"{self.player_name(ev.player_id)} passes",
                        ps.passes,
                        team=side,
                        player_id=ev.player_id,
                        event_ids=[ev.event_id],
                    )
                    f2 = self.fact(
                        "pass_accuracy",
                        f"{self.player_name(ev.player_id)} pass accuracy",
                        round(ps.pass_accuracy),
                        "%",
                        team=side,
                        player_id=ev.player_id,
                    )
                    triggers.append(
                        Trigger(
                            "pass_milestone",
                            ev.t,
                            ev.minute,
                            side,
                            ev.player_id or "",
                            [f, f2],
                            [ev.event_id],
                        )
                    )

        elif ev.type == EventType.SHOT:
            header = ev.body_part == "head"
            assist = ev.extra.get("assist_type")
            xg = expected_goals(ax, ay, header=header, under_pressure=ev.under_pressure, assisted_by=assist)
            m.xg = xg
            m.distance_m = round(math.hypot(105 - ax, 34 - ay), 1)
            m.ball_speed_kmh = self.measured_ball_speed(ev)
            ts.shots += 1
            ts.xg += xg
            if xg >= BIG_CHANCE_XG:
                ts.big_chances += 1
            self._add_threat(side, xg * 2.0, ev.t)
            on_target = ev.outcome in {"goal", "saved"}
            if on_target:
                ts.shots_on_target += 1
            if ps:
                ps.shots += 1
                ps.xg += xg
                ps.shots_on_target += on_target
            last = self._last_chain_pass.get(ev.possession_id)
            if last and last.recipient_id == ev.player_id and last.player_id in self.pstats:
                self.pstats[last.player_id].key_passes += 1
            if ev.outcome == "goal":
                ts.goals += 1
                self.score[side] += 1
                deficit = self.score[opp] - self.score[side]
                self._max_deficit[opp] = max(self._max_deficit.get(opp, 0), -deficit)
                if ps:
                    ps.goals += 1
                    if ps.goals in (1, 2, 3):
                        kind = {1: "first_goal", 2: "brace", 3: "hat_trick"}[ps.goals]
                        f = self.fact(
                            "player_goals",
                            f"{self.player_name(ev.player_id)} goals",
                            ps.goals,
                            team=side,
                            player_id=ev.player_id,
                            event_ids=[ev.event_id],
                        )
                        triggers.append(
                            Trigger(kind, ev.t, ev.minute, side, ev.player_id or "", [f], [ev.event_id])
                        )
                if last and last.recipient_id == ev.player_id and last.player_id in self.pstats:
                    self.pstats[last.player_id].assists += 1
                    ev.extra.setdefault("assist_by", last.player_id)

        elif ev.type == EventType.TACKLE:
            ts.tackles += 1
            if ps:
                ps.tackles += 1
            if ax > 42:
                ts.def_actions_high += 1
        elif ev.type == EventType.INTERCEPTION:
            ts.interceptions += 1
            if ps:
                ps.interceptions += 1
            if ax > 42:
                ts.def_actions_high += 1
        elif ev.type == EventType.FOUL:
            ts.fouls += 1
            if ps:
                ps.fouls += 1
            if ax > 42:
                ts.def_actions_high += 1
        elif ev.type == EventType.PRESSURE:
            ts.pressures += 1
            if ps:
                ps.pressures += 1
        elif ev.type == EventType.DRIBBLE and ev.outcome == "won" and ps:
            ps.dribbles_won += 1
        elif ev.type == EventType.CORNER:
            ts.corners += 1
        elif ev.type == EventType.CARD:
            if ev.outcome == "yellow":
                ts.yellow += 1
                if ps:
                    ps.yellow += 1
            else:
                ts.red += 1
                if ps:
                    ps.red += 1
                    ps.on_pitch = False
        elif ev.type == EventType.SUBSTITUTION:
            out_id, in_id = ev.extra.get("player_out"), ev.extra.get("player_in")
            if out_id in self.pstats:
                self.pstats[out_id].on_pitch = False
            if in_id in self.pstats:
                self.pstats[in_id].on_pitch = True
        elif ev.type == EventType.CARRY:
            eax, eay = to_attacking(ev.end_x or ev.x, ev.end_y or ev.y, side)
            gain = max(threat_value(eax, eay) - threat_value(ax, ay), 0.0)
            m.threat_added = round(gain, 4)
            m.distance_m = round(math.hypot(eax - ax, eay - ay), 1)
            self._add_threat(side, gain, ev.t)

        self.event_metrics[ev.event_id] = m
        self.window_events.append(ev)
        while self.window_events and self.window_events[0].t < ev.t - 300:
            self.window_events.popleft()
        while self.turnovers and self.turnovers[0][0] < ev.t - 300:
            self.turnovers.popleft()
        self._decay_momentum(ev.t)
        if not self.chaos_series or ev.t - self.chaos_series[-1][0] >= 60:
            idx, ctrl = self.chaos_index()
            self.chaos_series.append((ev.t, idx, ctrl))
        return triggers

    # ------------------------------------------------------------------ rhythm metrics

    def _add_threat(self, side: Side, value: float, t: float) -> None:
        self._decay_momentum(t)
        self.tstats[side].threat += value
        self.threat_minute[self.minute][side] += value
        self._mom_value += value if side == "home" else -value

    def _decay_momentum(self, t: float) -> None:
        dt = max(t - self._mom_t, 0.0)
        self._mom_value *= 0.5 ** (dt / 150.0)  # 2.5-minute half-life
        self._mom_t = t
        val = 100 * math.tanh(self._mom_value / 1.0)
        if not self.momentum_series or t - self.momentum_series[-1][0] >= 15:
            self.momentum_series.append((round(t, 1), round(val, 1)))

    @property
    def momentum(self) -> float:
        return round(100 * math.tanh(self._mom_value / 1.0), 1)

    def chaos_index(self) -> tuple[float, Side | None]:
        """0 = total control, 100 = chaos. Over the last 5 minutes of play.

        Blends turnover rate, duel rate and possession-chain length. Also returns the
        side in control (more completed passes in the window), if any.
        """
        evs = list(self.window_events)
        if len(evs) < 10:
            return 35.0, None
        span = max((evs[-1].t - evs[0].t) / 60, 1.0)
        turnovers_pm = len(self.turnovers) / span
        duels_pm = (
            sum(
                e.type in {EventType.TACKLE, EventType.FOUL, EventType.DRIBBLE, EventType.INTERCEPTION}
                for e in evs
            )
            / span
        )
        passes = [e for e in evs if e.type == EventType.PASS]
        chains = {e.possession_id for e in passes} or {0}
        chain_len = len(passes) / len(chains)

        def norm(v: float, lo: float, hi: float) -> float:
            return min(max((v - lo) / (hi - lo), 0.0), 1.0)

        idx = 100 * (
            0.45 * norm(turnovers_pm, 1.0, 3.2)
            + 0.30 * norm(duels_pm, 0.4, 2.4)
            + 0.25 * (1 - norm(chain_len, 2.0, 7.0))
        )
        comp = {s: sum(e.outcome == "complete" and e.team == s for e in passes) for s in ("home", "away")}
        ctrl: Side | None = None
        if comp["home"] >= 1.4 * max(comp["away"], 1):
            ctrl = "home"
        elif comp["away"] >= 1.4 * max(comp["home"], 1):
            ctrl = "away"
        return round(idx, 1), ctrl

    def window_stats(self, side: Side, seconds: float = 600) -> dict[str, float]:
        evs = [e for e in self.events if e.t >= self.t - seconds]
        opp = other(side)
        own_passes = [e for e in evs if e.type == EventType.PASS and e.team == side]
        opp_build = sum(
            1
            for e in evs
            if e.type == EventType.PASS and e.team == opp and to_attacking(e.x, e.y, opp)[0] < 63
        )
        def_high = sum(
            1
            for e in evs
            if e.team == side
            and e.type in {EventType.TACKLE, EventType.INTERCEPTION, EventType.FOUL}
            and to_attacking(e.x, e.y, side)[0] > 42
        )
        total_passes = sum(1 for e in evs if e.type == EventType.PASS)
        return {
            "possession": 100 * len(own_passes) / total_passes if total_passes else 50.0,
            "ppda": opp_build / def_high if def_high else float(opp_build) if opp_build else 0.0,
            "passes_per_min": len(own_passes) / max(seconds / 60, 1),
            "pass_accuracy": 100 * sum(e.outcome == "complete" for e in own_passes) / len(own_passes)
            if own_passes
            else 0.0,
            "shots": sum(1 for e in evs if e.type == EventType.SHOT and e.team == side),
            "xg": sum(
                (self.event_metrics[e.event_id].xg or 0)
                for e in evs
                if e.type == EventType.SHOT and e.team == side
            ),
        }

    # ------------------------------------------------------------------ snapshot

    def possession_pct(self) -> dict[Side, float]:
        total = self.tstats["home"].passes + self.tstats["away"].passes
        if not total:
            return {"home": 50.0, "away": 50.0}
        h = 100 * self.tstats["home"].passes / total
        return {"home": round(h, 1), "away": round(100 - h, 1)}

    def snapshot(self) -> dict[str, Any]:
        poss = self.possession_pct()
        idx, ctrl = self.chaos_index()

        def team(side: Side) -> dict[str, Any]:
            s = self.tstats[side]
            on = [p for p in self.pstats.values() if p.side == side]
            return {
                "goals": s.goals,
                "possession": poss[side],
                "passes": s.passes,
                "pass_accuracy": round(s.pass_accuracy, 1),
                "shots": s.shots,
                "shots_on_target": s.shots_on_target,
                "xg": round(s.xg, 2),
                "big_chances": s.big_chances,
                "corners": s.corners,
                "fouls": s.fouls,
                "yellow": s.yellow,
                "red": s.red,
                "tackles": s.tackles,
                "interceptions": s.interceptions,
                "pressures": s.pressures,
                "ppda": round(s.ppda, 1),
                "field_tilt": round(
                    100
                    * s.final_third_passes
                    / max(self.tstats["home"].final_third_passes + self.tstats["away"].final_third_passes, 1),
                    1,
                ),
                "distance_km": round(sum(p.distance_m for p in on) / 1000, 1),
                "sprints": sum(p.sprints for p in on),
            }

        return {
            "t": self.t,
            "minute": self.minute,
            "period": self.period,
            "score": [self.score["home"], self.score["away"]],
            "home": team("home"),
            "away": team("away"),
            "momentum": self.momentum,
            "momentum_series": self.momentum_series[:: max(1, len(self.momentum_series) // 240)],
            "chaos": idx,
            "control": ctrl,
            "chaos_series": [(round(t, 1), v) for t, v, _ in self.chaos_series[-100:]],
            "players": {
                pid: self.player_snapshot(pid) for pid, p in self.pstats.items() if p.touches or p.on_pitch
            },
        }

    def player_snapshot(self, pid: str) -> dict[str, Any]:
        p = self.pstats[pid]
        return {
            "id": pid,
            "side": p.side,
            "on": p.on_pitch,
            "passes": p.passes,
            "pass_accuracy": round(p.pass_accuracy, 1),
            "avg_difficulty": round(p.avg_difficulty, 1),
            "hardest_pass": p.hardest_completed,
            "progressive": p.progressive_passes,
            "key_passes": p.key_passes,
            "assists": p.assists,
            "shots": p.shots,
            "goals": p.goals,
            "xg": round(p.xg, 2),
            "tackles": p.tackles,
            "interceptions": p.interceptions,
            "pressures": p.pressures,
            "distance_km": round(p.distance_m / 1000, 2),
            "top_speed": round(p.top_speed_kmh, 1),
            "sprints": p.sprints,
            "touches": p.touches,
            "rating": p.rating(),
        }

    def player_of_match(self) -> str | None:
        candidates = [p for p in self.pstats.values() if p.touches > 5]
        if not candidates:
            return None
        winner_side: Side | None = None
        if self.score["home"] != self.score["away"]:
            winner_side = "home" if self.score["home"] > self.score["away"] else "away"
        return max(candidates, key=lambda p: p.rating() + (0.3 if p.side == winner_side else 0)).player_id
