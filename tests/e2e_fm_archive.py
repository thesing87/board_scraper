"""FM키워드 줄 1.9.0~1.9.1: 새 글이 한 쪽을 넘칠 때 안내('다음 쪽 보기 ▶', 칩 '새 N+'), 글 화면의 '보관'(보고 있는 화면의 본문·댓글을
그 FM키워드 카드의 보관함에 담음), 찾은 새 글 제목을 하루 요약용으로 보냄. 하루 요약 메시지(fm_digest)도 확인.
에펨코리아에는 접속하지 않도록 로컬 페이지에서 GM_* 함수를 흉내 내어 시험"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, time, socket, urllib.request, urllib.parse
from datetime import datetime
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, fm_digest
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
B = 'dc:car_new1'
storage.add_category(B)
storage.set_category_checked(B, True, page_name='자동차 갤러리')
GID, _ = storage.save_group(None, '자동차', [{'board': B, 'keyword': '차'}], fm_links=[{'board': 'car', 'keyword': '투싼'}])
NO = 9000000000
storage.fm_seen_init('car', '투싼', NO)

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'
with urllib.request.urlopen(BASE + '/fm-keywords.user.js') as r:
    script = r.read().decode('utf-8')
assert '// @version      1.9.1' in script

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
post_q = lambda no: f'{SEARCH}&document_srl={no}'
rows = lambda nos: '<table class="bd_lst"><tbody>' + ''.join(
    f'<tr><td class="title"><a class="hx" href="/api/fm-links?{post_q(no)}">투싼 글 {no - NO}</a></td></tr>' for no in nos) + '</tbody></table>'

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


def until(check, tries=30):
    for _ in range(tries):
        value = check()
        if value:
            return value
        time.sleep(0.2)
    return check()


note = lambda: js("const n = document.querySelector('.kmfm-note'); return n ? n.textContent.replace(/\\s+/g, ' ').trim() : ''")
badge = lambda: js(f"const b = {R}.querySelector('a.chip .newb'); return b ? b.textContent : ''")
side = lambda: js(f"const s = {R}.querySelector('.side'); return s ? s.textContent.replace(/\\s+/g, ' ').trim() : ''")

POST_BODY = """
<div class="rd_hd"><div class="board"><div class="top_area"><h1><span class="np_18px_span">투싼 하이브리드 후기</span></h1>
  <span class="date m_no">2026.11.25 14:02</span></div>
  <div class="btm_area"><div class="side"><a class="member_plate">차덕후</a></div>
  <div class="side fr"><span>조회 수 <b>1,204</b></span><span>추천 수 <b>12</b></span><span>댓글 <b>2</b></span></div></div></div></div>
<div class="rd_body"><article><div class="xe_content"><p>연비가 <b>좋아요</b></p><script>window.bad = 1</script>
  <img src="//image.fmkorea.com/files/attach/new/20261125/a.jpg"></div></article></div>
<div id="cmtPosition"><ul class="fdb_lst_ul">
  <li class="fdb_itm"><div class="meta"><a>갑</a><span class="date">1 시간 전</span></div><div class="comment-content"><div class="xe_content">저도 타요</div></div></li>
  <li class="fdb_itm" style="margin-left:2%"><div class="meta"><a>을</a></div><div class="comment-content"><div class="xe_content">답글</div></div></li>
</ul></div>"""

try:
    # 1쪽이 모두 새 글: 다음 쪽에 더 있을 수 있음, 칩은 '새 3+'
    page(SEARCH, rows([NO + 5, NO + 4, NO + 3]))
    assert until(lambda: '다음 쪽에도 더 있을 수 있음' in note()), note()
    assert note().startswith('안 읽은 새 글 3개'), note()
    href = js("return document.querySelector('[data-kmfm-next]').getAttribute('href')")
    assert 'page=2' in href and 'search_keyword' in href, href
    assert until(lambda: badge() == '새 3+'), badge()
    assert js("return document.querySelectorAll('.kmfm-line').length") == 0
    # 찾은 새 글 제목이 서버에 (하루 요약)
    titles = until(lambda: {r['no']: r['title'] for r in storage.fm_digest('2000-01-01')[0]['links'][0]['titles']}
                   if storage.fm_digest('2000-01-01') else None)
    assert titles == {NO + 5: '투싼 글 5', NO + 4: '투싼 글 4', NO + 3: '투싼 글 3'}, titles
    # 2쪽: 마지막으로 읽은 곳(기준)이 보이면 넘침이 풀림, 구분선
    page(SEARCH + '&page=2', rows([NO + 2, NO - 1, NO - 2]))
    assert until(lambda: note().startswith('안 읽은 새 글 1개')) and '다음 쪽' not in note(), note()
    assert js("return document.querySelectorAll('.kmfm-line').length") == 1
    assert until(lambda: badge() == '새 4'), badge()
    # 1.9.1: 2쪽까지 보고 1쪽에 돌아오면 '다음 쪽 보기'가 다시 뜨지 않음 (이어서 확인한 범위를 기억)
    page(SEARCH, rows([NO + 5, NO + 4, NO + 3]))
    assert until(lambda: note().startswith('안 읽은 새 글 3개')), note()
    assert '다음 쪽' not in note() and not js("return !!document.querySelector('[data-kmfm-next]')"), note()
    assert until(lambda: badge() == '새 4'), badge()
    print('OVERFLOW OK')

    # 글 화면(검색에서 연 글): '보관' → 비밀번호 → 보관함에 있음
    page(post_q(NO + 4), POST_BODY)
    assert until(lambda: '보관' in side()) and '보관함에 있음' not in side(), side()
    js(f"{R}.querySelector('[data-archive]').click()")
    assert until(lambda: js(f"return !!{R}.querySelector('[data-arcpwd]')"))
    js(f"const i = {R}.querySelector('[data-arcpwd]'); i.value = 'wrong'; i.dispatchEvent(new Event('input', {{bubbles: true}}))")
    js(f"{R}.querySelector('[data-arcgo]').click()")
    assert until(lambda: '비밀번호가 맞지 않습니다' in js(f"return {R}.querySelector('.picker').textContent")), side()
    assert not storage.fm_archive_status(str(NO + 4))['saved']
    js(f"const i = {R}.querySelector('[data-arcpwd]'); i.value = 'Secr3t!'; i.dispatchEvent(new Event('input', {{bubbles: true}}))")
    js(f"{R}.querySelector('[data-arcgo]').click()")
    assert until(lambda: '보관함에 있음 · 댓글 2' in side()), side()
    assert not js(f"return !!{R}.querySelector('.picker')")
    assert js("return JSON.parse(localStorage.getItem('gm_fm_admin_password'))") == 'Secr3t!'
    status = storage.fm_archive_status(str(NO + 4))
    assert status['saved'] and status['comments'] == 2, status
    total, posts = storage.query_all_posts(0, 10, group_id=GID, saved_only=True)
    assert total == 1, total
    p = posts[0]
    assert (p['title'], p['author'], p['views'], p['votes'], p['link']) == (
        '투싼 하이브리드 후기', '차덕후', '1204', '12', f'https://www.fmkorea.com/{NO + 4}'), p
    body = ' '.join(p['content'])
    assert '<b>좋아요</b>' in body and 'script' not in body and 'https://image.fmkorea.com/files/attach/new/20261125/a.jpg' in body, body
    assert [(c['author'], c['depth']) for c in p['comments']] == [('갑', 0), ('을', 1)], p['comments']
    assert not p['is_new'] and p['keywords'] == [{'board': 'car', 'keyword': '투싼'}], p
    # 다시 열면 '보관함에 있음' (서버에 물어봄), 다시 보관하면 댓글이 새로 고쳐짐
    page(post_q(NO + 4), POST_BODY.replace('</ul>', '<li class="fdb_itm"><div class="meta"><a>병</a></div><div class="xe_content">새 댓글</div></li></ul>'))
    assert until(lambda: '보관함에 있음 · 댓글 2' in side()), side()
    js(f"{R}.querySelector('[data-archive]').click()")
    assert until(lambda: '보관함에 있음 · 댓글 3' in side()), side()
    assert storage.fm_archive_status(str(NO + 4))['comments'] == 3
    # FM키워드 검색에서 연 글이 아니면 보관 단추 없음
    page(f'mid=car&document_srl={NO + 77}', POST_BODY)
    time.sleep(0.5)
    assert '보관' not in side(), side()
    print('ARCHIVE PC OK')

    # 휴대폰: 짧게 '보관됨'
    d.set_window_size(390, 844); time.sleep(.3)
    page(post_q(NO + 4), POST_BODY)
    assert until(lambda: '보관됨' in side()), side()
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('ARCHIVE MOBILE OK')

    # 하루 요약: 안 읽은 글(NO+5·NO+3·NO+2, NO+4는 열어서 읽음)
    sent = []
    fm_digest._send_html = lambda base, text, what: sent.append(text) or True
    assert fm_digest.send_if_due(datetime(2026, 11, 26, 9, 0))
    assert not fm_digest.send_if_due(datetime(2026, 11, 26, 10, 0))      # 하루 한 번
    text = sent[0]
    assert '찾은 새 글 4 · 안 읽음 3' in text and '<b>자동차</b>' in text and '· 투싼' in text, text
    assert f'<a href="https://www.fmkorea.com/{NO + 5}">투싼 글 5</a>' in text and '투싼 글 4' not in text, text
    assert fm_digest.build_message([]) is None
    print('DIGEST OK')

    # 그 뒤 새 글이 한 쪽 넘게 올라와 이어서 본 범위와 떨어지면 다시 '다음 쪽 보기'
    d.set_window_size(1280, 900); time.sleep(.3)
    page(SEARCH, rows([NO + 12, NO + 11, NO + 10]))
    assert until(lambda: '다음 쪽에도 더 있을 수 있음' in note()), note()
    assert until(lambda: badge().endswith('+')), badge()
    # 2쪽(바로 아래, 앞서 본 범위에 닿음)을 보면 1쪽에 돌아와도 풀린 채
    page(SEARCH + '&page=2', rows([NO + 9, NO + 6, NO + 5]))
    assert until(lambda: note() != '') and '다음 쪽' not in note(), note()
    page(SEARCH, rows([NO + 12, NO + 11, NO + 10]))
    assert until(lambda: note().startswith('안 읽은 새 글')) and '다음 쪽' not in note(), note()
    assert until(lambda: not badge().endswith('+')), badge()
    print('OVERFLOW AGAIN OK')
finally:
    d.quit()
    srv.shutdown()
