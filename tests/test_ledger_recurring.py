"""가계부 매달 반복 결제 (자동이체·월급 등): 기록과 함께 만들기, 그날 저절로 기록(말일·서버가 꺼져 있던 달·한 달에 한 번),
반복이 넣은 기록 고치기('다음 달부터도'), 반복 고치기·멈추기·다시 시작·지우기, 만든 사람·관리자만, 결제 알림과 같은 반복 찾기"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, json, urllib.request, urllib.error
import datetime as dt
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LEDGER_ADMIN_NAME='임기범')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, ledger

# 오늘을 정해 둠 (ledger 안의 date.today()만 바꿈)
TODAY = [dt.date(2026, 11, 26)]


class FakeDate(dt.date):
    @classmethod
    def today(cls):
        return TODAY[0]


ledger.date = FakeDate
D = dt.date

# ==== 날 계산: 그 달에 없는 날은 말일
assert ledger._on_day(2026, 2, 31) == D(2026, 2, 28) and ledger._on_day(2028, 2, 30) == D(2028, 2, 29)
assert ledger._month_after(D(2026, 1, 31), 31) == D(2026, 2, 28) and ledger._month_after(D(2026, 2, 28), 31) == D(2026, 3, 31)
assert ledger._month_after(D(2026, 12, 25), 25) == D(2027, 1, 25)
assert ledger._next_after(25, D(2026, 11, 25)) == D(2026, 12, 25) and ledger._next_after(27, D(2026, 11, 26)) == D(2026, 11, 27)

# ==== 서버
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'


def call(path, body=None, cookie=''):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method='POST' if data is not None else 'GET',
                               headers={'Content-Type': 'application/json', 'Cookie': cookie})
    try:
        with urllib.request.urlopen(r) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        d = e.read()
        return e.code, (json.loads(d) if d else {})


def login(name, password):
    r = urllib.request.Request(BASE + '/api/ledger/session', data=json.dumps({'action': 'login', 'name': name, 'password': password}).encode(),
                               method='POST', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r) as res:
        return (res.headers.get('Set-Cookie') or '').split(';')[0]


admin = login('임기범', 'Secr3t!')
for name in ('지은', '민수'):
    assert call('/api/ledger/session', {'action': 'signup', 'name': name, 'password': 'pw12'})[0] == 200
for p in call('/api/ledger/admin', cookie=admin)[1]['pending']:
    call('/api/ledger/admin', {'action': 'approve', 'user_id': p['id']}, cookie=admin)
user, other = login('지은', 'pw12'), login('민수', 'pw12')


def state(month='2026-11', cookie=None):
    code, d = call(f'/api/ledger/state?month={month}', cookie=cookie or user)
    assert code == 200, d
    return d


cats = state()['categories']
life = next(c['id'] for c in cats if c['name'] == '생활')
food = next(c['id'] for c in cats if c['name'] == '식비')
salary = next(c['id'] for c in cats if c['name'] == '급여')

# ==== 기록과 함께 반복 만들기: 이번 기록은 그대로, 다음 달 그날부터
code, r = call('/api/ledger/entry', {'action': 'add', 'amount': 55000, 'used_on': '2026-11-25', 'category_id': life,
                                     'memo': '신한은행 자동이체', 'repeat_day': 25}, cookie=user)
assert code == 200, r
first = r['id']
d = state()
assert len(d['recurring']) == 1, d['recurring']
rec = d['recurring'][0]
assert (rec['amount'], rec['day'], rec['next_on'], rec['memo'], rec['paused']) == (55000, 25, '2026-12-25', '신한은행 자동이체', 0), rec
assert next(e for e in d['entries'] if e['id'] == first)['recurring_id'] == rec['id']
# 잘못된 날은 거절, 기록도 넣지 않음
n = len(d['entries'])
assert call('/api/ledger/entry', {'action': 'add', 'amount': 1000, 'used_on': '2026-11-25', 'category_id': food, 'repeat_day': 32}, cookie=user)[0] == 400
assert len(state()['entries']) == n

# 지난 날로 기록해도 지난 달을 거슬러 넣지 않음 (오늘 다음의 그날부터): 월급 9/10 → 다음은 12/10
code, r = call('/api/ledger/entry', {'action': 'add', 'amount': 3000000, 'used_on': '2026-09-10', 'category_id': salary,
                                     'memo': '월급', 'repeat_day': 10}, cookie=other)
pay = next(x for x in state()['recurring'] if x['memo'] == '월급')
assert pay['next_on'] == '2026-12-10' and len(state('2026-10')['entries']) == 0, pay

# ==== 그날이 되면 기록 (이름을 바꾼 것이 그대로): 반복이 넣은 기록을 'XX 보험'으로 고치고 '다음 달부터도'
code, _ = call('/api/ledger/entry', {'action': 'edit', 'id': first, 'amount': 56000, 'used_on': '2026-11-25', 'category_id': life,
                                     'memo': 'XX 보험', 'apply_future': True}, cookie=user)
assert code == 200
rec = next(x for x in state()['recurring'] if x['id'] == rec['id'])
assert (rec['memo'], rec['amount']) == ('XX 보험', 56000), rec
TODAY[0] = D(2026, 12, 24)
assert ledger.run_recurring() == 1          # 월급 12/10만 (보험은 아직)
TODAY[0] = D(2026, 12, 25)
assert ledger.run_recurring() == 1 and ledger.run_recurring() == 0          # 한 달에 한 번만
dec = [e for e in state('2026-12')['entries'] if e['recurring_id'] == rec['id']]
assert len(dec) == 1 and (dec[0]['used_on'], dec[0]['memo'], dec[0]['amount'], dec[0]['category_id']) == ('2026-12-25', 'XX 보험', 56000, life), dec
assert dec[0]['user_id'] == next(m['id'] for m in state()['members'] if m['name'] == '지은')    # 만든 사람의 기록
# 그 달만 바꾸기 (apply_future 없음): 반복은 그대로
call('/api/ledger/entry', {'action': 'edit', 'id': dec[0]['id'], 'amount': 60000, 'used_on': '2026-12-25', 'category_id': life, 'memo': 'XX 보험'}, cookie=user)
assert next(x for x in state()['recurring'] if x['id'] == rec['id'])['amount'] == 56000
# 기록이 들어가면 다른 사람에게 갈 변경 기록도 남음
with storage._db() as conn:
    assert conn.execute("SELECT COUNT(*) FROM ledger_changes WHERE entry_id = ? AND before IS NULL", (dec[0]['id'],)).fetchone()[0] == 1

# ==== 서버가 꺼져 있던 달도 채움, 다음은 앞으로 올 그날
TODAY[0] = D(2027, 3, 1)
assert ledger.run_recurring() == 4    # 보험 1/25·2/25, 월급 1/10·2/10 (월급 12/10은 위에서 이미)
assert [e['used_on'] for e in state('2027-02')['entries'] if e['recurring_id'] == rec['id']] == ['2027-02-25']
rec = next(x for x in state('2027-03')['recurring'] if x['id'] == rec['id'])
assert rec['next_on'] == '2027-03-25', rec

# ==== 말일: 31일 반복은 2월엔 28일
code, r = call('/api/ledger/entry', {'action': 'add', 'amount': 9900, 'used_on': '2027-01-31', 'category_id': life, 'memo': '구독', 'repeat_day': 31}, cookie=user)
sub = next(x for x in state('2027-03')['recurring'] if x['memo'] == '구독')
assert sub['next_on'] == '2027-03-31', sub   # 오늘(3/1) 다음의 31일

# ==== 반복 고치기 (설정 > 반복 결제): 날을 바꾸면 다음에 넣을 달의 새 날, 이미 지났으면 바로
assert call('/api/ledger/recurring', {'action': 'edit', 'id': rec['id'], 'amount': 57000, 'day': 20, 'category_id': life, 'memo': 'XX 보험'}, cookie=other)[0] == 400   # 남의 것
assert call('/api/ledger/recurring', {'action': 'edit', 'id': rec['id'], 'amount': 57000, 'day': 0, 'category_id': life, 'memo': 'XX 보험'}, cookie=user)[0] == 400
code, r = call('/api/ledger/recurring', {'action': 'edit', 'id': rec['id'], 'amount': 57000, 'day': 20, 'category_id': life, 'memo': 'XX 보험'}, cookie=user)
assert code == 200 and next(x for x in r['recurring'] if x['id'] == rec['id'])['next_on'] == '2027-03-20', r
TODAY[0] = D(2027, 3, 22)
code, r = call('/api/ledger/recurring', {'action': 'edit', 'id': sub['id'], 'amount': 9900, 'day': 21, 'category_id': life, 'memo': '구독'}, cookie=user)
assert [e['used_on'] for e in state('2027-03')['entries'] if e['recurring_id'] == sub['id']] == ['2027-03-21']   # 3/21이 이미 지나 바로
assert [e['amount'] for e in state('2027-03')['entries'] if e['recurring_id'] == rec['id']] == [57000]           # state()가 3/20 것을

# ==== 멈추기 → 그동안은 넣지 않음, 다시 시작하면 지난 달은 채우지 않음. 관리자는 남의 것도
assert call('/api/ledger/recurring', {'action': 'pause', 'id': rec['id']}, cookie=admin)[0] == 200
TODAY[0] = D(2027, 6, 5)
ledger.run_recurring()
assert not [e for e in state('2027-04')['entries'] + state('2027-05')['entries'] if e['recurring_id'] == rec['id']]
code, r = call('/api/ledger/recurring', {'action': 'resume', 'id': rec['id']}, cookie=user)
assert next(x for x in r['recurring'] if x['id'] == rec['id'])['next_on'] == '2027-06-20' and not [e for e in state('2027-05')['entries'] if e['recurring_id'] == rec['id']]

# ==== 결제 알림과 같은 반복 찾기 ('신한은행 자동이체'로 와도 금액·날짜로): 이미 넣었으면 done, 곧 넣을 것이면 아님
with storage._db() as conn:
    item = {'amount': 57000, 'used_on': '2027-03-21'}
    assert ledger._recurring_match(conn, item) == {'memo': 'XX 보험', 'used_on': '2027-03-20', 'done': True}
    assert ledger._recurring_match(conn, {'amount': 57000, 'used_on': '2027-06-18'}) == {'memo': 'XX 보험', 'used_on': '2027-06-20', 'done': False}
    assert ledger._recurring_match(conn, {'amount': 57000, 'used_on': '2027-06-10'}) is None
    assert ledger._recurring_match(conn, {'amount': 57001, 'used_on': '2027-03-21'}) is None

# ==== 반복에 쓰인 분류는 지우지 못함, 반복을 지워도 기록은 그대로 (반복 표시만 없어짐)
code, r = call('/api/ledger/category', {'action': 'add', 'name': '보험', 'color': '#378ADD'}, cookie=user)
ins = next(c['id'] for c in state()['categories'] if c['name'] == '보험')
call('/api/ledger/recurring', {'action': 'edit', 'id': rec['id'], 'amount': 57000, 'day': 20, 'category_id': ins, 'memo': 'XX 보험'}, cookie=user)
assert '반복 결제' in call('/api/ledger/category', {'action': 'delete', 'id': ins}, cookie=user)[1].get('message', '')
before = [e['id'] for e in state('2027-03')['entries'] if e['recurring_id'] == rec['id']]
assert call('/api/ledger/recurring', {'action': 'delete', 'id': rec['id']}, cookie=other)[0] == 400
assert call('/api/ledger/recurring', {'action': 'delete', 'id': rec['id']}, cookie=user)[0] == 200
march = {e['id']: e for e in state('2027-03')['entries']}
assert all(i in march and march[i]['recurring_id'] is None for i in before) and not [x for x in state()['recurring'] if x['id'] == rec['id']]
assert call('/api/ledger/category', {'action': 'delete', 'id': ins}, cookie=user)[0] == 200

# ==== 반복이 아닌 기록에서 나중에 반복 만들기 (고치기 창에서 켬)
code, r = call('/api/ledger/entry', {'action': 'add', 'amount': 12000, 'used_on': '2027-06-03', 'category_id': food, 'memo': '정수기'}, cookie=user)
call('/api/ledger/entry', {'action': 'edit', 'id': r['id'], 'amount': 12000, 'used_on': '2027-06-03', 'category_id': food, 'memo': '정수기', 'repeat_day': 3}, cookie=user)
water = next(x for x in state()['recurring'] if x['memo'] == '정수기')
assert water['next_on'] == '2027-07-03' and next(e for e in state('2027-06')['entries'] if e['id'] == r['id'])['recurring_id'] == water['id']
assert call('/api/ledger/recurring', {'action': 'nope', 'id': water['id']}, cookie=user)[0] == 400
srv.shutdown()
print('OK')
