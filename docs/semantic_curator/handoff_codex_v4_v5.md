# 給 Codex：主導 AI 入坑 v4 / v5

你好，我是寫 v2、v3 的 Claude。使用者對目前的推薦品質還不滿意，這一輪改由你主導 v4、v5 的設計、實作與評估。這份文件交代現況、可以動的地方和不能破壞的規則。開始前請讀：

1. `docs/semantic_curator/PLAN.md`：v2 / v3 的目標、分工、資料格式、評估結果與試過沒用的做法
2. `README.md` 的「3. AI 入坑」一節：上線架構、模型部署方式、本機重建步驟

專案路徑：`~/Documents/KPOP Agent/kpop-agent`（目前在 `main`，v3 已上線 Hugging Face Space）

## 使用者不滿意的地方

使用者在 LINE 上實測 v3 的三個案例，使用者的判斷是**只有 HAEWON 推得準，MEOVV 那題完全失敗**：

| 使用者輸入 | Bot 推薦 | 今日入口 MV |
| --- | --- | --- |
| 我喜歡 MEOVV 的 ANNA，有沒有相似類型的推薦？ | MEOVV ANNA、MEOVV NARIN、MEOVV ELLA | QWER《가짜 아이돌》 |
| 推薦那種不刻意搞笑，卻因為太認真反而很好笑的女偶像。 | NMIXX HAEWON（準）、TWICE DAHYUN、TWICE SANA | TWICE《MOONLIGHT SUNRISE》 |
| 想找平常很安靜，但一上舞台就像變了一個人的女愛豆。 | QWER HINA、i-dle YUQI、Red Velvet IRENE | i-dle《Oh my god》 |

Claude 的初步判讀（請用程式和資料確認，不要直接當結論）：

1. **把使用者提到的人推回給他**：問「和 ANNA 相似的」，第一名卻是 ANNA 本人，後兩位也是同團。至少要排除被提到的成員本人；「相似類型」這種說法應該優先推其他團。`PLAN.md` 記錄過「排除使用者提到的團」在真實需求上變差（很多人是在問同一團的其他歌），所以要依句型判斷，不要一律排除。
2. **推薦理由在硬湊**：Gemini 收到 3 位成員後，會把使用者的條件直接套在每個人身上（說 DAHYUN「超級認真」、SANA「太過認真而出現小失誤」、YUQI「私下個性隨和又安靜」），聽起來合理，事實卻不一定對。YUQI 一般給人的印象是活潑外向，和「平常很安靜」相反。排序錯了，理由也會跟著替錯的答案背書。可以考慮讓 Gemini 在候選不符合時說出來或換人，或者提示詞只准用成員描述裡有的事實。
3. **「反差」類需求比對不到**：「平常 A、舞台上 B」「不刻意 A 卻 B」這類句子，向量會分別拉近 A 和 B 的字詞（「安靜」「舞台」「認真」），抓不到反差本身。也要檢查成員描述裡有沒有「私下 vs 舞台」「綜藝感」這類資訊；描述裡沒有，換排序方法也找不到。
4. **同團集中**：三題裡有兩題出現同團兩位以上（MEOVV ×3、TWICE ×2）。
5. **今日入口 MV 和推薦對不上（可能是 bug）**：推薦三位都是 MEOVV，`data/play_zone/daily_mv.csv` 裡也有 5 支 MEOVV 的 MV，入口卻給了 QWER，連結預覽圖也是壞的。請檢查 `ai_curator.py` 挑 MV 的邏輯（`_prioritize_members_with_mv`、`_ai_curator_artist_candidates` 一帶）以及團名比對。

請把這三句加進錯誤分析，當作 demo 的回歸案例。改版後它們要明顯變好，但不能拿它們調參數，調參仍然只用 `real-dev`。

## 現況

推薦流程（`src/bot/features/ai_curator.py` → `src/bot/semantic_index.py`）：

1. 使用者的話經 `OnnxEncoder`（int8 bge-m3 + LoRA，`models/bge-m3-v3-int8/`）轉成向量
2. 和預先算好的 154 位成員向量比較 cosine 相似度，取前幾名（`SemanticMemberRanker.rank`）
3. `apply_query_rules`：使用者明說女團／男團時做性別過濾
4. 選出 3 位成員，Gemini（flash-lite，關閉 thinking）只負責寫推薦理由；API 失敗時用本地 fallback

成員描述來自 `data/curator/member_profiles.csv`（Gemini）＋ `grok_enrichment.csv`（Grok 查核補充）；團體概念在 `grok_groups.csv`，只用在提示詞，沒有用在排序。

v3 在 Codex 60 題上的分題型結果（團體命中 @3 / 成員命中 @3）：

| 題型 | 團體 @3 | 成員 @3 |
| --- | --- | --- |
| tag（15 題） | 93% | 80% |
| open（20 題） | 45% | 42% |
| reference（15 題） | 33% | 33% |
| negation（10 題） | 90% | 78% |

真實粉絲需求（238 組）：團體 58% / 成員 28%。弱點很明確：

- **reference 題**（「像 Karina 那種」）：模型把「Karina」當成一般字詞比對，而不是去找和 Karina 風格相近的人。`grok_enrichment.csv` 有 `similar_to` 欄位，目前沒用在排序。
- **open 題**（氛圍、情境）：不到一半答對。
- **negation**：Codex 題上表現不差，但只有 10 題；除了性別過濾，程式裡沒有任何排除邏輯，真實需求裡的否定條件可能沒生效，值得在錯誤分析時確認。
- **真實需求**：v3 的合成訓練資料是 Qwen3-4B 依成員描述寫的，和真實粉絲的說法有分布偏移；真實需求的團體命中幾乎沒進步。

## v4 / v5 方向（由你決定，下面只是候選）

做法要能用評估數字說服人，每個版本都和 v3 在同一份測試集、同一種匯出流程下比較。

- **處理 reference**：偵測句中提到的藝人或成員（`referenced_artists` 已有雛形），改用該成員的向量或 `similar_to` 當查詢，再和原句向量混合。
- **處理 negation**（錯誤分析確認有問題才做）：把否定片段拆出來，對命中否定概念的成員扣分，而不是只做性別過濾。
- **重排序（rerank）**：向量取前 20，再用 cross-encoder（例如 bge-reranker-v2-m3，需量化成 ONNX）或讓 Gemini 從候選中挑 3 位並同時寫理由。後者可以和現在寫理由的那一次呼叫合併，不增加 API 次數。
- **縮小分布偏移**：用 `real-dev` 的說法風格（不是原句）改寫合成資料，或做 hard negative（同團不同成員、風格相反的團）。
- **多樣性**：避免三位推薦都同一團，或刻意一團一位，視使用者想要什麼而定。

## 不能破壞的規則

- **評估集不外洩**：`real-test`、`real-test-discovery` 和 Codex 60 題只用來報最終數字，不拿來調參或寫訓練資料；調參只用 `real-dev`。產生訓練資料或描述的程式和提示詞不能讀 `eval_queries.csv`、`grok_real_requests*.csv` 的原句。
- **小樣本**：每種題型只有 10–20 題，5 個百分點內的差距不算進步；成員層級的比較用逐題符號檢定（v3 就是這樣確認 14 勝 3 敗、p = 0.013）。
- **上線環境限制**：Hugging Face Space 免費 CPU、記憶體有限，執行期只裝 onnxruntime、tokenizers、numpy。新模型必須在本機量化成 int8 ONNX，以 LFS 放進 Space；不要在 Space 建置時量化（會記憶體不足）。單次推薦的延遲要維持在 LINE 回覆時限內（`reply_token` 約 1 分鐘，實際目標數秒內）。
- **自動退回**：找不到模型資料夾或成員向量和描述不一致時，要能退回較舊版本，不讓 Bot 掛掉。
- **本機環境**：M1 Pro、32GB。Python 一律用 `uv`（`uv run`、`uv run --group curator`），不要用 pip。全參數微調會大量用到交換空間，訓練請用 LoRA。
- **程式風格**：跟著現有程式寫，`uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest` 都要過（CI 會跑）。
- **語言**：文件、提示詞、回覆一律繁體中文（台灣用語）。
- **機密**：不要讀取或輸出 `.env` 的內容。
- **git**：從 `main` 開 `feature/curator-v4`（v5 視情況另開）。可以在自己的分支 commit；**push、合併、部署到 Hugging Face Space 都要先問使用者**。

## 建議的第一步

1. 跑 v3 的基準，確認環境正常：

   ```bash
   uv run --no-sync python scripts/evaluate_curator.py v2-bge-m3-v3-int8+gender
   uv run --no-sync python scripts/evaluate_curator.py --set real-dev v2-bge-m3-v3-int8+gender
   ```

   int8 模型只需要 `.venv` 裡已經裝好的 onnxruntime、tokenizers、numpy，所以加 `--no-sync`，不必重新同步、也不會讀 uv 快取。只有要訓練或匯出模型時，才需要 `--group curator`（會安裝 torch，好幾 GB）。

2. 讀第 1 步產生的 v3 rankings（Codex 題在 `data/curator/eval_results/v2-bge-m3-v3-int8+gender_rankings.csv`，real-dev 在 `data/curator/eval_results/real-dev/` 底下；real-test 已有 v3 結果，但只能看總分，不要逐題分析），把答錯的題目分類（reference、否定、抽象情境、同團其他歌、描述本身有錯……），估計每類占多少。
3. 先修「使用者不滿意的地方」第 5 點的 MV bug（和排序無關，修了馬上看得到效果），再依錯誤分布決定 v4 先做哪一項，把計畫寫成 `docs/semantic_curator/PLAN_v4_v5.md` 給使用者確認。
4. 新排序器加進 `scripts/evaluate_curator.py` 的 `RANKERS`，命名沿用 `v4-…`、`v5-…`，結果寫進 `data/curator/eval_results/`。

## 時程

成果要在 **2026-10-31** 的跨領域論壇分享。上台前一天要能定版，所以 v4 最好在 10/28 前有評估數字，v5 視剩餘時間決定是否上線；來不及上線的版本可以只放評估結果。

## 完成後

請在 `PLAN.md` 的結果表補上 v4 / v5 兩列，更新 README 的「v2 / v3：語意向量推薦」一節，並向使用者回報：

- 各版本在 Codex 60 題、real-test、real-test-discovery 的團體 @3 / 成員 @3
- 和 v3 逐題比較的勝敗數與符號檢定 p 值
- 上線所需的模型大小、延遲，以及部署步驟
- 試過但沒有採用的做法和原因
