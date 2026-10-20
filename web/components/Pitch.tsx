"use client";

import { memo } from "react";
import type { Cue, Frame } from "@/lib/types";

interface Props {
  frame: Frame | null;
  ids: (string | null)[];
  numbers: Record<string, number>;
  homeColor: string;
  awayColor: string;
  focusId?: string | null;
  cues?: Cue[];
  dark?: boolean;
}

function textOn(hex: string): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? "#0f1412" : "#ffffff";
}

const STRIPES = Array.from({ length: 12 }, (_, i) => i);

function Markings({ stroke }: { stroke: string }) {
  const s = { fill: "none", stroke, strokeWidth: 0.35 } as const;
  return (
    <g>
      <rect x={0.5} y={0.5} width={104} height={67} {...s} />
      <line x1={52.5} y1={0.5} x2={52.5} y2={67.5} {...s} />
      <circle cx={52.5} cy={34} r={9.15} {...s} />
      <circle cx={52.5} cy={34} r={0.45} fill={stroke} />
      <rect x={0.5} y={13.84} width={16.5} height={40.32} {...s} />
      <rect x={88} y={13.84} width={16.5} height={40.32} {...s} />
      <rect x={0.5} y={24.84} width={5.5} height={18.32} {...s} />
      <rect x={99} y={24.84} width={5.5} height={18.32} {...s} />
      <circle cx={11} cy={34} r={0.4} fill={stroke} />
      <circle cx={94} cy={34} r={0.4} fill={stroke} />
      <path d="M 17 26.7 A 9.15 9.15 0 0 1 17 41.3" {...s} />
      <path d="M 88 26.7 A 9.15 9.15 0 0 0 88 41.3" {...s} />
      <rect x={-1.5} y={30.34} width={2} height={7.32} {...s} />
      <rect x={104.5} y={30.34} width={2} height={7.32} {...s} />
    </g>
  );
}

function Pitch({ frame, ids, numbers, homeColor, awayColor, focusId, cues = [], dark }: Props) {
  const line = dark ? "rgba(255,255,255,0.55)" : "rgba(255,255,255,0.78)";
  const homeText = textOn(homeColor);
  const awayText = textOn(awayColor);
  const badges = cues.filter((c) => c.template === "speed_badge" && c.data.player_id);
  return (
    <div className="pitch-wrap" style={{ background: dark ? "#123d2b" : undefined }}>
      <svg viewBox="-2 -2 109 72" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Live 2D pitch">
        <rect x={-2} y={-2} width={109} height={72} fill={dark ? "#123d2b" : "var(--grass-a)"} />
        {STRIPES.map((i) =>
          i % 2 ? <rect key={i} x={0.5 + (104 / 12) * i} y={0.5} width={104 / 12} height={67} fill={dark ? "#15452f" : "var(--grass-b)"} /> : null,
        )}
        <Markings stroke={line} />
        {frame?.p.map((pt, slot) => {
          if (!pt) return null;
          const pid = ids[slot];
          const home = slot < 11;
          const focus = pid && focusId === pid;
          const fill = home ? homeColor : awayColor;
          return (
            <g key={slot} className="pitch-player" style={{ transform: `translate(${pt[0]}px, ${pt[1]}px)` }}>
              {focus && <circle r={2.6} fill="none" stroke="var(--signal)" strokeWidth={0.45} />}
              <circle r={1.45} fill={fill} stroke={home ? "rgba(0,0,0,0.35)" : "rgba(255,255,255,0.8)"} strokeWidth={0.22} />
              <text className="pitch-label" fill={home ? homeText : awayText}>
                {pid ? numbers[pid] ?? "" : ""}
              </text>
            </g>
          );
        })}
        {frame && (
          <g className="pitch-ball" style={{ transform: `translate(${frame.b[0]}px, ${frame.b[1]}px)` }}>
            <circle r={0.75} fill="#fff" stroke="#0f1412" strokeWidth={0.22} />
          </g>
        )}
        {frame &&
          badges.map((c) => {
            const slot = ids.indexOf(c.data.player_id);
            const pt = slot >= 0 ? frame.p[slot] : null;
            if (!pt) return null;
            const label = c.data.speed_kmh ? `${Number(c.data.speed_kmh).toFixed(1)} km/h` : `${c.data.distance_km} km`;
            return (
              <g key={c.cue_id} style={{ transform: `translate(${pt[0]}px, ${pt[1] - 4.2}px)` }} className="pitch-player">
                <rect x={-6.2} y={-1.7} width={12.4} height={3.4} rx={0.8} fill="#0f1412" />
                <text className="pitch-label" fill="#f2a900" style={{ fontSize: 1.9 }}>
                  {label}
                </text>
              </g>
            );
          })}
      </svg>
    </div>
  );
}

export default memo(Pitch);
