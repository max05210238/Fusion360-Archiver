# Handover: batch-download the native files of an entire Fusion 360 account

> A complete task brief. The goal is clear, the constraints are verified, and it
> includes two technical routes plus acceptance criteria.

---

## 1. Goal

Download **all native Fusion files** from the user's Autodesk / Fusion 360 account to a
local backup.

- Scope: **all projects** in the active hub (dozens) + every folder under each project +
  scattered one-off designs, **100+ files** total.
- **Native formats only** (`.f3d` / `.f3z`). No STEP/STL/IGES or other neutral formats.
- Preserve the "project / folder" structure locally.
- As hands-off as possible. After the run there must be a log clearly marking
  success / skipped / failed / needs-manual.

---

## 2. Required constraints (verified, they drive the architecture)

These are hard constraints, not implementation details — absorb them before picking a route:

1. **Fusion has no native UI batch export.** The official UI handles one file at a time;
   the community universally relies on scripts/APIs.
2. **Fusion's built-in API (`adsk.*`) cannot export the native file of an assembly with
   external references.**
   - For a file with linked components, Fusion only offers `.f3z`, not `.f3d`; and the
     **API cannot even produce the `.f3z`**.
   - So `createFusionArchiveExportOptions()` works for a single-body design (no external
     references) but necessarily fails or is forced to skip an assembly.
   - Sources:
     - https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Unable-to-export-Fusion-360-model-in-f3d-format-when-only-f3z-file-format-is-offered.html
     - https://github.com/WilkoV/Fusion360_ExportIt (README: API exports cannot contain linked components; cannot produce f3z)
3. **To get the native assembly file with all linked parts, the official path is to
   "Download" the top-level file from the Data Panel → produces `.f3z`.** This is a
   cloud/manual action, not an `adsk.*` API.
   - Source: https://forums.autodesk.com/t5/fusion-360-ideastation-archived/export-assemblies-with-referenced-parts-in-f3d/idi-p/8358860
4. **Everything lives in the cloud.** Each file open is a cloud fetch; 100+ files may take
   1–3 hours. Design for long, stable, unattended runs where a single failure doesn't
   stop the whole job.

> Conclusion: **no single route can fully automatically get every native file.** You must
> split handling of "single-body designs" and "assemblies".

---

## 3. Two technical routes

### Route A — Python script inside Fusion (known to work, but only covers single-body designs)

- Form: run as a **Script** inside Fusion (`adsk.core` / `adsk.fusion`).
- Can do: iterate all projects → recurse all folders → for each `.f3d` design call
  `createFusionArchiveExportOptions` to export native f3d, preserving structure.
- **Cannot do: assemblies with external references** (per section 2). For those, the script
  must **detect `activeDocument.allDocumentReferences.count > 0` and record them in a
  "needs manual download" list** — don't pretend it succeeded.
- Starting point (already written, edit directly): see the attached `Fusion_Batch_Export_All.py`.
  Required changes:
  - Keep f3d only as the export format.
  - For files with external references, write them to a `needs_manual_f3z` list (with
    project/folder path) and output it as `manual_download_list.txt`.
- Limitation: must be triggered manually inside the Fusion GUI; it can't be driven headless.

### Route B — APS (Autodesk Platform Services / formerly Forge) Data Management REST API (fully automatic, includes assemblies, but personal-hub access must be verified)

- Form: pure REST; can run the whole flow headless. This is the most hands-off route and the
  **only one that can possibly get native assembly files automatically**.
- High-level flow:
  1. Register an App at https://aps.autodesk.com to get a **Client ID / Secret**.
  2. **3-legged OAuth (Authorization Code flow)**, scope at least `data:read account:read`.
     ⚠️ Personal hub (My Hub / Personal) data **must use 3-legged (user authorization)**;
     2-legged cannot reach it.
  3. Traverse the data structure:
     - `GET /project/v1/hubs` → list hubs
     - `GET /project/v1/hubs/{hub_id}/projects` → list projects
     - `GET /project/v1/hubs/{hub_id}/projects/{project_id}` → get `rootFolder` (in relationships)
     - `GET /data/v1/projects/{project_id}/folders/{folder_id}/contents` → list items + subfolders, recurse
     - per item: `GET /data/v1/projects/{project_id}/items/{item_id}/versions` → take the latest version
     - download via the official Downloads API (request f3d/f3z), then the OSS signed S3 URL.
- **⚠️ Points that must be verified, not assumed** (do a 1-file spike before building):
  1. Whether the personal hub can be listed / read via APS (historically restricted, test it).
  2. Whether the downloaded artifact is a re-uploadable native `.f3d` / `.f3z`, and whether an
     assembly actually packages its linked parts. If not, Route B can't solve assemblies either,
     and you fall back to Route A + manual.
- Official docs (use the current version; API details may have changed):
  - Auth https://aps.autodesk.com/en/docs/oauth/v2/developers_guide/overview/
  - Data Management https://aps.autodesk.com/en/docs/data/v2/developers_guide/overview/
  - Downloads https://aps.autodesk.com/blog/download-fusion-360-archives

---

## 4. Suggested execution order

1. **Spike Route B first** (it's the only path to native assemblies and the most hands-off):
   use 1 single-body + 1 assembly to verify (a) the personal hub can be listed over APS, and
   (b) the Downloads-API f3z unzips to a complete set of linked parts.
   - Spike passes → use Route B to clear everything automatically (assemblies included).
   - Spike fails (personal hub unreachable, or the artifact isn't a native file) → fall back to
     Route A for single-body f3d + follow `manual_download_list.txt` to Download f3z in the
     Data Panel (the only officially guaranteed path).

---

## 5. Acceptance criteria

- [ ] The local output directory rebuilds the "project/subfolder" structure.
- [ ] Each **single-body design** has a corresponding `.f3d`.
- [ ] Each **assembly** has a corresponding `.f3z` (Route B success) or is clearly listed in
      `manual_download_list.txt` (pending manual).
- [ ] Produce `export_log.txt`: success / skipped (non-design) / failed (with error) / needs-manual,
      each listing filename and path.
- [ ] Against the cloud project/folder counts, you can compute coverage (downloaded ÷ expected).
- [ ] A single failure doesn't stop the whole run; re-runnable and won't re-overwrite already
      downloaded files (suffix on clash or check existence first).

---

## 6. Known landmines

- **Crash / hang**: the community reports Project-Archiver-style scripts occasionally crash
  Fusion after a few files on macOS. Route A must wrap each file in `try/except`, and between
  files call `adsk.doEvents()` + `document.close(False)` to release resources.
- **Save prompt**: open read-only and `close(False)` to avoid a "save?" dialog stalling the
  unattended run.
- **Illegal filename characters**: strip `<>:"/\|?*` etc. before writing.
- **Multiple hubs**: if the user also has a Team/company hub, Route A handles one active hub at a
  time (switch and re-run); Route B can traverse all hubs in one pass.
- **APS personal-hub access**: the biggest uncertainty in section 3 B; verify with a spike, don't
  build the whole thing only to find you can't get the data.

---

## 7. Deliverables

1. The edited Route A script (f3d only + generates the manual list + log).
2. A runnable Route B prototype (OAuth + traversal + download + spike validation script).
3. A one-page guide: how to run A in Fusion, how to set up APS for B, and how to fall back to the
   manual list when the spike fails.
