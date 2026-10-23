FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    FLASK_DEBUG=0 \
    DATABASE_PATH=data/chart_history.db \
    MOCK_DATA_DIR=data/mock \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so code-only changes reuse this layer.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked

# AI 入坑 v2 encoder: download bge-m3's official ONNX export, quantize it to int8 and
# precompute member embeddings. Only models/ reaches the final image. Build with
# --build-arg SEMANTIC_CURATOR=0 to skip it; the bot then falls back to v1 ranking.
FROM base AS encoder
ARG SEMANTIC_CURATOR=1
RUN uv sync --locked --group encoder-build
COPY src ./src
COPY scripts ./scripts
COPY data/curator ./data/curator
COPY data/play_zone ./data/play_zone
RUN mkdir -p models && \
    if [ "$SEMANTIC_CURATOR" = "1" ]; then \
        python scripts/export_onnx_encoder.py && \
        python scripts/build_member_embeddings.py; \
    fi

FROM base

COPY . .
COPY --from=encoder /app/models ./models
RUN python scripts/init_db.py && \
    python scripts/seed_data.py

EXPOSE 7860

CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-7860} app:app"]
