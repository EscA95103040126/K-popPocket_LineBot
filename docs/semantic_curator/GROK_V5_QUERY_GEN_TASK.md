# 給 Grok：在 RTX 5080 上產生 v5 訓練問句

更新日期：2026-10-28（台灣時間）。這份是可轉交的任務說明，由使用者轉給 Grok。

## 要做什麼

用使用者家裡 RTX 5080 電腦上的 Ollama 模型，執行 `scripts/generate_v5_queries.py`，把 `data/curator/member_evidence.csv` 裡每條成員特質，寫成粉絲找人的 LINE 訊息。這批問句會拿來訓練 v5 編碼器。

**你的工作只有執行腳本和回報**。提示詞、篩選規則都寫在腳本裡，不要修改，也不要手寫或手改任何問句；這樣訓練資料才能重現，也不會跟你正在蒐集的評估題互相影響。

## 需要的檔案

從 repo 的 `feature/curator-v5` 分支取得（保持原本的相對路徑）：

- `scripts/generate_v5_queries.py`
- `data/curator/member_evidence.csv`
- `data/play_zone/bias_radar_members.csv`
- `data/curator/grok_aliases.csv`

只需要 Python、`requests`、`opencc`，不用裝整個專案。

## 執行步驟

1. 確認 Ollama 有 `taide`（Gemma-3-TAIDE-12b-Chat）和 `gemma4`（Gemma-4-12B-it）兩個模型，其他模型這次不用。
2. 先試跑 3 條，不寫檔，把輸出貼回來給使用者看：

   ```bash
   uv run --no-project --with requests --with opencc python scripts/generate_v5_queries.py --model taide --limit 3 --dry-run
   ```

3. 使用者確認品質後，兩個模型各跑一次完整版（可中斷，重跑會從斷點繼續）：

   ```bash
   uv run --no-project --with requests --with opencc python scripts/generate_v5_queries.py --model taide
   ```

   ```bash
   uv run --no-project --with requests --with opencc python scripts/generate_v5_queries.py --model gemma4 --no-think
   ```

   Gemma 4 會先思考、答案不在一般欄位，所以一定要加 `--no-think`（改走 Ollama 原生 API 並關掉思考）。
4. 兩個模型會寫進同一個檔案：`data/curator/staging/v5_queries.csv`。

如果 Ollama 不在預設的 `http://127.0.0.1:11434`，用 `--base-url` 指定。如果模型名稱不同，用 `--model` 換成實際名稱，並在回報裡寫明。

## 回報內容

把 `v5_queries.csv` 放回使用者 Mac 的 `data/curator/staging/`，並附上：

- 兩個模型各產生幾句、有幾條證據產生 0 句（腳本最後會印出總數，失敗會印 `!`）。
- 實際使用的模型名稱、Ollama 版本、大約花了多久。
- 跑的過程中看到的明顯問題，例如整批變成簡體、一直輸出非 JSON、句子都在問歌。**只要描述，不要自己修正資料**。

## 不要做的事

- 不要修改腳本、提示詞或輸出的問句；不要另外補寫問句。
- 不要讀評估資料（`member_intent_eval_*`、`eval_results/`、`grok_real_requests*.csv`）來調整任何東西。
- 不要讀取 `.env`；不要修改 Bot 程式、模型、分支或部署。
