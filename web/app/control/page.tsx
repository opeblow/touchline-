"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AgentGraph from "@/components/AgentGraph";
import Nav from "@/components/Nav";
import ScoreBug from "@/components/ScoreBug";
import TraceList from "@/components/TraceList";
import { api, post, setOperatorKey } from "@/lib/api";
import { useMatch, type Prefs } from "@/lib/useMatch";
import type { AgentStatus } from "@/lib/types";

const CHAOS = [
  { action: "corrupt", agent: "explainer", label: "Make the Explainer state a wrong number", hint: "Guardian should reject it and force a rewrite", tone: "signal" },
  { action: "kill", agent: "explainer", label: "Take the Explainer offline (45 s)", hint: "Circuit breaker → verified template fallback", tone: "danger" },
  { action: "kill", agent: "persona", label: "Take Persona/Localizer offline (45 s)", hint: "Viewers still get every mode and language", tone: "danger" },
  { action: "kill", agent: "narrator", label: "Take the Narrator offline (45 s)", hint: "Commentary falls back, the feed keeps flowing", tone: "danger" },
] as const;

function ProducerReview({ matchId }: { matchId: string }) {
  const [data, setData] = useState<{ policy: { enabled: boolean; min_importance: number }; pending: any[] } | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [last, setLast] = useState<string | null>(null);
  useEffect(() => {
    let on = true;
    const tick = () => api(`/api/matches/${matchId}/reviews`).then((d) => on && setData(d)).catch(() => undefined);
    tick();
    const id = setInterval(tick, 1500);
    return () => { on = false; clearInterval(id); };
  }, [matchId]);
  const setPolicy = (enabled: boolean, min_importance = 90) =>
    post(`/api/matches/${matchId}/review-policy`, { enabled, min_importance }).then(() => api(`/api/matches/${matchId}/reviews`).then(setData));
  const decide = async (id: string, approved: boolean) => {
    const edited = edits[id];
    const r = await post(`/api/matches/${matchId}/reviews/${id}`, { approved, editor: "producer", edited_text: edited ?? null });
    setLast(`${r.outcome}${r.outcome !== "published" && r.outputs?.[0]?.includes("edit-rejected") ? ": " + r.outputs[0].split(":").slice(2).join(":") : ""}`);
    setData(await api(`/api/matches/${matchId}/reviews`));
  };
  const p = data?.policy;
  const mode = !p?.enabled ? "off" : p.min_importance >= 90 ? "critical" : "key";
  return (
    <div className="panel">
      <div className="panel-head"><span className="panel-title">Producer approval</span><span className="chip">human in the loop</span></div>
      <div className="panel-body stack">
        <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>
          The Agent Framework workflow pauses before publishing, until a producer approves, edits or rejects. Edits are checked by the Guardian too.
        </p>
        <div className="seg" style={{ alignSelf: "flex-start" }}>
          <button className={mode === "off" ? "on" : ""} onClick={() => setPolicy(false)}>Auto-publish</button>
          <button className={mode === "critical" ? "on" : ""} onClick={() => setPolicy(true, 90)}>Goals + reds</button>
          <button className={mode === "key" ? "on" : ""} onClick={() => setPolicy(true, 55)}>All key</button>
        </div>
        {data?.pending.length === 0 && p?.enabled && <span className="faint" style={{ fontSize: 13 }}>Nothing waiting. Held insights appear here.</span>}
        {data?.pending.map((r) => (
          <div key={r.request_id} className="fade-in" style={{ border: "1px solid var(--line)", borderRadius: 12, padding: 12 }}>
            <div className="row between" style={{ marginBottom: 6 }}>
              <b style={{ fontSize: 14 }}>{r.moment.minute}&apos; {r.moment.title}</b>
              <span className="mono faint" style={{ fontSize: 11 }}>{r.waiting_s}s</span>
            </div>
            <textarea className="input" rows={3} value={edits[r.request_id] ?? r.text} onChange={(e) => setEdits({ ...edits, [r.request_id]: e.target.value })} style={{ fontSize: 13.5 }} />
            <div className="row" style={{ gap: 6, marginTop: 8 }}>
              <button className="btn small green" onClick={() => decide(r.request_id, true)}>{edits[r.request_id] && edits[r.request_id] !== r.text ? "Approve edit" : "Approve"}</button>
              <button className="btn small secondary" onClick={() => decide(r.request_id, false)}>Reject</button>
            </div>
          </div>
        ))}
        {last && <span className="chip signal" style={{ height: "auto", padding: "5px 10px", whiteSpace: "normal" }}>Last decision: {last}</span>}
      </div>
    </div>
  );
}

function OperatorKey() {
  const [need, setNeed] = useState(false);
  const [val, setVal] = useState("");
  useEffect(() => {
    api("/api/health").then((h) => setNeed(!!h.operator_key_required)).catch(() => undefined);
  }, []);
  if (!need) return <span className="chip">Operator key: not required (demo)</span>;
  return (
    <span className="row" style={{ gap: 6 }}>
      <input className="input" type="password" placeholder="Operator key" value={val} onChange={(e) => setVal(e.target.value)} style={{ height: 28, width: 160 }} />
      <button className="btn small secondary" onClick={() => setOperatorKey(val)}>Save key</button>
    </span>
  );
}

function Stat({ k, v, tone }: { k: string; v: string | number; tone?: string }) {
  return (
    <div>
      <div className="eyebrow" style={{ fontSize: 10.5 }}>{k}</div>
      <div className="mono" style={{ fontSize: 24, fontWeight: 600, color: tone }}>{v}</div>
    </div>
  );
}

function Control() {
  const params = useSearchParams();
  const matchId = params.get("match") || "demo";
  const [prefs] = useState<Prefs>({ mode: "analyst", lang: "en", club: null, player_id: null });
  const { state, control } = useMatch(matchId, prefs, { frames: false });
  const [agents, setAgents] = useState<Record<string, AgentStatus>>({});
  const [audit, setAudit] = useState<any[]>([]);
  const [flash, setFlash] = useState<string | null>(null);

  useEffect(() => {
    let on = true;
    const tick = async () => {
      try {
        const s = await api(`/api/matches/${matchId}/agents/status`);
        const a = await api(`/api/matches/${matchId}/audit?limit=300`);
        if (on) { setAgents(s.agents); setAudit(a); }
      } catch { /* service warming up */ }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { on = false; clearInterval(id); };
  }, [matchId]);

  async function chaos(action: string, agent: string) {
    await post(`/api/matches/${matchId}/chaos`, { action, agent, seconds: 45 });
    setFlash(`${action === "corrupt" ? "Fault armed" : "Agent offline"}: ${agent}. Watch the trace stream.`);
    setTimeout(() => setFlash(null), 5000);
  }

  const totals = state.status?.totals;
  const meta = state.meta;
  const rejected = audit.filter((a) => !a.approved).slice(-8).reverse();
  const live = state.status?.status === "live";

  return (
    <>
      <Nav />
      <main className="container" style={{ padding: "20px 24px 60px" }}>
        <section className="row wrap between" style={{ gap: 16, marginBottom: 16 }}>
          <div>
            <span className="eyebrow">Control room · multi-agent system</span>
            <h1 className="display" style={{ fontSize: 40, margin: "2px 0 0" }}>Every agent, every handoff, live</h1>
          </div>
          <div className="row wrap" style={{ gap: 10 }}>
            {meta && state.stats && (
              <ScoreBug home={{ code: meta.home.code, color: meta.home.primary }} away={{ code: meta.away.code, color: meta.away.primary }} score={state.stats.score} minute={state.stats.minute} period={state.stats.period} finished={state.status?.status === "finished"} />
            )}
            {!live && (
              <button
                className="btn green"
                onClick={async () => {
                  const s = state.status?.status;
                  if (s === "paused") return control("resume");
                  if (s === "finished") await control("restart");
                  await control("start", 8);
                }}
              >
                Run match
              </button>
            )}
          </div>
        </section>

        <div className="card" style={{ padding: 18, marginBottom: 16 }}>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))" }}>
            <Stat k="Agent calls" v={totals?.calls ?? 0} />
            <Stat k="Guardian rejections" v={totals?.rejections ?? 0} tone={totals?.rejections ? "var(--danger)" : undefined} />
            <Stat k="Rewrites" v={totals?.retries ?? 0} />
            <Stat k="Fallbacks" v={totals?.fallbacks ?? 0} />
            <Stat k="Tokens" v={(totals ? totals.tokens_in + totals.tokens_out : 0).toLocaleString()} />
            <Stat k="Cost this match" v={`$${(totals?.cost_usd ?? 0).toFixed(4)}`} />
            <Stat k="Insight latency p50 / p95" v={`${(state.status?.insight_latency_ms?.p50 ?? 0).toFixed(0)} / ${(state.status?.insight_latency_ms?.p95 ?? 0).toFixed(0)} ms`} />
            <Stat k="Budget" v={`$${(state.status?.budget_usd ?? 0).toFixed(2)}`} tone={state.status?.over_budget ? "var(--danger)" : undefined} />
          </div>
          <div className="row wrap" style={{ gap: 8, marginTop: 14, fontSize: 12.5 }}>
            <span className="chip">LLM: {state.status?.llm === "offline" ? "offline templates" : `${state.status?.llm} · ${state.status?.model_fast} / ${state.status?.model_reasoning}`}</span>
            <span className="chip">Bus: {state.status?.bus}</span>
            <span className="chip">Realtime: {state.status?.hub}</span>
            <span className="chip">Workflow: Microsoft Agent Framework</span>
            <span className="chip">{state.status?.pending_moments ?? 0} moments in flight</span>
            <span className="chip">Mode: {state.status?.llm_mode ?? state.status?.llm}</span>
            <OperatorKey />
          </div>
        </div>

        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(300px, 360px)", alignItems: "start" }} data-cr-grid>
          <div className="grid">
            <div className="panel">
              <div className="panel-head"><span className="panel-title">Agent graph</span><span className="muted" style={{ fontSize: 12.5 }}>Green = working now · red = rejection or offline</span></div>
              <div className="panel-body"><AgentGraph agents={agents} traces={state.traces} now={state.now} /></div>
            </div>
            <div className="panel">
              <div className="panel-head"><span className="panel-title">Trace stream</span><span className="chip">OpenTelemetry → App Insights</span></div>
              <div className="scroll" style={{ maxHeight: 520 }}><TraceList traces={state.traces} /></div>
            </div>
          </div>
          <aside className="grid">
            <ProducerReview matchId={matchId} />
            <div className="panel">
              <div className="panel-head"><span className="panel-title">Chaos test</span></div>
              <div className="panel-body stack">
                <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>Break the system on purpose and watch it recover. No viewer ever sees an unverified number.</p>
                {CHAOS.map((c) => (
                  <button key={c.label} className={`btn ${c.tone === "danger" ? "secondary" : ""}`} style={{ height: "auto", padding: "10px 14px", justifyContent: "flex-start", textAlign: "left", whiteSpace: "normal", borderRadius: 12 }} onClick={() => chaos(c.action, c.agent)} disabled={!live}>
                    <span>
                      <span style={{ display: "block", fontWeight: 600 }}>{c.label}</span>
                      <span style={{ display: "block", fontSize: 12, opacity: 0.75, fontWeight: 400 }}>{c.hint}</span>
                    </span>
                  </button>
                ))}
                {!live && <span className="faint" style={{ fontSize: 12.5 }}>Start the match to enable chaos tests.</span>}
                {flash && <div className="chip signal fade-in" style={{ height: "auto", padding: "6px 10px", whiteSpace: "normal" }}>{flash}</div>}
              </div>
            </div>
            <div className="panel">
              <div className="panel-head"><span className="panel-title">Guardian audit</span><span className="chip">{audit.length} checks</span></div>
              <div className="scroll" style={{ maxHeight: 420 }}>
                {rejected.length === 0 && <div style={{ padding: 16, color: "var(--muted)", fontSize: 13.5 }}>No rejections yet. Arm a fault above to see one.</div>}
                {rejected.map((a, i) => (
                  <div key={i} style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
                    <div className="row" style={{ gap: 6, marginBottom: 4 }}>
                      <span className="chip danger">rejected</span>
                      <span className="mono faint" style={{ fontSize: 11.5 }}>{a.surface}</span>
                    </div>
                    <div style={{ fontSize: 13, color: "var(--danger)", fontWeight: 600 }}>{(a.reasons || []).join("; ")}</div>
                    <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4, textDecoration: "line-through" }}>{a.text}</div>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </div>
      </main>
      <style>{`@media (max-width: 980px){ [data-cr-grid]{ grid-template-columns: 1fr !important; } }`}</style>
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Control />
    </Suspense>
  );
}
