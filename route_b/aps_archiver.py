#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Route B — Use the APS (Autodesk Platform Services, formerly Forge) Data Management API
          to automatically download every native Fusion file (including assemblies as f3z)
          from your personal hub.

Why this path can get what the in-Fusion API cannot:
    Instead of grabbing the raw cloud storage object directly, we use the official
    Downloads API:
        GET  .../versions/{ver}/downloadFormats   list downloadable formats (f3d / f3z)
        POST .../projects/{proj}/downloads         create a download job for a format
        poll .../projects/{proj}/jobs|downloads/{id}
        finally get the storage object -> signed S3 download
    The official f3z that comes out "packages all linked components of the assembly",
    so this path yields re-uploadable native files even for assemblies.

WARNING: visibility of a personal hub (A360 Personal) over APS has historically been
   inconsistent -- this is the only real risk of this route. Validate first with
   `--spike` (can list projects + can complete the Downloads API on one file), then
   run the full job with `--all`.

Requirements:
    pip install -r requirements.txt   (only requests is needed)
    Create an App at https://aps.autodesk.com to get a Client ID / Secret, and set the
    Callback URL to exactly match CALLBACK_URL below (default
    http://localhost:8080/api/auth/callback).

Configuration (environment variables, or edit the constants below):
    APS_CLIENT_ID, APS_CLIENT_SECRET, APS_CALLBACK_URL, APS_OUTPUT_ROOT

Usage:
    python aps_archiver.py --spike     # validate personal hub + Downloads API (run this first)
    python aps_archiver.py --list      # just print the hub/project/folder/item tree
    python aps_archiver.py --all       # full automatic download, preserves structure, re-runnable

Official docs (details follow the current version):
    OAuth v2     https://aps.autodesk.com/en/docs/oauth/v2/developers_guide/overview/
    Data Mgmt v2 https://aps.autodesk.com/en/docs/data/v2/developers_guide/overview/
    Downloads    https://aps.autodesk.com/blog/download-fusion-360-archives
"""

import argparse
import json
import os
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

try:
    import requests
except ImportError:
    sys.exit('requests is required: run  pip install -r requirements.txt  first')

# ============================ Settings ============================

CLIENT_ID     = os.environ.get('APS_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('APS_CLIENT_SECRET', '')
CALLBACK_URL  = os.environ.get('APS_CALLBACK_URL', 'http://localhost:8080/api/auth/callback')
OUTPUT_ROOT   = os.path.expanduser(os.environ.get('APS_OUTPUT_ROOT', '~/Desktop/Fusion_Backup_APS'))

# Scopes:
#   data:read    - list hubs/projects/folders/items and read versions (browse + plan downloads)
#   data:create  - REQUIRED by Autodesk's Downloads API (POST .../downloads) just to generate the
#                  downloadable native archive. It does NOT let this tool modify or delete your
#                  existing designs (that would need data:write / delete scopes, which we never request),
#                  and the code only ever creates a transient download job -- nothing else.
#   account:read - read-only listing of related accounts.
SCOPES   = 'data:read data:create account:read'
BASE     = 'https://developer.api.autodesk.com'
TOKEN_CACHE = os.path.expanduser('~/.aps_archiver_token.json')

# Native formats to try, in priority order (assemblies usually only have f3z, singles have f3d).
PREFERRED_FORMATS = ['f3z', 'f3d']

# Connection retries
MAX_RETRIES = 4
JOB_POLL_TIMEOUT = 300   # max seconds to wait for a single Downloads job
JOB_POLL_INTERVAL = 3

JSONAPI_HEADERS = {'Content-Type': 'application/vnd.api+json'}

# ============================ Helpers ============================

def log(msg):
    print(msg, flush=True)


def safe_name(name):
    for ch in '<>:"/\\|?*\n\r\t':
        name = name.replace(ch, '_')
    return name.strip().rstrip('.')


# ======================= Sync manifest =======================
# A small JSON state file at the backup root that records, per downloaded file, the
# cloud version it came from. It is what turns a re-run into a real incremental sync
# (only download what is new or changed) instead of the old filename-only skip.

MANIFEST_NAME = '.aps_manifest.json'
MANIFEST_SCHEMA = 1

# Plan status codes (also the labels shown to the user).
STATUS_NEW = 'new'                    # not in manifest, no file on disk        -> download
STATUS_UPDATED = 'updated'            # cloud version differs from recorded      -> download (overwrite)
STATUS_UPTODATE = 'uptodate'          # recorded version matches, file present   -> skip
STATUS_MISSING_LOCAL = 'missing_local'  # recorded but file gone from disk       -> re-download
STATUS_UNVERIFIED = 'unverified'      # file on disk but no record (pre-manifest)-> skip by default
STATUS_ORPHAN = 'orphan'              # recorded/on disk but no longer in cloud  -> report only

# Statuses whose default action is "download this file".
_DOWNLOAD_STATUSES = {STATUS_NEW, STATUS_UPDATED, STATUS_MISSING_LOCAL}


def manifest_path(output_root):
    return os.path.join(output_root, MANIFEST_NAME)


def load_manifest(output_root):
    """Return the manifest dict, tolerating a missing or corrupt file."""
    path = manifest_path(output_root)
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get('records'), dict):
                return data
        except Exception:
            pass
    return {'schema': MANIFEST_SCHEMA, 'records': {}}


def save_manifest(output_root, man):
    """Atomically persist the manifest (write to .part then os.replace)."""
    os.makedirs(output_root, exist_ok=True)
    path = manifest_path(output_root)
    tmp = path + '.part'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(man, f, indent=1)
    os.replace(tmp, path)


def manifest_get(man, dest_key):
    return man.get('records', {}).get(dest_key)


def manifest_put(man, dest_key, record):
    man.setdefault('records', {})[dest_key] = record


def _rel_key(output_root, dest_path):
    """The manifest key for a destination file: its path relative to the backup root,
    with forward slashes so keys are stable across OSes."""
    rel = os.path.relpath(dest_path, output_root)
    return rel.replace(os.sep, '/')


def _existing_local(dest_base):
    """Return (dest_path, file_type) for an already-downloaded native file at dest_base,
    probing the preferred formats; (None, None) if nothing is on disk."""
    for f in PREFERRED_FORMATS:
        cand = dest_base + '.' + f
        if os.path.exists(cand):
            return cand, f
    return None, None


# ======================= Compare / plan =======================

def plan_item(cloud_item, dest_base, man, output_root):
    """Classify one cloud item against the manifest + local disk. Pure/read-only.
    `cloud_item` is a normalized dict: version_id, name, rel_path, lineage_id,
    last_modified, display_name, project_id. `dest_base` is the extension-less
    destination path already disambiguated by _claim_dest."""
    version_id = cloud_item.get('version_id')
    lineage_id = cloud_item.get('lineage_id')
    record = None
    rec_key = None

    # Prefer matching by the recorded dest key of this lineage (survives name probing);
    # fall back to whichever extension the record used.
    for key, rec in man.get('records', {}).items():
        if lineage_id and rec.get('lineage_id') == lineage_id:
            record, rec_key = rec, key
            break

    local_path, local_ft = _existing_local(dest_base)

    if record is not None:
        rec_path = os.path.join(output_root, rec_key.replace('/', os.sep))
        file_present = os.path.exists(rec_path) or local_path is not None
        dest_key = rec_key
        if record.get('version_id') == version_id:
            status = STATUS_UPTODATE if file_present else STATUS_MISSING_LOCAL
        else:
            status = STATUS_UPDATED
    elif local_path is not None:
        status = STATUS_UNVERIFIED
        dest_key = _rel_key(output_root, local_path)
    else:
        status = STATUS_NEW
        dest_key = None  # extension unknown until download picks a format

    local_mtime = None
    local_size = None
    ref_path = local_path or (record and os.path.join(output_root, rec_key.replace('/', os.sep)))
    if ref_path and os.path.exists(ref_path):
        try:
            local_mtime = os.path.getmtime(ref_path)
            local_size = os.path.getsize(ref_path)
        except OSError:
            pass

    return {
        'status': status,
        'action_default': status in _DOWNLOAD_STATUSES,
        'dest_base': dest_base,
        # Extension-less destination relative to the backup root. Always present (even for
        # NEW items, whose extension isn't known yet) so the download step reuses the exact
        # disambiguated base and can't drift or collide with a same-named design.
        'dest_base_rel': os.path.relpath(dest_base, output_root).replace(os.sep, '/'),
        'dest_key': dest_key,
        'version_id': version_id,
        'version_number': version_number_from_id(version_id),
        'recorded_version_number': record.get('version_number') if record else None,
        'lineage_id': lineage_id,
        'project_id': cloud_item.get('project_id'),
        'name': cloud_item.get('name'),
        'rel_path': cloud_item.get('rel_path'),
        'display_name': cloud_item.get('display_name') or cloud_item.get('name'),
        'cloud_last_modified': cloud_item.get('last_modified'),
        'local_mtime': local_mtime,
        'local_size': local_size,
        'file_type': (record or {}).get('file_type') or local_ft,
    }


def _claim_dest(output_root, cloud_item, man, claimed):
    """Compute the extension-less destination path for a cloud item, disambiguating
    same-named designs deterministically. A lineage that already has a manifest record
    reuses that exact base (regardless of traversal order); otherwise a per-run ' (n)'
    suffix keyed on lineage id is assigned so two different same-named designs never
    collide. Returns dest_base (absolute, no extension)."""
    lineage_id = cloud_item.get('lineage_id')

    # Reuse a prior assignment recorded in the manifest so keys are stable across runs.
    for key, rec in man.get('records', {}).items():
        if lineage_id and rec.get('lineage_id') == lineage_id:
            base_no_ext = os.path.splitext(os.path.join(output_root, key.replace('/', os.sep)))[0]
            claimed[base_no_ext] = lineage_id
            return base_no_ext

    rel_dir = os.path.join(output_root, cloud_item.get('rel_path', ''))
    stem = safe_name(os.path.splitext(cloud_item.get('name', 'item'))[0])
    base = os.path.join(rel_dir, stem)
    cand, n = base, 2
    while claimed.get(cand, lineage_id) != lineage_id:
        cand = '{} ({})'.format(base, n)
        n += 1
    claimed[cand] = lineage_id
    return cand


def build_plan(collected_items, man, output_root):
    """Diff a list of normalized cloud items against the manifest + disk.
    Returns {'plans': [...], 'orphans': [...], 'counts': {...}}. Read-only."""
    claimed = {}
    plans = []
    seen_lineages = set()
    for it in collected_items:
        dest_base = _claim_dest(output_root, it, man, claimed)
        p = plan_item(it, dest_base, man, output_root)
        plans.append(p)
        if it.get('lineage_id'):
            seen_lineages.add(it['lineage_id'])

    # Orphans: manifest records whose lineage was not seen in the cloud this run.
    orphans = []
    for key, rec in man.get('records', {}).items():
        if rec.get('lineage_id') and rec['lineage_id'] not in seen_lineages:
            orphans.append({
                'status': STATUS_ORPHAN,
                'action_default': False,
                'dest_key': key,
                'name': rec.get('display_name'),
                'version_number': rec.get('version_number'),
                'lineage_id': rec.get('lineage_id'),
            })

    counts = {}
    for p in plans:
        counts[p['status']] = counts.get(p['status'], 0) + 1
    if orphans:
        counts[STATUS_ORPHAN] = len(orphans)
    return {'plans': plans, 'orphans': orphans, 'counts': counts}


def make_record(dest_path, output_root, version_id, cloud_item, file_type):
    """Build a manifest record for a freshly-downloaded file."""
    try:
        size = os.path.getsize(dest_path)
        mtime = os.path.getmtime(dest_path)
    except OSError:
        size = mtime = None
    return {
        'lineage_id': cloud_item.get('lineage_id'),
        'version_id': version_id,
        'version_number': version_number_from_id(version_id),
        'file_type': file_type,
        'size': size,
        'local_mtime': mtime,
        'cloud_last_modified': cloud_item.get('last_modified'),
        'downloaded_at': time.time(),
        'project_id': cloud_item.get('project_id'),
        'display_name': cloud_item.get('display_name') or cloud_item.get('name'),
    }


# ======================= OAuth (3-legged) =======================

class _CallbackHandler(BaseHTTPRequestHandler):
    code = None
    error = None

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        if 'code' in qs:
            _CallbackHandler.code = qs['code'][0]
            body = 'Authorization succeeded. You can close this tab and return to the terminal.'
        else:
            _CallbackHandler.error = qs.get('error_description', qs.get('error', ['unknown']))[0]
            body = 'Authorization failed: {}'.format(_CallbackHandler.error)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(('<html><body><h3>%s</h3></body></html>' % body).encode('utf-8'))

    def log_message(self, *args):
        pass  # silence the default http server log


def _load_cached_token():
    if os.path.exists(TOKEN_CACHE):
        try:
            with open(TOKEN_CACHE) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _save_token(tok):
    tok['_obtained_at'] = time.time()
    with open(TOKEN_CACHE, 'w') as f:
        json.dump(tok, f)
    os.chmod(TOKEN_CACHE, 0o600)


def _token_valid(tok):
    if not tok or 'access_token' not in tok:
        return False
    age = time.time() - tok.get('_obtained_at', 0)
    return age < (tok.get('expires_in', 3600) - 120)  # keep a 2-minute buffer


def _refresh_token(tok):
    if not tok or 'refresh_token' not in tok:
        return None
    resp = requests.post(BASE + '/authentication/v2/token', data={
        'grant_type': 'refresh_token',
        'refresh_token': tok['refresh_token'],
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': SCOPES,
    })
    if resp.status_code == 200:
        new = resp.json()
        _save_token(new)
        log('Refreshed access token using the refresh token.')
        return new
    log('Refresh token is invalid; a new login is required.')
    return None


def _interactive_login():
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit('Missing APS_CLIENT_ID / APS_CLIENT_SECRET. Set the env vars or edit the settings in aps_archiver.py.')

    parsed = urlparse(CALLBACK_URL)
    host = parsed.hostname or 'localhost'
    port = parsed.port or 8080

    auth_url = BASE + '/authentication/v2/authorize?' + urlencode({
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': CALLBACK_URL,
        'scope': SCOPES,
    })

    log('Opening the browser to sign in to Autodesk... if it does not pop up, open this manually:\n' + auth_url)
    _CallbackHandler.code = None
    _CallbackHandler.error = None
    server = HTTPServer((host, port), _CallbackHandler)
    webbrowser.open(auth_url)
    while _CallbackHandler.code is None and _CallbackHandler.error is None:
        server.handle_request()
    server.server_close()

    if _CallbackHandler.error:
        sys.exit('Authorization failed: {}'.format(_CallbackHandler.error))

    resp = requests.post(BASE + '/authentication/v2/token', data={
        'grant_type': 'authorization_code',
        'code': _CallbackHandler.code,
        'redirect_uri': CALLBACK_URL,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
    })
    if resp.status_code != 200:
        sys.exit('Token exchange failed {}: {}'.format(resp.status_code, resp.text))
    tok = resp.json()
    _save_token(tok)
    log('Signed in. Token cached to {}'.format(TOKEN_CACHE))
    return tok


def get_token():
    tok = _load_cached_token()
    if _token_valid(tok):
        return tok['access_token']
    refreshed = _refresh_token(tok)
    if refreshed and _token_valid(refreshed):
        return refreshed['access_token']
    return _interactive_login()['access_token']


# The way the token is obtained can be swapped out: the CLI uses get_token (opens a
# browser to log in when there is no token); the Web UI replaces this with a
# "refresh-only, never open a browser" version so it doesn't collide with Flask on
# the callback port.
_token_provider = get_token


def set_token_provider(fn):
    """Let the web backend inject its own token-getter."""
    global _token_provider
    _token_provider = fn


# ======================= REST helper =======================

_session = requests.Session()


def api_get(path, token, params=None, full_url=None, accept_jsonapi=False):
    url = full_url or (BASE + path)
    headers = {'Authorization': 'Bearer ' + token}
    if accept_jsonapi:
        headers['Accept'] = 'application/vnd.api+json'
    for attempt in range(MAX_RETRIES):
        r = _session.get(url, headers=headers, params=params)
        if r.status_code == 401:
            token = _token_provider()
            headers['Authorization'] = 'Bearer ' + token
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            wait = 2 ** attempt
            log('  {} on {} -- retrying in {}s'.format(r.status_code, url, wait))
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError('GET failed after retries: {}'.format(url))


def api_post(path, token, body):
    url = BASE + path
    headers = {'Authorization': 'Bearer ' + token}
    headers.update(JSONAPI_HEADERS)
    for attempt in range(MAX_RETRIES):
        r = _session.post(url, headers=headers, data=json.dumps(body))
        if r.status_code == 401:
            token = _token_provider()
            headers['Authorization'] = 'Bearer ' + token
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        if r.status_code not in (200, 201, 202):
            raise RuntimeError('POST {} -> {}: {}'.format(url, r.status_code, r.text))
        return r.json()
    raise RuntimeError('POST failed after retries: {}'.format(url))


# ======================= Traverse Data Management =======================

def list_hubs(token):
    data = api_get('/project/v1/hubs', token)
    return data.get('data', [])


def list_projects(token, hub_id):
    out, url = [], BASE + '/project/v1/hubs/{}/projects'.format(hub_id)
    while url:
        data = api_get(None, token, full_url=url)
        out.extend(data.get('data', []))
        url = data.get('links', {}).get('next', {}).get('href')
    return out


def get_root_folder(token, hub_id, project_id):
    data = api_get('/project/v1/hubs/{}/projects/{}'.format(hub_id, project_id), token)
    return data['data']['relationships']['rootFolder']['data']['id']


def folder_contents(token, project_id, folder_id):
    """Return (folders, items). Each item carries its tip version id plus the extra
    metadata used for version-aware sync (lineage id, cloud modified time, name)."""
    folders, items = [], []
    url = BASE + '/data/v1/projects/{}/folders/{}/contents'.format(project_id, folder_id)
    while url:
        data = api_get(None, token, full_url=url)
        for obj in data.get('data', []):
            if obj['type'] == 'folders':
                folders.append(obj)
            elif obj['type'] == 'items':
                tip = obj.get('relationships', {}).get('tip', {}).get('data', {})
                attrs = obj.get('attributes', {})
                obj['_tip_version_id'] = tip.get('id')
                # The item id is the version-independent lineage id -- stable across edits,
                # so it is the right anchor for a re-runnable sync manifest.
                obj['_lineage_id'] = obj.get('id')
                obj['_last_modified'] = attrs.get('lastModifiedTime')
                obj['_display_name'] = attrs.get('displayName')
                items.append(obj)
        url = data.get('links', {}).get('next', {}).get('href')
    return folders, items


def version_number_from_id(version_id):
    """Best-effort parse of the human version number from a tip version URN, e.g.
    'urn:adsk.wipprod:fs.file:vf.AbC?version=7' -> 7. Returns None when absent.
    For display only -- change detection always compares the full version_id string."""
    if not version_id:
        return None
    try:
        qs = parse_qs(urlparse(version_id).query)
        v = qs.get('version', [None])[0]
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def download_formats(token, project_id, version_id):
    """List the downloadable formats for a version (e.g. f3d / f3z). Returns a set of format strings."""
    from urllib.parse import quote
    path = '/data/v1/projects/{}/versions/{}/downloadFormats'.format(project_id, quote(version_id, safe=''))
    data = api_get(path, token, accept_jsonapi=True)
    fmts = set()
    attrs = _as_obj(_as_obj(data.get('data')).get('attributes'))
    formats = attrs.get('formats', [])
    if isinstance(formats, dict):
        formats = [dict(v, fileType=k) for k, v in formats.items()]
    for f in formats:
        if isinstance(f, dict) and f.get('fileType'):
            fmts.add(f['fileType'])
    return fmts


def create_download(token, project_id, version_id, file_type):
    """Create a Downloads job; returns the raw POST response (may be a job or a finished download)."""
    body = {
        'jsonapi': {'version': '1.0'},
        'data': {
            'type': 'downloads',
            'attributes': {'format': {'fileType': file_type}},
            'relationships': {
                'source': {'data': {'type': 'versions', 'id': version_id}}
            },
        },
    }
    return api_post('/data/v1/projects/{}/downloads'.format(project_id), token, body)


def _as_obj(x):
    """Coerce a JSON:API node to a dict. Unwraps single-element lists; None/other -> {}.
    The downloads API sometimes returns `data` (and nested nodes) as arrays."""
    if isinstance(x, list):
        return _as_obj(x[0]) if x else {}
    return x if isinstance(x, dict) else {}


def _storage_from_download(dl):
    """Extract (object_id, direct_link) from a 'downloads' resource. Tolerant of lists."""
    dl = _as_obj(dl)
    storage = _as_obj(_as_obj(dl.get('relationships')).get('storage'))
    link = _as_obj(_as_obj(storage.get('meta')).get('link')).get('href')
    oid = _as_obj(storage.get('data')).get('id')
    return oid, link


def resolve_download_storage(token, project_id, post_resp):
    """
    From the create_download response, get the final storage object id
    (urn:adsk.objects:os.object:...) or a direct download link. The response may be:
      - directly type=downloads (already finished)
      - type=jobs / type=downloads with status (needs polling)
    On an unexpected shape, raises with the raw JSON so it can be diagnosed.
    """
    raw = json.dumps(post_resp)[:1200]
    data = _as_obj(post_resp.get('data'))
    dtype = data.get('type')

    if dtype == 'downloads':
        oid, link = _storage_from_download(data)
        if oid or link:
            return oid, link

    job_id = data.get('id')
    self_link = _as_obj(_as_obj(_as_obj(post_resp.get('links')).get('self'))).get('href')
    if not job_id and not self_link:
        raise RuntimeError('unexpected downloads response (no job id / storage): ' + raw)

    deadline = time.time() + JOB_POLL_TIMEOUT
    while time.time() < deadline:
        time.sleep(JOB_POLL_INTERVAL)
        if self_link:
            poll = api_get(None, token, full_url=self_link, accept_jsonapi=True)
        else:
            poll = api_get('/data/v1/projects/{}/downloads/{}'.format(project_id, job_id),
                           token, accept_jsonapi=True)
        pdata = _as_obj(poll.get('data'))
        status = _as_obj(pdata.get('attributes')).get('status')
        if pdata.get('type') == 'downloads':
            oid, link = _storage_from_download(pdata)
            if oid or link:
                return oid, link
        if status in ('failed', 'cancelled'):
            raise RuntimeError('Downloads job failed: ' + json.dumps(poll)[:1200])
        # status == 'processing' / 'inprogress' -> keep waiting
    raise RuntimeError('Downloads job timed out ({}s)'.format(JOB_POLL_TIMEOUT))


def signed_s3_download_url(token, object_id):
    """object_id looks like urn:adsk.objects:os.object:{bucket}/{object}."""
    if not object_id or 'os.object:' not in object_id:
        raise RuntimeError('unexpected storage object id: {!r}'.format(object_id))
    tail = object_id.split('os.object:', 1)[1]
    bucket, obj = tail.split('/', 1)
    from urllib.parse import quote
    path = '/oss/v2/buckets/{}/objects/{}/signeds3download'.format(bucket, quote(obj, safe=''))
    data = api_get(path, token)
    return data.get('url') or data.get('urls', [None])[0]


def download_to(url, dest_path):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with _session.get(url, stream=True) as r:
        r.raise_for_status()
        tmp = dest_path + '.part'
        with open(tmp, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        os.replace(tmp, dest_path)
    return os.path.getsize(dest_path)


def fetch_native(token, project_id, version_id, dest_no_ext, overwrite=False):
    """For one version, pick an available native format and download to dest_no_ext + ext.
    Returns (dest_path, file_type) or (None, available_formats).
    With overwrite=False (default) an existing file is treated as done (filename-based
    skip, backward-compatible). With overwrite=True the file is re-fetched and atomically
    replaced -- used by the version-aware sync when a design changed in the cloud."""
    dest_probe = _existing_local(dest_no_ext)[0]
    if dest_probe and not overwrite:
        return dest_probe, os.path.splitext(dest_probe)[1].lstrip('.')
    fmts = download_formats(token, project_id, version_id)
    chosen = next((f for f in PREFERRED_FORMATS if f in fmts), None)
    if not chosen:
        return None, fmts
    post_resp = create_download(token, project_id, version_id, chosen)
    object_id, direct_link = resolve_download_storage(token, project_id, post_resp)
    url = direct_link or signed_s3_download_url(token, object_id)
    dest = dest_no_ext + '.' + chosen
    if os.path.exists(dest) and not overwrite:
        return dest, chosen   # already exists, treat as done (re-runnable)
    download_to(url, dest)
    return dest, chosen


# ======================= Modes: list / spike / all =======================

def mode_list(token):
    hubs = list_hubs(token)
    log('Found {} hub(s):'.format(len(hubs)))
    for h in hubs:
        hid = h['id']
        hname = h['attributes']['name']
        log('\n[HUB] {}  ({})'.format(hname, hid))
        projs = list_projects(token, hid)
        log('  {} project(s)'.format(len(projs)))
        for p in projs:
            log('  - {}  ({})'.format(p['attributes']['name'], p['id']))


def _iter_all_items(token, hub_id, project_id, folder_id, rel_path):
    """Depth-first traversal, yields (rel_path, item_obj)."""
    folders, items = folder_contents(token, project_id, folder_id)
    for it in items:
        yield rel_path, it
    for fo in folders:
        fname = fo['attributes'].get('displayName') or fo['attributes'].get('name')
        yield from _iter_all_items(token, hub_id, project_id,
                                   fo['id'], rel_path + '/' + safe_name(fname))


def mode_spike(token):
    log('=== SPIKE: validate personal hub is readable + Downloads API yields native files ===\n')
    hubs = list_hubs(token)
    if not hubs:
        log('FAIL (risk 1): APS lists no hubs (the personal hub may not be exposed).')
        return
    log('OK: listed {} hub(s).'.format(len(hubs)))

    tested = 0
    for h in hubs:
        hid, hname = h['id'], h['attributes']['name']
        projs = list_projects(token, hid)
        log('  HUB {} -> {} projects'.format(hname, len(projs)))
        for p in projs:
            if tested >= 2:
                break
            pid = p['id']
            try:
                root = get_root_folder(token, hid, pid)
            except Exception as e:
                log('    failed to read rootFolder {}: {}'.format(p['attributes']['name'], e))
                continue
            for rel, it in _iter_all_items(token, hid, pid, root, safe_name(p['attributes']['name'])):
                vid = it.get('_tip_version_id')
                iname = it['attributes'].get('displayName', 'item')
                if not vid:
                    continue
                log('\n  testing file: {}/{}'.format(rel, iname))
                try:
                    fmts = download_formats(token, pid, vid)
                    log('    downloadFormats -> {}'.format(sorted(fmts) or '(none)'))
                    if not fmts:
                        log('    note: this version has no downloadable formats, trying the next one.')
                        continue
                    dest_base = os.path.join('/tmp/aps_spike', safe_name(iname))
                    dest, ft = fetch_native(token, pid, vid, dest_base)
                    if dest:
                        size = os.path.getsize(dest)
                        log('    OK downloaded: {}  ({} bytes, format {})'.format(dest, size, ft))
                        log('       -> unzip the .f3z to confirm it contains all linked parts (validates risk 2).')
                        tested += 1
                    else:
                        log('    note: no preferred native format available.')
                except Exception as e:
                    log('    FAIL Downloads API: {}'.format(e))
                if tested >= 2:
                    break
            if tested >= 2:
                break
        if tested >= 2:
            break

    log('\n=== SPIKE conclusion ===')
    if tested > 0:
        log('OK: personal hub is readable, and at least {} file(s) completed the Downloads API.'.format(tested))
        log('   Next: manually unzip the .f3z downloaded to /tmp/aps_spike to confirm it')
        log('   contains the linked parts. Once confirmed, run `--all` for the full job.')
    else:
        log('FAIL: no file succeeded. See the errors above; if hubs cannot be listed/read,')
        log('   the personal hub is not reachable over APS -> fall back to Route A + the')
        log('   manual_download_list.txt for manual downloads.')


def _normalize_item(project_id, rel, it):
    """Turn a raw traversal item into the flat dict the plan/sync code consumes."""
    return {
        'project_id': project_id,
        'version_id': it.get('_tip_version_id'),
        'name': it['attributes'].get('displayName', 'item'),
        'rel_path': rel,
        'lineage_id': it.get('_lineage_id') or it.get('id'),
        'last_modified': it.get('_last_modified'),
        'display_name': it.get('_display_name') or it['attributes'].get('displayName'),
    }


def _collect_cloud_items(token):
    """Traverse every hub/project/folder and return a flat list of normalized items
    that have a downloadable tip version. Shared by --all / --dry-run / --sync."""
    collected = []
    for h in list_hubs(token):
        hid = h['id']
        for p in list_projects(token, hid):
            pid = p['id']
            pname = safe_name(p['attributes']['name'])
            try:
                root = get_root_folder(token, hid, pid)
            except Exception as e:
                log('  x project {}: {}'.format(pname, e))
                continue
            for rel, it in _iter_all_items(token, hid, pid, root, pname):
                norm = _normalize_item(pid, rel, it)
                if norm['version_id']:
                    collected.append(norm)
    return collected


def _fmt_ts(ts):
    """Format an epoch seconds float or an ISO string for display; '' when unknown."""
    if ts is None:
        return ''
    if isinstance(ts, str):
        return ts[:19].replace('T', ' ')
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
    except (TypeError, ValueError):
        return ''


def _format_plan_table(plan):
    """Return a human-readable diff table for the CLI --dry-run / --sync summary."""
    order = [STATUS_NEW, STATUS_UPDATED, STATUS_MISSING_LOCAL,
             STATUS_UNVERIFIED, STATUS_UPTODATE]
    label = {STATUS_NEW: 'NEW', STATUS_UPDATED: 'UPDATED',
             STATUS_MISSING_LOCAL: 'MISSING', STATUS_UNVERIFIED: 'UNVERIFIED',
             STATUS_UPTODATE: 'UP-TO-DATE'}
    lines = []
    by_status = {}
    for p in plan['plans']:
        by_status.setdefault(p['status'], []).append(p)
    for st in order:
        rows = by_status.get(st, [])
        if not rows:
            continue
        lines.append('--- {} ({}) ---'.format(label[st], len(rows)))
        for p in rows:
            vnum = 'v{}'.format(p['version_number']) if p['version_number'] else ''
            lines.append('  {:<10} {}/{}'.format(vnum, p['rel_path'], p['name']))
    if plan['orphans']:
        lines.append('--- CLOUD-DELETED / ORPHAN ({}) [kept, never removed] ---'.format(len(plan['orphans'])))
        for o in plan['orphans']:
            lines.append('  {}'.format(o['dest_key']))
    return '\n'.join(lines)


def mode_plan(token, output_root=None):
    """Dry-run: traverse, diff against the manifest, print the plan. Writes nothing."""
    output_root = output_root or OUTPUT_ROOT
    man = load_manifest(output_root)
    log('Scanning cloud and comparing against {} ...'.format(output_root))
    collected = _collect_cloud_items(token)
    plan = build_plan(collected, man, output_root)
    log(_format_plan_table(plan))
    c = plan['counts']
    log('\nSummary: new {} / updated {} / up-to-date {} / missing {} / unverified {} / orphan {}'.format(
        c.get(STATUS_NEW, 0), c.get(STATUS_UPDATED, 0), c.get(STATUS_UPTODATE, 0),
        c.get(STATUS_MISSING_LOCAL, 0), c.get(STATUS_UNVERIFIED, 0), c.get(STATUS_ORPHAN, 0)))
    log('(dry run -- nothing downloaded. Run with --sync to apply.)')
    return plan


def _execute_plan(token, output_root, plan, man, results):
    """Download every plan entry whose default action is 'download', updating the
    manifest incrementally. Shared by mode_sync and (via mode_all) the full run."""
    to_do = [p for p in plan['plans'] if p['action_default']]
    log('Syncing {} file(s) -> {}'.format(len(to_do), output_root))
    for p in to_do:
        overwrite = p['status'] == STATUS_UPDATED
        cloud_item = {
            'lineage_id': p['lineage_id'], 'project_id': p['project_id'],
            'display_name': p['display_name'], 'name': p['name'],
            'last_modified': p['cloud_last_modified'],
        }
        try:
            dest, ft = fetch_native(token, p['project_id'], p['version_id'],
                                    p['dest_base'], overwrite=overwrite)
            if dest:
                results['exported'].append(dest)
                manifest_put(man, _rel_key(output_root, dest),
                             make_record(dest, output_root, p['version_id'], cloud_item, ft))
                save_manifest(output_root, man)
                log('  + [{}] {}/{}  [{}]'.format(p['status'], p['rel_path'], p['name'], ft))
            else:
                results['no_native'].append('{}/{} (formats: {})'.format(
                    p['rel_path'], p['name'], sorted(ft) if isinstance(ft, set) else ft))
                log('  - no native format: {}/{}'.format(p['rel_path'], p['name']))
        except Exception as e:
            results['failed'].append('{}/{}: {}'.format(p['rel_path'], p['name'], e))
            log('  x {}/{}: {}'.format(p['rel_path'], p['name'], e))


def mode_sync(token, output_root=None):
    """Version-aware download: only new/updated/missing files; writes the manifest."""
    output_root = output_root or OUTPUT_ROOT
    os.makedirs(output_root, exist_ok=True)
    man = load_manifest(output_root)
    results = {'exported': [], 'skipped': [], 'failed': [], 'no_native': []}
    collected = _collect_cloud_items(token)
    plan = build_plan(collected, man, output_root)
    c = plan['counts']
    log('Plan: new {} / updated {} / up-to-date {} / missing {} / unverified {} / orphan {}'.format(
        c.get(STATUS_NEW, 0), c.get(STATUS_UPDATED, 0), c.get(STATUS_UPTODATE, 0),
        c.get(STATUS_MISSING_LOCAL, 0), c.get(STATUS_UNVERIFIED, 0), c.get(STATUS_ORPHAN, 0)))
    _execute_plan(token, output_root, plan, man, results)
    save_manifest(output_root, man)

    log_path = os.path.join(output_root, 'export_log.txt')
    with open(log_path, 'w', encoding='utf-8') as fh:
        for key, title in [('exported', 'Synced'), ('no_native', 'No native format'),
                           ('failed', 'Failed')]:
            fh.write('=== {} ({}) ===\n'.format(title, len(results[key])))
            fh.write('\n'.join(map(str, results[key])) + '\n\n')
        if plan['orphans']:
            fh.write('=== Cloud-deleted / orphan ({}) [kept locally] ===\n'.format(len(plan['orphans'])))
            fh.write('\n'.join(o['dest_key'] for o in plan['orphans']) + '\n\n')
    log('\nDone. Synced {} / no-native {} / failed {} / orphan {}\nSee {}'.format(
        len(results['exported']), len(results['no_native']),
        len(results['failed']), len(plan['orphans']), log_path))


def mode_all(token):
    """Full run, now manifest-backed: downloads everything on a fresh backup and
    becomes an incremental sync on re-runs (skips unchanged, re-fetches updated)."""
    mode_sync(token)


# ======================= main =======================

def main():
    ap = argparse.ArgumentParser(description='Automatically download native Fusion files via APS (Route B)')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--spike', action='store_true', help='validate personal hub + Downloads API (run this first)')
    g.add_argument('--list', action='store_true', help='only print the hub/project structure')
    g.add_argument('--all', action='store_true', help='download/sync the entire hub (version-aware, re-runnable)')
    g.add_argument('--sync', action='store_true', help='same as --all: incremental version-aware sync')
    g.add_argument('--dry-run', '--plan', dest='dry_run', action='store_true',
                   help='preview the sync plan (new/updated/etc.) without downloading')
    args = ap.parse_args()

    token = get_token()
    if args.list:
        mode_list(token)
    elif args.spike:
        mode_spike(token)
    elif args.dry_run:
        mode_plan(token)
    elif args.sync or args.all:
        mode_sync(token)


if __name__ == '__main__':
    main()
