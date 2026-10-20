"use client";

import { useState } from "react";
import { post } from "@/lib/api";

const SUGGESTIONS = ["Why did the momentum change?", "Who is the fastest player?", "Who deserves to be winning?", "How hard are they pressing?"];

export default function AskBox({ matchId, lang }: { matchId: string; lang: string }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answers, setAnswers] = useState<{ q: string; a: string; tools: string[]; model: string }[]>([]);

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true);
    try {
      const r = await post(`/api/matches/${matchId}/ask`, { question, lang });
      setAnswers((xs) => [{ q: question, a: r.answer, tools: r.tools, model: r.model }, ...xs].slice(0, 5));
      setQ("");
    } catch (e: any) {
      setAnswers((xs) => [{ q: question, a: `Could not answer: ${e.message}`, tools: [], model: "error" }, ...xs]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: 12 }}>
      <form className="row" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about this match…" aria-label="Ask a question about the match" />
        <button className="btn green" disabled={busy || !q.trim()}>{busy ? "…" : "Ask"}</button>
      </form>
      <div className="row wrap" style={{ gap: 6 }}>
        {SUGGESTIONS.map((s) => (
          <button key={s} className="chip" style={{ cursor: "pointer" }} onClick={() => ask(s)}>{s}</button>
        ))}
      </div>
      {answers.map((x, i) => (
        <div key={i} className="fade-in" style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
          <div style={{ fontWeight: 600, fontSize: 13.5 }}>{x.q}</div>
          <p style={{ margin: "4px 0 6px", fontSize: 14.5 }}>{x.a}</p>
          <div className="row wrap" style={{ gap: 6 }}>
            <span className="chip green">✓ numbers verified</span>
            {x.tools.map((t) => <span key={t} className="chip cite">{t}()</span>)}
            <span className="chip">{x.model}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
