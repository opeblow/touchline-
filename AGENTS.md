# AGENTS.md

Instructions for AI coding agents (Claude Code, GitHub Copilot agent mode and others) working in this repository. Read `README.md` for the product, `CRITERIA.md` for what judges look for, and `DESIGN.md` for UI rules.

## Golden rules
1. **LLMs never invent numbers.** Every metric comes from `backend/touchline/stats/`. Agents receive facts (`{fact_id, label, display}`) and must cite `fact_id`s. New numbers must be created with `StatsEngine.fact(...)`.
2. **Everything an agent writes passes the Guardian** (`agents/guardian_rules.py`) before it is published.
3. **Synthetic and fictional only.** No real club or player names, no logos, no league marks.
4. **Every feature works offline.** If you add an LLM path, also add a deterministic fallback. Templates must stay Guardian-safe in all 6 languages (see `tests/test_guardian.py`).
5. **Follow `DESIGN.md`.** Light theme, green/amber accents, no purple or gradients, tabular numbers.

## Layout
```
backend/touchline/
  models.py           typed contracts (source of truth for web/lib/types.ts)
  sim/                engine.py (events), tracking.py (5 Hz physics), league.py, scenario.py, shape.py
  stats/              engine.py (incremental stats + facts + triggers), models.py (xG, pass difficulty, threat)
  intel/              moments.py (Moment Spotter), overlay.py (cues), analysis.py (offline pass)
  agents/             workflow.py (Agent Framework graph), specialists.py, runtime.py (timeouts, breakers,
                      faults, traces), guardian_rules.py, templates.py, context.py, ask.py, llm.py, prompts/*.md
  live/               session.py (orchestration), bus.py (queue | Event Hubs), hub.py (WS | Web PubSub), catalog.py
  api/main.py         FastAPI: REST, WebSocket, A2A mount, static web
  mcp_server.py, a2a_server.py, season.py, evals.py, search_index.py, cli.py
web/                  Next.js 16 static export (app/, components/, lib/)
infra/                Bicep (azd), fabric/queries.kql
```

## Commands
```bash
cd backend && ../.venv/Scripts/python -m pytest -q
../.venv/Scripts/python -m ruff check touchline tests && ../.venv/Scripts/python -m ruff format touchline tests
../.venv/Scripts/python -m touchline.cli serve
cd web && pnpm lint && pnpm build
```

## Agents (runtime)
| Agent | Code | Output |
|---|---|---|
| Moment Spotter | `intel/moments.py` | `Moment` (importance 0–100, facts) |
| Memory | `specialists.MemoryAgent` | season `Fact`s |
| Explainer | `specialists.Explainer` | `Insight` with `cited_fact_ids` |
| Narrator | `specialists.Narrator` | `CommentaryLine` per language |
| Guardian | `specialists.Guardian` + `guardian_rules.py` | `Verdict` + audit entry |
| Persona + Localizer | `specialists.Persona` | `PersonalizedInsight` per (mode, lang, club, player) |
| Tactician | `specialists.Tactician` | `TacticalShift` |
| Producer | `specialists.Producer` | `Recap` |
| Ask (A2A) | `agents/ask.py`, `a2a_server.py` | verified answer + tools used |

All agent calls go through `AgentRuntime.guarded()` / `trace()`. Never call the LLM directly from new code.

## Definition of done
- Tests and lint pass. `pnpm build` passes.
- It works offline **and** with a model configured.
- Every new requirement row in `CRITERIA.md` has code, a README mention and, for essentials, a demo moment.
