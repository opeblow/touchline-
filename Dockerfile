# Touchline: one image for the API + web app, the MCP server and the simulator job.

# ---- web (static export)
FROM node:22-alpine AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install
COPY web/ ./
RUN pnpm build

# ---- python runtime
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/touchline backend/touchline
RUN pip install "./backend[azure]"
COPY data/season data/season
COPY --from=web /web/out web/out
# Pre-generate the featured matches (events + tracking) so the first viewer never waits.
RUN python -c "from touchline.live.catalog import get_featured; [get_featured(m) for m in ('demo','classic','chaos')]"
RUN useradd -m touchline && chown -R touchline /app
USER touchline
EXPOSE 8000
CMD ["uvicorn", "touchline.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
