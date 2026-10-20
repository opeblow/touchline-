"""Synthetic, football-realistic match generation. Fictional clubs and players only."""

from touchline.sim.engine import MatchData, simulate_match
from touchline.sim.league import build_league, get_team
from touchline.sim.scenario import Beat, Scenario

__all__ = ["MatchData", "simulate_match", "build_league", "get_team", "Scenario", "Beat"]
