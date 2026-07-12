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

## ⚠️ Project status, support & disclaimer — please read

- **This is a personal backup tool, provided AS-IS, with NO warranty and NO support.**
- The repository owner **is not a developer**. They described a problem; **the code was written
  entirely by an AI assistant (Claude)** based on that description. The owner cannot debug,
  maintain, or guarantee this code.
- **If you find a bug, you are expected to fix it yourself** (fork the repo and modify it). Please
  **do not expect the owner to triage, answer, or fix issues** — they very likely can't.
- **Route B (APS)** is the part that was actually exercised. **Route A (the in-Fusion script) is
  UNTESTED by the owner** — it's included only as a convenience for people who want it. Treat it as
  experimental and verify it yourself before relying on it.
- **Verify your backup.** Before trusting it, restore at least one file back into Fusion (see
  "Restoring your backup into Fusion") to confirm the workflow works for your account.
- You use this tool, and your own Autodesk APS app/keys, **at your own risk.**

---

## Folder structure: it mirrors what you see in Fusion

The local output rebuilds the same hierarchy you see in Fusion's Data Panel:

```
<download path>/
  <Project name>/            # one top-level folder per project
    <Folder name>/           # same folder names as in Fusion
      <Design name>.f3d      # single-body design
      <Assembly name>.f3z    # assembly (with all linked parts inside)
```

Project, folder, and file names are **the same as in Fusion**, with one caveat: characters that are
illegal in filenames (`/ \ : * ? " < > |`) are replaced with `_`, so e.g. a design called
`Bracket v2 (final)` stays as-is, but `Left/Right Mount` becomes `Left_Right Mount`.

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
> - **Don't have Python?** It's a free one-time install. Step-by-step (with screenshots-level
>   detail) is in [docs/USER_GUIDE.md §A0](docs/USER_GUIDE.md#a0-install-python-first-only-if-you-dont-have-it).
>   Short version: macOS → <https://www.python.org/downloads/macos/> (open the `.pkg`, click through);
>   Windows → <https://www.python.org/downloads/windows/> (run it, **check "Add python.exe to PATH"**).
>   Then double-click the launcher again.
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
4. **3. Run**: click **"Scan & Compare"** — the tool diffs the cloud against your local
   folder (FreeFileSync-style) and lists each design as **New / Updated / Up-to-date /
   Missing / Unverified / Orphan**, with the cloud version number and modified dates. Check
   the rows you want and click **"Sync selected"** to download only those. (A plain
   "Download all selected" button is still there if you'd rather skip the compare step.)
5. **4. Results**: four buckets — Exported / Already current / No native format / Failed; if anything failed, click **"↻ Retry all failed"** to refetch.

> **Re-runnable, version-aware.** After the first backup the tool records what version of
> each design it saved (a small `.aps_manifest.json` in your download folder). On later runs
> it re-downloads **only** designs that are new or that changed in Fusion — even when the file
> name is unchanged — and never touches unchanged files. Designs you deleted in the cloud are
> reported as "orphan" but your local copies are **never** deleted.

> The UI and the CLI below share the same download logic and the same permissions (see
> "Data security" below): the tool only reads, lists, and triggers downloads — it never
> deletes or overwrites your designs. The first time, it's still recommended to run the
> CLI `--spike` to confirm the personal hub is readable (see below).

---

## Route B (CLI) — fully automatic via APS

### 1. Create an APS App
> First time on APS? The full click-by-click flow (accept terms → get the **free** APS plan → create
> an **APS Developer Hub** → create the app → fix the callback URL) is in
> [docs/USER_GUIDE.md §B1](docs/USER_GUIDE.md). Short version:

1. Sign in at <https://aps.autodesk.com/myapps>. First-time users must accept the ToS, sign up for the
   **Free** APS plan (a card is required to verify identity but you are **not** charged), and create an
   **APS Developer Hub**.
2. In that hub, **Create application** → type **Traditional Web App** → note its **Client ID** and
   **Client Secret**.
3. Set the App's **Callback URL** to exactly (the default created value is incomplete, fix it):
   ```
   http://localhost:8080/api/auth/callback
   ```
4. Ensure **Data Management API** is in the app's API Access list.

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

### 4. Full download / incremental sync
```bash
python aps_archiver.py --dry-run  # preview the plan: new / updated / up-to-date / missing / orphan
python aps_archiver.py --sync     # version-aware sync: download only new & changed files (== --all)
python aps_archiver.py --all      # same as --sync (kept for compatibility)
python aps_archiver.py --list     # just inspect the hub/project tree first
```
`--sync` compares the cloud against your local folder using a `.aps_manifest.json` it keeps in
`APS_OUTPUT_ROOT`, so re-runs re-download **only** what is new or has a newer version in Fusion
(matched by Autodesk version, not just file name) and skip everything unchanged. `--dry-run`
prints the same comparison without downloading anything. Output goes to `APS_OUTPUT_ROOT`, with
`export_log.txt` (synced / no native format / failed / orphan). Orphans (removed from the cloud)
are only reported — local files are never deleted.

> The first run opens a browser to sign in to Autodesk and authorize; the token is
> cached to `~/.aps_archiver_token.json` (gitignored — do not commit it).

---

## Route A — in-Fusion script (fallback, single-body f3d only) — ⚠️ UNTESTED

> **Heads-up: the owner has not tested Route A.** It's provided for people who want an in-Fusion
> option. Treat it as experimental — read the code, and verify it on a couple of files before
> trusting it.
>
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

To restore, in Fusion open the **Data Panel ▸ Upload** and choose the `.f3d` / `.f3z` file(s). Fusion
extracts each and loads it back as a **fully editable design** (for an f3z, the main assembly and all
its linked parts reappear). Official docs:
- How to make / use a local archive (backup) file:
  https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/How-to-make-a-local-archive-back-up-file-in-Fusion-360.html

**Tip:** Fusion's Upload dialog lets you **select many `.f3d` / `.f3z` files at once**, so you don't
have to upload them one by one.

### Why there isn't a single "restore everything" file, or a built-in Upload button
- **The restorable unit is one design.** Fusion's archive formats are per-design: a `.f3d` (one
  design) or a `.f3z` (one assembly + its links). Each `.f3z` we download is **already** a zip that
  Fusion accepts directly — that's the format you re-upload.
- **There is no whole-account / whole-folder archive that Fusion restores in one click.** If you
  zipped the entire backup folder into one `.zip`, Fusion would **not** accept it as a restore — it
  isn't an `.f3z`, just a generic zip. So bundling everything into one file wouldn't make restore
  easier; it would only mislead. The per-design `.f3d`/`.f3z` files are the right, ready-to-upload unit.
- **No built-in upload/restore UI here, on purpose.** A real restore-into-Fusion would require the
  tool to **create/modify designs in your account** and request broader write permissions; this tool
  never does that. The official **Data Panel ▸ Upload** is the reliable, supported way to restore, and
  it's just a file picker. Keeping restore manual is the safer choice.

## Is this safe? (you don't have to trust me)

Healthy skepticism is correct — **never give an unknown app access to your data on faith.** This tool
is built so you don't have to trust the author; you can *verify* instead:

- **It runs entirely on your own computer.** There is no server run by the author. It's a small local
  program at `http://localhost:8080`. Your designs move **directly between your machine and Autodesk** —
  they never touch the author or any third party.
- **You use your own Autodesk app and your own keys.** You create the APS app under *your* account; the
  login token is stored only on your machine and you can revoke it anytime by deleting the app. The
  author never receives your keys, token, or files.
- **It cannot delete or overwrite your designs.** It requests `data:read` + `data:create` (the latter
  only because Autodesk's download API requires it to build the archive). It never requests write or
  delete scopes and never calls them. Worst case, it reads and downloads.
- **It only talks to Autodesk.** The only network destinations in the code are
  `developer.api.autodesk.com` (Autodesk) and `localhost` (your machine). No telemetry, no analytics,
  no phone-home — search the code for `http` and check.
- **It's tiny and dependency-light.** A couple of readable files (one Python backend, one HTML page) and
  two well-known libraries (`requests`, `flask`). You — or an AI like Claude/ChatGPT — can audit the
  whole thing in minutes.
- **It's AI-written, and we say so.** The author isn't a developer; the code was written by an AI from a
  problem description (see the disclaimer above). That's exactly *why* it's small, open, and auditable.

**How to verify before you run it:**
1. Read `route_b/app.py` and `route_b/aps_archiver.py` (or paste them into an AI and ask: "does this do
   anything besides read and download my own Autodesk data?").
2. Confirm the only URLs are Autodesk + `localhost`.
3. Use least privilege: enable only the **Data Management API**, and **delete your APS app when you're
   done** (which revokes all access).

## Data security: your API keys and permissions

This tool downloads using **your own Autodesk authorization** (3-legged OAuth). Three things are
created and live **only on your computer**, in your home folder, never uploaded or committed:

| Item | What it is | Sensitivity |
|---|---|---|
| Client ID | Your APS app's public identifier | low |
| Client Secret | Your APS app's **password** | **high — treat like a password** |
| `~/.aps_archiver_token.json` | Login token for your Autodesk data (scopes below) | high while valid |

**What permissions (scopes) the tool requests:** `data:read data:create account:read`.
- `data:read` / `account:read` — list and read your hubs, projects, folders and designs.
- `data:create` — **required by Autodesk's official Downloads API** (`POST .../downloads`) just to
  generate the downloadable native archive. It is *not* used to change your designs.
- The tool **never** requests `data:write` or any delete scope, and its code only ever **reads, lists,
  and triggers downloads** — it never edits, moves, overwrites, or deletes anything in your account.
  So it **cannot delete or overwrite your existing designs.**

**Leak risk:** if your Client Secret or token file is exposed (e.g. shared, screenshotted, or copied
off your machine), someone could read/download your Fusion data (and, with `data:create`, create new
items) until you revoke it. They could **not** delete or overwrite your existing designs. Still, it's
your data — so **never post or screenshot the Client Secret**, and delete the keys when you're done
(below).

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
