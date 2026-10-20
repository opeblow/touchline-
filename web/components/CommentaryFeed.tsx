import { isRtl } from "@/lib/format";
import type { Commentary } from "@/lib/types";

const TONE: Record<string, string> = { excited: "var(--signal)", build: "var(--pitch)", calm: "var(--line-2)", somber: "var(--muted)" };

export default function CommentaryFeed({ lines, lang }: { lines: Commentary[]; lang: string }) {
  const rows = lines.filter((l) => l.lang === lang).slice(-30).reverse();
  if (!rows.length) return <div style={{ padding: 18, color: "var(--muted)" }}>Live commentary appears here.</div>;
  return (
    <div dir={isRtl(lang) ? "rtl" : undefined}>
      {rows.map((l) => (
        <p key={l.line_id} lang={l.lang} style={{ margin: 0, padding: "10px 16px", borderBottom: "1px solid var(--line)", borderInlineStart: `3px solid ${TONE[l.tone]}`, fontSize: 14.5, fontWeight: l.tone === "excited" ? 600 : 400 }}>
          {l.text}
        </p>
      ))}
    </div>
  );
}
