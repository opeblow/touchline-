"""5 Hz tracking generator: ball and 22 player positions derived from the event stream.

Ball: piecewise-linear between event start/end keyframes.
Players: each slot steers toward a target (team shape + personal drift, or the ball
for the carrier, the pass destination for the intended receiver, the ball for the
nearest pressers) with per-player top speed and an acceleration limit. Speeds and
distances computed from these positions behave like real tracking data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from touchline.models import PITCH_LENGTH, PITCH_WIDTH, EventType, TrackingFrame
from touchline.sim.shape import shape_absolute, team_shape, team_shape_batch

if TYPE_CHECKING:
    from touchline.sim.engine import MatchData

HZ = 5.0
DT = 1.0 / HZ
SIDES = ("home", "away")
DEFENSIVE_TYPES = {EventType.PRESSURE, EventType.FOUL}


@dataclass
class Tracking:
    hz: float
    times: np.ndarray  # (N,)
    ball: np.ndarray  # (N, 2)
    pos: np.ndarray  # (N, 22, 2); slots 0-10 home, 11-21 away; NaN = not on pitch
    roster_changes: list[tuple[int, int, str | None]]  # (frame index, slot 0-21, player id)
    initial_ids: list[str | None]

    def __len__(self) -> int:
        return len(self.times)

    def ids_at(self, i: int) -> list[str | None]:
        ids = list(self.initial_ids)
        for fi, slot, pid in self.roster_changes:
            if fi > i:
                break
            ids[slot] = pid
        return ids

    def index_at(self, t: float) -> int:
        return int(min(max(np.searchsorted(self.times, t, side="right") - 1, 0), len(self.times) - 1))

    def frame(self, i: int) -> TrackingFrame:
        ids = self.ids_at(i)
        p = self.pos[i]

        def side(lo: int, hi: int) -> tuple[list[tuple[float, float]], list[str]]:
            pts, out_ids = [], []
            for s in range(lo, hi):
                if ids[s] is None or np.isnan(p[s, 0]):
                    continue
                pts.append((round(float(p[s, 0]), 2), round(float(p[s, 1]), 2)))
                out_ids.append(ids[s])  # type: ignore[arg-type]
            return pts, out_ids

        home, hid = side(0, 11)
        away, aid = side(11, 22)
        return TrackingFrame(
            t=round(float(self.times[i]), 2),
            ball=(round(float(self.ball[i, 0]), 2), round(float(self.ball[i, 1]), 2)),
            home=home,
            away=away,
            home_ids=hid,
            away_ids=aid,
        )

    def speeds_kmh(self) -> np.ndarray:
        """(N, 22) instantaneous speed, NaN-safe."""
        d = np.diff(self.pos, axis=0, prepend=self.pos[:1])
        v = np.linalg.norm(d, axis=2) * self.hz * 3.6
        return np.nan_to_num(v, nan=0.0)

    def ball_speed_kmh(self) -> np.ndarray:
        d = np.diff(self.ball, axis=0, prepend=self.ball[:1])
        return np.linalg.norm(d, axis=1) * self.hz * 3.6


def _ball_path(events, times: np.ndarray) -> np.ndarray:
    kt, kx, ky = [], [], []
    for e in events:
        kt.append(e.t)
        kx.append(e.x)
        ky.append(e.y)
        if e.end_x is not None and e.duration > 0:
            kt.append(e.t + e.duration)
            kx.append(e.end_x)
            ky.append(e.end_y)
    order = np.argsort(np.array(kt), kind="stable")
    kt_a = np.array(kt)[order]
    # Enforce strictly increasing keyframe times for interpolation.
    kt_a = np.maximum.accumulate(kt_a + np.arange(len(kt_a)) * 1e-6)
    bx = np.interp(times, kt_a, np.array(kx)[order])
    by = np.interp(times, kt_a, np.array(ky)[order])
    return np.stack([bx, by], axis=1)


def build_tracking(data: MatchData, seed: int = 0) -> Tracking:
    rng = np.random.default_rng(seed + 99)
    events = data.events
    meta = data.meta
    t_end = events[-1].t + 1.0
    times = np.arange(0.0, t_end, DT)
    n = len(times)
    ball = _ball_path(events, times)

    # ---- roster per slot (0-10 home, 11-21 away)
    teams = {"home": meta.home, "away": meta.away}
    players = {p.id: p for t in teams.values() for p in t.players}
    current: list[str | None] = [p.id for p in meta.home.players[:11]] + [
        p.id for p in meta.away.players[:11]
    ]
    initial_ids = list(current)
    roster_changes: list[tuple[int, int, str | None]] = []

    # ---- per-event state: possession side, carrier, pass flight
    ev_t = np.array([e.t for e in events])
    poss_side: list[str] = []
    carrier_after: list[str | None] = []
    side_now, carrier_now = "home", None
    for e in events:
        if e.type in DEFENSIVE_TYPES or e.type in {
            EventType.CARD,
            EventType.BALL_OUT,
            EventType.SUBSTITUTION,
            EventType.HALF_END,
            EventType.MATCH_END,
        }:
            pass
        elif e.type == EventType.PASS:
            side_now = e.team
            carrier_now = e.recipient_id
        elif e.type == EventType.DRIBBLE and e.outcome == "lost":
            pass
        else:
            side_now = e.team
            carrier_now = e.player_id
        poss_side.append(side_now)
        carrier_after.append(carrier_now)

    # ---- per-slot movement parameters
    def vmax_of(pid: str | None) -> float:
        if pid is None:
            return 0.0
        p = players[pid]
        return 6.6 + 2.9 * p.pace  # m/s, ≈24–34 km/h

    vmax = np.array([vmax_of(pid) for pid in current])
    jog = np.full(22, 4.6)  # m/s ≈ 16.5 km/h
    jog[0] = jog[11] = 2.5  # goalkeepers
    amax = 3.0  # m/s²
    freq = rng.uniform(1 / 60, 1 / 18, size=(22, 2))
    phase = rng.uniform(0, 2 * math.pi, size=(22, 2))
    amp = rng.uniform(1.5, 4.5, size=(22, 2))
    # Off-ball runs: attackers in possession occasionally burst into space.
    run_until = np.zeros(22)
    run_target = np.zeros((22, 2))

    formations = {s: teams[s].style.formation for s in SIDES}
    widths = {s: teams[s].style.width for s in SIDES}
    presses = {s: teams[s].style.press for s in SIDES}

    # Teams react to where the ball has been over the last few seconds, not to every
    # touch: low-pass the ball before deriving team-shape targets.
    smooth = np.empty_like(ball)
    alpha = DT / 2.5
    acc = ball[0].copy()
    for i in range(n):
        acc += alpha * (ball[i] - acc)
        smooth[i] = acc

    # Pre-compute every frame's team-shape targets in one vectorised pass.
    frame_ev = np.clip(np.searchsorted(ev_t, times, side="right") - 1, 0, len(events) - 1)
    poss_home = np.array([s == "home" for s in poss_side])[frame_ev]
    shape_targets = np.empty((n, 22, 2))
    for s_i, s in enumerate(SIDES):
        if s == "home":
            ax, ay = smooth[:, 0], smooth[:, 1]
            in_p = poss_home
        else:
            ax, ay = PITCH_LENGTH - smooth[:, 0], PITCH_WIDTH - smooth[:, 1]
            in_p = ~poss_home
        sh = team_shape_batch(formations[s], ax, ay, in_p, widths[s], presses[s])
        if s == "away":
            sh[..., 0] = PITCH_LENGTH - sh[..., 0]
            sh[..., 1] = PITCH_WIDTH - sh[..., 1]
        shape_targets[:, s_i * 11 : (s_i + 1) * 11] = sh
    drift = amp[None] * np.sin(2 * math.pi * freq[None] * times[:, None, None] + phase[None])
    shape_targets += drift

    pos = np.full((n, 22, 2), np.nan, dtype=np.float32)
    cur = np.zeros((22, 2))
    for s_i, s in enumerate(SIDES):
        start = shape_absolute(team_shape(formations[s], 52.5, 34, s == "home"), s)
        start[:, 0] = np.where(s == "home", np.minimum(start[:, 0], 51), np.maximum(start[:, 0], 54))
        cur[s_i * 11 : (s_i + 1) * 11] = start
    vel = np.zeros((22, 2))

    # Roster events indexed by time
    roster_events = [
        e
        for e in events
        if e.type == EventType.SUBSTITUTION or (e.type == EventType.CARD and e.outcome == "red")
    ]
    r_i = 0

    slot_of = {pid: s for s, pid in enumerate(current) if pid is not None}
    amax_dt = amax * DT
    for i, t in enumerate(times):
        ev_idx = int(frame_ev[i])
        while r_i < len(roster_events) and roster_events[r_i].t <= t:
            re = roster_events[r_i]
            base = 0 if re.team == "home" else 11
            for s in range(base, base + 11):
                if current[s] == re.player_id:
                    if re.type == EventType.SUBSTITUTION:
                        current[s] = re.recipient_id
                        vmax[s] = vmax_of(re.recipient_id)
                        cur[s] = (52.5, 0.5 if base == 0 else 67.5)
                        vel[s] = 0
                    else:
                        current[s] = None
                        vmax[s] = 0
                    roster_changes.append((i, s, current[s]))
                    break
            r_i += 1
            slot_of = {pid: s for s, pid in enumerate(current) if pid is not None}

        e = events[ev_idx]
        bx, by = float(ball[i, 0]), float(ball[i, 1])
        in_poss = poss_side[ev_idx]
        targets = shape_targets[i].copy()
        cap = jog.copy()  # off-the-ball players jog into shape

        # Ball-related roles run at full speed.
        in_flight = e.type == EventType.PASS and t < e.t + e.duration
        carrier = None if in_flight else carrier_after[ev_idx]
        if in_flight:
            rid = e.recipient_id or e.extra.get("intended_recipient")
            if rid in slot_of and e.end_x is not None:
                targets[slot_of[rid]] = (e.end_x, e.end_y)
                cap[slot_of[rid]] = vmax[slot_of[rid]]
        if carrier in slot_of:
            targets[slot_of[carrier]] = (bx, by)
            cap[slot_of[carrier]] = vmax[slot_of[carrier]] * 0.85

        att_base = 0 if in_poss == "home" else 11
        direction = 1.0 if in_poss == "home" else -1.0
        for s in range(att_base + 1, att_base + 11):
            if current[s] is None or s == slot_of.get(carrier, -1):
                continue
            if t < run_until[s]:
                targets[s] = run_target[s]
                cap[s] = vmax[s] * 0.95
            elif rng.random() < 0.0035:
                run_until[s] = t + rng.uniform(2.0, 3.5)
                run_target[s] = (
                    float(np.clip(cur[s, 0] + direction * rng.uniform(14, 24), 2, PITCH_LENGTH - 2)),
                    float(np.clip(cur[s, 1] + rng.normal(0, 8), 2, PITCH_WIDTH - 2)),
                )

        # Two nearest defenders press / cover.
        def_base = 11 if in_poss == "home" else 0
        d_slots = [s for s in range(def_base + 1, def_base + 11) if current[s] is not None]
        if d_slots:
            rel = cur[d_slots] - (bx, by)
            order = np.argsort((rel * rel).sum(axis=1))
            own_goal_x = 0.0 if def_base == 0 else PITCH_LENGTH
            gx, gy = own_goal_x - bx, PITCH_WIDTH / 2 - by
            gn = max(math.hypot(gx, gy), 1e-6)
            gx, gy = gx / gn, gy / gn
            targets[d_slots[order[0]]] = (bx + gx * 1.4, by + gy * 1.4)
            cap[d_slots[order[0]]] = vmax[d_slots[order[0]]] * 0.9
            if len(order) > 1:
                targets[d_slots[order[1]]] = (bx + gx * 7.0, by + gy * 7.0)

        # Steering with speed and acceleration limits ("arrive" behaviour).
        desired = targets - cur
        dist = np.sqrt((desired * desired).sum(axis=1, keepdims=True)) + 1e-9
        # Far out of position → recovery run (faster than a jog).
        cap = np.where(dist[:, 0] > 14, np.maximum(cap, vmax * 0.8), cap)
        speed_goal = np.minimum(cap[:, None], dist / 1.5)
        dv = desired / dist * speed_goal - vel
        dvn = np.sqrt((dv * dv).sum(axis=1, keepdims=True)) + 1e-9
        dv *= np.minimum(1.0, amax_dt / dvn)
        vel = vel + dv
        cur = cur + vel * DT
        np.clip(cur[:, 0], -2, PITCH_LENGTH + 2, out=cur[:, 0])
        np.clip(cur[:, 1], -2, PITCH_WIDTH + 2, out=cur[:, 1])
        pos[i] = cur
        for s, pid in enumerate(current):
            if pid is None:
                pos[i, s] = np.nan

    return Tracking(
        hz=HZ, times=times, ball=ball, pos=pos, roster_changes=roster_changes, initial_ids=initial_ids
    )
