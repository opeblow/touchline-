"use client";

import { useEffect, useRef, useState } from "react";
import type { MatchMeta } from "@/lib/types";
import type { PartyState } from "@/lib/useMatch";

const REACTIONS = ["GOAL", "WOW", "CLAP", "COME ON", "NOOO", "HAHA", "UNREAL", "REF!"];
const ENTRA_CLIENT_ID = process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID || "";
const KEY = "touchline.identity";

interface Identity { name: string; provider: "microsoft" | "guest"; member_id: string; club: string | null }

function loadIdentity(): Identity | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Identity) : null;
  } catch {
    return null;
  }
}
function saveIdentity(id: Identity | null) {
  try {
    if (id) localStorage.setItem(KEY, JSON.stringify(id));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable */
  }
}

async function signInWithMicrosoft(): Promise<{ name: string; id: string }> {
  const { PublicClientApplication } = await import("@azure/msal-browser");
  const pca = new PublicClientApplication({
    auth: { clientId: ENTRA_CLIENT_ID, authority: "https://login.microsoftonline.com/common", redirectUri: window.location.origin },
    cache: { cacheLocation: "sessionStorage" },
  });
  await pca.initialize();
  const r = await pca.loginPopup({ scopes: ["User.Read"], prompt: "select_account" });
  return { name: r.account?.name || r.account?.username || "Microsoft user", id: "ms-" + (r.account?.localAccountId || r.uniqueId).slice(0, 16) };
}

function Avatar({ m, size = 30 }: { m: { avatar: string; provider: string; club: string | null }; size?: number }) {
  return (
    <span title={m.provider === "microsoft" ? "Signed in with Microsoft" : "Guest"} style={{
      width: size, height: size, borderRadius: "50%", display: "inline-grid", placeItems: "center", flexShrink: 0,
      background: m.provider === "microsoft" ? "#0f6cbd" : "var(--paper-2)", color: m.provider === "microsoft" ? "#fff" : "var(--ink)",
      fontSize: size * 0.4, fontWeight: 700, border: "2px solid var(--surface)", boxShadow: "0 0 0 1px var(--line)",
    }}>{m.avatar}</span>
  );
}

export default function WatchParty({ party, send, connected, meta }: {
  party: PartyState; send: (m: Record<string, unknown>) => void; connected: boolean; meta: MatchMeta;
}) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [name, setName] = useState("");
  const [club, setClub] = useState<string>("home");
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);

  useEffect(() => setIdentity(loadIdentity()), []);

  // (Re)join whenever we (re)connect.
  useEffect(() => {
    if (connected && identity) send({ type: "join", ...identity });
  }, [connected, identity, send]);

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" });
  }, [party.chat.length]);

  async function joinMicrosoft() {
    setErr(null);
    try {
      const r = await signInWithMicrosoft();
      const id: Identity = { name: r.name, provider: "microsoft", member_id: r.id, club };
      saveIdentity(id);
      setIdentity(id);
    } catch (e: any) {
      setErr(e?.message?.split("\n")[0] ?? "Sign-in cancelled");
    }
  }
  function joinGuest() {
    if (!name.trim()) return;
    const id: Identity = { name: name.trim(), provider: "guest", member_id: "g-" + Math.random().toString(36).slice(2, 12), club };
    saveIdentity(id);
    setIdentity(id);
  }

  const teamName = (c: string | null) => (c === "home" ? meta.home.short_name : c === "away" ? meta.away.short_name : "");
  const total = party.tally.home + party.tally.away + party.tally.none || 1;

  if (!identity || !party.me) {
    return (
      <div style={{ padding: 18 }} className="stack">
        <div className="display" style={{ fontSize: 26, lineHeight: 1 }}>Watch together</div>
        <p className="muted" style={{ margin: 0, fontSize: 14 }}>
          Join the watch party: chat with other fans, send reactions into the stadium and predict who scores next. Points go on the live leaderboard.
        </p>
        <div className="row wrap" style={{ gap: 8 }}>
          <span className="eyebrow">Supporting</span>
          <div className="seg">
            <button className={club === "home" ? "on" : ""} onClick={() => setClub("home")}>{meta.home.short_name}</button>
            <button className={club === "away" ? "on" : ""} onClick={() => setClub("away")}>{meta.away.short_name}</button>
          </div>
        </div>
        <button className="btn" style={{ background: "#0f6cbd", borderColor: "#0f6cbd", height: 44 }} onClick={joinMicrosoft} disabled={!ENTRA_CLIENT_ID}
          title={ENTRA_CLIENT_ID ? "Sign in with your Microsoft account" : "Set NEXT_PUBLIC_ENTRA_CLIENT_ID to enable Microsoft sign-in"}>
          <svg width="16" height="16" viewBox="0 0 21 21" aria-hidden><rect x="1" y="1" width="9" height="9" fill="#f25022" /><rect x="11" y="1" width="9" height="9" fill="#7fba00" /><rect x="1" y="11" width="9" height="9" fill="#00a4ef" /><rect x="11" y="11" width="9" height="9" fill="#ffb900" /></svg>
          Sign in with Microsoft
        </button>
        {!ENTRA_CLIENT_ID && <span className="faint" style={{ fontSize: 12 }}>Microsoft sign-in activates once an Entra app ID is configured. Guests can join now.</span>}
        <div className="row" style={{ gap: 8 }}>
          <input className="input" placeholder="Your name" value={name} maxLength={28} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && joinGuest()} />
          <button className="btn secondary" onClick={joinGuest} disabled={!name.trim()}>Join as guest</button>
        </div>
        {err && <span style={{ color: "var(--danger)", fontSize: 13 }}>{err}</span>}
        {identity && !party.me && <span className="analysing"><i /><i /><i /> Joining…</span>}
      </div>
    );
  }

  return (
    <div className="stack" style={{ gap: 0 }}>
      {/* who's here */}
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
        <div className="row between">
          <span className="row" style={{ gap: 8 }}>
            <Avatar m={party.me} /> <b>{party.me.name}</b>
            <span className="chip mono">{party.members.find((m) => m.id === party.me!.id)?.points ?? 0} pts</span>
          </span>
          <button className="chip" style={{ cursor: "pointer" }} onClick={() => { saveIdentity(null); setIdentity(null); location.reload(); }}>Leave</button>
        </div>
        <div className="row wrap" style={{ gap: 4, marginTop: 10 }}>
          {party.members.slice(0, 14).map((m) => <Avatar key={m.id} m={m} size={26} />)}
          <span className="muted" style={{ fontSize: 12.5, marginLeft: 6 }}>{party.members.length} watching</span>
        </div>
      </div>

      {/* prediction */}
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--line)" }}>
        <div className="row between" style={{ marginBottom: 8 }}>
          <span className="panel-title" style={{ fontSize: 15 }}>Who scores next?</span>
          <span className="mono faint" style={{ fontSize: 12 }}>round {party.round} · +10 pts</span>
        </div>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
          {([["home", meta.home.short_name, meta.home.primary], ["none", "No goal", "#5e6661"], ["away", meta.away.short_name, meta.away.primary]] as const).map(([k, label, color]) => (
            <button key={k} onClick={() => send({ type: "predict", pick: k })}
              style={{ border: `2px solid ${party.myPick === k ? color : "var(--line)"}`, background: party.myPick === k ? "var(--paper-2)" : "var(--surface)", borderRadius: 10, padding: "8px 6px", cursor: "pointer", textAlign: "left" }}>
              <div style={{ fontWeight: 700, fontSize: 13 }}>{label}</div>
              <div style={{ height: 5, borderRadius: 3, background: "var(--paper-2)", marginTop: 6, overflow: "hidden" }}>
                <div style={{ width: `${(party.tally[k] / total) * 100}%`, height: "100%", background: color, transition: "width 300ms" }} />
              </div>
              <div className="mono faint" style={{ fontSize: 11, marginTop: 3 }}>{party.tally[k]} picks</div>
            </button>
          ))}
        </div>
        {party.lastSettled && (
          <div className="fade-in" style={{ marginTop: 10, fontSize: 13, padding: "8px 10px", borderRadius: 8, background: "var(--signal-2)" }}>
            <b>{party.lastSettled.label}</b> settled round {party.lastSettled.round}.{" "}
            {party.lastSettled.winners.length ? `+10 for ${party.lastSettled.winners.slice(0, 4).join(", ")}${party.lastSettled.winners.length > 4 ? "…" : ""}` : "Nobody called it."}
          </div>
        )}
      </div>

      {/* leaderboard */}
      <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--line)" }}>
        <span className="eyebrow">Leaderboard</span>
        {party.members.slice(0, 5).map((m, i) => (
          <div key={m.id} className="row between" style={{ fontSize: 13.5, padding: "4px 0" }}>
            <span className="row" style={{ gap: 8 }}><span className="mono faint" style={{ width: 14 }}>{i + 1}</span><Avatar m={m} size={22} />{m.name}{m.club && <span className="faint" style={{ fontSize: 11.5 }}>· {teamName(m.club)}</span>}</span>
            <span className="mono" style={{ fontWeight: 600 }}>{m.points}</span>
          </div>
        ))}
      </div>

      {/* chat */}
      <div ref={chatRef} className="scroll" style={{ maxHeight: 260, minHeight: 120, padding: "8px 16px" }}>
        {party.chat.length === 0 && <div className="muted" style={{ fontSize: 13, padding: "8px 0" }}>Say something to the other fans.</div>}
        {party.chat.map((c) => (
          <div key={c.id} className="row" style={{ gap: 8, alignItems: "flex-start", padding: "5px 0" }}>
            <Avatar m={c.member} size={24} />
            <div style={{ fontSize: 13.5, lineHeight: 1.35 }}>
              <b>{c.member.name}</b> <span className="mono faint" style={{ fontSize: 11 }}>{c.minute}&apos;</span>
              <div>{c.text}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ padding: "8px 16px 14px", borderTop: "1px solid var(--line)" }} className="stack">
        <div className="row wrap" style={{ gap: 4 }}>
          {REACTIONS.map((e) => (
            <button key={e} onClick={() => send({ type: "react", emoji: e })} style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: "0.04em", background: "var(--paper-2)", border: "1px solid var(--line)", borderRadius: 999, padding: "0 10px", height: 30, cursor: "pointer" }} aria-label={`React ${e}`}>{e}</button>
          ))}
        </div>
        <form className="row" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); if (text.trim()) { send({ type: "chat", text }); setText(""); } }}>
          <input className="input" value={text} maxLength={240} onChange={(e) => setText(e.target.value)} placeholder="Message the party…" />
          <button className="btn green" disabled={!text.trim()}>Send</button>
        </form>
        {party.blocked && <span style={{ color: "var(--danger)", fontSize: 12.5 }}>{party.blocked}</span>}
      </div>
    </div>
  );
}

export function FloatingReactions({ reactions }: { reactions: { id: string; emoji: string; name: string; at: number }[] }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, []);
  const live = reactions.filter((r) => now - r.at < 3500);
  return (
    <div aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }}>
      {live.map((r) => {
        const left = 10 + (parseInt(r.id.slice(0, 4), 36) % 80);
        return (
          <div key={r.id} style={{ position: "absolute", left: `${left}%`, bottom: 10, animation: "floatUp 3.4s ease-out forwards", textAlign: "center" }}>
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 26, color: "#fff", background: "var(--pitch)", borderRadius: 10, padding: "4px 12px", boxShadow: "0 6px 16px rgba(0,0,0,.35)" }}>{r.emoji}</div>
            <div style={{ fontSize: 11, color: "#fff", background: "rgba(0,0,0,.45)", borderRadius: 6, padding: "1px 6px" }}>{r.name}</div>
          </div>
        );
      })}
    </div>
  );
}
