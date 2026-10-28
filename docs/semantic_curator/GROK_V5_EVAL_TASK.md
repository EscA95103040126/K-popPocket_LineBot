# 給 Grok：v5 成員推坑評估集

更新日期：2026-10-28（台灣時間）。這份是可轉交的任務說明，由使用者轉給 Grok。

## 為什麼要做

AI 入坑是**幫使用者找到值得入坑的成員**，不是找歌。v4 之前用的真實需求題（`grok_real_requests*.csv`）有六成是「求類似某首歌的歌」，成員答案只是回覆剛好提到某人，量不出推坑成員的好壞。

v5 會用深度學習提高成員命中，但要先有一把對的尺：一批**真實粉絲在找「人」**的問句，答案是**其他粉絲在回覆裡推薦的成員**。這批資料只用來評估，不會拿來訓練。

## 要蒐集什麼

真實的公開貼文，發文者想找**某種成員**，例如：

- 特質：「想找溫柔又很會照顧人的男偶像」「有沒有個性大剌剌的女團成員」
- 聲線／舞台：「推薦聲音沙啞、很有辨識度的成員」「想找跳舞很有力量的女生」
- 綜藝感：「綜藝很好笑的 idol 推薦」
- 長相／外型類型：「想找小狗相的男生」「有沒有清冷貓系長相的女團成員」「喜歡濃顏、很有攻擊性的長相」
- 反差：「平常很呆萌、上台很帥的成員」
- 像某人：「我喜歡 MEOVV 的 ANNA，有沒有相似類型的推薦？」「喜歡 Karina 那種氣質，還有誰像她」「長得像 Wonyoung 那種的」「像 Felix 一樣低音很重的人」
- 混合條件：「男團、主唱、私下很搞笑」「長相清冷但個性很暖」

**不收**：

- 找歌、找專輯、找 MV、找曲風（「類似〈Supernova〉的歌」）。
- 只問團體、不問成員的（「推薦一個男團」）。發文者問團、但回覆幾乎都在推特定成員的，也不收，避免題意被改寫。
- 八卦、戀愛傳聞、私生活猜測。
- 長相題裡評論身材、整形猜測、性暗示的貼文或回覆；長相只收動物相、五官氣質、造型風格這類描述。

## 來源

優先順序不拘，但每個來源都要能公開存取、不需登入：

- Reddit：r/kpop、r/kpophelp、r/kpoprecs 等「idol recommendations」「idols like X」類貼文
- PTT（KoreaStar、KoreaDrama 板的推薦文）、Dcard 追星／韓星板
- 韓文社群（theqoo、instiz、Naver 지식iN），只用能公開讀取的頁面
- X 公開貼文的串文回覆

中文（含簡中轉寫為繁中）來源至少占三成。同一串最多取 3 題，避免一串主導整批。不遵守 robots.txt 的抓取方式不要用；讀不到就記在 research_log。

## 答案怎麼定

- 答案**只能來自原貼的回覆**，是其他粉絲實際推薦的成員；不要自己判斷誰符合，也不要用你之前整理的 `member_evidence_*`、persona、別名以外的資料來補答案。
- 只記錄成員目錄裡的 154 位（`data/play_zone/bias_radar_members.csv` 的 `id`）。回覆推薦了目錄外的人，記在 `out_of_catalog`，不要對應到目錄裡長得像或同名的人。
- 每位被推薦的成員記下**不同回覆者的人數**（同一人多則回覆只算一次）。我們之後會用人數決定門檻，你不用先篩。
- 同名成員（例如兩位 Jiwoo）要依回覆裡的團名或語境判定；判斷不了就記在 `out_of_catalog` 並註明歧義。
- 回覆裡如果有推薦理由，簡短記下（用繁中轉述，30 字內），方便之後檢查理由品質。

## 問句怎麼寫

- `original_request`：保留原文最能代表需求的一句或兩句，150 字以內，去除帳號、@提及與個人資訊。
- `query_zh`：把原文改寫成**使用者會直接傳給 LINE Bot 的一句繁體中文（台灣用語）**。保留原意與所有條件（性別、團、不要什麼），不加原文沒有的條件，不美化、不擴寫。原文已是繁中且像一句話時可以照抄。
- 不要自己編問句。每題都必須有真實來源。

## 交付格式

放在 `data/curator/staging/grok/member_intent_eval_v1/`，不覆寫任何既有檔案。

### requests.csv

`request_id,platform,source_language,thread_url,post_date,original_request,query_zh,intent_type,reference_member_ids,similar_aspect,gender,exclude_artists,reply_count_read,notes`

- `request_id`：`mi-0001` 起編，穩定不重用。
- `intent_type`：`trait`、`appearance`、`vocal`、`performance`、`variety`、`contrast`、`similar_to_member`、`mixed`，多個條件時用 `mixed` 並在 notes 列出。
- `reference_member_ids`：「像某人」的那位（可多位，以 `|` 分隔）；沒有就空白。
- `similar_aspect`：只在 `similar_to_member` 填，發文者想要哪方面相似：`appearance`、`vibe`、`vocal`、`performance`、`unspecified`（像 ANNA 那題只說「相似類型」）。依原文判斷，不要從回覆反推；原文沒說就填 `unspecified`。
- `gender`：`female`、`male` 或空白（原文沒說）。
- `exclude_artists`：原文明說不要的團，以 `|` 分隔。
- `reply_count_read`：你實際讀過的回覆數，讓我們知道答案的完整度。

### answers.csv

`request_id,member_id,recommender_count,reply_urls,reason_zh`

每列一位被推薦的成員。`reply_urls` 以 `;` 分隔，網址照留。

### out_of_catalog.csv

`request_id,name_as_written,recommender_count,reason`（`reason`：目錄外、同名歧義、無法辨識）

### data_dictionary.md、research_log.md

字典說明欄位與缺值寫法；日誌記錄搜尋關鍵字、讀過的串數、各來源讀取失敗、排除了哪些貼文與原因（找歌、只問團、身材或整形評論…各幾則）。

## 數量與分批

- **第一批先交 30 題**，涵蓋至少 4 種 intent_type、中英各有，讓我們先檢查格式和題意判斷。通過後再補到 **150～200 題**。
- 每種 intent_type 不超過全部的 40%。`appearance`、`contrast` 與 `similar_to_member` 各至少 15 題；`similar_to_member` 裡 `unspecified` 和 `appearance` 各至少 5 題。
- 至少一半的題目要有 2 位以上回覆者推薦的目錄內成員；全部答案都在目錄外的題目可以交，但另外標註，不計入 150 題。

## 隱私

延續 v1_11_clean 的規則：網址欄照留；其他欄位與 .md 不放任何帳號名稱、暱稱或 ID，改成「一位 Reddit 使用者」「一位 PTT 鄉民」這類通用寫法。

## 隔離規則

這批資料是用來考 Bot 的，所以：

- 不要讀取 `data/curator/eval_results/`、`eval_queries.csv`、`grok_real_requests*.csv`、`docs/semantic_curator/` 裡除了這份任務說明以外的結果與計畫文件，也不要看 Bot 的推薦結果或 demo。
- 不要用你整理過的成員證據去選題或補答案，題目和答案都只看原始貼文。
- 不要修改 Bot 程式、正式資料、測試、模型、分支或部署；不要讀取 `.env`。
- 交付後由 Claude 分成 dev／test，test 會封存，到 v5 最後只驗收一次。
