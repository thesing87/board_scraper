"""가계부 변경 알림 (ledger_push.py): 넣기·고치기·지우기·대기함 확정을 고친 사람을 뺀 사람에게, 잇달아 고친 것은 하나로,
넣었다 지운 것·되돌린 것은 뺌, 처음에는 예전 변경을 알리지 않음, 가계부 알림을 켠 휴대폰(앱 1.14부터)만"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, json, urllib.request, urllib.error
from datetime import datetime, timedelta
out = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=out, LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LEDGER_ADMIN_NAME='임기범',
                  FCM_SERVICE_ACCOUNT=os.path.join(out, 'fcm.json'))
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, ledger, duty_push, ledger_push

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
    return datetime.now() + timedelta(seconds=ledger_push.QUIET_SECONDS + 5)


def entry(cookie, **b):
    code, r = call('/api/ledger/entry', b, cookie)
    assert code == 200, r
    return r.get('id')


def tokens_of(kind):
    with storage._db() as conn:
        return sorted(t for t, _ in duty_push.recipients(conn, kind))


admin = login('임기범', 'Secr3t!')
for name in ('지은', '민수', '예전'):
    ledger.signup(name, 'pw1234')
    ledger.approve(next(p['id'] for p in ledger.people()['pending'] if p['name'] == name))
jieun, minsu, old = login('지은', 'pw1234'), login('민수', 'pw1234'), login('예전', 'pw1234')

# ---- 토큰: 새 앱은 duty·ledger를 함께 보냄, 예전 앱(아무것도 안 보냄)은 근무표만
for cookie, tok, body in ((admin, 'tok-admin', {'duty': True, 'ledger': True}), (jieun, 'tok-jieun', {'duty': False, 'ledger': True}),
                          (minsu, 'tok-minsu', {'duty': True, 'ledger': True}), (old, 'tok-old', {})):
    code, r = call('/api/ledger/duty', {'action': 'push-token', 'token': tok, **body}, cookie)
    assert code == 200 and r['registered'] is True, r
assert tokens_of('duty') == ['tok-admin', 'tok-minsu', 'tok-old'], tokens_of('duty')
assert tokens_of('ledger') == ['tok-admin', 'tok-jieun', 'tok-minsu'], tokens_of('ledger')

C = {c['name']: c['id'] for c in ledger.state('')['categories']}

# ---- 처음 한 번은 지금까지를 보낸 것으로
entry(jieun, action='add', amount=1000, used_on='2026-11-20', category_id=C['식비'], memo='')
assert ledger_push.collect(later()) == []
assert ledger_push.collect(later()) == []

# ---- 지은이 넣고·고치고·지움: 조용해지기 전엔 안 보냄, 지나면 하나로, 지은에게는 안 감
a = entry(jieun, action='add', amount=12000, used_on='2026-11-24', category_id=C['식비'], memo='스타벅스')
b = entry(jieun, action='add', amount=3000, used_on='2026-11-23', category_id=C['교통'], memo='')
entry(jieun, action='edit', id=b, amount=4000, used_on='2026-11-23', category_id=C['교통'], memo='')
entry(jieun, action='edit', id=b, amount=4500, used_on='2026-11-23', category_id=C['교통'], memo='')
c = entry(jieun, action='add', amount=9999, used_on='2026-11-22', category_id=C['쇼핑'], memo='')
entry(jieun, action='delete', id=c)                                    # 넣었다 지움 → 뺌
assert ledger_push.collect(datetime.now()) == []
msgs = ledger_push.collect(later())
assert len(msgs) == 1, msgs
m = msgs[0]
assert m['title'] == '가계부 · 지은님' and m['channel'] == 'ledger_change' and m['data'] == {'kind': 'ledger'}, m
assert m['body'] == '등록 11/24(화) 식비 12,000원 · 스타벅스\n등록 11/23(월) 교통 4,500원', m['body']
assert sorted(m['tokens']) == ['tok-admin', 'tok-minsu'], m      # 예전 앱(tok-old)은 안 받음
assert ledger_push.collect(later()) == []

# ---- 고치기는 바뀐 것만 '→', 되돌리면 알림 없음
entry(jieun, action='edit', id=b, amount=4500, used_on='2026-11-25', category_id=C['식비'], memo='택시')
body = ledger_push.collect(later())[0]['body']
assert body == '수정 11/23(월) → 11/25(수) 교통 → 식비 4,500원 · 메모 없음 → 택시', body
entry(jieun, action='edit', id=b, amount=5000, used_on='2026-11-25', category_id=C['식비'], memo='택시')
entry(jieun, action='edit', id=b, amount=4500, used_on='2026-11-25', category_id=C['식비'], memo='택시')
assert ledger_push.collect(later()) == []

# ---- 관리자가 지은 기록을 지우면 지은도 받음, 두 사람이 고치면 따로. 수입은 +
entry(admin, action='delete', id=a)
d = entry(minsu, action='add', amount=3000000, used_on='2026-11-25', category_id=C['급여'], memo='')
msgs = {m['title']: m for m in ledger_push.collect(later())}
assert msgs['가계부 · 임기범님']['body'] == '삭제 11/24(화) 식비 12,000원 · 스타벅스', msgs
assert sorted(msgs['가계부 · 임기범님']['tokens']) == ['tok-jieun', 'tok-minsu'], msgs
assert msgs['가계부 · 민수님']['body'] == '등록 11/25(수) 급여 +3,000,000원', msgs
assert sorted(msgs['가계부 · 민수님']['tokens']) == ['tok-admin', 'tok-jieun'], msgs

# ---- 결제 알림 대기함 확정(결제 → 등록, 취소 → 삭제)도 알림
key = ledger.create_hook_key({'id': next(p['id'] for p in ledger.people()['members'] if p['name'] == '민수'), 'name': '민수', 'admin': False})
assert ledger.receive_hook(key, '[신한카드] 승인 8,800원 일시불 11/24 12:30 김밥천국') == 'saved'
item = call('/api/ledger/inbox', None, minsu)[1]['items'][0]
code, r = call('/api/ledger/inbox', {'action': 'update', 'id': item['id'], 'category_id': C['식비']}, minsu)
code, r = call('/api/ledger/inbox', {'action': 'confirm', 'id': item['id']}, minsu)
assert code == 200, r
msgs = ledger_push.collect(later())
assert len(msgs) == 1 and msgs[0]['title'] == '가계부 · 민수님' and msgs[0]['body'].startswith('등록 ') and '8,800원' in msgs[0]['body'], msgs
assert ledger.receive_hook(key, '[신한카드] 승인취소 8,800원 11/24 12:40 김밥천국') == 'saved'
item = call('/api/ledger/inbox', None, minsu)[1]['items'][0]
assert call('/api/ledger/inbox', {'action': 'confirm', 'id': item['id']}, minsu)[0] == 200
msgs = ledger_push.collect(later())
assert len(msgs) == 1 and msgs[0]['body'].startswith('삭제 ') and '8,800원' in msgs[0]['body'], msgs

# ---- 많이 넣으면 '외 n건'
for i in range(11):
    entry(jieun, action='add', amount=100 + i, used_on='2026-11-01', category_id=C['생활'], memo='')
lines = ledger_push.collect(later())[0]['body'].split('\n')
assert len(lines) == ledger_push.LINES_SHOWN + 1 and lines[-1] == '외 3건', lines

# ---- 가계부 알림을 끄면(ledger: false) 안 받음, 근무표 알림만 끈 휴대폰은 가계부는 받음
call('/api/ledger/duty', {'action': 'push-token', 'token': 'tok-minsu', 'duty': True, 'ledger': False}, minsu)
entry(jieun, action='add', amount=500, used_on='2026-11-02', category_id=C['생활'], memo='')
assert ledger_push.collect(later())[0]['tokens'] == ['tok-admin']

# ---- FCM 보내기: 채널·데이터가 가계부 것으로
posts = []


class Res:
    status_code, text = 200, '{}'


duty_push._account = lambda: {'project_id': 'p'}
duty_push._access_token = lambda account: 'ya29'
duty_push.requests.post = lambda url, json=None, headers=None, timeout=None: posts.append(json) or Res()
entry(admin, action='add', amount=700, used_on='2026-11-03', category_id=C['카페'], memo='')
assert duty_push.send(ledger_push.collect(later()), ledger_push.LABEL) == 1
msg = posts[-1]['message']
assert msg['token'] == 'tok-jieun' and msg['android']['notification']['channel_id'] == 'ledger_change' and msg['data'] == {'kind': 'ledger'}, msg
assert msg['notification']['title'] == '가계부 · 임기범님'
print('LEDGER PUSH OK')
