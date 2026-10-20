"""Team shape model: where each of the 11 slots stands, given the ball and phase.

Used both by the simulator (to pick realistic pass targets and defenders) and by
the tracking generator (as targets for player movement). Coordinates are in the
team's attacking frame (attacking towards x = 105); mirror for the away side.
"""

from __future__ import annotations

import numpy as np

from touchline.models import PITCH_LENGTH, PITCH_WIDTH

# Base positions in possession with the ball at the centre spot. Slot order matches the
# squad template: 0 GK, 1 LB, 2 LCB, 3 RCB, 4 RB, 5 DM, 6 CM, 7 AM, 8 LW, 9 ST, 10 RW
FORMATIONS: dict[str, list[tuple[float, float, str]]] = {
    "4-3-3": [
        (6, 34, "GK"),
        (36, 8, "FB"),
        (30, 24, "CB"),
        (30, 44, "CB"),
        (36, 60, "FB"),
        (42, 34, "DM"),
        (54, 22, "CM"),
        (56, 46, "CM"),
        (72, 10, "W"),
        (78, 34, "ST"),
        (72, 58, "W"),
    ],
    "4-2-3-1": [
        (6, 34, "GK"),
        (36, 8, "FB"),
        (30, 24, "CB"),
        (30, 44, "CB"),
        (36, 60, "FB"),
        (44, 27, "DM"),
        (44, 41, "CM"),
        (62, 34, "AM"),
        (66, 12, "W"),
        (78, 34, "ST"),
        (66, 56, "W"),
    ],
    "4-4-2": [
        (6, 34, "GK"),
        (34, 8, "FB"),
        (30, 24, "CB"),
        (30, 44, "CB"),
        (34, 60, "FB"),
        (48, 27, "CM"),
        (48, 41, "CM"),
        (66, 40, "ST"),
        (56, 10, "W"),
        (68, 28, "ST"),
        (56, 58, "W"),
    ],
    "3-5-2": [
        (6, 34, "GK"),
        (50, 6, "FB"),
        (30, 22, "CB"),
        (28, 34, "CB"),
        (50, 62, "FB"),
        (44, 34, "DM"),
        (56, 22, "CM"),
        (56, 46, "CM"),
        (30, 46, "CB"),
        (74, 28, "ST"),
        (74, 42, "ST"),
    ],
    "5-3-2": [
        (6, 34, "GK"),
        (40, 6, "FB"),
        (28, 22, "CB"),
        (28, 46, "CB"),
        (40, 62, "FB"),
        (46, 34, "DM"),
        (54, 20, "CM"),
        (54, 48, "CM"),
        (26, 34, "CB"),
        (72, 28, "ST"),
        (72, 42, "ST"),
    ],
    "3-4-3": [
        (6, 34, "GK"),
        (50, 6, "FB"),
        (30, 22, "CB"),
        (28, 34, "CB"),
        (50, 62, "FB"),
        (46, 28, "DM"),
        (46, 40, "CM"),
        (30, 46, "CB"),
        (70, 12, "W"),
        (78, 34, "ST"),
        (70, 56, "W"),
    ],
    "5-4-1": [
        (6, 34, "GK"),
        (38, 6, "FB"),
        (28, 22, "CB"),
        (28, 46, "CB"),
        (38, 62, "FB"),
        (46, 28, "CM"),
        (46, 40, "CM"),
        (26, 34, "CB"),
        (56, 12, "W"),
        (74, 34, "ST"),
        (56, 56, "W"),
    ],
}


_BASE_CACHE: dict[str, np.ndarray] = {}


def base_positions(formation: str) -> np.ndarray:
    if formation not in _BASE_CACHE:
        _BASE_CACHE[formation] = np.array(
            [(x, y) for x, y, _ in FORMATIONS.get(formation, FORMATIONS["4-3-3"])], dtype=float
        )
    return _BASE_CACHE[formation].copy()


def team_shape_batch(
    formation: str,
    ball_ax: np.ndarray,
    ball_ay: np.ndarray,
    in_possession: np.ndarray,
    width: float = 0.5,
    press: float = 0.5,
) -> np.ndarray:
    """Vectorised team_shape over N instants. Returns (N, 11, 2) in the attacking frame."""
    n = len(ball_ax)
    base = base_positions(formation)
    pos = np.broadcast_to(base, (n, 11, 2)).copy()
    centre = PITCH_WIDTH / 2
    poss = in_possession.astype(bool)
    shift = (ball_ax - PITCH_LENGTH / 2) * 0.55 + np.where(poss, 6.0, -6.0 + 10.0 * (press - 0.5))
    pos[:, 1:, 0] += shift[:, None]
    stretch = 0.85 + 0.35 * width
    y_att = centre + (pos[:, 1:, 1] - centre) * stretch
    y_def = centre + (pos[:, 1:, 1] - centre) * 0.72 + ((ball_ay - centre) * 0.32)[:, None]
    x_def = pos[:, 1:, 0] * 0.9 + (ball_ax * 0.1)[:, None] - 3.0
    pos[:, 1:, 1] = np.where(poss[:, None], y_att, y_def)
    pos[:, 1:, 0] = np.where(poss[:, None], pos[:, 1:, 0], x_def)
    pos[:, 0, 0] = np.clip(5.0 + shift * 0.12, 2.0, 18.0)
    pos[:, 0, 1] = centre + (ball_ay - centre) * 0.12
    pos[..., 0] = np.clip(pos[..., 0], 1.0, PITCH_LENGTH - 1.0)
    pos[..., 1] = np.clip(pos[..., 1], 1.0, PITCH_WIDTH - 1.0)
    return pos


def slot_roles(formation: str) -> list[str]:
    return [r for _, _, r in FORMATIONS.get(formation, FORMATIONS["4-3-3"])]


def team_shape(
    formation: str,
    ball_ax: float,
    ball_ay: float,
    in_possession: bool,
    width: float = 0.5,
    press: float = 0.5,
) -> np.ndarray:
    """Return (11, 2) target positions in the attacking frame."""
    pos = base_positions(formation)
    # Whole block slides with the ball, and pushes up when in possession.
    shift = (ball_ax - PITCH_LENGTH / 2) * 0.55 + (6.0 if in_possession else -6.0 + 10.0 * (press - 0.5))
    pos[1:, 0] += shift
    # Width: stretch when attacking, squeeze towards the ball side when defending.
    centre = PITCH_WIDTH / 2
    if in_possession:
        stretch = 0.85 + 0.35 * width
        pos[1:, 1] = centre + (pos[1:, 1] - centre) * stretch
    else:
        pos[1:, 1] = centre + (pos[1:, 1] - centre) * 0.72 + (ball_ay - centre) * 0.32
        # Defensive line compresses vertically toward the ball.
        pos[1:, 0] = pos[1:, 0] * 0.9 + ball_ax * 0.1 - 3.0
    # Goalkeeper hugs the goal.
    pos[0] = (float(np.clip(5.0 + shift * 0.12, 2.0, 18.0)), centre + (ball_ay - centre) * 0.12)
    pos[:, 0] = np.clip(pos[:, 0], 1.0, PITCH_LENGTH - 1.0)
    pos[:, 1] = np.clip(pos[:, 1], 1.0, PITCH_WIDTH - 1.0)
    return pos


def to_attacking(x: float, y: float, side: str) -> tuple[float, float]:
    """Absolute → attacking frame of `side` (home attacks right)."""
    return (x, y) if side == "home" else (PITCH_LENGTH - x, PITCH_WIDTH - y)


def to_absolute(ax: float, ay: float, side: str) -> tuple[float, float]:
    return (ax, ay) if side == "home" else (PITCH_LENGTH - ax, PITCH_WIDTH - ay)


def shape_absolute(pos_att: np.ndarray, side: str) -> np.ndarray:
    if side == "home":
        return pos_att
    out = pos_att.copy()
    out[:, 0] = PITCH_LENGTH - out[:, 0]
    out[:, 1] = PITCH_WIDTH - out[:, 1]
    return out
