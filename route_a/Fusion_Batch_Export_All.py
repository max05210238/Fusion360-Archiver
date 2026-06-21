# -*- coding: utf-8 -*-
# =============================================================================
#  路線 A — Fusion 360 內批次匯出「整個 active hub 的所有專案」（只匯原生 f3d）
#
#  以 Script 執行：
#    Utilities > ADD-INS > Scripts and Add-Ins > Scripts 分頁
#    > 按綠色 "+" 建立新 Script > 用此檔內容覆蓋 main 檔 > 選取 > Run
#
#  作法：自動走遍 active hub 內所有 Project，遞迴每個 Project 底下所有資料夾，
#  把每個 .f3d 逐一開啟 -> 匯出原生 f3d -> 關閉，並在本機重建「專案/資料夾」結構。
#
#  ⚠️ 已知硬限制（不是 bug，是 adsk.* API 的天花板）：
#     含外部參照（linked components）的組立件，exportManager 無法產生獨立原生檔。
#     這類檔本腳本「不假裝成功」，而是記入 manual_download_list.txt，
#     之後改用路線 B（APS Downloads API）或在 Data Panel 手動 Download f3z。
#
#  跑完跳出統計，並在輸出根目錄寫：
#     - export_log.txt           成功 / 跳過 / 失敗 / 需手動 四類清單
#     - manual_download_list.txt 所有需手動下載 f3z 的組立件（含雲端路徑）
# =============================================================================

import adsk.core
import adsk.fusion
import os
import traceback

# ============================ 設定區（依需求修改） ============================

# 輸出根目錄。預設桌面下的 Fusion_Backup，會自動建立。
OUTPUT_ROOT = os.path.expanduser('~/Desktop/Fusion_Backup')

# True = 在輸出目錄重建「專案/子資料夾」結構；False = 全部丟同一層。
PRESERVE_STRUCTURE = True

# True = 已存在同名檔就略過不重抓（可重跑、不重複下載）；
# False = 同名時加序號另存（保留每次結果）。
SKIP_IF_EXISTS = True

# ============================================================================

# needs_manual 每筆是 (data_path, reason)，data_path 用來在 Data Panel 找到該檔。
results = {'exported': [], 'skipped': [], 'failed': [], 'needs_manual': []}


def _safe(name):
    """移除檔名/資料夾名中的非法字元。"""
    for ch in '<>:"/\\|?*\n\r\t':
        name = name.replace(ch, '_')
    return name.strip().rstrip('.')


def _count_files(folder):
    """先數一遍 .f3d 總數，給進度條與覆蓋率用（只讀 metadata，很快）。"""
    n = 0
    for i in range(folder.dataFiles.count):
        if folder.dataFiles.item(i).fileExtension == 'f3d':
            n += 1
    for i in range(folder.dataFolders.count):
        n += _count_files(folder.dataFolders.item(i))
    return n


def _export_active(app, data_file, out_dir, data_path):
    """匯出目前作用中的設計為原生 f3d。回傳 True 表示確實產出了一個 f3d。"""
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        results['skipped'].append('{} (非設計檔)'.format(data_path))
        return False

    # 含外部參照的組立件：API 出不了原生檔，記入需手動清單，不假裝成功。
    if app.activeDocument.allDocumentReferences.count > 0:
        results['needs_manual'].append((data_path, '含外部參照組立件，API 無法匯出原生檔'))
        return False

    em = design.exportManager
    stem = _safe(os.path.splitext(data_file.name)[0])
    target = os.path.join(out_dir, stem + '.f3d')

    if os.path.exists(target):
        if SKIP_IF_EXISTS:
            results['skipped'].append('{} (已存在，略過)'.format(data_path))
            return False
        # 不略過 -> 加序號另存，避免覆蓋
        root, ext = os.path.splitext(target)
        i = 1
        while os.path.exists(target):
            target = '{}_{}{}'.format(root, i, ext)
            i += 1

    em.execute(em.createFusionArchiveExportOptions(target))
    results['exported'].append(target)
    return True


def _walk(app, folder, out_dir, data_path, progress):
    if PRESERVE_STRUCTURE:
        os.makedirs(out_dir, exist_ok=True)

    # 先處理子資料夾
    for i in range(folder.dataFolders.count):
        if progress.wasCancelled:
            return
        sub = folder.dataFolders.item(i)
        sub_safe = _safe(sub.name)
        sub_out = os.path.join(out_dir, sub_safe) if PRESERVE_STRUCTURE else out_dir
        _walk(app, sub, sub_out, data_path + '/' + sub.name, progress)

    # 再處理此層的檔案
    for i in range(folder.dataFiles.count):
        if progress.wasCancelled:
            return
        data_file = folder.dataFiles.item(i)
        file_path = data_path + '/' + data_file.name

        if data_file.fileExtension != 'f3d':
            results['skipped'].append('{} (.{} 非設計檔)'.format(file_path, data_file.fileExtension))
            continue

        progress.message = '匯出中：{}\n已完成 %v / %m'.format(data_file.name)

        # ---- macOS 崩潰防護：逐檔 try/except 隔離，單檔失敗不中斷全局 ----
        doc = None
        try:
            doc = app.documents.open(data_file, True)   # 唯讀開啟
            adsk.doEvents()
            _export_active(app, data_file, out_dir, file_path)
        except Exception as e:
            results['failed'].append('{}: {}'.format(file_path, str(e)))
        finally:
            if doc is not None:
                try:
                    doc.close(False)   # 不存檔關閉，避免「是否儲存」對話框卡死無人值守
                except Exception:
                    pass
            progress.progressValue += 1
            adsk.doEvents()            # 讓 Fusion 釋放資源，降低連續開檔崩潰機率


def _write_logs(total):
    log_path = os.path.join(OUTPUT_ROOT, 'export_log.txt')
    with open(log_path, 'w', encoding='utf-8') as fh:
        exported = len(results['exported'])
        coverage = '{:.0%}'.format(exported / total) if total else 'n/a'
        fh.write('=== 覆蓋率 ===\n')
        fh.write('雲端 .f3d 總數：{}\n'.format(total))
        fh.write('已匯出原生檔：{}\n'.format(exported))
        fh.write('需手動（組立件）：{}\n'.format(len(results['needs_manual'])))
        fh.write('覆蓋率（已匯出 / 總數）：{}\n\n'.format(coverage))

        fh.write('=== 成功 ({}) ===\n'.format(exported))
        fh.write('\n'.join(results['exported']) + '\n\n')

        fh.write('=== 跳過 ({}) ===\n'.format(len(results['skipped'])))
        fh.write('\n'.join(results['skipped']) + '\n\n')

        fh.write('=== 失敗 ({}) ===\n'.format(len(results['failed'])))
        fh.write('\n'.join(results['failed']) + '\n\n')

        fh.write('=== 需手動下載 f3z ({}) ===\n'.format(len(results['needs_manual'])))
        for path, reason in results['needs_manual']:
            fh.write('{}    [{}]\n'.format(path, reason))
        fh.write('\n')

    # 另外輸出一份乾淨的手動清單，方便照著在 Data Panel 逐一 Download。
    manual_path = os.path.join(OUTPUT_ROOT, 'manual_download_list.txt')
    with open(manual_path, 'w', encoding='utf-8') as fh:
        fh.write('# 以下組立件含外部參照，adsk.* API 無法匯出原生檔。\n')
        fh.write('# 處理方式：\n')
        fh.write('#   1) 優先用路線 B（APS Downloads API）自動下載 f3z；或\n')
        fh.write('#   2) 在 Fusion Data Panel 對每個檔右鍵 > Download，得到 .f3z。\n')
        fh.write('# 路徑格式：專案/資料夾/.../檔名\n\n')
        for path, _reason in results['needs_manual']:
            fh.write(path + '\n')
    return log_path, manual_path


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        projects = app.data.dataProjects
        if projects.count == 0:
            ui.messageBox('在目前的 hub 找不到任何專案。')
            return

        os.makedirs(OUTPUT_ROOT, exist_ok=True)

        # 先數總檔數（給進度條與覆蓋率）
        total = 0
        for i in range(projects.count):
            total += _count_files(projects.item(i).rootFolder)
        if total == 0:
            ui.messageBox('找不到任何 .f3d 檔可匯出。')
            return

        progress = ui.createProgressDialog()
        progress.isCancelButtonShown = True
        progress.show('Fusion 批次匯出（原生 f3d）', '準備中…', 0, total, 0)

        for i in range(projects.count):
            if progress.wasCancelled:
                break
            proj = projects.item(i)
            proj_safe = _safe(proj.name)
            proj_out = os.path.join(OUTPUT_ROOT, proj_safe) if PRESERVE_STRUCTURE else OUTPUT_ROOT
            _walk(app, proj.rootFolder, proj_out, proj.name, progress)

        progress.hide()

        log_path, manual_path = _write_logs(total)

        ui.messageBox(
            '完成！\n\n'
            '成功：{}\n跳過：{}\n失敗：{}\n需手動（組立件）：{}\n\n'
            '輸出位置：{}\n'
            '詳細清單：export_log.txt\n'
            '需手動下載清單：manual_download_list.txt'.format(
                len(results['exported']), len(results['skipped']),
                len(results['failed']), len(results['needs_manual']),
                OUTPUT_ROOT
            )
        )

    except:
        if ui:
            ui.messageBox('執行失敗：\n{}'.format(traceback.format_exc()))
