"""가계부 화면(/ledger/): 가입 요청 → 허락 전 로그인 안내 → 관리자 기기는 자동 로그인·사용자 허락 → 입력(금액·소비형태·메모)
→ 소비형태 추가(색을 골라야)·색 바꾸기 → 최근 메모 드롭다운(소비형태도 함께) → 일별·월별·사람 거르기·원형 그래프 →
내 기록 고치기·지우기, 남의 기록은 못 고침 → 메뉴의 가계부는 로그인한 기기에만, 휴대폰 넘침 없음"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, time
from datetime import date
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LEDGER_ADMIN_NAME='임기범')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, ledger
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
TODAY = date.today().isoformat()

o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
vis = lambda i: js(f"const e = document.getElementById('{i}'); return !!e && !e.hidden && e.offsetHeight > 0")
txt = lambda i: js(f"return document.getElementById('{i}').textContent.replace(/\\s+/g, ' ').trim()")
navs = lambda: js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)")
def typ(i, v):
    js("const e = document.getElementById(arguments[0]); e.value = arguments[1]; e.dispatchEvent(new Event('input', {bubbles: true}))", i, v)
def click(sel):
    js("document.querySelector(arguments[0]).click()", sel)
def entries():
    with storage._db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM ledger_entries ORDER BY id")]
try:
    # ---- 처음 온 사람: 로그인 화면, 메뉴에는 가계부가 이 페이지에서만
    d.get(BASE + '/'); time.sleep(1)
    assert 'ledger' not in navs()
    d.get(BASE + '/ledger/'); time.sleep(1.5)
    assert vis('auth') and not vis('app')
    # 가입 요청 (비밀번호 확인이 다르면 막음)
    click('#tab-signup')
    typ('su-name', '지은'); typ('su-pw', 'pw12'); typ('su-pw2', 'pw13')
    js("document.getElementById('signup-form').requestSubmit()"); time.sleep(.5)
    assert '다릅니다' in txt('auth-msg')
    typ('su-pw2', 'pw12')
    js("document.getElementById('signup-form').requestSubmit()"); time.sleep(1)
    assert '가입 요청을 보냈어요' in txt('auth-msg') and vis('login-form')
    # 허락 전에는 로그인 안 됨
    typ('login-pw', 'pw12')
    js("document.getElementById('login-form').requestSubmit()"); time.sleep(1)
    assert '허락하지 않았어요' in txt('auth-msg'), txt('auth-msg')
    print('SIGNUP OK')

    # ---- 관리자 기기: 대시보드 로그인 키로 자동 로그인, 사용자 허락
    js("localStorage.setItem('admin_token', arguments[0])", web_server.ADMIN_TOKEN)
    d.get(BASE + '/ledger/'); time.sleep(2)
    assert vis('app') and not vis('auth') and '임기범' in txt('who-me')
    assert js("return document.querySelector('#who-me .av').textContent") == '임'      # 아이콘은 이름 첫 글자
    assert vis('admin') and txt('pending-count') == '1' and js("return document.getElementById('admin').open")
    click('[data-admin="approve"]'); time.sleep(1)
    assert '기다리는 사람 없음' in txt('pending') and '지은' in txt('members')
    assert 'ledger' in navs()
    print('ADMIN OK')

    # ---- 입력: 금액(쉼표), 소비형태, 메모
    assert [c for c in js("return [...document.querySelectorAll('#cats .chip')].map(c => c.textContent.trim())")][:6] == ['식비', '카페', '교통', '생활', '쇼핑', '의료']
    typ('amount', '42000')
    assert js("return document.getElementById('amount').value") == '42,000'
    typ('memo', '이마트 장보기')
    click('#save'); time.sleep(1.2)
    e = entries()
    assert len(e) == 1 and e[0]['amount'] == 42000 and e[0]['memo'] == '이마트 장보기' and e[0]['used_on'] == TODAY
    assert txt('m1') == '42,000원' and txt('m2') == '1건' and txt('m3') == '식비 100%'
    # 금액 없이 입력하면 안내
    click('#save'); time.sleep(.3)
    assert txt('entry-msg') == '금액을 넣어 주세요.'
    # ---- 소비형태 추가: 색을 골라야, 미리보기, 추가하면 바로 선택
    click('#cat-add')
    assert vis('addbox')
    typ('new-name', '반려동물'); click('#add-ok'); time.sleep(.3)
    assert txt('add-msg') == '색을 골라 주세요.'
    click('[data-add-color="#2BA7B8"]')
    assert '반려동물' in txt('new-preview')
    click('#add-ok'); time.sleep(1)
    assert js("return document.querySelector('#cats .chip.on').textContent.trim()") == '반려동물'
    typ('amount', '15000'); typ('memo', '사료')
    click('#save'); time.sleep(1.2)
    assert txt('m1') == '57,000원' and txt('m2') == '2건'
    # 원형 그래프: 소비형태가 둘이면 조각 둘, 범례에 비율
    assert js("return document.querySelectorAll('#donut path').length") == 2
    assert '74%' in txt('legend') and '26%' in txt('legend'), txt('legend')
    # ---- 색·이름 편집: 색 바꾸기
    click('#cat-edit')
    click('#cats [data-cat]')            # 식비
    assert js("return !!document.querySelector('[data-pop]')")
    click('[data-pop-color="#378ADD"]'); time.sleep(1)
    with storage._db() as conn:
        assert conn.execute("SELECT color FROM ledger_categories WHERE name = '식비'").fetchone()[0] == '#378ADD'
    click('#cat-edit'); time.sleep(.2)
    # ---- 최근 메모 드롭다운: 고르면 메모와 그 소비형태
    js("document.getElementById('memo').focus()"); time.sleep(.3)
    assert vis('memo-dd') and js("return [...document.querySelectorAll('#memo-dd .m')].map(e => e.textContent)") == ['사료', '이마트 장보기']
    js("document.querySelectorAll('#memo-dd [data-memo]')[1].dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
    assert js("return document.getElementById('memo').value") == '이마트 장보기'
    assert js("return document.querySelector('#cats .chip.on').textContent.trim()") == '식비'
    typ('memo', '')
    print('ENTRY OK')

    # ---- 내 기록 고치기·지우기
    click('#list [data-entry]')            # 가장 최근(사료 15,000원)
    assert vis('edit-row') and txt('entry-title') == '기록 고치기' and js("return document.getElementById('amount').value") == '15,000'
    typ('amount', '16000'); click('#save'); time.sleep(1.2)
    assert [x['amount'] for x in entries()] == [42000, 16000] and not vis('edit-row')
    click('#list [data-entry]')
    js("window.confirm = () => true"); click('#edit-delete'); time.sleep(1.2)
    assert [x['amount'] for x in entries()] == [42000]
    print('EDIT OK')

    # ---- 지은으로 로그인: 관리자 칸 없음, 남의 기록은 못 고침, 거르기
    js("localStorage.removeItem('admin_token')")
    click('#logout'); time.sleep(1)
    assert vis('auth') and 'ledger' in navs()             # 이 페이지에서는 보임
    typ('login-name', '지은'); typ('login-pw', 'pw12')
    js("document.getElementById('login-form').requestSubmit()"); time.sleep(2)
    assert vis('app') and not vis('admin') and '지은' in txt('who-me')
    assert not js("return document.querySelector('#list [data-entry]').classList.contains('mine')")
    click('#list [data-entry]'); time.sleep(.3)
    assert not vis('edit-row')
    typ('amount', '5600'); typ('memo', '스타벅스'); click('#cats [data-cat]:nth-child(2)')   # 카페
    click('#save'); time.sleep(1.2)
    assert txt('m2') == '2건'
    # 사람 거르기: 지은만
    jieun = js("return [...document.querySelectorAll('#people [data-who]')].find(b => b.textContent.includes('지은')).dataset.who")
    click(f'#people [data-who="{jieun}"]'); time.sleep(.3)
    assert txt('m1').startswith('5,600원') and '지은' in txt('m1-label') and txt('count') == '1건'
    click('#people [data-who="0"]')
    # 일별: 오늘 기록, 하루 앞으로 가면 없음
    click('#mode-day'); time.sleep(.3)
    assert txt('m2') == '2건' and '이날' in txt('m1-label')
    click('#prev'); time.sleep(1)
    assert txt('m2') == '0건' and '기록이 없어요' in txt('list')
    click('#mode-month'); time.sleep(.3)
    # 다른 페이지 메뉴에도 가계부 (이 기기는 가계부에 로그인)
    d.get(BASE + '/'); time.sleep(1)
    assert 'ledger' in navs() and 'card' not in navs()
    print('MEMBER OK')

    # ---- 휴대폰: 넘침 없음
    d.set_window_size(390, 844); time.sleep(.3)
    d.get(BASE + '/ledger/'); time.sleep(2)
    assert vis('app') and js("return document.documentElement.scrollWidth <= innerWidth + 1")
    # 스크립트 오류 없음 (로그인 전 401·허락 전 403 같은 응답 코드 기록은 정상)
    logs = d.get_log('browser')
    assert not [m for m in logs if m['level'] == 'SEVERE' and 'Failed to load resource' not in m['message']], logs
    print('LEDGER UI OK')
finally:
    d.quit()
    srv.shutdown()
