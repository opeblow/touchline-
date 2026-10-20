> Status: everything below is implemented. Evidence: [docs/e2e/report.md](docs/e2e/report.md) (80/80 end-to-end checks) and [README §1–2](README.md).

# TOUCHLINE — Criteria Coverage Matrix

Every line of the official rules is mapped to a feature, where it lives in the repo, and where judges **see** it in the demo video.
Rule: if a row has no demo timestamp, assume judges will miss it. Put the essentials in the video, everything else in the README.

---

## A. Challenge requirements (Rules §4.1)

### A1. The five-stage pipeline
| Stage | Touchline feature | Repo | Video |
|---|---|---|---|
| (a) **Ingest** live events | Simulator → Event Hubs → stats consumer (1–10 events/s, replayable by seed) | `backend/touchline/sim`, `backend/touchline/stats` | 0:10 |
| (b) **Interpret** into stats and patterns | Deterministic stats engine (xG, pass difficulty, PPDA, momentum, Control vs Chaos) plus Tactician agent | `backend/touchline/stats`, `agents/tactician.py` | 0:15 |
| (c) **Explain** why it matters | Explainer agent writes "why it matters" with cited `fact_id`s, checked by the Guardian | `agents/explainer.py`, `agents/guardian.py` | 0:25 |
| (d) **Render** on screen | Timed overlay cues (`overlay.schema.json`) → 1080p Broadcast Overlay page | `data/schema`, `web/app/overlay` | 1:25 |
| (e) **Personalize** analyst vs casual fan | Persona agent: Analyst / Fan / Club / Player Cam modes, favorite club and player, "one metric I care about", language | `agents/persona.py`, `ModeSwitcher` | 0:35 |

### A2. Real-time match intelligence features
| Requirement | Feature | Video |
|---|---|---|
| Player identification: live name tags | `PlayerTag` on the 2D pitch and in the overlay | 0:12 |
| Speed and distance indicators **when thresholds are reached** | Threshold rules (sprint > 30 km/h, distance milestones such as 10 km) trigger a `SpeedBadge` cue | 0:20 |
| Pass quality: distance, accuracy, **difficulty rating** | Pass difficulty model (distance, pressure, lane blockers, angle) rated 0–100, plus per-player accuracy | 0:30 (Analyst mode) |
| Ball speed and shot speed | From tracking at 5 Hz, shown as a pop-up on every shot | 0:20 |
| **Auto-eventing from video** | **Auto-Eventer agent**: simulator renders top-down synthetic video, a vision model detects players and ball, events and speeds are derived and scored against ground truth (precision/recall shown) | 1:05 |

### A3. Other required capabilities
| Requirement | Feature | Video |
|---|---|---|
| (iii) Narratives, player context, **milestones**, recaps | Narrator (live lines). Producer (halftime and full-time recaps). Milestones from a **simulated full season** in Fabric ("his 10th goal of the synthetic season") | 1:25 |
| (iv) Explainability: control vs chaos, pressure changes, rhythm | **Control vs Chaos index** (possession stability vs turnover rate and transitions), pressure-shift detector, tempo/rhythm wave | 0:30 |
| (v) Data innovation: create or extend synthetic datasets | Open-source simulator, dataset card, 380-match synthetic season published as Parquet, LLM "scenario director" ("comeback with a red card at 60'") | 1:45 |
| (vi) Multi-language | Localizer agent: 6+ languages, football-specific glossary to fix term translation, right-to-left support (Arabic) | 0:45 |

---

## B. Judging criteria (Rules §6.2, each 20%)

### B1. Technological Implementation
| Judge's question | Our evidence |
|---|---|
| Creative, optimized synthetic data creation? | Physics-light simulator with team style profiles, fatigue and pressure. Seeded and reproducible. 380-match season generated in parallel on Container Apps Jobs. Validation report comparing distributions with published football norms (shots per game, pass completion). |
| Quality software practices? | Typed contracts (JSON Schema → Pydantic → TypeScript), 100% tests on the stats engine, CI on every PR, `azd` infrastructure as code, ADRs in `docs/adr/`. |
| Leverage of hero tech? | See section D. Each technology has a *real job*, not a logo. |
| Well-structured, documented code? | Monorepo layout, README with architecture diagram, `AGENTS.md`, docstrings on public APIs. |

### B2. Agentic Design & Innovation
| Judge's question | Our evidence |
|---|---|
| Creative agentic patterns? | **Blackboard + specialists + critic.** A Guardian critic loop with automatic retry. A scenario-director agent that *creates* data. A vision agent that *verifies* data. |
| Orchestration, MCP, multi-agent? | Microsoft Agent Framework workflow graph. Our own `touchline-mcp` server. A2A endpoints per agent. Azure MCP Server used for ops (shown in the README). |
| Novel / better than existing? | "Zero hallucinated numbers" guarantee with fact citations. Same intelligence → 4 personas × N languages from one canonical insight (cheap and consistent). |

### B3. Real-World Impact
| Judge's question | Our evidence |
|---|---|
| Significant problem? | Broadcasters need live, accurate, localized graphics. Fans want different depths. Today that takes production teams per market. |
| Production-deployable? | Overlay cue JSON is renderer-agnostic. Keyless managed identity for every Azure service (Container Apps secret only for Translator). Human-in-the-loop approval via Agent Framework `request_info`. Audit log of every check and publication. Per-agent latency, tokens and cost in the Control Room. |
| Impact? | One pipeline serves broadcast, streaming apps and social. The README includes cost and latency numbers per match. |

### B4. User Experience & Presentation
| Judge's question | Our evidence |
|---|---|
| Well-designed, intuitive UI? | Editorial design system (`DESIGN.md`) and accessible contrast. Mobile Match Center. |
| Demo video communicates value? | Scripted 2:00 video (`PLAN.md` §9). Hook in the first 10 s. One "wow" per 20 s. |
| Frontend and backend balance? | 5 polished screens **and** a visible Control Room that shows the backend working. |

### B5. Adherence to Category
We submit under **Best Multi-Agent System**. It is also eligible for Grand Prize, since a project can win 1 grand prize and 1 category prize.

---

## C. Category prize checklist

| Category | Judges assess | How Touchline satisfies it |
|---|---|---|
| **Best Multi-Agent System** (primary) | Distinct roles | 9 agents with single responsibilities and typed outputs (`AGENTS.md`) |
| | Shared state and handoffs | Cosmos DB Match Blackboard, Agent Framework workflow edges, A2A |
| | **Recovers from failures** | Guardian reject → retry. Timeout → template fallback. Circuit breaker. **Chaos button in the Control Room** that kills an agent live to show recovery |
| | Better than a single agent | Eval table in the README: single-agent baseline vs Touchline on numeric accuracy, latency and groundedness (Foundry Evaluations) |
| Best Use of Foundry | Faster innovation, orchestration, management | Foundry Agent Service for hosting, model catalog with fast and reasoning models, **Foundry Evaluations** (groundedness, fluency, custom "numeric accuracy" evaluator), tracing, content safety |
| Best Enterprise Solution | Reliability, transparency, controls | Audit log, human approval queue for the studio ("auto-publish" vs "producer approves"), RBAC roles, PII-free data, Responsible AI note |
| Best Azure Cloud Native | Event-driven, resilient, automated | Event Hubs → Container Apps (API, MCP scale-to-zero, season Job) → Cosmos DB blackboard → Web PubSub fan-out → Logic App distributes recaps to Teams. Health probes, managed identity, `azd up`, OIDC GitHub deploy. |

---

## D. Hero technology: what each one actually does

| Technology | Real job in Touchline | Proof judges can check |
|---|---|---|
| **Microsoft Foundry** | Model deployments, Agent Service, Evaluations, tracing | Screenshots plus eval results in README, `backend/touchline/agents/foundry.py` |
| **Microsoft Agent Framework** | Workflow graph, handoffs, A2A | `backend/touchline/agents/workflow.py` |
| **MCP** | `touchline-mcp` exposes match tools to agents **and** to GitHub Copilot or Claude, so a producer can ask in VS Code "Why did Northbank lose control after 60'?" | `backend/touchline/mcp_server.py`, demo GIF |
| **Azure MCP Server** | Used during development to query Cosmos, App Insights and Event Hubs from Copilot | README "How we built it" section |
| **GitHub Copilot Agent Mode** | Built with it, using `.github/copilot-instructions.md` and custom prompts in `.github/prompts/` | Files in the repo, PR history |
| **GitHub CLI / SDK** | `gh` scripts for releases. A GitHub Action publishes each generated dataset as a Release asset. | `.github/workflows/dataset-release.yml` |
| **Azure Event Hubs** | Live event ingest | `infra/` |
| **Azure Container Apps (+ Jobs)** | API, agents, MCP, web. Jobs generate a 380-match season in parallel. | `infra/` |
| **Azure Logic Apps** | Distribute recaps to Teams/email | `infra/logicapp.bicep` |
| **Azure Cosmos DB** | Blackboard, audit log, user preferences | `backend/touchline/agents/blackboard.py` |
| **Azure AI Search** | "Match memory": past moments and season facts for context and milestones | `backend/touchline/agents/memory.py` |
| **Azure Web PubSub** | Push live insights and overlay cues to browsers | `backend/touchline/live/hub.py` |
| **Azure AI Translator + Speech** | Translation with a football glossary. Optional TTS commentary voice. | `agents/persona.py` |
| **Azure AI Content Safety** | Guardian safety check | `agents/guardian.py` |
| **Azure AI Vision / Foundry vision model** | Auto-Eventer over synthetic video | `backend/touchline/autoevent.py` |
| **Microsoft Fabric** | OneLake (season Parquet), Eventstream → Eventhouse (live KQL), Power BI season dashboard | `infra/fabric/`, screenshot |
| **App Insights / OpenTelemetry** | Per-agent latency, tokens, cost in the Control Room | Control Room screen |
| **Entra ID + managed identity** | Keyless access to every Azure service; Sign in with Microsoft for the watch party | `infra/`, `web/components/WatchParty.tsx` |

---

## E. Submission requirements (Rules §4.4, §4.8, §4.9)
- [ ] New project, created after Sep 29, 2026 (git history proves it)
- [ ] Pitch: what it is, the Microsoft tech used, what it does, the problem it solves
- [ ] Video **under 2:00** on YouTube or Vimeo, public, showing it running, no copyrighted music or trademarks
- [ ] **Public** GitHub repository
- [ ] Working test link (public demo, plus test login for the studio console in the submission notes)
- [ ] Free and available until judging ends on **Nov 10, 2026**. Keep Azure running, and set a budget alert.
- [ ] English for all materials
- [ ] Only synthetic data. Fictional clubs and players. No Premier League marks.
