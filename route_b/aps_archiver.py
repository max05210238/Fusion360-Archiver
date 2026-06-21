#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路線 B — 用 APS (Autodesk Platform Services / 舊稱 Forge) Data Management API
        全自動下載整個個人 hub 的「原生 Fusion 檔」（含組立件 f3z）。

為什麼這條路能拿到 Fusion 內建 API 拿不到的東西：
    我們不直接抓雲端 raw storage 物件，而是用官方 Downloads API：
        GET  .../versions/{ver}/downloadFormats   列出該版本可下載格式（f3d / f3z）
        POST .../projects/{proj}/downloads         指定格式建立下載 job
        poll .../projects/{proj}/jobs|downloads/{id}
        最後拿到 storage 物件 -> signed S3 下載
    官方產出的 f3z 會「打包組立件的所有 linked components」，
    所以這條路連組立件都能拿到可重新上傳的原生檔。

⚠️ 個人 hub（A360 Personal）在 APS 的可見性歷來偶有限制 —— 這是本路線唯一真風險。
   先用 `--spike` 模式驗證：能列出 project + 能對 1 個檔成功跑完 Downloads API，
   再用 `--all` 跑整套。

需求：
    pip install -r requirements.txt   (只需 requests)
    在 https://aps.autodesk.com 建一個 App，拿 Client ID / Secret，
    把 Callback URL 設成與下方 CALLBACK_URL 完全一致（預設
    http://localhost:8080/api/auth/callback）。

設定（環境變數，或直接改下方常數）：
    APS_CLIENT_ID, APS_CLIENT_SECRET, APS_CALLBACK_URL, APS_OUTPUT_ROOT

用法：
    python aps_archiver.py --spike     # 驗證個人 hub + Downloads API（先跑這個）
    python aps_archiver.py --list      # 只列出 hub/project/folder/item 樹狀結構
    python aps_archiver.py --all       # 全自動下載，保留結構，可重跑

官方文件（細節以現行版為準）：
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
    sys.exit('需要 requests：請先執行  pip install -r requirements.txt')

# ============================ 設定區 ============================

CLIENT_ID     = os.environ.get('APS_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('APS_CLIENT_SECRET', '')
CALLBACK_URL  = os.environ.get('APS_CALLBACK_URL', 'http://localhost:8080/api/auth/callback')
OUTPUT_ROOT   = os.path.expanduser(os.environ.get('APS_OUTPUT_ROOT', '~/Desktop/Fusion_Backup_APS'))

SCOPES   = 'data:read account:read'
BASE     = 'https://developer.api.autodesk.com'
TOKEN_CACHE = os.path.expanduser('~/.aps_archiver_token.json')

# 想拿到的原生格式，依優先序嘗試（組立件通常只有 f3z，單體有 f3d）。
PREFERRED_FORMATS = ['f3z', 'f3d']

# 連線重試
MAX_RETRIES = 4
JOB_POLL_TIMEOUT = 300   # 單檔 Downloads job 最長等待秒數
JOB_POLL_INTERVAL = 3

JSONAPI_HEADERS = {'Content-Type': 'application/vnd.api+json'}

# ============================ 小工具 ============================

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
            body = '授權成功，可關閉此分頁回到終端機。'
        else:
            _CallbackHandler.error = qs.get('error_description', qs.get('error', ['unknown']))[0]
            body = '授權失敗：{}'.format(_CallbackHandler.error)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(('<html><body><h3>%s</h3></body></html>' % body).encode('utf-8'))

    def log_message(self, *args):
        pass  # 靜音 http server 預設 log


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
    return age < (tok.get('expires_in', 3600) - 120)  # 留 2 分鐘 buffer


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
        log('已用 refresh token 換到新 access token。')
        return new
    log('refresh token 失效，需重新登入。')
    return None


def _interactive_login():
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit('缺少 APS_CLIENT_ID / APS_CLIENT_SECRET，請先設定環境變數或改 aps_archiver.py 設定區。')

    parsed = urlparse(CALLBACK_URL)
    host = parsed.hostname or 'localhost'
    port = parsed.port or 8080

    auth_url = BASE + '/authentication/v2/authorize?' + urlencode({
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': CALLBACK_URL,
        'scope': SCOPES,
    })

    log('開啟瀏覽器登入 Autodesk…如果沒自動跳出，手動開啟：\n' + auth_url)
    _CallbackHandler.code = None
    _CallbackHandler.error = None
    server = HTTPServer((host, port), _CallbackHandler)
    webbrowser.open(auth_url)
    while _CallbackHandler.code is None and _CallbackHandler.error is None:
        server.handle_request()
    server.server_close()

    if _CallbackHandler.error:
        sys.exit('授權失敗：{}'.format(_CallbackHandler.error))

    resp = requests.post(BASE + '/authentication/v2/token', data={
        'grant_type': 'authorization_code',
        'code': _CallbackHandler.code,
        'redirect_uri': CALLBACK_URL,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
    })
    if resp.status_code != 200:
        sys.exit('換 token 失敗 {}：{}'.format(resp.status_code, resp.text))
    tok = resp.json()
    _save_token(tok)
    log('登入成功，token 已快取到 {}'.format(TOKEN_CACHE))
    return tok


def get_token():
    tok = _load_cached_token()
    if _token_valid(tok):
        return tok['access_token']
    refreshed = _refresh_token(tok)
    if refreshed and _token_valid(refreshed):
        return refreshed['access_token']
    return _interactive_login()['access_token']


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
            token = get_token()
            headers['Authorization'] = 'Bearer ' + token
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            wait = 2 ** attempt
            log('  {} on {} — {}s 後重試'.format(r.status_code, url, wait))
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError('GET 重試多次仍失敗：{}'.format(url))


def api_post(path, token, body):
    url = BASE + path
    headers = {'Authorization': 'Bearer ' + token}
    headers.update(JSONAPI_HEADERS)
    for attempt in range(MAX_RETRIES):
        r = _session.post(url, headers=headers, data=json.dumps(body))
        if r.status_code == 401:
            token = get_token()
            headers['Authorization'] = 'Bearer ' + token
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        if r.status_code not in (200, 201, 202):
            raise RuntimeError('POST {} -> {}：{}'.format(url, r.status_code, r.text))
        return r.json()
    raise RuntimeError('POST 重試多次仍失敗：{}'.format(url))


# ======================= 遍歷 Data Management =======================

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
    """回傳 (folders, items)。items 每筆附帶 tip 版本 id。"""
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
    """列出該版本可下載格式（如 f3d / f3z）。回傳格式字串集合。"""
    from urllib.parse import quote
    path = '/data/v1/projects/{}/versions/{}/downloadFormats'.format(project_id, quote(version_id, safe=''))
    data = api_get(path, token, accept_jsonapi=True)
    fmts = set()
    attrs = data.get('data', {}).get('attributes', {})
    for f in attrs.get('formats', []):
        if f.get('fileType'):
            fmts.add(f['fileType'])
    return fmts


def create_download(token, project_id, version_id, file_type):
    """建立 Downloads job，回傳 POST 的原始回應（可能是 job 或直接 download）。"""
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


def resolve_download_storage(token, project_id, post_resp):
    """
    從 create_download 的回應拿到最終 storage 物件 id（urn:adsk.objects:os.object:...）。
    回應可能是：
      - 直接 type=downloads（已完成）
      - type=jobs（需輪詢）
    """
    data = post_resp.get('data', {})
    dtype = data.get('type')

    def storage_from_download(dl):
        rel = dl.get('relationships', {}).get('storage', {})
        # 優先用直接下載連結
        link = rel.get('meta', {}).get('link', {}).get('href')
        oid = rel.get('data', {}).get('id')
        return oid, link

    if dtype == 'downloads':
        return storage_from_download(data)

    # 走 job 輪詢：用回應裡的 self link，否則組 /downloads/{id}
    job_id = data.get('id')
    self_link = post_resp.get('links', {}).get('self', {}).get('href')
    deadline = time.time() + JOB_POLL_TIMEOUT
    while time.time() < deadline:
        time.sleep(JOB_POLL_INTERVAL)
        if self_link:
            poll = api_get(None, token, full_url=self_link, accept_jsonapi=True)
        else:
            poll = api_get('/data/v1/projects/{}/downloads/{}'.format(project_id, job_id),
                           token, accept_jsonapi=True)
        pdata = poll.get('data', {})
        status = pdata.get('attributes', {}).get('status')
        if pdata.get('type') == 'downloads' and pdata.get('relationships', {}).get('storage'):
            return storage_from_download(pdata)
        if status in ('failed', 'cancelled'):
            raise RuntimeError('Downloads job 失敗：{}'.format(json.dumps(pdata)))
        # status == 'processing' / 'inprogress' -> 繼續等
    raise RuntimeError('Downloads job 等待逾時（{}s）'.format(JOB_POLL_TIMEOUT))


def signed_s3_download_url(token, object_id):
    """object_id 形如 urn:adsk.objects:os.object:{bucket}/{object}。"""
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
    """對一個版本，挑可用原生格式下載到 dest_no_ext + 副檔名。回傳 (dest_path, file_type) 或 None。"""
    fmts = download_formats(token, project_id, version_id)
    chosen = next((f for f in PREFERRED_FORMATS if f in fmts), None)
    if not chosen:
        return None, fmts
    post_resp = create_download(token, project_id, version_id, chosen)
    object_id, direct_link = resolve_download_storage(token, project_id, post_resp)
    url = direct_link or signed_s3_download_url(token, object_id)
    dest = dest_no_ext + '.' + chosen
    if os.path.exists(dest):
        return dest, chosen   # 已存在，視為完成（可重跑）
    download_to(url, dest)
    return dest, chosen


# ======================= 模式：list / spike / all =======================

def mode_list(token):
    hubs = list_hubs(token)
    log('找到 {} 個 hub：'.format(len(hubs)))
    for h in hubs:
        hid = h['id']
        hname = h['attributes']['name']
        log('\n[HUB] {}  ({})'.format(hname, hid))
        projs = list_projects(token, hid)
        log('  {} 個 project'.format(len(projs)))
        for p in projs:
            log('  - {}  ({})'.format(p['attributes']['name'], p['id']))


def _iter_all_items(token, hub_id, project_id, folder_id, rel_path):
    """深度遍歷，yield (rel_path, item_obj)。"""
    folders, items = folder_contents(token, project_id, folder_id)
    for it in items:
        yield rel_path, it
    for fo in folders:
        fname = fo['attributes'].get('displayName') or fo['attributes'].get('name')
        yield from _iter_all_items(token, hub_id, project_id,
                                   fo['id'], rel_path + '/' + safe_name(fname))


def mode_spike(token):
    log('=== SPIKE：驗證個人 hub 可讀 + Downloads API 可產原生檔 ===\n')
    hubs = list_hubs(token)
    if not hubs:
        log('❌ 風險點 1 失敗：APS 列不出任何 hub（個人 hub 可能不開放）。')
        return
    log('✅ 可列出 {} 個 hub。'.format(len(hubs)))

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
                log('    讀 rootFolder 失敗 {}: {}'.format(p['attributes']['name'], e))
                continue
            for rel, it in _iter_all_items(token, hid, pid, root, safe_name(p['attributes']['name'])):
                vid = it.get('_tip_version_id')
                iname = it['attributes'].get('displayName', 'item')
                if not vid:
                    continue
                log('\n  測試檔：{}/{}'.format(rel, iname))
                try:
                    fmts = download_formats(token, pid, vid)
                    log('    downloadFormats -> {}'.format(sorted(fmts) or '（無）'))
                    if not fmts:
                        log('    ⚠️ 此版本無可下載格式，換下一個。')
                        continue
                    dest_base = os.path.join('/tmp/aps_spike', safe_name(iname))
                    dest, ft = fetch_native(token, pid, vid, dest_base)
                    if dest:
                        size = os.path.getsize(dest)
                        log('    ✅ 下載成功：{}  ({} bytes, 格式 {})'.format(dest, size, ft))
                        log('       -> 解開 .f3z 確認是否含全部 linked 零件，即驗證風險點 2。')
                        tested += 1
                    else:
                        log('    ⚠️ 無偏好原生格式可下載。')
                except Exception as e:
                    log('    ❌ Downloads API 失敗：{}'.format(e))
                if tested >= 2:
                    break
            if tested >= 2:
                break
        if tested >= 2:
            break

    log('\n=== SPIKE 結論 ===')
    if tested > 0:
        log('✅ 個人 hub 可讀，且至少 {} 個檔成功跑完 Downloads API。'.format(tested))
        log('   下一步：手動解開下載到 /tmp/aps_spike 的 .f3z 確認含 linked 零件，')
        log('   通過後即可放心用 `--all` 全自動跑整套。')
    else:
        log('❌ 沒有任何檔成功。請看上面錯誤；若是 hub 列不出/讀不到，')
        log('   個人 hub APS 不通 -> 退回路線 A + 照 manual_download_list.txt 手動下載。')


def mode_all(token):
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    results = {'exported': [], 'skipped': [], 'failed': [], 'no_native': []}
    hubs = list_hubs(token)
    log('開始全量下載，{} 個 hub -> {}'.format(len(hubs), OUTPUT_ROOT))

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
                    results['skipped'].append('{}/{} (無 tip 版本)'.format(rel, iname))
                    continue
                try:
                    dest, ft = fetch_native(token, pid, vid, dest_base)
                    if dest:
                        results['exported'].append(dest)
                        log('  ✓ {}  [{}]'.format(dest, ft))
                    else:
                        results['no_native'].append('{}/{} (可用格式: {})'.format(rel, iname, sorted(ft)))
                        log('  - 無原生格式：{}/{}'.format(rel, iname))
                except Exception as e:
                    results['failed'].append('{}/{}: {}'.format(rel, iname, e))
                    log('  ✗ {}/{}: {}'.format(rel, iname, e))

    log_path = os.path.join(OUTPUT_ROOT, 'export_log.txt')
    with open(log_path, 'w', encoding='utf-8') as fh:
        for key, title in [('exported', '成功'), ('skipped', '跳過'),
                           ('no_native', '無原生格式'), ('failed', '失敗')]:
            fh.write('=== {} ({}) ===\n'.format(title, len(results[key])))
            fh.write('\n'.join(map(str, results[key])) + '\n\n')
    log('\n完成。成功 {} / 跳過 {} / 無原生 {} / 失敗 {}\n詳見 {}'.format(
        len(results['exported']), len(results['skipped']),
        len(results['no_native']), len(results['failed']), log_path))


# ======================= main =======================

def main():
    ap = argparse.ArgumentParser(description='APS 全自動下載 Fusion 原生檔（路線 B）')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--spike', action='store_true', help='驗證個人 hub + Downloads API（先跑這個）')
    g.add_argument('--list', action='store_true', help='只列出 hub/project 結構')
    g.add_argument('--all', action='store_true', help='全自動下載整個 hub')
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
