# 給 Grok：v5 長相觀感與成員照片

更新日期：2026-10-28（台灣時間）。這份是可轉交的任務說明，由使用者轉給 Grok。

## 為什麼要做

v5 要看得懂長相：「想找小狗相的男生」「長得像 ANNA 的類型」。我們分兩條路做：

- **文字**：粉絲對每位成員長相的共識，例如「粉絲常說他是小狗相」。用來回答描述型的長相問題。
- **照片**：每位成員幾張清楚的照片，在本機算成影像向量，用來回答「長得像某人」。照片不會放進 repo 或 Space，只上傳算好的向量。

兩條路都要涵蓋**全部 154 位**，照成員目錄依序做，不要挑人。

## A. 長相觀感（member_claims.csv）

格式和規則完全沿用 `member_evidence_v1_1` 的 `member_claims.csv`（欄位、perspective、source_count、aggregate_id、usable_for_persona 都一樣），只是 `facet` 一律填 `appearance`。

- 收：動物相（小狗、貓、狐狸、兔子、小鹿、熊…）、五官氣質（清冷、溫暖、濃顏、淡顏、少年感、明豔…）、造型風格的整體印象。
- 不收：身材、體重、整形猜測、性暗示、拿來比較誰比較好看的貶低說法。
- 一條主張只講一種長相類型。同一位成員粉絲說法分歧時，分成不同主張或標 `disputed`，不要合併成模糊的說法。
- 成立門檻同 v1_1：粉絲彙整列要有 **3 個以上獨立作者**才是 `supported`；單一來源列一律 `pending`。
- `value` 寫成「粉絲常說他是小狗相」「社群常形容她是清冷貓系長相」這種有歸屬的句子。
- 本命雷達裡現有的長相標籤（`bias_radar_members.csv` 的 `appearance` 欄）來源不明，**不能當證據**，也不要拿它當搜尋時的預設答案。

## B. 成員照片（photo_manifest.csv）

每位成員 **3～5 張**，只交網址與資訊，不用下載照片本身。

`member_id,image_url,source_page_url,source_type,era,face_visible,notes`

- `source_type`：`official`（經紀公司、官方帳號、官方網站）、`press`（媒體新聞照）、`broadcast`（官方節目截圖）。不收粉絲修圖、AI 生成圖、拼貼圖、表情包。
- `era`：拍攝或發布的年月，盡量用 2024–2026 年的近照；同一位成員的照片盡量來自不同活動。
- `face_visible`：正臉清楚、五官沒有被手、麥克風、口罩、大量文字遮住才填 `yes`。每位至少 3 張 `yes`。
- 一張照片只能有這位成員一人，團體照不收。
- `image_url` 要是可以直接下載的圖片網址；需要登入或會過期的網址不收。

## 交付

放在 `data/curator/staging/grok/appearance_v1/`：

- `member_claims.csv`
- `photo_manifest.csv`
- `coverage.csv`：154 位各有幾條 supported 長相主張、幾張可用照片
- `data_dictionary.md`、`research_log.md`

時間很緊（10/30 要完成 v5），請**先交前 40 位**（照目錄順序），再補其餘成員。

## 隱私與隔離

- 隱私同 v1_11_clean：網址照留；其他欄位與 .md 不放任何帳號名稱。
- 不要讀評估資料（`member_intent_eval_*`、`eval_results/`、`grok_real_requests*.csv`）來決定要整理誰或怎麼寫。
- 不要讀取 `.env`；不要修改 Bot 程式、正式資料、模型、分支或部署。
