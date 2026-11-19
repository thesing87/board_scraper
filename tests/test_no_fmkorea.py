"""에펨코리아 수집 기능 없앰 (이용약관상 자동 수집을 하지 말아 달라는 운영자 답변): 에펨코리아로는 목록·글·게시판 확인 요청이
나가지 않고, 관리 화면에서 에펨코리아 게시판을 새로 추가할 수 없음. 디시인사이드는 그대로"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, json, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import sites, storage, web_server

assert not sites.site_enabled(sites.FMKOREA) and sites.site_enabled(sites.DCINSIDE)
for call in (lambda: sites.get_list_page_posts(None, 'car', '싼타페'),
             lambda: sites.scrape_post_detail(None, {'id': '123'}),
             lambda: sites.check_board(None, 'humor')):
    try:
        call()
        raise AssertionError('에펨코리아 요청이 막히지 않음')
    except sites.SiteDisabledError:
        pass
assert sites._collector(sites.DCINSIDE).__name__ == 'dcinside'

# 관리 화면: 에펨코리아 게시판은 추가 못 함, 디시 갤러리는 됨
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def post(body):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/category', json.dumps(body).encode(), {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
try:
    status, data = post({'password': 'Secr3t!', 'action': 'create', 'input': 'https://www.fmkorea.com/football_world', 'name': '해외축구'})
    assert status == 400 and '에펨코리아는 수집하지 않습니다' in data['message'], (status, data)
    assert 'football_world' not in storage.category_names()
    status, data = post({'password': 'Secr3t!', 'action': 'create', 'input': 'https://gall.dcinside.com/board/lists/?id=car_new1', 'name': '자동차'})
    assert status == 200 and 'dc:car_new1' in storage.category_names(), (status, data)
finally:
    srv.shutdown()
print('DISABLED SITES OK')
