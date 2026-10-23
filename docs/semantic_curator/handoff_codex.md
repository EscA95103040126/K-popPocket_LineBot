# 給 Codex：撰寫評估用測試題

你好，我是負責這個專案主要實作的 Claude。請先讀 `docs/semantic_curator/PLAN.md` 了解全貌。這份文件是你目前的任務；程式審查和微調腳本之後會另外交接。

專案路徑：`~/Documents/KPOP Agent/kpop-agent`（git 分支 `feature/semantic-curator`）

## 背景

LINE Bot 的「AI 入坑」功能讓用戶用一句話描述喜好，Bot 推薦 K-pop 成員。我們要比較舊版（固定標籤比對）和新版（語意向量比對）誰推薦得比較準，需要一份獨立的測試題。

**獨立**是重點：成員描述由 Gemini 和 Grok 撰寫，如果出題時參考那些描述，題目會和描述用同一套說法，新版的分數會虛高。

## 可以讀與不能讀

- 可以讀 `data/play_zone/bias_radar_members.csv`，但只用 `id`、`artist`、`member`、`gender_group` 四欄來對答案。不要參考其他欄位的標籤來出題。
- 不要讀 `data/curator/` 底下除了你自己輸出檔以外的檔案。
- 出題依據你自己對這些成員的認識。

## 輸出

只寫入一個檔案：`data/curator/eval_queries.csv`，UTF-8，第一行是標題列：

```text
qid,query,expected_ids,expected_artists,type
```

| 欄位 | 規則 |
| --- | --- |
| `qid` | `q001` 起編號 |
| `query` | 一般粉絲或新手會在 LINE 輸入的一句話，口語、長短不一，有些可以有錯字或中英混用 |
| `expected_ids` | 合理答案的成員 `id`，1–5 個，用 `|` 分隔；必須存在於 `bias_radar_members.csv` |
| `expected_artists` | 合理答案的團體名稱，用 `|` 分隔，寫法和 CSV 的 `artist` 一致；題目只問團體時只填這欄 |
| `type` | 見下表 |

共 60 題，類型分配：

| `type` | 題數 | 說明 | 例子 |
| --- | --- | --- | --- |
| `tag` | 15 | 用常見形容就講得出來的需求 | 我想找舞跳很好、氣場很強的女團成員 |
| `open` | 20 | 抽象、氛圍、情境型說法 | 想找聽起來很 chill、適合深夜開車聽的男團 |
| `reference` | 15 | 拿其他藝人或作品比較 | 有沒有跟 Jennie 一樣很有時尚感的人 |
| `negation` | 10 | 含有排除條件 | 喜歡女團但不要太甜太可愛的 |

## 規則

- 使用繁體中文（台灣用語）。
- 答案寧缺勿濫：只放你有把握、大多數粉絲也會同意的答案。
- 男團、女團、不同團體盡量分散，不要集中在少數幾團。
- 欄位內有逗號時用雙引號包起來（標準 CSV）。
- 只寫入 `data/curator/eval_queries.csv`。不要修改其他檔案，不要 commit、push 或切換分支。
- 不要讀取或輸出 `.env` 的內容。

## 完成後

請回報：各類型題數，以及哪些題目的答案你比較沒把握。
