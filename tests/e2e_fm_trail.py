"""FM키워드 줄 1.5.0 검색 결과 이전·다음 글: 검색 결과 화면의 목록을 순서대로 기억하고, 그 목록의 글 화면에서
◀ 이전 · n/전체 · 다음 ▶ · 새 글 ▶▶ · 목록. 마지막 글에서는 다음 쪽 검색 결과로, PC 단축키 j·k·n·u.
에펨코리아에는 접속하지 않도록 로컬 페이지에서 GM_* 함수를 흉내 내어 시험"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, time, socket, urllib.request, urllib.parse
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
B = 'dc:car_new1'
storage.add_category(B)
storage.set_category_checked(B, True, page_name='자동차 갤러리')
storage.save_group(None, '자동차', [{'board': B, 'keyword': '차'}], fm_links=[{'board': 'car', 'keyword': '투싼'}])
NO = 9000000000
# 기준 NO: NO+1·NO+3은 새 글, NO-1은 예전 글
storage.fm_seen_init('car', '투싼', NO)

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'
with urllib.request.urlopen(BASE + '/fm-keywords.user.js') as r:
    script = r.read().decode('utf-8')
assert '// @version      1.9.0' in script

SHIM = """
const realMatch = window.matchMedia.bind(window);
window.matchMedia = q => q.includes('pointer') ? { matches: false } : realMatch(q);
window.GM_getValue = (k, d) => { const v = localStorage.getItem('gm_' + k); return v === null ? d : JSON.parse(v); };
window.GM_setValue = (k, v) => localStorage.setItem('gm_' + k, JSON.stringify(v));
window.GM_xmlhttpRequest = o => fetch(o.url, { method: o.method, headers: o.headers, body: o.data, keepalive: true })
    .then(r => r.text().then(t => o.onload({ status: r.status, responseText: t }))).catch(e => o.onerror(e));
"""
KW = urllib.parse.quote('투싼')
SEARCH = f'mid=car&search_target=title_content&search_keyword={KW}'
POSTS = [NO + 3, NO + 1, NO - 1]           # 검색 결과 순서 (최신 글이 위)
post_q = lambda no: f'mid=car&search_target=title_content&search_keyword={KW}&document_srl={no}'
ROWS = ''.join(f'<tr><td class="title"><a class="hx" href="/api/fm-links?{post_q(no)}">글 {no - NO}</a></td></tr>' for no in POSTS)

o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
d.execute_cdp_cmd('Network.enable', {})
d.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*fmkorea.com*']})
js = d.execute_script
R = "document.getElementById('keyword-monitor-fm-bar').shadowRoot"


def inject(body):
    js("document.body.innerHTML = arguments[0]", body)
    js(SHIM + script)
    for _ in range(30):
        if js("const h = document.getElementById('keyword-monitor-fm-bar'); return !!(h && h.shadowRoot.querySelector('.bar'))"):
            break
        time.sleep(0.2)
    time.sleep(0.8)


def page(query, body='<div style="height:300px">에펨코리아 글</div>'):
    for _ in range(3):
        d.get(BASE + '/api/fm-links?' + query); time.sleep(0.4)
        if d.current_url.startswith(BASE):
            break
    inject(body)


def wait_url(part):
    for _ in range(30):
        if part in urllib.parse.unquote(d.current_url):
            return True
        time.sleep(0.2)
    return False


pnav = lambda: js(f"const p = {R}.querySelector('.pnav'); return p ? p.textContent.replace(/\\s+/g, ' ').trim() : ''")
try:
    # 검색 결과 화면: 목록을 기억, 이 화면에는 이전·다음 줄이 없음
    page(SEARCH, f'<table class="bd_lst"><tbody>{ROWS}</tbody></table>')
    trail = js("return JSON.parse(localStorage.getItem('gm_fm_bar_trail'))")
    assert trail['keyword'] == '투싼' and trail['board'] == 'car' and [p['no'] for p in trail['posts']] == POSTS, trail
    assert trail['posts'][0]['title'].endswith('글 3') and pnav() == ''
    # 첫 글: 이전 없음, 1/3, 다음 ▶, 다음 새 글(NO+1), 목록
    page(post_q(NO + 3))
    assert pnav().startswith('◀ 이전 1/3 · 투싼 다음 ▶ 새 글 ▶▶ 목록'), pnav()
    assert js(f"return {R}.querySelector('[data-pnav=prev]').disabled")
    # 새 글 ▶▶ → 아직 안 읽은 새 글(NO+1)로
    js(f"{R}.querySelector('[data-pnav=new]').click()")
    assert wait_url(f'document_srl={NO + 1}'), d.current_url
    inject('<div>글</div>')
    assert pnav().startswith('◀ 이전 2/3'), pnav()
    assert '새 글' not in pnav()                     # 새 글은 둘 다 읽음 (NO+3은 열었고 NO+1은 지금)
    # 단축키 j → 다음 글, k → 이전 글
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'j', bubbles: true}))")
    assert wait_url(f'document_srl={NO - 1}'), d.current_url
    inject('<div>글</div>')
    # 마지막 글: '다음 쪽 ▶'은 다음 쪽 검색 결과로
    assert '3/3' in pnav() and '다음 쪽 ▶' in pnav(), pnav()
    js(f"{R}.querySelector('[data-pnav=nextpage]').click()")
    assert wait_url('page=2') and 'document_srl' not in d.current_url, d.current_url
    # 목록: 그 글을 연 검색 결과로
    page(post_q(NO + 1))
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', bubbles: true}))")
    assert wait_url(f'document_srl={NO + 3}'), d.current_url
    inject('<div>글</div>')
    js(f"{R}.querySelector('[data-pnav=list]').click()")
    assert wait_url(SEARCH.split('&')[-1].replace(KW, '투싼')) and 'document_srl' not in d.current_url, d.current_url
    # 글을 쓰는 중에는 단축키를 쓰지 않음
    page(post_q(NO + 1), '<textarea id="t"></textarea>')
    js("const t = document.getElementById('t'); t.focus(); t.dispatchEvent(new KeyboardEvent('keydown', {key: 'j', bubbles: true}))")
    time.sleep(1)
    assert f'document_srl={NO + 1}' in d.current_url
    # 목록에 없는 글은 이전·다음 줄 없음
    page(post_q(NO + 99))
    assert pnav() == ''
    print('TRAIL PC OK')

    # 휴대폰: 아랫줄에 ◀ n/전체 ▶ (짧게)
    d.set_window_size(390, 844); time.sleep(.3)
    page(post_q(NO + 1))
    assert js(f"return !!{R}.querySelector('.bar.bottom .pnav')") and pnav().startswith('◀ 2/3 다음 ▶'), pnav()
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('TRAIL MOBILE OK')
finally:
    d.quit()
    srv.shutdown()
