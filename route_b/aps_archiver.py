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
    """Return (folders, items). Each item carries its tip version id."""
    folders, items = [], []
    url = BASE + '/data/v1/projects/{}/folders/{}/contents'.format(project_id, folder_id)
    while url:
        data = api_get(None, token, full_url=url)
        for obj in data.get('data', []):
            if obj['type'] == 'folders':
                folders.append(obj)
            elif obj['type'] == 'items':
                tip = obj.get('relationships', {}).get('tip', {}).get('data', {})
                obj['_tip_version_id'] = tip.get('id')
                items.append(obj)
        url = data.get('links', {}).get('next', {}).get('href')
    return folders, items


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


def fetch_native(token, project_id, version_id, dest_no_ext):
    """For one version, pick an available native format and download to dest_no_ext + ext.
    Returns (dest_path, file_type) or (None, available_formats)."""
    fmts = download_formats(token, project_id, version_id)
    chosen = next((f for f in PREFERRED_FORMATS if f in fmts), None)
    if not chosen:
        return None, fmts
    post_resp = create_download(token, project_id, version_id, chosen)
    object_id, direct_link = resolve_download_storage(token, project_id, post_resp)
    url = direct_link or signed_s3_download_url(token, object_id)
    dest = dest_no_ext + '.' + chosen
    if os.path.exists(dest):
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


def mode_all(token):
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    results = {'exported': [], 'skipped': [], 'failed': [], 'no_native': []}
    hubs = list_hubs(token)
    log('Starting full download, {} hub(s) -> {}'.format(len(hubs), OUTPUT_ROOT))

    for h in hubs:
        hid, hname = h['id'], h['attributes']['name']
        for p in list_projects(token, hid):
            pid = p['id']
            pname = safe_name(p['attributes']['name'])
            try:
                root = get_root_folder(token, hid, pid)
            except Exception as e:
                results['failed'].append('project {}: {}'.format(pname, e))
                continue
            for rel, it in _iter_all_items(token, hid, pid, root, pname):
                vid = it.get('_tip_version_id')
                iname = it['attributes'].get('displayName', 'item')
                rel_dir = os.path.join(OUTPUT_ROOT, rel)
                dest_base = os.path.join(rel_dir, safe_name(os.path.splitext(iname)[0]))
                if not vid:
                    results['skipped'].append('{}/{} (no tip version)'.format(rel, iname))
                    continue
                try:
                    dest, ft = fetch_native(token, pid, vid, dest_base)
                    if dest:
                        results['exported'].append(dest)
                        log('  + {}  [{}]'.format(dest, ft))
                    else:
                        results['no_native'].append('{}/{} (available formats: {})'.format(rel, iname, sorted(ft)))
                        log('  - no native format: {}/{}'.format(rel, iname))
                except Exception as e:
                    results['failed'].append('{}/{}: {}'.format(rel, iname, e))
                    log('  x {}/{}: {}'.format(rel, iname, e))

    log_path = os.path.join(OUTPUT_ROOT, 'export_log.txt')
    with open(log_path, 'w', encoding='utf-8') as fh:
        for key, title in [('exported', 'Exported'), ('skipped', 'Skipped'),
                           ('no_native', 'No native format'), ('failed', 'Failed')]:
            fh.write('=== {} ({}) ===\n'.format(title, len(results[key])))
            fh.write('\n'.join(map(str, results[key])) + '\n\n')
    log('\nDone. Exported {} / skipped {} / no-native {} / failed {}\nSee {}'.format(
        len(results['exported']), len(results['skipped']),
        len(results['no_native']), len(results['failed']), log_path))


# ======================= main =======================

def main():
    ap = argparse.ArgumentParser(description='Automatically download native Fusion files via APS (Route B)')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--spike', action='store_true', help='validate personal hub + Downloads API (run this first)')
    g.add_argument('--list', action='store_true', help='only print the hub/project structure')
    g.add_argument('--all', action='store_true', help='download the entire hub automatically')
    args = ap.parse_args()

    token = get_token()
    if args.list:
        mode_list(token)
    elif args.spike:
        mode_spike(token)
    elif args.all:
        mode_all(token)


if __name__ == '__main__':
    main()
