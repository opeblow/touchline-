# TOUCHLINE — Explainable Match Intelligence

> One match. Every fan. Every language. Every claim backed by data.

Hackathon: **Microsoft + Premier League "Inside the Game"**
Submission deadline: **Oct 27, 2026, 11:59 PM PT**. Our target is **Oct 26** so we have a day of buffer.

---

## 1. The pitch (about 30 seconds)

Broadcasters show *what* happened. Touchline explains *why it matters*, live.

Touchline is a multi-agent system on Microsoft Foundry and Azure. It works in five steps:
1. It **ingests** a live stream of synthetic match events.
2. It **interprets** them with a deterministic stats engine covering xG, pass difficulty, pressure, momentum and a "Control vs Chaos" index.
3. Specialist AI agents **explain** the key moments. Every sentence cites the event IDs behind it, and a Guardian agent fact-checks every number before it goes on air.
4. The output is **rendered** as timed, machine-readable overlay JSON for broadcast graphics.
5. It is **personalized** into very different experiences: Analyst mode, Casual Fan mode, Club mode and Player Cam mode, in any language.

**Our edge:** most teams will ship a chatbot over stats. We ship a **trustworthy live production pipeline**, with these guarantees:
- No number on screen is made up by an LLM.
- Every insight is explainable and traceable.
- The same intelligence becomes four products.

---

## 2. Mapping to the judging criteria (each is 20%)

| Criterion | How we score |
|---|---|
| Technological Implementation | Our own synthetic match simulator (data innovation). Microsoft Foundry and Agent Framework. Azure MCP plus our own MCP server. Event Hubs, Container Apps, Cosmos DB, Fabric, `azd` one-command deploy, CI and tests. |
| Agentic Design & Innovation | 7 specialist agents share state through a match blackboard, hand off over A2A, and recover from failures (Guardian rejects → Explainer retries). A visible **Control Room** shows it all live. |
| Real-World Impact | Ready-to-use overlay JSON for broadcast partners. Multilingual output. Enterprise trust layer covering grounding, audit trail, content safety and cost/latency telemetry. |
| UX & Presentation | Polished editorial UI (see `DESIGN.md`) with a broadcast overlay mode. A tight 2-minute video. |
| Category Adherence | Primary category: **Best Multi-Agent System**. Also strong for Foundry, Enterprise and Cloud Native. |

---

## 3. Product surfaces (what the judges see)

1. **Landing page**: the story, a live demo embed, architecture and a "Watch it work" CTA.
2. **Match Center (live)**: 2D pitch with moving players and ball, event ticker, momentum wave, key-moment cards with a "Why it matters" button, and live stats.
3. **Personalize panel**: the mode switcher (Analyst / Fan / Club / Player Cam), language, favorite club and player, and a "metric I care about" setting. The same moment visibly changes for each mode.
4. **Broadcast Overlay mode**: a 1920×1080 transparent page that can be used directly in OBS, showing lower thirds, player tags, speed and distance badges and a shot-speed pop-up. It is driven only by the overlay JSON.
5. **Auto Recap**: halftime and full-time article, a highlight timeline, a player-of-the-match card with the reasoning behind it, and a one-click language switch.
6. **Control Room**: live agent graph, handoffs, Guardian rejections and retries, plus latency, tokens and cost for each agent. **This is what wins the multi-agent category.**
7. **Data Studio**: simulator controls such as seed, team styles (press/possession/counter), tempo and "inject chaos". It can export datasets as JSONL or Parquet to Fabric.

---

## 4. Architecture

```
 ┌──────────────┐   events    ┌──────────────┐   ┌────────────────────────┐
 │  Simulator   │───────────▶ │ Event Hubs   │──▶│ Stats Engine (Python)  │ deterministic
 │ (Data agent) │  JSON/1Hz+  └──────────────┘   │ xG, pass difficulty,   │ numbers only
 └──────────────┘                     │          │ speed, pressure, PPDA, │
                                      │          │ momentum, control idx  │
                                      ▼          └───────────┬────────────┘
                              Fabric Eventstream             │ match state
                              (analytics / KQL)              ▼
                                                 ┌────────────────────────┐
                                                 │ Match Blackboard        │ Cosmos DB
                                                 │ (shared agent state)    │ (+ cache)
                                                 └───────────┬────────────┘
                     Microsoft Agent Framework orchestrator │  MCP: match-tools server
   ┌──────────┬───────────┬────────────┬───────────┬────────┴──┬────────────┐
   ▼          ▼           ▼            ▼           ▼           ▼            ▼
 Moment    Tactician   Explainer   Narrator   Persona+     Guardian     Producer
 Spotter   (patterns)  (why it     (live      Localizer    (fact-check, (recaps,
 (scores               matters,    lines)     (modes,      safety,      highlight
 moments)              cites IDs)             languages)   retry)       reels)
                                                 │
                                                 ▼
                                  Overlay JSON + Fan feed (Azure Web PubSub)
                                                 │
                         ┌───────────────────────┼──────────────────┐
                         ▼                       ▼                  ▼
                    Match Center          Broadcast Overlay     Auto Recap
                    (Next.js)             (1080p, OBS)          (multilingual)
```

### Core rule: LLMs never produce numbers
- The **Stats Engine** computes every metric deterministically.
- Agents receive a facts packet such as `{fact_id, value, event_ids}` and must cite `fact_id`s.
- The **Guardian** parses each output and checks every number and name against the blackboard. If a check fails, the output is rejected with a reason and the Explainer retries once. If it fails again, a template fallback is used.
- This is how we show trust, explainability and enterprise readiness all at once.

### Latency budget (live)
- Overlay graphics are generated **without an LLM** and appear in under 200 ms.
- Narrative text uses a fast model and appears in about 1.5–3 s. It is streamed, and the UI shows "analysing…" until it arrives.
- Recaps use a reasoning model and run asynchronously at halftime and full time.

---

## 5. The agents

| # | Agent | Model | Input → Output |
|---|---|---|---|
| 1 | **Moment Spotter** | rules plus a fast model | Event window → importance score from 0 to 100, and moment type (big chance, momentum swing, press trap, milestone) |
| 2 | **Tactician** | reasoning model | 5-minute windows → tactical shifts (pressing height, width, tempo, "control vs chaos") |
| 3 | **Explainer** | fast model | Moment plus facts → "why it matters" in 1 to 3 sentences, citing `fact_id`s |
| 4 | **Narrator** | fast model | Moments → live commentary lines in the right tone |
| 5 | **Persona + Localizer** | fast model plus Azure AI Translator | Canonical insight → a version per mode and per language (Analyst = dense numbers, Fan = emotion and context, Player Cam = one player) |
| 6 | **Guardian** | rules plus a small model plus Azure AI Content Safety | Any output → approve, or reject with a reason. Writes an audit log. |
| 7 | **Producer** | reasoning model | Full match state → halftime and full-time recaps, highlight timeline, player-of-the-match reasoning |
| 0 | **Simulator (Data agent)** | code plus an LLM for scenario scripting | "Make a comeback match with a red card at 60'" → a realistic event stream |
| 8 | **Auto-Eventer** | vision model (Foundry or Azure AI Vision) | Synthetic top-down video → detected passes and speeds → accuracy vs ground truth. This covers the rule's "auto-eventing over video". |
| 9 | **Memory** | Azure AI Search | Season facts and past moments → milestones and context ("3rd comeback this season") |

**Proof of value:** the README includes a Foundry Evaluations table comparing a single-agent baseline with Touchline on numeric accuracy, groundedness and latency.
**Live recovery demo:** a "chaos" button in the Control Room kills an agent, and the system recovers live.

How they collaborate:
- **Shared state:** the Blackboard in Cosmos DB, keyed by `match_id`.
- **Handoffs:** the Agent Framework workflow graph, with A2A endpoints exposed for each agent.
- **Tools:** our `touchline-mcp` server provides `get_match_state`, `get_events(window)`, `get_player(id)`, `get_facts(moment_id)` and `compare_players`.
- **Recovery:** Guardian rejections are retried, a timeout triggers a template fallback, and a circuit breaker covers each agent. All of it is visible in the Control Room.

---

## 6. Synthetic data (the "data innovation" points)

- **Fictional league and players only.** Examples: "Northbank FC" vs "Harbour City". No real club names, logos or player names, which avoids any trademark or IP issues with the rules.
- **Simulator:** a possession chain model on an 18-zone pitch. It uses player attributes (pace, passing, finishing, stamina), team style profiles, fatigue curves, a pressure model and an xG model.
- **Per event:** `event_id, ts, minute, type, team, player, x, y, end_x, end_y, outcome, pressure, speed_kmh, distance_m, body_part, under_pressure, sequence_id`
- **Tracking (simplified):** player x/y at 5 Hz, for speed and distance badges and the 2D pitch.
- **Exports:** JSONL stream, Parquet to Fabric OneLake, and a published dataset card in the repo.

---

## 7. Azure and Microsoft stack (for the hero-tech checklist)

**Full requirement → feature → evidence mapping is in [CRITERIA.md](CRITERIA.md).** Additions beyond the list below:
- Container Apps **Jobs**, which generate a 380-match synthetic season
- **Logic Apps**, which send recaps to Teams and email
- **Azure AI Search**, for match memory
- A **vision model**, for auto-eventing
- **Entra ID** (managed identity, Sign in with Microsoft)
- `.github/copilot-instructions.md` plus `gh`-driven dataset releases


- **Microsoft Foundry**: model deployments, agent service, evaluations (groundedness), tracing
- **Microsoft Agent Framework** (Python): workflows, handoffs, A2A
- **MCP**: our own `touchline-mcp`, plus Azure MCP Server for ops
- **Azure Event Hubs**: event ingest
- **Azure Container Apps**: API, agents, simulator and web
- **Azure Cosmos DB**: blackboard and audit log
- **Azure Web PubSub**: live push to browsers
- **Azure AI Translator**, **AI Content Safety**, and optionally **AI Speech** for a TTS commentary voice
- **Microsoft Fabric**: Eventstream to Eventhouse (KQL) for post-match analytics
- **Application Insights / OpenTelemetry**: per-agent latency, tokens and cost
- **GitHub**: Copilot Agent Mode, Actions CI/CD, `azd` templates, public repository

---

## 8. Seven-day schedule

| Day | Date | Must ship |
|---|---|---|
| 1 | Tue Oct 20 | Repo scaffold, event schema, **simulator**, **stats engine** with tests, replay of 1 full match locally |
| 2 | Wed Oct 21 | `azd` infrastructure (Event Hubs, Cosmos, Container Apps, Web PubSub), stream to web, Match Center skeleton with a live 2D pitch |
| 3 | Thu Oct 22 | Agent Framework workflow: Moment Spotter, Explainer, Narrator, Guardian, plus the MCP server |
| 4 | Fri Oct 23 | Persona + Localizer (4 modes, 5+ languages), Producer recaps, Tactician |
| 5 | Sat Oct 24 | Broadcast Overlay page, Control Room (with chaos button), **landing page**, Data Studio. Auto-Eventer v1 (render video → detect → score). |
| 6 | Sun Oct 25 | Visual polish pass. Fabric season and dashboard. AI Search memory. Logic App. Foundry Evaluations table. README. Deploy to production URL. Load test. |
| 7 | Mon Oct 26 | **Record and edit the demo video**, write the pitch, **submit** |
| Buffer | Tue Oct 27 | Fixes only. Submit before 11:59 PM PT. |

Cut list if behind schedule, in order: Data Studio UI → TTS voice → Logic App → AI Search memory → Fabric dashboard → Tactician. Reduce the Auto-Eventer to a 30-second clip rather than cutting it, because it is named in the rules. **Never cut** the Guardian, the Control Room or personalization.

---

## 9. Demo video (under 2:00)

| Time | Shot |
|---|---|
| 0:00–0:10 | Hook: "Football isn't the scoreline. It's *why*." A match plays on the 2D pitch. |
| 0:10–0:35 | A big chance happens. The overlay pops up: shot speed 112 km/h, xG 0.41. A "Why it matters" card appears. |
| 0:35–1:00 | **The same moment** shown in Analyst, Fan and Player Cam modes, then switched to Spanish and Japanese. |
| 1:00–1:25 | Control Room: agents hand off, the Guardian **catches a wrong number**, and the Explainer retries with the correct one. |
| 1:25–1:45 | Full-time Auto Recap and the broadcast overlay running in OBS. |
| 1:45–2:00 | Architecture slide with Azure and Foundry logos, then the repo and live URL. |

Use only royalty-free music, and no Premier League marks or match footage.

---

## 10. Submission checklist
- [ ] Public GitHub repository with README, architecture diagram and setup steps
- [ ] Live URL with no login, or test credentials given in the submission
- [ ] YouTube or Vimeo video under 2:00, set to public
- [ ] Pitch text: what it is, the Microsoft tech used, the problem it solves
- [ ] All content in English, all data synthetic, no third-party trademarks
