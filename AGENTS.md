# AGENTS.md

K-pop Agent：部署在 Hugging Face Space 的 LINE Bot（Flask + gunicorn，Docker）。專案說明見 `README.md`。

## 目前任務

AI 入坑 v4 / v5 由 Codex 主導，交接文件：`docs/semantic_curator/handoff_codex_v4_v5.md`。

## 開發規則

- Python 一律用 `uv`（`uv sync`、`uv run …`、`uv run --group curator …`），不要用 pip。
- 送出前要過：`uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest`。
- 文件、提示詞、Bot 回覆一律繁體中文（台灣用語）。
- 不要讀取或輸出 `.env` 的內容。
- 只在自己的 feature 分支 commit；push、合併、部署到 Hugging Face Space 前先問使用者。
