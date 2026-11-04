"""관리자 로그인: 암호가 맞으면 로그인 키를 주고, 관리 요청은 암호 대신 그 키로도 받음.
키는 암호가 아니고, 틀린 암호·틀린 키는 거부하며 실패 횟수를 세어 잠금"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server

storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def post(path, body):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)

# 1) 틀린 암호는 거부, 맞는 암호면 로그인 키 (암호 자체가 아님)
code, body = post('/api/login', {'password': 'wrong'})
assert code == 401 and not body['success'] and 'token' not in body, (code, body)
code, body = post('/api/login', {'password': 'Secr3t!'})
token = body.get('token')
assert code == 200 and body['success'] and token and token != 'Secr3t!' and len(token) == 64, (code, body)
print('LOGIN OK')

# 2) 관리 요청은 로그인 키로도, 암호로도 받고, 틀린 키는 거부
assert post('/api/site', {'site': 'fmkorea', 'name': '에펨', 'short': 'FM', 'password': token})[1]['success']
assert post('/api/site', {'site': 'fmkorea', 'name': '에펨코리아', 'short': 'FM', 'password': 'Secr3t!'})[1]['success']
assert post('/api/site', {'site': 'fmkorea', 'name': '에펨', 'short': 'FM', 'password': token[:-1] + '0'})[0] == 401
print('TOKEN OK')

# 3) 틀린 시도가 쌓이면 로그인도 잠김 (성공하면 실패 횟수가 지워지므로, 앞의 틀린 키 1번 + 4번)
for _ in range(4):
    post('/api/login', {'password': 'nope'})
code, body = post('/api/login', {'password': 'Secr3t!'})
assert code == 429 and not body['success'], (code, body)
print('LOCKOUT OK')
