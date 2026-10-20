"use client";

import type { AgentStatus, Trace } from "@/lib/types";

const NODES: { id: string; label: string; role: string; x: number; y: number }[] = [
  { id: "spotter", label: "Moment Spotter", role: "rules · 0–100", x: 70, y: 150 },
  { id: "memory", label: "Memory", role: "AI Search", x: 230, y: 150 },
  { id: "explainer", label: "Explainer", role: "Foundry · fast", x: 400, y: 80 },
  { id: "narrator", label: "Narrator", role: "Foundry · fast", x: 400, y: 230 },
  { id: "guardian", label: "Guardian", role: "fact-check · safety", x: 580, y: 150 },
  { id: "persona", label: "Persona + Localizer", role: "4 modes × N langs", x: 760, y: 80 },
  { id: "publisher", label: "Publisher", role: "Web PubSub", x: 920, y: 150 },
  { id: "tactician", label: "Tactician", role: "Foundry · reasoning", x: 760, y: 270 },
  { id: "producer", label: "Producer", role: "recaps · reasoning", x: 580, y: 300 },
];
const EDGES: [string, string, string?][] = [
  ["spotter", "memory"], ["memory", "explainer"], ["memory", "narrator"], ["explainer", "guardian"],
  ["narrator", "guardian"], ["guardian", "persona", "approved"], ["guardian", "explainer", "rejected"],
  ["guardian", "publisher"], ["persona", "publisher"], ["tactician", "publisher"], ["producer", "guardian"],
];
const NW = 150, NH = 54;

export default function AgentGraph({ agents, traces, now }: { agents: Record<string, AgentStatus>; traces: Trace[]; now: number }) {
  const recent = new Map<string, Trace>();
  for (const t of traces.slice(-40)) recent.set(t.agent, t);
  const pos = Object.fromEntries(NODES.map((n) => [n.id, n]));
  return (
    <svg viewBox="-12 0 1024 360" width="100%" role="img" aria-label="Agent collaboration graph">
      <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--line-2)" />
        </marker>
        <marker id="arr-r" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--danger)" />
        </marker>
      </defs>
      {EDGES.map(([a, b, kind]) => {
        const A = pos[a], B = pos[b];
        const rejected = kind === "rejected";
        const x1 = A.x + (B.x > A.x ? NW / 2 : B.x < A.x ? -NW / 2 : 0);
        const x2 = B.x + (B.x > A.x ? -NW / 2 : B.x < A.x ? NW / 2 : 0);
        const y1 = A.y + (B.x === A.x ? (B.y > A.y ? NH / 2 : -NH / 2) : 0);
        const y2 = B.y + (B.x === A.x ? (B.y > A.y ? -NH / 2 : NH / 2) : 0);
        const path = rejected
          ? `M ${A.x - NW / 2 + 10} ${A.y - NH / 2} C ${A.x - 60} ${A.y - 110}, ${B.x + 60} ${B.y - 80}, ${B.x + NW / 2 - 10} ${B.y - NH / 2}`
          : `M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`;
        return (
          <g key={`${a}-${b}`}>
            <path d={path} fill="none" stroke={rejected ? "var(--danger)" : "var(--line-2)"} strokeWidth={1.6} strokeDasharray={rejected ? "5 5" : undefined} markerEnd={rejected ? "url(#arr-r)" : "url(#arr)"} />
            {rejected && <text x={(A.x + B.x) / 2} y={A.y - 108} fontSize={12} textAnchor="middle" fill="var(--danger)" fontFamily="var(--font-mono)">rejected → rewrite</text>}
          </g>
        );
      })}
      {NODES.map((n) => {
        const s = agents[n.id];
        const last = recent.get(n.id);
        const hot = last && now - last.started_at < 25;
        const killed = s?.killed;
        const open = s?.circuit === "open";
        const stroke = killed ? "var(--danger)" : last?.status === "rejected" && hot ? "var(--danger)" : hot ? "var(--pitch)" : "var(--line-2)";
        const avg = s && s.calls ? s.latency_ms_total / s.calls : 0;
        return (
          <g key={n.id} transform={`translate(${n.x - NW / 2}, ${n.y - NH / 2})`}>
            <rect width={NW} height={NH} rx={10} fill={killed ? "var(--danger-2)" : "var(--surface)"} stroke={stroke} strokeWidth={hot || killed ? 2.2 : 1.2} />
            {hot && !killed && <rect width={NW} height={NH} rx={10} fill="none" stroke={stroke} strokeWidth={6} opacity={0.15} />}
            <text x={12} y={21} fontSize={14} fontWeight={700} fill="var(--ink)">{n.label}</text>
            <text x={12} y={39} fontSize={11} fill="var(--muted)" fontFamily="var(--font-mono)">
              {killed ? "OFFLINE (chaos)" : open ? "circuit open" : s ? `${s.calls} calls · ${avg.toFixed(0)} ms` : n.role}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
