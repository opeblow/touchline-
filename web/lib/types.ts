// Mirrors backend/touchline/models.py (source of truth).

export type Side = "home" | "away";
export type Mode = "analyst" | "fan" | "club" | "player";

export interface Player {
  id: string;
  name: string;
  short_name: string;
  number: number;
  position: string;
  nationality: string;
}

export interface Team {
  id: string;
  name: string;
  short_name: string;
  code: string;
  city: string;
  primary: string;
  secondary: string;
  style: Record<string, number | string>;
  players: Player[];
}

export interface MatchMeta {
  match_id: string;
  competition: string;
  season: string;
  matchday: number;
  venue: string;
  seed: number;
  home: Team;
  away: Team;
  scenario: { label?: string } & Record<string, unknown>;
}

export interface Fact {
  fact_id: string;
  kind: string;
  label: string;
  value: number | string;
  unit: string;
  team: Side | null;
  player_id: string | null;
  minute: number | null;
  event_ids: string[];
}

export interface Moment {
  moment_id: string;
  match_id: string;
  type: string;
  minute: number;
  t: number;
  team: Side | null;
  player_id: string | null;
  importance: number;
  title: string;
  facts: Fact[];
  event_ids: string[];
}

export interface Insight {
  insight_id: string;
  moment_id: string;
  text: string;
  cited_fact_ids: string[];
  agent: string;
  attempts: number;
  model: string;
  fallback: boolean;
}

export interface Personalized {
  insight_id: string;
  moment_id: string;
  mode: Mode;
  lang: string;
  headline: string;
  text: string;
  cited_fact_ids: string[];
  sub_key: string;
}

export interface Commentary {
  line_id: string;
  t: number;
  minute: number;
  text: string;
  tone: "calm" | "build" | "excited" | "somber";
  lang: string;
}

export interface Cue {
  cue_id: string;
  template: string;
  t_in: number;
  t_out: number;
  priority: number;
  data: Record<string, any>;
  moment_id: string | null;
}

export interface Trace {
  trace_id: string;
  agent: string;
  action: string;
  status: "ok" | "retry" | "rejected" | "fallback" | "error" | "skipped";
  started_at: number;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  model: string;
  detail: string;
  handoff_to: string | null;
  input_ref: string | null;
  output_ref: string | null;
}

export interface Recap {
  recap_id: string;
  phase: "half_time" | "full_time";
  lang: string;
  headline: string;
  standfirst: string;
  body_md: string;
  key_moments: string[];
  player_of_match: string | null;
  potm_reason: string | null;
  cited_fact_ids: string[];
  model: string;
}

export interface Tactical {
  shift_id: string;
  window: [number, number];
  team: Side;
  kind: string;
  summary: string;
  facts: Fact[];
}

export interface TeamStats {
  goals: number;
  possession: number;
  passes: number;
  pass_accuracy: number;
  shots: number;
  shots_on_target: number;
  xg: number;
  big_chances: number;
  corners: number;
  fouls: number;
  yellow: number;
  red: number;
  tackles: number;
  interceptions: number;
  pressures: number;
  ppda: number;
  field_tilt: number;
  distance_km: number;
  sprints: number;
}

export interface PlayerStats {
  id: string;
  side: Side;
  on: boolean;
  passes: number;
  pass_accuracy: number;
  avg_difficulty: number;
  hardest_pass: number;
  progressive: number;
  key_passes: number;
  assists: number;
  shots: number;
  goals: number;
  xg: number;
  tackles: number;
  interceptions: number;
  pressures: number;
  distance_km: number;
  top_speed: number;
  sprints: number;
  touches: number;
  rating: number;
}

export interface Snapshot {
  t: number;
  minute: number;
  period: number;
  score: [number, number];
  home: TeamStats;
  away: TeamStats;
  momentum: number;
  momentum_series: [number, number][];
  chaos: number;
  control: Side | null;
  chaos_series: [number, number][];
  players: Record<string, PlayerStats>;
}

export interface Status {
  status: "ready" | "live" | "paused" | "finished" | "stopped";
  speed: number;
  t: number;
  minute: number;
  viewers: number;
  bus: string;
  hub: string;
  llm: string;
  model_fast: string;
  model_reasoning: string;
  totals: { calls: number; tokens_in: number; tokens_out: number; cost_usd: number; rejections: number; retries: number; fallbacks: number };
  pending_moments: number;
  llm_mode?: string;
  budget_usd?: number;
  over_budget?: boolean;
  insight_latency_ms?: { n: number; p50: number; p95: number };
}

export interface Frame {
  i?: number;
  t?: number;
  b: [number, number];
  p: ([number, number] | null)[];
  ids?: (string | null)[];
}

export interface MatchEvent {
  event_id: string;
  type: string;
  team: Side;
  player_id: string | null;
  recipient_id: string | null;
  minute: number;
  second: number;
  t: number;
  x: number;
  y: number;
  end_x: number | null;
  end_y: number | null;
  outcome: string | null;
  metrics: Record<string, number>;
}

export interface AgentStatus {
  calls: number;
  errors: number;
  latency_ms_total: number;
  tokens: number;
  cost_usd: number;
  circuit: "open" | "closed";
  killed: boolean;
}

export interface WireMessage<T = any> {
  kind: string;
  match_id: string;
  t: number;
  data: T;
}
