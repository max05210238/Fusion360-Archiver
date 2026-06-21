# -*- coding: utf-8 -*-
# =============================================================================
#  Route A — In-Fusion batch export of every project in the active hub (native f3d only)
#
#  How to run, inside Fusion:
#    Utilities > ADD-INS > Scripts and Add-Ins > Scripts tab
#    > click the green "+" to create a new Script > paste this file's content into
#    the main file > select it > Run
#
#  What it does: walks every Project in the active hub, recurses every folder under
#  each Project, opens each .f3d one by one -> exports native f3d -> closes it, and
#  rebuilds the "project/folder" structure locally.
#
#  KNOWN HARD LIMIT (not a bug, it's the adsk.* API ceiling):
#     Assemblies that contain external references (linked components) cannot be
#     exported as a standalone native file by exportManager. For those files this
#     script does NOT pretend to succeed; it records them into manual_download_list.txt
#     so you can grab them later via Route B (APS Downloads API) or by Download in
#     the Data Panel (which yields .f3z).
#
#  On completion it pops up a summary and writes, into the output root:
#     - export_log.txt            four lists: exported / skipped / failed / needs-manual
#     - manual_download_list.txt  every assembly needing a manual f3z download (with cloud path)
# =============================================================================

import adsk.core
import adsk.fusion
import os
import traceback

# ============================ Settings (edit as needed) ============================

# Output root directory. Defaults to Fusion_Backup on the Desktop; created automatically.
OUTPUT_ROOT = os.path.expanduser('~/Desktop/Fusion_Backup')

# True = rebuild the "project/subfolder" structure under the output dir;
# False = dump everything into one flat folder.
PRESERVE_STRUCTURE = True

# True  = if a file with the same name already exists, skip it (re-runnable, no re-download).
# False = on name clash, save with a numeric suffix (keep every run's results).
SKIP_IF_EXISTS = True

# ============================================================================

# Each needs_manual entry is (data_path, reason); data_path locates the file in the Data Panel.
results = {'exported': [], 'skipped': [], 'failed': [], 'needs_manual': []}


def _safe(name):
    """Strip characters that are illegal in file/folder names."""
    for ch in '<>:"/\\|?*\n\r\t':
        name = name.replace(ch, '_')
    return name.strip().rstrip('.')


def _count_files(folder):
    """Pre-count total .f3d files for the progress bar and coverage (metadata only, fast)."""
    n = 0
    for i in range(folder.dataFiles.count):
        if folder.dataFiles.item(i).fileExtension == 'f3d':
            n += 1
    for i in range(folder.dataFolders.count):
        n += _count_files(folder.dataFolders.item(i))
    return n


def _export_active(app, data_file, out_dir, data_path):
    """Export the currently active design as native f3d. Returns True if a file was produced."""
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        results['skipped'].append('{} (not a design)'.format(data_path))
        return False

    # Assembly with external references: the API cannot produce a native file.
    # Record it in the needs-manual list instead of pretending it succeeded.
    if app.activeDocument.allDocumentReferences.count > 0:
        results['needs_manual'].append((data_path, 'assembly with external references; API cannot export native file'))
        return False

    em = design.exportManager
    stem = _safe(os.path.splitext(data_file.name)[0])
    target = os.path.join(out_dir, stem + '.f3d')

    if os.path.exists(target):
        if SKIP_IF_EXISTS:
            results['skipped'].append('{} (already exists, skipped)'.format(data_path))
            return False
        # Not skipping -> add a numeric suffix so nothing is overwritten.
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

    # Handle subfolders first
    for i in range(folder.dataFolders.count):
        if progress.wasCancelled:
            return
        sub = folder.dataFolders.item(i)
        sub_safe = _safe(sub.name)
        sub_out = os.path.join(out_dir, sub_safe) if PRESERVE_STRUCTURE else out_dir
        _walk(app, sub, sub_out, data_path + '/' + sub.name, progress)

    # Then the files at this level
    for i in range(folder.dataFiles.count):
        if progress.wasCancelled:
            return
        data_file = folder.dataFiles.item(i)
        file_path = data_path + '/' + data_file.name

        if data_file.fileExtension != 'f3d':
            results['skipped'].append('{} (.{} not a design)'.format(file_path, data_file.fileExtension))
            continue

        progress.message = 'Exporting: {}\nDone %v / %m'.format(data_file.name)

        # ---- macOS crash guard: isolate each file in try/except; one failure doesn't stop the run ----
        doc = None
        try:
            doc = app.documents.open(data_file, True)   # open read-only
            adsk.doEvents()
            _export_active(app, data_file, out_dir, file_path)
        except Exception as e:
            results['failed'].append('{}: {}'.format(file_path, str(e)))
        finally:
            if doc is not None:
                try:
                    doc.close(False)   # close without saving, avoids a "save?" dialog stalling the run
                except Exception:
                    pass
            progress.progressValue += 1
            adsk.doEvents()            # let Fusion release resources, reduces crashes when opening many files


def _write_logs(total):
    log_path = os.path.join(OUTPUT_ROOT, 'export_log.txt')
    with open(log_path, 'w', encoding='utf-8') as fh:
        exported = len(results['exported'])
        coverage = '{:.0%}'.format(exported / total) if total else 'n/a'
        fh.write('=== Coverage ===\n')
        fh.write('Total cloud .f3d files: {}\n'.format(total))
        fh.write('Native files exported:  {}\n'.format(exported))
        fh.write('Needs manual (assemblies): {}\n'.format(len(results['needs_manual'])))
        fh.write('Coverage (exported / total): {}\n\n'.format(coverage))

        fh.write('=== Exported ({}) ===\n'.format(exported))
        fh.write('\n'.join(results['exported']) + '\n\n')

        fh.write('=== Skipped ({}) ===\n'.format(len(results['skipped'])))
        fh.write('\n'.join(results['skipped']) + '\n\n')

        fh.write('=== Failed ({}) ===\n'.format(len(results['failed'])))
        fh.write('\n'.join(results['failed']) + '\n\n')

        fh.write('=== Needs manual f3z download ({}) ===\n'.format(len(results['needs_manual'])))
        for path, reason in results['needs_manual']:
            fh.write('{}    [{}]\n'.format(path, reason))
        fh.write('\n')

    # Also write a clean manual list, easy to follow when downloading one by one in the Data Panel.
    manual_path = os.path.join(OUTPUT_ROOT, 'manual_download_list.txt')
    with open(manual_path, 'w', encoding='utf-8') as fh:
        fh.write('# The assemblies below contain external references; the adsk.* API\n')
        fh.write('# cannot export them as native files. How to handle:\n')
        fh.write('#   1) Preferred: use Route B (APS Downloads API) to download f3z automatically; or\n')
        fh.write('#   2) In the Fusion Data Panel, right-click each file > Download to get a .f3z.\n')
        fh.write('# Path format: project/folder/.../filename\n\n')
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
            ui.messageBox('No projects found in the current hub.')
            return

        os.makedirs(OUTPUT_ROOT, exist_ok=True)

        # Count total files first (for progress bar and coverage)
        total = 0
        for i in range(projects.count):
            total += _count_files(projects.item(i).rootFolder)
        if total == 0:
            ui.messageBox('No .f3d files found to export.')
            return

        progress = ui.createProgressDialog()
        progress.isCancelButtonShown = True
        progress.show('Fusion batch export (native f3d)', 'Preparing...', 0, total, 0)

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
            'Done!\n\n'
            'Exported: {}\nSkipped: {}\nFailed: {}\nNeeds manual (assemblies): {}\n\n'
            'Output location: {}\n'
            'Full lists: export_log.txt\n'
            'Manual download list: manual_download_list.txt'.format(
                len(results['exported']), len(results['skipped']),
                len(results['failed']), len(results['needs_manual']),
                OUTPUT_ROOT
            )
        )

    except:
        if ui:
            ui.messageBox('Run failed:\n{}'.format(traceback.format_exc()))
