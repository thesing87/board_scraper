import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, importlib.util, threading, socket, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='', ADMIN_PASSWORD='Secr3t!')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''

# 알림 버튼의 게시판 링크: DDNS_URL에 index.html 같은 페이지 파일이 붙어 있어도 /board/#post-ID
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
for ddns, expected in [('https://nas.me/index.html', 'https://nas.me/board/#post-7'),
                       ('https://nas.me/', 'https://nas.me/board/#post-7'),
                       ('nas.me:8082', 'http://nas.me:8082/board/#post-7'),
                       ('https://nas.me/app/index.htm', 'https://nas.me/app/board/#post-7'),
                       ('https://nas.me/#post-1', 'https://nas.me/board/#post-7')]:
    m.DDNS_URL = ddns
    assert m.post_urls({'id': '7', 'link': '/7'})[0] == expected, (ddns, m.post_urls({'id': '7'}))
m.DDNS_URL = ''
assert m.post_urls({'id': '7', 'link': '/7'}) == ('', 'https://www.fmkorea.com/7')
print('URL OK')

# 이미 보낸 /index.html/board/ 링크는 /board/로
import storage, web_server
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
try:
    for path in ('/index.html/board/', '/index.html/board'):
        try:
            urllib.request.build_opener(NoRedirect).open(f'http://127.0.0.1:{port}{path}')
            raise AssertionError(path)
        except urllib.error.HTTPError as e:
            assert e.code == 301 and e.headers['Location'] == '/board/', (path, e.code)
    assert urllib.request.urlopen(f'http://127.0.0.1:{port}/index.html/board/').status == 200
    print('REDIRECT OK')
finally:
    srv.shutdown()
