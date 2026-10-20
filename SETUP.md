# Touchline — Setup

## 1. Prerequisites
| Tool | Version | Needed for |
|---|---|---|
| Python | 3.11+ (3.12 recommended) | backend |
| Node.js + pnpm | Node 20/22+, pnpm 9+ | web app |
| Azure Developer CLI (`azd`) + Azure CLI | latest | cloud deploy only |
| Docker | latest | building the image locally (optional; `azd` can build remotely) |

## 2. Run locally (fully offline, no keys)
```bash
# from the repo root
python -m venv .venv
.venv/Scripts/pip install -e "./backend[dev]"      # macOS/Linux: .venv/bin/pip

cd web && pnpm install && pnpm build && cd ..        # static export → web/out (served by the API)

cd backend
../.venv/Scripts/python -m touchline.cli serve       # http://localhost:8000
```
Open http://localhost:8000. The first visit generates the 3 featured matches (about 15 s each, then cached in `.cache/`).

For frontend development with hot reload, run `pnpm dev` in `web/` (http://localhost:3000). It talks to the API on :8000 automatically.

## 3. Turn on Microsoft Foundry
```bash
az login
# .env at the repo root
FOUNDRY_PROJECT_ENDPOINT=https://<your-foundry>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL_FAST=gpt-4.1-mini        # deployment names in your project
FOUNDRY_MODEL_REASONING=gpt-4.1
```
Restart the API. The Control Room now shows the provider, model, tokens and cost. You can also use Azure OpenAI (`AZURE_OPENAI_ENDPOINT`) or any OpenAI-compatible endpoint (`OPENAI_API_KEY`, `OPENAI_BASE_URL`). See `.env.example`.

## 4. Deploy to Azure
```bash
azd auth login
azd up
```
`azd up` creates the resources below. Every service uses the app's **user-assigned managed identity** with RBAC; Translator is the only key, and it is stored as a Container Apps secret.

| Resource | Purpose |
|---|---|
| Microsoft Foundry (AI Services + project) | `gpt-4.1-mini` and `gpt-4.1` deployments (override with `azd env set`) |
| Event Hubs | `match-events` hub, plus consumer group `fabric` |
| Cosmos DB (serverless) | `touchline/blackboard` container (Match Blackboard and audit) |
| Web PubSub | Realtime fan-out to viewers |
| AI Translator, AI Content Safety, AI Search | Localization, safety screening, season memory |
| Logic App | Full-time recap distribution (optional Teams webhook: `azd env set TEAMS_WEBHOOK_URL <url>`) |
| Container Apps | `app` (API + web), `mcp` (MCP server, scales to zero), Job `season` (regenerates the 380-match season) |
| ACR, Log Analytics, Application Insights | Images, logs, telemetry |

After the first deploy, load the season memory into AI Search:
```bash
cd backend && SEARCH_ENDPOINT=$(azd env get-value ...) python -m touchline.search_index
```

Useful options:
- `azd env set DEPLOY_FOUNDRY false` uses an existing Foundry project instead. Set `FOUNDRY_PROJECT_ENDPOINT` on the container app.
- For CI/CD, `.github/workflows/deploy.yml` uses OIDC federated credentials (no secrets). Set the repository variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_ENV_NAME` and `AZURE_LOCATION`.

## 5. Microsoft Fabric (analytics)
1. In a Fabric workspace, create an **Eventstream** with the source Azure Event Hubs → `match-events`, consumer group `fabric`.
2. Set the destination to an **Eventhouse** KQL database, table `events`.
3. Open a KQL queryset and run `infra/fabric/queries.kql`. It includes the table mapping, live pass completion, pressing maps, a shot-speed leaderboard and turnover rate.

## 6. MCP and A2A
- **VS Code / GitHub Copilot:** `.vscode/mcp.json` registers `touchline-mcp` (stdio). Start the API, open Copilot Chat in Agent mode, and ask *"Use touchline to explain the key moments of the demo match."*
- **Remote MCP:** the `mcp` container app serves streamable HTTP at `https://<mcp-app>/mcp`.
- **A2A:** the Agent Card is at `/a2a/.well-known/agent-card.json` and the JSON-RPC endpoint is at `/a2a/`.

## 7. Commands
```bash
cd backend
pytest -q                                  # 23 tests
ruff check touchline tests                 # lint
python -m touchline.cli eval               # realism + grounding (+ single vs multi with a model) → docs/eval
python -m touchline.cli season             # regenerate data/season (~2–3 min on 4 cores)
python -m touchline.cli match --prompt "a comeback with a red card at 60'" --out ../data/samples
python -m touchline.cli feed --match demo  # publish a match to Event Hubs at real pace (simulator role)
cd ../web && pnpm lint && pnpm build       # type-check + static export
```

## 8. Demo checklist
- [ ] `/live?match=demo`: kick off at 8×. Switch modes and languages, then try Player cam.
- [ ] `/control?match=demo`: click "Make the Explainer state a wrong number". The Guardian rejects it, the Explainer rewrites it, and it appears in the audit list.
- [ ] `/overlay?match=demo&bg=transparent`: add as a 1920×1080 OBS browser source.
- [ ] `/recap?match=demo`: available after half time and full time.
- [ ] `/studio`: generate a match from a sentence.
