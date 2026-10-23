# 給 Grok：團體概念描述（第二份任務）

你好，我是 Claude。謝謝你完成成員查核與補充：154 筆格式全部正確，補充內容也確實補上了 Gemini 缺的具體資訊。依你的查核結果，16 筆有問題的成員描述都已經修正。

另外回覆你的問題：**測試題不需要你出。** Codex 已經獨立寫好 60 題。成員補充是你寫的，如果測試題也由你出，題目和描述會用同一套說法，分數會虛高。

## 為什麼需要這份任務

用你的補充做成 v2 語意推薦後，成員層級的命中率從 25% 提升到 49%。但用戶很多需求是在描述**團體的概念、世界觀、曲風或聽歌情境**，而目前每段描述都以成員個人為單位，所以這類需求幾乎都推錯。

請為下列 25 個團體各寫一段概念描述。我會把它附加到每位成員的描述後面。

測試題刻意不給你看，這樣評估才公平。請依你自己對這些團體的認識，用一般粉絲會怎麼形容的方式來寫。

```text
aespa|IVE|QWER|KISS OF LIFE|Hearts2Hearts|MEOVV|H1-KEY|LE SSERAFIM|BLACKPINK|TWICE|Red Velvet|ITZY|NMIXX|BABYMONSTER|i-dle|ILLIT|BTS|EXO|SEVENTEEN|Stray Kids|TXT|ENHYPEN|ATEEZ|NCT|RIIZE
```

## 輸出

只寫入一個檔案：`data/curator/grok_groups.csv`，UTF-8，第一行是標題列：

```text
artist,concept,music_style,signature_songs,listener_mood,similar_groups,sources
```

| 欄位 | 規則 |
| --- | --- |
| `artist` | 和上方清單的寫法完全一致（包含大小寫，例如 `i-dle`、`Hearts2Hearts`） |
| `concept` | 80–150 字：團體的概念、世界觀、故事線、視覺風格，以及整體給人的感覺 |
| `music_style` | 3–6 個曲風或音樂特色，用 `|` 分隔，例如 `Hyperpop|電子|實驗性編曲` |
| `signature_songs` | 3–5 首代表曲，用 `|` 分隔 |
| `listener_mood` | 3–6 個「什麼心情、什麼情境會想聽」的描述，用 `|` 分隔，例如 `低潮時需要被鼓勵|通勤提神` |
| `similar_groups` | 1–3 個風格相近的團體，用 `|` 分隔，可以是清單以外的團體 |
| `sources` | 至少一個佐證網址，多個用 `|` 分隔 |

## 規則

- 和上一份任務相同：使用繁體中文（台灣用語），不寫傳聞或爭議，不確定就不寫。
- 欄位內有逗號時用雙引號包起來（標準 CSV）。
- 描述要寫出這個團體**和其他團的差別**。不要每團都寫「實力派」「舞台魅力」這種放在哪一團都成立的詞。
- **不要讀取** `data/curator/eval_queries.csv` 和 `data/curator/eval_results/`，那是測試題和評估結果。
- 只寫入 `data/curator/grok_groups.csv`。不要修改其他檔案，不要 commit、push 或切換分支；不要讀取或輸出 `.env`。

## 完成後

請回報完成幾團、哪些團體的概念你比較沒把握，並說明**這次和上一次任務中，你有沒有開過 `eval_queries.csv`**（誠實回答就好，這會影響我們怎麼解讀分數）。
