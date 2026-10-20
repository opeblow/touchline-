"""Public analytic models: expected goals and pass difficulty.

These are the stats engine's *estimates*. The simulator uses its own hidden
"true" probabilities (with finishing skill, fatigue and noise), so xG here is a
model of the data, not a copy of it — just like in real football analytics.
"""

from __future__ import annotations

import math

from touchline.models import PITCH_LENGTH, PITCH_WIDTH

GOAL_HALF_WIDTH = 3.66


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def shot_geometry(ax: float, ay: float) -> tuple[float, float]:
    """Distance (m) to goal centre and the angle (rad) the goal mouth subtends."""
    dx = max(PITCH_LENGTH - ax, 0.1)
    dy = ay - PITCH_WIDTH / 2
    distance = math.hypot(dx, dy)
    a1 = math.atan2(dy + GOAL_HALF_WIDTH, dx)
    a2 = math.atan2(dy - GOAL_HALF_WIDTH, dx)
    return distance, abs(a1 - a2)


def expected_goals(
    ax: float,
    ay: float,
    *,
    header: bool = False,
    under_pressure: bool = False,
    assisted_by: str | None = None,
) -> float:
    """Logistic xG on distance and angle with context adjustments. Attacking frame."""
    distance, angle = shot_geometry(ax, ay)
    z = -1.55 - 0.11 * distance + 1.4 * angle
    if header:
        z -= 0.65
    if under_pressure:
        z -= 0.35
    if assisted_by in {"through", "cutback"}:
        z += 0.45
    elif assisted_by == "cross":
        z -= 0.1
    return round(min(max(_sigmoid(z), 0.005), 0.95), 3)


def pass_success_probability(
    distance: float,
    forward_m: float,
    *,
    under_pressure: bool,
    opponents_in_lane: int,
    pass_type: str | None = None,
) -> float:
    z = 3.4 - 0.055 * distance - 0.95 * under_pressure - 0.5 * opponents_in_lane - 0.018 * max(forward_m, 0)
    if pass_type in {"through", "cross"}:
        z -= 0.6
    elif pass_type == "back":
        z += 0.6
    return _sigmoid(z)


def pass_difficulty(
    distance: float,
    forward_m: float,
    *,
    under_pressure: bool,
    opponents_in_lane: int,
    pass_type: str | None = None,
) -> int:
    """0 (trivial) … 100 (near impossible). 1 − estimated completion probability."""
    p = pass_success_probability(
        distance,
        forward_m,
        under_pressure=under_pressure,
        opponents_in_lane=opponents_in_lane,
        pass_type=pass_type,
    )
    return int(round(100 * (1 - p)))


def threat_value(ax: float, ay: float) -> float:
    """Simple expected-threat surface: value of having the ball at (ax, ay)."""
    distance, angle = shot_geometry(ax, ay)
    return 0.02 + 0.5 * _sigmoid(-4.0 + 0.09 * (ax - 50)) * min(1.0, angle * 1.4) * math.exp(-distance / 40)
