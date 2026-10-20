# TOUCHLINE — Design Direction

**Look:** editorial sports broadcast, not "AI startup". Think of a printed match programme combined with a broadcast graphics package.
**Banned:** purple, neon gradients, glassmorphism blobs, dark-mode-by-default, sparkle ✨ icons, "Powered by AI" badges everywhere.

---

## 1. World-class references, by screen

Open these and screenshot what you like. Drop the screenshots into `design/refs/` and Claude can build directly from them.

### Landing page
| Reference | What to steal |
|---|---|
| **stripe.com** | Product shown *working* in the hero, clear section rhythm, precise copy |
| **linear.app** | Ruthless typography hierarchy, feature sections that each show one UI crop |
| **theathletic.com** | Editorial serif headlines plus sports photography energy |
| **theanalyst.com** (Opta Analyst) | Football data storytelling: charts that live inside the writing |
| **apple.com/apple-sports** | How to sell "fast, glanceable sports data" with restraint |
| **Galleries:** siteinspire.com, minimal.gallery, godly.website | Search for "sports", "data" or "editorial" |

### Match Center (live)
| Reference | What to steal |
|---|---|
| **FotMob** (app and web) | Momentum graph, shot map, clean tab structure |
| **Sofascore** | Attack momentum wave, player ratings, dense but readable stats |
| **Apple Sports** app | Minimal live score card, clean use of team colours |
| **Opta Analyst match pages** | Pass networks, xG race chart |
| **Mobbin** search terms: "live score", "sports", "match" | Real shipped mobile patterns |

### Broadcast Overlay
| Reference | What to steal |
|---|---|
| **Bundesliga Match Facts** (a live broadcast stats product) | The proof that live AI stats overlays work: xGoals and shot speed pop-ups |
| **NFL Next Gen Stats** graphics | Player speed tags that appear only when a threshold is crossed |
| **Sky Sports / TNT Sports** score bugs and lower thirds | Compact, high-contrast, 300 ms motion |
| **Amazon Prime Video "X-Ray"** for sports | An optional stats layer the fan can toggle |

### Control Room (agents)
| Reference | What to steal |
|---|---|
| **Vercel** deployment logs | Streaming log rows, status dots |
| **Datadog / Honeycomb** trace views | Waterfall spans showing agent → tool → model |
| **Linear** issue activity feed | Calm, readable event timeline |

### Auto Recap
| Reference | What to steal |
|---|---|
| **The Athletic** match reports | Headline, standfirst, key moments list |
| **NYT** interactive articles | Charts embedded inline in the text |

---

## 2. Design tokens (light-first)

```css
:root {
  --paper:   #F5F3EE;  /* warm off-white page */
  --surface: #FFFFFF;
  --ink:     #0F1412;  /* near-black text */
  --muted:   #5E6661;
  --line:    #E2DED5;
  --pitch:   #0E6B47;  /* primary: deep grass green */
  --pitch-2: #E6F1EB;  /* green tint backgrounds */
  --signal:  #F2A900;  /* key moment / live highlight (amber) */
  --danger:  #D6342C;  /* red card, Guardian reject */
  --home:    #1F4FD1;  /* team colours, fictional clubs */
  --away:    #E4572E;
}
```
- A dark theme is allowed **only** for the Broadcast Overlay page, which needs a transparent background with dark plates.
- One accent per screen. Use green for structure and amber **only** for "this moment matters".

## 3. Typography
- **Display / scoreline:** `Barlow Condensed` 600–700. It gives a broadcast-graphics feel.
- **UI / body:** `Inter` 400–600.
- **Numbers / stats:** `JetBrains Mono` or Inter with `font-variant-numeric: tabular-nums`, so numbers don't jump around when they change.
- **Editorial (recap headlines):** `Source Serif 4` 600.

## 4. Motion
- Overlay enter takes 250 ms, eased out with a slide from the edge. It holds for 5–7 s, then exits in 200 ms.
- Momentum wave animates continuously. Moment cards drop in from the top of the feed.
- Respect `prefers-reduced-motion`.

## 5. Components to build once
`ScoreBug`, `PitchCanvas` (2D, SVG), `MomentumWave`, `MomentCard` (with "Why it matters" expander and citation chips), `StatRow`, `PlayerTag`, `SpeedBadge`, `ModeSwitcher`, `LanguagePicker`, `AgentNode`, `TraceRow`, `GuardianVerdict`.

## 6. Rules
- Show real (synthetic) data everywhere. No lorem ipsum, no fake charts.
- Every AI sentence has a small citation chip, for example `⌁ 3 facts`, that reveals the underlying events.
- Mobile works for the Match Center and Recap. Overlay and Control Room are desktop-only.
