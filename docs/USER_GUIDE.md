# User Guide — Fusion360 Archiver (Web UI)

A step-by-step walkthrough for downloading all your native Fusion 360 files, written for
people who don't code. Allow ~15 minutes the first time (most of it is the one-time
Autodesk app setup).

There are two big phases:
- **Part A — Get the app running** (download, launch, get past macOS prompts).
- **Part B — Set up Autodesk access and download** (create an APS app, sign in, pick files).

---

## Part A — Get the app running

### A0. Install Python first (only if you don't have it)
This tool needs **Python 3** (a free, safe, widely-used program). You only install it once. The
launcher will tell you if it's missing — but you can just do this first to be safe.

**macOS**
1. Go to <https://www.python.org/downloads/macos/>.
2. Click the big yellow **Download Python 3.x** button — it downloads a file ending in `.pkg`.
3. Open the downloaded `.pkg` from your Downloads folder.
4. Click **Continue → Continue → Agree → Install**, enter your Mac password when asked, then **Close**.
5. Done. (You don't need to open Python yourself — the launcher uses it.)

**Windows**
1. Go to <https://www.python.org/downloads/windows/>.
2. Click **Download Python 3.x** (the installer is a `.exe`).
3. Run the installer. **IMPORTANT:** on the first screen, check the box **"Add python.exe to PATH"**
   at the bottom.
4. Click **Install Now**, allow it, then **Close**.
5. Done.

> Not sure if you already have it? Just try the launcher (next steps). If it pops up "Python not
> found", come back and install it as above.

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
To let the tool access your files, you register a free Autodesk "app" and get two keys (a Client ID
and a Client Secret). It's free, but Autodesk's onboarding has a few one-time steps. Take it slow —
this is the longest part, ~10 minutes the first time.

Go to <https://aps.autodesk.com/myapps> and **sign in** with the **same Autodesk account you use for
Fusion**. Then work through whatever Autodesk shows you:

**B1a. First-time "Welcome aboard" form (only on your very first visit).**
Autodesk asks you to accept Terms of Service and fill basic info. Required fields: Role, Company,
Company website, Industry (pick at least one), Country, "For what purpose are you using APS?", and the
**Terms of Service** checkbox. State/City/ZIP are optional. The values don't matter and aren't
verified (e.g. Role = "Hobbyist", Company = "Personal", website = `example.com`). Check the ToS box and
**Submit**.

**B1b. "You don't have a hub yet" → get the free APS plan.**
APS now requires a "developer hub", which requires an APS plan first. On the right side under **Get an
APS plan**, click **View options**, then on the plans page choose **Free** ▸ **Add to Cart** ▸
checkout. Notes:
- The **Free** plan is genuinely free (about 300,000 API calls/month; a full backup uses only a few
  thousand, so you'll never be charged).
- ⚠️ Checkout **requires a payment method (a card) to verify your identity**, but the total is **$0.00
  and you are not charged** unless you ever manually upgrade. The Free plan auto-renews at $0 (you can
  turn that off later in your Autodesk account). If you're not willing to put a card on file, you
  can't use Route B — use Route A instead (see the main README).
- Don't pick Prepay or Pay-as-You-Go (those are paid).

**B1c. Create the developer hub.**
After the plan is active, in your Autodesk account go to **Products and Services ▸ Hubs**. You may
already see a hub named like "Team hub – <you>" with product **Fusion** — that is your *data* hub, NOT
a developer hub, so you still need to make one. Click **Create hub ▸ APS Developer Hub**, give it a
name (e.g. `Fusion Backup Hub`), and **Create and activate**. Wait a moment for it to finish
activating.

**B1d. Create the application.**
Go to <https://aps.autodesk.com/myapps>; make sure the **Developer Hub** selector (top left) shows your
new hub. Click **Create application**:
- **Name**: anything (e.g. `Fusion Backup`).
- **Application Type**: choose **Traditional Web App** (the "Most flexible" one — it stores a secret
  and uses the Authorization Code login this tool needs). Click **Create**.

**B1e. Finish the app settings (this is where people get stuck).**
On the app's **App settings** page:
- ⚠️ **Callback URL**: it may default to just `http://localhost:8080/`. **Change it to exactly**
  (copy from the tool's Settings panel):
  ```
  http://localhost:8080/api/auth/callback
  ```
  Character-for-character, or sign-in fails. Then **Save changes**.
- **API Access**: make sure **Data Management API** is checked (it's the only one this tool needs;
  you may untick the rest for least privilege, or leave them — it doesn't increase risk).
- Copy your **Client ID** (copy icon) and reveal + copy your **Client Secret** (eye icon, then copy).
  Keep them handy for the next step.

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

The authorize screen will ask to **view your data** and **manage your data** — this is normal. The
tool requests `data:read data:create account:read`: it reads/lists your files, and `data:create` is
**required by Autodesk's download API just to generate the downloadable archive**. The tool only
reads, lists, and downloads — it **never edits, overwrites, or deletes** anything in your account.

### B4. Load and choose what to download
1. Click **Load / Refresh** under "2. Choose what to download". Your hubs and projects appear.
2. Expand items by clicking the small **▸** triangle. Check the boxes for what you want:
   - Check a whole **project** = every design inside it (the tool expands it for you).
   - Or drill into folders and check individual designs.
   - Or click **Select all projects** to grab everything.
3. The counter shows how many items are selected.

> If "Load" shows **"APS lists no hubs"**, your personal hub may not be reachable over APS.
> See Troubleshooting below.

### B5. Scan & Compare, then Sync
1. Click **Scan & Compare** under "3. Run". The tool looks at every design you selected in
   the cloud and compares it to what's already in your Download path — like FreeFileSync does
   for two folders. Each design gets a status:
   - **NEW** — never downloaded yet.
   - **UPDATED** — you changed it in Fusion since the last backup (a newer version exists).
     The table shows the new version number and the one you have.
   - **MISSING** — it's recorded as downloaded but the local file is gone.
   - **UP-TO-DATE** — your local copy already matches the cloud; nothing to do.
   - **UNVERIFIED** — a file is on disk but from before this compare feature existed, so its
     version is unknown. Left unchecked by default; check it if you want to re-fetch to be sure.
   - **ORPHAN** — removed from the cloud but still in your backup. **Never deleted**, just listed.
2. New / Updated / Missing rows are **checked** by default. Adjust the checkboxes, then click
   **Sync selected** to download only those.
3. Watch the progress bar and the current file name. For 100+ files this can take a while
   (cloud fetch per file) — you can leave it running. **Cancel** stops early; finished files are kept.

> Prefer the old behavior? **Download all selected** still works — it downloads everything you
> selected and skips files already on disk by name.

### B6. Check results and retry missing
Under "4. Results", four tabs:
- **Exported** — newly downloaded (new or updated) files.
- **Already current** — skipped because your local copy already matched the cloud.
- **No native format** — the cloud had no f3d/f3z to offer for that item.
- **Failed** — something went wrong (e.g. a network hiccup). The error is shown.

If anything is in **Failed**, click **↻ Retry all failed** to fetch just those again.

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
- **You can select multiple `.f3d` / `.f3z` files at once** in the Upload dialog, so restoring many
  designs isn't one-at-a-time.

So your backup is fully reversible — you can always get your designs back into Fusion. (Note: there's
no single "restore my whole account" file — Fusion restores per design — but each `.f3z`/`.f3d` is
already in the exact format Fusion's Upload accepts.)

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
- Your settings and sign-in are remembered. Just **Load**, select, **Scan & Compare**, **Sync selected**.
- Re-running is version-aware: it downloads only designs that are **new** or that you **changed**
  in Fusion since last time (matched by Autodesk version, not just file name), and skips
  everything unchanged — so it's a safe, fast way to keep the backup current. The tool remembers
  what it downloaded in a small `.aps_manifest.json` inside your Download path (leave it there).

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
- **Download-only behavior**: it requests `data:read data:create account:read`. The `data:create`
  scope is required by Autodesk's download API only to generate the downloadable archive. The tool
  reads, lists, and downloads; it **never edits, overwrites, or deletes** anything in your Autodesk
  cloud (it never requests `data:write` or any delete permission).
- **Local only**: the app runs on your own machine; nothing is uploaded anywhere except the
  normal login to Autodesk.
- **No background service**: it runs only while the Terminal window is open. Closing it stops everything.
