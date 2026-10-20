import numpy as np

from touchline.models import EventType
from touchline.sim import simulate_match
from touchline.sim.scenario import PRESETS, parse_scenario_text


def test_deterministic(league):
    a = simulate_match(league[3], league[4], seed=11, with_tracking=False)
    b = simulate_match(league[3], league[4], seed=11, with_tracking=False)
    assert [e.model_dump() for e in a.events] == [e.model_dump() for e in b.events]


def test_event_stream_is_well_formed(comeback):
    evs = comeback.events
    assert 1200 < len(evs) < 2600
    assert [e.seq for e in evs] == list(range(1, len(evs) + 1))
    assert all(evs[i].t <= evs[i + 1].t for i in range(len(evs) - 1))
    assert evs[0].type == EventType.KICKOFF and evs[-1].type == EventType.MATCH_END
    assert all(0 <= e.x <= 105 and 0 <= e.y <= 68 for e in evs)
    assert {EventType.PASS, EventType.SHOT, EventType.TACKLE, EventType.PRESSURE} <= {e.type for e in evs}


def test_scripted_comeback_happens(comeback):
    assert comeback.final_score() == (3, 2)
    reds = [e for e in comeback.events if e.type == EventType.CARD and e.outcome == "red"]
    assert any(e.team == "away" and 55 <= e.minute <= 62 for e in reds)


def test_tracking_is_physically_plausible(tracked):
    tr = tracked.tracking
    speeds = tr.speeds_kmh()
    assert np.percentile(speeds, 99.9) < 38  # nobody runs faster than a top sprinter
    assert np.median(speeds) < 12
    on = ~np.isnan(tr.pos[..., 0])
    assert on[0].sum() == 22


def test_scenario_parser():
    s = parse_scenario_text("a comeback with a red card at 60'")
    kinds = [b.kind for b in s.beats]
    assert "red_card" in kinds and kinds.count("goal") >= 3
    assert any(b.kind == "red_card" and b.minute == 60 for b in s.beats)
    assert parse_scenario_text("chaos").label == PRESETS["chaos"].label


def test_autoevent_detects_from_pixels(tracked):
    from touchline.autoevent import run

    r = run(tracked, from_minute=30, to_minute=31)
    assert r["ball_detection_rate"] > 0.8
    assert r["players_detected_per_frame"] > 15
    assert r["passes_detected"] > 0 and r["sample_frame_png"]
