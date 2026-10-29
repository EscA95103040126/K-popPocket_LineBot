FROM python:3.13-slim

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

# AI 入坑 needs models/bge-m3-v3-int8/ (int8 encoder + member embeddings) in the build
# context. It is built locally (scripts/train_encoder.py, export_onnx_encoder.py,
# build_member_embeddings.py) and committed to the Hugging Face Space through LFS;
# quantizing during the build was OOM-killed on the Space builder. Without it
# (GitHub CI, fresh clones) the bot falls back to v1 ranking.
COPY . .
RUN python scripts/init_db.py && \
    python scripts/seed_data.py

EXPOSE 7860

# The private Play Zone CSVs are not in the image; fetch them at start with the HF_TOKEN
# Space secret. If that fails the bot still starts, and the error is in the run log.
CMD ["sh", "-c", "python scripts/fetch_private_data.py; exec gunicorn -b 0.0.0.0:${PORT:-7860} app:app"]
