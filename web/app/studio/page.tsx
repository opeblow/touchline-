"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Nav from "@/components/Nav";
import { API_BASE, api, post } from "@/lib/api";

interface Club { id: string; name: string; short_name: string; code: string; primary: string; style: Record<string, any> }

const EXAMPLES = [
  "A comeback: Harbour go 2-0 up, then a red card at 58' and the home side turn it around",
  "A cagey, tactical 0-0 with very few chances",
  "End-to-end chaos with lots of turnovers and two red cards",
  "Total dominance by the home side from the first whistle",
];

function AutoEvent() {
  const [busy, setBusy] = useState(false);
  const [from, setFrom] = useState(60);
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true); setErr(null);
    try { setR(await api(`/api/matches/demo/autoevent?from_minute=${from}&minutes=3`)); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  return (
    <section className="card" style={{ padding: 22, marginTop: 20 }}>
      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 28, alignItems: "start" }} data-studio-grid>
        <div>
          <span className="eyebrow">Auto-eventing from video</span>
          <h2 className="display" style={{ fontSize: 32, margin: "4px 0 8px" }}>Events from pixels, scored against the truth</h2>
          <p className="muted" style={{ marginTop: 0, fontSize: 14.5 }}>
            Touchline renders a synthetic tactical-camera video (with sensor noise and occlusions). A computer-vision pass then finds the
            players and the ball, detects passes and measures ball speed from pixels alone. Those detections are scored against the
            ground-truth event feed, so tagging can be automated instead of done by hand.
          </p>
          <div className="row wrap" style={{ gap: 10 }}>
            <label className="row" style={{ gap: 6, fontSize: 13 }}>From minute
              <input className="input" type="number" min={1} max={85} value={from} onChange={(e) => setFrom(Number(e.target.value))} style={{ width: 80, height: 34, borderRadius: 999 }} />
            </label>
            <button className="btn green" onClick={go} disabled={busy}>{busy ? "Rendering + detecting…" : "Run on 3 minutes of the demo match"}</button>
          </div>
          {busy && <p className="analysing" style={{ marginTop: 10 }}><i /><i /><i /> about 900 frames, about 30 s</p>}
          {err && <p style={{ color: "var(--danger)" }}>{err}</p>}
          {r && (
            <div className="grid fade-in" style={{ gridTemplateColumns: "repeat(3, 1fr)", marginTop: 18 }}>
              {[
                ["Ball found", pct(r.ball_detection_rate)], ["Players / frame", `${r.players_detected_per_frame} of 22`],
                ["Passes (true / found)", `${r.passes_truth} / ${r.passes_detected}`], ["Precision · recall", `${pct(r.precision)} · ${pct(r.recall)}`],
                ["Timing error", `${r.median_timing_error_s ?? "–"} s`], ["Ball speed error", `${r.median_speed_error_kmh ?? "–"} km/h`],
              ].map(([k, v]) => (
                <div key={k}><div className="eyebrow" style={{ fontSize: 10.5 }}>{k}</div><div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{v}</div></div>
              ))}
            </div>
          )}
        </div>
        <div>
          {r?.sample_frame_png ? (
            <img alt="Synthetic tactical-camera frame used for detection" src={`data:image/png;base64,${r.sample_frame_png}`} style={{ width: "100%", borderRadius: 12, imageRendering: "pixelated" }} />
          ) : (
            <div style={{ aspectRatio: "105/68", borderRadius: 12, background: "var(--paper-2)", display: "grid", placeItems: "center", color: "var(--muted)", fontSize: 13 }}>A rendered video frame appears here</div>
          )}
          {r && <div className="mono faint" style={{ fontSize: 11.5, marginTop: 6 }}>{r.frames} frames at {r.resolution[0]}×{r.resolution[1]} px · minutes {r.window[0]}–{r.window[1]}</div>}
        </div>
      </div>
    </section>
  );
}

export default function Studio() {
  const [clubs, setClubs] = useState<Club[]>([]);
  const [table, setTable] = useState<any[]>([]);
  const [home, setHome] = useState("nbk");
  const [away, setAway] = useState("hbc");
  const [seed, setSeed] = useState(42);
  const [prompt, setPrompt] = useState(EXAMPLES[0]);
  const [preset, setPreset] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Club[]>("/api/league").then(setClubs).catch((e) => setError(e.message));
    api<any[]>("/api/season/table?matchday=29").then(setTable).catch(() => undefined);
  }, []);

  async function generate() {
    setBusy(true); setError(null); setResult(null);
    try {
      const r = await post("/api/matches", { home, away, seed, prompt: preset ? null : prompt, preset });
      setResult(r);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  const club = (id: string) => clubs.find((c) => c.id === id);
  return (
    <>
      <Nav />
      <main className="container" style={{ padding: "28px 24px 80px" }}>
        <span className="eyebrow">Data studio · synthetic data innovation</span>
        <h1 className="display" style={{ fontSize: 46, margin: "4px 0 6px" }}>Generate a match. Describe it in words.</h1>
        <p className="muted" style={{ maxWidth: 720, fontSize: 16, marginTop: 0 }}>
          The simulator produces a full event stream (passes, shots, tackles, pressure, cards, substitutions) and 5&nbsp;Hz tracking
          for 22 players and the ball. The Scenario Director agent turns your description into a script. Every club and player is fictional.
        </p>

        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.3fr) minmax(280px, 1fr)", alignItems: "start", marginTop: 20 }} data-studio-grid>
          <div className="card" style={{ padding: 22 }}>
            <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 120px" }}>
              <label className="stack" style={{ gap: 6 }}>
                <span className="eyebrow">Home</span>
                <select className="select" value={home} onChange={(e) => setHome(e.target.value)}>
                  {clubs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
              <label className="stack" style={{ gap: 6 }}>
                <span className="eyebrow">Away</span>
                <select className="select" value={away} onChange={(e) => setAway(e.target.value)}>
                  {clubs.filter((c) => c.id !== home).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
              <label className="stack" style={{ gap: 6 }}>
                <span className="eyebrow">Seed</span>
                <input className="input" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} style={{ height: 34, borderRadius: 999 }} />
              </label>
            </div>
            {club(home) && club(away) && (
              <div className="row wrap" style={{ gap: 8, marginTop: 14 }}>
                {[club(home)!, club(away)!].map((c) => (
                  <span key={c.id} className="chip" style={{ height: "auto", padding: "6px 10px" }}>
                    <i style={{ width: 10, height: 10, borderRadius: 3, background: c.primary, display: "inline-block" }} />
                    <b>{c.code}</b> {c.style.formation} · press {Math.round(c.style.press * 100)} · possession {Math.round(c.style.possession * 100)} · direct {Math.round(c.style.directness * 100)}
                  </span>
                ))}
              </div>
            )}

            <div className="stack" style={{ marginTop: 20 }}>
              <span className="eyebrow">Scenario</span>
              <div className="seg" style={{ alignSelf: "flex-start" }}>
                <button className={preset === null ? "on" : ""} onClick={() => setPreset(null)}>Describe it</button>
                {["classic", "comeback", "chaos", "siege"].map((p) => (
                  <button key={p} className={preset === p ? "on" : ""} onClick={() => setPreset(p)}>{p}</button>
                ))}
              </div>
              {preset === null && (
                <>
                  <textarea className="input" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
                  <div className="row wrap" style={{ gap: 6 }}>
                    {EXAMPLES.map((x) => <button key={x} className="chip" style={{ cursor: "pointer" }} onClick={() => setPrompt(x)}>{x.slice(0, 42)}…</button>)}
                  </div>
                </>
              )}
            </div>

            <div className="row wrap" style={{ gap: 10, marginTop: 22 }}>
              <button className="btn green" onClick={generate} disabled={busy}>{busy ? "Simulating 90 minutes…" : "Generate match"}</button>
              {busy && <span className="analysing"><i /><i /><i /> events, tracking and physics (≈15 s)</span>}
            </div>
            {error && <p style={{ color: "var(--danger)" }}>{error}</p>}
            {result && (
              <div className="fade-in" style={{ marginTop: 20, padding: 16, borderRadius: 12, background: "var(--pitch-2)", border: "1px solid #c4dfd1" }}>
                <div style={{ fontWeight: 700 }}>Generated: {result.scenario.label}</div>
                <div className="mono" style={{ fontSize: 13, margin: "6px 0 12px" }}>
                  {result.events.toLocaleString()} events · {result.frames.toLocaleString()} tracking frames · {result.scenario.beats.length} scripted beats · director: {result.scenario_model ?? "preset"}
                </div>
                <div className="row wrap" style={{ gap: 8 }}>
                  <Link className="btn small" href={`/live?match=${result.match_id}`}>Open live →</Link>
                  <Link className="btn small secondary" href={`/control?match=${result.match_id}`}>Control room</Link>
                  <a className="btn small secondary" href={`${API_BASE}/api/matches/${result.match_id}/full-events`} target="_blank" rel="noreferrer">Download events (JSON)</a>
                </div>
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-head"><span className="panel-title">Synthetic season · after matchday 29</span><span className="chip">380 matches</span></div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
              <thead>
                <tr className="eyebrow" style={{ textAlign: "left" }}>
                  <th style={{ padding: "8px 14px" }}>#</th><th>Club</th><th className="num">P</th><th className="num">GD</th><th className="num">Pts</th><th style={{ paddingRight: 14 }}>Form</th>
                </tr>
              </thead>
              <tbody>
                {table.map((r) => {
                  const c = club(r.team);
                  return (
                    <tr key={r.team} style={{ borderTop: "1px solid var(--line)", background: r.team === home || r.team === away ? "var(--signal-2)" : undefined }}>
                      <td className="mono" style={{ padding: "7px 14px" }}>{r.pos}</td>
                      <td><span className="row" style={{ gap: 8 }}><i style={{ width: 8, height: 8, borderRadius: 2, background: c?.primary, display: "inline-block" }} />{c?.short_name ?? r.team}</span></td>
                      <td className="mono">{r.p}</td>
                      <td className="mono">{r.gf - r.ga > 0 ? "+" : ""}{r.gf - r.ga}</td>
                      <td className="mono" style={{ fontWeight: 700 }}>{r.pts}</td>
                      <td className="mono" style={{ paddingRight: 14, letterSpacing: "0.1em" }}>{r.form}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        <AutoEvent />
      </main>
      <style>{`@media (max-width: 900px){ [data-studio-grid]{ grid-template-columns: 1fr !important; } }`}</style>
    </>
  );
}
