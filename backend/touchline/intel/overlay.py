"""Overlay cue builder: timed, machine-readable graphics instructions.

Cues are produced deterministically from the stats engine (no LLM in the hot path),
so graphics appear within milliseconds of the event. A rendering partner only needs
`overlay.schema.json`; our own /overlay page is one reference renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from touchline.models import EventType, MatchEvent, Moment, MomentType, OverlayCue
from touchline.stats.engine import StatsEngine, Trigger

LATENCY_S = 0.3  # time between the event and graphics on air


@dataclass
class CueBuilder:
    stats: StatsEngine
    match_id: str
    _seq: int = 0
    _last_momentum_t: float = -1e9
    _tagged: dict[str, float] = field(default_factory=dict)

    def _cue(
        self,
        template: str,
        t: float,
        hold: float,
        data: dict,
        priority: int = 50,
        moment_id: str | None = None,
    ) -> OverlayCue:
        self._seq += 1
        return OverlayCue(
            cue_id=f"{self.match_id}-C{self._seq:04d}",
            match_id=self.match_id,
            template=template,  # type: ignore[arg-type]
            t_in=round(t + LATENCY_S, 2),
            t_out=round(t + LATENCY_S + hold, 2),
            priority=priority,
            data=data,
            moment_id=moment_id,
        )

    def _player(self, pid: str | None) -> dict:
        if not pid:
            return {}
        p = self.stats.players[pid]
        side = self.stats.player_side[pid]
        team = self.stats.meta.home if side == "home" else self.stats.meta.away
        return {
            "player_id": pid,
            "name": p.name,
            "short_name": p.short_name,
            "number": p.number,
            "team": side,
            "team_code": team.code,
            "color": team.primary,
        }

    def score_bug(self, t: float) -> OverlayCue:
        s = self.stats
        return self._cue(
            "score_bug",
            t - LATENCY_S,
            99999,
            {
                "home": s.meta.home.code,
                "away": s.meta.away.code,
                "home_color": s.meta.home.primary,
                "away_color": s.meta.away.primary,
                "score": [s.score["home"], s.score["away"]],
                "minute": s.minute,
                "period": s.period,
            },
            priority=100,
        )

    def for_event(self, ev: MatchEvent, triggers: list[Trigger]) -> list[OverlayCue]:
        s = self.stats
        cues: list[OverlayCue] = []
        if ev.type == EventType.SHOT:
            m = s.event_metrics[ev.event_id]
            cues.append(
                self._cue(
                    "shot_speed",
                    ev.t,
                    5.0,
                    {
                        **self._player(ev.player_id),
                        "speed_kmh": m.ball_speed_kmh,
                        "outcome": ev.outcome,
                        "event_id": ev.event_id,
                    },
                    priority=80,
                )
            )
            cues.append(
                self._cue(
                    "xg_popup",
                    ev.t + 0.4,
                    5.0,
                    {
                        **self._player(ev.player_id),
                        "xg": m.xg,
                        "distance_m": m.distance_m,
                        "outcome": ev.outcome,
                        "event_id": ev.event_id,
                    },
                    priority=82,
                )
            )
            if ev.outcome == "goal":
                cues.append(self.score_bug(ev.t))
        elif ev.type == EventType.PASS and ev.outcome == "complete":
            m = s.event_metrics[ev.event_id]
            if (m.difficulty or 0) >= 60:
                cues.append(
                    self._cue(
                        "pass_rating",
                        ev.t + ev.duration,
                        4.5,
                        {
                            **self._player(ev.player_id),
                            "difficulty": m.difficulty,
                            "distance_m": m.distance_m,
                            "recipient": self._player(ev.recipient_id).get("name"),
                            "event_id": ev.event_id,
                        },
                        priority=60,
                    )
                )
        elif (
            ev.type == EventType.KICKOFF
            and ev.seq <= 1
            or ev.type in {EventType.HALF_END, EventType.MATCH_END}
        ):
            cues.append(self.score_bug(ev.t))
            if ev.type in {EventType.HALF_END, EventType.MATCH_END}:
                h, a = s.tstats["home"], s.tstats["away"]
                poss = s.possession_pct()
                cues.append(
                    self._cue(
                        "stat_compare",
                        ev.t + 2,
                        12.0,
                        {
                            "title": "Half time" if ev.type == EventType.HALF_END else "Full time",
                            "home": s.meta.home.code,
                            "away": s.meta.away.code,
                            "rows": [
                                {
                                    "label": "Possession",
                                    "home": poss["home"],
                                    "away": poss["away"],
                                    "unit": "%",
                                },
                                {"label": "Shots", "home": h.shots, "away": a.shots},
                                {"label": "xG", "home": round(h.xg, 2), "away": round(a.xg, 2)},
                                {
                                    "label": "Pass accuracy",
                                    "home": round(h.pass_accuracy),
                                    "away": round(a.pass_accuracy),
                                    "unit": "%",
                                },
                                {"label": "PPDA", "home": round(h.ppda, 1), "away": round(a.ppda, 1)},
                            ],
                        },
                        priority=90,
                    )
                )
        elif ev.type == EventType.CARD:
            cues.append(
                self._cue(
                    "lower_third",
                    ev.t,
                    6.0,
                    {
                        **self._player(ev.player_id),
                        "title": "Red card" if ev.outcome == "red" else "Yellow card",
                        "card": ev.outcome,
                    },
                    priority=75,
                )
            )
        elif ev.type == EventType.SUBSTITUTION:
            pin, pout = ev.extra.get("player_in"), ev.extra.get("player_out")
            cues.append(
                self._cue(
                    "lower_third",
                    ev.t,
                    6.0,
                    {
                        "title": "Substitution",
                        "in": self._player(pin),
                        "out": self._player(pout),
                        "team": ev.team,
                    },
                    priority=40,
                )
            )

        for trg in triggers:
            if trg.kind == "sprint":
                cues.append(
                    self._cue(
                        "speed_badge",
                        trg.t,
                        4.0,
                        {**self._player(trg.player_id), "speed_kmh": trg.facts[0].value},
                        priority=65,
                    )
                )
            elif trg.kind == "distance_milestone":
                cues.append(
                    self._cue(
                        "speed_badge",
                        trg.t,
                        4.0,
                        {
                            **self._player(trg.player_id),
                            "distance_km": trg.facts[0].value,
                            "kind": "distance",
                        },
                        priority=45,
                    )
                )

        # Player tag for the ball carrier on dangerous actions, at most once every 20 s per player.
        if ev.player_id and ev.type in {EventType.SHOT, EventType.DRIBBLE, EventType.TACKLE}:
            last = self._tagged.get(ev.player_id, -1e9)
            if ev.t - last > 20:
                self._tagged[ev.player_id] = ev.t
                cues.append(self._cue("player_tag", ev.t, 3.0, self._player(ev.player_id), priority=55))

        if ev.t - self._last_momentum_t >= 300:
            self._last_momentum_t = ev.t
            cues.append(
                self._cue(
                    "momentum_bar",
                    ev.t,
                    8.0,
                    {
                        "value": s.momentum,
                        "series": s.momentum_series[-40:],
                        "home": s.meta.home.code,
                        "away": s.meta.away.code,
                    },
                    priority=30,
                )
            )
        return cues

    def for_moment(self, moment: Moment, headline: str | None = None) -> OverlayCue | None:
        if moment.importance < 55 or moment.type == MomentType.PHASE:
            return None
        return self._cue(
            "moment_card",
            moment.t + 1.5,
            7.0,
            {
                "title": moment.title,
                "headline": headline,
                "type": moment.type.value,
                "minute": moment.minute,
                "team": moment.team,
                "facts": [
                    {"id": f.fact_id, "label": f.label, "value": f.display()} for f in moment.facts[:3]
                ],
            },
            priority=70,
            moment_id=moment.moment_id,
        )
