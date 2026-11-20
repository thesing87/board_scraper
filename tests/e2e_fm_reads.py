"""FM키워드 줄 1.4.2 읽음 기록: 읽은 글이 다시 새 글로 돌아가지 않게.
1) 검색 결과에서 연 글 화면(주소에 검색어가 붙어 있음)도 주소의 글 번호로 읽음.
2) 서버에 못 보낸 읽음은 Tampermonkey 저장소에 남겨 두었다가 다음 화면에서 다시 보내고, 받은 목록에도 반영 ('새 N'이 되살아나지 않음).
3) 뒤로 가기로 되살아난 화면(pageshow persisted)도 다른 화면에서 바뀐 목록으로 다시 그림.
에펨코리아에는 접속하지 않도록 로컬 페이지에서 GM_* 함수를 흉내 내어 시험"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, time, json, socket, urllib.request, urllib.parse
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
car, _ = storage.save_group(None, '자동차', [{'board': B, 'keyword': '차'}],
                            fm_links=[{'board': 'car', 'keyword': '투싼'}, {'board': 'car', 'keyword': '쏘렌토'}])
BASE_NO = 9000000000
storage.fm_seen_init('car', '투싼', BASE_NO)
storage.fm_seen_found('car', '투싼', [BASE_NO + 1, BASE_NO + 2, BASE_NO + 3])

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'
with urllib.request.urlopen(BASE + '/fm-keywords.user.js') as r:
    script = r.read().decode('utf-8')
assert '// @version      1.7.0' in script

SHIM = """
const realMatch = window.matchMedia.bind(window);
window.matchMedia = q => q.includes('pointer') ? { matches: false } : realMatch(q);
window.GM_getValue = (k, d) => { const v = localStorage.getItem('gm_' + k); return v === null ? d : JSON.parse(v); };
window.GM_setValue = (k, v) => localStorage.setItem('gm_' + k, JSON.stringify(v));
window.GM_xmlhttpRequest = o => fetch(o.url, { method: o.method, headers: o.headers, body: o.data, keepalive: true })
    .then(r => r.text().then(t => o.onload({ status: r.status, responseText: t }))).catch(e => o.onerror(e));
"""
def read_ids():
    with storage._db() as conn:
        return json.loads(conn.execute("SELECT read_ids FROM fm_seen WHERE board = 'car' AND keyword = '투싼'").fetchone()[0])

o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
d.execute_cdp_cmd('Network.enable', {})
d.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*fmkorea.com*']})
js = d.execute_script
R = "document.getElementById('keyword-monitor-fm-bar').shadowRoot"
def page(query, before=''):
    for _ in range(3):
        d.get(BASE + '/api/fm-links?' + query); time.sleep(0.5)
        if d.current_url.startswith(BASE):
            break
    js("document.body.innerHTML = '<div style=\"height:300px\">에펨코리아 화면</div>'")
    js(SHIM + before + script)
    for _ in range(30):
        if js("const h = document.getElementById('keyword-monitor-fm-bar'); return !!(h && h.shadowRoot.querySelector('.bar'))"):
            break
        time.sleep(0.2)
    time.sleep(0.8)
def badge():
    # 자동차 묶음을 펼친 줄에서 투싼 칩의 '새 N'
    js(f"if (!{R}.querySelector('a.chip[data-keyword=\"투싼\"]')) {R}.querySelector('[data-toggle=\"{car}\"]').click()")
    return js(f"const b = {R}.querySelector('a.chip[data-keyword=\"투싼\"] .newb'); return b ? b.textContent : ''")
try:
    page('mid=car')
    assert badge() == '새 3', badge()
    # 1) 검색 결과에서 연 글 화면: 주소에 검색어가 붙어 있어도 읽음
    page(f'mid=car&search_target=title_content&search_keyword={urllib.parse.quote("투싼")}&document_srl={BASE_NO + 1}')
    assert BASE_NO + 1 in read_ids(), read_ids()
    page('mid=car')
    assert badge() == '새 2', badge()
    # 2) 서버에 못 보낸 읽음: 남겨 두고, 받은 목록에도 반영, 다음 화면에서 다시 보냄
    d.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*fmkorea.com*', '*/api/fm-link']})
    page('x=1', before=f"history.replaceState(null, '', '/{BASE_NO + 2}');")   # 글 화면 (짧은 주소) 흉내
    assert BASE_NO + 2 not in read_ids()
    assert js("return JSON.parse(localStorage.getItem('gm_fm_bar_pending_reads'))") == [BASE_NO + 2]
    page('mid=car')   # 아직 서버에 못 닿았어도 받은 목록에 반영
    assert badge() == '새 1', badge()
    d.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*fmkorea.com*']})
    page('mid=car')   # 다시 보냄
    assert BASE_NO + 2 in read_ids(), read_ids()
    assert js("return JSON.parse(localStorage.getItem('gm_fm_bar_pending_reads'))") == []
    assert badge() == '새 1', badge()
    # 3) 뒤로 가기로 되살아난 화면: 다른 화면에서 읽은 글을 반영해 다시 그림
    storage.fm_seen_read(BASE_NO + 3)
    js("const c = JSON.parse(JSON.parse(localStorage.getItem('gm_fm_bar_cache'))); c.forEach(g => g.links.forEach(l => { if (l.keyword === '투싼') (l.read_ids = l.read_ids || []).push(%d); }));"
       "localStorage.setItem('gm_fm_bar_cache', JSON.stringify(JSON.stringify(c)))" % (BASE_NO + 3))
    js("window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))"); time.sleep(1)
    assert badge() == '', badge()
    severe = [m['message'][:200] for m in d.get_log('browser') if m['level'] == 'SEVERE' and 'fm-link' not in m['message'] and 'fmkorea' not in m['message'] and 'favicon' not in m['message']]
    assert not severe, severe
finally:
    d.quit()
print('ALL OK')
