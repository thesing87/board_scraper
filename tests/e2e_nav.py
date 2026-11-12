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

# 모든 페이지 공통 바로가기 메뉴: 일곱 칸, 지금 페이지 표시, 휴대폰 아이콘 줄, 게시판의 메뉴 버튼, 인기글로 이동, 새 글 수
storage.init_db()
gid = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])[0]
storage.save_keyword_post('car', '싼타페', {'id': '801', 'title': '글', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                            'comment_count': '0', 'link': '/801', 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}, is_new=True)
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

PAGES = {'/': 'home', '/card/': 'card', '/apt/': 'apt', '/stats/': 'stats', '/ev/': 'ev', '/board/': 'board'}
KEYS = ['home', 'board', 'popular', 'apt', 'card', 'ev', 'stats']
o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    for width in (1280, 390):
        d.set_window_size(width, 900); time.sleep(.3)
        for path, key in PAGES.items():
            d.get(BASE + path); time.sleep(1.2)
            assert js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)") == KEYS, path
            assert js("return document.querySelector('.site-nav [aria-current=page]').dataset.nav") == key, path
            assert js("return document.documentElement.scrollWidth <= innerWidth"), (path, width)
            if key == 'board':
                assert js("return document.querySelector('.site-nav').classList.contains('is-menu')")
                continue
            compact = js("return document.querySelector('.site-nav').classList.contains('is-compact')")
            assert compact == (width < 820 or key == 'ev'), (path, width)
            # 일곱 칸이 모두 보이고 한 줄
            tops = js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => Math.round(a.getBoundingClientRect().top))")
            assert len(set(tops)) == 1, (path, width, tops)
            if compact:
                names = js("return [...document.querySelectorAll('.site-nav-short')].filter(e => e.offsetWidth > 0).length")
                assert names == 7, (path, names)
    print('PAGES OK')

    # 대시보드: 게시판 칸에 안 읽은 새 글 수 (위에서 게시판을 열어 읽은 글은 빠지므로 새 글을 하나 더 넣음)
    d.set_window_size(1280, 900)
    d.get(BASE + '/'); time.sleep(1.5)
    assert js("return document.querySelector('[data-badge=board]').hidden")
    storage.save_keyword_post('car', '싼타페', {'id': '802', 'title': '새 글', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                                'comment_count': '0', 'link': '/802', 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}, is_new=True)
    d.get(BASE + '/'); time.sleep(1.5)
    assert js("return document.querySelector('[data-badge=board]').textContent") == '1'
    assert not js("return document.querySelector('[data-badge=board]').hidden")
    # 대시보드에서 실거래가로
    js("document.querySelector('.site-nav [data-nav=apt]').click()"); time.sleep(1)
    assert d.current_url == BASE + '/apt/'

    # 게시판: 메뉴 버튼으로 펼치고, 바깥을 누르면 닫힘. 인기글은 같은 페이지라도 인기글 보기로 다시 엶
    d.get(BASE + '/board/'); time.sleep(2)
    panel = "document.querySelector('.site-nav-panel')"
    assert js(f"return {panel}.hidden")
    js("document.querySelector('.site-nav-toggle').click()")
    assert not js(f"return {panel}.hidden") and js("return document.querySelector('.site-nav-toggle').getAttribute('aria-expanded')") == 'true'
    js("document.body.click()")
    assert js(f"return {panel}.hidden")
    js("document.querySelector('.site-nav-toggle').click()")
    js("document.querySelector('.site-nav-panel [data-nav=popular]').click()"); time.sleep(2.5)
    assert js("return app.filter") == 'popular', js("return app.filter")
    print('LINKS OK')
finally:
    d.quit()
    srv.shutdown()
