"use client";

import { isRtl, MOMENT_LABEL } from "@/lib/format";
import type { Insight, Moment, Personalized } from "@/lib/types";
import FactChip from "./FactChip";

interface Props {
  matchId: string;
  moments: Moment[];
  insights: Record<string, Insight>;
  personalized: Record<string, Personalized>;
  lang: string;
  minImportance?: number;
  limit?: number;
  highlightKinds?: string[];
}

function tone(m: Moment): string {
  if (m.type === "goal") return "goal";
  if (m.type === "red_card") return "red";
  return m.importance >= 60 ? "hot" : "";
}

export default function MomentFeed({ matchId, moments, insights, personalized, lang, minImportance = 30, limit = 40, highlightKinds = [] }: Props) {
  const items = moments.filter((m) => m.importance >= minImportance).slice(-limit).reverse();
  if (!items.length) {
    return (
      <div style={{ padding: "28px 18px", color: "var(--muted)", fontSize: 14 }}>
        Key moments appear here as they happen, each explained and fact-checked.
      </div>
    );
  }
  return (
    <div>
      {items.map((m) => {
        const p = personalized[m.moment_id];
        const i = insights[m.moment_id];
        const text = p?.text ?? i?.text;
        const head = p?.headline ?? m.title;
        const cited = p?.cited_fact_ids ?? i?.cited_fact_ids ?? [];
        const rtl = p ? isRtl(p.lang) : false;
        return (
          <article key={m.moment_id} className={`moment ${tone(m)}`} dir={rtl ? "rtl" : undefined}>
            <div className="moment-meta" dir="ltr">
              <span className="moment-minute">{m.minute}&apos;</span>
              <span className={`chip ${m.type === "goal" ? "green" : m.type === "red_card" ? "danger" : m.importance >= 60 ? "signal" : ""}`}>
                {MOMENT_LABEL[m.type] ?? m.type}
              </span>
              {m.facts.some((f) => highlightKinds.includes(f.kind)) && <span className="chip dark" title="Involves the metric you pinned">★ your metric</span>}
              {i?.fallback && <span className="chip" title="Model unavailable or rejected; verified template used">template</span>}
              {i && i.attempts > 1 && <span className="chip signal" title="Guardian rejected the first draft">rewritten ×{i.attempts - 1}</span>}
              <span className="faint mono" style={{ marginLeft: "auto", fontSize: 11 }}>{m.importance}</span>
            </div>
            <h3 className="moment-head">{head}</h3>
            {text ? (
              <p className="moment-text" lang={p?.lang ?? lang}>{text}</p>
            ) : (
              <span className="analysing" aria-live="polite">
                <i /><i /><i /> Explaining and fact-checking…
              </span>
            )}
            {cited.length > 0 && (
              <div className="moment-cites" dir="ltr">
                {cited.slice(0, 5).map((fid) => (
                  <FactChip key={fid} matchId={matchId} factId={fid} fact={m.facts.find((f) => f.fact_id === fid)} />
                ))}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
