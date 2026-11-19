"""FM키워드 순서 바꾸기: 키워드 게시판 FM키워드 화면의 편집에서 키워드 칩을 끌어 카드 안 순서를, 손잡이(⠿)를 끌어 카드 순서를 바꿈.
서버에 저장되어 에펨코리아 화면의 키워드 줄(/api/fm-links)·대시보드 카드도 같은 순서. 사이드바 순서는 그대로, 마지막으로 연 시각도 그대로"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, time, json, socket, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome, ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

storage.init_db()
B = 'dc:car_new1'
storage.add_category(B)
storage.set_category_checked(B, True, page_name='자동차 갤러리')
car, _ = storage.save_group(None, '자동차', [{'board': B, 'keyword': '차'}],
                            fm_links=[{'board': 'car', 'keyword': k} for k in ('투싼', '쏘렌토', '아반떼')])
soccer, _ = storage.save_group(None, '축구', [{'board': B, 'keyword': '공'}], fm_links=[{'board': 'football_world', 'keyword': '손흥민'}])
plain, _ = storage.save_group(None, '빈칸', [{'board': B, 'keyword': '빈'}])
ai, _ = storage.save_group(None, 'AI', [{'board': B, 'keyword': '클로드'}], fm_links=[{'board': '', 'keyword': 'gpt'}])
storage.touch_fm_link(car, 'car', '쏘렌토')

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'

def post(body, password='Secr3t!'):
    req = urllib.request.Request(BASE + '/api/fm-link', json.dumps({**body, 'password': password}).encode(), {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
def kws(gid):
    return [l['keyword'] for l in next(g for g in storage.list_groups() if g['id'] == gid)['fm_links']]
def bar():
    with urllib.request.urlopen(BASE + '/api/fm-links') as r:
        return [(g['name'], [l['keyword'] for l in g['links']]) for g in json.loads(r.read())['groups']]
sidebar = [g['id'] for g in storage.list_groups()]

# API: 관리자만, 목록이 다르면 거부, 마지막으로 연 시각은 그대로
order = [{'board': 'car', 'keyword': k} for k in ('아반떼', '투싼', '쏘렌토')]
assert post({'action': 'reorder', 'group_id': car, 'links': order}, password='nope')[0] in (401, 403)
assert post({'action': 'reorder', 'group_id': car, 'links': order[:2]})[0] == 409
assert post({'action': 'reorder', 'group_id': car, 'links': order + order[:1]})[0] == 409
assert post({'action': 'reorder', 'group_id': car, 'links': 'x'})[0] == 400
st, data = post({'action': 'reorder', 'group_id': car, 'links': order})
assert st == 200 and [l['keyword'] for l in data['links']] == ['아반떼', '투싼', '쏘렌토'], data
assert next(l for l in data['links'] if l['keyword'] == '쏘렌토')['last_opened']
assert kws(car) == ['아반떼', '투싼', '쏘렌토']
assert post({'action': 'reorder_groups', 'ids': [99999]})[0] == 409
assert post({'action': 'reorder_groups', 'ids': ['a']})[0] == 400
assert post({'action': 'reorder_groups', 'ids': [ai]})[0] == 200
# 정한 카드(AI) 먼저, 나머지는 사이드바 순서
assert bar() == [('AI', ['gpt']), ('자동차', ['아반떼', '투싼', '쏘렌토']), ('축구', ['손흥민'])], bar()
assert [g['id'] for g in storage.list_groups()] == sidebar   # 사이드바 순서는 그대로
# 다른 카드로 옮기기 (API): 받는 카드에 같은 링크가 있거나 목록이 다르면 거부
to_soccer = [{'board': 'car', 'keyword': '아반떼'}, {'board': 'football_world', 'keyword': '손흥민'}]
assert post({'action': 'move', 'from_group': car, 'group_id': soccer, 'board': 'car', 'keyword': '아반떼', 'links': to_soccer[1:]})[0] == 409
assert post({'action': 'move', 'from_group': car, 'group_id': car, 'board': 'car', 'keyword': '아반떼', 'links': to_soccer})[0] == 409
assert post({'action': 'move', 'from_group': car, 'group_id': soccer, 'board': 'car', 'keyword': '없음', 'links': to_soccer})[0] == 409
assert post({'action': 'move', 'from_group': car, 'group_id': soccer, 'board': 'car', 'keyword': '아반떼', 'links': to_soccer}, password='x')[0] == 401
st, data = post({'action': 'move', 'from_group': car, 'group_id': soccer, 'board': 'car', 'keyword': '아반떼', 'links': to_soccer})
assert st == 200 and kws(soccer) == ['아반떼', '손흥민'] and kws(car) == ['투싼', '쏘렌토'], data
storage.add_fm_link(car, 'car', '아반떼')
assert post({'action': 'move', 'from_group': soccer, 'group_id': car, 'board': 'car', 'keyword': '아반떼',
             'links': [{'board': 'car', 'keyword': k} for k in ('아반떼', '투싼', '쏘렌토')]})[0] == 409
storage.remove_fm_link(soccer, 'car', '아반떼')
# 처음 순서로 되돌림
post({'action': 'reorder', 'group_id': car, 'links': [{'board': 'car', 'keyword': k} for k in ('투싼', '쏘렌토', '아반떼')]})
post({'action': 'reorder_groups', 'ids': []})
assert bar() == [('자동차', ['투싼', '쏘렌토', '아반떼']), ('축구', ['손흥민']), ('AI', ['gpt'])], bar()
print('API OK')

def run(mobile):
    o = Options()
    for a in ['--headless=new', '--window-size=' + ('400,860' if mobile else '1440,900')]:
        o.add_argument(a)
    if mobile:
        o.add_experimental_option('mobileEmulation', {'deviceMetrics': {'width': 400, 'height': 860, 'pixelRatio': 2, 'touch': True}})
    d = Chrome(options=o)
    js = d.execute_script
    try:
        d.get(BASE + '/board/'); time.sleep(2.5)
        js("localStorage.setItem('admin_token', 'Secr3t!'); updateAdminUI(); openBoard(FM_KEY)"); time.sleep(1)
        assert js("return [...document.querySelectorAll('[data-action=\"fm-sort\"]')].map(b => b.textContent)") == ['내 순서', '오래 안 본 순']
        assert not js("return document.querySelector('.fmk-grip')")
        js("document.querySelector('[data-action=\"fm-edit\"]').click()"); time.sleep(0.4)
        assert js("return document.querySelectorAll('.fmk-grip').length") == 3
        chips = lambda: js(f"return [...document.querySelectorAll('[data-fm-group=\"{car}\"] .fmk-chip')].map(c => c.dataset.keyword)")
        cards = lambda: js("return [...document.querySelectorAll('.fmk-card[data-fm-group]')].map(c => c.getAttribute('aria-label'))")
        assert chips() == ['투싼', '쏘렌토', '아반떼'], chips()

        def drag(src, dst):
            src.location_once_scrolled_into_view
            ac = ActionChains(d)
            # 칩의 왼쪽(글자)을 누름 (오른쪽의 빼기 단추가 아니라)
            ac.move_to_element_with_offset(src, -src.size['width'] // 2 + 8, 0).click_and_hold().move_by_offset(4, 4).pause(0.1)
            ac.move_to_element(dst).pause(0.1).move_by_offset(2, 0).pause(0.1).release().perform()
            time.sleep(1.2)
        chip_el = lambda k: d.find_element(By.CSS_SELECTOR, f'[data-fm-group="{car}"] .fmk-chip[data-keyword="{k}"]')
        # 아반떼를 투싼 자리로 끌면 맨 앞
        drag(chip_el('아반떼'), chip_el('투싼'))
        assert chips() == ['아반떼', '투싼', '쏘렌토'], chips()
        assert kws(car) == ['아반떼', '투싼', '쏘렌토'], kws(car)
        # 조금만 움직이면(누르기만) 그대로
        el = chip_el('투싼')
        ActionChains(d).move_to_element_with_offset(el, -el.size['width'] // 2 + 8, 0).click_and_hold().move_by_offset(2, 0).release().perform(); time.sleep(0.6)
        assert kws(car) == ['아반떼', '투싼', '쏘렌토'], (kws(car), chips())
        # 카드: AI 손잡이를 자동차 카드 위로
        grip = lambda name: d.find_element(By.CSS_SELECTOR, f'.fmk-card[aria-label="{name}"] .fmk-grip')
        card = lambda name: d.find_element(By.CSS_SELECTOR, f'.fmk-card[aria-label="{name}"]')
        assert cards() == ['자동차', '축구', 'AI'], cards()
        drag(grip('AI'), card('자동차'))
        assert cards() == ['AI', '자동차', '축구'], cards()
        assert bar() == [('AI', ['gpt']), ('자동차', ['아반떼', '투싼', '쏘렌토']), ('축구', ['손흥민'])], bar()
        assert [g['id'] for g in storage.list_groups()] == sidebar
        if mobile:
            # 손가락으로 끌기 (터치): 쏘렌토를 아반떼 자리로 → 쏘렌토, 아반떼, 투싼
            box = lambda k: js(f"const r = document.querySelector('[data-fm-group=\"{car}\"] .fmk-chip[data-keyword=\"{k}\"]').getBoundingClientRect(); return [r.left + 10, r.top + r.height / 2]")
            touch = lambda kind, xy: d.execute_cdp_cmd('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': [] if kind == 'touchEnd' else [{'x': xy[0], 'y': xy[1]}]})
            sx, sy = box('쏘렌토'); tx, ty = box('아반떼')
            touch('touchStart', (sx, sy))
            for n in range(1, 11):
                touch('touchMove', (sx + (tx - sx) * n / 10, sy + (ty - sy) * n / 10)); time.sleep(0.03)
            touch('touchEnd', None); time.sleep(1.2)
            assert kws(car) == ['쏘렌토', '아반떼', '투싼'], (kws(car), chips())
            post({'action': 'reorder', 'group_id': car, 'links': [{'board': 'car', 'keyword': k} for k in ('아반떼', '투싼', '쏘렌토')]})
            js("loadState()"); time.sleep(1.5)
        # 새로 고쳐도, 편집을 끝내도(내 순서) 같은 순서
        d.refresh(); time.sleep(2.5)
        js("openBoard(FM_KEY)"); time.sleep(1)
        assert cards() == ['AI', '자동차', '축구'] and chips() == ['아반떼', '투싼', '쏘렌토'], (cards(), chips())
        # 다른 카드로 옮기기: 쏘렌토를 축구의 손흥민 위로 → 축구 맨 앞, 마지막으로 연 시각은 그대로
        js("document.querySelector('[data-action=\"fm-edit\"]').click()"); time.sleep(0.4)
        soccer_chip = lambda k: d.find_element(By.CSS_SELECTOR, f'[data-fm-group="{soccer}"] .fmk-chip[data-keyword="{k}"]')
        drag(chip_el('쏘렌토'), soccer_chip('손흥민'))
        assert kws(soccer) == ['쏘렌토', '손흥민'] and kws(car) == ['아반떼', '투싼'], (kws(soccer), kws(car))
        assert next(g for g in storage.list_groups() if g['id'] == soccer)['fm_links'][0]['last_opened']
        assert js(f"return [...document.querySelectorAll('[data-fm-group=\"{soccer}\"] .fmk-chip')].map(c => c.dataset.keyword)") == ['쏘렌토', '손흥민']
        assert not js("return document.querySelector('.is-drop, .is-refuse')")
        # 되돌림 (API)
        st, data = post({'action': 'move', 'from_group': soccer, 'group_id': car, 'board': 'car', 'keyword': '쏘렌토',
                         'links': [{'board': 'car', 'keyword': k} for k in ('아반떼', '투싼', '쏘렌토')]})
        assert st == 200 and [l['keyword'] for l in data['from_links']] == ['손흥민'], data
        # 같은 키워드가 있는 카드에는 넣지 않음
        storage.add_fm_link(soccer, 'car', '아반떼')
        js("loadState()"); time.sleep(1.5)
        drag(chip_el('아반떼'), soccer_chip('손흥민'))
        assert kws(car) == ['아반떼', '투싼', '쏘렌토'] and kws(soccer) == ['손흥민', '아반떼'], (kws(car), kws(soccer))
        assert chips() == ['아반떼', '투싼', '쏘렌토'], chips()
        storage.remove_fm_link(soccer, 'car', '아반떼')
        # 대시보드 카드도 같은 순서
        d.get(BASE + '/'); time.sleep(2.5)
        names = js("return [...document.querySelectorAll('#fmlinks-body .fm-groups > *')].map(g => g.textContent.trim().split(/\\s+/)[0])")
        assert names[:3] == ['AI', '자동차', '축구'], names
        assert not [m for m in d.get_log('browser') if m['level'] == 'SEVERE'], d.get_log('browser')
    finally:
        d.quit()
    # 다음 실행을 위해 처음 순서로
    post({'action': 'reorder', 'group_id': car, 'links': [{'board': 'car', 'keyword': k} for k in ('투싼', '쏘렌토', '아반떼')]})
    post({'action': 'reorder_groups', 'ids': []})

run(False)
print('PC DRAG OK')
run(True)
print('MOBILE DRAG OK')
print('ALL OK')
