"use client";

import { LANGS, MODES } from "@/lib/format";
import type { MatchMeta } from "@/lib/types";
import type { Prefs } from "@/lib/useMatch";

export default function PersonalizeBar({ prefs, onChange, meta }: { prefs: Prefs; onChange: (p: Prefs) => void; meta: MatchMeta | null }) {
  const players = meta ? [...meta.home.players, ...meta.away.players] : [];
  return (
    <div className="row wrap" style={{ gap: 10 }}>
      <div className="seg" role="tablist" aria-label="Viewing mode">
        {MODES.map((m) => (
          <button
            key={m.id}
            role="tab"
            aria-selected={prefs.mode === m.id}
            className={prefs.mode === m.id ? "on" : ""}
            title={m.hint}
            onClick={() =>
              onChange({
                ...prefs,
                mode: m.id,
                club: m.id === "club" ? prefs.club ?? "home" : null,
                player_id: m.id === "player" ? prefs.player_id ?? meta?.home.players[9]?.id ?? null : null,
              })
            }
          >
            {m.label}
          </button>
        ))}
      </div>
      {prefs.mode === "club" && meta && (
        <select className="select" aria-label="Your club" value={prefs.club ?? "home"} onChange={(e) => onChange({ ...prefs, club: e.target.value as any })}>
          <option value="home">{meta.home.name}</option>
          <option value="away">{meta.away.name}</option>
        </select>
      )}
      {prefs.mode === "player" && meta && (
        <select className="select" aria-label="Player to follow" value={prefs.player_id ?? ""} onChange={(e) => onChange({ ...prefs, player_id: e.target.value })}>
          {players.map((p) => (
            <option key={p.id} value={p.id}>
              {p.number} {p.name} ({p.id.startsWith(meta.home.code.toLowerCase()) ? meta.home.code : meta.away.code})
            </option>
          ))}
        </select>
      )}
      <select className="select" aria-label="Language" value={prefs.lang} onChange={(e) => onChange({ ...prefs, lang: e.target.value })}>
        {LANGS.map((l) => (
          <option key={l.code} value={l.code}>
            {l.native}
          </option>
        ))}
      </select>
    </div>
  );
}
