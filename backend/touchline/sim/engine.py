"""Possession-chain match simulator.

Produces a full, football-realistic event stream (≈1,300–1,700 events) plus 5 Hz
player and ball tracking for one match. Deterministic for a given seed.

Model, in short:
  * The ball carrier chooses an action (pass / carry / dribble / shot / cross /
    clearance) based on pitch zone, pressure and the team's style.
  * Opponents press according to their pressing intensity and pitch zone.
  * Outcomes are sampled from hidden "true" probabilities that depend on player
    attributes, fatigue, momentum and the scenario's chaos level.
  * Scripted beats (goals, red cards, momentum) let the Scenario Director shape
    the story without breaking realism.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from touchline.models import (
    PITCH_LENGTH,
    PITCH_WIDTH,
    EventType,
    MatchEvent,
    MatchMeta,
    Player,
    Side,
    Team,
)
from touchline.sim.scenario import Beat, Scenario
from touchline.sim.shape import shape_absolute, slot_roles, team_shape, to_absolute, to_attacking
from touchline.stats.models import expected_goals

HALF_SECONDS = 45 * 60


def other(side: Side) -> Side:
    return "away" if side == "home" else "home"


@dataclass
class TeamState:
    side: Side
    team: Team
    slots: list[Player | None]
    bench: list[Player]
    on_since: dict[str, float]
    roles: list[str]
    goals: int = 0
    subs_left: int = 3
    yellows: set[str] = field(default_factory=set)
    reds: int = 0
    confidence: float = 0.0
    momentum_until: float = -1.0

    def active(self) -> list[tuple[int, Player]]:
        return [(i, p) for i, p in enumerate(self.slots) if p is not None]

    def slot_of(self, player_id: str) -> int | None:
        for i, p in enumerate(self.slots):
            if p is not None and p.id == player_id:
                return i
        return None


@dataclass
class MatchData:
    meta: MatchMeta
    events: list[MatchEvent]
    tracking: Tracking | None = None

    @property
    def players(self) -> dict[str, Player]:
        return {p.id: p for t in (self.meta.home, self.meta.away) for p in t.players}

    def final_score(self) -> tuple[int, int]:
        h = sum(
            1 for e in self.events if e.type == EventType.SHOT and e.outcome == "goal" and e.team == "home"
        )
        a = sum(
            1 for e in self.events if e.type == EventType.SHOT and e.outcome == "goal" and e.team == "away"
        )
        return h, a


class MatchSimulator:
    def __init__(self, home: Team, away: Team, *, seed: int, scenario: Scenario, match_id: str) -> None:
        self.rng = np.random.default_rng(seed)
        self.scenario = scenario
        self.match_id = match_id
        self.teams: dict[Side, TeamState] = {
            "home": self._team_state("home", home),
            "away": self._team_state("away", away),
        }
        self.events: list[MatchEvent] = []
        self.seq = 0
        self.possession_id = 0
        self.t = 0.0  # continuous seconds of play
        self.clock = 0.0  # displayed match clock
        self.period: int = 1
        self.pending_beats: list[Beat] = sorted(scenario.beats, key=lambda b: b.minute)
        self.scripted_goals = any(b.kind == "goal" for b in scenario.beats)
        self.sub_minutes = {s: sorted(self.rng.uniform(57, 86, size=3).tolist()) for s in ("home", "away")}
        # Possession state
        self.poss: Side = "home"
        self.carrier: Player | None = None
        self.bx, self.by = PITCH_LENGTH / 2, PITCH_WIDTH / 2
        self.under_pressure = False
        self.pressure_by: str | None = None
        self.last_pass_type: str | None = None

    # ------------------------------------------------------------------ setup

    def _team_state(self, side: Side, team: Team) -> TeamState:
        starters = list(team.players[:11])
        return TeamState(
            side=side,
            team=team,
            slots=starters,
            bench=list(team.players[11:]),
            on_since={p.id: 0.0 for p in starters},
            roles=slot_roles(team.style.formation),
        )

    # ------------------------------------------------------------------ helpers

    @property
    def minute(self) -> int:
        return int(self.clock // 60) + 1

    def _emit(self, type_: EventType, team: Side, player: Player | None = None, **kw) -> MatchEvent:
        self.seq += 1
        clock = self.clock
        half_cap = HALF_SECONDS if self.period == 1 else 2 * HALF_SECONDS
        stoppage = max(0, int((clock - half_cap) // 60) + 1) if clock >= half_cap else 0
        ev = MatchEvent(
            event_id=f"{self.match_id}-e{self.seq:05d}",
            match_id=self.match_id,
            seq=self.seq,
            possession_id=self.possession_id,
            t=round(self.t, 2),
            period=self.period,  # type: ignore[arg-type]
            minute=min(int(clock // 60) + 1, 45 if self.period == 1 else 90)
            if stoppage
            else int(clock // 60) + 1,
            second=int(clock % 60),
            type=type_,
            team=team,
            player_id=player.id if player else None,
            x=round(kw.pop("x", self.bx), 2),
            y=round(kw.pop("y", self.by), 2),
            **kw,
        )
        if stoppage:
            ev.extra["stoppage"] = stoppage
        self.events.append(ev)
        return ev

    def _advance(self, seconds: float) -> None:
        self.t += seconds
        self.clock += seconds

    def _fatigue(self, side: Side, p: Player) -> float:
        on = self.teams[side].on_since.get(p.id, 0.0)
        mins = (self.t - on) / 60
        return 1.0 - max(0.0, mins - 55) / 90 * (1 - p.stamina) * 0.7

    def _boost(self, side: Side) -> float:
        ts = self.teams[side]
        b = 0.0
        if self.t < ts.momentum_until:
            b += 0.09
        b += 0.03 * ts.confidence
        b -= 0.035 * ts.reds
        if side == "home":
            b += 0.012  # home advantage
        return b

    def _shape(self, side: Side) -> np.ndarray:
        ts = self.teams[side]
        ax, ay = to_attacking(self.bx, self.by, side)
        pos = team_shape(
            ts.team.style.formation,
            ax,
            ay,
            in_possession=(side == self.poss),
            width=ts.team.style.width,
            press=ts.team.style.press,
        )
        return shape_absolute(pos, side)

    def _nearest(
        self, side: Side, x: float, y: float, exclude: str | None = None, outfield: bool = True
    ) -> Player:
        ts = self.teams[side]
        pos = self._shape(side)
        best, best_d = None, 1e9
        for i, p in ts.active():
            if exclude and p.id == exclude:
                continue
            if outfield and ts.roles[i] == "GK":
                continue
            d = math.hypot(pos[i, 0] - x, pos[i, 1] - y) + self.rng.uniform(0, 4)
            if d < best_d:
                best, best_d = p, d
        assert best is not None
        return best

    def _keeper(self, side: Side) -> Player:
        ts = self.teams[side]
        return ts.slots[0] or next(p for _, p in ts.active())

    def _new_possession(self, side: Side, carrier: Player) -> None:
        self.possession_id += 1
        self.poss = side
        self.carrier = carrier
        self.under_pressure = False
        self.last_pass_type = None

    def _att(self) -> tuple[float, float]:
        return to_attacking(self.bx, self.by, self.poss)

    def _set_ball_att(self, ax: float, ay: float, side: Side) -> None:
        ax = float(np.clip(ax, 0.5, PITCH_LENGTH - 0.5))
        ay = float(np.clip(ay, 0.5, PITCH_WIDTH - 0.5))
        self.bx, self.by = to_absolute(ax, ay, side)

    def _chaos(self) -> float:
        return self.scenario.chaos

    def _gap(self) -> float:
        tempo = 0.5 * (self.scenario.tempo + self.teams[self.poss].team.style.tempo)
        return float(0.3 + self.rng.exponential(1.4 - 0.8 * tempo))

    # ------------------------------------------------------------------ restarts

    def _kickoff(self, side: Side) -> None:
        self.bx, self.by = PITCH_LENGTH / 2, PITCH_WIDTH / 2
        ts = self.teams[side]
        striker = next((p for i, p in ts.active() if ts.roles[i] == "ST"), ts.active()[-1][1])
        self._new_possession(side, striker)
        self._emit(EventType.KICKOFF, side, striker)
        self._advance(0.5)

    def _restart(
        self, kind: EventType, side: Side, ax: float, ay: float, dead_time: tuple[float, float]
    ) -> None:
        self._advance(float(self.rng.uniform(*dead_time)))
        self._set_ball_att(ax, ay, side)
        taker = self._keeper(side) if kind == EventType.GOAL_KICK else self._nearest(side, self.bx, self.by)
        self._new_possession(side, taker)
        self._emit(kind, side, taker)
        if kind == EventType.CORNER:
            self._corner(side, taker)

    # ------------------------------------------------------------------ actions

    def _pressure_step(self) -> bool:
        """Maybe apply pressure. Returns True if possession was lost (tackle) or play stopped."""
        assert self.carrier is not None
        side, opp = self.poss, other(self.poss)
        ax, _ = self._att()
        o_style = self.teams[opp].team.style
        p_press = (
            0.12
            + 0.42 * o_style.press * max(0.0, 1 - ax / 105) * (1.0 if ax < 70 else 0.6)
            + 0.10 * self._chaos()
            + (0.12 if ax > 82 else 0.0)
            + max(0.0, self._boost(opp))
        )
        self.under_pressure = False
        self.pressure_by = None
        if self.rng.random() > p_press:
            return False
        presser = self._nearest(opp, self.bx, self.by)
        self.under_pressure = True
        self.pressure_by = presser.id
        self._emit(EventType.PRESSURE, opp, presser, duration=0.6)
        self._advance(0.6)

        # Foul?
        if self.rng.random() < 0.045 + 0.06 * self._chaos():
            self._foul(opp, presser, victim_side=side)
            return True
        # Tackle?
        p_tackle = (
            0.10
            + 0.16 * presser.defending
            + 0.07 * self._chaos()
            - 0.08 * self.carrier.pace
            + self._boost(opp)
        )
        if self.rng.random() < p_tackle:
            self._emit(
                EventType.TACKLE,
                opp,
                presser,
                outcome="won",
                extra={"against": self.carrier.id},
            )
            self._new_possession(opp, presser)
            self._advance(0.8)
            return True
        return False

    def _foul(
        self, offender_side: Side, offender: Player, victim_side: Side, card: str | None = None
    ) -> None:
        self._emit(
            EventType.FOUL,
            offender_side,
            offender,
            extra={"victim": self.carrier.id if self.carrier else None},
        )
        ts = self.teams[offender_side]
        roll = self.rng.random()
        if card is None:
            if roll < 0.006 + 0.01 * self._chaos():
                card = "red"
            elif roll < 0.13 + 0.06 * self._chaos():
                card = "yellow"
        if card == "yellow" and offender.id in ts.yellows:
            card = "second_yellow"
        if card:
            self._advance(25)
            self._emit(
                EventType.CARD,
                offender_side,
                offender,
                outcome="red" if card != "yellow" else "yellow",
                extra={"reason": card},
            )
            if card == "yellow":
                ts.yellows.add(offender.id)
            else:
                slot = ts.slot_of(offender.id)
                if slot is not None:
                    ts.slots[slot] = None
                    ts.reds += 1
        # Free kick to the fouled team at the spot.
        self._advance(float(self.rng.uniform(10, 25)))
        taker = self._nearest(victim_side, self.bx, self.by)
        self._new_possession(victim_side, taker)
        self._emit(EventType.FREE_KICK, victim_side, taker)

    def _choose_pass_target(self) -> tuple[Player, float, float, str, float]:
        assert self.carrier is not None
        side = self.poss
        ts = self.teams[side]
        style = ts.team.style
        pos = self._shape(side)
        ax, ay = self._att()
        is_gk = ts.slot_of(self.carrier.id) == 0
        cands, weights, targets = [], [], []
        for i, p in ts.active():
            if p.id == self.carrier.id or i == 0:
                continue
            tx, ty = pos[i]
            tax, tay = to_attacking(tx, ty, side)
            tax += self.rng.normal(0, 3)
            tay += self.rng.normal(0, 3)
            dist = math.hypot(tax - ax, tay - ay)
            fwd = tax - ax
            w = math.exp(-(((dist - 16) / 13) ** 2))
            w *= 1 + (style.directness + 4 * max(self._boost(side), 0)) * max(fwd, 0) / 18
            if fwd < -8:
                w *= 0.55 + 0.6 * style.possession
            if is_gk and dist > 35:
                w *= 1.5 + 2 * style.directness
            if dist < 4:
                w *= 0.1
            cands.append(p)
            weights.append(max(w, 1e-4))
            targets.append((tax, tay, dist, fwd))
        w = np.array(weights)
        idx = int(self.rng.choice(len(cands), p=w / w.sum()))
        tax, tay, dist, fwd = targets[idx]
        ptype = "short"
        if dist > 32:
            ptype = "long" if abs(tay - ay) < 30 else "switch"
        if fwd > 14 and tax > 70 and self.rng.random() < 0.45:
            ptype = "through"
            tax += float(self.rng.uniform(4, 9))
        if fwd < -5:
            ptype = "back"
        if ax > 78 and abs(ay - 34) > 17 and tax > 88 and abs(tay - 34) < 14:
            ptype = "cross"
        tax = float(np.clip(tax, 1, 104))
        tay = float(np.clip(tay, 1, 67))
        dist = math.hypot(tax - ax, tay - ay)
        return cands[idx], tax, tay, ptype, dist

    def _pass(
        self, forced_target: tuple[Player, float, float, str] | None = None, force_complete: bool = False
    ) -> None:
        assert self.carrier is not None
        side, opp = self.poss, other(self.poss)
        ax, ay = self._att()
        if forced_target:
            target, tax, tay, ptype = forced_target
            dist = math.hypot(tax - ax, tay - ay)
        else:
            target, tax, tay, ptype, dist = self._choose_pass_target()
        fwd = tax - ax
        lam = 0.12 + 0.025 * max(fwd, 0) + (0.35 if ax > 70 else 0.0) + 0.2 * self._chaos()
        lane = int(min(self.rng.poisson(lam), 4))
        fat = self._fatigue(side, self.carrier)
        z = (
            3.5
            - 0.05 * dist
            - 0.85 * self.under_pressure
            - 0.45 * lane
            - 0.016 * max(fwd, 0)
            + 1.6 * (self.carrier.passing - 0.6)
            - 0.9 * self._chaos()
            + 6 * self._boost(side)
            - 1.2 * (1 - fat)
        )
        if ptype in {"through", "cross"}:
            z -= 0.7
        if ptype == "back":
            z += 0.9
        p_ok = 1 / (1 + math.exp(-z))
        complete = force_complete or self.rng.random() < p_ok
        if ptype == "cross":
            speed = float(self.rng.uniform(62, 88))
        elif dist > 30:
            speed = 52 + dist * 0.55 + float(self.rng.normal(0, 5))
        else:
            speed = 26 + dist * 1.1 + float(self.rng.normal(0, 4))
        duration = dist / (speed / 3.6) * 1.15 + 0.25
        ex, ey = to_absolute(tax, tay, side)
        ev = self._emit(
            EventType.PASS,
            side,
            self.carrier,
            end_x=round(ex, 2),
            end_y=round(ey, 2),
            duration=round(duration, 2),
            recipient_id=target.id if complete else None,
            outcome="complete" if complete else "incomplete",
            pass_type=ptype,
            under_pressure=self.under_pressure,
            pressure_player_id=self.pressure_by,
            opponents_in_lane=lane,
            speed_kmh=round(speed, 1),
            body_part="foot",
            extra={"intended_recipient": target.id},
        )
        self._advance(duration)
        self.last_pass_type = ptype
        if complete:
            self.carrier = target
            self.bx, self.by = ev.end_x, ev.end_y  # type: ignore[assignment]
            self.under_pressure = False
            return
        # Incomplete: out of play or intercepted.
        if self.rng.random() < 0.28:
            out_ax = float(np.clip(tax + self.rng.normal(4, 4), 0, 105))
            out_ay = float(self.rng.choice([0.0, 68.0])) if abs(tay - 34) > 20 else tay
            if out_ax >= 104.5:
                self._set_ball_att(105, out_ay, side)
                self._emit(EventType.BALL_OUT, side, None)
                self._restart(EventType.GOAL_KICK, opp, 6, 34, (12, 22))
            else:
                self._set_ball_att(out_ax, 0.5 if out_ay < 34 else 67.5, side)
                self._emit(EventType.BALL_OUT, side, None)
                oax, oay = to_attacking(self.bx, self.by, opp)
                self._restart(EventType.THROW_IN, opp, oax, oay, (6, 14))
            return
        self._set_ball_att(tax + float(self.rng.normal(-3, 3)), tay + float(self.rng.normal(0, 3)), side)
        interceptor = self._nearest(opp, self.bx, self.by)
        self._emit(EventType.INTERCEPTION, opp, interceptor, outcome="won")
        self._new_possession(opp, interceptor)
        self._advance(0.5)

    def _carry(self) -> None:
        assert self.carrier is not None
        side, opp = self.poss, other(self.poss)
        ax, ay = self._att()
        fat = self._fatigue(side, self.carrier)
        if self.under_pressure and ax > 50 and self.rng.random() < 0.45:
            p_win = 0.38 + 0.4 * self.carrier.pace * fat - 0.2 * self._chaos() + self._boost(side)
            won = self.rng.random() < p_win
            dx = float(self.rng.uniform(3, 8)) if won else 0.0
            self._set_ball_att(ax + dx, ay + float(self.rng.normal(0, 3)), side)
            self._emit(
                EventType.DRIBBLE,
                side,
                self.carrier,
                outcome="won" if won else "lost",
                end_x=round(self.bx, 2),
                end_y=round(self.by, 2),
                duration=1.2,
            )
            self._advance(1.2)
            if not won:
                tackler = self.teams[opp].team.players[0]
                tackler = next((p for p in [self._nearest(opp, self.bx, self.by)]), tackler)
                self._emit(EventType.TACKLE, opp, tackler, outcome="won", extra={"against": self.carrier.id})
                self._new_possession(opp, tackler)
                self._advance(0.6)
            return
        dist = float(self.rng.uniform(3, 15)) * (0.6 + self.carrier.pace) * fat
        dy = float(self.rng.normal(0, 4))
        tax = min(ax + dist, 102.0)
        tay = float(np.clip(ay + dy, 2, 66))
        sx, sy = self.bx, self.by
        self._set_ball_att(tax, tay, side)
        real = math.hypot(self.bx - sx, self.by - sy)
        duration = real / (3.8 + 3.2 * self.carrier.pace * fat) + 0.2
        self._emit(
            EventType.CARRY,
            side,
            self.carrier,
            x=sx,
            y=sy,
            end_x=round(self.bx, 2),
            end_y=round(self.by, 2),
            duration=round(duration, 2),
            under_pressure=self.under_pressure,
        )
        self._advance(duration)

    def _clearance(self) -> None:
        assert self.carrier is not None
        side = self.poss
        ax, ay = self._att()
        tax = ax + float(self.rng.uniform(30, 55))
        tay = float(np.clip(ay + self.rng.normal(0, 15), 3, 65))
        sx, sy = self.bx, self.by
        self._set_ball_att(tax, tay, side)
        self._emit(
            EventType.CLEARANCE,
            side,
            self.carrier,
            x=sx,
            y=sy,
            end_x=round(self.bx, 2),
            end_y=round(self.by, 2),
            duration=2.2,
            speed_kmh=round(float(self.rng.uniform(70, 95)), 1),
        )
        self._advance(2.2)
        winner = side if self.rng.random() < 0.4 else other(side)
        self._new_possession(winner, self._nearest(winner, self.bx, self.by))

    def _shot(self, force_goal: bool = False, header: bool | None = None) -> None:
        assert self.carrier is not None
        side, opp = self.poss, other(self.poss)
        ax, ay = self._att()
        if header is None:
            header = self.last_pass_type == "cross" and self.rng.random() < 0.6
        assisted = self.last_pass_type if self.last_pass_type in {"through", "cross"} else None
        xg = expected_goals(ax, ay, header=header, under_pressure=self.under_pressure, assisted_by=assisted)
        fat = self._fatigue(side, self.carrier)
        keeper = self._keeper(opp)
        p_goal = xg * (0.55 + 0.6 * self.carrier.finishing) * fat * (1.08 - 0.3 * keeper.defending)
        p_goal *= 1 + 2.5 * self._boost(side)
        goal = force_goal or (not self.scripted_goals and self.rng.random() < p_goal)
        if header:
            speed = float(self.rng.uniform(38, 62))
        else:
            speed = (
                62 + 48 * self.carrier.finishing * float(self.rng.uniform(0.6, 1.1)) - (8 if ax > 95 else 0)
            )
        if goal:
            outcome = "goal"
            gy = 34 + float(self.rng.uniform(-3.2, 3.2))
            end = (105.0, gy)
        else:
            r = self.rng.random()
            if r < 0.33:
                outcome, end = "saved", (103.5, 34 + float(self.rng.uniform(-3, 3)))
            elif r < 0.33 + 0.24 + 0.15 * self.under_pressure:
                outcome, end = (
                    "blocked",
                    (
                        min(ax + float(self.rng.uniform(1.5, 5)), 104.0),
                        float(np.clip(ay + self.rng.normal(0, 2), 1, 67)),
                    ),
                )
            else:
                side_off = float(self.rng.choice([-1, 1]))
                outcome, end = "off_target", (105.0, 34 + side_off * float(self.rng.uniform(4.2, 12)))
        dist = math.hypot(end[0] - ax, end[1] - ay)
        duration = max(dist / (speed / 3.6), 0.06)
        ex, ey = to_absolute(end[0], end[1], side)
        self._emit(
            EventType.SHOT,
            side,
            self.carrier,
            end_x=round(ex, 2),
            end_y=round(ey, 2),
            duration=round(duration, 3),
            outcome=outcome,
            body_part="head" if header else "foot",
            under_pressure=self.under_pressure,
            pressure_player_id=self.pressure_by,
            speed_kmh=round(speed, 1),
            extra={"assist_type": assisted, "sim_xg": xg},
        )
        self._advance(duration)
        self.bx, self.by = ex, ey
        if outcome == "goal":
            self.teams[side].goals += 1
            self.teams[side].confidence = min(1.0, self.teams[side].confidence + 0.5)
            self.teams[opp].confidence = max(-1.0, self.teams[opp].confidence - 0.2)
            self._advance(float(self.rng.uniform(45, 75)))
            self._kickoff(opp)
            return
        if outcome == "saved":
            held = self.rng.random() < 0.55
            self._emit(EventType.SAVE, opp, keeper, outcome="held" if held else "parried")
            self._advance(0.4)
            if held:
                self._new_possession(opp, keeper)
                self._advance(float(self.rng.uniform(3, 8)))
            elif self.rng.random() < 0.5:
                self._restart(EventType.CORNER, side, 104.5, float(self.rng.choice([0.5, 67.5])), (18, 30))
            else:
                winner = side if self.rng.random() < 0.45 else opp
                self._set_ball_att(float(self.rng.uniform(92, 100)), float(self.rng.uniform(22, 46)), side)
                self._new_possession(winner, self._nearest(winner, self.bx, self.by))
            return
        if outcome == "off_target":
            self._emit(EventType.BALL_OUT, side, None)
            self._restart(EventType.GOAL_KICK, opp, 6, 34, (14, 24))
            return
        # blocked
        if self.rng.random() < 0.4:
            self._restart(EventType.CORNER, side, 104.5, float(self.rng.choice([0.5, 67.5])), (18, 30))
        else:
            winner = side if self.rng.random() < 0.4 else opp
            self._new_possession(winner, self._nearest(winner, self.bx, self.by))

    def _corner(self, side: Side, taker: Player) -> None:
        # Delivery into the box.
        tax, tay = float(self.rng.uniform(92, 99)), float(self.rng.uniform(28, 40))
        ts = self.teams[side]
        targets = [p for i, p in ts.active() if ts.roles[i] in {"CB", "ST", "AM"}] or [
            p for _, p in ts.active()[1:]
        ]
        target = targets[int(self.rng.integers(len(targets)))]
        self.carrier = taker
        self.last_pass_type = "cross"
        attack_wins = self.rng.random() < 0.38 + self._boost(side)
        if attack_wins:
            self._pass(forced_target=(target, tax, tay, "cross"), force_complete=True)
            if self.rng.random() < 0.6:
                self._shot(header=True)
            return
        self._pass(forced_target=(target, tax, tay, "cross"))

    # ------------------------------------------------------------------ scripted beats

    def _apply_beats(self) -> None:
        while self.pending_beats and self.pending_beats[0].minute <= self.minute:
            beat = self.pending_beats.pop(0)
            if (beat.minute <= 45) != (self.period == 1) and self.period == 1:
                self.pending_beats.insert(0, beat)
                return
            ts = self.teams[beat.team]
            if beat.kind == "momentum":
                ts.momentum_until = self.t + beat.duration * 60
            elif beat.kind in {"red_card", "yellow_card"}:
                offender = self._nearest(beat.team, self.bx, self.by)
                victim = other(beat.team)
                if self.poss != victim:
                    self._new_possession(victim, self._nearest(victim, self.bx, self.by))
                self._foul(beat.team, offender, victim, card="red" if beat.kind == "red_card" else "yellow")
            elif beat.kind == "goal":
                self._scripted_goal(beat.team)

    def _scripted_goal(self, side: Side) -> None:
        opp = other(side)
        if self.poss != side:
            ax, ay = float(self.rng.uniform(45, 62)), float(self.rng.uniform(15, 53))
            self._set_ball_att(ax, ay, side)
            winner = self._nearest(side, self.bx, self.by)
            self._emit(EventType.INTERCEPTION, side, winner, outcome="won")
            self._new_possession(side, winner)
            self._advance(0.6)
        ts = self.teams[side]
        for _ in range(int(self.rng.integers(2, 4))):
            ax, ay = self._att()
            if ax > 80:
                break
            outfield = [p for i, p in ts.active() if i != 0 and p.id != self.carrier.id]  # type: ignore[union-attr]
            target = outfield[int(self.rng.integers(len(outfield)))]
            tax = min(ax + float(self.rng.uniform(14, 26)), 92)
            tay = float(np.clip(ay + self.rng.normal(0, 10), 12, 56))
            self._pass(
                forced_target=(target, tax, tay, "through" if tax > 80 else "short"), force_complete=True
            )
        ax, ay = self._att()
        # Work the ball into a realistic scoring position (central, inside the box).
        shooters = [p for i, p in ts.active() if ts.roles[i] in {"ST", "W", "AM"}] or [
            p for _, p in ts.active()
        ]
        shooter = shooters[int(self.rng.integers(len(shooters)))]
        if shooter.id != self.carrier.id:  # type: ignore[union-attr]
            tax, tay = float(self.rng.uniform(86, 92)), float(self.rng.uniform(24, 44))
            self._pass(forced_target=(shooter, tax, tay, "through"), force_complete=True)
        sx, sy = self.bx, self.by
        self._set_ball_att(float(self.rng.uniform(90, 98.5)), float(self.rng.uniform(27, 41)), side)
        dist = math.hypot(self.bx - sx, self.by - sy)
        if dist > 0.5:
            dur = dist / 6.5 + 0.2
            self._emit(
                EventType.CARRY,
                side,
                self.carrier,
                x=sx,
                y=sy,
                end_x=round(self.bx, 2),
                end_y=round(self.by, 2),
                duration=round(dur, 2),
            )
            self._advance(dur)
        self.under_pressure = self.rng.random() < 0.4
        self._shot(force_goal=True)
        _ = opp

    # ------------------------------------------------------------------ substitutions

    def _maybe_subs(self) -> None:
        for side in ("home", "away"):
            ts = self.teams[side]  # type: ignore[index]
            mins = self.sub_minutes[side]
            while mins and self.minute >= mins[0] and ts.subs_left > 0:
                mins.pop(0)
                outs = [(i, p) for i, p in ts.active() if i != 0]
                if not outs or not ts.bench:
                    break
                i, p_out = min(outs, key=lambda ip: self._fatigue(side, ip[1]) + self.rng.uniform(0, 0.05))  # type: ignore[arg-type]
                role = ts.roles[i]
                bench = [b for b in ts.bench if b.position != "GK"]
                pref = [b for b in bench if b.position == role] or bench
                p_in = pref[0]
                ts.bench.remove(p_in)
                ts.slots[i] = p_in
                ts.on_since[p_in.id] = self.t
                ts.subs_left -= 1
                self._advance(20)
                self._emit(
                    EventType.SUBSTITUTION,
                    side,
                    p_out,
                    recipient_id=p_in.id,  # type: ignore[arg-type]
                    extra={"player_in": p_in.id, "player_out": p_out.id, "slot": i},
                )
                if self.carrier is not None and self.carrier.id == p_out.id:
                    self.carrier = p_in

    # ------------------------------------------------------------------ main loop

    def _step(self) -> None:
        self._apply_beats()
        self._maybe_subs()
        if self.carrier is None or self.teams[self.poss].slot_of(self.carrier.id) is None:
            self.carrier = self._nearest(self.poss, self.bx, self.by)
        for ts in self.teams.values():
            ts.confidence *= 0.995
        if self._pressure_step():
            return
        side = self.poss
        ax, ay = self._att()
        ts = self.teams[side]
        slot = ts.slot_of(self.carrier.id)
        is_gk = slot == 0
        dist_goal = math.hypot(105 - ax, 34 - ay)
        style = ts.team.style
        r = self.rng.random()
        if is_gk:
            self._pass()
        elif ax < 18 and self.under_pressure and r < 0.55:
            self._clearance()
        elif (
            ax > 83
            and abs(ay - 34) < 22
            and r < (0.11 if dist_goal < 16 else 0.045) + self._boost(side)
            or 70 < ax <= 83
            and abs(ay - 34) < 16
            and r < 0.05 + 0.05 * self.carrier.finishing
        ):
            self._shot()
        elif (
            ax > 78
            and abs(ay - 34) > 16
            and r < 0.4
            or r < 0.6 + 0.22 * style.possession - (0.12 if ts.roles[slot or 0] in {"W", "AM"} else 0)
        ):
            self._pass()
        else:
            self._carry()
        self._advance(self._gap())

    def run(self) -> list[MatchEvent]:
        for period in (1, 2):
            self.period = period
            self.clock = 0.0 if period == 1 else float(HALF_SECONDS)
            end_clock = self.clock + HALF_SECONDS + 60 * float(self.rng.integers(1, 3 if period == 1 else 6))
            self._kickoff("home" if period == 1 else "away")
            while self.clock < end_clock:
                self._step()
            self._emit(
                EventType.HALF_END if period == 1 else EventType.MATCH_END,
                self.poss,
                None,
                extra={"score": [self.teams["home"].goals, self.teams["away"].goals]},
            )
            self._advance(1.0)
        return self.events


def simulate_match(
    home: Team,
    away: Team,
    *,
    seed: int = 7,
    scenario: Scenario | None = None,
    match_id: str | None = None,
    matchday: int = 30,
    with_tracking: bool = True,
) -> MatchData:
    scenario = scenario or Scenario()
    match_id = match_id or f"m-{home.code.lower()}-{away.code.lower()}-{seed}"
    sim = MatchSimulator(home, away, seed=seed, scenario=scenario, match_id=match_id)
    events = sim.run()
    meta = MatchMeta(
        match_id=match_id,
        matchday=matchday,
        venue=f"{home.city} Park",
        kickoff_iso=datetime(2026, 10, 24, 15, 0, tzinfo=UTC).isoformat(),
        seed=seed,
        home=home,
        away=away,
        scenario=scenario.model_dump(),
    )
    data = MatchData(meta=meta, events=events)
    if with_tracking:
        from touchline.sim.tracking import build_tracking

        data.tracking = build_tracking(data, seed=seed)
    return data


# Late import for type checking only.
from touchline.sim.tracking import Tracking  # noqa: E402
