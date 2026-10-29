# v4＋LLM 偏好解析：test3 事前登記

初版寫於 2026-10-29 12:20（台北），補充修訂於 12:33，都在 test3（Grok `member_intent_eval_v3_test3`，40 題）的題目和答案打開之前。只跑一次，跑完不依結果調整任何參數再報分。原登記 2026-10-30 執行，使用者要求改為 2026-10-29 執行（見修訂紀錄）。

開發期間對 test3 只做過三件事：確認 SEALED.md 的 sha256（六個檔案都 OK）、讀 `data_dictionary.md`（欄位說明和外貌子集題號）、從 `requests.csv` 只讀 `request_id`、`intent_type`、`similar_aspect` 三欄核對外貌子集（見下）。沒有讀過問句、答案和 out_of_catalog。

## 受測版本：`v4+pref`

1. v4 排序照舊：v3 int8 編碼器、v4 的別名表和意圖約束，不用 v5 的證據向量、照片和 visual_similarity。目前的程式關掉這些之後（`v4-now`），在 dev、test、test2 共 137 題上逐題和 v4 的存檔結果相同。
2. Gemini 把問句解析成偏好 JSON（`src/bot/preference.py`，提示詞 `pref-v3`，模型固定為 `gemini-3.1-flash-lite-preview`，temperature 0）。特質只能用 `data/curator/trait_tags.csv` 的 18 個 tag，每個 tag 的成員完全由 `member_evidence.csv` 裡有來源的主張決定；對應不到的說法不參與排序。
3. 重排：v4 分數標準化後，符合正向特質的成員加 2.0 × 程度（high 1.0、mid 0.6、low 0.3），符合否定特質的扣 1.0 × 程度（往後排，不刪除）；排除 exclude_artists 的團和參照成員本人；性別不合的往後排。
4. 評分只讀快取（`data/curator/llm_pref_cache.json`），不即時呼叫模型。

權重在 dev＋test＋test2（137 題，外貌 80 題）上選：外貌子集 lenient hit@3 0.325 → 0.400（9 勝 3 敗），整體 strong hit@3 0.333 → 0.333（4 勝 4 敗）。練習集 60 句（扣掉當範例的 pp-0002）：性別 90%、參照成員完全相同 97%、特質 precision 0.82、recall 0.88。

輸入：兩個系統都用 `query_zh`（台灣繁體改寫），和之前所有評估相同。

### 凍結的檔案（sha256 前 16 碼，12:33 版）

| 檔案 | sha256 |
|---|---|
| src/bot/preference.py | 615a8a9ecd1ec929 |
| src/bot/semantic_index.py | 7efd62e07bb09554 |
| src/bot/curator_query.py | 1bc80559c23b1bfe |
| src/bot/container.py | bb65d67c34dd0749 |
| data/curator/trait_tags.csv | 624eb52b0fe12223 |
| data/curator/member_evidence.csv | 7c73b820f23a337a |
| data/curator/grok_aliases.csv | 0b79fbefc89a7339 |
| data/curator/member_profiles.csv | 812b69aa675eb4ab |
| data/curator/llm_pref_cache.json（解析 test3 之前） | cab210966776d0f6 |
| models/bge-m3-v3-int8/model.onnx | a32a07d8372bb3ec |
| models/bge-m3-v3-int8/member_embeddings.npz | 3451f8199e1f6cca |
| scripts/evaluate_member_intent.py | 00d293b33ea4ee9e |
| scripts/parse_preferences.py | d4c21474c4ac9c03 |

v4 的程式版本：git `b48f1ca`（v5 之前的 HEAD）。

## 比較基準

同一次執行裡算 `v4-now`；另外用 `b48f1ca` 的 worktree 跑一次 v4，兩者逐題要相同（不同就以 `b48f1ca` 為準，並記錄差異）。

## 通過標準（Grok 交接說明的建議，原樣採用）

兩項都要成立：

1. 外貌子集的 hit@3（前三名至少命中一位 answers.csv 的成員，即 lenient hit@3）**高於** v4。
2. 全體 strong hit@3（只算 recommender_count ≥ 2 的答案）**不低於** v4。

符號檢定 p 值一併回報，但不列入判定。

### 排除的題目

t3-0024 沒有目錄內答案，從所有 hit@3 計算（外貌子集和全體）中排除。評分程式本來就只算有目錄內答案的題目，執行時會確認被排除的只有這一題。

### 外貌子集

以 Grok `data_dictionary.md` 列的 32 題 ID 為準：t3-0001～0019、0022～0029、0031、0033、0035、0037、0040。

評分程式的篩法（intent_type 是 appearance／similar_to_member，或 similar_aspect 是 appearance／vibe／styling）在 12:33 核對過，篩出的 32 題和這份清單完全相同，沒有差異。扣掉 t3-0024 後外貌子集是 31 題。

## 執行步驟（2026-10-29 執行，原登記 10/30）

1. 用 SEALED.md 確認六個檔案的 sha256，再確認上表凍結檔案的 sha256 沒變。
2. 把 requests.csv、answers.csv 複製成 `data/curator/member_intent/test3_{requests,answers}.csv`。
3. `uv run python scripts/parse_preferences.py --split test3 --final`：網路錯誤的句子重跑到全部解析完；真的解析不出來的那題照 v4 排序。記下解析後快取的 sha256。
4. `uv run --group curator python scripts/evaluate_member_intent.py v4-now v4+pref --split test3 --final`，再用 `b48f1ca` 的 worktree 跑 v4 對照。
5. 結果寫進 `RESULTS_v5.md`，不論通過與否。

## 已知限制

- **權重不是在乾淨的資料上調的。** 加分和扣分是在 dev、test、test2 共 137 題上選的；test 和 test2 都已經跑過封存測試，看過結果，不再是乾淨的測試集。test3 是唯一沒看過的資料。
- **測不到直接讀韓文的能力。** 兩個系統都吃 `query_zh`（中文改寫）。test3 有 67.5% 的題目來自韓文的 Naver 知識iN，但評分用的是改寫後的中文；解析器讀韓文原句的表現只在練習集上量過（見上），不會反映在 test3 的分數上。
- 40 題、外貌子集 31 題：差 1 題就會改變判定，p 值不會顯著。
- 推薦人數是下限（PTT 自動比對、X 只讀到部分回覆）。
- 否定扣分沒有資料可調；test3 有 9 題含否定。

## 修訂紀錄

12:33：

- 補上 t3-0024 的排除和外貌子集的核對結果（以 Grok 清單為準，兩者相同）。
- 偏好解析的模型固定為 `gemini-3.1-flash-lite-preview`（`PREFERENCE_MODEL`），不跟著 `GEMINI_MODEL` 換：換金鑰時 `.env` 的 `GEMINI_MODEL` 變成 `gemini-3.8-flash`，這個模型本機連一個字的回覆都逾時，而練習集和權重都是用 flash-lite 的解析結果調的。因此 `preference.py`、`container.py`、`parse_preferences.py` 的 sha256 更新。排序邏輯、提示詞和權重都沒變。
- 快取檔含粉絲原文片段（`raw` 欄位），加進 `.gitignore`，只留在本機重現評估；bot 執行時沒有快取檔也能運作。
- 限制補上權重的調整範圍和 `query_zh` 的說明。

12:37：

- 使用者要求執行日從 2026-10-30 改為 2026-10-29。版本、凍結檔案的 sha256、通過標準和排除規則都不變。
- 同時 `GEMINI_MODEL` 改成 `gemini-3.5-flash-lite`（bot 產生回覆用）。偏好解析照登記固定在 `gemini-3.1-flash-lite-preview`，不受影響。
