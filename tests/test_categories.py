import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, importlib.util, io, contextlib, threading, json, sqlite3, urllib.request
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LOG_LEVEL='WARN',
                  KEYWORDS_BASEBALL='삼성')
import storage, web_server, scraper, config

storage.init_db()

# --- 1) 처음 만든 DB: BOARD_MAP 기본 카테고리가 확인된(ok) 상태로 들어가고, 기존 키워드도 그대로 수집 대상
cats = storage.list_categories()
assert [c['key'] for c in cats] == list(config.BOARD_MAP), cats
assert all(c['status'] == 'ok' for c in cats)
assert storage.load_keywords()['baseball'] == ['삼성']
assert list(storage.load_keywords()) == list(config.BOARD_MAP)
baseball = next(c for c in cats if c['key'] == 'baseball')
assert baseball['keyword_count'] == 1 and baseball['groups'] == ['삼성'], baseball

# 기본 카테고리를 지워도 다시 시작할 때 되살아나지 않음 (처음 1회만 채움)
storage.delete_category('humor')
storage._initialized = False
storage.init_db()
assert 'humor' not in storage.category_names()
print('SEED OK')

# --- 2) 키워드가 BOARD_MAP 밖의 게시판에 등록된 예전 DB도 그 게시판을 카테고리로 이어받음
legacy_dir = tempfile.mkdtemp()
legacy = sqlite3.connect(os.path.join(legacy_dir, 'board.db'))
storage._create_schema(legacy)
legacy.execute("INSERT INTO meta(key, value) VALUES('schema_version', '1'), ('keyword_boards_migrated', '1')")
legacy.execute("INSERT INTO keywords(board, keyword) VALUES('football_world', '손흥민')")
legacy.commit(); legacy.close()
with contextlib.closing(sqlite3.connect(os.path.join(legacy_dir, 'board.db'))) as conn:
    conn.row_factory = sqlite3.Row
    with conn:
        storage._seed_categories(conn)
    rows = {r['key']: dict(r) for r in conn.execute("SELECT * FROM categories")}
assert rows['football_world']['status'] == 'ok' and rows['football_world']['name'] == 'football_world', rows
print('LEGACY SEED OK')

# --- 3) 주소·mid 입력 해석
cases = {
    'hotdeal': 'hotdeal',
    ' HotDeal ': 'hotdeal',
    'https://www.fmkorea.com/hotdeal': 'hotdeal',
    'https://m.fmkorea.com/football_world': 'football_world',
    'fmkorea.com/index.php?mid=stock&page=2': 'stock',
    'https://www.fmkorea.com/index.php?mid=car&search_keyword=x': 'car',
    'https://www.fmkorea.com/12345': None,       # 글 주소
    '12345': None,
    'https://www.fmkorea.com/': None,
    'https://example.com/hotdeal': None,
    'https://fmkorea.com.evil.com/hotdeal': None,
    'hot deal': None,
    '': None,
}
for text, expected in cases.items():
    assert web_server.board_key_from_input(text) == expected, (text, web_server.board_key_from_input(text))
print('INPUT PARSE OK')

# --- 4) 게시판 확인 (표 형태 목록인지)
class Page:
    def __init__(self, html, title): self.page_source, self.title, self.urls = html, title, []
    def get(self, url): self.urls.append(url)
scraper.WebDriverWait = lambda d, t: type('W', (), {'until': lambda self, c: True})()
scraper.time.sleep = lambda s: None
table = '<div class="bd_lst_wrp"><table class="bd_lst"><tbody><tr><td class="title"><a class="hx" href="/123">t</a></td></tr></tbody></table></div>'
cards = '<div class="fm_best_widget"><ul><li class="li"><h3 class="title"><a href="/123">t</a></h3></li></ul></div>'
page = Page(table, '핫딜 - 에펨코리아')
assert scraper.check_board(page, 'hotdeal') == (True, '핫딜') and page.urls == ['https://www.fmkorea.com/index.php?mid=hotdeal']
ok, reason = scraper.check_board(Page(cards, '핫딜 - 에펨코리아'), 'hotdeal')
assert not ok and '핫딜 - 에펨코리아' in reason, reason
assert scraper.check_board(Page('<table class="bd_lst"><tbody></tbody></table>', 'x'), 'x')[0] is False
assert scraper.board_title('캐스퍼 - 자동차 - 에펨코리아') == '자동차' and scraper.board_title('') == ''
print('CHECK BOARD OK')

# --- 5) 메인 루프: 추가한 카테고리는 확인 전에는 수집하지 않고, 확인되면 다음 주기부터 수집.
#        수집할 수 없는 게시판은 차단 의심으로 보지 않음 (대기 시간·텔레그램 그대로)
storage.add_category('football_world')           # 이름 없이 추가 → 게시판 제목으로 채움
storage.add_category('wrongmid', '오타')
storage.save_group(None, '해외축구 모음', [{'board': 'football_world', 'keyword': '손흥민'}, {'board': 'wrongmid', 'keyword': 'x'}])
assert 'football_world' not in storage.load_keywords() and storage.pending_categories() == ['football_world', 'wrongmid']

spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class FakeDriver:
    def execute_script(self, s): return 1
    def quit(self): pass
m.create_driver = lambda: FakeDriver()
m.run_api_server = lambda: None
state = {'cycle': 0, 'list_calls': [], 'checks': [], 'sleeps': [], 'telegram': []}
def fake_list(driver, board, keyword, page=1):
    state['list_calls'].append((state['cycle'], board))
    return []
def fake_check(driver, board):
    state['checks'].append((state['cycle'], board))
    if board == 'football_world':
        return True, '해외축구'
    return False, '글 목록(표)이 없는 페이지 (제목: 에펨코리아)'
m.get_list_page_posts = fake_list
m.check_board = fake_check
m.send_telegram_message = lambda text: state['telegram'].append(text)
def fake_sleep(s):
    state['sleeps'].append(s)
    state['cycle'] += 1
    if state['cycle'] > 2:
        raise KeyboardInterrupt
m.time.sleep = fake_sleep
with contextlib.redirect_stdout(io.StringIO()):
    m.main()
print('checks', state['checks'], 'list calls', sorted(set(state['list_calls'])))
assert state['checks'] == [(0, 'football_world'), (0, 'wrongmid')], state['checks']
assert (0, 'football_world') not in state['list_calls'] and (1, 'football_world') in state['list_calls']
assert not any(b == 'wrongmid' for _, b in state['list_calls'])
assert state['sleeps'] == [config.CHECK_INTERVAL] * 3 and state['telegram'] == [], (state['sleeps'], state['telegram'])
cats = {c['key']: c for c in storage.list_categories()}
assert cats['football_world']['status'] == 'ok' and cats['football_world']['name'] == '해외축구', cats['football_world']
assert cats['wrongmid']['status'] == 'invalid' and cats['wrongmid']['name'] == '오타' and '표' in cats['wrongmid']['message']
assert storage.load_keywords()['football_world'] == ['손흥민'] and 'wrongmid' not in storage.load_keywords()
print('MAIN LOOP OK')

# 차단 의심 주기에는 확인하지 않음 (차단 화면을 잘못된 게시판으로 오판하지 않도록)
storage.recheck_category('wrongmid')
state.update(cycle=0, checks=[], sleeps=[], telegram=[])
def blocked_list(driver, board, keyword, page=1):
    if state['cycle'] == 0:
        raise m.BlockedError('게시판 목록이 아닌 페이지 응답 (제목: Just a moment...)')
    return []
m.get_list_page_posts = blocked_list
with contextlib.redirect_stdout(io.StringIO()):
    m.main()
assert state['checks'] == [(1, 'wrongmid')], state['checks']
print('BLOCKED CYCLE SKIP OK')

# --- 6) 관리 API
srv = web_server.ThreadedHTTPServer(('127.0.0.1', 0), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{srv.server_address[1]}'
def post(body, password='Secr3t!'):
    req = urllib.request.Request(base + '/api/category', data=json.dumps({**body, 'password': password}).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
def get_state():
    with urllib.request.urlopen(base + '/api/state') as res:
        return json.load(res)

assert post({'action': 'create', 'input': 'https://www.fmkorea.com/stock'}, password='wrong')[0] == 401
status, data = post({'action': 'create', 'input': 'https://www.fmkorea.com/stock'})
assert status == 200 and data['key'] == 'stock', data
assert post({'action': 'create', 'input': 'stock'})[0] == 400                      # 중복
assert post({'action': 'create', 'input': 'https://www.fmkorea.com/1234'})[0] == 400  # 글 주소
assert post({'action': 'create', 'input': 'x', 'name': '가' * 21})[0] == 400
boards = {b['key']: b for b in get_state()['boards']}
assert boards['stock']['status'] == 'pending' and boards['stock']['name'] == 'stock'
assert boards['football_world']['groups'] == ['해외축구 모음']

assert post({'action': 'rename', 'key': 'stock', 'name': '주식'})[0] == 200
assert post({'action': 'rename', 'key': 'nope', 'name': '주식'})[0] == 400
assert post({'action': 'rename', 'key': 'stock', 'name': ' '})[0] == 400
# 확인 대기 중인 카테고리에도 키워드를 미리 등록할 수 있음 (확인되면 수집)
req = urllib.request.Request(base + '/api/group', data=json.dumps({
    'action': 'create', 'name': '주식', 'members': [{'board': 'stock', 'keyword': '삼전'}], 'password': 'Secr3t!'}).encode(),
    headers={'Content-Type': 'application/json'})
assert json.load(urllib.request.urlopen(req))['success']
st = get_state()
member = next(g for g in st['groups'] if g['name'] == '주식')['members'][0]
assert member['board_name'] == '주식', member
# 없는 카테고리의 키워드는 거부
req = urllib.request.Request(base + '/api/group', data=json.dumps({
    'action': 'create', 'name': 'x', 'members': [{'board': 'nope', 'keyword': 'a'}], 'password': 'Secr3t!'}).encode(),
    headers={'Content-Type': 'application/json'})
try:
    urllib.request.urlopen(req); raise SystemExit('unknown category accepted')
except urllib.error.HTTPError as e:
    assert e.code == 400

# 키워드가 등록된 카테고리는 삭제 거부, 키워드를 빼면 삭제 가능
status, data = post({'action': 'delete', 'key': 'stock'})
assert status == 400 and '주식' in data['message'], data
assert post({'action': 'recheck', 'key': 'stock'})[0] == 400                       # 실패 상태가 아님
storage.delete_group(next(g for g in st['groups'] if g['name'] == '주식')['id'])
assert post({'action': 'delete', 'key': 'stock'})[0] == 200
assert 'stock' not in storage.category_names()
assert post({'action': 'recheck', 'key': 'wrongmid'})[0] == 200
assert post({'action': 'drop'})[0] == 400
srv.shutdown()
print('API OK')
print('CATEGORIES OK')
