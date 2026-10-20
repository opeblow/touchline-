"use client";

import type { MatchMeta, Snapshot } from "@/lib/types";

export const METRICS: { id: string; label: string; unit: string; digits: number; team?: (s: any) => number; player?: string; kinds: string[] }[] = [
  { id: "xg", label: "Expected goals", unit: "", digits: 2, team: (t) => t.xg, player: "xg", kinds: ["xg", "xg_total"] },
  { id: "top_speed", label: "Top speed", unit: " km/h", digits: 1, player: "top_speed", kinds: ["top_speed"] },
  { id: "distance", label: "Distance covered", unit: " km", digits: 1, team: (t) => t.distance_km, player: "distance_km", kinds: ["distance"] },
  { id: "pass_accuracy", label: "Pass accuracy", unit: "%", digits: 0, team: (t) => t.pass_accuracy, player: "pass_accuracy", kinds: ["pass_accuracy", "pass_accuracy_window"] },
  { id: "pass_difficulty", label: "Hardest pass", unit: "/100", digits: 0, player: "hardest_pass", kinds: ["pass_difficulty"] },
  { id: "possession", label: "Possession", unit: "%", digits: 0, team: (t) => t.possession, kinds: ["possession", "possession_window"] },
  { id: "ppda", label: "Pressing (PPDA)", unit: "", digits: 1, team: (t) => t.ppda, kinds: ["ppda"] },
  { id: "shots", label: "Shots", unit: "", digits: 0, team: (t) => t.shots, player: "shots", kinds: ["shot_speed", "shots", "shots_window"] },
];

export default function MetricPin({ metric, onChange, stats, meta, focusId, playerName }: {
  metric: string; onChange: (m: string) => void; stats: Snapshot | null; meta: MatchMeta; focusId: string | null; playerName: (id: string) => string;
}) {
  const m = METRICS.find((x) => x.id === metric) ?? METRICS[0];
  const fmt = (v: number | undefined) => (v === undefined || Number.isNaN(v) ? "–" : `${v.toFixed(m.digits)}${m.unit}`);
  const leader = m.player && stats
    ? Object.values(stats.players).filter((p) => p.touches > 0).sort((a: any, b: any) => (b as any)[m.player!] - (a as any)[m.player!])[0]
    : null;
  const focus = focusId && stats?.players[focusId];
  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="row between" style={{ marginBottom: 8 }}>
        <span className="eyebrow">Your metric</span>
        <select className="select" value={m.id} onChange={(e) => onChange(e.target.value)} aria-label="Metric you care about">
          {METRICS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
        </select>
      </div>
      <div className="row wrap" style={{ gap: 22 }}>
        {m.team && stats && (
          <>
            <div><div className="mono" style={{ fontSize: 26, fontWeight: 600, color: meta.home.primary }}>{fmt(m.team(stats.home))}</div><div className="muted" style={{ fontSize: 12 }}>{meta.home.short_name}</div></div>
            <div><div className="mono" style={{ fontSize: 26, fontWeight: 600, color: meta.away.primary }}>{fmt(m.team(stats.away))}</div><div className="muted" style={{ fontSize: 12 }}>{meta.away.short_name}</div></div>
          </>
        )}
        {focus && m.player && (
          <div><div className="mono" style={{ fontSize: 26, fontWeight: 600, color: "var(--signal)" }}>{fmt((focus as any)[m.player])}</div><div className="muted" style={{ fontSize: 12 }}>{playerName(focusId!)} (you follow)</div></div>
        )}
        {leader && m.player && (
          <div><div className="mono" style={{ fontSize: 26, fontWeight: 600 }}>{fmt((leader as any)[m.player])}</div><div className="muted" style={{ fontSize: 12 }}>Match leader: {playerName(leader.id)}</div></div>
        )}
      </div>
    </div>
  );
}
