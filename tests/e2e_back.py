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

# 휴대폰: 페이지를 옮겨도 뒤로 가기 기록이 쌓이지 않고, 뒤로 가기 두 번(2초 안)이면 앱(사이트)에서 나감. 넓은 화면은 보통 브라우저처럼
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
for a in ['--headless=new', '--window-size=390,844']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
toast = lambda: js("const t=document.querySelector('.nav-exit-toast'); return !!t && t.classList.contains('is-shown')")
def menu(key):
    js(f"document.querySelector('.site-nav [data-nav={key}]').click()"); time.sleep(2)
try:
    d.get('data:,')
    d.get(BASE + '/'); time.sleep(1.5)
    start = js("return history.length")
    # 메뉴로 여러 페이지를 옮겨도 기록 수는 그대로
    for key, path in [('card', '/card/'), ('ev', '/ev/'), ('board', '/board/'), ('apt', '/apt/'), ('stats', '/stats/')]:
        menu(key)
        assert d.current_url.startswith(BASE + path), (key, d.current_url)
        assert js("return history.length") == start, (key, js("return history.length"), start)
    # 대시보드 카드 링크로 옮겨도 마찬가지
    menu('home')
    js("document.querySelector('#card-ev .card-head').click()"); time.sleep(2)
    assert d.current_url == BASE + '/ev/' and js("return history.length") == start
    print('NO STACK OK')

    # 뒤로 1번: 이전 페이지(대시보드)로 가지 않고 안내만
    d.back(); time.sleep(.8)
    assert d.current_url == BASE + '/ev/' and toast()
    # 2초가 지나면 다시 처음부터 (한 번 더 눌러도 안내만)
    time.sleep(2.5)
    assert not toast()
    d.back(); time.sleep(.8)
    assert d.current_url == BASE + '/ev/' and toast()
    # 2초 안에 한 번 더: 사이트에서 나감 (앱이면 종료)
    d.back(); time.sleep(1.5)
    assert not d.current_url.startswith(BASE), d.current_url
    print('DOUBLE BACK EXIT OK')

    # 게시판 안의 글 링크(#post-)는 지금처럼 뒤로 가기로 돌아옴 (안내·종료 없음)
    d.get(BASE + '/board/'); time.sleep(2)
    js("location.hash = 'post-901'"); time.sleep(2)
    d.back(); time.sleep(1)
    assert d.current_url.startswith(BASE + '/board/') and not toast(), d.current_url
    # 그다음 뒤로 두 번이면 나감
    d.back(); time.sleep(.6)
    assert toast()
    d.back(); time.sleep(1.5)
    assert not d.current_url.startswith(BASE + '/board/'), d.current_url
    # 새로고침해도 칸이 늘지 않음
    d.get(BASE + '/stats/'); time.sleep(1.2)
    n = js("return history.length")
    d.refresh(); time.sleep(1.2)
    d.refresh(); time.sleep(1.2)
    assert js("return history.length") == n
    d.back(); time.sleep(.6)
    assert d.current_url == BASE + '/stats/' and toast()
    print('BOARD AND RELOAD OK')

    # 넓은 화면: 보통 브라우저처럼 뒤로 가면 이전 페이지
    d.set_window_size(1280, 900)
    d.get(BASE + '/'); time.sleep(1.5)
    menu('card')
    d.back(); time.sleep(1.5)
    assert d.current_url == BASE + '/', d.current_url
    print('DESKTOP OK')
finally:
    d.quit()
    srv.shutdown()
