FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
RUN addgroup --system hria && adduser --system --ingroup hria hria
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY hria ./hria
RUN uv sync --frozen --no-dev --no-editable
USER hria
EXPOSE 8000
CMD ["uvicorn", "hria.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
