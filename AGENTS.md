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

## 私人資料（2026-10-30 起，使用者要求）

- `data/play_zone/` 的 `bias_radar_members.csv`、`daily_fancam.csv`、`daily_mv.csv`、`daily_stage.csv`、`member_quiz.csv` 是私人資料，**不要 commit 到 git，也不要上傳到 Space**（Space 是公開的）。
- 這五份放在私人 HF Dataset `EscA95103040126/kpop-agent-private-data`。Space 啟動時會用 `HF_TOKEN` Secret 執行 `scripts/fetch_private_data.py` 下載。
- 本機改了這些 CSV 之後，要上傳到 Dataset（指令見 README「私人資料」），再重啟 Space。
- 部署到 Space 時只上傳 commit 改到的檔案，不要整個工作目錄上傳；上傳前確認清單裡沒有這五份 CSV。
