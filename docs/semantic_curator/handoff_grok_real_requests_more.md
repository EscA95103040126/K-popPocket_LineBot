# 給 Grok：擴充真實「求推坑」資料（第二輪）

你好，我是 Claude。謝謝你整理的 167 組真實需求，格式和隱私處理都很好，也謝謝你主動說明資料的限制。

這一輪的目標很明確：**多找近幾年、而且推薦落在 Bot 清單內的資料**。如果你還在做團體概念和成員粉絲用語，請先把那兩項完成，再開始這一輪。

## 上一輪的問題

| 問題 | 上一輪 | 這一輪的目標 |
| --- | --- | --- |
| 年份 | 大多是 2015–2018 年 | **2022 年以後為主**（aespa、IVE、LE SSERAFIM、ILLIT 等團多半在這之後才出道或走紅） |
| 推薦是否在清單內 | 只有 93 / 167 組 | **至少 60% 的資料，推薦裡有清單內的團或成員** |
| 來源 | 151 組來自 PTT | 分散到下面列出的來源 |
| 數量 | 167 組 | **再新增 300 組以上** |

Bot 的 25 團清單（填答案時請用這個寫法）：

```text
aespa|IVE|QWER|KISS OF LIFE|Hearts2Hearts|MEOVV|H1-KEY|LE SSERAFIM|BLACKPINK|TWICE|Red Velvet|ITZY|NMIXX|BABYMONSTER|i-dle|ILLIT|BTS|EXO|SEVENTEEN|Stray Kids|TXT|ENHYPEN|ATEEZ|NCT|RIIZE
```

## 建議的來源與搜尋方式

**不限中文。** 英文和韓文的需求同樣有用，改寫成繁體中文即可，這是擴大數量最有效的方法。

| 來源 | 為什麼值得找 | 搜尋方向（僅供參考） |
| --- | --- | --- |
| Reddit（r/kpophelp、r/kpop、r/kpoprecommendations 等） | 推薦文多、年份新、回覆常提到清單內的團 | `looking for groups like`、`recommend me kpop`、`new to kpop`、`songs similar to` |
| X | 你最熟悉，也有近期資料 | `求推坑`、`入坑推薦`、`像 aespa 的女團`、`kpop recs`、`입덕 추천` |
| PTT KoreaStar 版 | 繁中、台灣用語 | 只找 **2022 年以後**的推坑文 |
| 韓國社群（theqoo、Instiz、NamuWiki 討論等） | 韓國粉絲的說法和台灣不同，能增加多樣性 | `입덕 추천`、`비슷한 그룹 추천` |
| YouTube 或其他論壇 | 補充用 | 需求和回覆要能明確對應 |

搜尋時**以清單內的團名當關鍵字**最有效，例如「like ENHYPEN」「aespa 같은 그룹」。這樣找到的回覆，比較可能推薦清單內的團。

## 輸出

寫入**新檔案** `data/curator/grok_real_requests_more.csv`，不要修改上一輪的 `grok_real_requests.csv`。UTF-8，第一行是標題列：

```text
req_id,platform,source_language,request,recommended_groups,recommended_members,request_type,post_period
```

| 欄位 | 規則 |
| --- | --- |
| `req_id` | 從 `m001` 開始編號，不要和上一輪的 `r001` 起的編號重複 |
| `platform` | `Reddit`、`X`、`PTT`、`theqoo`、`Instiz`、`YouTube`、`其他` |
| `source_language` | 原文語言：`zh`、`en`、`ko`、`ja`、`其他` |
| `request` | 用繁體中文（台灣用語）**改寫**的需求，保留原本的語氣和具體細節，例如提到的歌名、形容詞、情境 |
| `recommended_groups` | 回覆中推薦的團體，用 `|` 分隔。清單內的團請用上面的寫法，清單外的照常寫 |
| `recommended_members` | 回覆中推薦的特定成員，格式 `團名 成員名`，用 `|` 分隔；沒有就留空 |
| `request_type` | 和上一輪相同：`曲風`、`抽象氛圍`、`聲音/唱腔`、`舞台/舞蹈`、`具體成員參照`、`綜藝/個性`、`其他` |
| `post_period` | 貼文年月，格式 `YYYY-MM`；只知道年份就寫 `YYYY` |

## 規則

**資料品質**
- 一篇貼文只記一組，同一篇不要拆成多組。
- 不要和上一輪重複，也不要收錄重複轉貼的同一則需求。
- 回覆裡沒有任何具體推薦的貼文，不要收錄。
- 推薦要來自**其他人的回覆**，不是發文者自己舉的例子。

**隱私與著作權**
- 只記錄改寫後的需求和推薦名單。不要抄原文，不要記錄使用者名稱、個別貼文連結或任何能辨識發文者的資訊。

**獨立性與檔案權限**
- 不要讀取 `data/curator/eval_queries.csv` 和 `data/curator/eval_results/`。
- 只寫入 `data/curator/grok_real_requests_more.csv`。不要修改其他檔案，不要 commit、push 或切換分支；不要讀取或輸出 `.env`。

## 完成後

請回報：
- 新增幾組
- 依來源、語言、年份的分布
- 推薦落在清單內的比例
- 哪些來源讀不到或資料品質不好
