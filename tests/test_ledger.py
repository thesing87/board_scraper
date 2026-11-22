"""가계부 API (ledger.py): 가입 요청 → 관리자 허락 전에는 로그인 안 됨 → 허락하면 로그인(가계부 전용 쿠키),
관리자는 관리자 암호·로그인 키로(이름 없이도), 기록은 모두가 함께 보고 고치기·지우기는 쓴 사람과 관리자만,
소비형태는 누구나 추가·색·이름 바꾸기(기록에 쓰인 것은 못 지움), 최근 메모, 허락 취소하면 로그인이 끊김, 로그인 실패 잠금"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, json, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LEDGER_ADMIN_NAME='임기범')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, ledger

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
            return res.status, json.loads(res.read()), res.headers
    except urllib.error.HTTPError as e:
        data = e.read()
        return e.code, (json.loads(data) if data else {}), e.headers


def login(name, password):
    code, data, h = call('/api/ledger/session', {'action': 'login', 'name': name, 'password': password})
    return code, data, (h.get('Set-Cookie') or '').split(';')[0]


# ---- 로그인 없으면 거절
assert call('/api/ledger/state')[0] == 401 and call('/api/ledger/entry', {'action': 'add'})[0] == 401

# ---- 관리자: 이름 + 관리자 암호, 또는 이름 없이 로그인 키
code, data, admin = login('임기범', 'Secr3t!')
assert code == 200 and data['user'] == {'id': data['user']['id'], 'name': '임기범', 'admin': True}, data
_, h_cookie = None, None
code, data, h = call('/api/ledger/session', {'action': 'login', 'password': web_server.ADMIN_TOKEN})
assert code == 200 and data['user']['admin']
assert 'HttpOnly' in h['Set-Cookie'] and 'Path=/api/ledger/' in h['Set-Cookie']
assert login('임기범', 'wrong')[0] == 401

# ---- 가입 요청: 허락 전에는 로그인 안 됨, 이름 겹치면 거절
assert call('/api/ledger/session', {'action': 'signup', 'name': '지은', 'password': 'pw12'})[0] == 200
assert call('/api/ledger/session', {'action': 'signup', 'name': '지은', 'password': 'pw12'})[1]['message'].startswith('❌ 이미 있는 이름')
assert call('/api/ledger/session', {'action': 'signup', 'name': '임기범', 'password': 'pw12'})[0] == 400
assert call('/api/ledger/session', {'action': 'signup', 'name': '홍길동', 'password': '12'})[0] == 400   # 짧은 비밀번호
assert call('/api/ledger/session', {'action': 'signup', 'name': '홍길동', 'password': 'pw34'})[0] == 200
code, data, _ = login('지은', 'pw12')
assert code == 403 and '허락' in data['message'], data
web_server._clear_auth_failures('127.0.0.1')

# ---- 관리자 화면: 기다리는 사람 → 허락·거절 (관리자가 아니면 거절)
code, people, _ = call('/api/ledger/admin', cookie=admin)
assert [p['name'] for p in people['pending']] == ['지은', '홍길동'] and [m['name'] for m in people['members']] == ['임기범'], people
jieun = next(p['id'] for p in people['pending'] if p['name'] == '지은')
hong = next(p['id'] for p in people['pending'] if p['name'] == '홍길동')
code, data, _ = call('/api/ledger/admin', {'action': 'approve', 'user_id': jieun}, cookie=admin)
assert code == 200 and [m['name'] for m in data['members']] == ['임기범', '지은'], data
assert call('/api/ledger/admin', {'action': 'reject', 'user_id': hong}, cookie=admin)[1]['pending'] == []
assert call('/api/ledger/admin', {'action': 'revoke', 'user_id': data['members'][0]['id']}, cookie=admin)[0] == 400   # 관리자는 못 바꿈
code, data, user = login('지은', 'pw12')
assert code == 200 and data['user'] == {'id': jieun, 'name': '지은', 'admin': False}
assert call('/api/ledger/admin', cookie=user)[0] == 404 and call('/api/ledger/admin', {'action': 'approve', 'user_id': hong}, cookie=user)[0] == 403
assert login('홍길동', 'pw34')[0] == 401   # 거절된 요청은 지워짐
web_server._clear_auth_failures('127.0.0.1')

# ---- 지은은 가계부만: 다른 관리 기능(카드 등)은 쿠키로 열리지 않음
assert call('/api/card', {'action': 'list', 'password': ''}, cookie=user)[0] == 401
web_server._clear_auth_failures('127.0.0.1')

# ---- 소비형태: 처음 6개, 누구나 추가(색 필수)·바꾸기
st = call('/api/ledger/state?month=2026-11', cookie=user)[1]
assert [c['name'] for c in st['categories'] if c['kind'] == 'expense'] == ['식비', '카페', '교통', '생활', '쇼핑', '의료'] and st['month'] == '2026-11'
assert [c['name'] for c in st['categories'] if c['kind'] == 'income'] == ['급여', '부수입', '용돈', '이자·환급']
# 수입 종류 추가 (kind), 잘못된 kind는 거절
assert call('/api/ledger/category', {'action': 'add', 'name': '상여', 'color': '#185FA5', 'kind': 'bonus'}, cookie=user)[0] == 400
code, data, _ = call('/api/ledger/category', {'action': 'add', 'name': '상여', 'color': '#185FA5', 'kind': 'income'}, cookie=user)
assert code == 200 and next(c for c in call('/api/ledger/state', cookie=user)[1]['categories'] if c['id'] == data['id'])['kind'] == 'income'
assert call('/api/ledger/category', {'action': 'delete', 'id': data['id']}, cookie=user)[0] == 200
assert call('/api/ledger/category', {'action': 'add', 'name': '반려동물'}, cookie=user)[1]['message'] == '❌ 색을 골라 주세요.'
assert call('/api/ledger/category', {'action': 'add', 'name': '식비', 'color': '#112233'}, cookie=user)[0] == 400
code, data, _ = call('/api/ledger/category', {'action': 'add', 'name': '반려동물', 'color': '#2ba7b8'}, cookie=user)
pet = data['id']
cats = {c['name']: c for c in call('/api/ledger/state?month=2026-11', cookie=user)[1]['categories']}
assert cats['반려동물']['color'] == '#2BA7B8'
food, cafe = cats['식비']['id'], cats['카페']['id']

# ---- 기록: 함께 보기, 고치기·지우기는 쓴 사람과 관리자만
def add(cookie, amount, day, cat, memo=''):
    code, data, _ = call('/api/ledger/entry', {'action': 'add', 'amount': amount, 'used_on': day, 'category_id': cat, 'memo': memo}, cookie=cookie)
    assert code == 200, data
    return data['id']
e1 = add(admin, 42000, '2026-11-22', food, '이마트 장보기')
e2 = add(user, 5600, '2026-11-22', cafe, '스타벅스')
e3 = add(user, 3000, '2026-10-30', cafe, '스타벅스')
assert call('/api/ledger/entry', {'action': 'add', 'amount': 0, 'used_on': '2026-11-22', 'category_id': food}, cookie=user)[0] == 400
assert call('/api/ledger/entry', {'action': 'add', 'amount': 10, 'used_on': '2026-02-30', 'category_id': food}, cookie=user)[0] == 400
assert call('/api/ledger/entry', {'action': 'add', 'amount': 10, 'used_on': '2026-11-22', 'category_id': 999}, cookie=user)[0] == 400
st = call('/api/ledger/state?month=2026-11', cookie=user)[1]
assert [e['id'] for e in st['entries']] == [e2, e1] and {m['name'] for m in st['members']} == {'임기범', '지은'}
assert st['memos'][:2] == [{'memo': '스타벅스', 'category_id': cafe}, {'memo': '이마트 장보기', 'category_id': food}], st['memos']
assert [e['id'] for e in call('/api/ledger/state?month=2026-10', cookie=admin)[1]['entries']] == [e3]
assert call('/api/ledger/entry', {'action': 'edit', 'id': e1, 'amount': 1, 'used_on': '2026-11-22', 'category_id': food}, cookie=user)[1]['message'] == '❌ 내가 쓴 기록만 고칠 수 있어요.'
assert call('/api/ledger/entry', {'action': 'edit', 'id': e2, 'amount': 6100, 'used_on': '2026-11-21', 'category_id': pet, 'memo': ' 간식  '}, cookie=user)[0] == 200
assert call('/api/ledger/entry', {'action': 'delete', 'id': e2}, cookie=admin)[0] == 200   # 관리자는 남의 기록도
assert [e['memo'] for e in call('/api/ledger/state?month=2026-11', cookie=user)[1]['entries']] == ['이마트 장보기']
# 소비형태: 이름 바꾸면 기록도 따라감, 기록에 쓰인 것은 못 지움
assert call('/api/ledger/category', {'action': 'edit', 'id': food, 'name': '먹거리', 'color': '#FF0000'}, cookie=user)[0] == 200
st = call('/api/ledger/state?month=2026-11', cookie=user)[1]
assert next(c for c in st['categories'] if c['id'] == st['entries'][0]['category_id'])['name'] == '먹거리'
assert call('/api/ledger/category', {'action': 'delete', 'id': food}, cookie=user)[1]['message'] == '❌ 기록에 쓰인 소비형태는 지울 수 없어요.'
assert call('/api/ledger/category', {'action': 'delete', 'id': pet}, cookie=user)[0] == 200

# ---- 허락 취소: 로그인이 끊기고, 쓴 기록과 이름은 기록 목록에 그대로
assert call('/api/ledger/admin', {'action': 'revoke', 'user_id': jieun}, cookie=admin)[0] == 200
assert call('/api/ledger/state', cookie=user)[0] == 401 and login('지은', 'pw12')[0] == 403
assert '지은' in {m['name'] for m in call('/api/ledger/state?month=2026-10', cookie=admin)[1]['members']}
assert call('/api/ledger/admin', {'action': 'reject', 'user_id': jieun}, cookie=admin)[1]['message'] == '❌ 기록이 있는 사람은 지울 수 없어요.'

# ---- 로그아웃하면 그 쿠키는 더 못 씀
assert call('/api/ledger/session', {'action': 'logout'}, cookie=admin)[0] == 200
assert call('/api/ledger/state', cookie=admin)[0] == 401

# ---- 로그인을 여러 번 틀리면 잠시 막힘
web_server._clear_auth_failures('127.0.0.1')
codes = [login('임기범', f'x{i}')[0] for i in range(6)]
assert codes[-1] == 429, codes
web_server._clear_auth_failures('127.0.0.1')
# ---- 예전 가계부 DB(분류에 kind 칸 없음): 칸을 더하고 예전 분류는 모두 지출, 수입 종류는 한 번만 들어감
import sqlite3
old = sqlite3.connect(':memory:')
old.row_factory = sqlite3.Row
old.execute("CREATE TABLE ledger_categories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, color TEXT, position INTEGER, created_at TEXT)")
old.execute("INSERT INTO ledger_categories(name, color, position, created_at) VALUES('식비', '#D85A30', 0, 't')")
storage._create_schema(old)            # 나머지 표는 지금 구조로 (ledger_categories는 이미 있어 그대로)
storage._add_missing_columns(old)
assert [tuple(r) for r in old.execute("SELECT name, kind FROM ledger_categories")] == [('식비', 'expense')]
srv.shutdown()
print('LEDGER API OK')
