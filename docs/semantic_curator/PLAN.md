# AI 入坑 v2：語意向量推薦

目標：把「AI 入坑」從固定 34 個標籤的比對，升級成以成員描述為基礎的語意向量檢索，並用評估集量化 v1 → v2（→ v3 微調）的改善。成果用於 2026-10-31 跨領域論壇分享。

分支：`feature/semantic-curator`

## 為什麼要改

v1 會先把用戶的話翻譯成 5 個欄位、約 34 個固定標籤，再用標籤重疊數替成員計分。標籤表以外的說法（「像 Karina 那種」、「聽起來很 chill」、「有故事感的團」）在翻譯時就會消失。v2 讓每位成員有一段開放式描述，直接比較用戶的話和描述的語意相似度，標籤分數保留作為混合排序的一部分。

## 分工

| 角色 | 負責 | 只能寫入 |
| --- | --- | --- |
| Claude | 主要實作：描述生成腳本、embedding 檢索、混合排序、接進 Bot、評估程式、圖表、README | `src/`、`scripts/`、`tests/`、`docs/semantic_curator/`、`data/curator/member_profiles.csv`、`data/curator/eval_results/` |
| Gemini（腳本呼叫） | 依 kprofiles 摘錄與既有標籤生成 154 位成員的基礎描述 | 由 `scripts/build_member_profiles.py` 寫入 `data/curator/member_profiles.csv` |
| Grok | 查核 Gemini 描述並補充描述 | `data/curator/grok_enrichment.csv` |
| Codex | 獨立撰寫測試題；程式審查；（加分）微調腳本 | `data/curator/eval_queries.csv`、`training/` |
| 使用者 | 在工具之間轉交、挑 demo 案例、上台前抽查、簡報 | — |

規則：

- 每個 AI 只寫自己欄位列出的檔案，不改別人的檔案，不 commit、不 push、不切換分支；commit 由使用者決定。
- 不讀取、不輸出 `.env` 的內容。
- Codex 撰寫測試題時不看 `data/curator/` 的描述檔，避免出題和描述用同一套說法而讓分數虛高。
- 反過來，撰寫描述的 AI（Gemini、Grok）不能讀 `data/curator/eval_queries.csv` 和 `data/curator/eval_results/`；給它們的說明也不能引用測試題原句。

## 檔案格式

全部是 UTF-8 CSV，多值欄位用 `|` 分隔，中文一律使用繁體中文（台灣用語）。

### `data/curator/member_profiles.csv`（Gemini 基礎描述）

| 欄位 | 說明 |
| --- | --- |
| `id` | 對應 `data/play_zone/bias_radar_members.csv` 的 `id` |
| `artist` / `member` / `gender_group` | 同上，方便閱讀 |
| `profile` | 80–150 字描述：舞台風格、形象氣質、團內角色、適合哪種粉絲 |
| `keywords` | 5–12 個開放式關鍵字，不受 v1 標籤表限制 |
| `evidence` | `kprofiles` 表示有來源摘錄佐證；`tags` 表示只依既有標籤 |

### `data/curator/grok_enrichment.csv`（Grok 查核與補充）

| 欄位 | 說明 |
| --- | --- |
| `id` | 成員 id |
| `verdict` | `ok`、`minor_issue`、`wrong` 三選一，評的是 Gemini 的 `profile` |
| `issue` | `verdict` 不是 `ok` 時說明哪裡錯 |
| `enrichment` | 60–120 字補充：代表舞台或作品、粉絲常用暱稱與形容、近期形象 |
| `similar_to` | 風格相近的其他 K-pop 成員或團體，例如 `IVE WONYOUNG|NewJeans` |
| `fan_terms` | 粉絲描述這位成員時常用的詞 |
| `sources` | 佐證網址，至少一個 |

### `data/curator/eval_queries.csv`（Codex 測試題）

| 欄位 | 說明 |
| --- | --- |
| `qid` | `q001` 起編號 |
| `query` | 用戶會在 LINE 輸入的一句話 |
| `expected_ids` | 答案成員 id，可多個，用 `|` 分隔 |
| `expected_artists` | 答案團體，可多個；題目只問團體時填這欄 |
| `type` | `tag`（v1 標籤講得出來）、`open`（標籤表以外的說法）、`reference`（提到其他藝人）、`negation`（含否定） |

## 時程

| 日期 | 內容 |
| --- | --- |
| 10/24–25 | Gemini 基礎描述；Grok 查核與補充；Codex 撰寫測試題 |
| 10/26 | 合併描述、embedding 檢索、v1 vs v2 評估 |
| 10/27 | 接進 LINE Bot，部署 HF Space 實測 |
| 10/28–29 | （加分）合成訓練資料、微調、v3 評估 |
| 10/30 | 圖表、demo 截圖、README、緩衝 |

## 結果（2026-10-24）

團體命中 @3 / 成員命中 @3。Codex 為 60 題 AI 獨立出的題目；真實為 Grok 蒐集、推薦落在 25 團內的 238 則粉絲需求（Reddit 摘要另作調參集，不計入）。

| 版本 | Codex | 真實 |
| --- | --- | --- |
| v1 純關鍵字 | 31% / 13% | 42% / 15% |
| v1 關鍵字 + Gemini | 44% / 25% | 45% / 19% |
| v2 bge-m3（官方 ONNX，int8） | 62% / 47% | 55% / 23% |
| v3 LoRA 微調（int8，上線中） | 62% / 60% | 58% / 28% |

試過但沒有採用：

- 團體概念加進排序：直接附加在成員描述後面，或分開計分再以權重合併（權重在調參集上挑），兩份測試集都沒有穩定進步，改用在推薦文字的提示詞。
- 「排除使用者提到的團」：只在 Codex 題多 1 個百分點，在真實需求上變差（很多人是在問同一團的其他歌），所以只保留性別過濾。
- 全參數微調：在 32GB 的 M1 Pro 上大量使用交換空間，改用 LoRA。

注意事項：

- 每種題型只有 15 題，5 個百分點以內的差距不能下結論；v3 的成員層級進步以逐題符號檢定確認（14 勝 3 敗，p = 0.013）。
- 合成資料訓練出的進步集中在 AI 出的題目，真實需求的團體命中持平，也就是分布偏移。
- 公平比較要用同一種匯出流程：官方 ONNX 量化後約掉 3 個百分點，自寫的 torch 匯出幾乎無損。
