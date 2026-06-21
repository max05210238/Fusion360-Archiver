# User Guide — Fusion360 Archiver (Web UI)

A step-by-step walkthrough for downloading all your native Fusion 360 files, written for
people who don't code. Allow ~15 minutes the first time (most of it is the one-time
Autodesk app setup).

There are two big phases:
- **Part A — Get the app running** (download, launch, get past macOS prompts).
- **Part B — Set up Autodesk access and download** (create an APS app, sign in, pick files).

---

## Part A — Get the app running

### A1. Download the project
1. On the project's GitHub page, click the green **Code** button ▸ **Download ZIP**.
2. Find the ZIP in your **Downloads** folder and double-click to unzip it.
3. You'll get a folder like `Fusion360-Archiver-...`. Inside are `Start-Mac.command`,
   `Start-Windows.bat`, `route_a`, `route_b`, etc.

> Tip (optional): move that folder out of **Downloads** into, say, your home folder or a
> new folder. Files launched from Downloads trigger an extra macOS permission prompt (see A4).
> It's harmless either way.

### A2. Launch it
- **macOS**: double-click **`Start-Mac.command`**.
- **Windows**: double-click **`Start-Windows.bat`**.

The first launch sets up a small isolated environment and installs two packages
(about 1 minute). After that it starts a local app and opens your browser to
`http://localhost:8080`.

### A3. macOS: "Apple could not verify… Not Opened"
Because the file was downloaded from the internet and isn't from a paid Apple developer,
macOS blocks it the first time. **This is expected. Do NOT click "Move to Trash."**

1. Click **Done**.
2. Open **System Settings** ▸ **Privacy & Security**.
3. Scroll down to the **Security** section. You'll see a line like
   *"Start-Mac.command" was blocked…* with an **Open Anyway** button. Click it and
   authenticate (password / Touch ID).
4. Double-click **`Start-Mac.command`** again. If a smaller dialog appears, click **Open**.

(Alternative: right-click the file ▸ **Open**. On the newest macOS the Privacy & Security
route above is the reliable one.)

### A4. macOS: "Terminal would like to access files in your Downloads folder"
This appears only if the project sits in **Downloads**. The launcher needs to read/write the
project files there. Click **Allow**.

### A5. macOS: "Allow Python to find devices on local networks?"
Click **Don't Allow** — the app only talks to your own computer (`localhost`) and the
Autodesk servers on the internet. It never needs your local network, so denying this changes
nothing.

### A6. The interface is open
Your browser shows **Fusion360 Archiver** with four numbered sections:
1. Settings 2. Choose what to download 3. Run 4. Results.
Leave this browser tab open. Keep the little black Terminal window open too — that's the app
running. (To stop the app later, just close that window.)

---

## Part B — Set up Autodesk access and download

### B1. Create an Autodesk APS app (one time)
To let the tool read your files, you register a free "app" with Autodesk and get two keys.

1. Go to <https://aps.autodesk.com> and **sign in** with the same Autodesk account you use for Fusion.
2. Click your profile (top right) ▸ **Applications** (or go directly to
   <https://aps.autodesk.com/myapps>).
3. Click **Create application**.
4. When asked which APIs the app uses, enable **Data Management API**.
5. Give it any **name** (e.g. "My Fusion Backup").
6. Set the **Callback URL** to exactly (copy it from the tool's Settings panel — it's shown there):
   ```
   http://localhost:8080/api/auth/callback
   ```
   ⚠️ It must match character-for-character, or sign-in will fail.
7. Click **Create**. You'll now see a **Client ID** and a **Client Secret**. Keep this page open
   (you'll copy both in the next step).

### B2. Fill in Settings (in the tool)
Back in the browser tab with Fusion360 Archiver:
1. Paste the **Client ID** into **APS Client ID**.
2. Paste the **Client Secret** into **APS Client Secret**.
3. **Download path** — where files are saved. The default
   (`/Users/you/Desktop/Fusion_Backup_APS`) is fine; change it if you want.
4. Click **Save settings**. You should see "Saved ✓".

> Your keys are stored only on your computer (`~/.aps_archiver_config.json`). The Client Secret
> box shows blank after saving on purpose — that's normal; it's still saved.

### B3. Sign in to Autodesk
1. Click **Sign in to Autodesk** (top right).
2. Your browser goes to Autodesk; log in and click **Allow / Authorize**.
3. You're sent back to the tool, and the badge top-right now reads **Signed in**.

This grants **read-only** access (`data:read`). The tool can list and download your files; it
**cannot delete or change** anything in the cloud.

### B4. Load and choose what to download
1. Click **Load / Refresh** under "2. Choose what to download". Your hubs and projects appear.
2. Expand items by clicking the small **▸** triangle. Check the boxes for what you want:
   - Check a whole **project** = every design inside it (the tool expands it for you).
   - Or drill into folders and check individual designs.
   - Or click **Select all projects** to grab everything.
3. The counter shows how many items are selected.

> If "Load" shows **"APS lists no hubs"**, your personal hub may not be reachable over APS.
> See Troubleshooting below.

### B5. Download
1. Click **Download selected** under "3. Run".
2. Watch the progress bar and the current file name. For 100+ files this can take a while
   (cloud fetch per file) — you can leave it running.
3. To stop early, click **Cancel** (already-downloaded files are kept).

### B6. Check results and retry missing
Under "4. Results", four tabs:
- **Exported** — newly downloaded files.
- **Already exists** — skipped because they were already downloaded (safe to re-run anytime).
- **No native format** — the cloud had no f3d/f3z to offer for that item.
- **Failed** — something went wrong (e.g. a network hiccup). The error is shown.

If anything is in **Failed**, click **↻ Retry all failed** to fetch just those again.
Already-downloaded files are skipped, so retrying is always safe.

A text log is also written to `export_log.txt` inside your download path.

### B7. Your files
Open the **Download path** folder. Files are organized as
`Project / Folder / Design.f3d` (or `.f3z` for assemblies). Assemblies as `.f3z` contain all
their linked parts.

### B8. Restoring a file back into Fusion (so the backup is actually useful)
These are Autodesk's official native archive formats, made for exactly this:
- In Fusion, open the **Data Panel** (the grid icon, top left).
- Click **Upload**, choose your `.f3d` or `.f3z` file, and confirm.
- Fusion processes it and the design appears in your project as a **fully editable** model. For a
  `.f3z` assembly, the main assembly and all its linked parts are restored together.

So your backup is fully reversible — you can always get your designs back into Fusion.

### B9. Delete your keys when you're done (recommended)
For safety, clean up after a backup session:
1. In the app, scroll to **"5. Security & restore"** and click **🗑 Delete my keys & sign out**.
   This removes the saved Client ID/Secret and your login token from this computer.
2. For full safety, also go to <https://aps.autodesk.com/myapps>, open your app, and **Delete** it.
   That permanently revokes the keys (you can make a new app next time).

Why: the **Client Secret** is like a password, and the login token grants read access to your
Autodesk data. They live only on your computer, but never share or screenshot the Client Secret,
and deleting them when done removes any lingering risk.

---

## Using it again later
- Double-click the launcher again (no more macOS prompts after the first time).
- Your settings and sign-in are remembered. Just **Load**, select, **Download**.
- Re-running never re-downloads files you already have, so it's a safe way to "fill in" anything new.

## Stopping / removing
- **Stop the app**: close the small black Terminal window.
- **Remove everything**: delete the project folder, plus `~/.aps_archiver_config.json` and
  `~/.aps_archiver_token.json` in your home folder. (Your downloaded backup files stay until
  you delete them.) Nothing is installed system-wide except Python itself if you had to install it.

---

## Troubleshooting

**"Load" says "APS lists no hubs."**
Autodesk's API sometimes can't see a personal (free) Fusion hub. This is a known limitation on
Autodesk's side, not a bug in the tool. Options:
- Double-check you signed in with the same account that owns the Fusion files.
- If it still shows nothing, use **Route A** instead (the in-Fusion script) to grab single-body
  designs, and download assemblies manually from the Fusion Data Panel. See the main README.

**Sign-in fails / "Token exchange failed."**
The **Callback URL** in your APS app doesn't exactly match
`http://localhost:8080/api/auth/callback`. Fix it in the APS app settings and try again.

**Browser didn't open automatically.**
Open a browser and go to <http://localhost:8080> yourself.

**Port 8080 already in use.**
Something else uses that port. Close it, or (advanced) start the app on another port — but then
your APS Callback URL must use the same port.

**A few files land in "Failed."**
Usually a transient network issue. Click **↻ Retry all failed**.

---

## What this tool does and doesn't do (safety)
- **Read-only**: it requests only Autodesk's `data:read` permission. It downloads; it cannot
  delete or modify anything in your Autodesk cloud.
- **Local only**: the app runs on your own machine; nothing is uploaded anywhere except the
  normal login to Autodesk.
- **No background service**: it runs only while the Terminal window is open. Closing it stops everything.
