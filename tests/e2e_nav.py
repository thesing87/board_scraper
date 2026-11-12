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
    # 모든 페이지가 같은 모양: 넓은 화면은 버튼 줄, 휴대폰은 아이콘 줄. 어느 페이지든 제목 줄 바로 아래 한 줄
    for width in (1280, 390):
        d.set_window_size(width, 900); time.sleep(.3)
        shapes = set()
        for path, key in PAGES.items():
            d.get(BASE + path); time.sleep(1.2)
            assert js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)") == KEYS, path
            assert js("return document.querySelector('.site-nav [aria-current=page]').dataset.nav") == key, path
            assert js("return document.documentElement.scrollWidth <= innerWidth"), (path, width)
            compact = js("return document.querySelector('.site-nav').classList.contains('is-compact')")
            assert compact == (width < 820), (path, width)
            tops = js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => Math.round(a.getBoundingClientRect().top))")
            assert len(set(tops)) == 1, (path, width, tops)
            # 버튼 크기·글자도 페이지마다 같아야 함
            shapes.add(js("const a=document.querySelector('.site-nav [data-nav=card]'), r=a.getBoundingClientRect(), s=getComputedStyle(a);"
                          " return [Math.round(r.height), s.fontSize, s.borderRadius, a.closest('.is-compact') ? 0 : Math.round(r.width)].join('|')"))
            names = js("return [...document.querySelectorAll('.site-nav-short')].filter(e => e.offsetWidth > 0).length")
            assert names == (7 if compact else 0), (path, names)
        assert len(shapes) == 1, (width, shapes)
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

    # 게시판: 인기글은 같은 페이지라도 인기글 보기로 다시 엶
    d.get(BASE + '/board/'); time.sleep(2)
    js("document.querySelector('.site-nav [data-nav=popular]').click()"); time.sleep(2.5)
    assert js("return app.filter") == 'popular', js("return app.filter")
    # 휴대폰 게시판: 아래로 내리면 메뉴 줄도 상단 바와 함께 숨고, 올리면 다시 보임
    d.set_window_size(390, 844)
    d.get(BASE + '/board/'); time.sleep(2)
    bar = "document.querySelector('.topbar')"
    assert js(f"return {bar}.contains(document.querySelector('.site-nav'))")
    print('LINKS OK')
finally:
    d.quit()
    srv.shutdown()
