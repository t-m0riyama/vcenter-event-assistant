# syntax=docker/dockerfile:1
# Stage 1: build React SPA
FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python app + embedded frontend/dist
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY packages ./packages
COPY --from=frontend /app/frontend/dist ./frontend/dist

# /app（アプリのコードと .venv）は root 所有のままにし、実行ユーザー appuser には書かせない。
# Compose ではワーカー・インストーラ・ビルダーもそれぞれ別の非 root UID で動く（Issue #274）。
# アプリの既定の置き場所（./data/vea.dev.db・data/plugins）は /app/data なので、/data へのリンクにする。
# ENV で DATABASE_URL などを指定すると、/app/.env に書いた値より優先されてしまうので使わない。
ENV UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev \
    && .venv/bin/python -m compileall -q src packages \
    && useradd --create-home --uid 1000 appuser \
    && useradd --no-create-home --uid 1001 vea-worker \
    && useradd --no-create-home --uid 1002 vea-installer \
    && useradd --no-create-home --uid 1003 vea-builder \
    && install -d -o appuser -g appuser /var/log/vea /data /data/plugins /legacy-data \
    && install -d -m 2710 -o vea-worker -g appuser /sockets/worker \
    && install -d -m 2710 -o vea-installer -g appuser /sockets/installer \
    && install -d -m 2710 -o vea-builder -g appuser /sockets/builder \
    && ln -s /data /app/data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
USER appuser

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["vcenter-event-assistant"]
