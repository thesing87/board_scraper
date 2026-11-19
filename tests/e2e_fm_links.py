"""에펨코리아 바로가기: 수집하지 않고 게시판에 에펨코리아 검색 링크만 등록. 게시판 편집에서 추가·빼기(직접 입력 포함),
키워드 게시판 제목 아래 링크 줄(A안), 대시보드 '에펨코리아 바로가기' 카드. 합친 게시판의 링크는 옮겨 옴"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, time, json, socket, urllib.request, urllib.error, urllib.parse
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
tesla, _ = storage.save_group(None, '테슬라', [{'board': B, 'keyword': '테슬라'}])
# 예전 에펨코리아 키워드가 남은 게시판 (키워드 설명 줄에는 디시 키워드만)
mixed, _ = storage.save_group(None, '볼보', [{'board': 'car', 'keyword': '볼보'}, {'board': B, 'keyword': '볼보'}])
fm_only, _ = storage.save_group(None, '삼성', [{'board': 'baseball', 'keyword': '삼성'}])
ai, _ = storage.save_group(None, 'AI', [{'board': B, 'keyword': '클로드'}], fm_links=[{'board': '', 'keyword': 'gpt'}])

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'

def post(body):
    req = urllib.request.Request(BASE + '/api/group', json.dumps({**body, 'password': 'Secr3t!'}).encode(), {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
def links(gid):
    return next(g for g in storage.list_groups() if g['id'] == gid)['fm_links']

# API: 잘못된 게시판 이름·빈 키워드는 거부, 보내지 않으면 그대로
base = {'action': 'update', 'id': tesla, 'name': '테슬라', 'members': [{'board': B, 'keyword': '테슬라'}]}
assert post({**base, 'fm_links': [{'board': '12345', 'keyword': 'x'}]})[0] == 400
assert post({**base, 'fm_links': [{'board': 'car', 'keyword': ' '}]})[0] == 400
assert post({**base, 'fm_links': [{'board': 'Car', 'keyword': '테슬라'}]})[0] == 200
assert links(tesla) == [{'board': 'car', 'keyword': '테슬라'}]
assert post(base)[0] == 200 and links(tesla) == [{'board': 'car', 'keyword': '테슬라'}]
print('API OK')

o = Options()
for a in ['--headless=new', '--window-size=1440,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get(BASE + '/board/'); time.sleep(2.5)
    js("localStorage.setItem('admin_token', 'Secr3t!'); updateAdminUI(); document.querySelector('.topbar [data-action=\"open-settings\"]').click()"); time.sleep(0.5)
    js(f"document.querySelector('[data-action=\"edit-group\"][data-group-id=\"{tesla}\"]').click()"); time.sleep(0.4)
    assert js("return [...document.querySelectorAll('#group-fm-board option')].map(o => o.textContent)")[-2:] == ['전체 게시판', '직접 입력…']
    assert '자동차' in js("return document.getElementById('group-fmlinks').textContent")
    # 자동차 게시판에 모델y, 직접 입력으로 해외축구에 손흥민
    js("const s = document.getElementById('group-fm-board'); s.value = 'car'; s.dispatchEvent(new Event('change', {bubbles: true}))")
    js("document.getElementById('group-fm-input').value = '모델y'; document.querySelector('[data-action=\"add-draft-fmlink\"]').click()"); time.sleep(0.2)
    js("const s = document.getElementById('group-fm-board'); s.value = '__custom'; s.dispatchEvent(new Event('change', {bubbles: true}))")
    assert not js("return document.getElementById('group-fm-mid').hidden")
    js("document.getElementById('group-fm-mid').value = 'Football_World'; document.getElementById('group-fm-input').value = '손흥민'; document.querySelector('[data-action=\"add-draft-fmlink\"]').click()"); time.sleep(0.2)
    # 빼기 (모델y)
    js("document.querySelectorAll('[data-action=\"remove-draft-fmlink\"]')[1].click()"); time.sleep(0.2)
    js("document.querySelector('[data-action=\"save-group\"]').click()"); time.sleep(2)
    assert links(tesla) == [{'board': 'car', 'keyword': '테슬라'}, {'board': 'football_world', 'keyword': '손흥민'}], links(tesla)
    # 저장하면 그 게시판이 열림: 제목 아래 바로가기 줄 (게시판이 둘 이상이면 게시판 이름도)
    chips = js("return [...document.querySelectorAll('.fm-links .fm-link')].map(a => [a.textContent.trim(), a.href, a.target])")
    print('chips', chips)
    q = urllib.parse.quote('테슬라')
    assert chips[0][1] == f'https://www.fmkorea.com/index.php?mid=car&search_target=title_content&search_keyword={q}' and chips[0][2] == '_blank'
    assert chips[0][0].endswith('테슬라') and 'football_world' in chips[1][1]
    # 바로가기 없는 게시판은 줄이 없음
    js("openBoard(ALL_KEY)"); time.sleep(1.2)
    assert not js("return document.querySelector('.fm-links')")
    js(f"openBoard('group:{mixed}')"); time.sleep(1.2)
    sub = js("return document.querySelector('.feed-sub').textContent")
    assert '키워드 볼보' in sub and 'FM' not in sub and 'DC' not in sub, sub
    js(f"openBoard('group:{fm_only}')"); time.sleep(1.2)
    assert '수집하는 키워드 없음' in js("return document.querySelector('.feed-sub').textContent")
    print('BOARD VIEW OK')

    # 게시판 합치기: AI 게시판을 테슬라에 합치면 AI의 바로가기(전체 검색 gpt)도 옮겨 옴
    st, data = post({**base, 'merge_ids': [ai], 'members': [{'board': B, 'keyword': '테슬라'}, {'board': B, 'keyword': '클로드'}]})
    assert st == 200 and links(tesla)[-1] == {'board': '', 'keyword': 'gpt'} and len(links(tesla)) == 3, links(tesla)
    print('MERGE OK')

    # 대시보드 카드
    d.get(BASE + '/'); time.sleep(2.5)
    body = js("return document.getElementById('fmlinks-body').textContent")
    hrefs = js("return [...document.querySelectorAll('#fmlinks-body .fm-chip')].map(a => a.href)")
    assert '테슬라' in body and len(hrefs) == 3 and hrefs[2] == 'https://www.fmkorea.com/search.php?act=IS&is_keyword=gpt', hrefs
    assert js("return document.getElementById('fmlinks-sub').textContent") == '검색 링크 3개 · 새 창'
    d.set_window_size(390, 844); time.sleep(0.5)
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('DASHBOARD OK')
finally:
    d.quit()
    srv.shutdown()
print('FM LINKS OK')
