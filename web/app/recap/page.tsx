"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useEffect, useMemo, useState } from "react";
import FactChip from "@/components/FactChip";
import MomentumWave from "@/components/MomentumWave";
import Nav from "@/components/Nav";
import ScoreBug from "@/components/ScoreBug";
import StatCompare from "@/components/StatCompare";
import { api } from "@/lib/api";
import { isRtl, LANGS, playersById } from "@/lib/format";
import { useMatch, type Prefs } from "@/lib/useMatch";

function Markdown({ md }: { md: string }) {
  const paras = md.split(/\n{2,}/).filter(Boolean);
  return (
    <div className="prose">
      {paras.map((p, i) => (
        <p key={i}>
          {p.split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
            part.startsWith("**") ? <strong key={j}>{part.slice(2, -2)}</strong> : <Fragment key={j}>{part}</Fragment>,
          )}
        </p>
      ))}
    </div>
  );
}

function Recap() {
  const params = useSearchParams();
  const matchId = params.get("match") || "demo";
  const [prefs] = useState<Prefs>({ mode: "fan", lang: "en", club: null, player_id: null });
  const { state } = useMatch(matchId, prefs, { frames: false });
  const [lang, setLang] = useState("en");
  const [analysis, setAnalysis] = useState<any>(null);
  const players = useMemo(() => playersById(state.meta), [state.meta]);

  const recaps = state.recaps;
  const phase = recaps.some((r) => r.phase === "full_time") ? "full_time" : "half_time";
  const langs = Array.from(new Set(recaps.filter((r) => r.phase === phase).map((r) => r.lang)));
  const recap = recaps.find((r) => r.phase === phase && r.lang === lang) ?? recaps.find((r) => r.phase === phase);

  useEffect(() => {
    if (recaps.length === 0) api(`/api/matches/${matchId}/analysis`).then(setAnalysis).catch(() => undefined);
  }, [matchId, recaps.length]);

  const meta = state.meta;
  const stats = state.stats;
  const potm = recap?.player_of_match ? players[recap.player_of_match] : null;
  const potmStats = recap?.player_of_match ? stats?.players[recap.player_of_match] : null;

  return (
    <>
      <Nav />
      <main className="container" style={{ padding: "36px 24px 80px", maxWidth: 1080 }}>
        {meta && stats && (
          <div className="row wrap between" style={{ gap: 14, marginBottom: 26 }}>
            <ScoreBug home={{ code: meta.home.code, color: meta.home.primary }} away={{ code: meta.away.code, color: meta.away.primary }} score={stats.score} minute={stats.minute} period={stats.period} finished={phase === "full_time" && !!recap} size="lg" />
            {langs.length > 1 && (
              <div className="seg" aria-label="Recap language">
                {langs.map((l) => (
                  <button key={l} className={(recap?.lang ?? "en") === l ? "on" : ""} onClick={() => setLang(l)}>
                    {LANGS.find((x) => x.code === l)?.native ?? l}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {recap ? (
          <article className="fade-in" dir={isRtl(recap.lang) ? "rtl" : undefined}>
            <span className="eyebrow">{recap.phase === "full_time" ? "Full-time report" : "Half-time report"} · written by the Producer agent · {recap.model}</span>
            <h1 className="serif" style={{ fontSize: "clamp(34px, 5vw, 56px)", lineHeight: 1.05, margin: "10px 0 14px", fontWeight: 700, letterSpacing: "-0.01em" }}>{recap.headline}</h1>
            <p className="serif" style={{ fontSize: 23, lineHeight: 1.45, color: "var(--muted)", margin: "0 0 30px" }}>{recap.standfirst}</p>
            <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) 300px", gap: 40, alignItems: "start" }} data-recap-grid>
              <div>
                <Markdown md={recap.body_md} />
                <div className="row wrap" style={{ gap: 6, marginTop: 10 }} dir="ltr">
                  <span className="eyebrow" style={{ marginRight: 6 }}>Sources</span>
                  {recap.cited_fact_ids.slice(0, 12).map((f) => <FactChip key={f} matchId={matchId} factId={f} />)}
                </div>
              </div>
              <aside className="stack" style={{ gap: 16 }} dir="ltr">
                {potm && (
                  <div className="card" style={{ padding: 18, borderTop: "4px solid var(--signal)" }}>
                    <span className="eyebrow">Player of the match</span>
                    <div className="display" style={{ fontSize: 30, lineHeight: 1.05, margin: "4px 0" }}>{potm.name}</div>
                    <div className="muted" style={{ fontSize: 13 }}>#{potm.number} · {potm.position} · {potm.side === "home" ? meta?.home.short_name : meta?.away.short_name}</div>
                    {recap.potm_reason && <p style={{ fontSize: 14, margin: "10px 0 0" }}>{recap.potm_reason}</p>}
                    {potmStats && recap.phase === "full_time" && <div className="mono" style={{ fontSize: 13, marginTop: 10, color: "var(--muted)" }}>{potmStats.distance_km.toFixed(1)} km · {potmStats.top_speed.toFixed(1)} km/h · {potmStats.passes} passes</div>}
                  </div>
                )}
                {meta && stats && (
                  <div className="panel">
                    <div className="panel-head"><span className="panel-title">Numbers</span></div>
                    <div className="panel-body" style={{ paddingTop: 4 }}>
                      <StatCompare home={stats.home} away={stats.away} homeColor={meta.home.primary} awayColor={meta.away.primary} compact />
                    </div>
                  </div>
                )}
              </aside>
            </div>
            {meta && stats && (
              <div className="panel" style={{ marginTop: 34 }} dir="ltr">
                <div className="panel-head"><span className="panel-title">How the match swung</span></div>
                <div className="panel-body">
                  <MomentumWave series={stats.momentum_series} homeColor={meta.home.primary} awayColor={meta.away.primary} moments={state.moments} homeCode={meta.home.code} awayCode={meta.away.code} height={150} />
                </div>
              </div>
            )}
          </article>
        ) : (
          <section>
            <span className="eyebrow">Recap</span>
            <h1 className="serif" style={{ fontSize: 44, margin: "8px 0 10px" }}>The recap is written at half time and full time.</h1>
            <p className="muted" style={{ fontSize: 17, maxWidth: 640 }}>
              The Producer agent writes it from approved explanations and verified facts, then the Guardian checks it before it is published.
              {" "}<Link href={`/live?match=${matchId}`} style={{ color: "var(--pitch)", fontWeight: 600 }}>Start the match →</Link>
            </p>
            {analysis && (
              <div className="panel" style={{ marginTop: 26 }}>
                <div className="panel-head"><span className="panel-title">Preview: deterministic analysis of this synthetic match</span><span className="chip">{analysis.events} events · {analysis.frames.toLocaleString()} frames</span></div>
                {analysis.key_moments.slice(0, 8).map((m: any, i: number) => (
                  <div key={i} style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
                    <span className="mono" style={{ fontWeight: 600 }}>{m.minute}&apos;</span> <b>{m.title}</b>
                    <p style={{ margin: "4px 0 0", color: "var(--ink-2)" }}>{m.why}</p>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </main>
      <style>{`@media (max-width: 860px){ [data-recap-grid]{ grid-template-columns: 1fr !important; } }`}</style>
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Recap />
    </Suspense>
  );
}
