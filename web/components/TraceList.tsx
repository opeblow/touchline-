import type { Trace } from "@/lib/types";

export default function TraceList({ traces, limit = 120, filter }: { traces: Trace[]; limit?: number; filter?: (t: Trace) => boolean }) {
  const rows = (filter ? traces.filter(filter) : traces).slice(-limit).reverse();
  if (!rows.length) return <div style={{ padding: 18, color: "var(--muted)" }}>Agent activity streams here once the match starts.</div>;
  return (
    <div role="log" aria-live="polite">
      {rows.map((t) => (
        <div className="trace" key={t.trace_id}>
          <span className="when">{Math.floor(t.started_at / 60) + 1}&apos;</span>
          <span className="who">
            <span className={`status-${t.status}`} style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: "currentColor", marginRight: 6, verticalAlign: "middle" }} />{t.agent}
          </span>
          <span className="what" title={t.detail}>
            <span style={{ fontWeight: 600 }}>{t.action}</span>
            {t.detail ? <span className="muted"> — {t.detail}</span> : null}
            {t.handoff_to ? <span className="faint"> → {t.handoff_to}</span> : null}
          </span>
          <span className="meta">
            {t.status !== "ok" && <span className={`status-${t.status}`} style={{ marginRight: 8, textTransform: "uppercase" }}>{t.status}</span>}
            {t.latency_ms.toFixed(0)} ms{t.tokens_in + t.tokens_out ? ` · ${t.tokens_in + t.tokens_out} tok` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}
