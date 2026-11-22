"""가계부 자동 기록: 결제 알림 글 읽기(ledger_parse) → 연결 주소로 받기 → 확인 대기함 → 확정·버리기·고치기,
가게 이름 규칙(대기함에도 바로 적용), 취소 알림은 맞는 기록을 찾아 지움, 같은 알림 두 번·결제 아닌 알림·모르는 키"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, json, urllib.request, urllib.error
from datetime import datetime
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LEDGER_ADMIN_NAME='임기범')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, ledger
from ledger_parse import parse, rule_key, suggest_pattern

# ==== 알림 글 읽기
NOW = datetime(2026, 11, 26, 9, 0)
CASES = [
    ('[삼성카드] 임*범님 11/25 12:41 5,600원 일시불 스타벅스 강남점 누적 412,300원', 5600, '스타벅스 강남점', '삼성카드', '2026-11-25', '12:41', False),
    ('[Web발신]\nKB국민카드1234승인\n임*범님\n13,900원 일시불\n11/24 21:03\n쿠팡이츠\n누적1,234,000원', 13900, '쿠팡이츠', 'KB국민카드', '2026-11-24', '21:03', False),
    ('신한카드(1234)승인 임*범 42,000원(일시불)11/23 19:20 이마트 성수점 누적512,000원', 42000, '이마트 성수점', '신한카드', '2026-11-23', '19:20', False),
    ('[현대카드] 승인취소 5,600원 스타벅스 강남점 11/25 13:02', 5600, '스타벅스 강남점', '현대카드', '2026-11-25', '13:02', True),
    ('하나카드 체크 3,000원 GS25 역삼점 12/30 08:10', 3000, 'GS25 역삼점', '하나카드', '2025-12-30', '08:10', False),   # 미래 날짜 → 지난해
]
for text, amount, merchant, card, day, hhmm, cancel in CASES:
    p = parse(text, NOW)
    assert p == {'amount': amount, 'merchant': merchant, 'card': card, 'used_on': day, 'time': hhmm, 'cancel': cancel}, (text, p)
assert parse('오늘 날씨 맑음', NOW) is None and parse('카카오톡: 내일 3,000원 갚을게', NOW) is None and parse('', NOW) is None
assert parse('[삼성카드] 결제 예정 금액 안내 누적 412,300원', NOW) is None   # 누적 금액뿐
assert rule_key('(주)스타 벅스') == '스타벅스' and suggest_pattern('스타벅스 강남점') == '스타벅스' and suggest_pattern('쿠팡이츠') == '쿠팡이츠'

# ==== 서버
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'


def call(path, body=None, cookie='', raw=None, ctype='application/json'):
    data = raw.encode() if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(BASE + path, data=data, method='POST' if data is not None else 'GET',
                               headers={'Content-Type': ctype, 'Cookie': cookie})
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
assert call('/api/ledger/session', {'action': 'signup', 'name': '지은', 'password': 'pw12'})[0] == 200
jieun = call('/api/ledger/admin', cookie=admin)[1]['pending'][0]['id']
call('/api/ledger/admin', {'action': 'approve', 'user_id': jieun}, cookie=admin)
user = login('지은', 'pw12')

# 로그인 없으면 거절, 처음엔 비어 있고 연결 주소 없음
assert call('/api/ledger/inbox')[0] == 401 and call('/api/ledger/hook-key', {'action': 'create'})[0] == 401
code, ib = call('/api/ledger/inbox', cookie=user)
assert code == 200 and ib['items'] == [] and ib['rules'] == [] and ib['hook'] is None and ib['hook_base'].endswith('/api/ledger/hook/'), ib

# ---- 연결 주소 만들기 (주소는 이때만), 받기
code, data = call('/api/ledger/hook-key', {'action': 'create'}, cookie=user)
assert code == 200 and data['url'].startswith(ib['hook_base']) and data['hook']['hint'] == data['url'][-4:] and data['hook']['last_used'] is None
hook = data['url'][len(BASE):]
assert call('/api/ledger/inbox', cookie=user)[1]['hook']['hint'] == data['hook']['hint']

today = datetime.now()
md = f'{today.month}/{today.day}'
pay = f'[삼성카드] 지*님 {md} 12:41 5,600원 일시불 스타벅스 강남점 누적 412,300원'
assert call(hook, raw=pay, ctype='text/plain') == (200, {'success': True, 'result': 'saved'})
assert call(hook, raw=pay, ctype='text/plain')[1]['result'] == 'duplicate'                          # 같은 알림 또
assert call(hook, raw='배터리가 부족합니다', ctype='text/plain')[1]['result'] == 'ignored'
assert call(hook, {'text': f'KB국민카드 승인 13,900원 {md} 21:03 쿠팡이츠'})[1]['result'] == 'saved'     # JSON 본문
assert call(hook, raw='text=' + urllib.request.quote(f'신한카드 승인 42,000원 {md} 19:20 이마트 성수점'),
            ctype='application/x-www-form-urlencoded')[1]['result'] == 'saved'                       # 폼 본문
assert call('/api/ledger/hook/wrongkey', raw=pay, ctype='text/plain')[0] == 404
web_server._clear_auth_failures('127.0.0.1')

code, ib = call('/api/ledger/inbox', cookie=user)
assert [x['merchant'] for x in ib['items']] == ['쿠팡이츠', '이마트 성수점', '스타벅스 강남점'], ib['items']   # 시각 늦은 순
assert all(x['category_id'] is None and not x['cancel'] for x in ib['items'])
assert ib['hook']['last_status'] == 'saved' and ib['hook']['last_used']
assert call('/api/ledger/inbox', cookie=admin)[1]['items'] == []        # 남의 대기함은 안 보임
star, emart, coupang = (next(x['id'] for x in ib['items'] if x['merchant'] == m) for m in ('스타벅스 강남점', '이마트 성수점', '쿠팡이츠'))

cats = {c['name']: c['id'] for c in call('/api/ledger/state', cookie=user)[1]['categories']}
# 분류 없이 확정은 안 됨, 남의 알림은 못 건드림
assert call('/api/ledger/inbox', {'action': 'confirm', 'id': star}, cookie=user)[0] == 400
assert call('/api/ledger/inbox', {'action': 'discard', 'id': star}, cookie=admin)[0] == 400
assert call('/api/ledger/inbox', {'action': 'confirm_all'}, cookie=user)[1]['confirmed'] == 0

# ---- 규칙: 넣으면 대기함의 분류 없는 결제에 바로 적용, 같은 글자는 덮어씀
code, data = call('/api/ledger/rule', {'action': 'add', 'pattern': '스타벅스', 'category_id': cats['식비']}, cookie=user)
assert code == 200 and next(x for x in data['items'] if x['id'] == star)['category_id'] == cats['식비']
code, data = call('/api/ledger/rule', {'action': 'add', 'pattern': '스타 벅스', 'category_id': cats['카페']}, cookie=user)
assert [(r['pattern'], r['category_id']) for r in data['rules']] == [('스타벅스', cats['카페'])], data['rules']
assert next(x for x in data['items'] if x['id'] == star)['category_id'] == cats['식비']                # 이미 정해진 건 그대로
assert call('/api/ledger/rule', {'action': 'add', 'pattern': '스', 'category_id': cats['카페']}, cookie=user)[0] == 400
assert call('/api/ledger/rule', {'action': 'add', 'pattern': '이마트', 'category_id': 99999}, cookie=user)[0] == 400

# ---- 고치기 (분류·금액·가게·날짜), 잘못된 값은 거절
code, data = call('/api/ledger/inbox', {'action': 'update', 'id': coupang, 'category_id': cats['식비'], 'amount': 14900, 'merchant': '  쿠팡이츠   치킨 '}, cookie=user)
x = next(x for x in data['items'] if x['id'] == coupang)
assert code == 200 and (x['amount'], x['merchant'], x['category_id']) == (14900, '쿠팡이츠 치킨', cats['식비'])
assert call('/api/ledger/inbox', {'action': 'update', 'id': coupang, 'amount': 0}, cookie=user)[0] == 400
assert call('/api/ledger/inbox', {'action': 'update', 'id': coupang, 'used_on': '2026-13-01'}, cookie=user)[0] == 400

# ---- 하나 확정 → 기록(메모는 가게 이름), 버리기, 모두 확정
assert call('/api/ledger/inbox', {'action': 'confirm', 'id': star}, cookie=user)[0] == 200
assert call('/api/ledger/inbox', {'action': 'discard', 'id': emart}, cookie=user)[0] == 200
code, data = call('/api/ledger/inbox', {'action': 'confirm_all'}, cookie=user)
assert code == 200 and data['confirmed'] == 1 and data['items'] == []
month = today.strftime('%Y-%m')
entries = call(f'/api/ledger/state?month={month}', cookie=user)[1]['entries']
assert sorted((e['amount'], e['memo'], e['category_id'], e['user_id']) for e in entries) == \
    sorted([(5600, '스타벅스 강남점', cats['식비'], jieun), (14900, '쿠팡이츠 치킨', cats['식비'], jieun)]), entries

# ---- 새 규칙은 다음 알림부터 바로 분류됨
assert call(hook, raw=f'[삼성카드] {md} 08:05 4,500원 일시불 스타벅스 역삼점', ctype='text/plain')[1]['result'] == 'saved'
item = call('/api/ledger/inbox', cookie=user)[1]['items'][0]
assert item['category_id'] == cats['카페'], item
call('/api/ledger/inbox', {'action': 'discard', 'id': item['id']}, cookie=user)

# ---- 취소: 같은 금액·가게의 기록을 찾아 확정하면 지움, 못 찾으면 알림만 지움
assert call(hook, raw=f'[현대카드] 승인취소 5,600원 스타벅스 강남점 {md} 13:02', ctype='text/plain')[1]['result'] == 'saved'
assert call(hook, raw=f'[현대카드] 승인취소 77,000원 어딘가 {md} 13:05', ctype='text/plain')[1]['result'] == 'saved'
items = call('/api/ledger/inbox', cookie=user)[1]['items']
found = next(x for x in items if x['amount'] == 5600)
lost = next(x for x in items if x['amount'] == 77000)
assert found['cancel'] and found['match'] and found['category_id'] is None and lost['cancel'] and lost['match'] is None, items
code, data = call('/api/ledger/inbox', {'action': 'confirm_all'}, cookie=user)
assert data['confirmed'] == 1 and [x['id'] for x in data['items']] == [lost['id']]                  # 못 찾은 취소는 남음
entries = call(f'/api/ledger/state?month={month}', cookie=user)[1]['entries']
assert [e['memo'] for e in entries] == ['쿠팡이츠 치킨'], entries
assert call('/api/ledger/inbox', {'action': 'confirm', 'id': lost['id']}, cookie=user)[1]['items'] == []

# ---- 시험 알림, 연결 주소 새로 만들면 예전 주소는 못 씀
code, data = call('/api/ledger/inbox', {'action': 'test'}, cookie=user)
assert code == 200 and len(data['items']) == 1 and data['items'][0]['amount'] == 1000 and data['items'][0]['card'] == '삼성카드', data
call('/api/ledger/inbox', {'action': 'discard', 'id': data['items'][0]['id']}, cookie=user)
new = call('/api/ledger/hook-key', {'action': 'create'}, cookie=user)[1]['url'][len(BASE):]
assert new != hook and call(hook, raw=pay, ctype='text/plain')[0] == 404 and call(new, raw=pay + ' 2', ctype='text/plain')[1]['result'] == 'saved'
web_server._clear_auth_failures('127.0.0.1')

# ---- 허락을 취소하면 연결 주소로도 못 보냄, 규칙 지우기
call('/api/ledger/admin', {'action': 'revoke', 'user_id': jieun}, cookie=admin)
assert call(new, raw=pay + ' 3', ctype='text/plain')[0] == 404
web_server._clear_auth_failures('127.0.0.1')
rule_id = call('/api/ledger/inbox', cookie=admin)[1]['rules'][0]['id']
assert call('/api/ledger/rule', {'action': 'delete', 'id': rule_id}, cookie=admin)[1]['rules'] == []
assert call('/api/ledger/rule', {'action': 'delete', 'id': rule_id}, cookie=admin)[0] == 400

# ---- 너무 긴 본문
assert call(new, raw='가' * 5000, ctype='text/plain')[0] == 413
srv.shutdown()
print('ledger hook OK')
