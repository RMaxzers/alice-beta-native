FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.9.27 \
    && groupadd --gid 1000 alice && useradd --uid 1000 --gid 1000 --create-home alice
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache --python /usr/local/bin/python
COPY clients/cli/ ./clients/cli/
RUN uv pip install --python /app/.venv/bin/python --no-deps ./clients/cli
COPY apps/api/ ./apps/api/
COPY services/ ./services/
COPY packages/ ./packages/
COPY config/ ./config/
COPY --from=web /web/dist/ ./apps/web/dist/
RUN mkdir -p data storage logs work && chown -R alice:alice data storage logs work
USER alice
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
