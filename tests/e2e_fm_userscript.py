"""에펨코리아 화면에 붙는 FM키워드 줄 (Tampermonkey 스크립트, /fm-keywords.user.js): 설치 주소가 사이트 주소를 넣어 내려주고,
줄이 키워드 목록을 가져와 PC는 위·휴대폰은 아래에 붙으며, 지금 보는 검색을 표시하고, 누르면 연 시각을 남긴 뒤 같은 탭에서 이동.
휴대폰은 아래로 스크롤하면 줄이 숨고 위로 올리면 다시 보임. 에펨코리아에는 접속하지 않도록 로컬 페이지에서 GM_* 함수를 흉내 내어 시험"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, time, json, socket, urllib.request
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
tesla, _ = storage.save_group(None, '테슬라', [{'board': B, 'keyword': '테슬라'}],
                              fm_links=[{'board': 'car', 'keyword': '테슬라'}, {'board': 'car', 'keyword': '모델y'}])
ai, _ = storage.save_group(None, 'AI', [{'board': B, 'keyword': '클로드'}], fm_links=[{'board': '', 'keyword': 'gpt'}])
storage.save_group(None, '빈 게시판', [{'board': B, 'keyword': '볼보'}])
with storage._db() as conn, conn:
    conn.execute("UPDATE fm_links SET last_opened = '2020-01-01 00:00:00' WHERE keyword = '모델y'")

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'

# 설치 주소: 사이트 주소·접속 허용 호스트를 넣어 내려줌, 프록시가 https라고 알려 주면 https
with urllib.request.urlopen(BASE + '/fm-keywords.user.js') as r:
    script = r.read().decode('utf-8')
    assert r.headers['Content-Type'].startswith('text/javascript')
assert f"const SITE = '{BASE}';" in script and '// @connect      127.0.0.1' in script and '__SITE' not in script
# www 없이 여는 주소(fmkorea.com/car)에서도 실행, 업데이트는 같은 설치 주소에서
assert '// @match        https://fmkorea.com/*' in script and '// @match        https://*.fmkorea.com/*' in script
assert f'// @updateURL    {BASE}/fm-keywords.user.js' in script and f'// @downloadURL  {BASE}/fm-keywords.user.js' in script
req = urllib.request.Request(BASE + '/fm-keywords.user.js', headers={'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'example.synology.me'})
assert "const SITE = 'https://example.synology.me';" in urllib.request.urlopen(req).read().decode('utf-8')
data = json.load(urllib.request.urlopen(BASE + '/api/fm-links'))
assert [g['name'] for g in data['groups']] == ['테슬라', 'AI'] and data['groups'][1]['links'][0]['board_name'] == '전체', data
print('SERVE OK')

# Tampermonkey 흉내: GM_xmlhttpRequest는 fetch로, GM_getValue/SetValue는 localStorage로
SHIM = """
// 화면 없는 시험용 크롬은 마우스가 없는 기기(손가락 기기)로 잡히므로, 기기 종류는 화면 폭으로만 판단하게 바꿔 둠
const realMatch = window.matchMedia.bind(window);
window.matchMedia = q => q.includes('pointer') ? { matches: false } : realMatch(q);
window.GM_getValue = (k, d) => { const v = localStorage.getItem('gm_' + k); return v === null ? d : JSON.parse(v); };
window.GM_setValue = (k, v) => localStorage.setItem('gm_' + k, JSON.stringify(v));
window.GM_xmlhttpRequest = o => fetch(o.url, { method: o.method, headers: o.headers, body: o.data })
    .then(r => r.text().then(t => o.onload({ status: r.status, responseText: t }))).catch(e => o.onerror(e));
"""
def page(d, query, tall=False):
    # 에펨코리아 검색 화면 대신 로컬 빈 페이지 (주소의 검색 부분만 흉내)
    d.get(BASE + '/api/fm-links?' + query); time.sleep(0.5)
    d.execute_script("document.body.innerHTML = '<div id=fake style=\"height:' + (arguments[0] ? 4000 : 300) + 'px\">에펨코리아 검색 결과</div>'", tall)
    d.execute_script(SHIM + script)
    for _ in range(30):
        if d.execute_script("const h = document.getElementById('keyword-monitor-fm-bar'); return !!(h && h.shadowRoot.querySelector('.bar'))"):
            break
        time.sleep(0.2)
def bar(d, sel):
    return d.execute_script(f"return document.getElementById('keyword-monitor-fm-bar').shadowRoot.querySelector('{sel}')")
def chips(d):
    return d.execute_script("return [...document.getElementById('keyword-monitor-fm-bar').shadowRoot.querySelectorAll('a.chip')]"
                            ".map(a => [a.textContent.replace(/\\s+/g, ' ').trim(), a.classList.contains('on'), a.classList.contains('stale')])")

o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
try:
    # PC: 위에 고정, 지금 보는 검색(테슬라)이 들어 있는 게시판, 연 시각·7일 넘으면 주황
    page(d, 'mid=car&search_target=title_content&search_keyword=%ED%85%8C%EC%8A%AC%EB%9D%BC')
    assert d.execute_script("const b = arguments[0].getBoundingClientRect(); return [Math.round(b.top), getComputedStyle(arguments[0]).position]", bar(d, '.bar')) == [0, 'fixed']
    assert d.execute_script("return arguments[0].value", bar(d, 'select')) == str(tesla)
    got = chips(d)
    assert got[0][0].startswith('테슬라') and got[0][1] and not got[0][2] and got[1][0].startswith('모델y') and got[1][2], got
    assert '아직 안 봄' in got[0][0] and float(d.execute_script("return document.documentElement.style.paddingTop")[:-2]) > 20
    # 게시판 바꾸기 (기억)
    d.execute_script("const s = arguments[0]; s.value = arguments[1]; s.dispatchEvent(new Event('change', {bubbles: true}))", bar(d, 'select'), str(ai))
    time.sleep(0.3)
    got = (chips(d), d.execute_script("return localStorage.getItem('gm_fm_bar_group')"))
    assert len(got[0]) == 1 and got[0][0][0].startswith('gpt') and got[1] == str(ai), got
    # 누르면 연 시각을 남기고 같은 탭에서 이동 (시험에서는 이동할 주소를 로컬로 바꿔 에펨코리아에 접속하지 않음)
    d.execute_script("const a = arguments[0]; a.href = location.origin + '/api/fm-links?moved=1'; a.click()", bar(d, 'a.chip'))
    time.sleep(1.5)
    assert 'moved=1' in d.current_url, d.current_url
    assert [l for g in storage.list_groups() if g['id'] == ai for l in g['fm_links']][0]['last_opened']
    # 접기·펴기 (기억)
    page(d, 'mid=car&search_keyword=x')
    d.execute_script("arguments[0].click()", bar(d, '[data-fold]')); time.sleep(0.2)
    assert bar(d, '.mini') and d.execute_script("return arguments[0].textContent", bar(d, '.mini')).startswith('FM키워드')
    page(d, 'mid=car&search_keyword=x')
    assert bar(d, '.mini')
    d.execute_script("arguments[0].click()", bar(d, '[data-unfold]')); time.sleep(0.2)
    assert bar(d, 'a.chip')
    print('PC OK')

    # 휴대폰: 아래에 고정, 연 시각은 줄여서 안 보임, 아래로 스크롤하면 숨고 위로 올리면 보임
    d.set_window_size(390, 844); time.sleep(0.3)
    page(d, 'mid=car&search_keyword=%EB%AA%A8%EB%8D%B8y', tall=True)
    rect = d.execute_script("const r = arguments[0].getBoundingClientRect(); return [Math.round(innerHeight - r.bottom), Math.round(r.height)]", bar(d, '.bar'))
    assert rect[0] == 0 and rect[1] > 40, rect
    got = chips(d)
    assert [c[0] for c in got] == ['테슬라', '모델y'] and got[1][1], got
    gone = lambda: d.execute_script("return arguments[0].classList.contains('gone')", bar(d, '.bar'))
    d.execute_script("window.scrollTo(0, 600)"); time.sleep(0.4)
    assert gone()
    d.execute_script("window.scrollTo(0, 595)"); time.sleep(0.4)      # 10px 안의 떨림은 그대로
    assert gone()
    d.execute_script("window.scrollTo(0, 400)"); time.sleep(0.4)
    assert not gone()
    d.execute_script("window.scrollTo(0, 1200)"); time.sleep(0.4)
    assert gone()
    d.execute_script("window.scrollTo(0, document.documentElement.scrollHeight)"); time.sleep(0.4)
    assert not gone()                                                   # 맨 아래에 닿으면 보임
    assert d.execute_script("return document.documentElement.scrollWidth <= innerWidth")
    print('MOBILE OK')

    # 키워드 모니터 FM키워드 화면의 설치 안내
    d.set_window_size(1280, 900)
    d.get(BASE + '/board/#fm'); time.sleep(2)
    d.execute_script("document.querySelector('.fmk-install summary').click()"); time.sleep(0.2)
    assert d.execute_script("return document.querySelector('.fmk-install a').getAttribute('href')") == '/fm-keywords.user.js'
    print('INSTALL GUIDE OK')
finally:
    d.quit()
    srv.shutdown()
print('FM USERSCRIPT OK')
