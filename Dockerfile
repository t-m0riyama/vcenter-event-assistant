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
COPY src ./src
COPY packages ./packages
COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /var/log/vea \
    && chown -R appuser:appuser /app /var/log/vea
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
USER appuser
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["vcenter-event-assistant"]
