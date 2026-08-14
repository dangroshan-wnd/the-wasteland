# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.10.7 AS uv

FROM python:3.12.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY companies.yml ./companies.yml
RUN uv sync --locked --no-dev \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && chown app:app /app

ENV PATH="/app/.venv/bin:$PATH" \
    COMPANIES_FILE=/app/companies.yml

USER app

CMD ["career-page-snapshots"]
