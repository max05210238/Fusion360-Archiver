# Security & trust

**Short version: you don't have to trust the author — you can verify.** See
[README ▸ "Is this safe?"](README.md#is-this-safe-you-dont-have-to-trust-me) for the full explanation.

## Threat model in one screen

- **No author-run server.** The tool runs entirely on *your* machine at `http://localhost:8080`. Your
  designs move directly between your computer and Autodesk. The author and anyone else never receive
  your keys, your login token, or your files.
- **Your own credentials.** You register your own Autodesk (APS) app and use your own Client ID/Secret.
  You can revoke everything at any time by deleting that app at <https://aps.autodesk.com/myapps>.
- **Read + download only.** The OAuth scopes requested are `data:read data:create account:read`.
  `data:create` is required *only* by Autodesk's official download endpoint to generate the archive.
  The tool never requests `data:write` or any delete scope, and never edits, overwrites, or deletes
  anything in your account.
- **Only talks to Autodesk.** The only network endpoints in the code are `developer.api.autodesk.com`
  and `localhost`. There is no telemetry or analytics.
- **Small and auditable.** The backend is two Python files (`route_b/app.py`, `route_b/aps_archiver.py`)
  plus one HTML page (`route_b/static/index.html`), using only `requests` and `flask`.

## How to verify

1. Read the two Python files (or paste them into an AI and ask whether they do anything besides read and
   download your own data).
2. Grep for network calls and confirm the only hosts are Autodesk + `localhost`.
3. Enable only the **Data Management API** on your APS app (least privilege).
4. Delete your APS app and the local key/token files when you're done.

## Local files this tool creates

- `~/.aps_archiver_config.json` — your Client ID/Secret and download path.
- `~/.aps_archiver_token.json` — your login token.

Both live only on your machine and are removed by the in-app **"Delete my keys & sign out"** button (or
by deleting the files manually).

## Reporting

This is an as-is, unmaintained personal project (see the disclaimer in the README). If you find a
security issue, the best path is to open a public issue describing it, or fork and fix it — the author
may not be able to respond.
