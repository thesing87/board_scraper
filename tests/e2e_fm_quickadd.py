"""FM키워드 줄에서 바로 추가 (Tampermonkey 스크립트 1.4.0): 목록에 없는 검색을 직접 보고 있으면 '+ 추가' 단추,
누르면 넣을 카드를 고름(이 게시판을 가장 많이 쓰는 카드가 맨 위). 처음 한 번만 관리자 비밀번호를 물어 Tampermonkey 저장소에 둠,
틀리면 지우고 다시 물음. 이미 목록에 있는 검색이면 단추 없음. 에펨코리아에는 접속하지 않도록 로컬 페이지에서 GM_* 함수를 흉내 내어 시험"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, time, socket, urllib.request
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
ai, _ = storage.save_group(None, 'AI', [{'board': B, 'keyword': '클로드'}], fm_links=[{'board': '', 'keyword': 'gpt'}])
car, _ = storage.save_group(None, '자동차', [{'board': B, 'keyword': '차'}],
                            fm_links=[{'board': 'car', 'keyword': '투싼'}, {'board': 'car', 'keyword': '쏘렌토'}])

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'
with urllib.request.urlopen(BASE + '/fm-keywords.user.js') as r:
    script = r.read().decode('utf-8')
assert '// @version      1.5.0' in script

SHIM = """
const realMatch = window.matchMedia.bind(window);
window.matchMedia = q => q.includes('pointer') ? { matches: false } : realMatch(q);
window.GM_getValue = (k, d) => { const v = localStorage.getItem('gm_' + k); return v === null ? d : JSON.parse(v); };
window.GM_setValue = (k, v) => localStorage.setItem('gm_' + k, JSON.stringify(v));
window.GM_xmlhttpRequest = o => fetch(o.url, { method: o.method, headers: o.headers, body: o.data, keepalive: true })
    .then(r => r.text().then(t => o.onload({ status: r.status, responseText: t }))).catch(e => o.onerror(e));
"""
def kws(gid):
    return [l['keyword'] for l in next(g for g in storage.list_groups() if g['id'] == gid)['fm_links']]

def run(mobile):
    o = Options()
    for a in ['--headless=new', '--window-size=' + ('400,860' if mobile else '1280,900')]:
        o.add_argument(a)
    d = Chrome(options=o)
    d.execute_cdp_cmd('Network.enable', {})
    d.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*fmkorea.com*']})
    js = d.execute_script
    R = "document.getElementById('keyword-monitor-fm-bar').shadowRoot"
    def page(query):
        for _ in range(3):
            d.get(BASE + '/api/fm-links?' + query); time.sleep(0.5)
            if d.current_url.startswith(BASE):
                break
        js("document.body.innerHTML = '<div style=\"height:300px\">에펨코리아 검색 결과</div>'")
        js(SHIM + script)
        for _ in range(30):
            if js(f"const h = document.getElementById('keyword-monitor-fm-bar'); return !!(h && h.shadowRoot.querySelector('.bar'))"):
                break
            time.sleep(0.2)
        time.sleep(0.8)
    def q(sel):
        return js(f"return {R}.querySelector('{sel}')")
    def click(sel):
        js(f"{R}.querySelector('{sel}').click()"); time.sleep(1)
    try:
        # 이미 목록에 있는 검색: 단추 없음
        page('mid=car&search_keyword=' + urllib.parse.quote('투싼'))
        assert not q('[data-add]')
        # 목록에 없는 검색: 단추 → 고르기 (자동차 게시판을 쓰는 '자동차' 카드가 맨 위)
        page('mid=car&search_keyword=' + urllib.parse.quote('캐스퍼'))
        assert q('[data-add]'), js(f"return {R}.innerHTML")
        label = js(f"return {R}.querySelector('[data-add]').textContent")
        assert label == ('+ 추가' if mobile else "+ '캐스퍼' 추가"), label
        click('[data-add]')
        names = js(f"return [...{R}.querySelectorAll('[data-addto]')].map(b => [b.textContent.trim(), b.classList.contains('best')])")
        assert names[0][0].startswith('자동차') and names[0][1] and names[1] == ['AI', False], names
        assert q('[data-addpwd]')
        # 비밀번호 없이 → 안내, 틀리면 → 안내하고 저장하지 않음
        click('[data-addto]')
        assert '비밀번호를 넣어' in js(f"return {R}.querySelector('.err').textContent")
        pwd = js(f"return {R}.querySelector('[data-addpwd]')")
        pwd.send_keys('wrong]')   # 입력 칸의 ]는 '다음' 단축키가 아님
        time.sleep(0.3)
        assert d.current_url.startswith(BASE + '/api/fm-links?mid=car'), d.current_url
        click('[data-addto]')
        assert '맞지 않습니다' in js(f"return {R}.querySelector('.err').textContent")
        assert kws(car) == ['투싼', '쏘렌토'] and not js("return JSON.parse(localStorage.getItem('gm_fm_admin_password') || '\"\"')")
        pwd = js(f"return {R}.querySelector('[data-addpwd]')")
        pwd.clear(); pwd.send_keys('Secr3t!')
        click('[data-addto]')
        assert kws(car) == ['투싼', '쏘렌토', '캐스퍼'], kws(car)
        assert not q('[data-add]') and not q('.picker')
        on = js(f"return [...{R}.querySelectorAll('a.chip.on')].map(a => a.dataset.keyword)")
        assert on == ['캐스퍼'], on
        assert next(l for l in storage.list_groups() if l['id'] == car)['fm_links'][-1]['last_opened']
        assert js("return JSON.parse(localStorage.getItem('gm_fm_admin_password'))") == 'Secr3t!'
        # 다음부터는 비밀번호를 묻지 않음 · 전체 검색도 추가
        page('act=IS&is_keyword=' + urllib.parse.quote('클로드'))
        click('[data-add]')
        assert not q('[data-addpwd]')
        js(f"[...{R}.querySelectorAll('[data-addto]')].find(b => b.textContent.trim().startsWith('AI')).click()"); time.sleep(1)
        assert kws(ai) == ['gpt', '클로드'], kws(ai)
        # 닫기
        page('mid=car&search_keyword=' + urllib.parse.quote('아이오닉'))
        click('[data-add]'); assert q('.picker')
        click('[data-addclose]'); assert not q('.picker')
        if not mobile:
            # 키워드를 누르면 서버 답을 기다리지 않고 바로 넘어감. 기록이 끊겨도(서버에 못 닿음) 다음 화면에서 다시 보냄
            with storage._db() as conn, conn:
                conn.execute("UPDATE fm_links SET last_opened = NULL WHERE keyword = '쏘렌토'")
            page('mid=car&search_keyword=' + urllib.parse.quote('아이오닉'))
            d.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*fmkorea.com*', '*/api/fm-link']})
            js(f"{R}.querySelector('a.chip[data-keyword=\"쏘렌토\"]') || {R}.querySelector('[data-toggle=\"{car}\"]').click()")
            # 누른 때와 화면을 떠나기 시작한 때를 이 페이지의 저장소에 남김
            js("window.addEventListener('beforeunload', () => localStorage.setItem('t_leave', Date.now()));"
               f"localStorage.setItem('t_click', Date.now()); setTimeout(() => {R}.querySelector('a.chip[data-keyword=\"쏘렌토\"]').click(), 0)")
            time.sleep(2)
            assert 'search_keyword' in d.current_url, d.current_url
            d.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*fmkorea.com*']})
            assert not next(g for g in storage.list_groups() if g['id'] == car)['fm_links'][1]['last_opened']
            page('mid=car&search_keyword=' + urllib.parse.quote('아이오닉'))
            time.sleep(0.5)
            assert next(g for g in storage.list_groups() if g['id'] == car)['fm_links'][1]['last_opened']
            assert js("return JSON.parse(localStorage.getItem('gm_fm_bar_pending_opens'))") == []
            waited = js("return localStorage.getItem('t_leave') - localStorage.getItem('t_click')")
            assert 0 <= waited < 150, waited
            # 받은 목록이 예전 시각이어도 '방금 전'
            assert '방금 전' in js(f"return {R}.querySelector('a.chip[data-keyword=\"쏘렌토\"]').textContent")
    finally:
        d.quit()
    # 다음 실행을 위해 처음으로
    storage.remove_fm_link(car, 'car', '캐스퍼'); storage.remove_fm_link(ai, '', '클로드')

import urllib.parse
run(False)
print('PC QUICK ADD OK')
run(True)
print('MOBILE QUICK ADD OK')
print('ALL OK')
