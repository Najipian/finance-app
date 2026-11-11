# syntax=docker/dockerfile:1.7
# One image for both the API and the arq worker; docker-compose picks the command.

# ---------------------------------------------------------------- builder
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# 1) Dependencies only: this layer stays cached until uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# 2) The application itself, installed as a regular (non-editable) package.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]

CMD ["uvicorn", "finance_app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
