import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome, ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

# 대시보드 카드 배치 편집: 손잡이로 이동, 모서리로 크기 조절, 기기에 저장, 기본값, 편집 중 링크 막기, 카드 겹침 없음
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
for a in ['--headless=new', '--window-size=1280,1000']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
IDS = ['card-board', 'card-ev', 'card-benefit']
order = lambda: js("return ['card-board','card-ev','card-benefit'].sort((a,b)=>+document.getElementById(a).style.order - +document.getElementById(b).style.order)")
rect = lambda i: js(f"const r=document.getElementById('{i}').getBoundingClientRect(); return [r.left,r.top,r.width,r.height]")
def no_overlap():
    rs = [rect(i) for i in IDS]
    for a in range(3):
        for b in range(a + 1, 3):
            A, B = rs[a], rs[b]
            separated = A[0] + A[2] <= B[0] + 1 or B[0] + B[2] <= A[0] + 1 or A[1] + A[3] <= B[1] + 1 or B[1] + B[3] <= A[1] + 1
            assert separated, (IDS[a], IDS[b], rs)
def el(sel): return d.find_element(By.CSS_SELECTOR, sel)
try:
    d.get(BASE + '/'); time.sleep(1.5)
    assert order() == IDS
    no_overlap()
    # 기본 배치: 왼쪽 게시판, 오른쪽 유지비. 카드 혜택은 그 아래 빈자리 중 먼저 나오는 곳 (글이 없는 시험 DB라 게시판이 짧음)
    board, ev, ben = (rect(i) for i in IDS)
    assert ev[0] > board[0] + board[2] - 1 and abs(board[1] - ev[1]) < 2, (board, ev)
    assert ben[1] > ev[1], ben
    # 편집 전에는 손잡이 없음
    assert js("return getComputedStyle(document.querySelector('.card-grip')).display") == 'none'
    el('#layout-edit').click()
    assert js("return document.body.classList.contains('is-editing')") and el('#layout-edit').text == '완료'

    # 편집 중 링크는 이동하지 않음
    el('#card-ev .card-head').click(); time.sleep(.3)
    assert d.current_url == BASE + '/'

    # 끌어서 이동: 유지비 카드를 게시판 위로
    ActionChains(d).click_and_hold(el('#card-ev .card-grip')).move_to_element(el('#card-board')).move_by_offset(5, 5).release().perform()
    time.sleep(.4)
    assert order() == ['card-ev', 'card-board', 'card-benefit'], order()
    assert js("return document.getElementById('card-ev').style.transform") == ''
    no_overlap()

    # 크기: 오른쪽으로 끌면 칸이 넓어지고, 가로로만 끌면 높이는 내용에 맞춤 유지
    before = rect('card-ev')
    ActionChains(d).click_and_hold(el('#card-ev .card-resize')).move_by_offset(160, 0).release().perform()
    time.sleep(.4)
    after = rect('card-ev')
    assert after[2] > before[2] + 50, (before, after)
    assert js("return document.getElementById('card-ev').style.height") == ''
    no_overlap()
    # 아래로 끌면 높이 고정, 내용은 카드 안에서 스크롤
    before = rect('card-benefit')
    ActionChains(d).click_and_hold(el('#card-benefit .card-resize')).move_by_offset(0, 120).release().perform()
    time.sleep(.4)
    after = rect('card-benefit')
    assert 100 < after[3] - before[3] < 140, (before, after)
    no_overlap()
    # 크게 줄여도 최소 크기는 지킴
    ActionChains(d).click_and_hold(el('#card-benefit .card-resize')).move_by_offset(int(40 - after[0] - after[2]), int(40 - after[1] - after[3])).release().perform()
    time.sleep(.4)
    small = rect('card-benefit')
    assert small[3] >= 119 and small[2] > 200, small
    print('DRAG OK')

    # 방향키로도 이동
    el('#card-benefit .card-grip').send_keys(Keys.ARROW_LEFT); time.sleep(.2)
    assert order() == ['card-ev', 'card-benefit', 'card-board'], order()

    # 다시 열어도 유지
    saved = order(); saved_w = rect('card-ev')[2]
    d.get(BASE + '/'); time.sleep(1.5)
    assert order() == saved and abs(rect('card-ev')[2] - saved_w) < 2
    assert not js("return document.body.classList.contains('is-editing')")
    no_overlap()
    # 잘못 저장된 값이 있어도 동작
    js("localStorage.setItem('dashboard_layout_v1', '[{\"id\":\"없음\"},{\"id\":\"card-ev\",\"w\":99,\"h\":\"x\"},5]')")
    d.get(BASE + '/'); time.sleep(1.5)
    assert order() == ['card-ev', 'card-board', 'card-benefit'] and rect('card-ev')[2] > 900
    print('SAVE OK')

    # 기본값
    el('#layout-edit').click()
    el('#layout-reset').click(); time.sleep(.3)
    assert order() == IDS and js("return JSON.parse(localStorage.getItem('dashboard_layout_v1'))[0].w") == 7
    no_overlap()
    el('#layout-edit').click()
    assert el('#layout-reset').is_displayed() is False

    # 편집을 끝내면 링크가 다시 동작
    el('#card-ev .card-head').click(); time.sleep(1)
    assert d.current_url == BASE + '/ev/'

    # 모바일: 한 줄, 가로 넘침 없음, 순서 이동
    d.set_window_size(390, 844); time.sleep(.5)
    d.get(BASE + '/'); time.sleep(1.5)
    width = js("return document.getElementById('dash-grid').clientWidth")
    for i in IDS:
        assert abs(rect(i)[2] - width) < 2, rect(i)
    no_overlap()
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    el('#layout-edit').click()
    el('#card-ev .card-grip').send_keys(Keys.ARROW_UP); time.sleep(.2)
    assert order()[0] == 'card-ev'
    no_overlap()
    print('MOBILE OK')
finally:
    d.quit()
    srv.shutdown()
