import pytest

from touchline.intel.moments import MomentDetector
from touchline.intel.overlay import CueBuilder
from touchline.models import EventType, format_value
from touchline.stats.engine import StatsEngine
from touchline.stats.models import expected_goals, pass_difficulty


def test_xg_behaves():
    close = expected_goals(99, 34)
    far = expected_goals(80, 34)
    wide = expected_goals(99, 10)
    assert 0.3 < close < 0.95 and far < 0.08 and wide < close
    assert expected_goals(99, 34, header=True) < close
    assert expected_goals(99, 34, under_pressure=True) < close


@pytest.mark.parametrize("dist", [5, 15, 30, 45])
def test_pass_difficulty_monotonic(dist):
    easy = pass_difficulty(dist, 0, under_pressure=False, opponents_in_lane=0)
    hard = pass_difficulty(dist, 20, under_pressure=True, opponents_in_lane=2, pass_type="through")
    assert 0 <= easy < hard <= 100


def test_format_value():
    assert format_value(0.4123, "", "xg") == "0.41"
    assert format_value(112.4, "km/h") == "112 km/h"
    assert format_value(61.0, "%") == "61%"
    assert format_value(7.25, "km") == "7.2 km"


def test_engine_totals(comeback):
    s = StatsEngine(comeback.meta)
    for e in comeback.events:
        s.ingest(e)
    snap = s.snapshot()
    assert snap["score"] == [3, 2]
    assert snap["home"]["possession"] + snap["away"]["possession"] == pytest.approx(100, abs=0.2)
    passes = sum(1 for e in comeback.events if e.type == EventType.PASS)
    assert snap["home"]["passes"] + snap["away"]["passes"] == passes
    assert -100 <= snap["momentum"] <= 100 and 0 <= snap["chaos"] <= 100
    assert all(f.fact_id.startswith("F") for f in s.facts.values())


def test_physical_metrics(tracked):
    s = StatsEngine(tracked.meta, tracked.tracking)
    for e in tracked.events:
        s.ingest(e)
    outfield = [
        p
        for p in s.pstats.values()
        if p.on_pitch and s.players[p.player_id].position != "GK" and p.distance_m > 0
    ]
    km = sorted(p.distance_m / 1000 for p in outfield)
    assert 7 < km[len(km) // 2] < 13  # realistic distance covered per outfielder
    assert max(p.top_speed_kmh for p in outfield) < 38


def test_moments_and_cues(comeback):
    s = StatsEngine(comeback.meta)
    md, cb = MomentDetector(s, "t"), CueBuilder(s, "t")
    moments, cues = [], []
    for e in comeback.events:
        trg = s.ingest(e)
        moments += md.detect(e, trg)
        cues += cb.for_event(e, trg)
    types = [m.type.value for m in moments]
    assert types.count("goal") == 5 and "red_card" in types and types.count("phase") == 2
    for m in moments:
        assert m.facts and all(f.fact_id in s.facts for f in m.facts)
        assert 0 <= m.importance <= 100
    assert {"shot_speed", "xg_popup", "score_bug"} <= {c.template for c in cues}
    assert all(c.t_out > c.t_in for c in cues)
