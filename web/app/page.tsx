"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import AgentGraph from "@/components/AgentGraph";
import Nav, { Wordmark } from "@/components/Nav";
import OverlayStage from "@/components/OverlayStage";
import Stadium3D from "@/components/Stadium3D";
import { api } from "@/lib/api";
import { isRtl, LANGS, MODES } from "@/lib/format";
import type { Cue, Frame } from "@/lib/types";

interface Clip {
  moment: { moment_id: string; minute: number; t: number; title: string; type: string; team: "home" | "away" };
  facts: Record<string, { label: string; display: string }>;
  modes: Record<string, { headline: string; text: string; cited: string[] }>;
  guardian: { draft: string; draft_verdict: { approved: boolean; reasons: string[] }; final: string; final_verdict: { approved: boolean } };
  frames: (Frame & { t: number })[];
  ids: (string | null)[];
  players: Record<string, { name: string; short: string; number: number }>;
  home: { code: string; name: string; color: string };
  away: { code: string; name: string; color: string };
  cues: Cue[];
  score_after: [number, number];
}

function useClip(lang: string) {
  const [clip, setClip] = useState<Clip | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    api<Clip>(`/api/matches/demo/clip?type=goal&index=-1&lang=${lang}`).then(setClip).catch(() => setError(true));
  }, [lang]);
  return { clip, error };
}

function HeroClip({ clip }: { clip: Clip }) {
  const [k, setK] = useState(0);
  const n = clip.frames.length;
  useEffect(() => {
    const id = setInterval(() => setK((x) => (x + 1) % (n + 15)), 200);
    return () => clearInterval(id);
  }, [n]);
  const i = Math.min(k, n - 1);
  const f = clip.frames[i];
  const scored = f.t >= clip.moment.t;
  const score: [number, number] = scored ? clip.score_after : [clip.score_after[0] - (clip.moment.team === "home" ? 1 : 0), clip.score_after[1] - (clip.moment.team === "away" ? 1 : 0)];
  const card: Cue = {
    cue_id: "why", template: "moment_card", t_in: clip.moment.t + 0.6, t_out: clip.moment.t + 60, priority: 70, moment_id: clip.moment.moment_id,
    data: { title: clip.moment.title, headline: clip.modes.fan.headline, minute: clip.moment.minute, facts: clip.modes.analyst.cited.slice(0, 3).map((id) => ({ id, label: clip.facts[id]?.label, value: clip.facts[id]?.display })) },
  };
  const cues = [...clip.cues, ...(f.t > clip.moment.t + 3.2 ? [card] : [])].filter((c) => c.template !== "moment_card" || c.cue_id === "why");
  return (
    <div style={{ borderRadius: 18, overflow: "hidden", boxShadow: "var(--shadow-lg)", border: "1px solid #1d2a23", background: "#0b120e" }}>
      <OverlayStage
        cues={cues} now={f.t} minute={clip.moment.minute} period={2} score={score} home={clip.home} away={clip.away}
        background={
          <div style={{ position: "absolute", inset: 0 }}>
            <Stadium3D frame={f} ids={clip.ids} players={clip.players} homeColor={clip.home.color} awayColor={clip.away.color} focusId={clip.moment && (clip as any).moment.player_id} showControls={false} />
          </div>
        }
      />
    </div>
  );
}

const STAGES = [
  { n: "01", t: "Ingest", d: "A live feed of passes, shots, tackles, pressure and 5 Hz tracking flows through Azure Event Hubs." },
  { n: "02", t: "Interpret", d: "A deterministic stats engine computes xG, pass difficulty, speed, PPDA, momentum and a Control vs Chaos index." },
  { n: "03", t: "Explain", d: "Specialist agents say why a moment matters. Every number cites a verified fact, and a Guardian checks it." },
  { n: "04", t: "Render", d: "Timed overlay cues in machine-readable JSON drive broadcast graphics within milliseconds of the event." },
  { n: "05", t: "Personalise", d: "The same insight becomes Analyst, Fan, Club and Player modes, in any language." },
];

const STACK = [
  ["Microsoft Foundry", "Model deployments, Evaluations, tracing"],
  ["Microsoft Agent Framework", "Workflow graph, typed handoffs, A2A"],
  ["Azure Event Hubs", "Live event ingest, partitioned per match"],
  ["Azure Container Apps", "API, agents, simulator, MCP server"],
  ["Azure Cosmos DB", "Match blackboard and audit trail"],
  ["Azure Web PubSub", "Realtime fan-out to every viewer"],
  ["Azure AI Translator", "Any language, names protected"],
  ["Azure AI Content Safety", "Screens every published sentence"],
  ["Azure AI Search", "Season memory for milestones"],
  ["Microsoft Fabric", "Eventstream → Eventhouse analytics"],
  ["Azure Functions + Logic Apps", "Recap triggers and distribution"],
  ["GitHub Copilot + MCP", "Built with Copilot; match tools over MCP"],
];

export default function Home() {
  const [lang, setLang] = useState("en");
  const [mode, setMode] = useState<"analyst" | "fan" | "club" | "player">("analyst");
  const { clip, error } = useClip(lang);
  const [stats, setStats] = useState<any>(null);
  const shown = useRef(false);
  useEffect(() => {
    if (shown.current) return;
    shown.current = true;
    api("/api/matches/demo/analysis").then(setStats).catch(() => undefined);
  }, []);

  return (
    <>
      <Nav />
      <main>
        {/* HERO */}
        <section className="container" style={{ padding: "56px 24px 40px" }}>
          <div className="grid" style={{ gridTemplateColumns: "minmax(0, 0.9fr) minmax(0, 1.25fr)", gap: 48, alignItems: "center" }} data-hero>
            <div>
              <span className="eyebrow">Explainable match intelligence</span>
              <h1 className="display" style={{ fontSize: "clamp(52px, 7vw, 96px)", lineHeight: 0.92, margin: "14px 0 18px", letterSpacing: "-0.005em" }}>
                Football isn&apos;t the scoreline.<br /><span style={{ color: "var(--pitch)" }}>It&apos;s why.</span>
              </h1>
              <p style={{ fontSize: 19, lineHeight: 1.5, color: "var(--ink-2)", maxWidth: 520, margin: "0 0 26px" }}>
                Touchline turns a live stream of match events into broadcast graphics, explanations and recaps. Each one is personalised for every fan, in every language, and every number is checked.
              </p>
              <div className="row wrap" style={{ gap: 10 }}>
                <Link href="/live?match=demo" className="btn green" style={{ height: 46, padding: "0 22px", fontSize: 15 }}>Watch the live demo</Link>
                <Link href="/control?match=demo" className="btn secondary" style={{ height: 46, padding: "0 22px", fontSize: 15 }}>Open the control room</Link>
              </div>
              <div className="row wrap" style={{ gap: 18, marginTop: 30 }}>
                {[
                  [stats ? stats.events.toLocaleString() : "1,800", "events per match"],
                  [stats ? stats.frames.toLocaleString() : "28,000", "tracking frames"],
                  ["0", "unverified numbers"],
                ].map(([v, l]) => (
                  <div key={l}>
                    <div className="mono" style={{ fontSize: 26, fontWeight: 600 }}>{v}</div>
                    <div className="muted" style={{ fontSize: 13 }}>{l}</div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              {clip ? <HeroClip clip={clip} /> : (
                <div style={{ aspectRatio: "16/9", borderRadius: 18, background: "#0b120e", display: "grid", placeItems: "center", color: "#9fb3aa" }}>
                  {error ? "Start the API to see the live clip" : <span className="analysing" style={{ color: "#9fb3aa" }}><i /><i /><i /> Loading a real synthetic highlight…</span>}
                </div>
              )}
              <p className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
                Real output: the {clip ? `${clip.moment.minute}'` : "late"} winner from the demo match, with player tracking, shot speed, xG and the explanation, all generated by Touchline. Clubs and players are fictional.
              </p>
            </div>
          </div>
        </section>

        {/* STAGES */}
        <section style={{ borderTop: "1px solid var(--line)", borderBottom: "1px solid var(--line)", background: "var(--surface)" }}>
          <div className="container grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 0 }}>
            {STAGES.map((s, i) => (
              <div key={s.n} style={{ padding: "28px 22px", borderLeft: i ? "1px solid var(--line)" : undefined }}>
                <div className="mono" style={{ color: "var(--pitch)", fontSize: 13, fontWeight: 600 }}>{s.n}</div>
                <div className="display" style={{ fontSize: 28, margin: "2px 0 6px" }}>{s.t}</div>
                <p style={{ margin: 0, fontSize: 14, color: "var(--ink-2)" }}>{s.d}</p>
              </div>
            ))}
          </div>
        </section>

        {/* PERSONALISATION */}
        <section className="container" style={{ padding: "80px 24px 40px" }}>
          <div className="grid" style={{ gridTemplateColumns: "minmax(0, 0.8fr) minmax(0, 1.2fr)", gap: 48, alignItems: "start" }} data-hero>
            <div>
              <span className="eyebrow">Personalisation</span>
              <h2 className="display" style={{ fontSize: 56, lineHeight: 0.95, margin: "10px 0 14px" }}>One moment.<br />Every kind of fan.</h2>
              <p style={{ fontSize: 17, color: "var(--ink-2)", maxWidth: 460 }}>
                A data analyst and a casual fan get two different experiences, built from the same verified facts. Switch the mode and language: this is the actual output for that goal.
              </p>
              <div className="stack" style={{ gap: 12, marginTop: 22 }}>
                <div className="seg" style={{ alignSelf: "flex-start" }}>
                  {MODES.map((m) => <button key={m.id} className={mode === m.id ? "on" : ""} onClick={() => setMode(m.id)}>{m.label}</button>)}
                </div>
                <div className="row wrap" style={{ gap: 6 }}>
                  {LANGS.slice(0, 6).map((l) => (
                    <button key={l.code} className={`chip ${lang === l.code ? "dark" : ""}`} style={{ cursor: "pointer" }} onClick={() => setLang(l.code)}>{l.native}</button>
                  ))}
                </div>
              </div>
            </div>
            <div className="card" style={{ padding: 28, minHeight: 260 }} dir={isRtl(lang) ? "rtl" : undefined}>
              {clip ? (
                <div key={`${mode}-${lang}`} className="fade-in">
                  <div className="row" style={{ gap: 8, marginBottom: 10 }} dir="ltr">
                    <span className="mono" style={{ fontWeight: 600 }}>{clip.moment.minute}&apos;</span>
                    <span className="chip green">Goal</span>
                    <span className="chip">{MODES.find((m) => m.id === mode)?.hint}</span>
                  </div>
                  <h3 className="display" style={{ fontSize: 34, lineHeight: 1.02, margin: "0 0 10px" }}>{clip.modes[mode].headline}</h3>
                  <p style={{ fontSize: 18, lineHeight: 1.55, margin: 0, color: "var(--ink-2)" }} lang={lang}>{clip.modes[mode].text}</p>
                  <div className="row wrap" style={{ gap: 6, marginTop: 16 }} dir="ltr">
                    {clip.modes[mode].cited.map((id) => (
                      <span key={id} className="chip cite" title={clip.facts[id]?.label}>⌁ {id} · {clip.facts[id]?.display}</span>
                    ))}
                  </div>
                </div>
              ) : <span className="analysing"><i /><i /><i /> Loading…</span>}
            </div>
          </div>
        </section>

        {/* GUARDIAN */}
        <section className="container" style={{ padding: "60px 24px" }}>
          <div className="card" style={{ padding: "36px 32px", background: "var(--ink)", color: "var(--paper)", border: "none" }}>
            <div className="grid" style={{ gridTemplateColumns: "minmax(0, 0.8fr) minmax(0, 1.2fr)", gap: 40, alignItems: "center" }} data-hero>
              <div>
                <span className="eyebrow" style={{ color: "#9fb3aa" }}>The Guardian</span>
                <h2 className="display" style={{ fontSize: 52, lineHeight: 0.95, margin: "10px 0 14px" }}>Nothing on screen is made up.</h2>
                <p style={{ fontSize: 16.5, color: "#cfd8d3" }}>
                  Models write the words; they never produce the numbers. A Guardian agent checks every figure against verified facts, every name against the team sheets, and every sentence with Azure AI Content Safety. If a draft fails, it goes back for a rewrite.
                </p>
              </div>
              {clip && (
                <div className="stack" style={{ gap: 12 }}>
                  <div style={{ background: "#1a1f1c", borderRadius: 12, padding: 18, border: "1px solid #3a2321" }}>
                    <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                      <span className="chip danger">Draft rejected</span>
                      <span className="mono" style={{ fontSize: 12, color: "#f08a84" }}>{clip.guardian.draft_verdict.reasons.join("; ")}</span>
                    </div>
                    <p style={{ margin: 0, color: "#a9b2ad", textDecoration: "line-through", textDecorationColor: "#d6342c" }}>{clip.guardian.draft}</p>
                  </div>
                  <div style={{ background: "#14231b", borderRadius: 12, padding: 18, border: "1px solid #24543c" }}>
                    <div className="row" style={{ gap: 8, marginBottom: 8 }}><span className="chip green">Approved after rewrite</span></div>
                    <p style={{ margin: 0 }}>{clip.guardian.final}</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* AGENTS */}
        <section className="container" style={{ padding: "40px 24px 60px" }}>
          <span className="eyebrow">Multi-agent system</span>
          <h2 className="display" style={{ fontSize: 52, lineHeight: 0.95, margin: "10px 0 6px" }}>Nine specialists. One shared blackboard.</h2>
          <p style={{ fontSize: 17, color: "var(--ink-2)", maxWidth: 760 }}>
            Built on Microsoft Agent Framework. Each agent has one job and a typed output. They hand off through a workflow graph, share state in Cosmos DB, and recover from failure with timeouts, circuit breakers and verified fallbacks. Break one in the control room and watch.
          </p>
          <div className="card" style={{ padding: 18, marginTop: 20 }}>
            <AgentGraph agents={{}} traces={[]} now={0} />
          </div>
        </section>

        {/* STACK */}
        <section style={{ background: "var(--surface)", borderTop: "1px solid var(--line)", borderBottom: "1px solid var(--line)" }}>
          <div className="container" style={{ padding: "50px 24px" }}>
            <span className="eyebrow">Built on Microsoft and Azure</span>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", marginTop: 18, gap: 0, border: "1px solid var(--line)", borderRadius: 14, overflow: "hidden" }}>
              {STACK.map(([t, d]) => (
                <div key={t} style={{ padding: "18px 18px", borderRight: "1px solid var(--line)", borderBottom: "1px solid var(--line)", marginRight: -1, marginBottom: -1 }}>
                  <div style={{ fontWeight: 700, fontSize: 14.5 }}>{t}</div>
                  <div className="muted" style={{ fontSize: 13.5 }}>{d}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="container" style={{ padding: "70px 24px 40px", textAlign: "center" }}>
          <h2 className="display" style={{ fontSize: "clamp(40px, 6vw, 72px)", lineHeight: 0.95, margin: "0 0 18px" }}>0–2 down. Ten men. 88th minute.</h2>
          <p style={{ fontSize: 18, color: "var(--ink-2)", margin: "0 auto 26px", maxWidth: 560 }}>Watch the demo match live, then change the language, switch to player cam, or break an agent.</p>
          <div className="row wrap" style={{ gap: 10, justifyContent: "center" }}>
            <Link href="/live?match=demo" className="btn green" style={{ height: 48, padding: "0 24px", fontSize: 15 }}>Kick off the demo</Link>
            <Link href="/overlay?match=demo&bg=pitch" className="btn secondary" style={{ height: 48, padding: "0 24px", fontSize: 15 }}>Broadcast overlay</Link>
            <Link href="/studio" className="btn secondary" style={{ height: 48, padding: "0 24px", fontSize: 15 }}>Generate your own match</Link>
          </div>
        </section>

        <footer className="container" style={{ padding: "30px 24px 50px", borderTop: "1px solid var(--line)", marginTop: 40 }}>
          <div className="row wrap between" style={{ gap: 14 }}>
            <Wordmark />
            <span className="muted" style={{ fontSize: 13 }}>All clubs, players and match data are synthetic and fictional. Built for the Inside the Game developer hackathon.</span>
          </div>
        </footer>
      </main>
      <style>{`@media (max-width: 960px){ [data-hero]{ grid-template-columns: 1fr !important; gap: 28px !important; } }`}</style>
    </>
  );
}
