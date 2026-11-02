FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Dependencies first, so a code change does not reinstall them. No dev
# tools and no pyspark (group "spark", ~300 MB): the engine and the
# consumers do not need it, and EMR Serverless brings its own Spark.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups --no-install-project

COPY . .

EXPOSE 8000
CMD ["uvicorn", "services.decision_engine.main:app", "--host", "0.0.0.0", "--port", "8000"]
