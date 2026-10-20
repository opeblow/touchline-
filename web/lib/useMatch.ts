"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { api, post, wsUrl } from "./api";
import type {
  AgentStatus,
  Commentary,
  Cue,
  Frame,
  Insight,
  MatchEvent,
  MatchMeta,
  Mode,
  Moment,
  Personalized,
  Recap,
  Side,
  Snapshot,
  Status,
  Tactical,
  Trace,
  WireMessage,
} from "./types";

export interface Prefs {
  mode: Mode;
  lang: string;
  club: Side | null;
  player_id: string | null;
}

export interface MatchState {
  meta: MatchMeta | null;
  status: Status | null;
  stats: Snapshot | null;
  moments: Moment[];
  insights: Record<string, Insight>;
  personalized: Record<string, Personalized>;
  commentary: Commentary[];
  cues: Cue[];
  traces: Trace[];
  recaps: Recap[];
  tactical: Tactical[];
  events: MatchEvent[];
  frame: Frame | null;
  ids: (string | null)[];
  now: number;
  agents: Record<string, AgentStatus>;
  connected: boolean;
  error: string | null;
  subKey: string;
  party: PartyState;
}

export interface PartyMember { id: string; name: string; provider: string; avatar: string; club: string | null; points: number }
export interface PartyState {
  me: PartyMember | null;
  members: PartyMember[];
  chat: { id: string; member: PartyMember; text: string; minute: number }[];
  round: number;
  tally: { home: number; away: number; none: number };
  myPick: string | null;
  lastSettled: any | null;
  reactions: { id: string; emoji: string; name: string; at: number }[];
  blocked: string | null;
}

const initial: MatchState = {
  meta: null,
  status: null,
  stats: null,
  moments: [],
  insights: {},
  personalized: {},
  commentary: [],
  cues: [],
  traces: [],
  recaps: [],
  tactical: [],
  events: [],
  frame: null,
  ids: [],
  now: 0,
  agents: {},
  connected: false,
  error: null,
  subKey: "fan:en:-:-",
  party: { me: null, members: [], chat: [], round: 1, tally: { home: 0, away: 0, none: 0 }, myPick: null, lastSettled: null, reactions: [], blocked: null },
};

type Action =
  | { type: "state"; data: any }
  | { type: "msg"; msg: WireMessage }
  | { type: "connected"; value: boolean }
  | { type: "error"; error: string }
  | { type: "pick"; pick: string };

const cap = <T,>(arr: T[], n: number) => (arr.length > n ? arr.slice(arr.length - n) : arr);

function reducer(s: MatchState, a: Action): MatchState {
  switch (a.type) {
    case "connected":
      return { ...s, connected: a.value };
    case "error":
      return { ...s, error: a.error };
    case "pick":
      return { ...s, party: { ...s.party, myPick: a.pick } };
    case "state": {
      const d = a.data;
      const insights: Record<string, Insight> = {};
      for (const i of d.insights || []) insights[i.moment_id] = i;
      const personalized: Record<string, Personalized> = {};
      for (const p of d.personalized || []) personalized[p.moment_id] = p;
      return {
        ...s,
        meta: d.meta,
        status: d.status,
        stats: d.stats,
        moments: d.moments || [],
        insights,
        personalized,
        commentary: d.commentary || [],
        cues: d.cues || [],
        recaps: d.recaps || [],
        tactical: d.tactical || [],
        traces: d.traces || [],
        agents: d.agents || {},
        ids: d.ids && d.ids.length ? d.ids : s.ids,
        now: d.status?.t ?? 0,
        error: null,
      };
    }
    case "msg": {
      const { kind, data } = a.msg;
      switch (kind) {
        case "hello":
          return { ...s, subKey: data.sub_key, status: { ...(s.status || ({} as Status)), ...data } };
        case "frame": {
          const ids = data.ids ?? s.ids;
          const now = typeof data.i === "number" ? data.i / 5 : s.now;
          return { ...s, frame: data, ids, now };
        }
        case "stats":
          return { ...s, stats: data };
        case "status":
          return { ...s, status: data };
        case "event":
          return { ...s, events: cap([...s.events, data], 40) };
        case "moment":
          if (s.moments.some((m) => m.moment_id === data.moment_id)) return s;
          return { ...s, moments: cap([...s.moments, data], 200) };
        case "insight":
          return { ...s, insights: { ...s.insights, [data.moment_id]: data } };
        case "personalized":
          if (data.sub_key !== s.subKey) return s;
          return { ...s, personalized: { ...s.personalized, [data.moment_id]: data } };
        case "commentary":
          return { ...s, commentary: cap([...s.commentary, data], 120) };
        case "cue":
          return { ...s, cues: cap([...s.cues, data], 80) };
        case "trace":
          return { ...s, traces: cap([...s.traces, data], 400) };
        case "recap":
          return { ...s, recaps: [...s.recaps.filter((r) => r.recap_id !== data.recap_id), data] };
        case "tactical":
          return { ...s, tactical: [...s.tactical, data] };
        case "party": {
          const p = s.party;
          switch (data.type) {
            case "welcome":
              return { ...s, party: { ...p, me: data.me, members: data.members, chat: data.chat, round: data.round, tally: data.tally, myPick: data.my_pick } };
            case "presence":
              return { ...s, party: { ...p, members: data.members } };
            case "chat":
              return { ...s, party: { ...p, chat: cap([...p.chat, data.message], 120) } };
            case "react":
              return { ...s, party: { ...p, reactions: cap([...p.reactions, { id: Math.random().toString(36).slice(2), emoji: data.emoji, name: data.member.name, at: Date.now() }], 30) } };
            case "tally":
              return { ...s, party: { ...p, tally: data.tally, round: data.round } };
            case "settled":
              return { ...s, party: { ...p, lastSettled: data, members: data.members, round: data.round + 1, tally: { home: 0, away: 0, none: 0 }, myPick: null } };
            case "blocked":
              return { ...s, party: { ...p, blocked: data.reason } };
            default:
              return s;
          }
        }
        default:
          return s;
      }
    }
  }
}

export function subKeyOf(p: Prefs): string {
  return `${p.mode}:${p.lang}:${p.club ?? "-"}:${p.player_id ?? "-"}`;
}

export function useMatch(matchId: string, prefs: Prefs, opts: { frames?: boolean } = {}) {
  const [state, dispatch] = useReducer(reducer, initial);
  const wsRef = useRef<WebSocket | null>(null);
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const frames = opts.frames ?? true;

  const loadState = useCallback(async () => {
    const p = prefsRef.current;
    const q = new URLSearchParams({ mode: p.mode, lang: p.lang });
    if (p.club) q.set("club", p.club);
    if (p.player_id) q.set("player_id", p.player_id);
    try {
      const data = await api(`/api/matches/${matchId}/state?${q}`);
      dispatch({ type: "state", data });
    } catch (e: any) {
      dispatch({ type: "error", error: e.message || String(e) });
    }
  }, [matchId]);

  // Connect once per match; reconnect with backoff.
  useEffect(() => {
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      const p = prefsRef.current;
      const q = new URLSearchParams({ mode: p.mode, lang: p.lang, frames: String(frames) });
      if (p.club) q.set("club", p.club);
      if (p.player_id) q.set("player_id", p.player_id);
      const ws = new WebSocket(wsUrl(`/ws/matches/${matchId}?${q}`));
      wsRef.current = ws;
      ws.onopen = () => {
        retry = 0;
        dispatch({ type: "connected", value: true });
        loadState();
      };
      ws.onmessage = (ev) => {
        try {
          dispatch({ type: "msg", msg: JSON.parse(ev.data) });
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        dispatch({ type: "connected", value: false });
        if (!closed) timer = setTimeout(connect, Math.min(8000, 500 * 2 ** retry++));
      };
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      wsRef.current?.close();
    };
  }, [matchId, frames, loadState]);

  // Personalisation change: tell the server, then reload history for the new variant.
  const key = subKeyOf(prefs);
  useEffect(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "prefs", ...prefs }));
      loadState();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const control = useCallback(
    async (action: "start" | "pause" | "resume" | "restart", speed?: number) => {
      await post(`/api/matches/${matchId}/${action}`, action === "start" ? { speed } : undefined);
      if (action === "restart") setTimeout(loadState, 300);
    },
    [matchId, loadState],
  );
  const setSpeed = useCallback((speed: number) => post(`/api/matches/${matchId}/speed`, { speed }), [matchId]);

  const send = useCallback((msg: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    if (msg.type === "predict") dispatch({ type: "pick", pick: String(msg.pick) });
  }, []);

  return { state, control, setSpeed, reload: loadState, send };
}
