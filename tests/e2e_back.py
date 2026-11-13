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
from selenium.webdriver.common.by import By

# 뒤로 가기: 페이지는 보통 브라우저처럼 이전 화면으로. 휴대폰의 대시보드(홈)에서는 두 번 연달아 누르면 종료(사이트에서 나감)
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
def touch():
    # 실제로 화면을 누름 (스크립트로 누르면 사용자 입력으로 치지 않음)
    d.find_element(By.CSS_SELECTOR, '.site-top h1').click(); time.sleep(.3)
def menu(key):
    js(f"document.querySelector('.site-nav [data-nav={key}]').click()"); time.sleep(2)
try:
    toast = lambda: js("const t = document.querySelector('.nav-toast'); return !!t && t.classList.contains('is-shown')")
    d.get('data:,')
    d.get(BASE + '/'); time.sleep(1.5)
    # 홈이 아닌 페이지는 옮긴 순서대로 뒤로 가면 하나씩 이전 화면 (안내 없음)
    visited = []
    for key, path in [('card', '/card/'), ('ev', '/ev/'), ('apt', '/apt/'), ('stats', '/stats/')]:
        menu(key)
        assert d.current_url.startswith(BASE + path), (key, d.current_url)
        visited.append(path)
    for path in reversed(visited[:-1]):
        d.back(); time.sleep(1.5)
        assert d.current_url.startswith(BASE + path) and not toast(), (path, d.current_url)
    # 그다음 뒤로: 홈으로
    d.back(); time.sleep(1.5)
    assert d.current_url == BASE + '/', d.current_url
    print('BACK TO PREVIOUS OK')

    # 홈에서 뒤로 1번: 나가지 않고 안내, 2초 지나면 다시 처음부터
    # (지키는 칸은 화면을 한 번 누른 뒤에 들어감: 크롬은 누르지 않은 페이지가 넣은 칸을 뒤로 가기에서 건너뜀)
    touch()
    d.back(); time.sleep(.8)
    assert d.current_url == BASE + '/' and toast()
    time.sleep(2.5)
    assert not toast()
    d.back(); time.sleep(.8)
    assert d.current_url == BASE + '/' and toast()
    # 2초 안에 한 번 더: 사이트에서 나감 (앱이면 종료)
    d.back(); time.sleep(2)
    assert not d.current_url.startswith(BASE), d.current_url
    print('HOME DOUBLE BACK EXIT OK')

    # 다른 페이지를 거쳐 메뉴로 홈에 와도, 홈에서 두 번이면 나감 (그 전 페이지로 가지 않고)
    d.get('data:,')
    d.get(BASE + '/card/'); time.sleep(1.5)
    menu('ev')
    js("location.href = '/board/#post-901'"); time.sleep(2.5)
    menu('home')
    assert d.current_url == BASE + '/', d.current_url
    touch()
    d.back(); time.sleep(.8)
    assert d.current_url == BASE + '/' and toast()
    d.back(); time.sleep(3)
    assert not d.current_url.startswith(BASE), d.current_url
    print('HOME EXIT FROM DEEP OK')

    # 대시보드 카드로 연 페이지에서 뒤로 → 대시보드, 게시판 글 링크(#post-)도 뒤로 가면 돌아옴
    d.get(BASE + '/'); time.sleep(1.5)
    js("document.querySelector('#card-ev .card-head').click()"); time.sleep(2)
    assert d.current_url == BASE + '/ev/'
    d.back(); time.sleep(1.5)
    assert d.current_url == BASE + '/', d.current_url
    menu('board')
    js("location.hash = 'post-901'"); time.sleep(2)
    d.back(); time.sleep(1.2)
    assert d.current_url.startswith(BASE + '/board/'), d.current_url
    d.back(); time.sleep(1.5)
    assert d.current_url == BASE + '/' and not toast(), d.current_url
    print('BACK OK')
finally:
    d.quit()
    srv.shutdown()
