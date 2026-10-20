from touchline.agents.context import build_context
from touchline.agents.guardian_rules import TEMPLATE_CONSTANTS, NameIndex, extract_numbers, verify_text
from touchline.agents.templates import LANGS, render_personalized
from touchline.intel.moments import MomentDetector
from touchline.stats.engine import StatsEngine


def _setup(match):
    s = StatsEngine(match.meta)
    md = MomentDetector(s, "t")
    out = []
    for e in match.events:
        before = (s.score["home"], s.score["away"])
        for m in md.detect(e, s.ingest(e)):
            out.append((m, build_context(m, s, before), e.outcome))
    return s, NameIndex(match.meta), out


def test_extract_numbers_handles_locales():
    assert extract_numbers("xG 0,41 at 112 km/h") == [0.41, 112.0]
    assert extract_numbers("٣٢ km/h") == [32.0]
    assert extract_numbers("cites F12 and F7") == []


def test_guardian_accepts_grounded_and_rejects_invented(comeback):
    s, names, moments = _setup(comeback)
    goal, ctx, _ = next(x for x in moments if x[0].type.value == "goal")
    xg = next(f for f in goal.facts if f.kind == "xg")
    ok = verify_text(f"A {xg.display()} xG chance, finished.", [xg.fact_id], s.facts, names=names)
    assert ok.approved
    bad = verify_text("A 0.87 xG chance, finished.", [xg.fact_id], s.facts, names=names)
    assert not bad.approved and "0.87" in bad.reasons[0]
    uncited = verify_text(f"A {xg.display()} xG chance.", [], s.facts, names=names)
    assert not uncited.approved


def test_guardian_rejects_foreign_players(comeback, league):
    s, names, moments = _setup(comeback)
    outsider = league[10].players[9].name
    v = verify_text(f"{outsider} would have scored that.", [], s.facts, names=names)
    assert not v.approved and outsider in v.reasons[0]


def test_every_template_is_grounded(comeback):
    s, names, moments = _setup(comeback)
    for m, ctx, outcome in moments:
        for lang in LANGS:
            for mode in ("analyst", "fan", "club", "player"):
                r = render_personalized(
                    ctx,
                    mode,
                    lang,
                    club="home",
                    focus_player_id=m.player_id,
                    focus_player_name=ctx.player,
                    outcome=outcome,
                )
                v = verify_text(
                    r.text, r.cited, s.facts, names=names, extra_numbers=[m.minute, *TEMPLATE_CONSTANTS]
                )
                assert v.approved, (m.type, lang, mode, v.reasons, r.text)
