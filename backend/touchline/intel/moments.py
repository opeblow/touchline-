"""Moment detection: decides which events matter and attaches the facts behind them.

Rules are transparent and scored 0–100 so judges, producers and the Control Room
can see exactly *why* something was flagged. Cool-downs stop the feed from spamming.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from touchline.models import EventType, Fact, MatchEvent, Moment, MomentType, Side
from touchline.stats.engine import BIG_CHANCE_XG, StatsEngine, Trigger, other

COOLDOWN_S: dict[MomentType, float] = {
    MomentType.MOMENTUM_SWING: 480,
    MomentType.PRESSURE_SHIFT: 420,
    MomentType.CHAOS_SPIKE: 420,
    MomentType.SPRINT: 150,
    MomentType.PASS_OF_MATCH: 420,
    MomentType.MILESTONE: 120,
    MomentType.SHOT_ON_TARGET: 60,
}


@dataclass
class MomentDetector:
    stats: StatsEngine
    match_id: str
    _seq: int = 0
    _last: dict[MomentType, float] = field(default_factory=dict)
    _mom_history: list[tuple[float, float]] = field(default_factory=list)
    _last_window_check: float = 0.0
    _prev_ppda: dict[Side, float] = field(default_factory=dict)
    _prev_chaos: float = 35.0
    _best_pass: int = 0

    def _ok(self, mtype: MomentType, t: float) -> bool:
        cd = COOLDOWN_S.get(mtype)
        return cd is None or t - self._last.get(mtype, -1e9) >= cd

    def _make(
        self,
        mtype: MomentType,
        ev_t: float,
        minute: int,
        importance: int,
        title: str,
        facts: list[Fact],
        *,
        team: Side | None = None,
        player_id: str | None = None,
        event_ids: list[str] | None = None,
    ) -> Moment:
        self._seq += 1
        self._last[mtype] = ev_t
        return Moment(
            moment_id=f"{self.match_id}-M{self._seq:03d}",
            match_id=self.match_id,
            type=mtype,
            minute=minute,
            t=ev_t,
            team=team,
            player_id=player_id,
            importance=max(0, min(100, importance)),
            title=title,
            facts=facts,
            event_ids=event_ids or [],
        )

    # ------------------------------------------------------------------ main entry

    def detect(self, ev: MatchEvent, triggers: list[Trigger]) -> list[Moment]:
        s = self.stats
        out: list[Moment] = []
        name = s.player_name
        team_name = s.team_name

        if ev.type == EventType.SHOT:
            m = s.event_metrics[ev.event_id]
            xg = m.xg or 0.0
            facts = [
                s.fact("xg", "Shot xG", xg, team=ev.team, player_id=ev.player_id, event_ids=[ev.event_id]),
                s.fact(
                    "shot_speed",
                    "Shot speed",
                    m.ball_speed_kmh or 0.0,
                    "km/h",
                    team=ev.team,
                    player_id=ev.player_id,
                    event_ids=[ev.event_id],
                ),
                s.fact(
                    "shot_distance",
                    "Shot distance",
                    m.distance_m or 0.0,
                    "m",
                    team=ev.team,
                    player_id=ev.player_id,
                    event_ids=[ev.event_id],
                ),
            ]
            if ev.outcome == "goal":
                facts += [
                    s.fact("score", "Score", f"{s.score['home']}-{s.score['away']}", event_ids=[ev.event_id]),
                    s.fact(
                        "xg_total",
                        f"{team_name(ev.team)} total xG",
                        round(s.tstats[ev.team].xg, 2),
                        team=ev.team,
                    ),
                    s.fact(
                        "xg_total",
                        f"{team_name(other(ev.team))} total xG",
                        round(s.tstats[other(ev.team)].xg, 2),
                        team=other(ev.team),
                    ),
                ]
                assist = ev.extra.get("assist_by")
                if assist:
                    last = s._last_chain_pass.get(ev.possession_id)
                    if last is not None:
                        diff = s.event_metrics[last.event_id].difficulty or 0
                        facts.append(
                            s.fact(
                                "pass_difficulty",
                                f"Assist by {name(assist)}: pass difficulty",
                                diff,
                                "/100",
                                team=ev.team,
                                player_id=assist,
                                event_ids=[last.event_id],
                            )
                        )
                for trg in triggers:
                    if trg.kind in {"brace", "hat_trick"} and trg.player_id == ev.player_id:
                        facts += trg.facts
                importance = 95 + (3 if any(t.kind == "hat_trick" for t in triggers) else 0)
                swing = abs(s.score["home"] - s.score["away"]) <= 1
                importance += 2 if swing and ev.minute >= 75 else 0
                out.append(
                    self._make(
                        MomentType.GOAL,
                        ev.t,
                        ev.minute,
                        importance,
                        f"GOAL — {name(ev.player_id)} ({team_name(ev.team)}) {ev.minute}'",
                        facts,
                        team=ev.team,
                        player_id=ev.player_id,
                        event_ids=[ev.event_id],
                    )
                )
            elif xg >= BIG_CHANCE_XG:
                out.append(
                    self._make(
                        MomentType.BIG_CHANCE,
                        ev.t,
                        ev.minute,
                        62 + int(xg * 40),
                        f"Big chance — {name(ev.player_id)} {ev.minute}'",
                        facts,
                        team=ev.team,
                        player_id=ev.player_id,
                        event_ids=[ev.event_id],
                    )
                )
            elif (
                ev.outcome == "saved"
                and (m.ball_speed_kmh or 0) >= 95
                and self._ok(MomentType.SHOT_ON_TARGET, ev.t)
            ):
                out.append(
                    self._make(
                        MomentType.SHOT_ON_TARGET,
                        ev.t,
                        ev.minute,
                        48,
                        f"Rocket from {name(ev.player_id)}",
                        facts,
                        team=ev.team,
                        player_id=ev.player_id,
                        event_ids=[ev.event_id],
                    )
                )

        elif ev.type == EventType.CARD:
            if ev.outcome == "red":
                before = s.window_stats(ev.team, 600)
                facts = [
                    s.fact(
                        "players_on_pitch",
                        f"{team_name(ev.team)} players left",
                        10 - (s.tstats[ev.team].red - 1),
                        team=ev.team,
                        event_ids=[ev.event_id],
                    ),
                    s.fact(
                        "possession_window",
                        f"{team_name(ev.team)} possession, last 10 min",
                        round(before["possession"]),
                        "%",
                        team=ev.team,
                    ),
                    s.fact("minutes_left", "Minutes remaining", max(90 - ev.minute, 0), "'"),
                ]
                out.append(
                    self._make(
                        MomentType.RED_CARD,
                        ev.t,
                        ev.minute,
                        90,
                        f"RED CARD — {name(ev.player_id)} ({team_name(ev.team)})",
                        facts,
                        team=ev.team,
                        player_id=ev.player_id,
                        event_ids=[ev.event_id],
                    )
                )
            else:
                facts = [
                    s.fact(
                        "yellow_cards",
                        f"{team_name(ev.team)} yellow cards",
                        s.tstats[ev.team].yellow,
                        team=ev.team,
                        event_ids=[ev.event_id],
                    )
                ]
                out.append(
                    self._make(
                        MomentType.YELLOW_CARD,
                        ev.t,
                        ev.minute,
                        28,
                        f"Booking — {name(ev.player_id)}",
                        facts,
                        team=ev.team,
                        player_id=ev.player_id,
                        event_ids=[ev.event_id],
                    )
                )

        elif ev.type == EventType.PASS and ev.outcome == "complete":
            m = s.event_metrics[ev.event_id]
            diff = m.difficulty or 0
            if (
                diff >= 68
                and diff > self._best_pass
                and ev.minute > 5
                and self._ok(MomentType.PASS_OF_MATCH, ev.t)
            ):
                self._best_pass = diff
                facts = [
                    s.fact(
                        "pass_difficulty",
                        "Pass difficulty",
                        diff,
                        "/100",
                        team=ev.team,
                        player_id=ev.player_id,
                        event_ids=[ev.event_id],
                    ),
                    s.fact(
                        "pass_distance",
                        "Pass distance",
                        m.distance_m or 0.0,
                        "m",
                        team=ev.team,
                        player_id=ev.player_id,
                        event_ids=[ev.event_id],
                    ),
                    s.fact(
                        "opponents_bypassed",
                        "Opponents in the passing lane",
                        ev.opponents_in_lane,
                        team=ev.team,
                        event_ids=[ev.event_id],
                    ),
                    s.fact(
                        "pass_accuracy",
                        f"{name(ev.player_id)} pass accuracy",
                        round(s.pstats[ev.player_id].pass_accuracy),
                        "%",
                        team=ev.team,
                        player_id=ev.player_id,
                    ),
                ]
                out.append(
                    self._make(
                        MomentType.PASS_OF_MATCH,
                        ev.t,
                        ev.minute,
                        52,
                        f"Pass of the match so far — {name(ev.player_id)}",
                        facts,
                        team=ev.team,
                        player_id=ev.player_id,
                        event_ids=[ev.event_id],
                    )
                )

        elif ev.type in {EventType.HALF_END, EventType.MATCH_END}:
            facts = [
                s.fact("score", "Score", f"{s.score['home']}-{s.score['away']}", event_ids=[ev.event_id]),
                s.fact(
                    "possession",
                    f"{team_name('home')} possession",
                    s.possession_pct()["home"],
                    "%",
                    team="home",
                ),
                s.fact("xg_total", f"{team_name('home')} xG", round(s.tstats["home"].xg, 2), team="home"),
                s.fact("xg_total", f"{team_name('away')} xG", round(s.tstats["away"].xg, 2), team="away"),
                s.fact("shots", f"{team_name('home')} shots", s.tstats["home"].shots, team="home"),
                s.fact("shots", f"{team_name('away')} shots", s.tstats["away"].shots, team="away"),
            ]
            label = "Half time" if ev.type == EventType.HALF_END else "Full time"
            out.append(
                self._make(
                    MomentType.PHASE,
                    ev.t,
                    ev.minute,
                    80,
                    f"{label}: {team_name('home')} {s.score['home']}-{s.score['away']} {team_name('away')}",
                    facts,
                    event_ids=[ev.event_id],
                )
            )

        # ---- triggers from the physical / milestone layer
        for trg in triggers:
            if trg.kind == "sprint" and self._ok(MomentType.SPRINT, trg.t):
                out.append(
                    self._make(
                        MomentType.SPRINT,
                        trg.t,
                        trg.minute,
                        38,
                        f"Flying — {name(trg.player_id)} hits {trg.facts[0].display()}",
                        trg.facts,
                        team=trg.team,
                        player_id=trg.player_id,
                    )
                )
            elif trg.kind in {"distance_milestone", "pass_milestone"} and self._ok(
                MomentType.MILESTONE, trg.t
            ):
                label = "km covered" if trg.kind == "distance_milestone" else "passes"
                out.append(
                    self._make(
                        MomentType.MILESTONE,
                        trg.t,
                        trg.minute,
                        30,
                        f"Milestone — {name(trg.player_id)}: {trg.facts[0].display()} {label if trg.kind == 'pass_milestone' else ''}".strip(),
                        trg.facts,
                        team=trg.team,
                        player_id=trg.player_id,
                        event_ids=trg.event_ids,
                    )
                )

        out += self._rhythm(ev)
        return out

    # ------------------------------------------------------------------ rhythm moments

    def _rhythm(self, ev: MatchEvent) -> list[Moment]:
        s = self.stats
        out: list[Moment] = []
        mom = s.momentum
        self._mom_history.append((ev.t, mom))
        while self._mom_history and self._mom_history[0][0] < ev.t - 300:
            self._mom_history.pop(0)
        if len(self._mom_history) > 5 and ev.minute > 8:
            first = self._mom_history[0][1]
            # A swing = momentum moved hard from one side to the other inside 5 minutes.
            swung = (first <= -40 and mom >= 40) or (first >= 40 and mom <= -40)
            if swung and self._ok(MomentType.MOMENTUM_SWING, ev.t):
                side: Side = "home" if mom > 0 else "away"
                win = s.window_stats(side, 300)
                facts = [
                    s.fact("momentum", "Momentum 5 minutes ago", round(first), "", minute=ev.minute - 5),
                    s.fact("momentum", "Momentum now", round(mom), ""),
                    s.fact(
                        "possession_window",
                        f"{s.team_name(side)} possession, last 5 min",
                        round(win["possession"]),
                        "%",
                        team=side,
                    ),
                    s.fact(
                        "shots_window", f"{s.team_name(side)} shots, last 5 min", int(win["shots"]), team=side
                    ),
                ]
                out.append(
                    self._make(
                        MomentType.MOMENTUM_SWING,
                        ev.t,
                        ev.minute,
                        64,
                        f"Momentum swings to {s.team_name(side)}",
                        facts,
                        team=side,
                    )
                )
                self._mom_history.clear()

        # Window checks every 5 minutes of play.
        if ev.t - self._last_window_check >= 300 and ev.minute >= 15:
            self._last_window_check = ev.t
            for side in ("home", "away"):
                now = s.window_stats(side, 600)
                prev = self._prev_ppda.get(side)
                self._prev_ppda[side] = now["ppda"]
                if (
                    prev
                    and now["ppda"]
                    and prev >= 8
                    and now["ppda"] <= prev * 0.55
                    and self._ok(MomentType.PRESSURE_SHIFT, ev.t)
                ):
                    facts = [
                        s.fact(
                            "ppda", f"{s.team_name(side)} PPDA, previous window", round(prev, 1), team=side
                        ),
                        s.fact(
                            "ppda", f"{s.team_name(side)} PPDA, last 10 min", round(now["ppda"], 1), team=side
                        ),
                        s.fact(
                            "possession_window",
                            f"{s.team_name(side)} possession, last 10 min",
                            round(now["possession"]),
                            "%",
                            team=side,
                        ),
                    ]
                    out.append(
                        self._make(
                            MomentType.PRESSURE_SHIFT,
                            ev.t,
                            ev.minute,
                            56,
                            f"{s.team_name(side)} turn up the press",
                            facts,
                            team=side,
                        )
                    )
            idx, ctrl = s.chaos_index()
            if idx >= 72 and self._prev_chaos < 55 and self._ok(MomentType.CHAOS_SPIKE, ev.t):
                facts = [
                    s.fact("chaos_index", "Control vs Chaos index", round(idx), "/100"),
                    s.fact("chaos_index", "Index 5 minutes earlier", round(self._prev_chaos), "/100"),
                    s.fact("turnovers_window", "Turnovers, last 5 min", len(s.turnovers)),
                ]
                out.append(
                    self._make(
                        MomentType.CHAOS_SPIKE, ev.t, ev.minute, 54, "The match descends into chaos", facts
                    )
                )
            elif idx <= 22 and ctrl and self._prev_chaos > 40 and self._ok(MomentType.CHAOS_SPIKE, ev.t):
                win = s.window_stats(ctrl, 300)
                facts = [
                    s.fact("chaos_index", "Control vs Chaos index", round(idx), "/100"),
                    s.fact(
                        "possession_window",
                        f"{s.team_name(ctrl)} possession, last 5 min",
                        round(win["possession"]),
                        "%",
                        team=ctrl,
                    ),
                    s.fact(
                        "pass_accuracy_window",
                        f"{s.team_name(ctrl)} pass accuracy, last 5 min",
                        round(win["pass_accuracy"]),
                        "%",
                        team=ctrl,
                    ),
                ]
                out.append(
                    self._make(
                        MomentType.CHAOS_SPIKE,
                        ev.t,
                        ev.minute,
                        50,
                        f"{s.team_name(ctrl)} take control",
                        facts,
                        team=ctrl,
                    )
                )
            self._prev_chaos = idx
        return out
