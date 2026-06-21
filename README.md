# Fusion360-Archiver

批次下載整個 Autodesk / Fusion 360 個人帳號的**原生檔**（`.f3d` / `.f3z`）到本機，保留「專案 / 資料夾」結構。

## 為什麼要兩條路線

Fusion 的 `adsk.*` 內建 API **拿不到含外部參照（linked components）的組立件原生檔** —— 這是 API 天花板，不是腳本問題。所以分流處理：

| | 路線 A（Fusion 內腳本） | 路線 B（APS REST API） |
|---|---|---|
| 形式 | 在 Fusion GUI 內手動 Run 的 Script | 本機 headless 跑的 Python |
| 單體設計 f3d | ✅ | ✅ |
| 組立件原生檔 | ❌（只能列入待手動清單） | ✅ 官方 Downloads API 產 f3z（打包 linked 零件） |
| 無人值守 | 需手動觸發 | 一次瀏覽器登入後全自動 |
| 角色 | **備援** | **主力** |

> **建議順序：先跑路線 B 的 `--spike` 驗證個人 hub 通不通；通了就用 `--all` 一次清空（含組立件）。萬一個人 hub 在 APS 不開放，才退回路線 A 收單體 f3d ＋ 照清單手動補組立件。**

---

## 🚀 最簡單：點兩下就能跑（不用懂程式、不用開 VSCode）

1. 下載整個專案（GitHub 綠色 **Code ▸ Download ZIP**），解壓縮。
2. **macOS**：對 **`啟動-Mac.command`** 點兩下。
   **Windows**：對 **`啟動-Windows.bat`** 點兩下。
3. 第一次它會自動裝好需要的東西（約 1 分鐘），然後**自動打開瀏覽器**到操作介面。

> - macOS 第一次若跳「無法打開，因為來自未識別的開發者」：對該檔**按右鍵 ▸ 打開 ▸ 打開**，之後就能直接點兩下。
> - 若提示沒有 Python，它會自動打開下載頁；裝好後再點兩下啟動檔即可（macOS 記得裝 python.org 版本，Windows 安裝時勾 **Add Python to PATH**）。
> - 之後每次要用，就點兩下啟動檔；要結束就關掉那個黑色視窗。

打開介面後，照畫面四個步驟（設定 → 登入 → 勾選 → 下載）操作即可，詳見下一節。

---

## 🖥️ 進階：手動用指令跑 Web UI

懂終端機的話也可以手動啟動（內容和雙擊啟動檔一樣）：

```bash
cd route_b
python3 -m venv .venv && source .venv/bin/activate   # 建議用隔離環境
pip install -r requirements.txt
python app.py
```
然後瀏覽器開 <http://localhost:8080>，依畫面四個步驟：

1. **① 設定**：貼上 APS Client ID / Secret、選下載路徑、按「儲存設定」。
   （先到 <https://aps.autodesk.com> 建一個 App，Callback URL 填頁面上顯示的那一行，預設 `http://localhost:8080/api/auth/callback`。）
2. **右上角「登入 Autodesk」**：跳轉瀏覽器授權，回來就顯示「已登入」。
3. **② 選擇**：按「載入」列出 hub/專案，展開勾選；勾整個 project = 含其下全部設計。也可「全選所有 project」。
4. **③ 執行**：按「開始下載所選」，看即時進度。
5. **④ 結果分析**：分「成功 / 已存在 / 無原生格式 / 失敗」四類；有失敗時按 **「↻ 重抓所有失敗的漏檔」** 一鍵補抓（已下載的會自動略過）。

> UI 與下方 CLI 共用同一套下載邏輯與唯讀權限；只下載、不刪改任何檔。第一次仍建議先用 CLI 的 `--spike` 驗證個人 hub 是否可讀（見下）。

---

## 路線 B（CLI）— APS 全自動

### 1. 建立 APS App
1. 到 <https://aps.autodesk.com> 登入，建立一個 App。
2. 記下 **Client ID** 與 **Client Secret**。
3. App 的 **Callback URL** 設為與腳本一致（預設）：
   ```
   http://localhost:8080/api/auth/callback
   ```

### 2. 安裝與設定
```bash
cd route_b
pip install -r requirements.txt

export APS_CLIENT_ID=你的ClientID
export APS_CLIENT_SECRET=你的ClientSecret
# 可選：自訂輸出位置 / callback
export APS_OUTPUT_ROOT="~/Desktop/Fusion_Backup_APS"
# export APS_CALLBACK_URL="http://localhost:8080/api/auth/callback"
```

### 3. 先 spike（強烈建議）
```bash
python aps_archiver.py --spike
```
會做兩件驗證並印出結果：
- **風險點 1**：APS 能不能列出你的個人 hub / projects。
- **風險點 2**：對 1～2 個檔跑完整 Downloads API，把原生檔抓到 `/tmp/aps_spike/`。

spike 成功後，**手動解開**抓下來的 `.f3z`，確認裡面含全部 linked 零件（驗證組立件真的被打包）。

### 4. 全量下載
```bash
python aps_archiver.py --all      # 保留結構、可重跑（已存在的檔自動略過）
python aps_archiver.py --list     # 只想先看 hub/project 樹狀結構
```
輸出在 `APS_OUTPUT_ROOT`，含 `export_log.txt`（成功 / 跳過 / 無原生格式 / 失敗）。

> 第一次執行會跳出瀏覽器要你登入 Autodesk 並授權；token 會快取到 `~/.aps_archiver_token.json`（已列入 `.gitignore`，請勿提交）。

---

## 路線 A — Fusion 內腳本（備援，只收單體 f3d）

> 用於：個人 hub 在 APS 不通時，至少把單體設計的原生 f3d 收下來，並產出組立件的待手動清單。

1. Fusion 開啟 → **Utilities ▸ ADD-INS ▸ Scripts and Add-Ins ▸ Scripts** 分頁。
2. 按綠色 **「+」** 建立新 Script，把 `route_a/Fusion_Batch_Export_All.py` 的內容貼進 main 檔。
3. （可選）改檔頭設定區：`OUTPUT_ROOT`、`PRESERVE_STRUCTURE`、`SKIP_IF_EXISTS`。
4. 選取該 Script ▸ **Run**。它會走遍 active hub 所有專案，逐檔開啟匯出原生 f3d。

跑完在輸出目錄產生：
- `export_log.txt` — 成功 / 跳過 / 失敗 / 需手動 四類，含覆蓋率。
- `manual_download_list.txt` — 所有含外部參照、API 出不了原生檔的組立件路徑。

### 組立件怎麼補
照 `manual_download_list.txt`：
- 優先：用路線 B 的 `--all`／`--spike` 自動下載 f3z；
- 不行才：在 Fusion **Data Panel** 對每個檔右鍵 **Download** 取得 `.f3z`。

### macOS 注意
社群回報 Project-Archiver 類腳本在 macOS 上連續開檔偶有讓 Fusion 崩潰。本腳本已逐檔 `try/except` 隔離、每檔之間 `adsk.doEvents()` + `document.close(False)` 釋放資源、單檔失敗不中斷全局，並可重跑（`SKIP_IF_EXISTS=True` 不重抓已下載的檔）。

---

## 已知地雷
- **個人 hub 的 APS 可見性**：路線 B 唯一真風險，務必先 `--spike` 驗證，別寫完整套才發現拿不到。
- **多 hub**：路線 A 一次只處理 active hub（需切換重跑）；路線 B 會一次遍歷所有 hub。
- **存檔提示 / 非法字元 / 重複覆蓋**：兩條路線都已處理（唯讀關閉、清非法字元、同名略過或加序號）。

## 檔案結構
```
啟動-Mac.command                     macOS 雙擊啟動（自動裝環境 + 開介面）
啟動-Windows.bat                     Windows 雙擊啟動
route_a/Fusion_Batch_Export_All.py   路線 A：Fusion 內批次匯出 f3d + 生成待手動清單
route_b/aps_archiver.py              路線 B 核心：APS OAuth + 遍歷 + Downloads API 下載（CLI 可獨立用）
route_b/app.py                       路線 B Web UI 後端（Flask，包住上面的核心邏輯）
route_b/static/index.html            Web UI 前端（登入/勾選/執行/結果/重抓）
route_b/requirements.txt
docs/Fusion_Native_Backup_BRIEF.md   原始任務簡報（背景與限制查證）
```
