# 給 Grok：成員描述查核與補充

你好，我是負責這個專案主要實作的 Claude。請先讀 `docs/semantic_curator/PLAN.md` 了解全貌。這份文件是你的任務。

專案路徑：`~/Documents/KPOP Agent/kpop-agent`（git 分支 `feature/semantic-curator`）

## 背景

LINE Bot 的「AI 入坑」要改成語意推薦：每位成員有一段描述，系統比較用戶的話和描述的相似度來推薦。描述的基礎版本由 Gemini 依 kprofiles 摘錄和既有標籤生成，在 `data/curator/member_profiles.csv`，共 154 位成員。

Gemini 的知識可能過時或出錯，而且描述偏保守。你熟悉 X 上的即時資訊和粉絲用語，所以請你負責兩件事：

1. **查核**：Gemini 寫的 `profile` 有沒有事實錯誤。
2. **補充**：Gemini 沒寫到、但粉絲找人時會用到的資訊。

## 最需要你補的東西

Claude 抽查後發現，Gemini 的描述大多只是把既有標籤換句話說：「反差萌」出現在 85 位成員、「白月光」50 位、「神性」59 位，「作詞」「作曲」「吉他」一次都沒出現，QWER 是樂團卻沒提到樂器。這樣推薦系統分不出成員之間的差別。

所以 `enrichment` 請優先寫**能區分這位成員和別人**的具體資訊：

- 音色與唱腔：低沉、沙啞、清亮、氣聲、R&B 轉音
- 舞蹈風格：力量型、柔軟延伸、Hip-hop、現代舞底子
- 創作與樂器：作詞作曲、製作、彈吉他、打鼓
- 代表舞台、個人作品或角色
- 綜藝與私下形象，以及團體的音樂風格或世界觀

請**避免**再用「白月光」「神性」「氛圍感」「反差萌」「清冷感」這類 Gemini 已經大量使用的詞，除非真的是這位成員最主要的特色。

## 輸入

- `data/curator/member_profiles.csv`：Gemini 的描述（欄位見 PLAN.md）
- `data/play_zone/bias_radar_members.csv`：成員清單和既有標籤，只讀

## 輸出

只寫入一個檔案：`data/curator/grok_enrichment.csv`，UTF-8，第一行是標題列：

```text
id,verdict,issue,enrichment,similar_to,fan_terms,sources
```

| 欄位 | 規則 |
| --- | --- |
| `id` | 必須和 `member_profiles.csv` 的 `id` 完全一致 |
| `verdict` | `ok`、`minor_issue`、`wrong` 三選一 |
| `issue` | `verdict` 不是 `ok` 時，寫出哪一句錯、正確應該是什麼；`ok` 時留空 |
| `enrichment` | 60–120 字補充，例如：代表舞台或作品、粉絲常用的暱稱與形容、近期形象轉變。不要重複 `profile` 已經寫的內容 |
| `similar_to` | 1–4 個風格相近的成員或團體，用 `|` 分隔，例如 `IVE WONYOUNG|NewJeans` |
| `fan_terms` | 3–8 個粉絲描述這位成員時常用的詞，用 `|` 分隔 |
| `sources` | 至少一個佐證網址，多個用 `|` 分隔 |

範例：

```text
id,verdict,issue,enrichment,similar_to,fan_terms,sources
aespa-karina,ok,,以 Supernova、Whiplash 等舞台展現強烈的未來感與控場力，舞台上冷冽、私下反差可愛，常被粉絲稱為「AI 臉」「人間 Karina」。,IVE WONYOUNG|ITZY YEJI,AI臉|控場|冷艷|反差萌,https://kprofiles.com/aespa-profile/
```

## 規則

- 使用繁體中文（台灣用語），不要使用簡體字或中國用語。
- 欄位內有逗號時，整個欄位用雙引號包起來（標準 CSV）。
- 不確定的事寫進 `issue` 或乾脆不寫，不要猜。不要寫戀愛傳聞、爭議事件、私生活。
- 可以分批做：每次處理一個或幾個團體，直接附加到檔案後面；已經有的 `id` 不要重複寫。
- 只寫入 `data/curator/grok_enrichment.csv`。不要修改其他檔案，不要 commit、push 或切換分支。
- 不要讀取或輸出 `.env` 的內容。

## 完成後

請回報：處理了幾位成員、`verdict` 各有幾筆、哪些成員你特別沒把握。
