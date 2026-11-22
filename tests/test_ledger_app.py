"""YeYe가계부 앱 파일(ledger_app.py): 관리자만 APK를 올림 → APK 안에서 패키지·버전을 읽어 확인(다른 앱·APK 아닌 파일·낮은 버전은 거절)
→ 가계부에 로그인한 사람은 누구나 받음(파일 이름에 버전), 로그인 없으면 못 받음"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, json, io, zipfile, urllib.request, urllib.error, urllib.parse
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LEDGER_ADMIN_NAME='임기범')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, ledger_app

APK = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'ledger-notify-1.0.apk'), 'rb').read()

# ---- APK 안의 바이너리 XML에서 패키지·버전 읽기
with zipfile.ZipFile(io.BytesIO(APK)) as z:
    assert ledger_app.read_manifest(z.read('AndroidManifest.xml')) == {'package': 'kr.home.ledgernotify', 'versionCode': 1, 'versionName': '1.0'}
for bad in (b'', b'\x03\x00\x08\x00', b'<?xml version="1.0"?><manifest/>'):
    try:
        ledger_app.read_manifest(bad)
        raise AssertionError(bad)
    except ledger_app.AppFileError:
        pass

storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'


def req(path, data=None, cookie='', ctype='application/json'):
    r = urllib.request.Request(BASE + path, data=data, method='POST' if data is not None else 'GET', headers={'Content-Type': ctype, 'Cookie': cookie})
    try:
        with urllib.request.urlopen(r) as res:
            return res.status, res.read(), res.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def upload(data, cookie=''):
    code, body, _ = req('/api/ledger/app-upload', data, cookie, 'application/octet-stream')
    return code, json.loads(body or b'{}')


def login(name, password):
    code, _, h = req('/api/ledger/session', json.dumps({'action': 'login', 'name': name, 'password': password}).encode())
    assert code == 200
    return (h.get('Set-Cookie') or '').split(';')[0]


admin = login('임기범', 'Secr3t!')
assert req('/api/ledger/session', json.dumps({'action': 'signup', 'name': '지은', 'password': 'pw12'}).encode())[0] == 200
jieun = json.loads(req('/api/ledger/admin', cookie=admin)[1])['pending'][0]['id']
req('/api/ledger/admin', json.dumps({'action': 'approve', 'user_id': jieun}).encode(), admin)
user = login('지은', 'pw12')

# ---- 처음엔 없음, 받기 404
assert json.loads(req('/api/ledger/app', cookie=user)[1])['app'] is None
assert json.loads(req('/api/ledger/inbox', cookie=user)[1])['app'] is None
assert req('/api/ledger/app.apk', cookie=user)[0] == 404

# ---- 올리기: 로그인 없으면 401, 관리자가 아니면 403, APK가 아니면 400
assert upload(APK)[0] == 401
assert upload(APK, user)[0] == 403
code, data = upload(b'hello', admin)
assert code == 400 and 'APK' in data['message'], data
buf = io.BytesIO()
with zipfile.ZipFile(buf, 'w') as z:
    z.writestr('AndroidManifest.xml', b'not binary xml')
    z.writestr('classes.dex', b'dex')
code, data = upload(buf.getvalue(), admin)
assert code == 400 and '읽지 못했어요' in data['message'], data
assert not os.path.exists(ledger_app.APK_FILE)

# ---- 관리자가 올림 → 모두 받음 (버전이 든 파일 이름, 같은 내용)
code, data = upload(APK, admin)
assert code == 200 and data['app']['versionName'] == '1.0' and data['app']['size'] == len(APK) and data['app']['uploaded_by'] == '임기범', data
info = json.loads(req('/api/ledger/inbox', cookie=user)[1])['app']
assert info['versionCode'] == 1 and len(info['sha256']) == 64, info
code, body, h = req('/api/ledger/app.apk', cookie=user)
assert code == 200 and body == APK and h['Content-Type'] == 'application/vnd.android.package-archive', h
assert "filename*=UTF-8''" + urllib.parse.quote('YeYe가계부-1.0.apk') in h['Content-Disposition'], h['Content-Disposition']
assert req('/api/ledger/app.apk')[0] == 401                      # 로그인 없으면 못 받음
# 앱이 연결 전에 가계부 로그인(쿠키)으로 새 버전 확인
assert req('/api/ledger/app')[0] == 401
assert json.loads(req('/api/ledger/app', cookie=user)[1])['app'] == {k: info[k] for k in ('versionCode', 'versionName', 'size', 'sha256')}

# ---- 앱이 연결 주소(키)로 새 버전 확인·받기 (쿠키 없이)
hook = json.loads(req('/api/ledger/hook-key', json.dumps({'action': 'create'}).encode(), user)[1])['url'][len(BASE):]
code, body, _ = req(hook + '/app')
assert code == 200 and json.loads(body)['app'] == {k: info[k] for k in ('versionCode', 'versionName', 'size', 'sha256')}, body
code, body, h = req(hook + '/app.apk')
assert code == 200 and body == APK and urllib.parse.quote('YeYe가계부-1.0.apk') in h['Content-Disposition']
assert req(hook + '/other')[0] == 404 and req('/api/ledger/hook/wrongkey/app')[0] == 404
web_server._clear_auth_failures('127.0.0.1')

# ---- 같은 버전은 다시 올릴 수 있고, 낮은 버전은 거절
assert upload(APK, admin)[0] == 200
with open(ledger_app.INFO_FILE, 'w', encoding='utf-8') as f:
    json.dump({**info, 'versionCode': 5, 'versionName': '1.4'}, f)
code, data = upload(APK, admin)
assert code == 400 and '낮은 버전' in data['message'], data
# 허락을 취소하면 연결 키로도 못 받음
req('/api/ledger/admin', json.dumps({'action': 'revoke', 'user_id': jieun}).encode(), admin)
assert req(hook + '/app')[0] == 404
web_server._clear_auth_failures('127.0.0.1')
srv.shutdown()
print('ledger app OK')
