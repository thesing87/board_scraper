"""근무표 변경 알림 (duty_push.py): 휴대폰 토큰 등록·지움, 고친 사람을 뺀 사람에게만, 잇달아 고친 것은 하나로 모으고
되돌린 날은 뺌, 처음에는 예전 변경을 알리지 않음, FCM 보내기(서명·없어진 토큰 지움)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, json, random, base64, hashlib, urllib.request, urllib.error
from datetime import datetime, timedelta
out = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=out, LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LEDGER_ADMIN_NAME='임기범',
                  FCM_SERVICE_ACCOUNT=os.path.join(out, 'fcm.json'))
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, ledger, duty, duty_push

storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'


def call(path, body=None, cookie=''):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                               method='POST' if body is not None else 'GET',
                               headers={'Content-Type': 'application/json', 'Cookie': cookie})
    try:
        with urllib.request.urlopen(r) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        data = e.read()
        return e.code, (json.loads(data) if data else {})


def login(name, password):
    r = urllib.request.Request(BASE + '/api/ledger/session', data=json.dumps({'action': 'login', 'name': name, 'password': password}).encode(),
                               method='POST', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r) as res:
        return (res.headers.get('Set-Cookie') or '').split(';')[0]


def later():
    return datetime.now() + timedelta(seconds=duty_push.QUIET_SECONDS + 5)


admin = login('임기범', 'Secr3t!')
for name in ('지은', '민수'):
    ledger.signup(name, 'pw1234')
    ledger.approve(next(p['id'] for p in ledger.people()['pending'] if p['name'] == name))
jieun, minsu = login('지은', 'pw1234'), login('민수', 'pw1234')

# ---- 토큰 등록: 로그인해야 함, 이상한 토큰은 거절
assert call('/api/ledger/duty', {'action': 'push-token', 'token': 'tok-a'})[0] == 401
assert call('/api/ledger/duty', {'action': 'push-token', 'token': 'bad token!'}, admin)[1]['registered'] is False
assert call('/api/ledger/duty', {'action': 'push-token'}, admin)[0] == 400
for cookie, tok in ((admin, 'tok-admin'), (jieun, 'tok-jieun'), (minsu, 'tok-minsu')):
    code, r = call('/api/ledger/duty', {'action': 'push-token', 'token': tok}, cookie)
    assert code == 200 and r['registered'] is True, r

T = {t['code']: t['id'] for t in duty.state('2026-12')['types']}
yeye = call('/api/ledger/duty', {'action': 'person-add', 'name': '예예'}, jieun)[1]['id']

# ---- 처음 한 번은 지금까지를 보낸 것으로 (예전 변경은 알리지 않음)
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-01': T['D']}}, jieun)
assert duty_push.collect(later()) == []
assert duty_push.collect(later()) == []

# ---- 지은이 잇달아 고침: 아직 조용하지 않으면 안 보냄, 지나면 하나로. 지은에게는 안 감
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-01': T['N'], '2026-12-02': T['OFF']}}, jieun)
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-03': T['E']}}, jieun)
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-04': T['D']}}, jieun)
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-04': None}}, jieun)   # 넣었다가 지움 → 뺌
assert duty_push.collect(datetime.now()) == []
msgs = duty_push.collect(later())
assert len(msgs) == 1, msgs
m = msgs[0]
assert m['title'] == '근무표 변경 · 예예' and m['person_id'] == yeye, m
assert m['body'] == '지은님이 고침\n12/1(화) 데이 → 나이트\n12/2(수) 휴무\n12/3(목) 이브닝', m['body']
assert sorted(m['tokens']) == ['tok-admin', 'tok-minsu'], m
assert duty_push.collect(later()) == []          # 한 번만

# ---- 같은 근무로 다시 넣거나 넣고 지우기만 하면 알림 없음
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-05': T['D']}}, minsu)
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-05': None}}, minsu)
assert duty_push.collect(later()) == []

# ---- 두 사람이 고치면 고친 사람마다 따로, 지움 표시
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-01': None}}, minsu)
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-02': T['D']}}, admin)
msgs = {m['body'].split('님')[0]: m for m in duty_push.collect(later())}
assert msgs['민수']['body'].endswith('12/1(화) 나이트 → 지움') and sorted(msgs['민수']['tokens']) == ['tok-admin', 'tok-jieun'], msgs
assert msgs['임기범']['body'].endswith('12/2(수) 휴무 → 데이') and sorted(msgs['임기범']['tokens']) == ['tok-jieun', 'tok-minsu'], msgs

# ---- 많이 고치면 '외 n일'
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {f'2026-12-{d:02d}': T['OFF'] for d in range(10, 21)}}, jieun)
body = duty_push.collect(later())[0]['body'].split('\n')
assert len(body) == 1 + duty_push.LINES_SHOWN + 1 and body[-1] == '외 3일', body

# ---- 로그아웃하면 그 휴대폰 토큰도 지워짐, 허락을 취소해도 안 감
call('/api/ledger/session', {'action': 'logout'}, minsu)
ledger.revoke(next(p['id'] for p in ledger.people()['members'] if p['name'] == '지은'))
call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-12-25': T['연차']}}, admin)
assert duty_push.collect(later()) == []          # 받을 사람이 없음
call('/api/ledger/duty', {'action': 'push-token-delete', 'token': 'tok-admin'}, admin)
with storage._db() as conn:
    assert conn.execute("SELECT COUNT(*) FROM duty_push_tokens").fetchone()[0] == 0


# ---- RS256 서명: 파이썬만으로 만든 키로 서명하고 공개키로 확인
def is_prime(n):
    if n < 2 or n % 2 == 0:
        return n == 2
    d, r = n - 1, 0
    while d % 2 == 0:
        d, r = d // 2, r + 1
    for _ in range(20):
        x = pow(random.randrange(2, n - 1), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def prime(bits):
    while True:
        p = random.getrandbits(bits) | (1 << (bits - 1)) | 1
        if is_prime(p):
            return p


def der(tag, body):
    n = len(body)
    length = bytes([n]) if n < 128 else bytes([0x80 | ((n.bit_length() + 7) // 8)]) + n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return bytes([tag]) + length + body


def der_int(v):
    return der(0x02, v.to_bytes(v.bit_length() // 8 + 1, 'big'))


e = 65537
while True:
    p, q = prime(1024), prime(1024)
    if p != q and (p - 1) % e and (q - 1) % e:
        break
n, d = p * q, pow(e, -1, (p - 1) * (q - 1))
rsa = der(0x30, b''.join(der_int(v) for v in (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))))
pkcs8 = der(0x30, der_int(0) + der(0x30, der(0x06, bytes.fromhex('2a864886f70d010101')) + b'\x05\x00') + der(0x04, rsa))
b64 = base64.b64encode(pkcs8).decode()
pem = '-----BEGIN PRIVATE KEY-----\n' + '\n'.join(b64[i:i + 64] for i in range(0, len(b64), 64)) + '\n-----END PRIVATE KEY-----\n'
assert duty_push._rsa_key(pem) == (n, d)
sig = duty_push._rs256(b'hello', n, d)
em = pow(int.from_bytes(sig, 'big'), e, n).to_bytes(256, 'big')
assert em.startswith(b'\x00\x01\xff') and em.endswith(duty_push._SHA256_PREFIX + hashlib.sha256(b'hello').digest())

# ---- 보내기: 키가 없으면 안 보냄, 있으면 인증 받고 보냄, 없어진 토큰은 지움
assert duty_push.send([{'title': 't', 'body': 'b', 'person_id': 1, 'tokens': ['x']}]) == 0
with open(os.environ['FCM_SERVICE_ACCOUNT'], 'w', encoding='utf-8') as f:
    json.dump({'project_id': 'yeye-test', 'client_email': 'push@yeye-test.iam.gserviceaccount.com', 'private_key': pem,
               'token_uri': 'https://oauth2.googleapis.com/token'}, f)


class Res:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        assert self.status_code == 200


posts = []


def fake_post(url, json=None, data=None, headers=None, timeout=None):
    posts.append((url, json, data, headers))
    if url.endswith('/token'):
        head, claims, sig = data['assertion'].split('.')
        pad = lambda s: s + '=' * (-len(s) % 4)
        assert pow(int.from_bytes(base64.urlsafe_b64decode(pad(sig)), 'big'), e, n).to_bytes(256, 'big').endswith(
            hashlib.sha256(f'{head}.{claims}'.encode()).digest())
        c = __import__('json').loads(base64.urlsafe_b64decode(pad(claims)))
        assert c['scope'] == 'https://www.googleapis.com/auth/firebase.messaging' and c['iss'].startswith('push@')
        return Res(200, {'access_token': 'ya29.test', 'expires_in': 3600})
    if json['message']['token'] == 'gone':
        return Res(404, {'error': {'status': 'NOT_FOUND', 'details': [{'errorCode': 'UNREGISTERED'}]}})
    return Res(200, {'name': 'projects/yeye-test/messages/1'})


duty_push.requests.post = fake_post
admin = login('임기범', 'Secr3t!')
call('/api/ledger/duty', {'action': 'push-token', 'token': 'gone'}, admin)
call('/api/ledger/duty', {'action': 'push-token', 'token': 'alive'}, admin)
sent = duty_push.send([{'title': '근무표 변경 · 예예', 'body': '지은님이 고침', 'person_id': yeye, 'tokens': ['gone', 'alive']}])
assert sent == 1, posts
msg = [p for p in posts if 'messages:send' in p[0]][-1]
assert msg[0] == 'https://fcm.googleapis.com/v1/projects/yeye-test/messages:send' and msg[3]['Authorization'] == 'Bearer ya29.test'
assert msg[1]['message']['android']['notification']['channel_id'] == 'duty_change' and msg[1]['message']['data'] == {'kind': 'duty', 'person_id': str(yeye)}
with storage._db() as conn:
    assert [r[0] for r in conn.execute("SELECT token FROM duty_push_tokens")] == ['alive']
duty_push.send([{'title': 't', 'body': 'b', 'person_id': yeye, 'tokens': ['alive']}])
assert sum(1 for p in posts if p[0].endswith('/token')) == 1      # 인증은 다시 씀
print('DUTY PUSH OK')
