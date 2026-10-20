"use client";

import type { Moment } from "@/lib/types";

interface Props {
  series: [number, number][]; // (t seconds, -100..100, + = home)
  homeColor: string;
  awayColor: string;
  moments?: Moment[];
  height?: number;
  homeCode: string;
  awayCode: string;
}

const W = 600;

export default function MomentumWave({ series, homeColor, awayColor, moments = [], height = 120, homeCode, awayCode }: Props) {
  const H = height;
  const mid = H / 2;
  const maxT = Math.max(95 * 60, ...series.map((s) => s[0]));
  const x = (t: number) => (t / maxT) * W;
  const y = (v: number) => mid - (v / 100) * (mid - 6);
  const pts = series.length ? series : ([[0, 0]] as [number, number][]);
  const line = pts.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(pts[pts.length - 1][0]).toFixed(1)},${mid} L${x(pts[0][0]).toFixed(1)},${mid} Z`;
  const goals = moments.filter((m) => m.type === "goal" || m.type === "red_card");
  const last = pts[pts.length - 1];
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="Momentum over the match" preserveAspectRatio="none">
        <defs>
          <clipPath id="mw-top"><rect x={0} y={0} width={W} height={mid} /></clipPath>
          <clipPath id="mw-bot"><rect x={0} y={mid} width={W} height={mid} /></clipPath>
        </defs>
        <rect x={x(45 * 60)} y={0} width={1} height={H} fill="var(--line-2)" />
        <line x1={0} x2={W} y1={mid} y2={mid} stroke="var(--line-2)" strokeWidth={1} />
        <path d={area} fill={homeColor} opacity={0.28} clipPath="url(#mw-top)" />
        <path d={area} fill={awayColor} opacity={0.28} clipPath="url(#mw-bot)" />
        <path d={line} fill="none" stroke="var(--ink)" strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
        {goals.map((g) => (
          <g key={g.moment_id} transform={`translate(${x(g.t)},${g.team === "home" ? 8 : H - 8})`}>
            <circle r={4.5} fill={g.type === "red_card" ? "var(--danger)" : g.team === "home" ? homeColor : awayColor} stroke="#fff" strokeWidth={1.5} />
          </g>
        ))}
        {last && <circle cx={x(last[0])} cy={y(last[1])} r={3.5} fill="var(--signal)" stroke="var(--ink)" strokeWidth={1} />}
      </svg>
      <figcaption className="row between" style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 4 }}>
        <span className="mono">0&apos;</span>
        <span className="row" style={{ gap: 14 }}>
          <span className="row" style={{ gap: 5 }}><i style={{ width: 8, height: 8, borderRadius: 2, background: homeColor, display: "inline-block" }} />{homeCode} on top</span>
          <span className="row" style={{ gap: 5 }}><i style={{ width: 8, height: 8, borderRadius: 2, background: awayColor, display: "inline-block" }} />{awayCode} on top</span>
        </span>
        <span className="mono">90&apos;</span>
      </figcaption>
    </figure>
  );
}
