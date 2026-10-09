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
# プラグインは appuser で動くので、書けると本体のコードを書き換えられる（監査 M-1、Issue #235）。
# appuser が書けるのは /data（DB・プラグイン）と /var/log/vea だけ。
# アプリの既定の置き場所（./data/vea.dev.db・data/plugins）は /app/data なので、/data へのリンクにする。
# ENV で DATABASE_URL などを指定すると、/app/.env に書いた値より優先されてしまうので使わない。
ENV UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev \
    && .venv/bin/python -m compileall -q src packages \
    && useradd --create-home --uid 1000 appuser \
    && mkdir -p /var/log/vea /data \
    && chown -R appuser:appuser /var/log/vea /data \
    && ln -s /data /app/data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
USER appuser

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["vcenter-event-assistant"]
