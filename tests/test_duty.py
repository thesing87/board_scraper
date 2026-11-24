"""근무표 API (duty.py, /api/ledger/duty): 가계부 로그인이 있어야 하고, 허락받은 멤버는 누구나 근무를 넣고·지우고,
사람·근무 종류를 더하고 바꿀 수 있음. 바뀐 것은 누가 했는지 남고, 근무표에 쓰인 종류는 못 지움"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, json, urllib.request, urllib.error
from datetime import date, timedelta
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LEDGER_ADMIN_NAME='임기범')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, ledger, duty

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


# ---- 로그인 없으면 거절, 페이지는 열림
assert call('/api/ledger/duty')[0] == 401 and call('/api/ledger/duty', {'action': 'set'})[0] == 401
with urllib.request.urlopen(BASE + '/duty/') as res:
    assert res.status == 200 and '근무표' in res.read().decode()

admin = login('임기범', 'Secr3t!')
ledger.signup('지은', 'pw1234')
ledger.approve(next(p['id'] for p in ledger.people()['pending'] if p['name'] == '지은'))
member = login('지은', 'pw1234')

# ---- 처음: 근무 종류 다섯 개(D·E·N·OFF·연차), 사람은 없음
code, st = call('/api/ledger/duty?month=2026-11', cookie=member)
assert code == 200 and [t['code'] for t in st['types']] == ['D', 'E', 'N', 'OFF', '연차'] and st['people'] == [] and st['person_id'] is None, st
T = {t['code']: t['id'] for t in st['types']}
assert st['types'][2]['start_time'] == '23:00' and st['types'][2]['end_time'] == '07:00'

# ---- 사람 추가 (멤버도), 같은 이름은 거절
code, r = call('/api/ledger/duty', {'action': 'person-add', 'name': ' 예예 '}, member)
assert code == 200, r
yeye = r['id']
assert call('/api/ledger/duty', {'action': 'person-add', 'name': '예예'}, admin)[0] == 400
assert call('/api/ledger/duty', {'action': 'person-add', 'name': ''}, admin)[0] == 400
kb = call('/api/ledger/duty', {'action': 'person-add', 'name': '기범'}, admin)[1]['id']

# ---- 근무 넣기: 멤버가 여러 날 한 번에, 관리자가 하나 고침, 지우기(None)
code, r = call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-11-24': T['E'], '2026-11-25': T['N'], '2026-11-26': T['N'], '2026-12-01': T['D']}}, member)
assert code == 200 and r['changed'] == 4, r
assert call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-11-26': T['OFF'], '2026-11-25': T['N']}}, admin)[1]['changed'] == 1
assert call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {'2026-11-24': None}}, member)[1]['changed'] == 1
# 잘못된 요청
for bad in [{'2026-11-31': T['D']}, {'2026-1-1': T['D']}, {'2026-11-02': 999}, {'2026-11-02': 'D'}, {}]:
    assert call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': bad}, member)[0] == 400, bad
assert call('/api/ledger/duty', {'action': 'set', 'person_id': 999, 'days': {'2026-11-02': T['D']}}, member)[0] == 400
assert call('/api/ledger/duty', {'action': 'set', 'person_id': yeye, 'days': {f'2026-{m:02d}-{d:02d}': T['D'] for m in (1, 2, 3) for d in range(1, 29)}}, member)[0] == 400

# ---- 보기: 그 달 것만, 고른 사람 것만, 최근 바뀐 것(누가), 다른 사람은 비어 있음
code, st = call(f'/api/ledger/duty?month=2026-11&person={yeye}', cookie=admin)
assert st['person_id'] == yeye and st['days'] == {'2026-11-25': T['N'], '2026-11-26': T['OFF']}, st['days']
assert [(c['day'], c['type_id'], c['who']) for c in st['changes'][:2]] == [('2026-11-24', None, '지은'), ('2026-11-26', T['OFF'], '임기범')], st['changes']
assert call(f'/api/ledger/duty?month=2026-11&person={kb}', cookie=admin)[1]['days'] == {}
assert call('/api/ledger/duty?month=2026-12', cookie=admin)[1]['days'] == {'2026-12-01': T['D']}   # 사람을 안 고르면 첫 사람
# 오늘부터 나흘 (near)
s2 = duty.state('2026-11', yeye, today=date(2026, 11, 24))
assert s2['near'] == {'2026-11-25': T['N'], '2026-11-26': T['OFF']} and s2['today'] == '2026-11-24'
s3 = duty.state('2026-11', yeye, today=date(2026, 11, 28))
assert s3['near'] == {'2026-12-01': T['D']}                                           # 달이 넘어가도

# ---- 앱 홈 탭 요약: 사람마다 오늘·내일, 고른 사람의 7일 / 가계부 이번 달 합계·대기함·최근 3건
sm = duty.summary(yeye, today=date(2026, 11, 24))
assert [(p['name'], p['today'], p['tomorrow']) for p in sm['people']] == [('예예', None, T['N']), ('기범', None, None)], sm['people']
assert sm['person_id'] == yeye and [w['type_id'] for w in sm['week']] == [None, T['N'], T['OFF'], None, None, None, None] and sm['week'][0]['day'] == '2026-11-24'
assert duty.summary(999, today=date(2026, 11, 24))['person_id'] == yeye          # 없는 사람이면 첫 사람
assert call('/api/ledger/home', cookie='')[0] == 401
code, home = call(f'/api/ledger/home?person={kb}', cookie=member)
assert code == 200 and home['duty']['person_id'] == kb and set(home['ledger']) == {'month', 'expense', 'income', 'inbox', 'recent'}, home
cats = {c['name']: c['id'] for c in ledger.state('')['categories']}
ledger.add_entry({'id': ledger.user_for_token(member.split('=', 1)[1])['id']}, 12000, date.today().isoformat(), cats['식비'], '점심')
ledger.add_entry({'id': ledger.user_for_token(member.split('=', 1)[1])['id']}, 500000, date.today().isoformat(), cats['급여'], '')
lg = call('/api/ledger/home', cookie=member)[1]['ledger']
assert lg['expense'] == 12000 and lg['income'] == 500000 and lg['inbox'] == 0, lg
assert [(r['memo'], r['kind']) for r in lg['recent']] == [('급여', 'income'), ('점심', 'expense')], lg['recent']   # 메모가 없으면 분류 이름

# ---- 근무 종류: 추가·바꾸기·지우기 (쓰인 것은 못 지움), 값 검사
code, r = call('/api/ledger/duty', {'action': 'type-add', 'code': '교육', 'name': '교육', 'start_time': '09:00', 'end_time': '18:00', 'color': '#378add'}, member)
assert code == 200, r
edu = r['id']
for bad in [{'code': 'D'}, {'code': ''}, {'code': 'ABCDE'}, {'code': 'X', 'start_time': '9:00', 'end_time': '18:00'},
            {'code': 'X', 'start_time': '09:00'}, {'code': 'X', 'color': 'red'}, {'code': 'X', 'start_time': '24:00', 'end_time': '01:00'}]:
    body = {'action': 'type-add', 'name': '', 'start_time': '', 'end_time': '', 'color': '#378ADD', **bad}
    assert call('/api/ledger/duty', body, member)[0] == 400, bad
assert call('/api/ledger/duty', {'action': 'type-edit', 'id': T['D'], 'code': 'D', 'name': '데이', 'start_time': '06:30', 'end_time': '14:30', 'color': '#EF9F27'}, member)[0] == 200
assert call('/api/ledger/duty', {'action': 'type-edit', 'id': T['D'], 'code': 'E', 'name': '데이', 'start_time': '', 'end_time': '', 'color': '#EF9F27'}, member)[0] == 400
st = call('/api/ledger/duty', cookie=member)[1]
assert next(t for t in st['types'] if t['id'] == T['D'])['start_time'] == '06:30' and st['types'][-1] == {
    'id': edu, 'code': '교육', 'name': '교육', 'start_time': '09:00', 'end_time': '18:00', 'color': '#378ADD'}
code, r = call('/api/ledger/duty', {'action': 'type-delete', 'id': T['N']}, member)
assert code == 400 and '지울 수 없어요' in r['message']
assert call('/api/ledger/duty', {'action': 'type-delete', 'id': edu}, member)[0] == 200

# ---- 사람 이름 바꾸기·지우기 (근무도 함께 지움)
assert call('/api/ledger/duty', {'action': 'person-rename', 'id': kb, 'name': '예예'}, member)[0] == 400
assert call('/api/ledger/duty', {'action': 'person-rename', 'id': kb, 'name': '기범2'}, member)[0] == 200
assert call('/api/ledger/duty', {'action': 'person-delete', 'id': yeye}, member)[0] == 200
with storage._db() as conn:
    assert conn.execute("SELECT COUNT(*) FROM duty_days").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM duty_changes").fetchone()[0] == 0
assert [p['name'] for p in call('/api/ledger/duty', cookie=member)[1]['people']] == ['기범2']
assert call('/api/ledger/duty', {'action': 'nope'}, member)[0] == 400 and call('/api/ledger/duty', {'action': 'person-delete'}, member)[0] == 400

# ---- 근무 종류 한 번에 저장 (type-save): 글자 맞바꾸기 가능, 틀린 줄이 있으면 아무것도 안 바꾸고 그 줄 번호(row)
types = {t['code']: t for t in duty.state('2026-11', None)['types']}
d_, e_ = types['D'], types['E']
code, data = call('/api/ledger/duty', {'action': 'type-save', 'types': [
    {'id': d_['id'], 'code': 'E', 'name': d_['name'], 'start_time': d_['start_time'], 'end_time': d_['end_time'], 'color': d_['color']},
    {'id': e_['id'], 'code': 'D', 'name': e_['name'], 'start_time': e_['start_time'], 'end_time': e_['end_time'], 'color': e_['color']},
    {'code': 'X', 'name': '시험', 'start_time': '', 'end_time': '', 'color': '#378ADD'}]}, cookie=member)
assert code == 200, data
after = {t['id']: t['code'] for t in duty.state('2026-11', None)['types']}
assert after[d_['id']] == 'E' and after[e_['id']] == 'D' and 'X' in after.values()
code, data = call('/api/ledger/duty', {'action': 'type-save', 'types': [
    {'id': d_['id'], 'code': 'D', 'name': '바뀜', 'start_time': '', 'end_time': '', 'color': '#378ADD'},
    {'code': '', 'name': '글자 없음', 'start_time': '', 'end_time': '', 'color': '#378ADD'}]}, cookie=member)
assert code == 400 and data['row'] == 1 and '짧은 글자' in data['message'], data
assert {t['id']: t['code'] for t in duty.state('2026-11', None)['types']} == after          # 하나도 안 바뀜
code, data = call('/api/ledger/duty', {'action': 'type-save', 'types': [
    {'id': d_['id'], 'code': 'OFF', 'name': 'x', 'start_time': '', 'end_time': '', 'color': '#378ADD'}]}, cookie=member)
assert code == 400 and data['row'] == 0 and '겹쳐요' in data['message'], data
code, data = call('/api/ledger/duty', {'action': 'type-save', 'types': [
    {'id': d_['id'], 'code': 'D', 'name': d_['name'], 'start_time': d_['start_time'], 'end_time': d_['end_time'], 'color': d_['color']},
    {'id': e_['id'], 'code': 'E', 'name': e_['name'], 'start_time': e_['start_time'], 'end_time': e_['end_time'], 'color': e_['color']}]}, cookie=member)
assert code == 200, data

# ---- 허락을 취소하면 근무표도 못 씀
ledger.revoke(next(p['id'] for p in ledger.people()['members'] if p['name'] == '지은'))
assert call('/api/ledger/duty', cookie=member)[0] == 401
print('DUTY OK')
