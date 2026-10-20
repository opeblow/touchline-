"""Per-moment context handed to every agent (and serialised into LLM prompts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from touchline.models import Fact, Moment, Side
from touchline.stats.engine import StatsEngine, other


@dataclass
class MomentContext:
    moment: Moment
    home: str
    away: str
    team: str | None
    opponent: str | None
    player: str | None
    player_short: str | None
    score: tuple[int, int]
    score_before: tuple[int, int]
    period: int
    state: str  # opener | equaliser | go_ahead | extend_lead | pull_back | comeback | late_winner | none
    late: bool
    memory: list[Fact] = field(default_factory=list)

    @property
    def facts(self) -> list[Fact]:
        return self.moment.facts + self.memory

    def fact(self, kind: str, index: int = 0) -> Fact | None:
        found = [f for f in self.facts if f.kind == kind]
        return found[index] if len(found) > index else None

    def side_relation(self, club: Side | None) -> str:
        """good | bad | neutral for a fan of `club`."""
        if club is None or self.moment.team is None:
            return "neutral"
        positive = self.moment.type.value not in {"red_card", "yellow_card"}
        mine = self.moment.team == club
        return "good" if mine == positive else "bad"

    def prompt_dict(self) -> dict[str, Any]:
        return {
            "moment_type": self.moment.type.value,
            "title": self.moment.title,
            "minute": self.moment.minute,
            "home": self.home,
            "away": self.away,
            "team": self.team,
            "opponent": self.opponent,
            "player": self.player,
            "score_after": f"{self.score[0]}-{self.score[1]}",
            "game_state": self.state,
            "late_in_match": self.late,
            "facts": [
                {"id": f.fact_id, "label": f.label, "value": f.value, "unit": f.unit, "display": f.display()}
                for f in self.facts
            ],
        }


def build_context(
    moment: Moment, stats: StatsEngine, score_before: tuple[int, int], memory: list[Fact] | None = None
) -> MomentContext:
    meta = stats.meta
    team = opp = None
    if moment.team:
        team = stats.team_name(moment.team)
        opp = stats.team_name(other(moment.team))
    player = stats.players.get(moment.player_id) if moment.player_id else None
    score = (stats.score["home"], stats.score["away"])
    state = "none"
    if moment.type.value == "goal" and moment.team:
        idx = 0 if moment.team == "home" else 1
        mine_b, opp_b = score_before[idx], score_before[1 - idx]
        mine_a = score[idx]
        if mine_b == 0 and opp_b == 0:
            state = "opener"
        elif mine_a == opp_b:
            state = "equaliser"
        elif mine_b == opp_b:
            state = "late_winner" if moment.minute >= 80 else "go_ahead"
        elif mine_b > opp_b:
            state = "extend_lead"
        elif mine_a < opp_b:
            state = "pull_back"
        # Comeback: scorer's team had trailed by 2+ earlier in the match and now leads.
        if mine_a > opp_b and getattr(stats, "_max_deficit", {}).get(moment.team, 0) >= 2:
            state = "comeback"
    return MomentContext(
        moment=moment,
        home=meta.home.short_name,
        away=meta.away.short_name,
        team=team,
        opponent=opp,
        player=player.name if player else None,
        player_short=player.short_name if player else None,
        score=score,
        score_before=score_before,
        period=stats.period,
        state=state,
        late=moment.minute >= 75,
        memory=memory or [],
    )
