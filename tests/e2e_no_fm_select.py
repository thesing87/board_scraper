"""관리 화면에서 에펨코리아를 고를 수 없음 (에펨코리아 수집 기능 없앰): 게시판 편집의 카테고리 칩·카테고리 목록·사이트 이름에
에펨코리아가 없고, 예전 에펨코리아 키워드는 게시판을 고쳐 저장해도 그대로 남음 (예전 글이 게시판에 계속 보이게).
API로도 에펨코리아 키워드를 새로 등록할 수 없음"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, time, json, socket, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
storage.add_category('dc:car_new1')
storage.set_category_checked('dc:car_new1', True, page_name='자동차 갤러리')
old_id, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}, {'board': 'dc:car_new1', 'keyword': '싼타페'}])

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'

def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps({**body, 'password': 'Secr3t!'}).encode(), {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# API: 새 에펨코리아 키워드는 거부, 예전부터 있던 것은 그대로 둘 수 있음
status, data = post('/api/group', {'action': 'create', 'name': '새것', 'members': [{'board': 'car', 'keyword': '캐스퍼'}]})
assert status == 400 and '새로 등록할 수 없습니다' in data['message'], (status, data)
status, data = post('/api/group', {'action': 'update', 'id': old_id, 'name': '싼타페',
                                   'members': [{'board': 'car', 'keyword': '싼타페'}, {'board': 'dc:car_new1', 'keyword': '싼타페'}]})
assert status == 200, data
print('API OK')

o = Options()
for a in ['--headless=new', '--window-size=1440,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get(BASE + '/board/'); time.sleep(2.5)
    js("localStorage.setItem('admin_token', 'Secr3t!'); updateAdminUI(); document.querySelector('.topbar [data-action=\"open-settings\"]').click()"); time.sleep(0.5)
    # 새 게시판: 카테고리 칩에 디시만, 기본으로 디시가 골라짐
    js("document.querySelector('[data-action=\"new-group\"]').click()"); time.sleep(0.4)
    chips = js("return [...document.querySelectorAll('#group-board-checks .board-check')].map(b => [b.dataset.board, b.getAttribute('aria-pressed')])")
    assert chips == [['dc:car_new1', 'true']], chips
    targets = js("return [...document.querySelectorAll('#group-kw-target option')].map(o => o.value)")
    assert targets == ['dc:car_new1'], targets
    # 예전 게시판 수정: 에펨코리아 칩·찾을 곳·키워드 태그가 없음
    js("document.querySelector('[data-action=\"cancel-group\"]') && document.querySelector('[data-action=\"cancel-group\"]').click()"); time.sleep(0.3)
    js(f"document.querySelector('[data-action=\"edit-group\"][data-group-id=\"{old_id}\"]').click()"); time.sleep(0.4)
    chips = js("return [...document.querySelectorAll('#group-board-checks .board-check')].map(b => b.dataset.board)")
    assert chips == ['dc:car_new1'], chips
    assert js("return [...document.querySelectorAll('#group-kw-target option')].map(o => o.value)") == ['dc:car_new1']
    # 수집할 키워드 칸에는 에펨코리아 키워드가 없음 (에펨코리아는 아래 '바로가기' 칸에서 링크로만)
    tags = js("return document.getElementById('group-keywords').textContent + document.getElementById('group-kw-target').textContent")
    assert 'FM' not in tags and '에펨코리아' not in tags, tags
    # 카테고리 목록·사이트 이름: 디시만
    js("document.querySelector('[data-action=\"settings-tab\"][data-tab=\"sources\"]').click()"); time.sleep(0.3)
    cats = js("return document.getElementById('settings-categories').textContent")
    assert '자동차 갤러리' in cats and '유머' not in cats and '핫딜' not in cats, cats
    sites = js("return [...document.querySelectorAll('#settings-sites .site-name-input')].map(i => i.dataset.site)")
    assert sites == ['dcinside'], sites
    print('UI OK')
finally:
    d.quit()
    srv.shutdown()
print('NO FM SELECT OK')
