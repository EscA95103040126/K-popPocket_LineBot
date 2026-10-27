# 給 Grok：v4 改以人物推薦為核心

更新日期：2026-10-26。此任務取代歌曲補滿、歌曲爬取與第一批 75 首的要求。舊成果保留，不刪除、不覆寫。這份文件是可轉交的任務說明，尚未代替使用者傳送給 Grok。

## 目標

讓系統能根據使用者喜歡的氣質、個性、綜藝互動、舞台或聲線，推薦有證據支持的成員，並說明符合與不足之處。請整理「人物特質與證據」，不再以整團歌曲資料的完整度為目標。

## 先停止的工作

- 不再擴大歌曲爬取，不補滿 25 團各三首或 3–5 首的配額，不繼續替整批歌曲補曲風、編曲、情境。
- 不做長相／造型相似、圖片向量或相關關係擴充。
- 保留既有歌曲 pipeline、CSV、快取規則與失敗紀錄；不得刪除，也不必為本任務重跑。

## 第一階段：整理既有成員資料

1. 盤點現有 154 位成員的 Persona 與逐條 claim，使用現有穩定 member_id。以既有 `grok_persona_v2.csv`、`claim_evidence.csv` 及修訂紀錄為起點，不把上一版 supported 當成不可更動的結論。
2. 把每條主張對回具體面向：`vibe`（被描述的氣質）、`offstage_public`（公開自述或互動）、`variety`、`performance`、`vocal`、`contrast`。
3. 逐條檢查形容是否超出原文。節目效果、特定時期或特定場合要保留情境；「參加綜藝」不等於「某種搞笑方式」，「外貌清冷」不等於「個性安靜」，團體音樂也不等於每位成員聲線。
4. 顯示 pending／unsupported／disputed，不為填滿表格補想像。缺少證據只表示目前不能肯定，不表示此人一定沒有該特質。
5. 優先依資料缺漏、原文可定位程度及面向覆蓋，獨立選約 12–20 位、多團的小批交付。不要依 Bot 結果、使用者案例、理想答案或評估題選人；如果只能核實更少位，也先交可驗證的部分。

不重寫 154 篇華麗人格簡介，不要求人人都有反差、舞台強或綜藝感。先把已有證據整理到能直接驗證與引用，再針對真正缺口搜尋。

## 第二階段：有需要才補來源

優先本人或團員公開訪談、官方節目／幕後／演唱／直拍、可定位的原始媒體評述；粉絲維護站可以作線索或明標社群感知，不冒充官方共識。重用既有下載與快取程式即可，不另建全韓網大規模爬取工程。

每次補資料需保留原文所在段落、主詞、時間、情境與來源層級；訪談轉引要追原始來源，追不到就保留二手狀態。影片只能記錄實際確認的標題、網址與時間點；找不到時間點可空，不杜撰。只依允許公開存取的來源工作，抓不到就記錄失敗。

歌曲／舞台只在能支持「某位成員的聲音或表演」時收錄，不從整團曲風推導個人成員。入口片段須能展現已核實的特質，沒有就留空，不用隨機 MV 當人格證據。

## 反差的特別規則

- 明確記錄軸線，例如 `offstage_vs_performance`、`appearance_vs_personality`、`variety_vs_offstage`；不同軸線不混用。
- 來源直接比較時，保留原文及兩面指向，才能把「來源談反差」標為 supported。
- 只有兩面各有證據、來源未直接比較時，分別交付兩個主張；不要自行新增 supported 的反差主張。是否以保守推論推薦由 Codex 另行實驗，必須明示推論。
- 不把「冷／暖」「認真／搞笑」等詞共現當成反差，不預設哪些人一定符合。

## 第一批交付格式

新增資料放 `data/curator/staging/grok/member_evidence_v1/`。原始正式 CSV 與既有 staging 批次不覆寫。這是資料批次名稱，不是 Bot 的 v5 版本。

### member_claims.csv

每列只表達一位成員、一個面向的一項主張：

`claim_id,member_id,facet,value,claim_kind,context_or_era,source_url,original_source_url,source_title,source_type,source_subject,section_or_timestamp,original_excerpt,evidence_summary_zh,support_type,verification_status,accessed_at,notes`

- `claim_id` 穩定且唯一，修訂時保留原 claim 的對應。
- `claim_kind` 區分公開自述、他人描述、具體行為、社群主觀感知；不要都包成客觀人格。
- `value` 短而精確，原文與中文摘要分欄，保留必要主詞及否定／限定語。短摘只留查核所需範圍。
- `support_type` 區分 direct／secondhand／inference。網頁可開啟另列，不等於 supported。
- `verification_status` 沿用 supported／pending／unsupported／disputed；supported 是你的研究判定，還要經 Codex 匯入驗證。
- 沒有確定的資料使用 insufficient_evidence 或規範的缺值，不混寫肯定形容。

### persona_review.csv

`member_id,previous_claim_id,previous_text,decision,replacement_claim_ids,reason`

`decision` 使用 keep／narrow／withdraw／pending，清楚指出舊描述哪些保留、哪些縮小語意、撤回或待查。只判斷是否被來源支持，不按推薦效果改資料。

### contrast_evidence.csv

僅列確有直接比較的資料：

`contrast_id,member_id,contrast_axis,side_a_claim_ids,side_b_claim_ids,comparison_claim_id,verification_status,notes`

如果第一批沒有直接反差證據，可交只有表頭的檔案並說明，不湊數。

### member_entry_points.csv（有現成資料才交）

`entry_id,member_id,facet,claim_ids,title,url,timestamp_or_section,why_this_entry,accessed_at`

每位先少量、與人物特質相關的公開入口即可。它不是歌曲曲風資料庫；沒有可用片段不阻塞主張交付。

### coverage.csv、data_dictionary.md、research_log.md

coverage 需列出 154 位哪些面向已具備可查證主張、哪些只有二手／社群、哪些缺資料，以及第一批選樣理由。字典說明缺值、狀態與 ID；日誌記錄新增／撤回主張、搜尋與讀取失敗，並列出仍無法支持的內容。

## 驗收方式與分工

任意抽一列，Codex 應能由 member_id → facet → 原文主詞與限定語 → 定位來源，理解它支持什麼、不能支持什麼。資料可分批通過，不以人數、網址數或 supported 比例當作正確率。

Grok 負責研究、來源定位、語意整理、研究狀態與缺漏；Codex 負責匯入驗證、人物意圖、分面檢索、推薦理由與評估。沒有授權你修改 Bot 程式、正式資料、測試、模型、分支或部署。

**隔離規則**：不要讀取或修改 `eval_queries.csv`、`grok_real_requests*.csv`、任何 real-dev／test、eval_results、demo、排名與答案；不要讀整份工程計畫、交接或結果報告來挑人物，這份任務已提供所需研究範圍。只讀成員目錄、既有描述、staging 人物資料與公開來源。不接觸 `.env` 或輸出金鑰。

先交第一批資料與可核實例子，不用等 154 位全補齊；也不要回到歌曲配額。Codex 會另行驗證，supported 不自動代表正式採用。
