#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local Web UI backend (Flask) for Route B.

It wraps the download logic of aps_archiver.py as an HTTP API; the frontend
(static/index.html) provides:
  - one-click browser login (the OAuth callback is handled by this service's
    /api/auth/callback)
  - a tree to browse hub / project / folder and check the items to download
  - a custom download path, run button, live progress
  - results analysis (exported / no native format / failed)
  - one-click retry of failed/missing files

Safety: it inherits aps_archiver's read-only `data:read account:read` scope --
download only, never deletes or modifies any cloud or local file.

Start:
    cd route_b
    pip install -r requirements.txt
    python app.py
    # then open http://localhost:8080 in a browser
"""

import json
import os
import subprocess
import sys
import threading
import time
from urllib.parse import urlencode

import requests
from flask import Flask, jsonify, request, redirect, send_from_directory

import aps_archiver as aps

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.expanduser('~/.aps_archiver_config.json')
PORT = int(os.environ.get('APS_UI_PORT', '8080'))

app = Flask(__name__, static_folder=os.path.join(HERE, 'static'), static_url_path='/static')

# ============================ Config file ============================

def load_config():
    cfg = {
        'client_id': os.environ.get('APS_CLIENT_ID', ''),
        'client_secret': os.environ.get('APS_CLIENT_SECRET', ''),
        'output_root': os.path.expanduser(os.environ.get('APS_OUTPUT_ROOT', '~/Desktop/Fusion_Backup_APS')),
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg.update({k: v for k, v in json.load(f).items() if v})
        except Exception:
            pass
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f)
    os.chmod(CONFIG_PATH, 0o600)


CONFIG = load_config()


def _apply_config_to_aps():
    # Make aps_archiver use the UI-configured keys (refresh token needs client id/secret).
    aps.CLIENT_ID = CONFIG['client_id']
    aps.CLIENT_SECRET = CONFIG['client_secret']
    aps.CALLBACK_URL = 'http://localhost:{}/api/auth/callback'.format(PORT)


_apply_config_to_aps()


# ============================ OAuth (web version) ============================

def web_token():
    """Refresh only, never open a browser. Raises RuntimeError when there is no valid
    token so the frontend can route to login."""
    tok = aps._load_cached_token()
    if aps._token_valid(tok):
        return tok['access_token']
    refreshed = aps._refresh_token(tok)
    if refreshed and aps._token_valid(refreshed):
        return refreshed['access_token']
    raise RuntimeError('NOT_AUTHENTICATED')


# API calls also use this on a 401 (won't accidentally open a browser / collide with the Flask port)
aps.set_token_provider(web_token)


def is_authenticated():
    try:
        web_token()
        return True
    except Exception:
        return False


# ============================ Progress state ============================

LOCK = threading.Lock()
PROGRESS = {
    'running': False, 'cancel': False, 'phase': 'idle',
    'total': 0, 'done': 0, 'current': '',
    'started': None, 'finished': None,
    'output_root': CONFIG['output_root'],
    'results': {'exported': [], 'skipped': [], 'no_native': [], 'failed': []},
}


def _reset_progress(output_root):
    with LOCK:
        PROGRESS.update({
            'running': True, 'cancel': False, 'phase': 'expanding',
            'total': 0, 'done': 0, 'current': '',
            'started': time.time(), 'finished': None,
            'output_root': output_root,
            'results': {'exported': [], 'skipped': [], 'no_native': [], 'failed': []},
        })


# ============================ Download worker ============================

def _expand_targets(token, targets):
    """Expand project / folder / item targets into a flat list of normalized items
    (project_id, version_id, name, rel_path, lineage_id, last_modified, display_name)."""
    items = []
    for t in targets:
        ttype = t.get('type')
        if ttype == 'item':
            items.append({
                'project_id': t['project_id'],
                'version_id': t['version_id'],
                'name': t['name'],
                'rel_path': t['rel_path'],
                'lineage_id': t.get('lineage_id') or t.get('item_id'),
                'last_modified': t.get('last_modified'),
                'display_name': t.get('name'),
            })
        elif ttype == 'folder':
            for rel, it in aps._iter_all_items(token, t.get('hub_id'), t['project_id'],
                                               t['folder_id'], t['rel_path']):
                if it.get('_tip_version_id'):
                    items.append(aps._normalize_item(t['project_id'], rel, it))
        elif ttype == 'project':
            root = aps.get_root_folder(token, t['hub_id'], t['project_id'])
            base = aps.safe_name(t['name'])
            for rel, it in aps._iter_all_items(token, t['hub_id'], t['project_id'], root, base):
                if it.get('_tip_version_id'):
                    items.append(aps._normalize_item(t['project_id'], rel, it))
    return items


def _download_worker(output_root, targets, items=None):
    try:
        token = web_token()
        man = aps.load_manifest(output_root)

        if items is None:
            # Legacy path: expand tree targets and disambiguate deterministically
            # (manifest-seeded) so dest keys match a prior run.
            expanded = _expand_targets(token, targets)
            claimed = {}
            work = []
            for it in expanded:
                dest_base = aps._claim_dest(output_root, it, man, claimed)
                work.append({**it, 'dest_base': dest_base, 'overwrite': False})
        else:
            # Pre-planned path from /api/scan: honor the dest_key the plan keyed on.
            work = []
            for it in items:
                # Prefer the disambiguated base the scan computed (dest_base_rel), so two
                # same-named designs never collide. Fall back to dest_key, then to a derived path.
                base_rel = it.get('dest_base_rel')
                if base_rel:
                    dest_base = os.path.join(output_root, base_rel.replace('/', os.sep))
                elif it.get('dest_key'):
                    dest_base = os.path.splitext(
                        os.path.join(output_root, it['dest_key'].replace('/', os.sep)))[0]
                else:
                    dest_base = os.path.join(output_root, it['rel_path'],
                                             aps.safe_name(os.path.splitext(it['name'])[0]))
                work.append({**it, 'dest_base': dest_base,
                             'overwrite': bool(it.get('overwrite'))})

        with LOCK:
            PROGRESS['total'] = len(work)
            PROGRESS['phase'] = 'downloading'

        for it in work:
            with LOCK:
                if PROGRESS['cancel']:
                    break
                PROGRESS['current'] = '{}/{}'.format(it['rel_path'], it['name'])
            dest_base = it['dest_base']
            entry = {'name': it['name'], 'rel_path': it['rel_path'],
                     'project_id': it['project_id'], 'version_id': it['version_id']}
            try:
                already = aps._existing_local(dest_base)[0] is not None
                dest, ft = aps.fetch_native(token, it['project_id'], it['version_id'],
                                            dest_base, overwrite=it['overwrite'])
                if dest:
                    entry.update({'dest': dest, 'file_type': ft, 'size': os.path.getsize(dest)})
                    downloaded = it['overwrite'] or not already
                    bucket = 'exported' if downloaded else 'skipped'
                    if downloaded:
                        cloud_item = {'lineage_id': it.get('lineage_id'),
                                      'project_id': it['project_id'],
                                      'display_name': it.get('display_name') or it['name'],
                                      'name': it['name'],
                                      'last_modified': it.get('last_modified')}
                        with LOCK:
                            aps.manifest_put(man, aps._rel_key(output_root, dest),
                                             aps.make_record(dest, output_root,
                                                             it['version_id'], cloud_item, ft))
                            aps.save_manifest(output_root, man)
                    with LOCK:
                        PROGRESS['results'][bucket].append(entry)
                else:
                    entry['formats'] = sorted(ft) if isinstance(ft, set) else []
                    with LOCK:
                        PROGRESS['results']['no_native'].append(entry)
            except Exception as e:
                entry['error'] = str(e)
                with LOCK:
                    PROGRESS['results']['failed'].append(entry)
            with LOCK:
                PROGRESS['done'] += 1

        with LOCK:
            aps.save_manifest(output_root, man)
        _write_log(output_root)
    except Exception as e:
        with LOCK:
            PROGRESS['results']['failed'].append({'name': '(overall process)', 'error': str(e)})
    finally:
        with LOCK:
            PROGRESS['running'] = False
            PROGRESS['phase'] = 'cancelled' if PROGRESS['cancel'] else 'done'
            PROGRESS['finished'] = time.time()


def _write_log(output_root):
    try:
        os.makedirs(output_root, exist_ok=True)
        path = os.path.join(output_root, 'export_log.txt')
        r = PROGRESS['results']
        with open(path, 'w', encoding='utf-8') as fh:
            for key, title in [('exported', 'Exported'), ('skipped', 'Already exists (skipped)'),
                               ('no_native', 'No native format'), ('failed', 'Failed')]:
                fh.write('=== {} ({}) ===\n'.format(title, len(r[key])))
                for e in r[key]:
                    line = '{}/{}'.format(e.get('rel_path', ''), e.get('name', ''))
                    if e.get('error'):
                        line += '  ERROR: ' + e['error']
                    fh.write(line + '\n')
                fh.write('\n')
    except Exception:
        pass


# ============================ Routes: page ============================

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


# ============================ Routes: config ============================

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({
        'client_id': CONFIG['client_id'],
        'has_secret': bool(CONFIG['client_secret']),
        'output_root': CONFIG['output_root'],
        'callback_url': aps.CALLBACK_URL,
        'authenticated': is_authenticated(),
    })


@app.route('/api/config', methods=['POST'])
def set_config():
    body = request.get_json(force=True)
    if 'client_id' in body:
        CONFIG['client_id'] = body['client_id'].strip()
    if body.get('client_secret'):
        CONFIG['client_secret'] = body['client_secret'].strip()
    if 'output_root' in body:
        CONFIG['output_root'] = os.path.expanduser(body['output_root'].strip())
    save_config(CONFIG)
    _apply_config_to_aps()
    return jsonify({'ok': True})


@app.route('/api/pick-folder', methods=['POST'])
def pick_folder():
    """Open a native folder picker on this machine (the server runs locally) and return the path."""
    try:
        if sys.platform == 'darwin':
            script = ('POSIX path of (choose folder with prompt '
                      '"Choose where to save your Fusion backup")')
            r = subprocess.run(['osascript', '-e', script],
                               capture_output=True, text=True, timeout=180)
            path = r.stdout.strip()
            if path:
                return jsonify({'path': path.rstrip('/')})
            return jsonify({'cancelled': True})
        else:
            # tkinter fallback for Windows / Linux
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.askdirectory()
            root.destroy()
            if path:
                return jsonify({'path': path})
            return jsonify({'cancelled': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================ Routes: OAuth ============================

@app.route('/api/auth/login')
def auth_login():
    if not CONFIG['client_id'] or not CONFIG['client_secret']:
        return 'Client ID / Secret not set yet. Fill them in under "Settings" on the home page first.', 400
    auth_url = aps.BASE + '/authentication/v2/authorize?' + urlencode({
        'response_type': 'code',
        'client_id': CONFIG['client_id'],
        'redirect_uri': aps.CALLBACK_URL,
        'scope': aps.SCOPES,
    })
    return redirect(auth_url)


@app.route('/api/auth/callback')
def auth_callback():
    code = request.args.get('code')
    if not code:
        return 'Authorization failed: {}'.format(request.args.get('error_description', 'no code')), 400
    resp = requests.post(aps.BASE + '/authentication/v2/token', data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': aps.CALLBACK_URL,
        'client_id': CONFIG['client_id'],
        'client_secret': CONFIG['client_secret'],
    })
    if resp.status_code != 200:
        return 'Token exchange failed {}: {}'.format(resp.status_code, resp.text), 400
    aps._save_token(resp.json())
    return redirect('/')


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    try:
        if os.path.exists(aps.TOKEN_CACHE):
            os.remove(aps.TOKEN_CACHE)
    except Exception:
        pass
    return jsonify({'ok': True})


@app.route('/api/wipe', methods=['POST'])
def api_wipe():
    """Remove the locally stored token AND the saved Client ID/Secret (full cleanup)."""
    for p in (aps.TOKEN_CACHE, CONFIG_PATH):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    CONFIG['client_id'] = ''
    CONFIG['client_secret'] = ''
    _apply_config_to_aps()
    return jsonify({'ok': True})


# ============================ Routes: browse data ============================

def _auth_guard():
    if not is_authenticated():
        return jsonify({'error': 'NOT_AUTHENTICATED'}), 401
    return None


@app.route('/api/hubs')
def api_hubs():
    g = _auth_guard()
    if g:
        return g
    token = web_token()
    hubs = [{'id': h['id'], 'name': h['attributes']['name']} for h in aps.list_hubs(token)]
    return jsonify({'hubs': hubs})


@app.route('/api/projects')
def api_projects():
    g = _auth_guard()
    if g:
        return g
    token = web_token()
    hub_id = request.args['hub_id']
    projs = [{'id': p['id'], 'name': p['attributes']['name']}
             for p in aps.list_projects(token, hub_id)]
    return jsonify({'projects': projs})


@app.route('/api/contents')
def api_contents():
    g = _auth_guard()
    if g:
        return g
    token = web_token()
    hub_id = request.args.get('hub_id')
    project_id = request.args['project_id']
    folder_id = request.args.get('folder_id')
    if not folder_id:
        folder_id = aps.get_root_folder(token, hub_id, project_id)
    folders, items = aps.folder_contents(token, project_id, folder_id)
    return jsonify({
        'folder_id': folder_id,
        'folders': [{'id': f['id'],
                     'name': f['attributes'].get('displayName') or f['attributes'].get('name')}
                    for f in folders],
        'items': [{'id': it['id'],
                   'name': it['attributes'].get('displayName', 'item'),
                   'version_id': it.get('_tip_version_id'),
                   'lineage_id': it.get('_lineage_id') or it['id'],
                   'last_modified': it.get('_last_modified')}
                  for it in items],
    })


# ============================ Routes: scan / compare ============================

@app.route('/api/scan', methods=['POST'])
def api_scan():
    """FreeFileSync-style compare: diff the selected cloud targets against the local
    folder + manifest and return a categorized plan. Read-only, synchronous."""
    g = _auth_guard()
    if g:
        return g
    body = request.get_json(force=True)
    targets = body.get('targets', [])
    if not targets:
        return jsonify({'error': 'No items selected'}), 400
    output_root = os.path.expanduser(body.get('output_root') or CONFIG['output_root'])
    token = web_token()
    collected = _expand_targets(token, targets)
    man = aps.load_manifest(output_root)
    plan = aps.build_plan(collected, man, output_root)
    # Keep only the display-relevant fields (dest_base is an absolute local path).
    keep = ('status', 'action_default', 'dest_key', 'dest_base_rel', 'version_id',
            'version_number', 'recorded_version_number', 'lineage_id', 'project_id', 'name',
            'rel_path', 'display_name', 'cloud_last_modified', 'local_mtime', 'local_size', 'file_type')
    plans = [{k: p.get(k) for k in keep} for p in plan['plans']]
    return jsonify({'plans': plans, 'orphans': plan['orphans'],
                    'counts': plan['counts'], 'output_root': output_root})


# ============================ Routes: download / progress ============================

@app.route('/api/download', methods=['POST'])
def api_download():
    g = _auth_guard()
    if g:
        return g
    with LOCK:
        if PROGRESS['running']:
            return jsonify({'error': 'A download is already in progress'}), 409
    body = request.get_json(force=True)
    targets = body.get('targets', [])
    items = body.get('items')  # pre-planned rows from /api/scan (each may carry overwrite/dest_key)
    if not targets and not items:
        return jsonify({'error': 'No items selected'}), 400
    output_root = os.path.expanduser(body.get('output_root') or CONFIG['output_root'])
    _reset_progress(output_root)
    threading.Thread(target=_download_worker, args=(output_root, targets),
                     kwargs={'items': items}, daemon=True).start()
    return jsonify({'ok': True})


@app.route('/api/progress')
def api_progress():
    with LOCK:
        return jsonify(dict(PROGRESS))


@app.route('/api/cancel', methods=['POST'])
def api_cancel():
    with LOCK:
        PROGRESS['cancel'] = True
    return jsonify({'ok': True})


if __name__ == '__main__':
    url = 'http://localhost:{}'.format(PORT)
    print('APS Archiver UI started: ' + url)
    print('(OAuth callback is set to {})'.format(aps.CALLBACK_URL))
    print('The browser will open automatically; if not, open the URL above. To stop, close this window or press Ctrl+C.')
    # Open the browser automatically after startup (disable with APS_NO_BROWSER=1)
    if os.environ.get('APS_NO_BROWSER') != '1':
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host='127.0.0.1', port=PORT, threaded=True)
