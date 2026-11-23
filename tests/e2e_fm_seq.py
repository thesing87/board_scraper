"""FM키워드 줄 1.6.0 전체 키워드 차례대로: 줄의 ‹ n/전체 › 단추와 PC 단축키 . , 로 카드 순서 → 카드 안 순서대로 다음·이전 키워드,
끝에서는 처음으로(처음에서는 끝으로). 지금 보는 검색이 목록에 없으면 다음은 첫 키워드, 이전은 마지막. 누른 시각도 기록.
에펨코리아에는 접속하지 않도록 로컬 페이지에서 GM_* 함수를 흉내 내어 시험 (넘어가는 주소만 확인)"""
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
# 카드 순서: 자동차(투싼·쏘렌토) → AI(gpt 전체 검색)
car, _ = storage.save_group(None, '자동차', [{'board': B, 'keyword': '차'}],
                            fm_links=[{'board': 'car', 'keyword': '투싼'}, {'board': 'car', 'keyword': '쏘렌토'}])
ai, _ = storage.save_group(None, 'AI', [{'board': B, 'keyword': '인공지능'}], fm_links=[{'board': '', 'keyword': 'gpt'}])

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'
with urllib.request.urlopen(BASE + '/fm-keywords.user.js') as r:
    script = r.read().decode('utf-8')
assert '// @version      1.8.0' in script
order = [(l['board'], l['keyword']) for g in web_server.json.loads(urllib.request.urlopen(BASE + '/api/fm-links').read())['groups'] for l in g['links']]
assert len(order) == 3, order

SHIM = """
const realMatch = window.matchMedia.bind(window);
window.matchMedia = q => q.includes('pointer') ? { matches: false } : realMatch(q);
window.GM_getValue = (k, d) => { const v = localStorage.getItem('gm_' + k); return v === null ? d : JSON.parse(v); };
window.GM_setValue = (k, v) => localStorage.setItem('gm_' + k, JSON.stringify(v));
window.GM_xmlhttpRequest = o => fetch(o.url, { method: o.method, headers: o.headers, body: o.data, keepalive: true })
    .then(r => r.text().then(t => o.onload({ status: r.status, responseText: t }))).catch(e => o.onerror(e));
"""
o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
d.execute_cdp_cmd('Network.enable', {})
d.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['*fmkorea.com*']})
js = d.execute_script
R = "document.getElementById('keyword-monitor-fm-bar').shadowRoot"


def page(query):
    for _ in range(3):
        d.get(BASE + '/api/fm-links?' + query); time.sleep(0.4)
        if d.current_url.startswith(BASE):
            break
    js("document.body.innerHTML = '<div style=\"height:300px\">에펨코리아 화면</div>'")
    js(SHIM + script)
    for _ in range(30):
        if js(f"return !!{R}.querySelector('.bignext')"):
            break
        time.sleep(0.2)
    time.sleep(0.5)


def search_query(board, keyword):
    q = urllib.parse.quote(keyword)
    return f'mid={board}&search_target=title_content&search_keyword={q}' if board else f'act=IS&is_keyword={q}'


def went_to(board, keyword):
    want = 'is_keyword=' + urllib.parse.quote(keyword) if not board else 'search_keyword=' + urllib.parse.quote(keyword)
    for _ in range(75):   # 막아 둔 에펨코리아 주소로 넘어가는 데 가끔 몇 초 걸림 (15초까지 기다림)
        if want in d.current_url and 'fmkorea.com' in d.current_url:
            return True
        time.sleep(0.2)
    return False


# 1.8.0부터 ‹ n/전체 › 단추는 없고, 큰 다음 키워드 단추(› 다음 키워드 n/전체)와 단축키 . , 로 넘김
big_label = lambda: js(f"return {R}.querySelector('.bignext').textContent.replace(/\s+/g, '')")
try:
    # 첫 키워드(투싼)를 보는 중: 1/3, 다음 단추는 쏘렌토, 이전 단추는 마지막(gpt)으로 돌아감
    page(search_query(*order[0]))
    assert big_label() == '›쏘렌토2/3', big_label()
    assert '쏘렌토' in js(f"return {R}.querySelector('[data-seq=\"1\"]').title")
    assert not js(f"return {R}.querySelector('.knav, [data-seq=\"-1\"], .prog, [data-next]')")   # 이전·오늘 진행·다음 ▶ 단추는 없음
    # PC: 다음 키워드는 윗줄 오른쪽 끝의 큰 단추 하나 (작은 ‹ 옆의 ›는 없음), 다음 키워드 이름·순번
    big = js(f"""const b = {R}.querySelector('.bar.top .bignext'), r = b.getBoundingClientRect();
                 return [b.textContent.replace(/\\s+/g, ' ').trim(), Math.round(innerWidth - r.right), Math.round(r.height),
                         {R}.querySelectorAll('[data-seq=\"1\"]').length]""")
    assert big[0].replace(' ', '') == '›쏘렌토2/3' and big[1] <= 12 and big[2] >= 30 and big[3] == 1, big
    js(f"{R}.querySelector('[data-seq=\"1\"]').click()")
    assert went_to(*order[1]), d.current_url
    # 두 번째(쏘렌토)에서 단축키 . → 다음 카드의 gpt, , → 투싼
    page(search_query(*order[1]))
    assert big_label() == '›gpt3/3', big_label()
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: '.', bubbles: true}))")
    assert went_to(*order[2]), d.current_url
    page(search_query(*order[1]))
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: ',', bubbles: true}))")
    assert went_to(*order[0]), d.current_url
    # 마지막(gpt)에서 다음은 처음(투싼)으로
    page(search_query(*order[2]))
    assert big_label() == '›투싼1/3', big_label()
    js(f"{R}.querySelector('[data-seq=\"1\"]').click()")
    assert went_to(*order[0]), d.current_url
    # 누른 시각이 기록됨
    time.sleep(1)
    last = {(l['board'], l['keyword']): l['last_opened'] for g in storage.list_groups() for l in g.get('fm_links', [])}
    assert last[order[0]] and last[order[1]] and last[order[2]], last
    # 목록에 없는 검색: 다음은 첫 키워드, 이전은 마지막 키워드
    page('mid=car&search_keyword=x')
    assert big_label() == '›투싼1/3', big_label()
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: ',', bubbles: true}))")
    assert went_to(*order[2]), d.current_url
    # 묶음 이름(1.7.1): 이름을 누르면 그 묶음의 첫 키워드로, ▸ 화살표 쪽은 펼치기·접기 (이동 없음)
    page(search_query(*order[2]))                              # gpt 보는 중: AI 묶음이 펼쳐져 있음
    js(f"{R}.querySelector('.box:not(.open) .gname').click()")  # 접힌 자동차 묶음의 이름
    assert went_to(*order[0]), d.current_url
    page(search_query(*order[2]))
    js(f"{R}.querySelector('.box:not(.open) [data-toggle]').click()"); time.sleep(.3)
    assert d.current_url.startswith(BASE) and js(f"return {R}.querySelector('.box.open .gname').textContent") == '자동차'
    print('SEQ PC OK')

    # 휴대폰: ‹ n/전체 ›·오늘 진행·다음 ▶ 없음, 큰 다음 단추만
    d.set_window_size(390, 844); time.sleep(.3)
    page(search_query(*order[1]))
    assert not js(f"return {R}.querySelector('.knav, [data-seq=\"-1\"], .prog, [data-next]')")
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    # 휴대폰: 아랫줄 오른쪽에 두 줄 높이의 큰 다음 단추 (엄지가 닿는 자리)
    big = js(f"""const b = {R}.querySelector('.bar.bottom.has-big .bignext'), r = b.getBoundingClientRect();
                 return [b.textContent.replace(/\\s+/g, ' ').trim(), Math.round(innerWidth - r.right), Math.round(r.width), Math.round(r.height)]""")
    assert big[0].replace(' ', '') == '›gpt3/3' and big[1] <= 14 and big[2] >= 56 and big[3] >= 56, big
    js(f"{R}.querySelector('.bignext').click()")
    assert went_to(*order[2]), d.current_url
    print('SEQ MOBILE OK')
finally:
    d.quit()
    srv.shutdown()
