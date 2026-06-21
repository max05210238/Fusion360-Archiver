# 交接文檔：批次下載整個 Fusion 360 帳號的「原生檔」

> 給 Claude Code 的完整任務簡報。目標明確、限制已查證、含兩條技術路線與驗收標準。
> 讀完直接開工，不需回頭問需求。

---

## 1. 目標

把使用者 Autodesk / Fusion 360 帳號裡的**所有原生 Fusion 檔**完整下載到本機備份。

- 範圍：active hub 內**所有專案**（數十個）＋各專案下所有資料夾＋散落的 one-off 設計，總量 **100+ 檔**。
- 只要**原生格式**（`.f3d` / `.f3z`）。不需要 STEP/STL/IGES 等中性格式。
- 本機輸出保留「專案 / 資料夾」結構。
- 全程盡量無人值守（hands-off）。跑完要有一份 log 清楚標示成功 / 跳過 / 失敗 / 需手動處理。

---

## 2. 必讀限制（已查證，會決定架構）

這幾條是硬限制，不是實作細節，請先吸收再選路線：

1. **Fusion 沒有原生的 UI 批次匯出。** 官方 UI 一次只能逐檔處理，社群一律靠腳本/API。
2. **Fusion 內建 API（`adsk.*`）無法匯出含外部參照的組立件原生檔。**
   - 含 linked components 的檔，Fusion 只給 `.f3z`，不給 `.f3d`；而 **API 連 `.f3z` 都無法產生**。
   - 也就是說：`createFusionArchiveExportOptions()` 對「單體設計（無外部參照）」可行，對「組立件」必然失敗或被迫跳過。
   - 來源：
     - https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Unable-to-export-Fusion-360-model-in-f3d-format-when-only-f3z-file-format-is-offered.html
     - https://github.com/WilkoV/Fusion360_ExportIt （README：API exports cannot contain linked components；無法產生 f3z）
3. **取得帶所有連結零件的原生組立檔，官方途徑是 Data Panel 對最上層檔「Download」→ 產生 `.f3z`。** 這是雲端/手動動作，非 `adsk.*` API。
   - 來源：https://forums.autodesk.com/t5/fusion-360-ideastation-archived/export-assemblies-with-referenced-parts-in-f3d/idi-p/8358860
4. **所有檔都在雲端**，每開一個檔都是一次雲端抓取，100+ 檔可能要 1–3 小時；要設計成可長時間穩定執行、單檔失敗不中斷全局。

> 結論：**單一條路線無法 100% 自動拿到全部原生檔。** 必須分流處理「單體設計」與「組立件」。

---

## 3. 兩條技術路線

### 路線 A — Fusion 內 Python 腳本（已知可行，但只覆蓋單體設計）

- 形式：在 Fusion 內以 **Script** 執行（`adsk.core` / `adsk.fusion`）。
- 能做：迭代所有專案 → 遞迴所有資料夾 → 對每個 `.f3d` 設計呼叫 `createFusionArchiveExportOptions` 匯出原生 f3d，保留結構。
- **不能做：含外部參照的組立件**（受第 2 節限制）。對這類檔，腳本必須**偵測 `activeDocument.allDocumentReferences.count > 0` 並記入「需手動下載」清單**，不要假裝成功。
- 既有起點腳本（已寫好，可直接改）：見隨附 `Fusion_Batch_Export_All.py`。需要的修改：
  - 匯出格式只留 f3d。
  - 對有外部參照者，寫入 `needs_manual_f3z` 清單（含專案/資料夾路徑），最後輸出成 `manual_download_list.txt`。
- 限制：必須在 Fusion GUI 內手動觸發執行，無法由 Claude Code 直接 headless 驅動。Claude Code 的角色是把腳本改好交付 + 產生操作說明。

### 路線 B — APS（Autodesk Platform Services / 舊稱 Forge）資料管理 REST API（可全自動，含組立件，但需驗證個人 hub 權限）

- 形式：純 REST，Claude Code 可在本機 headless 跑完整個流程，這是最「hands-off」的路線，也是**唯一可能自動拿到組立件原生檔**的路線。
- 高層流程：
  1. 在 https://aps.autodesk.com 註冊一個 App，拿 **Client ID / Secret**。
  2. **3-legged OAuth（Authorization Code flow）**，scope 至少 `data:read account:read`。
     ⚠️ 個人 hub（My Hub / Personal）資料**必須用 3-legged（使用者授權）**，2-legged 拿不到。
  3. 遍歷資料結構：
     - `GET /project/v1/hubs` → 列出 hubs
     - `GET /project/v1/hubs/{hub_id}/projects` → 列出 projects
     - `GET /project/v1/hubs/{hub_id}/projects/{project_id}` → 取 `rootFolder`（在 relationships 內）
     - `GET /data/v1/projects/{project_id}/folders/{folder_id}/contents` → 列 items + 子資料夾，遞迴
     - 每個 item：`GET /data/v1/projects/{project_id}/items/{item_id}/versions` → 取最新版本 → `relationships.storage` 拿 storage object（`urn:adsk.objects:os.object:bucket/object`）
     - 下載：OSS v2 signed S3 download（`GET /oss/v2/buckets/{bucket}/objects/{object}/signeds3download`），再從回傳的 URL 抓檔。
- **⚠️ 必須先驗證、不可假設成立的點**（Claude Code 動工前先用 1 個檔做 spike）：
  1. 個人 hub 是否能透過 APS 列出 / 讀取（歷來有限制，需實測）。
  2. Fusion 設計版本的 storage object 下載下來**是否就是可重新上傳的原生 `.f3d` / `.f3z`**，特別是組立件是否打包了連結零件。若不是，路線 B 對組立件也無解，得退回路線 A + 手動。
- 官方文件（請以現行版為準，API 細節可能已更新）：
  - 認證 https://aps.autodesk.com/en/docs/oauth/v2/developers_guide/overview/
  - Data Management https://aps.autodesk.com/en/docs/data/v2/developers_guide/overview/
  - OSS https://aps.autodesk.com/en/docs/data/v2/reference/http/buckets-:bucketKey-objects-:objectKey-signeds3download-GET/

---

## 4. 建議執行順序

1. **先跑路線 A** 拿下所有單體設計的原生 f3d（量大、確定可行），同時生成 `manual_download_list.txt`（所有組立件）。
2. **針對組立件清單**，做路線 B 的 spike：先用清單上的 1 個組立件，驗證 APS 能否下載到可用的 `.f3z`。
   - spike 成功 → 用路線 B 自動清掉整份組立件清單。
   - spike 失敗（個人 hub 不通，或下載物不是原生檔）→ 直接照 `manual_download_list.txt` 在 Data Panel 逐一手動 Download f3z（這是官方唯一保證途徑）。

> 不要一開始就 all-in 路線 B；先用 spike 驗證那兩個風險點，再決定要不要投入完整實作。

---

## 5. 驗收標準

- [ ] 本機輸出目錄按「專案/子資料夾」重建結構。
- [ ] 每個**單體設計**有對應 `.f3d`。
- [ ] 每個**組立件**有對應 `.f3z`（路線 B 成功）或明確列在 `manual_download_list.txt`（待手動）。
- [ ] 產出 `export_log.txt`：成功 / 跳過（非設計檔）/ 失敗（含錯誤訊息）/ 需手動 四類，各列檔名與路徑。
- [ ] 對照雲端專案/資料夾數量，能算出覆蓋率（已下載檔數 ÷ 應有 f3d 數）。
- [ ] 單檔失敗不中斷整體；可重跑且不重複覆蓋已下載檔（同名加序號或先檢查存在）。

---

## 6. 已知地雷

- **崩潰/卡死**：社群回報 Project-Archiver 類腳本在 macOS 上偶有跑幾個檔後讓 Fusion 崩潰。路線 A 要逐檔 `try/except` 包好，並在每檔之間 `adsk.doEvents()` + `document.close(False)` 釋放資源。
- **存檔提示**：以唯讀開啟、`close(False)` 關閉，避免跳「是否儲存」對話框卡住無人值守流程。
- **檔名非法字元**：清掉 `<>:"/\|?*` 等再寫檔。
- **多 hub**：若使用者另有 Team/公司 hub，路線 A 一次只處理 active hub，需切換後再跑；路線 B 可一次遍歷所有 hub。先和使用者確認是否只有一個個人 hub。
- **APS 個人 hub 權限**：第 3 節 B 的最大不確定點，務必 spike 驗證，別寫完整套才發現拿不到。

---

## 7. 交付物

1. 改好的路線 A 腳本（只匯 f3d + 生成 manual 清單 + log）。
2. 路線 B 的可執行原型（OAuth + 遍歷 + 下載 + spike 驗證腳本）。
3. 一頁操作說明：如何在 Fusion 跑 A、如何設定 APS 跑 B、spike 失敗時如何照清單手動補。
