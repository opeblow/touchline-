"use client";

/**
 * Match audio: synthesised stadium crowd (Web Audio), referee whistle, and spoken
 * commentary (browser speech synthesis, in the viewer's language).
 * Nothing is pre-recorded, so there are no third-party audio rights involved.
 */

const VOICE_LANG: Record<string, string> = {
  en: "en-GB", es: "es-ES", fr: "fr-FR", pt: "pt-BR", ar: "ar-SA", ja: "ja-JP", de: "de-DE", ko: "ko-KR", hi: "hi-IN", sw: "sw-KE",
};

type Line = { text: string; priority: number; lang: string; at: number; emotion: Emotion };
export type Emotion = "calm" | "build" | "excited" | "somber";
export type CrowdKind = "roar" | "cheer" | "groan" | "ooh" | "boo" | "applause" | "chant" | "whistles";

// Vowel formants (F1, F2) for crowd voices.
const VOWELS: Record<string, [number, number]> = { ah: [800, 1250], oh: [500, 900], oo: [330, 780], eh: [600, 1800] };

export const GOAL_CALL: Record<string, string> = {
  en: "Goal! Goal!", es: "¡Gol! ¡Gooool!", fr: "But ! But !", pt: "Gol! Gooool!", ar: "هدف! هدف!", ja: "ゴール！ゴール！",
  de: "Tor! Tor!", ko: "골! 골!", hi: "गोल! गोल!", sw: "Goli! Goli!",
};
export const COMEBACK_CALL: Record<string, string> = {
  en: "What a comeback! Unbelievable!", es: "¡Qué remontada! ¡Increíble!", fr: "Quelle remontada ! Incroyable !",
  pt: "Que virada! Inacreditável!", ar: "يا لها من عودة! لا يصدق!", ja: "なんという逆転劇！信じられない！",
};
export const EQUALISER_CALL: Record<string, string> = {
  en: "They're level! Game on!", es: "¡Empate! ¡Hay partido!", fr: "Égalisation ! Tout est relancé !",
  pt: "Empate! O jogo está aberto!", ar: "التعادل! المباراة اشتعلت!", ja: "同点！試合は振り出しに！",
};

export class MatchAudio {
  private ctx: AudioContext | null = null;
  private crowdGain: GainNode | null = null;
  private crowdFilter: BiquadFilterNode | null = null;
  private master: GainNode | null = null;
  private base = 0.16;
  private excitement = 0;
  private raf = 0;
  private queue: Line[] = [];
  private speaking = false;
  private lastSpoke = 0;
  voiceOn = true;
  crowdOn = true;

  start() {
    if (this.ctx) {
      this.ctx.resume();
      return;
    }
    const Ctx = window.AudioContext || (window as any).webkitAudioContext;
    const ctx: AudioContext = new Ctx();
    this.ctx = ctx;
    this.master = ctx.createGain();
    this.master.gain.value = 0.9;
    this.master.connect(ctx.destination);

    // Crowd bed: brown noise → band-pass (voices) → slow amplitude wobble.
    const len = ctx.sampleRate * 4;
    const buf = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      let last = 0;
      for (let i = 0; i < len; i++) {
        const white = Math.random() * 2 - 1;
        last = (last + 0.02 * white) / 1.02;
        d[i] = last * 3.5;
      }
    }
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = 700;
    bp.Q.value = 0.6;
    const hum = ctx.createBiquadFilter();
    hum.type = "lowshelf";
    hum.frequency.value = 200;
    hum.gain.value = 6;
    this.crowdFilter = bp;
    this.crowdGain = ctx.createGain();
    this.crowdGain.gain.value = this.base;
    src.connect(bp).connect(hum).connect(this.crowdGain).connect(this.master);
    src.start();

    const tick = () => {
      this.raf = requestAnimationFrame(tick);
      if (!this.crowdGain || !this.crowdFilter || !this.ctx) return;
      this.excitement *= 0.985;
      const wobble = 0.03 * Math.sin(this.ctx.currentTime * 0.7) + 0.02 * Math.sin(this.ctx.currentTime * 2.3);
      const target = this.crowdOn ? this.base + wobble + this.excitement * 0.75 : 0;
      this.crowdGain.gain.setTargetAtTime(Math.max(0, target), this.ctx.currentTime, 0.12);
      this.crowdFilter.frequency.setTargetAtTime(650 + this.excitement * 900, this.ctx.currentTime, 0.2);
    };
    tick();
  }

  stop() {
    cancelAnimationFrame(this.raf);
    window.speechSynthesis?.cancel();
    this.ctx?.close();
    this.ctx = null;
  }

  /** 0..1 — swell for attacks, 1 for a goal. */
  react(level: number) {
    this.excitement = Math.min(1.2, Math.max(this.excitement, level));
  }

  private reverb: ConvolverNode | null = null;
  private crowdBus(): AudioNode | null {
    const ctx = this.ctx;
    if (!ctx || !this.master) return null;
    if (!this.reverb) {
      // Stadium-sized reverb: 2.8 s decaying noise impulse.
      const len = Math.floor(ctx.sampleRate * 2.8);
      const ir = ctx.createBuffer(2, len, ctx.sampleRate);
      for (let ch = 0; ch < 2; ch++) {
        const d = ir.getChannelData(ch);
        for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 2.6);
      }
      this.reverb = ctx.createConvolver();
      this.reverb.buffer = ir;
      const wet = ctx.createGain();
      wet.gain.value = 0.55;
      this.reverb.connect(wet).connect(this.master);
    }
    return this.reverb;
  }

  /**
   * Synthesised crowd voices: many detuned "singers" through vowel formants, plus breath noise.
   * kind shapes the pitch contour and vowel; intensity 0..1.2 scales loudness and crowd size.
   */
  crowd(kind: CrowdKind, intensity = 1) {
    const ctx = this.ctx;
    const bus = this.crowdBus();
    if (!ctx || !bus || !this.master || !this.crowdOn) return;
    if (kind === "applause") return this.applause(intensity);
    if (kind === "chant") return this.chant(intensity);
    if (kind === "whistles") return this.crowdWhistles(intensity);
    const t0 = ctx.currentTime + 0.02;
    const spec = {
      roar: { vowel: "ah", f: [140, 330], dur: 5.5, rise: 1.25, fall: 1.0, n: 46, gain: 0.05 },
      cheer: { vowel: "ah", f: [140, 300], dur: 3.2, rise: 1.15, fall: 1.0, n: 30, gain: 0.045 },
      groan: { vowel: "oh", f: [110, 220], dur: 2.8, rise: 1.05, fall: 0.62, n: 34, gain: 0.05 },
      ooh: { vowel: "oo", f: [150, 300], dur: 2.0, rise: 1.3, fall: 0.7, n: 34, gain: 0.05 },
      boo: { vowel: "oo", f: [85, 150], dur: 3.0, rise: 1.0, fall: 0.92, n: 36, gain: 0.06 },
    }[kind];
    const [F1, F2] = VOWELS[spec.vowel];
    const out = ctx.createGain();
    out.gain.value = Math.min(1.3, intensity);
    const f1 = ctx.createBiquadFilter(); f1.type = "bandpass"; f1.frequency.value = F1; f1.Q.value = 4;
    const f2 = ctx.createBiquadFilter(); f2.type = "bandpass"; f2.frequency.value = F2; f2.Q.value = 5;
    const g2 = ctx.createGain(); g2.gain.value = 0.55;
    const dry = ctx.createGain(); dry.gain.value = 0.9;
    f1.connect(out); f2.connect(g2).connect(out);
    out.connect(dry).connect(this.master);
    out.connect(bus);
    const n = Math.round(spec.n * (0.5 + intensity * 0.5));
    for (let i = 0; i < n; i++) {
      const start = t0 + Math.random() * (kind === "roar" ? 0.35 : 0.25);
      const end = start + spec.dur * (0.75 + Math.random() * 0.4);
      const f0 = spec.f[0] + Math.random() * (spec.f[1] - spec.f[0]);
      const osc = ctx.createOscillator();
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(f0 * 0.92, start);
      osc.frequency.linearRampToValueAtTime(f0 * spec.rise, start + spec.dur * 0.3);
      osc.frequency.linearRampToValueAtTime(f0 * spec.fall, end);
      const vib = ctx.createOscillator();
      vib.frequency.value = 4 + Math.random() * 3;
      const vibG = ctx.createGain();
      vibG.gain.value = f0 * 0.025;
      vib.connect(vibG).connect(osc.frequency);
      const env = ctx.createGain();
      const peak = spec.gain * (0.6 + Math.random() * 0.6);
      env.gain.setValueAtTime(0, start);
      env.gain.linearRampToValueAtTime(peak, start + 0.18 + Math.random() * 0.2);
      env.gain.setValueAtTime(peak * (kind === "ooh" ? 1.1 : 0.9), start + spec.dur * 0.45);
      env.gain.linearRampToValueAtTime(0, end);
      osc.connect(env);
      env.connect(f1);
      env.connect(f2);
      osc.start(start); vib.start(start);
      osc.stop(end + 0.05); vib.stop(end + 0.05);
    }
    // Breath / shouting noise layer.
    const nb = ctx.createBuffer(1, Math.floor(ctx.sampleRate * spec.dur), ctx.sampleRate);
    const d = nb.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const ns = ctx.createBufferSource();
    ns.buffer = nb;
    const ng = ctx.createGain();
    ng.gain.setValueAtTime(0, t0);
    ng.gain.linearRampToValueAtTime(0.18 * intensity * (kind === "roar" ? 1.6 : 1), t0 + 0.3);
    ng.gain.linearRampToValueAtTime(0, t0 + spec.dur);
    ns.connect(ng);
    ng.connect(f1);
    ng.connect(f2);
    ns.start(t0);
    this.react(kind === "roar" ? 1.2 : kind === "cheer" ? 0.7 : 0.35);
  }

  private clap(at: number, gain: number) {
    const ctx = this.ctx!;
    const len = Math.floor(ctx.sampleRate * 0.03);
    const b = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = b.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3);
    const s = ctx.createBufferSource();
    s.buffer = b;
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = 1100 + Math.random() * 1400;
    bp.Q.value = 1.2;
    const g = ctx.createGain();
    g.gain.value = gain;
    s.connect(bp).connect(g);
    g.connect(this.master!);
    g.connect(this.crowdBus()!);
    s.start(at);
  }

  private applause(intensity: number) {
    const ctx = this.ctx!;
    const t0 = ctx.currentTime;
    const n = Math.round(260 * intensity);
    for (let i = 0; i < n; i++) {
      const at = t0 + Math.pow(Math.random(), 1.6) * 3.5;
      this.clap(at, 0.05 + Math.random() * 0.07);
    }
  }

  /** Rhythmic clap-clap … clap-clap-clap with a chanting "oh" over it. */
  private chant(intensity: number) {
    const ctx = this.ctx!;
    const t0 = ctx.currentTime + 0.1;
    const beat = 0.42;
    const pattern = [0, 1, 3, 4, 5]; // clap clap _ clap clap clap
    for (let bar = 0; bar < 4; bar++) {
      for (const p of pattern) {
        const at = t0 + bar * beat * 8 + p * beat;
        for (let k = 0; k < 60 * intensity; k++) this.clap(at + Math.random() * 0.05, 0.03 + Math.random() * 0.04);
      }
    }
    // Sung "oh-oh" phrase per bar.
    const [F1, F2] = VOWELS.oh;
    const f1 = ctx.createBiquadFilter(); f1.type = "bandpass"; f1.frequency.value = F1; f1.Q.value = 4;
    const f2 = ctx.createBiquadFilter(); f2.type = "bandpass"; f2.frequency.value = F2; f2.Q.value = 5;
    const out = ctx.createGain(); out.gain.value = 0.9 * intensity;
    f1.connect(out); f2.connect(out); out.connect(this.master!); out.connect(this.crowdBus()!);
    const notes = [196, 220, 247, 220]; // a simple terrace tune
    for (let bar = 0; bar < 4; bar++) {
      notes.forEach((hz, i) => {
        const st = t0 + bar * beat * 8 + i * beat * 2;
        for (let v = 0; v < 18; v++) {
          const o = ctx.createOscillator();
          o.type = "sawtooth";
          o.frequency.value = hz * (0.98 + Math.random() * 0.04) * (v % 3 === 0 ? 0.5 : 1);
          const e = ctx.createGain();
          e.gain.setValueAtTime(0, st);
          e.gain.linearRampToValueAtTime(0.035, st + 0.08);
          e.gain.linearRampToValueAtTime(0, st + beat * 1.8);
          o.connect(e); e.connect(f1); e.connect(f2);
          o.start(st); o.stop(st + beat * 2);
        }
      });
    }
  }

  /** Fans whistling (frustration, time-wasting, a bad decision). */
  private crowdWhistles(intensity: number) {
    const ctx = this.ctx!;
    const t0 = ctx.currentTime;
    for (let i = 0; i < 40 * intensity; i++) {
      const st = t0 + Math.random() * 1.8;
      const dur = 0.4 + Math.random() * 1.2;
      const o = ctx.createOscillator();
      o.type = "sine";
      const f = 1800 + Math.random() * 1400;
      o.frequency.setValueAtTime(f, st);
      o.frequency.linearRampToValueAtTime(f * (0.85 + Math.random() * 0.3), st + dur);
      const g = ctx.createGain();
      g.gain.setValueAtTime(0, st);
      g.gain.linearRampToValueAtTime(0.012, st + 0.05);
      g.gain.linearRampToValueAtTime(0, st + dur);
      o.connect(g); g.connect(this.master!); g.connect(this.crowdBus()!);
      o.start(st); o.stop(st + dur + 0.05);
    }
  }

  whistle(blasts = 1, long = false) {
    const ctx = this.ctx;
    if (!ctx || !this.master) return;
    for (let b = 0; b < blasts; b++) {
      const t0 = ctx.currentTime + b * (long ? 0.9 : 0.35);
      const dur = long ? 0.75 : 0.22;
      const osc = ctx.createOscillator();
      osc.type = "square";
      osc.frequency.setValueAtTime(2900, t0);
      const lfo = ctx.createOscillator();
      lfo.frequency.value = 38; // the pea in the whistle
      const lfoGain = ctx.createGain();
      lfoGain.gain.value = 180;
      lfo.connect(lfoGain).connect(osc.frequency);
      const g = ctx.createGain();
      g.gain.setValueAtTime(0, t0);
      g.gain.linearRampToValueAtTime(0.09, t0 + 0.02);
      g.gain.setValueAtTime(0.09, t0 + dur - 0.05);
      g.gain.linearRampToValueAtTime(0, t0 + dur);
      const hp = ctx.createBiquadFilter();
      hp.type = "highpass";
      hp.frequency.value = 1800;
      osc.connect(hp).connect(g).connect(this.master);
      osc.start(t0);
      lfo.start(t0);
      osc.stop(t0 + dur + 0.05);
      lfo.stop(t0 + dur + 0.05);
    }
  }

  /** Queue a commentary line. Priority 2 = key moment (interrupts), 1 = play-by-play. */
  say(text: string, lang: string, priority = 1, emotion: Emotion = priority >= 2 ? "build" : "calm") {
    if (!this.voiceOn || typeof window === "undefined" || !window.speechSynthesis) return;
    const now = performance.now();
    if (priority >= 2) {
      this.queue = this.queue.filter((l) => l.priority >= 2);
      if (this.speaking && this.queue.length === 0) window.speechSynthesis.cancel();
    } else if (this.queue.length > 1 || now - this.lastSpoke < 2200) {
      return; // keep play-by-play sparse and current
    }
    this.queue.push({ text, priority, lang, at: now, emotion });
    this.pump();
  }

  private pickVoice(lang: string): SpeechSynthesisVoice | undefined {
    const want = VOICE_LANG[lang] ?? lang;
    const voices = window.speechSynthesis.getVoices();
    const pref = voices.filter((v) => v.lang.toLowerCase().startsWith(want.slice(0, 2).toLowerCase()));
    return (
      pref.find((v) => v.lang === want && /natural|neural|online/i.test(v.name)) ??
      pref.find((v) => /natural|neural|online/i.test(v.name)) ??
      pref.find((v) => v.lang === want) ??
      pref[0]
    );
  }

  private pump(): void {
    if (this.speaking || !this.queue.length) return;
    const line = this.queue.shift()!;
    if (performance.now() - line.at > 6000 && line.priority < 2) {
      this.pump(); // stale line: skip it
      return;
    }
    const u = new SpeechSynthesisUtterance(line.text.replace(/^\d+'\s*/, ""));
    const v = this.pickVoice(line.lang);
    if (v) u.voice = v;
    u.lang = VOICE_LANG[line.lang] ?? line.lang;
    // Delivery follows the emotion of the moment.
    const style = { excited: [1.22, 1.3], build: [1.14, 1.12], somber: [0.92, 0.85], calm: [1.12, 1.0] }[line.emotion];
    u.rate = style[0];
    u.pitch = style[1];
    u.volume = 1;
    this.speaking = true;
    u.onend = u.onerror = () => {
      this.speaking = false;
      this.lastSpoke = performance.now();
      this.pump();
    };
    window.speechSynthesis.speak(u);
  }
}

// ---------------------------------------------------------------- play-by-play

const PBP: Record<string, Record<string, string[]>> = {
  en: {
    pass: ["{a} to {b}.", "{a}, finds {b}.", "Played out to {b}.", "{a} keeps it moving."],
    long: ["Long ball from {a}!", "{a} switches it, looking for {b}."],
    through: ["{a} threads it through for {b}!", "Lovely ball from {a}!"],
    cross: ["{a} whips it in!", "Cross from {a}!"],
    lost: ["{a}'s pass is cut out.", "Intercepted!"],
    carry: ["{a} drives forward.", "{a} on the ball."],
    dribble: ["{a} takes him on!", "Great skill from {a}!"],
    tackle: ["Strong tackle from {a}!", "{a} wins it back!"],
    shot: ["{a} shoots!", "{a}, a strike at goal!"],
    saved: ["Saved!", "Good stop from the keeper!"],
    wide: ["Wide!", "Just past the post!"],
    blocked: ["Blocked!"],
    foul: ["Foul by {a}.", "{a} brings him down. Free kick."],
    corner: ["Corner kick."],
    kickoff: ["And we're under way!", "Kick-off."],
    half: ["That's half time.", "The referee blows for half time."],
    full: ["It's all over!", "Full time here!"],
    sub: ["Substitution: {b} comes on for {a}."],
  },
  es: {
    pass: ["{a} para {b}.", "{a} busca a {b}."], long: ["¡Balón largo de {a}!"], through: ["¡Pase al hueco de {a}!"],
    cross: ["¡Centro de {a}!"], lost: ["¡Interceptado!"], carry: ["{a} avanza."], dribble: ["¡Regate de {a}!"],
    tackle: ["¡Gran entrada de {a}!"], shot: ["¡Dispara {a}!"], saved: ["¡Parada!"], wide: ["¡Fuera!"], blocked: ["¡Bloqueado!"],
    foul: ["Falta de {a}."], corner: ["Córner."], kickoff: ["¡Arranca el partido!"], half: ["Descanso."], full: ["¡Final del partido!"],
    sub: ["Cambio: entra {b} por {a}."],
  },
  fr: {
    pass: ["{a} pour {b}.", "{a} trouve {b}."], long: ["Long ballon de {a} !"], through: ["Passe en profondeur de {a} !"],
    cross: ["Centre de {a} !"], lost: ["Interception !"], carry: ["{a} avance."], dribble: ["Dribble de {a} !"],
    tackle: ["Beau tacle de {a} !"], shot: ["Frappe de {a} !"], saved: ["Arrêt !"], wide: ["À côté !"], blocked: ["Contré !"],
    foul: ["Faute de {a}."], corner: ["Corner."], kickoff: ["C'est parti !"], half: ["C'est la mi-temps."], full: ["C'est terminé !"],
    sub: ["Changement : {b} remplace {a}."],
  },
  pt: {
    pass: ["{a} para {b}.", "{a} encontra {b}."], long: ["Bola longa de {a}!"], through: ["Enfiada de {a}!"],
    cross: ["Cruzamento de {a}!"], lost: ["Interceptado!"], carry: ["{a} avança."], dribble: ["Drible de {a}!"],
    tackle: ["Grande desarme de {a}!"], shot: ["Chuta {a}!"], saved: ["Defesa!"], wide: ["Para fora!"], blocked: ["Bloqueado!"],
    foul: ["Falta de {a}."], corner: ["Escanteio."], kickoff: ["Começa o jogo!"], half: ["Intervalo."], full: ["Fim de jogo!"],
    sub: ["Substituição: entra {b}, sai {a}."],
  },
};

export function playByPlay(ev: any, name: (id: string | null) => string, lang: string): { text: string; level: number; whistle?: number } | null {
  const T = PBP[lang] ?? PBP.en;
  const pick = (k: string) => {
    const arr = T[k] ?? PBP.en[k];
    return arr ? arr[Math.floor(Math.random() * arr.length)] : null;
  };
  const fill = (s: string | null, a?: string | null, b?: string | null) =>
    s ? s.replace("{a}", a ?? "").replace("{b}", b ?? "") : null;
  const a = name(ev.player_id);
  const b = name(ev.recipient_id ?? ev.extra?.player_in ?? null);
  switch (ev.type) {
    case "pass": {
      if (ev.outcome !== "complete") return Math.random() < 0.5 ? { text: fill(pick("lost"), a)!, level: 0.1 } : null;
      const k = ev.pass_type === "through" ? "through" : ev.pass_type === "cross" ? "cross" : ev.pass_type === "long" || ev.pass_type === "switch" ? "long" : "pass";
      if (k === "pass" && Math.random() < 0.55) return null;
      return { text: fill(pick(k), a, b)!, level: k === "pass" ? 0.04 : 0.18 };
    }
    case "carry": return Math.random() < 0.25 ? { text: fill(pick("carry"), a)!, level: 0.05 } : null;
    case "dribble": return ev.outcome === "won" ? { text: fill(pick("dribble"), a)!, level: 0.2 } : null;
    case "tackle": return { text: fill(pick("tackle"), a)!, level: 0.15 };
    case "shot": {
      if (ev.outcome === "goal") return null; // key-moment commentary handles goals
      const follow = ev.outcome === "saved" ? "saved" : ev.outcome === "blocked" ? "blocked" : "wide";
      return { text: `${fill(pick("shot"), a)} ${fill(pick(follow), a)}`, level: 0.55 };
    }
    case "foul": return { text: fill(pick("foul"), a)!, level: 0.12, whistle: 1 };
    case "corner": return { text: pick("corner")!, level: 0.25 };
    case "kickoff": return ev.seq <= 1 || ev.minute === 46 ? { text: pick("kickoff")!, level: 0.3, whistle: 1 } : { text: "", level: 0.1, whistle: 1 };
    case "half_end": return { text: pick("half")!, level: 0.2, whistle: 2 };
    case "match_end": return { text: pick("full")!, level: 0.6, whistle: 3 };
    case "substitution": return { text: fill(pick("sub"), a, b)!, level: 0.05 };
    default: return null;
  }
}
