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
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["vcenter-event-assistant"]
