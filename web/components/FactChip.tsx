"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Fact } from "@/lib/types";

/** A citation chip. Click to see the verified fact and the raw events it came from. */
export default function FactChip({ matchId, factId, fact }: { matchId: string; factId: string; fact?: Fact }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<{ display: string; fact: Fact; events: any[] } | null>(null);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open || detail) return;
    api(`/api/matches/${matchId}/facts/${factId}`).then(setDetail).catch(() => undefined);
  }, [open, detail, matchId, factId]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const label = fact?.label ?? detail?.fact.label ?? factId;
  return (
    <span ref={ref} style={{ position: "relative" }}>
      <button className="chip cite" onClick={() => setOpen((o) => !o)} aria-expanded={open} title={label}>
        {factId}
      </button>
      {open && (
        <span className="popover" role="dialog" style={{ top: 30, left: 0 }}>
          <span className="k">Verified fact · {factId}</span>
          <div style={{ fontWeight: 600, marginTop: 4 }}>{label}</div>
          <div className="mono" style={{ fontSize: 22, margin: "4px 0 6px", color: "var(--signal)" }}>
            {detail?.display ?? "…"}
          </div>
          {detail && detail.events.length > 0 && (
            <>
              <span className="k">Source events</span>
              {detail.events.slice(0, 3).map((e) => (
                <div key={e.event_id} className="mono" style={{ fontSize: 11.5, color: "#cfd8d3", marginTop: 3 }}>
                  {e.event_id.split("-").pop()} · {e.minute}&apos; {e.type} {e.outcome ?? ""}
                </div>
              ))}
            </>
          )}
          {detail && detail.events.length === 0 && (
            <span style={{ fontSize: 12, color: "#cfd8d3" }}>Computed by the stats engine from tracking and events.</span>
          )}
        </span>
      )}
    </span>
  );
}
