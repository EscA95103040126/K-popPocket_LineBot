# v5 第二次封存測試：事前登記

寫於 2026-10-28 23:55（台北），在第一次讀取 test2 分數之前。test2 只跑一次，跑完不再依結果調整任何參數。

## 背景

- 第一次封存測試（test，46 題）：重新訓練的 v5 編碼器在 strong hit@3 和 v4 打平（0.400），lenient hit@3 顯著退步（0.630 → 0.435，3 勝 12 敗，p=0.035）。進步只出現在長相題。test 已用掉。
- 因此上線候選改成「v4 照舊，只在長相題加上 v5 的訊號」，只用 dev（47 題）確認沒有壞掉。

## 受測版本

`scripts/evaluate_member_intent.py` 的 `v5`：

- 編碼器：v3 int8（`models/bge-m3-v3-int8/`，和 v4 相同）
- 長相題（解析成 `visual_similarity`，或問句有長相詞，例如「長相、長得、顏值、五官、臉」）：加上證據向量（EVIDENCE_WEIGHT 0.5）、參照成員文件相似度（1.0）和照片相似度（visual_similarity 1.5）
- 其他題目：和 v4 同樣的排序（不用證據、不混參照成員和照片）
- 資料：`data/curator/member_evidence.csv`（263 條，其中長相 68 條，sha256 開頭 7c73b820f23a337a）、`data/curator/member_photo_embeddings.npz`（154/154 位，未正規化平均，開頭 b7faf9a42533c604）、`models/bge-m3-v3-int8/member_embeddings.npz`（開頭 3451f8199e1f6cca）

dev 結果（對 v4）：strong hit@3 0.345 → 0.345、lenient hit@3 0.383 → 0.404、strong hit@10 0.552 → 0.621；只有 3 題前三名不同。

## 比較基準

v4：用 v5 之前的程式（git HEAD b48f1ca，v3 int8 編碼器）跑同樣 44 題。這段程式在 dev 上能逐題重現存檔的 v4 結果。

## 判定規則（事先決定）

`v5` 通過、可以部署，需要兩項都成立：

1. strong hit@3 不低於 v4。
2. lenient hit@3 沒有顯著退步：不能「輸的題數多於贏的題數，而且符號檢定 p < 0.05」。

另外會回報長相題（appearance、similar_to_member）的分數，因為 v5 只改這些題目，但不列入判定。`v5-retrained`（重新訓練的編碼器，同樣的長相規則）也會一起跑，只供參考，不論結果都不會換成它。

## 已知限制

- test2 50 題，有答案的 44 題，strong 28 題；長相相關 37 題（appearance 25、similar_to_member 12）。
- PTT 17 題的推薦人數是自動比對加人工抽查的近似值；X 有 2 串只讀了一部分，人數是下限。
- 照片的 face_visible 是 YuNet 自動判斷，只有一小部分人工看過。
