import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket, sqlite3
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, config
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# 본문이 긴 새 글 3개
storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
for pid in ('801', '802', '803'):
    storage.save_keyword_post('car', '싼타페', {'id': pid, 'title': f'글 {pid}', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                                'comment_count': '1', 'link': f'/{pid}', 'content': ['<p>본문</p>'] * 80, 'videos': [],
                                                'comments': [{'author': 'u', 'date': 'd', 'content': ['댓글'], 'votes': '0', 'is_reply': False}]},
                              is_new=True)
# 다른 게시판(캐스퍼)의 글 하나: 접기 상태는 게시판마다 따로
storage.save_group(None, '캐스퍼', [{'board': 'car', 'keyword': '캐스퍼'}])
storage.save_keyword_post('car', '캐스퍼', {'id': '804', 'title': '글 804', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                            'comment_count': '0', 'link': '/804', 'content': ['<p>본문</p>'], 'videos': [], 'comments': []},
                          is_new=True)
db = sqlite3.connect(config.DB_FILE)
read_ids = lambda: {r[0] for r in db.execute('SELECT post_id FROM read_posts')}

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
for a in ['--headless=new', '--window-size=1440,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
key = lambda k: js("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: arguments[0], bubbles: true}))", k)
try:
    d.get(f'http://127.0.0.1:{port}/'); time.sleep(2.5)
    # 1) G: 전부 접기 → 글마다 제목 줄만, 버튼 이름이 바뀌고 기기에 기억
    key('g'); time.sleep(0.5)
    assert js("return document.getElementById('feed').classList.contains('is-folded')")
    assert js("return getComputedStyle(document.querySelector('.post-card .post-content')).display") == 'none'
    assert js("return getComputedStyle(document.querySelector('.post-card .comments')).display") == 'none'
    assert '전부 펼치기' in js("return document.querySelector('[data-action=toggle-fold]').textContent")
    assert js("return JSON.parse(localStorage.getItem('posts_folded_by_view'))") == {'__all__': True}
    # 2) 접힌 글은 화면을 지나가도 읽음 아님 (접기 전 첫 화면에서 읽힌 짧은 글 기록은 지우고 봄)
    db.execute('DELETE FROM read_posts'); db.commit()
    js("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(2.5)
    assert read_ids() == set(), read_ids()
    # 3) 제목 줄을 누르면 그 글만 펼침 → 끝까지 보면 그 글만 읽음
    js("window.scrollTo(0, 0); document.querySelector('#post-802 .post-title').click()"); time.sleep(0.3)
    assert js("return [...document.querySelectorAll('.post-card.is-open')].map(c => c.id)") == ['post-802']
    js("window.scrollTo(0, document.querySelector('#post-802 .read-sentinel').getBoundingClientRect().top + scrollY - 200)"); time.sleep(2.5)
    assert read_ids() == {'802'}, read_ids()
    # 4) 새로고침해도 접힌 상태, G로 다시 전부 펼침
    d.refresh(); time.sleep(2.5)
    assert js("return document.getElementById('feed').classList.contains('is-folded')")
    key('G'); time.sleep(0.5)
    assert not js("return document.getElementById('feed').classList.contains('is-folded')")
    print('FOLD OK')

    # 4-1) 게시판마다 따로: 싼타페만 접어 두면 캐스퍼·전체는 펼친 채, 다시 싼타페로 오면 접힌 채
    open_board = lambda name: js("openBoard('group:' + app.state.groups.find(g => g.name === arguments[0]).id)", name)
    folded = lambda: js("return document.getElementById('feed').classList.contains('is-folded')")
    open_board('싼타페'); time.sleep(1.5)
    js("app.filter = 'all'; openView(app.activeKey, 1)"); time.sleep(1.5)
    assert not folded()
    key('g'); time.sleep(0.5)
    assert folded()
    open_board('캐스퍼'); time.sleep(1.5)
    assert not folded()
    js("openBoard(ALL_KEY)"); time.sleep(1.5)
    assert not folded()
    open_board('싼타페'); time.sleep(1.5)
    assert folded()
    d.refresh(); time.sleep(2.5)   # 새로고침하면 보던 게시판(싼타페)으로, 접힌 채
    assert folded()
    key('g'); time.sleep(0.5)
    js("openBoard(ALL_KEY)"); time.sleep(1.5)
    print('FOLD PER BOARD OK')

    # 5) F: 다음 글, 단축키 안내는 지금 화면에서 쓰는 키만 진하게, 접어 두면 기억
    js("window.scrollTo(0, 0)"); time.sleep(0.3)
    key('f'); time.sleep(1.5)
    assert js("return Math.abs(document.querySelector('#feed .post-card:nth-of-type(2)').getBoundingClientRect().top - document.querySelector('.topbar').offsetHeight)") < 40
    off = js("return [...document.querySelectorAll('#shortcut-guide li')].map(l => l.classList.contains('is-off'))")
    assert off == [False, False, True, True, True, True], off
    js("setFilter('image')"); time.sleep(1.5)
    off = js("return [...document.querySelectorAll('#shortcut-guide li')].map(l => l.classList.contains('is-off'))")
    assert off == [True, True, False, True, True, True], off
    js("document.querySelector('.keys-toggle').click()")
    d.refresh(); time.sleep(2.5)
    assert js("return document.getElementById('shortcut-guide').classList.contains('is-closed')")
    print('SHORTCUTS OK')
finally:
    d.quit()
    srv.shutdown()
