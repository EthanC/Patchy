# syntax=docker/dockerfile:1

FROM python:3.15-alpine AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first so they are cached independently of source changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable


FROM python:3.15-alpine

LABEL org.opencontainers.image.title="Patchy" \
      org.opencontainers.image.description="Monitor games on Steam, Battle.net, and PlayStation and notify about updates via Discord." \
      org.opencontainers.image.source="https://github.com/EthanC/Patchy" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

RUN apk add --no-cache su-exec tzdata

COPY --from=builder /app/.venv /app/.venv
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PUID=1000 \
    PGID=1000 \
    PATCHY_CONFIG=/data/config.toml \
    PATCHY_DATABASE_PATH=/data/patchy.db

WORKDIR /data
VOLUME /data

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["patchy"]
