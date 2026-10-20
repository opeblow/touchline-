"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import WatchParty, { FloatingReactions } from "@/components/WatchParty";
import MetricPin, { METRICS } from "@/components/MetricPin";
import { COMEBACK_CALL, EQUALISER_CALL, GOAL_CALL, MatchAudio, playByPlay } from "@/lib/audio";
import AskBox from "@/components/AskBox";
import CommentaryFeed from "@/components/CommentaryFeed";
import MomentFeed from "@/components/MomentFeed";
import MomentumWave from "@/components/MomentumWave";
import Nav from "@/components/Nav";
import OverlayStage from "@/components/OverlayStage";
import PersonalizeBar from "@/components/PersonalizeBar";
import Pitch from "@/components/Pitch";
import Stadium3D from "@/components/Stadium3D";
import ScoreBug from "@/components/ScoreBug";
import StatCompare from "@/components/StatCompare";
import { playersById } from "@/lib/format";
import { useMatch, type Prefs } from "@/lib/useMatch";

const SPEEDS = [1, 4, 8, 16, 30];

function ChaosMeter({ value, control, homeCode, awayCode }: { value: number; control: string | null; homeCode: string; awayCode: string }) {
  const label = value >= 70 ? "Chaos" : value <= 30 ? "Control" : "Contested";
  return (
    <div>
      <div className="row between" style={{ marginBottom: 6 }}>
        <span className="eyebrow">Control vs Chaos</span>
        <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{value.toFixed(0)}<span className="faint">/100</span></span>
      </div>
      <div style={{ position: "relative", height: 10, borderRadius: 5, background: "linear-gradient(90deg, var(--pitch) 0%, #cfd6c4 50%, var(--signal) 85%, var(--danger) 100%)" }}>
        <span style={{ position: "absolute", top: -4, left: `calc(${value}% - 2px)`, width: 4, height: 18, borderRadius: 2, background: "var(--ink)", transition: "left 600ms var(--ease)" }} />
      </div>
      <div className="row between" style={{ marginTop: 6, fontSize: 12.5 }}>
        <span className="muted">{label}{control ? ` · ${control === "home" ? homeCode : awayCode} in control` : ""}</span>
        <span className="faint">turnovers · duels · chain length</span>
      </div>
    </div>
  );
}

function Live() {
  const params = useSearchParams();
  const matchId = params.get("match") || "demo";
  const [prefs, setPrefs] = useState<Prefs>(() => ({
    mode: (["analyst", "fan", "club", "player"].includes(params.get("mode") ?? "") ? params.get("mode") : "fan") as Prefs["mode"],
    lang: params.get("lang") || "en",
    club: params.get("club") === "away" ? "away" : params.get("club") === "home" ? "home" : null,
    player_id: params.get("player"),
  }));
  const [view, setView] = useState<"stadium" | "pitch" | "broadcast">("stadium");
  const [metric, setMetric] = useState<string>(params.get("metric") || "xg");
  const [tab, setTab] = useState<"moments" | "commentary" | "party" | "ask">("moments");
  const { state, control, setSpeed, send } = useMatch(matchId, prefs);
  const { meta, stats, status } = state;
  const players = useMemo(() => playersById(meta), [meta]);
  const numbers = useMemo(() => Object.fromEntries(Object.entries(players).map(([id, p]) => [id, p.number])), [players]);
  const activeCues = state.cues.filter((c) => c.t_in <= state.now && state.now <= c.t_out);

  // ---- sound: crowd, whistle, spoken commentary
  const audioRef = useRef<MatchAudio | null>(null);
  const [sound, setSound] = useState(false);
  const [celebrate, setCelebrate] = useState<{ side: "home" | "away"; at: number } | null>(null);
  const lastSeq = useRef(0);
  const lastLine = useRef("");
  const seenMoments = useRef(new Set<string>());
  function toggleSound() {
    if (!audioRef.current) audioRef.current = new MatchAudio();
    if (!sound) audioRef.current.start();
    else audioRef.current.stop(), (audioRef.current = null);
    setSound(!sound);
  }
  useEffect(() => () => audioRef.current?.stop(), []);
  // Play-by-play + crowd swells from the live event feed.
  useEffect(() => {
    const a = audioRef.current;
    const evs = state.events;
    if (!evs.length) return;
    const fresh = evs.filter((e: any) => e.seq > lastSeq.current);
    lastSeq.current = Math.max(lastSeq.current, ...evs.map((e: any) => e.seq));
    if (!a || !sound) return;
    const name = (id: string | null) => (id && players[id] ? players[id].short_name : "");
    const slow = (status?.speed ?? 8) <= 8;
    for (const e of fresh.slice(-3)) {
      const pbp = playByPlay(e, name, prefs.lang);
      // The home end reacts like home fans.
      const homeAct = e.team === "home";
      if (e.type === "shot" && e.outcome !== "goal") {
        if (homeAct) { a.crowd("ooh", 1); setTimeout(() => a.crowd("applause", 0.5), 1600); }
        else a.crowd(e.outcome === "saved" ? "cheer" : "ooh", 0.45);
      } else if (e.type === "save" && e.team === "home") setTimeout(() => a.crowd("applause", 0.8), 400);
      else if (e.type === "foul" && !homeAct && Math.random() < 0.6) a.crowd("boo", 0.5);
      else if (e.type === "foul" && homeAct && Math.random() < 0.3) a.crowd("whistles", 0.6);
      else if (e.type === "card") a.crowd(homeAct ? "boo" : "cheer", e.outcome === "red" ? 1 : 0.6);
      else if (e.type === "tackle" && homeAct && Math.random() < 0.5) a.crowd("applause", 0.35);
      else if (e.type === "match_end") {
        const sc = stats?.score ?? [0, 0];
        a.crowd(sc[0] > sc[1] ? "roar" : sc[0] < sc[1] ? "boo" : "applause", 1);
      }
      if (!pbp) continue;
      a.react(pbp.level);
      if (pbp.whistle) a.whistle(pbp.whistle, e.type === "match_end" || e.type === "half_end");
      if (slow && pbp.text) a.say(pbp.text, prefs.lang, e.type === "shot" ? 2 : 1, e.type === "shot" ? "excited" : "calm");
    }
  }, [state.events, sound, players, prefs.lang, status?.speed]);
  // Agent commentary on key moments (priority) + goal celebrations.
  useEffect(() => {
    const l = state.commentary[state.commentary.length - 1];
    if (!l || l.line_id === lastLine.current) return;
    lastLine.current = l.line_id;
    if (sound && audioRef.current && l.lang === prefs.lang) {
      const emotion = l.tone === "excited" ? "excited" : l.tone === "somber" ? "somber" : l.tone === "build" ? "build" : "calm";
      audioRef.current.say(l.text, l.lang, 2, emotion);
    }
  }, [state.commentary, sound, prefs.lang]);
  // Goals: crowd + commentator react from the home fans' point of view.
  const running = useRef<[number, number]>([0, 0]);
  const worstDeficit = useRef<[number, number]>([0, 0]);
  useEffect(() => {
    const a = audioRef.current;
    for (const m of state.moments) {
      if (seenMoments.current.has(m.moment_id)) continue;
      seenMoments.current.add(m.moment_id);
      if (m.type === "goal" && m.team) {
        const i = m.team === "home" ? 0 : 1;
        const sc = running.current;
        sc[i] += 1;
        worstDeficit.current[0] = Math.max(worstDeficit.current[0], sc[1] - sc[0]);
        worstDeficit.current[1] = Math.max(worstDeficit.current[1], sc[0] - sc[1]);
        const level = sc[0] === sc[1];
        const comeback = sc[i] > sc[1 - i] && worstDeficit.current[i] >= 2;
        setCelebrate({ side: m.team, at: Date.now() });
        if (!a || !sound) continue;
        const live = Date.now();
        if (m.team === "home") {
          a.crowd("roar", comeback || level ? 1.3 : 1.1);
          setTimeout(() => a.crowd("applause", 1), 2500);
          setTimeout(() => a.crowd("chant", comeback ? 1.2 : 0.9), 5200);
          a.say(GOAL_CALL[prefs.lang] ?? GOAL_CALL.en, prefs.lang, 2, "excited");
          if (comeback) a.say(COMEBACK_CALL[prefs.lang] ?? COMEBACK_CALL.en, prefs.lang, 2, "excited");
          else if (level) a.say(EQUALISER_CALL[prefs.lang] ?? EQUALISER_CALL.en, prefs.lang, 2, "excited");
        } else {
          a.crowd("groan", 1.1);
          a.crowd("cheer", 0.35); // the away end
          setTimeout(() => a.crowd("whistles", 0.5), 2200);
          a.say(GOAL_CALL[prefs.lang] ?? GOAL_CALL.en, prefs.lang, 2, comeback || level ? "excited" : "somber");
          if (comeback) a.say(COMEBACK_CALL[prefs.lang] ?? COMEBACK_CALL.en, prefs.lang, 2, "excited");
          else if (level) a.say(EQUALISER_CALL[prefs.lang] ?? EQUALISER_CALL.en, prefs.lang, 2, "build");
        }
        void live;
      } else if (a && sound) {
        if (m.type === "red_card") a.crowd(m.team === "home" ? "boo" : "roar", 0.9);
        else if (m.type === "big_chance") a.react(0.9);
        else if (m.type === "momentum_swing" && m.team === "home") a.crowd("chant", 0.7);
      }
    }
  }, [state.moments, sound, prefs.lang]);

  if (!meta) {
    return (
      <>
        <Nav />
        <main className="container" style={{ padding: "60px 24px" }}>
          <div className="analysing"><i /><i /><i /> {state.error ? `Can't reach the match service: ${state.error}` : "Loading match and generating synthetic data…"}</div>
        </main>
      </>
    );
  }
  const home = { code: meta.home.code, color: meta.home.primary };
  const away = { code: meta.away.code, color: meta.away.primary };
  const score = stats?.score ?? [0, 0];
  const live = status?.status === "live";
  const finished = status?.status === "finished";
  const focus = prefs.mode === "player" ? prefs.player_id : null;
  const focusStats = focus && stats?.players[focus];

  return (
    <>
      <Nav
        right={
          <span className="row" style={{ gap: 8, fontSize: 13 }}>
            {live && <span className="live-dot" aria-hidden />}
            <span className="mono">{live ? "LIVE" : status?.status?.toUpperCase()}</span>
            <span className="faint hide-sm">· {status?.viewers ?? 0} viewing · {status?.llm === "offline" ? "offline templates" : status?.model_fast}</span>
          </span>
        }
      />
      <main className="container" style={{ padding: "20px 24px 60px" }}>
        {/* Header */}
        <section className="row wrap between" style={{ gap: 16, marginBottom: 16 }}>
          <div className="row wrap" style={{ gap: 18 }}>
            <ScoreBug home={home} away={away} score={score as [number, number]} minute={stats?.minute ?? 0} period={stats?.period ?? 1} size="lg" finished={finished} />
            <div>
              <div className="display" style={{ fontSize: 22, lineHeight: 1.1 }}>{meta.home.name} v {meta.away.name}</div>
              <div className="muted" style={{ fontSize: 13 }}>
                Matchday {meta.matchday} · {meta.venue} · {String(meta.scenario.label ?? "")}
              </div>
            </div>
          </div>
          <div className="row wrap" style={{ gap: 8 }}>
            {!live && !finished && (
              <button className="btn green" onClick={() => control(status?.status === "paused" ? "resume" : "start", 8)}>
                {status?.status === "paused" ? "Resume" : "Kick off"}
              </button>
            )}
            {live && <button className="btn secondary" onClick={() => control("pause")}>Pause</button>}
            {finished && <button className="btn green" onClick={() => control("restart").then(() => control("start", 8))}>Replay match</button>}
            <button className={`btn ${sound ? "" : "secondary"}`} onClick={toggleSound} title="Crowd, whistle and spoken commentary">
              {sound ? "Sound on" : "Turn on sound"}
            </button>
            <div className="seg" aria-label="Replay speed">
              {SPEEDS.map((s) => (
                <button key={s} className={status?.speed === s ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>
              ))}
            </div>
          </div>
        </section>

        <section className="row wrap between" style={{ gap: 12, marginBottom: 16 }}>
          <PersonalizeBar prefs={prefs} onChange={setPrefs} meta={meta} />
          <div className="seg" aria-label="View">
            <button className={view === "stadium" ? "on" : ""} onClick={() => setView("stadium")}>3D stadium</button>
            <button className={view === "pitch" ? "on" : ""} onClick={() => setView("pitch")}>2D pitch</button>
            <button className={view === "broadcast" ? "on" : ""} onClick={() => setView("broadcast")}>Broadcast view</button>
          </div>
        </section>

        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(320px, 400px)", alignItems: "start" }} data-live-grid>
          {/* Left */}
          <div className="grid">
            <div className="card" style={{ padding: 10, position: "relative" }}>
              {view === "stadium" ? (
                <div style={{ position: "relative" }}>
                  <Stadium3D frame={state.frame} ids={state.ids} players={players} homeColor={home.color} awayColor={away.color} focusId={focus} height="min(62vh, 620px)" initialCam={focus ? "follow" : "broadcast"} celebrate={celebrate} events={state.events} speed={status?.speed} />
                  <FloatingReactions reactions={state.party.reactions} />
                  {state.commentary.length > 0 && (
                    <div key={state.commentary[state.commentary.length - 1].line_id} className="fade-in" style={{ position: "absolute", left: 14, bottom: 14, maxWidth: "70%", background: "rgba(10,14,12,0.82)", color: "#fff", padding: "8px 12px", borderRadius: 8, fontSize: 14, borderLeft: "4px solid var(--signal)" }}>
                      {state.commentary[state.commentary.length - 1].text}
                    </div>
                  )}
                </div>
              ) : view === "pitch" ? (
                <Pitch frame={state.frame} ids={state.ids} numbers={numbers} homeColor={home.color} awayColor={away.color} focusId={focus} cues={activeCues} />
              ) : (
                <div style={{ borderRadius: 12, overflow: "hidden" }}>
                  <OverlayStage
                    cues={state.cues} now={state.now} minute={stats?.minute ?? 0} period={stats?.period ?? 1} score={score as [number, number]}
                    home={home} away={away} finished={finished}
                    background={<Stadium3D frame={state.frame} ids={state.ids} players={players} homeColor={home.color} awayColor={away.color} focusId={focus} showControls={false} celebrate={celebrate} events={state.events} speed={status?.speed} />}
                  />
                </div>
              )}
              <div className="row wrap" style={{ gap: 8, padding: "10px 6px 2px", fontSize: 12.5 }}>
                <span className="eyebrow">Live feed</span>
                {state.events.slice(-5).reverse().map((e) => (
                  <span key={e.event_id} className="chip" title={e.event_id}>
                    <span className="mono">{e.minute}&apos;</span> {e.type.replace("_", " ")}
                    {e.player_id && players[e.player_id] ? ` · ${players[e.player_id].short_name}` : ""}
                    {e.metrics?.difficulty !== undefined ? ` · diff ${e.metrics.difficulty}` : ""}
                    {e.metrics?.xg !== undefined ? ` · xG ${e.metrics.xg.toFixed(2)}` : ""}
                  </span>
                ))}
              </div>
            </div>

            <MetricPin metric={metric} onChange={setMetric} stats={stats} meta={meta} focusId={focus} playerName={(id) => players[id]?.name ?? id} />

            {focusStats && focus && players[focus] && (
              <div className="card" style={{ padding: 16 }}>
                <div className="row between">
                  <div>
                    <span className="eyebrow">Player cam</span>
                    <div className="display" style={{ fontSize: 26 }}>#{players[focus].number} {players[focus].name}</div>
                  </div>
                  <span className="chip dark mono">rating {focusStats.rating.toFixed(1)}</span>
                </div>
                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", marginTop: 12 }}>
                  {[
                    ["Distance", `${focusStats.distance_km.toFixed(2)} km`], ["Top speed", `${focusStats.top_speed.toFixed(1)} km/h`],
                    ["Sprints", focusStats.sprints], ["Passes", `${focusStats.passes} · ${focusStats.pass_accuracy.toFixed(0)}%`],
                    ["Hardest pass", `${focusStats.hardest_pass}/100`], ["Shots · xG", `${focusStats.shots} · ${focusStats.xg.toFixed(2)}`],
                    ["Tackles + int.", focusStats.tackles + focusStats.interceptions], ["Touches", focusStats.touches],
                  ].map(([k, v]) => (
                    <div key={String(k)}>
                      <div className="eyebrow" style={{ fontSize: 10.5 }}>{k}</div>
                      <div className="mono" style={{ fontSize: 18, fontWeight: 600 }}>{v}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
              <div className="panel">
                <div className="panel-head"><span className="panel-title">Momentum</span><span className="mono muted" style={{ fontSize: 12 }}>{stats ? (stats.momentum >= 0 ? `${home.code} +${stats.momentum.toFixed(0)}` : `${away.code} +${Math.abs(stats.momentum).toFixed(0)}`) : ""}</span></div>
                <div className="panel-body stack" style={{ gap: 18 }}>
                  <MomentumWave series={stats?.momentum_series ?? []} homeColor={home.color} awayColor={away.color} moments={state.moments} homeCode={home.code} awayCode={away.code} />
                  <ChaosMeter value={stats?.chaos ?? 35} control={stats?.control ?? null} homeCode={home.code} awayCode={away.code} />
                </div>
              </div>
              <div className="panel">
                <div className="panel-head">
                  <span className="panel-title">Match stats</span>
                  <span className="row" style={{ gap: 6, fontSize: 12 }}><b style={{ color: home.color }}>{home.code}</b><span className="faint">v</span><b style={{ color: away.color }}>{away.code}</b></span>
                </div>
                <div className="panel-body" style={{ paddingTop: 6 }}>
                  {stats && <StatCompare home={stats.home} away={stats.away} homeColor={home.color} awayColor={away.color} compact={prefs.mode === "fan"} />}
                </div>
              </div>
            </div>

            {state.tactical.length > 0 && (
              <div className="panel">
                <div className="panel-head"><span className="panel-title">Tactical notes</span><span className="chip">Tactician agent</span></div>
                <div>
                  {state.tactical.slice().reverse().map((t) => (
                    <div key={t.shift_id} style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
                      <span className="mono faint" style={{ fontSize: 12 }}>{t.window[0]}&apos;–{t.window[1]}&apos;</span>
                      <p style={{ margin: "2px 0 0", fontSize: 14.5 }}>{t.summary}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right */}
          <aside className="panel" style={{ position: "sticky", top: 76 }}>
            <div className="panel-head" style={{ padding: 10 }}>
              <div className="seg" role="tablist">
                <button className={tab === "moments" ? "on" : ""} onClick={() => setTab("moments")}>Key moments</button>
                <button className={tab === "commentary" ? "on" : ""} onClick={() => setTab("commentary")}>Commentary</button>
                <button className={tab === "party" ? "on" : ""} onClick={() => setTab("party")}>Watch party{state.party.members.length ? ` · ${state.party.members.length}` : ""}</button>
                <button className={tab === "ask" ? "on" : ""} onClick={() => setTab("ask")}>Ask</button>
              </div>
            </div>
            <div className="scroll" style={{ maxHeight: "calc(100vh - 160px)" }}>
              {tab === "moments" && (
                <MomentFeed matchId={matchId} moments={state.moments} insights={state.insights} personalized={state.personalized} lang={prefs.lang} minImportance={prefs.mode === "analyst" ? 25 : 40} highlightKinds={METRICS.find((x) => x.id === metric)?.kinds} />
              )}
              {tab === "commentary" && <CommentaryFeed lines={state.commentary} lang={prefs.lang} />}
              {tab === "ask" && <div style={{ padding: 16 }}><AskBox matchId={matchId} lang={prefs.lang} /></div>}
              {tab === "party" && <WatchParty party={state.party} send={send} connected={state.connected} meta={meta} />}
            </div>
            {finished && (
              <div style={{ padding: 14, borderTop: "1px solid var(--line)" }}>
                <Link className="btn" href={`/recap?match=${matchId}`} style={{ width: "100%" }}>Read the full-time recap →</Link>
              </div>
            )}
          </aside>
        </div>
      </main>
      <style>{`@media (max-width: 980px){ [data-live-grid]{ grid-template-columns: 1fr !important; } [data-live-grid] aside{ position: static !important; } }`}</style>
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Live />
    </Suspense>
  );
}
