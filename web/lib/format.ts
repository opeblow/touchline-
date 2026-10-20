import type { MatchMeta, Player, Side } from "./types";

export function clockLabel(minute: number, period: number): string {
  if (period === 1 && minute > 45) return `45+${minute - 45}'`;
  if (period === 2 && minute > 90) return `90+${minute - 90}'`;
  return `${Math.max(minute, 0)}'`;
}

export function playersById(meta?: MatchMeta | null): Record<string, Player & { side: Side }> {
  const out: Record<string, Player & { side: Side }> = {};
  if (!meta) return out;
  for (const p of meta.home.players) out[p.id] = { ...p, side: "home" };
  for (const p of meta.away.players) out[p.id] = { ...p, side: "away" };
  return out;
}

export function teamOf(meta: MatchMeta | null | undefined, side: Side | null | undefined) {
  if (!meta || !side) return null;
  return side === "home" ? meta.home : meta.away;
}

export const LANGS: { code: string; label: string; native: string; rtl?: boolean }[] = [
  { code: "en", label: "English", native: "English" },
  { code: "es", label: "Spanish", native: "Español" },
  { code: "fr", label: "French", native: "Français" },
  { code: "pt", label: "Portuguese", native: "Português" },
  { code: "ar", label: "Arabic", native: "العربية", rtl: true },
  { code: "ja", label: "Japanese", native: "日本語" },
  { code: "de", label: "German", native: "Deutsch" },
  { code: "ko", label: "Korean", native: "한국어" },
  { code: "hi", label: "Hindi", native: "हिन्दी" },
  { code: "sw", label: "Swahili", native: "Kiswahili" },
];

export const isRtl = (lang: string) => LANGS.find((l) => l.code === lang)?.rtl ?? false;

export const MODES: { id: "analyst" | "fan" | "club" | "player"; label: string; hint: string }[] = [
  { id: "analyst", label: "Analyst", hint: "Every number, tactical detail" },
  { id: "fan", label: "Fan", hint: "The story, the emotion" },
  { id: "club", label: "My club", hint: "Good news or bad, for your side" },
  { id: "player", label: "Player cam", hint: "Follow one player all match" },
];

export const MOMENT_LABEL: Record<string, string> = {
  goal: "Goal",
  big_chance: "Big chance",
  shot_on_target: "Shot",
  save: "Save",
  red_card: "Red card",
  yellow_card: "Booking",
  momentum_swing: "Momentum",
  pressure_shift: "Pressing",
  chaos_spike: "Rhythm",
  sprint: "Speed",
  pass_of_match: "Pass",
  milestone: "Milestone",
  substitution: "Sub",
  phase: "Whistle",
};

export function fmt(n: number | undefined | null, digits = 0): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "–";
  return n.toFixed(digits);
}
