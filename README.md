---
title: Kpop Pocket
sdk: docker
app_port: 7860
pinned: false
---

# Kpop Pocket

[![CI](https://github.com/EscA95103040126/K-popPocket_LineBot/actions/workflows/ci.yml/badge.svg)](https://github.com/EscA95103040126/K-popPocket_LineBot/actions/workflows/ci.yml)

Kpop Pocket 是一個已部署至 Hugging Face Space 的 LINE Bot 專案，將 K-pop 榜單資料、Naver 新聞、YouTube 留言情感分析、Gemini 文字生成、SQLite 快取與 LINE Flex Message 整合成可互動的 K-pop 分析與遊玩型機器人。

- Hugging Face Space: <https://huggingface.co/spaces/EscA95103040126/kpop-agent>
- GitHub Repo: <https://github.com/EscA95103040126/K-popPocket_LineBot>
- Runtime: Docker on Hugging Face Spaces
- App Port: `7860`
- Local Framework: Flask
- Bot Platform: LINE Messaging API

## 專案定位

這個專案分成兩條主要路線：

| 路線 | 說明 |
| --- | --- |
| 資料分析線 | 藝人分析報告、Bugs 榜單、Naver 新聞、YouTube 留言情感分析、Gemini 市場洞察 |
| 互動體驗線 | Rich Menu、AI 入坑、每日一首 K-pop、我的 K-pop 口袋、Play Zone 測驗與抽卡 |

核心目標不是只回覆固定文字，而是把資料與互動流程包裝成 LINE 使用者可以直接點選、抽取、測驗與追問的 Bot 體驗。

## 已部署狀態

本專案目前已部署在 Hugging Face Space：

```text
https://huggingface.co/spaces/EscA95103040126/kpop-agent
```

Hugging Face 使用 repo 根目錄的 `Dockerfile` 建置服務，並透過 README frontmatter 指定：

```yaml
sdk: docker
app_port: 7860
```

`Dockerfile` 會用 uv 依 `uv.lock` 安裝執行期依賴（`uv sync --locked`，不含開發工具），初始化 SQLite 資料庫，並以 `gunicorn` 啟動 Flask app。

## 主要功能

### 1. LINE Rich Menu

Rich Menu 提供六個主要入口：

| 入口 | 功能 |
| --- | --- |
| 分析藝人 | 選擇藝人並產生完整市場分析報告 |
| 本週榜單 | 查詢 Bugs K-pop 週榜資料 |
| 互動專區 | 進入 K-pop Play Zone |
| 每日一首 | 抽 MV、直拍或舞台推薦 |
| AI 入坑 | 根據自然語言偏好推薦入坑路線 |
| 使用說明 | 顯示支援指令與使用方式 |

Rich Menu 建立腳本位於：

```text
scripts/setup_rich_menu.py
```

### 2. 藝人分析報告

使用者可以在 LINE 輸入：

```text
分析 aespa
分析 IVE
分析 NCT
```

Bot 會優先讀取離線產生的 ABSA cache，回傳包含以下內容的分析報告：

- 藝人基本分析
- Bugs 榜單表現
- YouTube 韓文留言 ABSA / 情感比例
- Naver 近期新聞摘要
- Gemini 市場洞察
- LINE Flex Message 視覺化卡片

目前支援分析的藝人：

```text
aespa, IVE, BABYMONSTER, NMIXX, Hearts2Hearts, NCT,
ZEROBASEONE, TXT, ENHYPEN, BOYNEXTDOOR
```

Hearts2Hearts 也支援 `分析 H2H`、`分析 하츠투하츠`，並使用和其他藝人相同的五面向 ABSA 與 LINE 分析卡片。ILLIT 已退出此分析名單；每日推薦、收藏與 AI 入坑的 ILLIT 資料仍可使用。

### 3. AI 入坑

AI 入坑支援自然語言偏好，例如：

```text
我喜歡小鹿臉的
我想入坑清冷感、舞台強的女團
幫我推薦 vocal 強、現場穩的 K-pop
我喜歡霸氣舞台、rap 和 dance
```

系統會依照使用者偏好推薦成員與團體，再搭配 `data/play_zone/daily_mv.csv` 提供 MV 入坑路線。

若 Gemini API 可用，會產生較自然的推薦文字；若 API 不可用，會使用本地 fallback 產生穩定回覆。

#### v2 / v3：語意向量推薦

v1 會先把使用者的話對應到約 34 個固定標籤，再依 `bias_radar_members.csv` 的標籤重疊數排序，標籤表以外的說法（例如「像 Karina 那種」「適合深夜開車聽」）會直接遺失。v2 改為：

1. 每位成員有一段開放式描述：Gemini 依 kprofiles 摘錄生成（`data/curator/member_profiles.csv`），再由 Grok 查核並補充代表作、音色、粉絲用語（`data/curator/grok_enrichment.csv`）。
2. 以 int8 量化的 [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) 把描述和使用者的話轉成向量，依相似度排序；使用者明說女團或男團時，再做性別過濾。
3. 推薦文字的提示詞加入成員簡介與團體概念（`data/curator/grok_groups.csv`），讓 Gemini 說得出「為什麼推這團」。v2 不再呼叫 Gemini 解析偏好，每次推薦只用 1 次 Gemini。

v3 再用 LoRA 微調 bge-m3：本機 MLX 上的 Qwen3-4B 依成員描述寫出 2,267 句粉絲口吻的需求（`scripts/generate_synthetic_queries.py`），以 `scripts/train_encoder.py` 訓練（只訓練 0.41% 的參數）。目前上線的是 v3。

評估結果（團體命中 @3 / 成員命中 @3，見 `scripts/evaluate_curator.py` 與 `docs/semantic_curator/PLAN.md`）：

| 測試集 | v1（關鍵字 + Gemini） | v2（bge-m3 int8） | v3（LoRA 微調 int8） |
| --- | --- | --- | --- |
| Codex 撰寫的 60 題 | 44% / 25% | 62% / 47% | 62% / 60% |
| 真實粉絲推坑需求 238 組 | 45% / 19% | 55% / 23% | 58% / 28% |

v3 的進步集中在成員層級：和用同一流程匯出的原始 bge-m3 逐題比較，多答對 14 題、答錯 3 題（符號檢定 p = 0.013）；真實需求的團體命中則持平。

#### v4：看懂「像誰」，理由要有來源

v4 沿用 v3 的模型和向量，不重新訓練，改的是排序前後兩端：

1. **別名與意圖**（`src/bot/curator_query.py`）：把暱稱、韓文名、中文名對回成員（`data/curator/grok_aliases.csv`），同名但沒寫團名的不猜。說「像 ANNA 那種」時排除 ANNA 本人，同團只保留一位在前面；明說「其他團」或「不要某團」才整團排除。
2. **有來源的成員特質**（`data/curator/member_evidence.csv`）：Grok 從粉絲社群、媒體與百科整理成員觀感，粉絲觀感要有 3 個以上獨立來源才成立；本人自述、單一來源和待查的都不收。目前 154 位裡有 126 位、共 193 條。這份資料只用來寫推薦理由，不影響排序。
3. **理由不硬套**：Gemini 會收到每位成員有來源的特質，以及「資料沒寫他的反差／綜藝感…」的提醒；粉絲觀感寫成「粉絲常說…」。沒有 Gemini 時，本地理由也只用和問題同一面向的粉絲觀感。

real-dev（116 題，只用來調整規則）：團體命中 @3 從 v3 的 33.6% 升到 39.7%，逐題 7 勝 0 敗（符號檢定 p = 0.016）；成員命中 @3 持平在 25%（只有 20 題有成員答案，看不出差異）。正式測試集尚未重跑。原始批次含第三方貼文摘錄，留在本機 `data/curator/staging/`，不進 git；更新證據表：

```bash
uv run python scripts/build_member_evidence.py
```

#### v5：v4 加上 LLM 偏好解析（目前上線）

v5 不改 v4 的編碼器和排序，在上面多一層 Gemini 偏好解析（`src/bot/preference.py`）：

1. **解析偏好**：Gemini 把粉絲的話（中文、韓文或英文）解析成 JSON：想要或不想要的特質、程度（超、有點…）、性別、是不是在問長相。特質只能從 `data/curator/trait_tags.csv` 的 18 個標籤裡選，每個標籤有哪些成員完全由證據表裡**有來源的主張**決定，模型不能替成員補特質；對應不到的說法不參與排序。
2. **人名整名比對**：Gemini 只照原文列出提到的人名、團名和是不是負向參照；本機再用別名表整個名字精確比對，不找子字串。團名不符、同名分不清或目錄外的人一律不算參照成員。提示詞不附成員表，約 3,000 字。
3. **重排**：v4 分數標準化後，符合正向特質的成員加分、符合否定特質的往後排（不刪除），排除指定的團和參照成員本人，性別不合的往後排。
4. **失敗就退回 v4**：偏好解析另用一個 8 秒逾時的 Gemini 連線；逾時、格式錯誤或沒有金鑰時直接照 v4 排序，不影響回覆。偏好解析的模型固定在程式裡（`PREFERENCE_MODEL`，目前是 `gemini-3.1-flash-lite`），不跟著 `GEMINI_MODEL` 換。每則 AI 入坑會用 2 次 Gemini（解析 1 次、產生回覆 1 次）。

在 Space 上量的偏好解析延遲（20 次）：中位數 1.79 秒、p90 4.34 秒、最慢 14.47 秒。需要重量時設定 Space 變數 `PREFERENCE_PROBE_RUNS=20`，啟動後背景量測、結果寫進 log，量完再刪掉變數。

評估（詳見 [`docs/semantic_curator/RESULTS_v5.md`](docs/semantic_curator/RESULTS_v5.md)）：

- 第三份封存測試 test3（Grok 蒐集的真實推坑串，40 題，事前登記、只跑一次）：外貌子集 hit@3 從 v4 的 0.300 升到 0.400，全體 strong hit@3 持平 0.579，兩項登記標準都通過；進步 3 題、退步 0 題，樣本小，不顯著。
- test3 測的是 **pref-v3**（提示詞附成員表，由 Gemini 直接填成員 id）。上線的 **pref-v6** 改成本機整名比對，只在練習集和已用過的 137 題上驗證過：練習集 61 句參照成員 98%、特質 precision 0.84、recall 0.91；137 題上整體 strong hit@3 和 v4 持平，外貌子集 lenient hit@3 0.325 → 0.388。
- test3 執行時的 prompt 含一句改寫自公開貼文的例句，現已改為自寫例句（pref-v6）。
- 重新訓練編碼器、證據向量和照片相似度（v5 第一版）在前兩次封存測試都沒有贏 v4，程式留著但預設關閉。

訊息路由：點「AI 入坑」後 10 分鐘內的文字都視為偏好；沒點入口時，其他功能都沒接走、且含有「喜歡、想找、推薦、有沒有」等字眼的訊息，也會交給 AI 入坑。

模型不放進 GitHub，只以 LFS 放進 Hugging Face Space 的儲存庫（在 Space 建置時量化會記憶體不足）。`models/bge-m3-v3-int8/` 內含 int8 模型和預先算好的成員向量，執行時只需要 onnxruntime、tokenizers 和 numpy。找不到這個資料夾，或成員向量和目前描述不一致時，會自動退回 v1；所以修改 `data/curator/` 後，要重跑 `build_member_embeddings.py` 再部署。本機重建 v3：

```bash
uv run --group curator python scripts/train_encoder.py
```

```bash
uv run --group curator python scripts/export_onnx_encoder.py --source models/bge-m3-curator-v3 --out models/bge-m3-v3-int8
```

```bash
uv run python scripts/build_member_embeddings.py
```

### 4. 每日一首 K-pop

每日一首提供三種抽取：

| 類型 | 資料來源 |
| --- | --- |
| 每日 MV | `data/play_zone/daily_mv.csv` / Supabase `kpop_items` |
| 每日直拍 | `data/play_zone/daily_fancam.csv` |
| 每日舞台 | `data/play_zone/daily_stage.csv` |

抽取結果會回傳純文字連結，讓 LINE 自動產生 YouTube 預覽，並附上可再次抽取的 Flex Message。

若 Supabase 已設定，`每日 MV` 會優先使用 `kpop_items` 做個人化推薦。使用者在「我的 K-pop 口袋」設定的 `preferred_gender` 會對應到 `kpop_items.gender_category`，因此可以只抽女團、男團或都可以。若選擇 `all` / 都可以，系統不會只推薦 `mixed` 內容，而是不加性別篩選，從男團、女團與 mixed 全部 MV 中抽取。若 Supabase 未設定或查詢失敗，系統會回到 `daily_mv.csv` 的本地隨機抽取。

`daily_mv.csv` 本身只存 `artist`、`title`、`url`，不直接存性別分類。分類是在匯入 Supabase 前由 `scripts/import_kpop_items.py` 補上：

- 先從 `data/play_zone/bias_radar_members.csv` 的 `group_type` 建立藝人性別 lookup。
- 再用 `MANUAL_ARTIST_GENDERS` 補齊 CSV 內沒有出現在本命雷達資料集的團體名稱。
- 匯入後寫入 `kpop_items.gender_category`，每日 MV 推薦再用使用者的 `preferred_gender` 篩選。
- `mixed` 是內容分類，不是使用者偏好選項；使用者偏好選項只有女團、男團、都可以。

目前 MV 藝人分類已校正為：

| 分類 | 藝人 |
| --- | --- |
| `boy_group` | ATEEZ, BOYNEXTDOOR, BSS, CRAVITY, DAY6, ENHYPEN, EXO, MONSTA X, NCT 127, NCT DREAM, NCT U, NCT WISH, SEVENTEEN, Stray Kids, TXT, ZEROBASEONE |
| `girl_group` | aespa, BABYMONSTER, BLACKPINK, H1-KEY, Hearts2Hearts, i-dle, ILLIT, IVE, KISS OF LIFE, LE SSERAFIM, MEOVV, QWER, Red Velvet, Red Velvet X aespa, tripleS, TWICE |
| `mixed` | ALLDAY PROJECT |

### 5. 我的 K-pop 口袋

我的 K-pop 口袋使用 Supabase 儲存使用者收藏與推薦偏好，包含：

- `user_preferences.preferred_gender`：每日 MV 推薦偏好，可為 `girl_group`、`boy_group` 或 `all`。
- `kpop_items.gender_category`：每筆 MV、直拍或照片的團體分類。
- `user_saved_items`：使用者收藏的 MV、直拍與照片。
- `user_draw_history`：每日 MV 已抽過的項目，用來降低重複推薦。

使用者可以在 LINE 中查看收藏數、查看已收藏內容、修改每日 MV 推薦偏好，並從每日推薦、直拍或神圖抽卡結果加入收藏。

推薦邏輯重點：

1. 設定推薦偏好
使用者可以選擇女團、男團或都可以，讓每日 MV 推薦更符合自己的追星方向。

2. 減少每日 MV 重複推薦
系統會記錄使用者已抽過與已收藏的 MV，推薦時優先避開重複項目，提升探索新內容的效率。

3. 建立個人化資料層
收藏、偏好與抽取記錄會寫入 Supabase，讓 LINE Bot 從一次性回覆工具，升級成能累積使用者喜好的 K-pop 助理。

### 6. K-pop Play Zone

Play Zone 是互動遊玩區，目前包含：

| 功能 | 說明 | 主要資料 |
| --- | --- | --- |
| 粉絲屬性測驗 | 透過 5 題選擇題判斷使用者是團飯、唯飯或跟風粉 | app 內建題庫 |
| 本命雷達測驗 | 依照性別團、外貌偏好、定位、氣質、關係感推薦 K-pop 成員 | `bias_radar_questions.json`, `bias_radar_members.csv`, `radar_image/` |
| 認人測驗 | 顯示成員圖片並讓使用者選答案 | `member_quiz.csv`, `member_quiz_images/` |
| 神圖抽卡 | 隨機抽取成員神圖或推薦內容 | `photo_cards.csv` |

### 7. 榜單、新聞與情感分析

專案整合多個資料來源：

| 資料 | 用途 | 主要檔案 |
| --- | --- | --- |
| Bugs Chart | K-pop 週榜爬取與 SQLite 儲存 | `src/tools/bugs_chart.py`, `src/tools/chart_db.py` |
| Naver News | 查詢藝人近期新聞 | `src/tools/naver_news.py` |
| YouTube Comments | 抓取韓文留言 | `scripts/fetch_youtube_comments.py` |
| Offline ABSA | 對新聞與留言做面向式情感分析，輸出本地 cache | `src/tools/absa.py`, `scripts/build_absa_cache.py`, `data/cache/absa/*.json` |
| Sentiment CSV | 預標註留言情感分析 fallback | `src/tools/sentiment.py`, `data/sample_comments.csv` |
| Gemini | 市場洞察、AI 入坑、推薦原因生成 | `src/agent.py`, `app.py` |

`本週榜單` 仍回覆資料庫中最新一週的 Bugs 前 10；若資料庫有更早週次，Bot 會額外顯示「歷史週次」按鈕，點選後回覆該週前 10。

### 8. 離線 ABSA pipeline

`分析 藝人` 的輿論面向分析不在 LINE webhook 內即時跑模型，也不在 webhook 內大量抓 YouTube 留言。正式流程是先執行離線批次：

```bash
uv run python scripts/build_absa_cache.py
```

批次腳本會：

- 透過 Naver News API 抓取每位藝人近期新聞；API 不可用時沿用既有 mock fallback。
- 透過 YouTube Data API 抓取韓文留言；若未提供 `YOUTUBE_API_KEY` 可用 `--use-sample-comments` 讀取 `data/sample_comments.csv`。
- 使用 KcELECTRA sentiment/ABSA model 做韓文新聞與留言情感分類；若批次環境未安裝 `transformers` / `torch`，腳本會降級為 keyword fallback，仍維持相同 JSON schema。
- 依五個面向輸出 `data/cache/absa/{artist}.json`，另輸出 `data/cache/absa/summary.csv`。

支援面向：

```text
song / music
performance
visual / styling
vocal / rap
fandom / public_opinion
```

LINE Bot 收到 `分析 aespa`、`分析 IVE` 等完整藝人分析指令時，會先讀 `data/cache/absa/{artist}.json`。若 ABSA cache 不存在或 schema 無效，才回到既有 `data/cache/artists/{artist}.json` / 本地 fallback 流程。

## 按月份更新藝人分析

2026/10/28 回歸更新包含 BABYMONSTER《DESERVE》、IVE《Looks Can Kill》、NMIXX《Strange Muse》／〈Birthday Wish（긴 소원）〉，並將 Hearts2Hearts 納入 ABSA。針對回歸作品可限制影片發布日期，避免採樣到先前作品的影片：

```bash
uv run python scripts/refresh_monthly_analysis.py --month 2026-10 --as-of 2026-10-28 --artists BABYMONSTER IVE NMIXX Hearts2Hearts --comments-per-artist 200 --video-published-after 2026-10-12 --publish-local
```

需要分析指定月份時，使用有日期與來源紀錄的更新流程：

```bash
uv run python -u scripts/refresh_monthly_analysis.py --month 2026-10 --as-of 2026-10-11 --publish-local
```

這個流程直接讀取 Naver、YouTube、Bugs 與 Gemini API，不以 mock 或舊留言替代當月資料。它會按發布日期篩選新聞及韓文頂層留言，以 Gemini 做整體及五面向情感標註，再產生附引用來源的繁體中文報告。新聞不納入留言情感比例，正面比例不作為市場熱度指標。影片搜尋為抽樣，並包含非官方舞台影片，不代表所有粉絲或一般大眾。

預設每組藝人目標為 100 則留言，但只保留期間內實際可取得的留言，樣本可能少於目標。新聞依韓國刊登日篩選；留言依 Asia/Taipei 日期篩選。當月尚未結束時，產出的是截至日分析。Bugs 使用實際回傳的已發布週榜日期，不把查詢日期當成榜單日期；橫跨月份的週榜會標明限制。

原始資料、模型標註、JSON 快取、CSV 與 Markdown 報告寫入 `data/reports/{月份}-through-{截至日}/`。所有指定藝人完成後，`--publish-local` 才會更新本機 `data/cache/absa/`，並在報告目錄備份原本快取。LINE 讀取月報時會保留報告的日期與榜單快照。

失敗後可以加 `--reuse-raw`，接續使用同一期間已取得的資料與完成的結果。未加 `--publish-local` 時只產生報告，不變更啟用快取。更新本機檔案後，仍需同步部署至 Hugging Face，線上 LINE Bot 才會使用新版報告。

## 系統架構

三個入口（LINE webhook、JSON API `/analyze`、本機 mock webhook）共用同一張路由表。每個功能只回傳跟平台無關的 `Reply`，再由各入口轉成自己的格式：

```text
LINE 使用者 ──> LINE Messaging API ──> POST /webhook ──> LineAdapter
                                                          │ 驗證簽章、去重、debounce
HTTP 呼叫端 ───────────────────────> POST /analyze ──────┤
本機 mock ─────────────────────────> POST /webhook ──────┤（未設定 LINE 金鑰時）
                                                          v
                                          Dispatcher（src/bot/routing.py）
                                          依序比對 18 個 handler，第一個符合的負責回覆
                                                          │
          ┌──────────────┬──────────────┬─────────────────┼──────────────┬──────────────┐
          v              v              v                 v              v              v
       藝人分析        週榜           AI 入坑         Play Zone      每日一首      我的口袋
     (agent +       (agent +       (Gemini +        (本命雷達、     (CSV /        (Supabase)
     ABSA cache)    SQLite)        CSV 資料)        認人、抽卡)     Supabase)
          └──────────────┴──────────────┴────────┬────────┴──────────────┴──────────────┘
                                                  v
                                        Reply（文字、Flex、Quick Reply）
                                                  │
                         ┌────────────────────────┼────────────────────────┐
                         v                        v                        v
                 LINE 訊息（line_renderer）   JSON（Reply.to_json）     純文字（mock）
```

設計重點：

- **單一路由表**：`src/bot/routing.py` 是唯一決定「哪則訊息由哪個功能處理」的地方，順序就是優先順序。
- **依賴注入**：`create_app(deps)` 接收 `BotDeps`（設定、分析 agent、Supabase repo、Gemini client、亂數、時鐘）。正式環境由 `BotDeps.from_settings()` 建立；測試則注入假物件，不用 monkeypatch 全域變數。
- **狀態跟著實例走**：抽卡佇列等暫時狀態存在各功能物件裡，每個 app 實例各自獨立。
- **對話狀態可以撐過重啟**：本命雷達的作答進度和 AI 入坑的追問脈絡透過 `SessionStore`（`src/bot/sessions.py`）存取，見下方「對話狀態保存」。

### 對話狀態保存

`SessionStore` 是一個小介面（`get` / `set` / `delete`，每筆資料都有 TTL），有三種實作：

| 實作 | 用途 |
| --- | --- |
| `InMemorySessionStore` | 本機開發與測試；資料只存在這個 process 裡 |
| `SupabaseSessionStore` | 寫進 Supabase 的 `bot_sessions` 資料表，Space 重啟後仍在 |
| `CachedSessionStore` | 正式環境的組合：讀取先查記憶體，寫入同時寫進 Supabase |

有設定 Supabase 時，`BotDeps.from_settings()` 會使用 `CachedSessionStore`：

- 同一個 process 寫入的資料，之後都直接從記憶體讀，不必每次訊息都打 Supabase；只有重啟後第一次讀取才會向 Supabase 查詢。
- 查不到資料的結果也會快取 5 分鐘，所以一般聊天訊息不會每則都多一次查詢。
- Supabase 出錯時只記一筆警告，bot 會繼續用記憶體運作，不會因此回覆失敗。
- 這個設計假設只有一個 bot process（Hugging Face Space 就是這樣）；如果要同時跑多個 process，需要改用不在本機快取的寫法。

啟用前要先在 Supabase SQL editor 執行 `supabase/bot_sessions_schema.sql`。`/health` 的 `session_store` 欄位會顯示目前用的是哪種實作，以及 `bot_sessions` 能不能存取（`ok`）。

## 專案結構

```text
.
├── app.py                         # WSGI 進入點（gunicorn app:app），只呼叫 create_app()
├── Dockerfile                     # Hugging Face Space Docker runtime
├── pyproject.toml                 # 依賴、pytest、coverage 與 ruff 設定
├── uv.lock                        # uv 鎖定的完整依賴版本
├── .python-version                # Python 3.13
├── .github/workflows/ci.yml       # GitHub Actions：lint、測試、coverage、Docker 冒煙測試
├── src/
│   ├── web/
│   │   └── app_factory.py         # create_app()：Flask 路由、health、圖片路由
│   ├── bot/
│   │   ├── container.py           # BotDeps、Features 與 build_bot() 組裝
│   │   ├── routing.py             # 單一路由表與固定指令判斷
│   │   ├── dispatcher.py          # Dispatcher / Handler / MessageContext
│   │   ├── reply.py               # 跟平台無關的 Reply 與 QuickReplyAction
│   │   ├── line_adapter.py        # LINE webhook：簽章驗證、事件分派、送出回覆
│   │   ├── line_events.py         # LINE 事件去重與 debounce
│   │   ├── line_renderer.py       # Reply → LINE 訊息
│   │   ├── llm.py                 # Gemini 文字生成 client
│   │   ├── catalog.py             # Play Zone CSV 資料讀取與快取
│   │   ├── flex_common.py         # 共用 Flex 元件與配色
│   │   ├── text_utils.py          # 名稱比對等文字工具
│   │   ├── sessions.py            # SessionStore：對話狀態（記憶體 / Supabase）
│   │   └── features/              # 各功能模組
│   │       ├── menus.py           # 選單、使用說明、選擇藝人
│   │       ├── artist_report.py   # 藝人分析報告
│   │       ├── charts.py          # 本週榜單與歷史週榜
│   │       ├── ai_curator.py      # AI 入坑與推薦理由追問
│   │       ├── bias_radar.py      # 本命雷達測驗
│   │       ├── fan_quiz.py        # 粉絲屬性測驗
│   │       ├── member_quiz.py     # 認人測驗
│   │       ├── daily_kpop.py      # 每日一首
│   │       ├── photo_card.py      # 神圖抽卡
│   │       └── pocket.py          # 我的 K-pop 口袋
│   ├── agent.py                   # 藝人分析、Gemini 報告與 fallback
│   ├── config.py                  # 環境變數與路徑設定
│   ├── router.py                  # 藝人名稱與週榜 intent 解析
│   ├── tools/
│   │   ├── bugs_chart.py          # Bugs 榜單爬蟲/parser
│   │   ├── chart_db.py            # SQLite 榜單查詢
│   │   ├── naver_news.py          # Naver News API
│   │   ├── sentiment.py           # 留言情感分析 fallback
│   │   ├── kpop_radar.py          # Supabase K-pop 口袋、收藏與每日 MV 個人化
│   │   └── absa.py                # 離線 ABSA cache schema / loader / analyzer
│   └── utils/
│       ├── response_formatter.py  # LINE 文字長度處理
│       └── text_cleaner.py        # 文字清理
├── scripts/
│   ├── setup_rich_menu.py         # 建立 LINE Rich Menu
│   ├── fetch_bugs_chart.py        # 抓取 Bugs 週榜
│   ├── fetch_youtube_comments.py  # 抓取 YouTube 留言
│   ├── build_absa_cache.py        # 離線 Naver + YouTube + KcELECTRA ABSA cache
│   ├── refresh_monthly_analysis.py # 按月份更新藝人分析
│   ├── import_kpop_items.py       # 將每日 MV、直拍與神圖資料匯入 Supabase kpop_items
│   ├── label_sentiments.py        # Gemini 標註留言情感
│   ├── preload_cache.py           # 預先產生藝人分析快取
│   └── start.sh                   # 本機 ngrok + Flask 啟動輔助
├── data/
│   ├── chart_history.db           # SQLite 榜單資料庫
│   ├── sample_comments.csv        # 留言情感資料
│   └── play_zone/                 # Play Zone CSV、JSON 與圖片素材
├── supabase/
│   ├── kpop_radar_schema.sql      # K-pop 口袋 Supabase schema
│   └── bot_sessions_schema.sql    # 對話狀態 bot_sessions 資料表
└── tests/
    ├── conftest.py                # 讓測試不讀 .env、不帶任何金鑰
    ├── fakes.py                   # 假依賴與 make_app() / make_deps()
    ├── golden/                    # golden master 快照
    └── test_*.py                  # pytest 測試
```

## 環境變數

可以從 `.env.example` 複製：

```bash
cp .env.example .env
```

主要設定：

| 變數 | 用途 | 必填 |
| --- | --- | --- |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot access token | 部署 LINE Bot 時必填 |
| `LINE_CHANNEL_SECRET` | LINE webhook 驗證 | 部署 LINE Bot 時必填 |
| `NAVER_CLIENT_ID` | Naver Search API client id | 有真實新聞資料時填 |
| `NAVER_CLIENT_SECRET` | Naver Search API secret | 有真實新聞資料時填 |
| `GEMINI_API_KEY` | Gemini API key | 使用 AI 生成時填 |
| `GEMINI_MODEL` | Gemini model name | 選填 |
| `YOUTUBE_API_KEY` | YouTube Data API key | 抓留言時填 |
| `SUPABASE_URL` | Supabase project URL | 啟用 K-pop 口袋、每日 MV 個人化與對話狀態保存時填 |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key | 同上 |
| `DATABASE_PATH` | SQLite 資料庫位置 | 預設可用 |
| `MOCK_DATA_DIR` | mock data 位置 | 預設可用 |
| `PORT` | Flask port | HF 使用 `7860` |
| `KPOP_AGENT_ENV_FILE` | 改讀其他 env 檔；設為空字串則不讀任何 env 檔（測試用） | 選填 |

若部分 API key 未設定，系統會使用 mock data 或本地 fallback，避免整個 Bot 中斷。

## 本機啟動

### 1. 安裝依賴

專案用 [uv](https://docs.astral.sh/uv/) 管理 Python 與依賴，以下指令會依 `.python-version` 準備 Python 3.13，並照 `uv.lock` 安裝執行期依賴和開發工具：

```bash
uv sync
```

新增依賴用 `uv add 套件名稱`（開發工具用 `uv add --dev`），會一併更新 `pyproject.toml` 和 `uv.lock`。

### 2. 初始化資料庫

```bash
uv run python scripts/init_db.py
uv run python scripts/seed_data.py
```

### 3. 啟動 Flask

```bash
uv run python app.py
```

本機預設 port 由 `.env` 的 `PORT` 決定，若未設定則使用 `5000`。

### 4. 健康檢查

```bash
curl http://127.0.0.1:5000/health
```

### 5. 測試分析 API

```bash
curl -X POST http://127.0.0.1:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"message":"分析 aespa"}'
```

## LINE Webhook

部署後，在 LINE Developers 後台將 webhook 指向：

```text
https://你的網域/webhook
```

若使用 Hugging Face Space，webhook URL 會是：

```text
https://EscA95103040126-kpop-agent.hf.space/webhook
```

本機測試可使用 `scripts/start.sh` 搭配 ngrok，啟動後將輸出的 public URL 設定到 LINE Developers。

## 常用資料更新指令

```bash
# 抓取 Bugs 週榜
uv run python scripts/fetch_bugs_chart.py

# 抓取指定週次 Bugs 週榜
uv run python scripts/fetch_bugs_chart.py --chart-date 2026-05-18

# 預先產生藝人 cache
uv run python scripts/preload_cache.py

# 抓取 YouTube 留言
uv run python scripts/fetch_youtube_comments.py

# 使用 Gemini 標註留言情感
uv run python scripts/label_sentiments.py

# 建立或更新 LINE Rich Menu
uv run python scripts/setup_rich_menu.py

# 匯入每日 MV、直拍與神圖資料到 Supabase kpop_items
uv run python scripts/import_kpop_items.py

# 僅檢查匯入資料數量，不寫入 Supabase
uv run python scripts/import_kpop_items.py --dry-run
```

## 測試與程式碼品質

```bash
uv run pytest                 # 測試
uv run pytest --cov           # 測試加覆蓋率（低於 65% 會失敗）
uv run ruff check .           # lint
uv run ruff format .          # 自動排版
```

GitHub Actions（`.github/workflows/ci.yml`）在每次 push 到 `main` 和每個 PR 上執行同樣的檢查，並把覆蓋率表格寫進 job summary。另一個 job 會實際 build Docker 映像檔、啟動 container 並打 `/health`，確認部署到 Hugging Face 的映像檔能跑起來。

全專案統一排版的 commit 記錄在 `.git-blame-ignore-revs`，執行下面這行之後，`git blame` 就會略過它：

```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

測試不會讀 `.env`，也不會連到任何外部服務：`tests/conftest.py` 會在載入設定前清掉所有金鑰，每個測試再用 `tests/fakes.py` 的 `make_app()` 建一個注入假依賴的 app。

`tests/test_characterization.py` 是 golden master 測試：同一組對話腳本會分別送進 LINE、`/analyze` 和 mock webhook，輸出要跟 `tests/golden/` 的快照完全一致。刻意改變行為時，用下面的指令更新快照，並在 commit 裡檢查 diff：

```bash
UPDATE_GOLDEN=1 pytest tests/test_characterization.py
```

目前測試涵蓋：

- 三個入口的 golden master 快照
- 路由表順序與 Dispatcher、LINE renderer
- 帶簽章的 LINE webhook 端到端流程（文字、postback、加好友、重送）
- Flask health check
- LINE webhook 去重與 debounce
- Router intent 判斷
- Bugs chart parser
- SQLite chart query
- Naver News fallback
- Sentiment classifier
- Play Zone、每日一首、本命雷達、認人測驗與抽卡流程
- K-pop 口袋、Supabase 每日 MV 推薦與收藏流程

## 技術棧

- Python 3.13
- Flask
- LINE Messaging API
- Gemini API
- Naver Search API
- YouTube Data API
- SQLite
- CSV / JSON cache
- Docker
- Hugging Face Spaces
- pytest、pytest-cov
- uv、ruff
- GitHub Actions

## 目前狀態

- 已部署至 Hugging Face Space
- 已整合 LINE webhook 與 Rich Menu
- 已完成藝人分析、榜單、新聞、情感分析與 Gemini insight
- 已完成 AI 入坑、每日一首、我的 K-pop 口袋、Play Zone 測驗與抽卡
- 已提供本地 fallback 與 mock data，方便無 API key 的展示與測試
