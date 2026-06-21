# Fusion360-Archiver

Batch-download every **native file** (`.f3d` / `.f3z`) from your Autodesk / Fusion 360
personal account to your computer, preserving the "project / folder" structure.

---

## Background: the problem, the limits, and what you get

### The problem
Everything in Fusion 360 lives in **Autodesk's cloud**. If you have a whole account's worth of
designs — dozens of projects, folders, and one-off files, easily **100+ files** — there is no
built-in way to pull them all down as a real, restorable backup:

- **Fusion has no native UI batch export.** The official interface handles **one file at a time**.
- To truly own your work offline you want the **native format** (`.f3d` / `.f3z`), not a neutral
  format like STEP — because only the native format restores back into Fusion as a **fully editable
  design with its edit history** (STEP is flattened, history-less geometry).

### Why it's hard (the hard limits)
These are verified constraints, not implementation choices:

1. **No batch export in the Fusion UI** — the community relies entirely on scripts/APIs.
2. **Fusion's built-in `adsk.*` API cannot export an assembly with external references (linked
   components) as a native file.** For such a file Fusion only offers `.f3z`, and the API can't even
   produce that. So an in-Fusion script can do single-body designs but is *forced to skip* assemblies.
3. **The official way to get a native assembly with all its linked parts is to "Download" the
   top-level file from the cloud Data Panel → which yields a `.f3z`.** That's a cloud action, not an
   `adsk.*` API call.
4. **Everything is a cloud fetch**, so 100+ files can take 1–3 hours and must survive single-file
   failures without aborting the whole run.

> Bottom line: **no single in-Fusion script can fully, automatically get every native file.** You
> have to handle "single-body designs" and "assemblies" by different means.

### What existing tools can and can't do — e.g. [tapnair/Project-Archiver](https://github.com/tapnair/Project-Archiver)
This is the well-known community add-in (and the inspiration for this project). It's good, but it
hits exactly the wall above:

- **What it does:** runs inside Fusion and bulk-exports every design in a project to **STEP**
  (plus EAGLE formats for electronics). Cross-platform, batches a whole project.
- **What it *can't* do — and why:**
  - **No native `.f3d` / `.f3z`** — it only outputs STEP. STEP is **neutral, flattened geometry**:
    no edit history, no parametric features, and you **can't re-upload it as an editable native
    design**. Fine for handing geometry to another CAD tool; **not a true restorable backup**.
  - **No assemblies with linked components** as native — same `adsk.*` ceiling; it sidesteps the
    problem by only ever producing STEP.
  - It's an **in-Fusion GUI add-in**, so it can't run headless, and it must be triggered by hand.
    (The community also reports it occasionally crashing Fusion on macOS after many files.)

So Project-Archiver answers "give me the geometry as STEP," not "give me my real, editable Fusion
files back."

### Our solution
Two routes, so you're never stuck:

- **Route B (primary, fully automatic):** talk to the **APS (Autodesk Platform Services) Data
  Management REST API** from your own machine, using the **official Downloads API**
  (`downloadFormats → create download job → signed download`). This produces **real, re-uploadable
  native `.f3d` / `.f3z`**, and the `.f3z` **packages all linked components** of an assembly. It runs
  headless after a one-time browser login, and ships with a point-and-click **Web UI**.
- **Route A (fallback, in-Fusion script):** if the APS path can't see your personal hub, an improved
  in-Fusion script still grabs native **`.f3d` for single-body designs** and writes a
  `manual_download_list.txt` of the assemblies for you to Download from the Data Panel.

### What you get with this approach
- **Native `.f3d` / `.f3z`**, not STEP → **fully editable** and **restorable into Fusion** (Data
  Panel ▸ Upload), with edit history intact.
- **Assemblies as `.f3z`** containing **all linked parts**.
- Your **project / folder structure** rebuilt locally.
- A **hands-off** workflow (sign in → select → download → retry failures) via a local Web UI.
- A real, **reversible** backup — see "Restoring your backup into Fusion" below.

### At a glance

| | Project-Archiver | This tool — Route A | This tool — Route B |
|---|---|---|---|
| Output format | STEP (+ EAGLE) | native `.f3d` | native `.f3d` + `.f3z` |
| Single-body designs | ✅ as STEP | ✅ native | ✅ native |
| Assemblies w/ linked parts | ⚠️ STEP only (flattened) | ❌ (listed for manual) | ✅ `.f3z` with all parts |
| Editable / restorable into Fusion | ❌ geometry only | ✅ | ✅ |
| Edit history preserved | ❌ | ✅ | ✅ |
| Fully automatic / headless | ❌ | ❌ | ✅ |
| Needs the Fusion GUI | yes | yes | no (local web UI) |

---

## Why two routes (quick summary)

As explained above, no single in-Fusion script can get every native file, so the work is split:

| | Route A (in-Fusion script) | Route B (APS REST API) |
|---|---|---|
| Form | A Script you Run manually inside the Fusion GUI | Headless Python on your machine |
| Single-body f3d | ✅ | ✅ |
| Native assembly file | ❌ (can only list them for manual download) | ✅ official Downloads API yields f3z (packs linked parts) |
| Unattended | needs manual triggering | fully automatic after one browser login |
| Role | **fallback** | **primary** |

> **Recommended order: first run Route B's `--spike` to verify the personal hub is
> reachable; if so, run `--all` to clear everything (assemblies included). If the
> personal hub is not exposed over APS, fall back to Route A for single-body f3d
> plus manual download of the assemblies from the list.**

---

## 🚀 Easiest: double-click to run (no coding, no VSCode)

1. Download the whole project (GitHub green **Code ▸ Download ZIP**) and unzip it.
2. **macOS**: double-click **`Start-Mac.command`**.
   **Windows**: double-click **`Start-Windows.bat`**.
3. The first time, it installs what it needs automatically (about 1 minute), then
   **opens your browser** to the interface.

> - macOS, first time, if it says "cannot be opened because it is from an
>   unidentified developer": **right-click the file ▸ Open ▸ Open**; after that you
>   can just double-click it.
> - If it reports Python is missing, it opens the download page automatically; install
>   it and double-click the launcher again (on macOS install the python.org build; on
>   Windows check **Add Python to PATH** during install).
> - Each later time, just double-click the launcher; to stop, close the black window.

Once the interface opens, follow the four on-screen steps (Settings → Sign in →
Select → Download).

> **📖 New to this? Read the [step-by-step User Guide](docs/USER_GUIDE.md)** — it walks
> through every screen and every macOS permission prompt, plus how to create the Autodesk
> APS app. Highly recommended for first-time setup.

---

## 🖥️ Advanced: start the Web UI from the command line

If you're comfortable with a terminal you can start it manually (same as the launcher):

```bash
cd route_b
python3 -m venv .venv && source .venv/bin/activate   # an isolated environment is recommended
pip install -r requirements.txt
python app.py
```
Then open <http://localhost:8080> and follow the four on-screen steps:

1. **1. Settings**: paste your APS Client ID / Secret, choose a download path, click "Save settings".
   (First create an App at <https://aps.autodesk.com>; set its Callback URL to the line shown
   on the page, default `http://localhost:8080/api/auth/callback`.)
2. **"Sign in to Autodesk"** (top right): it redirects you to authorize; on return it shows "Signed in".
3. **2. Select**: click "Load" to list hubs/projects, expand and check; checking a whole project = all designs under it. You can also "Select all projects".
4. **3. Run**: click "Download selected" and watch live progress.
5. **4. Results**: four buckets — Exported / Already exists / No native format / Failed; if anything failed, click **"↻ Retry all failed"** to refetch (already-downloaded files are skipped).

> The UI and the CLI below share the same download logic and read-only scope; download
> only, never delete or modify anything. The first time, it's still recommended to run
> the CLI `--spike` to confirm the personal hub is readable (see below).

---

## Route B (CLI) — fully automatic via APS

### 1. Create an APS App
1. Sign in at <https://aps.autodesk.com> and create an App.
2. Note its **Client ID** and **Client Secret**.
3. Set the App's **Callback URL** to match the script (default):
   ```
   http://localhost:8080/api/auth/callback
   ```

### 2. Install and configure
```bash
cd route_b
pip install -r requirements.txt

export APS_CLIENT_ID=yourClientID
export APS_CLIENT_SECRET=yourClientSecret
# optional: custom output path / callback
export APS_OUTPUT_ROOT="~/Desktop/Fusion_Backup_APS"
# export APS_CALLBACK_URL="http://localhost:8080/api/auth/callback"
```

### 3. Spike first (strongly recommended)
```bash
python aps_archiver.py --spike
```
It runs two checks and prints the results:
- **Risk 1**: whether APS can list your personal hub / projects.
- **Risk 2**: it runs the full Downloads API on 1–2 files, fetching native files to `/tmp/aps_spike/`.

After a successful spike, **manually unzip** the `.f3z` you fetched to confirm it
contains all linked parts (proving assemblies are packaged).

### 4. Full download
```bash
python aps_archiver.py --all      # preserves structure, re-runnable (existing files are skipped)
python aps_archiver.py --list     # just inspect the hub/project tree first
```
Output goes to `APS_OUTPUT_ROOT`, with `export_log.txt` (exported / skipped / no native format / failed).

> The first run opens a browser to sign in to Autodesk and authorize; the token is
> cached to `~/.aps_archiver_token.json` (gitignored — do not commit it).

---

## Route A — in-Fusion script (fallback, single-body f3d only)

> Use when the personal hub is not reachable over APS: at least pull the native f3d
> for single-body designs, and produce a manual-download list for the assemblies.

1. In Fusion, open **Utilities ▸ ADD-INS ▸ Scripts and Add-Ins ▸ Scripts** tab.
2. Click the green **"+"** to create a new Script and paste the content of `route_a/Fusion_Batch_Export_All.py` into its main file.
3. (Optional) edit the settings at the top: `OUTPUT_ROOT`, `PRESERVE_STRUCTURE`, `SKIP_IF_EXISTS`.
4. Select the Script ▸ **Run**. It walks every project in the active hub, opening and exporting each as native f3d.

When done, it produces, in the output directory:
- `export_log.txt` — exported / skipped / failed / needs-manual, with coverage.
- `manual_download_list.txt` — every assembly with external references the API can't export.

### How to get the assemblies
Follow `manual_download_list.txt`:
- Preferred: use Route B's `--all` / `--spike` to download f3z automatically;
- Otherwise: in the Fusion **Data Panel**, right-click each file **Download** to get a `.f3z`.

### macOS note
The community reports that Project-Archiver-style scripts occasionally crash Fusion when
opening many files in a row on macOS. This script isolates each file in `try/except`,
calls `adsk.doEvents()` + `document.close(False)` between files to release resources, never
lets one failure stop the run, and is re-runnable (`SKIP_IF_EXISTS=True` skips already-downloaded files).

---

## Restoring your backup into Fusion (yes, it works)

The downloaded files are Autodesk's **official native archive formats**, designed exactly for
backup/restore — so this backup is fully reversible:

- **`.f3d`** — a single design.
- **`.f3z`** — an assembly, **including all its linked components** (it's a zip of the f3d files).

To restore, in Fusion open the **Data Panel ▸ Upload** and choose the `.f3d` / `.f3z` file. Fusion
extracts it and loads it back as a **fully editable design** (for an f3z, the main assembly and all
its linked parts reappear). Official docs:
- How to make / use a local archive (backup) file:
  https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/How-to-make-a-local-archive-back-up-file-in-Fusion-360.html

## Data security: your API keys

This tool downloads using **your own Autodesk authorization** (3-legged OAuth). Three things are
created and live **only on your computer**, in your home folder, never uploaded or committed:

| Item | What it is | Sensitivity |
|---|---|---|
| Client ID | Your APS app's public identifier | low |
| Client Secret | Your APS app's **password** | **high — treat like a password** |
| `~/.aps_archiver_token.json` | Login token granting **read** access to your Autodesk data | high while valid |

**Leak risk:** if your Client Secret or token file is exposed (e.g. shared, screenshotted, or copied
off your machine), someone could read/download your Fusion data. The scope is **read-only**, so they
could not delete or modify your cloud data — but it's still your data. So: **never post or screenshot
the Client Secret.**

### How to get the keys
See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) §B1, or in short: <https://aps.autodesk.com/myapps> ▸
**Create application** ▸ enable **Data Management API** ▸ set Callback URL
`http://localhost:8080/api/auth/callback` ▸ copy the Client ID & Secret.

### How to delete the keys when you're done (recommended)
1. **In the app** (section "5. Security & restore"): click **🗑 Delete my keys & sign out** — this
   removes the saved Client ID/Secret and the login token from your computer.
   (Equivalent manual step: delete `~/.aps_archiver_config.json` and `~/.aps_archiver_token.json`.)
2. **For full revocation**: go to <https://aps.autodesk.com/myapps>, open your app, and **Delete** it.
   This permanently invalidates the Client ID/Secret so they can never be used again — even if they
   had leaked. You can always create a fresh app next time you back up.

> Doing your backup and then deleting both the local keys and the APS app is the safest pattern.

## Known pitfalls
- **APS visibility of the personal hub**: the only real risk for Route B; always `--spike`
  first instead of building the whole thing before discovering you can't get the data.
- **Multiple hubs**: Route A handles one active hub at a time (switch and re-run); Route B
  traverses all hubs in one pass.
- **Save prompts / illegal characters / overwrites**: both routes handle these (close
  read-only, strip illegal chars, skip or suffix on name clash).

## File structure
```
Start-Mac.command                    macOS double-click launcher (auto env setup + opens the UI)
Start-Windows.bat                    Windows double-click launcher
route_a/Fusion_Batch_Export_All.py   Route A: in-Fusion batch export to f3d + manual list
route_b/aps_archiver.py              Route B core: APS OAuth + traversal + Downloads API (also usable standalone via CLI)
route_b/app.py                       Route B Web UI backend (Flask, wraps the core)
route_b/static/index.html            Web UI frontend (sign in / select / run / results / retry)
route_b/requirements.txt
docs/USER_GUIDE.md                   step-by-step walkthrough for non-coders (start here)
docs/Fusion_Native_Backup_BRIEF.md   original task brief (background and verified constraints)
```
