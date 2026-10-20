"""Auto-eventing: derive pass and speed metrics from video instead of tagging them by hand.

Pipeline (all synthetic, no real footage):
  1. render   — draw a top-down "broadcast tactical cam" video from tracking (with sensor noise
                and random occlusions), 4 px per metre.
  2. detect   — computer vision on pixels only: colour segmentation → blobs → player and
                ball positions per frame (no access to the event feed).
  3. derive   — possession = nearest player to the ball; a pass = possession moving between
                two players of the same team with ball travel; ball speed from the ball track.
  4. score    — compare against the ground-truth event feed: precision, recall, timing error
                and ball-speed error.

This is the hackathon's "auto-eventing" stretch goal, made measurable.
"""

from __future__ import annotations

import base64
import math
import struct
import zlib
from dataclasses import dataclass
from typing import Any

import numpy as np

from touchline.models import PITCH_LENGTH, PITCH_WIDTH, EventType
from touchline.sim.engine import MatchData

PX = 4  # pixels per metre
W, H = int(PITCH_LENGTH * PX), int(PITCH_WIDTH * PX)
GRASS = np.array([46, 117, 80], dtype=np.int16)
BALL = np.array([250, 250, 250], dtype=np.int16)


def _hex(c: str) -> np.ndarray:
    c = c.lstrip("#")
    return np.array([int(c[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.int16)


def kit_colors(data: MatchData) -> tuple[np.ndarray, np.ndarray]:
    """Pick contrasting kits, like a referee would: avoid the grass and each other."""

    def dist(a: np.ndarray, b: np.ndarray) -> int:
        return int(np.abs(a - b).sum())

    home_opts = [_hex(data.meta.home.primary), _hex(data.meta.home.secondary)]
    home = next((c for c in home_opts if dist(c, GRASS) > 120 and dist(c, BALL) > 120), home_opts[0])
    away_opts = [
        _hex(data.meta.away.primary),
        _hex(data.meta.away.secondary),
        np.array([20, 20, 20], dtype=np.int16),
    ]
    away = next(
        (c for c in away_opts if dist(c, GRASS) > 120 and dist(c, home) > 150 and dist(c, BALL) > 120),
        away_opts[-1],
    )
    return home, away


@dataclass
class Detection:
    t: float
    ball: tuple[float, float] | None
    home: list[tuple[float, float]]
    away: list[tuple[float, float]]


def render_frame(data: MatchData, i: int, rng: np.random.Generator, noise: float = 6.0) -> np.ndarray:
    tr = data.tracking
    img = np.empty((H, W, 3), dtype=np.int16)
    img[:] = GRASS
    yy, xx = np.mgrid[-6:7, -6:7]
    disc = (xx**2 + yy**2) <= 5.5**2
    home, away = kit_colors(data)
    cols = [home] * 11 + [away] * 11
    for s in range(22):
        p = tr.pos[i, s]
        if np.isnan(p[0]):
            continue
        if rng.random() < 0.02:  # occasional occlusion (camera graphics, other players)
            continue
        cx, cy = int(p[0] * PX), int(p[1] * PX)
        y0, y1, x0, x1 = cy - 6, cy + 7, cx - 6, cx + 7
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
            continue
        img[y0:y1, x0:x1][disc] = cols[s]
    bx, by = int(tr.ball[i, 0] * PX), int(tr.ball[i, 1] * PX)
    if 2 <= bx < W - 2 and 2 <= by < H - 2:
        img[by - 2 : by + 3, bx - 2 : bx + 3] = BALL
    img += rng.normal(0, noise, img.shape).astype(np.int16)
    return np.clip(img, 0, 255).astype(np.uint8)


def _blobs(mask: np.ndarray, min_px: int = 25) -> list[tuple[float, float]]:
    """Greedy clustering of mask pixels into blobs; returns centroids in metres."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0 or len(xs) > 12000:  # nothing, or a colour clash flooding the frame
        return []
    pts = np.stack([xs, ys], axis=1).astype(float)
    out = []
    remaining = np.ones(len(pts), dtype=bool)
    while remaining.any():
        seed = pts[np.argmax(remaining)]
        near = remaining & (np.abs(pts[:, 0] - seed[0]) <= 9) & (np.abs(pts[:, 1] - seed[1]) <= 9)
        c = pts[near].mean(axis=0)
        near = remaining & (np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1]) <= 9)
        if near.sum() >= min_px:
            c = pts[near].mean(axis=0)
            out.append((c[0] / PX, c[1] / PX))
        remaining &= ~near
    return out


def detect(img: np.ndarray, home: np.ndarray, away: np.ndarray, t: float) -> Detection:
    f = img.astype(np.int16)
    ball_mask = (f > 225).all(axis=2)
    grass = np.abs(f - GRASS).sum(axis=2) < 45
    ball = None
    ys, xs = np.nonzero(ball_mask)
    if len(xs) >= 4:
        ball = (float(xs.mean()) / PX, float(ys.mean()) / PX)

    def near(col: np.ndarray) -> np.ndarray:
        return (np.abs(f - col).sum(axis=2) < 70) & ~ball_mask & ~grass

    return Detection(t=t, ball=ball, home=_blobs(near(home)), away=_blobs(near(away)))


def derive_passes(dets: list[Detection], hz: float) -> list[dict[str, Any]]:
    """Possession chain from detections → completed passes with ball speed."""
    passes = []
    owner: tuple[str, int, tuple[float, float]] | None = None  # (team, blob idx, position when released)
    last_ball: tuple[float, float] | None = None
    flight_start_t = None
    flight_speed = 0.0
    for d in dets:
        if d.ball is None:
            continue
        if last_ball is not None:
            v = math.hypot(d.ball[0] - last_ball[0], d.ball[1] - last_ball[1]) * hz * 3.6
            if v < 150:
                flight_speed = max(flight_speed, v)
        last_ball = d.ball
        cands = [("home", p) for p in d.home] + [("away", p) for p in d.away]
        if not cands:
            continue
        team, pos = min(cands, key=lambda c: math.hypot(c[1][0] - d.ball[0], c[1][1] - d.ball[1]))
        dist = math.hypot(pos[0] - d.ball[0], pos[1] - d.ball[1])
        if dist > 2.4:
            if owner is not None and flight_start_t is None:
                flight_start_t = d.t
            continue
        if owner is None:
            owner = (team, 0, pos)
            flight_speed = 0.0
            continue
        moved = math.hypot(pos[0] - owner[2][0], pos[1] - owner[2][1])
        if flight_start_t is not None and moved >= 6:
            passes.append(
                {
                    "t_release": round(flight_start_t, 2),
                    "t_receive": round(d.t, 2),
                    "team": owner[0],
                    "to_team": team,
                    "complete": team == owner[0],
                    "distance_m": round(moved, 1),
                    "peak_ball_speed_kmh": round(flight_speed, 1),
                }
            )
        owner = (team, 0, pos)
        flight_start_t = None
        flight_speed = 0.0
    return passes


def png_b64(img: np.ndarray) -> str:
    """Minimal PNG encoder (no imaging dependency)."""
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode()


def run(
    data: MatchData, from_minute: int = 60, to_minute: int = 70, seed: int = 0, tolerance_s: float = 1.2
) -> dict[str, Any]:
    tr = data.tracking
    if tr is None:
        raise ValueError("match has no tracking")
    rng = np.random.default_rng(seed)
    home, away = kit_colors(data)
    # Map match minutes to tracking time using the event stream.
    in_window = [e for e in data.events if from_minute <= e.minute < to_minute]
    if not in_window:
        raise ValueError("empty window")
    t0, t1 = in_window[0].t, in_window[-1].t
    i0, i1 = tr.index_at(t0), tr.index_at(t1)
    dets, sample = [], None
    for i in range(i0, i1 + 1):
        img = render_frame(data, i, rng)
        if sample is None and i >= (i0 + i1) // 2:
            sample = img
        dets.append(detect(img, home, away, float(tr.times[i])))
    detected = derive_passes(dets, tr.hz)
    truth = [
        e for e in in_window if e.type == EventType.PASS and e.outcome == "complete" and e.duration >= 0.4
    ]
    matched, used = 0, set()
    timing, speed_err = [], []
    for e in truth:
        best = None
        for k, d in enumerate(detected):
            if k in used or not d["complete"]:
                continue
            dt = abs(d["t_release"] - e.t)
            if dt <= tolerance_s and (best is None or dt < best[0]):
                best = (dt, k)
        if best:
            used.add(best[1])
            matched += 1
            timing.append(best[0])
            true_speed = (
                math.hypot((e.end_x or e.x) - e.x, (e.end_y or e.y) - e.y) / max(e.duration, 0.05) * 3.6
            )
            speed_err.append(abs(detected[best[1]]["peak_ball_speed_kmh"] - true_speed))
    det_complete = [d for d in detected if d["complete"]]
    precision = matched / len(det_complete) if det_complete else 0.0
    recall = matched / len(truth) if truth else 0.0
    ball_seen = sum(d.ball is not None for d in dets) / len(dets)
    players_seen = float(np.mean([len(d.home) + len(d.away) for d in dets]))
    return {
        "window": [from_minute, to_minute],
        "frames": len(dets),
        "resolution": [W, H],
        "ball_detection_rate": round(ball_seen, 3),
        "players_detected_per_frame": round(players_seen, 1),
        "passes_truth": len(truth),
        "passes_detected": len(det_complete),
        "turnovers_detected": len(detected) - len(det_complete),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
        "median_timing_error_s": round(float(np.median(timing)), 2) if timing else None,
        "median_speed_error_kmh": round(float(np.median(speed_err)), 1) if speed_err else None,
        "sample_detections": detected[:8],
        "sample_frame_png": png_b64(sample) if sample is not None else None,
    }
