"""YeYe홈 홈 화면(/yeye/): 인사 · 카드(오늘 근무·이번 달 지출·확인할 결제·최근 내역) → 카드 순서 바꾸기(이 기기에 저장, 바꾸는 중엔 눌러도 이동 안 함)
→ 아래 메뉴(홈·설정, 설정 = 전체 설정) → 휴대폰 넘침 없음"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, time
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LEDGER_ADMIN_NAME='임기범')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, ledger
from datetime import date
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
vis = lambda i: js(f"const e = document.getElementById('{i}'); return !!e && !e.hidden && e.offsetHeight > 0")
txt = lambda i: js(f"return document.getElementById('{i}').textContent.replace(/\\s+/g, ' ').trim()")
click = lambda sel: js("document.querySelector(arguments[0]).click()", sel)
order = lambda: js("return [...document.querySelectorAll('#cards [data-card]')].filter(c => !c.hidden).map(c => c.dataset.card)")
try:
    # 관리자 기기로 로그인, 기록 하나·확인할 결제 하나
    d.get(BASE + '/yeye/'); time.sleep(2)
    assert vis('auth') and not vis('hnav')                              # 로그인 전엔 아래 메뉴 없음
    js("localStorage.setItem('admin_token', arguments[0])", web_server.ADMIN_TOKEN)
    ledger.state(date.today().strftime('%Y-%m'))
    with storage._db() as conn:
        admin = dict(conn.execute("SELECT * FROM ledger_users WHERE is_admin = 1").fetchone())
        cafe = conn.execute("SELECT id FROM ledger_categories WHERE name = '카페'").fetchone()[0]
    user = {'id': admin['id'], 'name': admin['name'], 'admin': True}
    ledger.add_entry(user, 5600, date.today().isoformat(), cafe, '스타벅스')
    d.get(BASE + '/yeye/'); time.sleep(2)
    # 인사 · 카드 (확인할 결제가 없으면 그 카드는 숨김) · 아래 메뉴
    assert vis('app') and '안녕하세요, 임기범님' in txt('greet-name') and txt('greet-date').endswith('요일')
    assert order() == ['duty', 'spend', 'recent'], order()
    assert txt('ledger-body').startswith('5,600원') and '☕' in txt('recent-body') and '스타벅스' in txt('recent-body')
    assert vis('hnav') and [b.strip() for b in js("return [...document.querySelectorAll('#hnav [data-hv]')].map(b => b.textContent)")] == ['홈', '설정']
    assert js("return document.querySelector('#hnav .on').dataset.hv") == 'home'
    assert not js("return !!document.getElementById('set-open')")      # 위의 '전체 설정' 단추는 없음 (아래 메뉴로)
    # 브라우저(PC)에서는 다른 페이지처럼 제목 줄·사이트 메뉴, 메뉴에 'YeYe홈'(지금 페이지), 가계부에서도 메뉴로 옴
    navs = lambda: js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)")
    assert js("return document.querySelector('.site-top').offsetHeight > 0") and 'yeye' in navs() and navs().index('yeye') < navs().index('ledger')
    d.get(BASE + '/ledger/'); time.sleep(2)
    js("document.querySelector('.site-nav [data-nav=\"yeye\"]').click()"); time.sleep(2)
    assert js("return location.pathname") == '/yeye/' and vis('app')
    key = ledger.create_hook_key(user)
    ledger.receive_hook_detail(key, f'[삼성카드] {date.today().month}/{date.today().day} 12:30 13,000원 일시불 블루보틀 성수점')
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    assert order() == ['duty', 'spend', 'inbox', 'recent'] and txt('inbox-n') == '1'
    # ---- 카드 순서 바꾸기: 바꾸는 중엔 카드 이름과 ⋮⋮만, 눌러도 이동 안 함, 끌어 옮기면 이 기기에 저장
    click('#order-btn'); time.sleep(.2)
    assert vis('order-bar') and not vis('order-btn') and not vis('duty-body') and js("return getComputedStyle(document.querySelector('#duty-card .drag')).display") != 'none'
    click('#ledger-card'); time.sleep(.3)
    assert js("return location.pathname") == '/yeye/'
    js("window.homeMoveCard('inbox', 0)")
    assert order() == ['inbox', 'duty', 'spend', 'recent'] and js("return localStorage.getItem('home_cards')") == 'inbox,duty,spend,recent'
    click('#order-done'); time.sleep(.2)
    assert not vis('order-bar') and vis('order-btn') and vis('duty-body')
    d.refresh(); time.sleep(2)
    assert order() == ['inbox', 'duty', 'spend', 'recent'], order()     # 다시 열어도 그 순서
    # 앱의 뒤로가기: 순서 바꾸는 중이면 그것부터 끝냄
    click('#order-btn'); time.sleep(.2)
    assert js('return window.ledgerBack()') is True and not vis('order-bar')
    assert js('return window.ledgerBack()') is False
    # ---- 아래 메뉴 '설정' → 전체 설정 (앱 파일·로그인), '홈' → 카드
    click('#hnav [data-hv="set"]'); time.sleep(.4)
    assert vis('set-view') and not vis('app') and vis('hnav') and js("return location.hash") == '#settings'
    assert js("return document.querySelector('#hnav .on').dataset.hv") == 'set' and '임기범 (관리자)' in txt('who')
    click('#hnav [data-hv="home"]'); time.sleep(.5)
    assert not vis('set-view') and vis('app') and js("return location.hash") == ''
    # 카드를 누르면 그 페이지로
    click('#inbox-card'); time.sleep(1.2)
    assert js("return location.pathname + location.hash") == '/ledger/#inbox' or js("return location.pathname") == '/ledger/'
    # ---- 앱 안 (YeYe홈 1.11, window.LedgerApp 흉내): 설정에 이 휴대폰 앱·결제 알림(권한·금액 인식 알림·무시할 알림), 줄을 누르면 앱 화면
    d.get(BASE + '/stats/'); time.sleep(.5)
    d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': "window.__calls = []; window.LedgerApp = {version: () => '1.11', connected: () => true, "
        "phoneState: () => JSON.stringify({access: true, battery: false, alertOn: true, ignores: 3, connected: true}), setAlertOn: v => window.__calls.push('alert:' + v), "
        "openPhoneSettings: () => window.__calls.push('phone'), checkUpdate: () => {}, updateText: () => ''};"})
    d.get(BASE + '/yeye/#settings'); time.sleep(2)
    assert not js("return document.querySelector('.site-top').offsetHeight > 0")   # 앱 안: 제목 줄·사이트 메뉴 숨김 (앱의 위쪽 탭)
    assert vis('phone-card') and vis('notify-card') and 'YeYe홈 1.11' in txt('phone-state'), txt('phone-state')
    assert '켜짐' in txt('ph-access-s') and '배터리 절약' in txt('ph-access-s') and js("return document.getElementById('ph-alert').checked") and txt('ph-ignore-n') == '3'
    assert '연결됨' in txt('ph-link-s')
    click('#ph-alert'); click('#ph-ignore'); time.sleep(.2)
    assert js("return window.__calls") == ['alert:false', 'phone'], js("return window.__calls")   # 예전 앱(1.12까지): 전체 화면
    # 1.13부터: 줄마다 그 칸만 보이는 화면
    js("window.LedgerApp.openPhoneSection = s => window.__calls.push('sec:' + s); window.__calls = []")
    for r in ('access', 'link', 'ignore', 'apps', 'logs'): click('#ph-' + r)
    time.sleep(.2)
    assert js("return window.__calls") == ['sec:access', 'sec:link', 'sec:ignore', 'sec:apps', 'sec:logs'], js("return window.__calls")
    # ---- 휴대폰: 넘침 없음, 아래 메뉴는 맨 아래
    d.set_window_size(390, 844); d.get(BASE + '/yeye/'); time.sleep(2)
    assert js("return document.documentElement.scrollWidth <= innerWidth + 1")
    assert js("const r = document.getElementById('hnav').getBoundingClientRect(); return Math.round(r.bottom) === innerHeight")
    logs = d.get_log('browser')
    assert not [m for m in logs if m['level'] == 'SEVERE' and 'Failed to load resource' not in m['message']], logs
    print('YEYE HOME OK')
finally:
    d.quit()
    srv.shutdown()
