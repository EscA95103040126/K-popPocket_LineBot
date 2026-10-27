# Grok staging 第一批補件規格

> 已於 2026-10-26 被 `GROK_V4_MEMBER_TASK.md` 取代。本文件僅保留歷史紀錄；停止執行歌曲配額與歌曲擴充要求。

目標仍是歌曲主線；不要為了湊 347 首的欄位覆蓋而補推論。保留原始 CSV，另交新增的查核檔與修訂紀錄。本文件不含評估題、demo 原句或排名結果；研究者不得讀取評估資料。未代替使用者發送給任何外部 Agent。

## 先完成 25 團各三首的核心證據

先查核歌曲的 `genre` 與 `sound_features`，其餘欄位可維持 `insufficient_evidence`。已有兩欄的 62 首待查核候選見 `staging_audit.json` 的 `pilot_candidates`；候選順序只依輸入檔案，不代表都通過或一定最具代表性。可由研究者依正式作品、可靠描述來源獨立調整選樣，但不能看評估題決定。

同一首同時有兩核心欄位的覆蓋不足團體：ATEEZ、BABYMONSTER、ENHYPEN、Hearts2Hearts、ILLIT 各缺至少一首；KISS OF LIFE 缺兩首；H1-KEY、QWER 各缺三首。若找不到三首有足夠編曲來源，照實標缺漏，不以聽感或歌名填滿。

每個主張一列，新增 `claim_evidence.csv`，至少包含：

`claim_id,entity_type,entity_id,field,value,source_url,source_title,source_type,original_source_url,source_subject,section_or_locator,evidence_excerpt_or_summary,support_type,verification_status,accessed_at`

- `entity_id` 沿用 song_id 或 member id；`field` 指明支援哪一欄，不能把整頁 URL 當作所有欄位的共同證明。
- `source_subject` 要寫來源段落正在談的曲目／人物；同篇新聞談多首歌時，保留該主張究竟屬於哪首的證據。
- 短摘控制在必要範圍，或寫可定位的摘要；需要看得到前後主詞，不能只留關鍵字。
- `support_type` 區分直接描述、二手轉述、研究者推論；推論不標 verified、不進肯定推薦理由。
- 媒體經由 Wikipedia／粉絲站轉述時，填原始來源或明標二手轉述；不要把來源頁類型與原始消息類型混為一欄。
- `verification_status` 分成 pending／supported／unsupported／disputed；「網頁可開啟」另外記錄，不等於 supported。

## 請釐清的資料問題

1. aespa〈Black Mamba〉的冬季／冬天，是否把成員 Winter 當季節？沒有直接情境證據就移除該主張。
2. aespa〈Supernova〉「搖滾吶喊」需給出確實談該曲的段落；找不到就改為不足。
3. IVE〈Supernova Love〉的節慶／聖誕節，不能只用取樣曲名 Christmas 或 12/24 MV 發表日期支持。
4. KARINA、SEHUN 的反差項目目前是研究者比較，不是來源直接說法，應更正 support_type 或補直接證據。
5. Persona 六列 press 的資料需釐清直接來源／二手轉述層級；不要只改整列 confidence 來處理。
6. 反差另加 `contrast_axis`：私下／舞台、外貌／個性、綜藝／私下等，避免不同反差面向互換。

## 不需擴大範圍

不新增長相／造型研究，不追求填滿所有缺值，不新增沒有來源的相似歌曲；氣質、舞台、聲線既有關係也需依同樣欄位標示證據。先把小批資料做到能驗證，再擴到每團 4–5 首。

補齊 `data_dictionary.md` 的 songs／persona 定義，以及本批的 `research_log.md`：查核過的主張、無法讀取頁面、撤回欄位、尚缺的團體與來源。不讀或修改任何正式 CSV、評估檔案或評估結果。
