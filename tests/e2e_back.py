import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# 뒤로 가기: 휴대폰·넓은 화면 모두 보통 브라우저처럼 이전 화면으로 (두 번 누르면 종료하던 방식은 없앰)
storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
for i in range(3):
    storage.save_keyword_post('car', '싼타페', {'id': str(901 + i), 'title': f'글 {i}', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                                'comment_count': '0', 'link': f'/{901 + i}', 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}, is_new=True)
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
o.add_argument('--headless=new')
o.add_experimental_option('mobileEmulation', {'deviceMetrics': {'width': 390, 'height': 844, 'pixelRatio': 2}})
d = Chrome(options=o)
js = d.execute_script
def menu(key):
    js(f"document.querySelector('.site-nav [data-nav={key}]').click()"); time.sleep(2)
try:
    d.get(BASE + '/'); time.sleep(1.5)
    # 메뉴로 옮긴 순서대로 뒤로 가면 하나씩 이전 화면
    visited = ['/']
    for key, path in [('card', '/card/'), ('ev', '/ev/'), ('apt', '/apt/'), ('stats', '/stats/')]:
        menu(key)
        assert d.current_url.startswith(BASE + path), (key, d.current_url)
        visited.append(path)
    for path in reversed(visited[:-1]):
        d.back(); time.sleep(1.5)
        assert d.current_url.startswith(BASE + path), (path, d.current_url)
        assert not js("return !!document.querySelector('.nav-exit-toast')")
    print('BACK TO PREVIOUS OK')

    # 대시보드 카드로 연 페이지에서 뒤로 → 대시보드
    js("document.querySelector('#card-ev .card-head').click()"); time.sleep(2)
    assert d.current_url == BASE + '/ev/'
    d.back(); time.sleep(1.5)
    assert d.current_url == BASE + '/', d.current_url
    # 게시판 안의 글 링크(#post-)도 뒤로 가면 돌아옴, 한 번 더 뒤로 가면 이전 페이지
    menu('board')
    js("location.hash = 'post-901'"); time.sleep(2)
    d.back(); time.sleep(1.2)
    assert d.current_url.startswith(BASE + '/board/'), d.current_url
    d.back(); time.sleep(1.5)
    assert d.current_url == BASE + '/', d.current_url
    print('BACK OK')
finally:
    d.quit()
    srv.shutdown()
