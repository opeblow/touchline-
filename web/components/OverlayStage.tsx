"use client";

import { useEffect, useRef, useState } from "react";
import { clockLabel } from "@/lib/format";
import type { Cue } from "@/lib/types";

interface Props {
  cues: Cue[];
  now: number;
  minute: number;
  period: number;
  score: [number, number];
  home: { code: string; color: string };
  away: { code: string; color: string };
  background?: React.ReactNode;
  finished?: boolean;
}

/** Scales a fixed 1920×1080 broadcast canvas to its container. */
function useScale() {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.5);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setScale(e.contentRect.width / 1920));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return { ref, scale };
}

const label: React.CSSProperties = { fontFamily: "var(--font-mono)", fontSize: 18, letterSpacing: "0.14em", textTransform: "uppercase", color: "#9fb3aa" };
const big: React.CSSProperties = { fontFamily: "var(--font-display)", fontWeight: 700, letterSpacing: "0.01em" };

function TeamBar({ color }: { color: string }) {
  return <span style={{ width: 8, alignSelf: "stretch", background: color, borderRadius: 2 }} />;
}

export default function OverlayStage({ cues, now, minute, period, score, home, away, background, finished }: Props) {
  const { ref, scale } = useScale();
  const active = cues.filter((c) => c.t_in <= now && now <= c.t_out);
  const latest = (t: string) => active.filter((c) => c.template === t).sort((a, b) => b.t_in - a.t_in)[0];
  const shot = latest("shot_speed");
  const xg = latest("xg_popup");
  const tag = latest("player_tag");
  const speed = latest("speed_badge");
  const pass = latest("pass_rating");
  const card = latest("moment_card");
  const lower = latest("lower_third");
  const compare = latest("stat_compare");
  const mom = latest("momentum_bar");

  return (
    <div ref={ref} style={{ width: "100%", aspectRatio: "16 / 9", position: "relative", overflow: "hidden" }}>
      <div className="ov-root" style={{ transform: `scale(${scale})`, transformOrigin: "top left", position: "absolute", top: 0, left: 0 }}>
        {background && <div style={{ position: "absolute", inset: 0 }}>{background}</div>}

        {/* Score bug: always on */}
        <div className="ov-plate" style={{ position: "absolute", top: 54, left: 64, display: "flex", alignItems: "stretch", height: 64, overflow: "hidden" }}>
          <TeamBar color={home.color} />
          <span style={{ ...big, fontSize: 36, padding: "0 18px", display: "flex", alignItems: "center" }}>{home.code}</span>
          <span style={{ ...big, fontSize: 40, padding: "0 20px", background: "#fff", color: "#0f1412", display: "flex", alignItems: "center", fontVariantNumeric: "tabular-nums" }}>
            {score[0]}<span style={{ opacity: 0.3, margin: "0 10px" }}>–</span>{score[1]}
          </span>
          <span style={{ ...big, fontSize: 36, padding: "0 18px", display: "flex", alignItems: "center" }}>{away.code}</span>
          <TeamBar color={away.color} />
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 24, padding: "0 20px", background: "#0e6b47", display: "flex", alignItems: "center" }}>
            {finished ? "FT" : clockLabel(minute, period)}
          </span>
        </div>

        {/* Right column: shot speed + xG */}
        {shot && (
          <div key={shot.cue_id} className="ov-plate ov-enter-r" style={{ position: "absolute", right: 64, top: 160, width: 420, padding: "22px 28px" }}>
            <div style={label}>Shot speed</div>
            <div style={{ ...big, fontSize: 96, lineHeight: 1, color: "#f2a900", fontVariantNumeric: "tabular-nums" }}>
              {Number(shot.data.speed_kmh).toFixed(0)}<span style={{ fontSize: 36, color: "#fff", marginLeft: 10 }}>km/h</span>
            </div>
            <div style={{ fontSize: 24, marginTop: 6, display: "flex", gap: 10, alignItems: "center" }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: shot.data.color }} />
              {shot.data.number} {shot.data.name}
            </div>
          </div>
        )}
        {xg && (
          <div key={xg.cue_id} className="ov-plate ov-enter-r" style={{ position: "absolute", right: 64, top: 400, width: 420, padding: "22px 28px", animationDelay: "120ms" }}>
            <div style={label}>Expected goals</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
              <span style={{ ...big, fontSize: 80, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{Number(xg.data.xg).toFixed(2)}</span>
              <span style={{ fontSize: 22, color: "#cfd8d3" }}>from {Number(xg.data.distance_m).toFixed(0)} m</span>
            </div>
            <div style={{ height: 10, borderRadius: 5, background: "rgba(255,255,255,0.12)", marginTop: 14, overflow: "hidden" }}>
              <div style={{ width: `${Math.min(100, Number(xg.data.xg) * 100)}%`, height: "100%", background: "#f2a900" }} />
            </div>
            <div style={{ fontSize: 20, marginTop: 10, color: "#cfd8d3", textTransform: "capitalize" }}>
              {xg.data.outcome === "goal" ? "Scored" : String(xg.data.outcome ?? "").replace("_", " ")}
            </div>
          </div>
        )}

        {/* Moment card ("why it matters") */}
        {card && !shot && (
          <div key={card.cue_id} className="ov-plate ov-enter-r" style={{ position: "absolute", right: 64, top: 160, width: 560, padding: "26px 30px", borderTop: "6px solid #f2a900" }}>
            <div style={label}>{card.data.minute}&apos; · Why it matters</div>
            <div style={{ ...big, fontSize: 44, lineHeight: 1.05, margin: "8px 0 10px", textTransform: "uppercase" }}>{card.data.headline || card.data.title}</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, marginTop: 14 }}>
              {(card.data.facts || []).map((f: any) => (
                <div key={f.id}>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 30, color: "#f2a900", fontVariantNumeric: "tabular-nums" }}>{f.value}</div>
                  <div style={{ fontSize: 16, color: "#cfd8d3", lineHeight: 1.25 }}>{f.label}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Lower left: player tag / speed badge / lower third */}
        {lower ? (
          <div key={lower.cue_id} className="ov-plate ov-enter" style={{ position: "absolute", left: 64, bottom: 96, minWidth: 560, padding: "20px 26px", display: "flex", gap: 18, alignItems: "center" }}>
            {lower.data.card && <span style={{ width: 34, height: 46, borderRadius: 4, background: lower.data.card === "red" ? "#d6342c" : "#f2c94c" }} />}
            <div>
              <div style={label}>{lower.data.title}</div>
              {lower.data.name && <div style={{ ...big, fontSize: 46, textTransform: "uppercase" }}>{lower.data.number} {lower.data.name}</div>}
              {lower.data.in && (
                <div style={{ fontSize: 28, marginTop: 4 }}>
                  <span style={{ color: "#6fd3a0" }}>▲ {lower.data.in.name}</span>
                  <span style={{ color: "#f08a84", marginLeft: 22 }}>▼ {lower.data.out?.name}</span>
                </div>
              )}
            </div>
          </div>
        ) : speed ? (
          <div key={speed.cue_id} className="ov-plate ov-enter" style={{ position: "absolute", left: 64, bottom: 96, padding: "18px 26px", display: "flex", gap: 22, alignItems: "center" }}>
            <TeamBar color={speed.data.color} />
            <div>
              <div style={label}>{speed.data.kind === "distance" ? "Distance covered" : "Top speed"}</div>
              <div style={{ ...big, fontSize: 64, lineHeight: 1, color: "#f2a900", fontVariantNumeric: "tabular-nums" }}>
                {speed.data.kind === "distance" ? `${speed.data.distance_km} km` : `${Number(speed.data.speed_kmh).toFixed(1)} km/h`}
              </div>
            </div>
            <div style={{ fontSize: 28, borderLeft: "1px solid rgba(255,255,255,0.15)", paddingLeft: 22 }}>
              <div style={{ ...big, fontSize: 34, textTransform: "uppercase" }}>{speed.data.name}</div>
              <div style={{ fontSize: 20, color: "#cfd8d3" }}>#{speed.data.number} · {speed.data.team_code}</div>
            </div>
          </div>
        ) : tag ? (
          <div key={tag.cue_id} className="ov-plate ov-enter" style={{ position: "absolute", left: 64, bottom: 96, padding: "14px 22px", display: "flex", gap: 16, alignItems: "center" }}>
            <TeamBar color={tag.data.color} />
            <span style={{ ...big, fontSize: 48, color: "#f2a900" }}>{tag.data.number}</span>
            <span style={{ ...big, fontSize: 40, textTransform: "uppercase" }}>{tag.data.name}</span>
          </div>
        ) : null}

        {/* Pass rating, bottom centre */}
        {pass && (
          <div key={pass.cue_id} className="ov-plate ov-enter-up" style={{ position: "absolute", left: "50%", bottom: 96, transform: "translateX(-50%)", padding: "16px 26px", display: "flex", gap: 26, alignItems: "center" }}>
            <div>
              <div style={label}>Pass difficulty</div>
              <div style={{ ...big, fontSize: 58, lineHeight: 1, color: "#f2a900" }}>{pass.data.difficulty}<span style={{ fontSize: 26, color: "#cfd8d3" }}>/100</span></div>
            </div>
            <div style={{ fontSize: 22 }}>
              <div style={{ ...big, fontSize: 30, textTransform: "uppercase" }}>{pass.data.name}</div>
              <div style={{ color: "#cfd8d3" }}>{Number(pass.data.distance_m).toFixed(0)} m{pass.data.recipient ? ` to ${pass.data.recipient}` : ""}</div>
            </div>
          </div>
        )}

        {/* Half/full time comparison */}
        {compare && (
          <div key={compare.cue_id} className="ov-plate ov-enter-up" style={{ position: "absolute", left: "50%", top: "50%", transform: "translate(-50%, -50%)", width: 860, padding: "30px 40px" }}>
            <div style={{ ...big, fontSize: 40, textAlign: "center", textTransform: "uppercase", marginBottom: 18 }}>{compare.data.title}</div>
            {(compare.data.rows || []).map((r: any) => {
              const total = Number(r.home) + Number(r.away) || 1;
              return (
                <div key={r.label} style={{ display: "grid", gridTemplateColumns: "120px 1fr 120px", alignItems: "center", gap: 18, margin: "12px 0" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 30 }}>{r.home}{r.unit ?? ""}</span>
                  <div>
                    <div style={{ textAlign: "center", fontSize: 20, color: "#cfd8d3", marginBottom: 6 }}>{r.label}</div>
                    <div style={{ display: "flex", height: 10, gap: 4 }}>
                      <span style={{ width: `${(Number(r.home) / total) * 100}%`, background: home.color, borderRadius: 5 }} />
                      <span style={{ width: `${(Number(r.away) / total) * 100}%`, background: away.color, borderRadius: 5 }} />
                    </div>
                  </div>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 30, textAlign: "right" }}>{r.away}{r.unit ?? ""}</span>
                </div>
              );
            })}
          </div>
        )}

        {/* Momentum strip */}
        {mom && !compare && (
          <div key={mom.cue_id} className="ov-plate ov-enter-up" style={{ position: "absolute", right: 64, bottom: 96, width: 520, padding: "16px 22px" }}>
            <div style={{ ...label, display: "flex", justifyContent: "space-between" }}>
              <span>Momentum</span><span style={{ color: Number(mom.data.value) >= 0 ? "#fff" : "#fff" }}>{Number(mom.data.value) >= 0 ? mom.data.home : mom.data.away}</span>
            </div>
            <svg viewBox="0 0 400 70" width="100%" height="70">
              <line x1={0} x2={400} y1={35} y2={35} stroke="rgba(255,255,255,0.2)" />
              {(mom.data.series || []).map((p: [number, number], i: number, arr: [number, number][]) => {
                const w = 400 / Math.max(arr.length, 1);
                const h = (Math.abs(p[1]) / 100) * 33;
                return <rect key={i} x={i * w} y={p[1] >= 0 ? 35 - h : 35} width={Math.max(w - 1, 1)} height={h} fill={p[1] >= 0 ? home.color : away.color} />;
              })}
            </svg>
          </div>
        )}
      </div>
    </div>
  );
}
