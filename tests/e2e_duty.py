"""근무표 화면(/duty/): 가계부 계정으로 로그인 → 사람 더하기 → 근무 골라 날짜 누르기(바로 저장, 다시 누르면 지움, 되돌리기)
→ 오늘·내일 카드, 달별 개수 → 다른 멤버도 고치고 '최근 고친 것'에 이름 → 설정에서 근무 종류 더하기·바꾸기, 사람 이름 바꾸기
→ 뒤로가기(window.ledgerBack) → 휴대폰 폭에서 넘침 없음"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, threading, socket, time
from datetime import date, timedelta
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
TODAY = date.today()
T, TM = TODAY.isoformat(), (TODAY + timedelta(days=1)).isoformat()
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shots')

ledger.signup('지은', 'pw1234')
ledger.approve(next(p['id'] for p in ledger.people()['pending'] if p['name'] == '지은'))

o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
vis = lambda i: js(f"const e = document.getElementById('{i}'); return !!e && !e.hidden && e.offsetHeight > 0")
txt = lambda i: js(f"return document.getElementById('{i}').textContent.replace(/\\s+/g, ' ').trim()")
def typ(i, v):
    js("const e = document.getElementById(arguments[0]); e.value = arguments[1]; e.dispatchEvent(new Event('input', {bubbles: true}))", i, v)
def click(sel):
    js("document.querySelector(arguments[0]).click()", sel)
def days():
    with storage._db() as conn:
        return {r['day']: r['code'] for r in conn.execute("SELECT d.day, t.code FROM duty_days d JOIN duty_types t ON t.id = d.type_id")}
def brush(code):
    js("[...document.querySelectorAll('#brush [data-brush]')].find(b => b.textContent === arguments[0]).click()", code)
cell = lambda day: f'#cal [data-day="{day}"]'
try:
    # ---- 로그인 화면 → 지은으로 로그인
    d.get(BASE + '/duty/'); time.sleep(1.2)
    assert vis('auth') and not vis('app')
    js("document.getElementById('login-form').requestSubmit()"); time.sleep(.3)
    assert '넣어 주세요' in txt('auth-msg')
    typ('login-name', '지은'); typ('login-pw', 'pw1234')
    js("document.getElementById('login-form').requestSubmit()"); time.sleep(1.2)
    assert vis('app') and txt('who-me') == '지은' and vis('no-person') and not vis('roster')
    assert 'duty' in js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)")
    # 머리줄에 '전체 설정' 없음 (홈의 아래 메뉴 '설정'으로). 아래 메뉴: 달력·고친 기록·설정 (맨 아래 고정)
    assert not js("return !!document.getElementById('all-set')")
    assert vis('dnav') and [b.strip() for b in js("return [...document.querySelectorAll('#dnav [data-dv]')].map(b => b.textContent)")] == ['달력', '고친 기록', '설정']
    assert js("const r = document.getElementById('dnav').getBoundingClientRect(); return Math.round(r.bottom) === innerHeight")
    assert js("return document.querySelector('#dnav .on').dataset.dv") == 'cal' and not vis('edit-fab')   # 사람이 없으면 ✎ 없음

    # ---- 사람 더하기 (빈 이름은 막음)
    click('#first-person'); time.sleep(.2)
    assert vis('add-person') and not vis('no-person') and js("return document.activeElement.id") == 'ap-name'
    click('#ap-save'); time.sleep(.3)
    assert '이름을' in txt('ap-msg')
    typ('ap-name', '예예'); click('#ap-save'); time.sleep(1)
    assert vis('roster') and txt('people').startswith('예예') and '아직 안 넣었어요' in txt('today')
    # 보여줄 사람 칩은 오늘 아래·달력 바로 위, '＋ 사람'의 이름 칸은 칩 바로 아래
    assert js("return document.getElementById('today').nextElementSibling.id") == 'people'
    assert js("return document.getElementById('people').nextElementSibling.id") == 'add-person'
    assert js("const p = document.getElementById('people').getBoundingClientRect(), t = document.getElementById('today').getBoundingClientRect(), c = document.getElementById('cal-sec').getBoundingClientRect(); return t.bottom <= p.top && p.bottom <= c.top")
    click('[data-add-person]'); time.sleep(.2)
    assert vis('add-person') and js("return document.getElementById('people').nextElementSibling.id") == 'add-person'
    click('#ap-cancel'); time.sleep(.2)
    assert js("return document.querySelectorAll('#cal [data-day]').length") == int((date(TODAY.year + TODAY.month // 12, TODAY.month % 12 + 1, 1) - timedelta(days=1)).day)
    assert js(f"return document.querySelector('{cell(T)}').classList.contains('today')")

    # ---- 평소엔 보기만: 날짜를 눌러도 안 바뀌고 근무 고르기 줄도 없음 → 오른쪽 아래 ✎
    fab = lambda: js("return document.getElementById('edit-fab').getAttribute('aria-label')")
    assert not vis('brush-sec') and vis('edit-fab') and fab() == '고치기' and js("return !!document.querySelector('#edit-fab svg')")
    # 아이콘은 단추 정가운데 (글자 기준선 때문에 처지지 않게)
    assert js("const b = document.getElementById('edit-fab').getBoundingClientRect(), i = document.querySelector('#edit-fab svg').getBoundingClientRect();"
              "return Math.abs((b.top + b.bottom) / 2 - (i.top + i.bottom) / 2) < 1 && Math.abs((b.left + b.right) / 2 - (i.left + i.right) / 2) < 1")
    click(cell(T)); time.sleep(.2)
    assert '연필 단추' in txt('cal-msg') and days() == {}
    click('#edit-fab'); time.sleep(.2)
    assert vis('brush-sec') and fab() == '고치기 끝' and txt('edit-btn') == '완료' and '고치는 중 · 예예' in txt('edit-label')
    assert js("return document.getElementById('cal-sec').classList.contains('editing')")
    # 근무를 안 고르고 날짜를 누르면 안내, 고르면 바로 들어가고 잠깐 뒤 저장
    click(cell(T)); time.sleep(.2)
    assert '먼저 골라' in txt('cal-msg') and days() == {}
    brush('E'); time.sleep(.1)
    assert '이브닝' in txt('brush-hint')
    click(cell(T)); time.sleep(.1)
    assert js(f"return document.querySelector('{cell(T)} .badge').textContent") == 'E' and '이브닝' in txt('today')
    if TM.startswith(T[:7]):
        brush('N'); click(cell(TM))
    time.sleep(1.5)
    want = {T: 'E', **({TM: 'N'} if TM.startswith(T[:7]) else {})}
    assert days() == want, days()
    assert txt('counts').startswith('이브닝1'), txt('counts')
    # 아래 메뉴 '고친 기록': 달력·✎ 대신 고친 기록 (고치는 중이면 끝냄), '달력'으로 돌아옴
    assert not vis('changes-sec')
    click('#dnav [data-dv="history"]'); time.sleep(.3)
    assert vis('changes-sec') and '지은' in txt('changes') and not vis('cal-sec') and not vis('edit-fab') and not vis('brush-sec')
    click('#dnav [data-dv="cal"]'); time.sleep(.3)
    assert vis('cal-sec') and not vis('changes-sec') and not vis('brush-sec')
    click('#edit-fab'); time.sleep(.2)
    # 같은 근무로 다시 누르면 지움, 되돌리기로 되살림
    brush('E'); click(cell(T)); time.sleep(1.2)
    assert T not in days() and vis('undo')
    click('#undo'); time.sleep(1.2)
    assert days().get(T) == 'E'

    # ---- 다른 멤버(관리자 기기)도 고치고, 지은 화면에는 다시 열면 반영 + 누가 고쳤는지
    d2 = Chrome(options=o)
    d2.get(BASE + '/stats/'); time.sleep(.6)
    d2.execute_script("localStorage.setItem('admin_token', arguments[0])", web_server.ADMIN_TOKEN)
    d2.get(BASE + '/duty/'); time.sleep(1.5)
    assert d2.execute_script("return document.getElementById('who-me').textContent") == '임기범'
    d2.execute_script("document.getElementById('edit-btn').click()")
    d2.execute_script("[...document.querySelectorAll('#brush [data-brush]')].find(b => b.textContent === 'OFF').click()")
    d2.execute_script(f"document.querySelector('{cell(T)}').click()"); time.sleep(1.5)
    d2.quit()
    assert days().get(T) == 'OFF'
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1)
    assert js(f"return document.querySelector('{cell(T)} .badge').textContent") == 'OFF' and '임기범' in txt('changes')   # (숨은 '고친 기록'에도)

    # ---- 달 넘기기
    click('#next'); time.sleep(.8)
    assert not js(f"return !!document.querySelector('{cell(T)}')")
    click('#month-label'); time.sleep(.8)
    assert js(f"return !!document.querySelector('{cell(T)}')")

    # ---- 휴대폰 폭: 넘침 없음, 스크린샷
    d.set_window_size(400, 900); time.sleep(.5)
    assert js("return document.documentElement.scrollWidth <= window.innerWidth")
    os.makedirs(SHOTS, exist_ok=True)
    assert js("const r = document.getElementById('logout').getBoundingClientRect(); return r.right <= window.innerWidth")   # 머리줄 버튼이 화면 안에
    d.save_screenshot(os.path.join(SHOTS, 'duty_mobile.png'))
    d.set_window_size(1280, 900); time.sleep(.4)

    # ---- 설정: 근무 종류 더하기 (글자 없으면 거절), 바꾸기, 사람 이름 바꾸기
    click('#dnav [data-dv="set"]'); time.sleep(.5)                      # 아래 메뉴 '설정'
    assert vis('set-view') and not vis('main-view') and js("return location.hash") == '#settings' and vis('dnav')
    assert js("return document.querySelector('#dnav .on').dataset.dv") == 'set'
    # 근무 종류: 줄마다 저장 없이 고친 것을 모아 '모두 저장' 한 번 (고친 줄은 노랗게)
    def tset(row, f, v):   # row: 줄 번호(-1은 마지막), 칸에 치기
        js("const r = [...document.querySelectorAll('#types .trow')].at(arguments[0]), i = r.querySelector(`[data-f=${arguments[1]}]`);"
           "i.value = arguments[2]; i.dispatchEvent(new Event('input', {bubbles: true}))", row, f, v)
    def types_db():
        with storage._db() as conn:
            return {r['code']: dict(r) for r in conn.execute("SELECT code, name, start_time, end_time FROM duty_types")}
    assert txt('type-save') == '바뀐 것 없음' and not js("return [...document.querySelectorAll('#types [data-type-save]')].length")
    click('#type-add'); time.sleep(.2)
    assert txt('type-save') == '모두 저장 (1개 바뀜)' and js("return document.querySelector('#types .trow:last-child').classList.contains('changed')")
    click('#type-save'); time.sleep(.6)                                   # 글자가 없는 줄 → 아무것도 안 바뀌고 그 줄이 빨갛게
    assert '짧은 글자' in txt('type-msg') and js("return document.querySelector('#types .trow:last-child').classList.contains('bad')")
    before = types_db()
    tset(-1, 'code', '교육'); tset(-1, 'name', '교육'); tset(-1, 'start_time', '09:00'); tset(-1, 'end_time', '18:00')
    tset(0, 'name', '데이 근무')                                           # 다른 줄도 함께
    assert txt('type-save') == '모두 저장 (2개 바뀜)'
    assert types_db() == before                                          # 저장 전엔 그대로
    click('#type-save'); time.sleep(1.2)
    db = types_db()
    assert '저장했어요' in txt('type-msg') and db['교육']['start_time'] == '09:00' and db['교육']['end_time'] == '18:00' and db['D']['name'] == '데이 근무', db
    assert txt('type-save') == '바뀐 것 없음' and not js("return !!document.querySelector('#types .trow.changed')")
    # 글자가 겹치면 거절 (아무것도 안 바뀜)
    tset(0, 'code', 'E'); click('#type-save'); time.sleep(.6)
    assert '겹쳐요' in txt('type-msg') and types_db() == db
    # 쓰인 종류(OFF)는 못 지움 (✕는 확인 후 바로), 고치던 다른 줄은 그대로
    js("window.confirm = () => true")
    js("[...document.querySelectorAll('#types .trow')].find(r => r.querySelector('[data-f=code]').value === 'OFF').querySelector('[data-type-del]').click()"); time.sleep(.6)
    assert '지울 수 없어요' in txt('type-msg') and js("return document.querySelector('#types .trow [data-f=code]').value") == 'E'
    # 저장하지 않고 나가려 하면 물음 (취소하면 그대로, 버리면 원래대로)
    js("window.confirm = () => false"); click('#set-back'); time.sleep(.3)
    assert vis('set-view')
    js("window.confirm = () => true"); click('#set-back'); time.sleep(.6)
    assert not vis('set-view') and types_db() == db
    click('#dnav [data-dv="set"]'); time.sleep(.5)
    assert js("return document.querySelector('#types .trow [data-f=code]').value") == 'D' and txt('type-save') == '바뀐 것 없음'
    js("const r = document.querySelector('[data-pe]'); r.querySelector('input').value = '예예쌤'; r.querySelector('[data-pe-save]').click()"); time.sleep(1)
    assert '바꿨어요' in txt('pe-msg')
    d.save_screenshot(os.path.join(SHOTS, 'duty_settings.png'))
    # 휴대폰 설정 화면: 시간 칸이 서로 겹치지 않음 (글자·이름 / 시간 / 색 / 버튼 줄)
    d.set_window_size(400, 900); time.sleep(.5)
    boxes = js("return [...document.querySelectorAll('#types .trow')][0].querySelectorAll('input[type=time]').length ? [...[...document.querySelectorAll('#types .trow')][0].querySelectorAll('input[type=time]')].map(i => { const r = i.getBoundingClientRect(); return [r.left, r.right, r.top]; }) : []")
    assert len(boxes) == 2 and boxes[0][1] <= boxes[1][0] and boxes[0][2] == boxes[1][2], boxes
    assert js("return document.documentElement.scrollWidth <= window.innerWidth")
    d.save_screenshot(os.path.join(SHOTS, 'duty_settings_mobile.png'))
    d.set_window_size(1280, 900); time.sleep(.4)
    # ---- PC(마우스)의 시간 칸: 글자 칸 + 30분 간격 목록 (끝 시간엔 근무 길이), 숫자로 치기, ↑↓로 10분씩
    # (헤드리스 크롬은 손가락 기기로 나타나므로 마우스 PC로 흉내)
    pc = d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source':
        "const mm = window.matchMedia.bind(window); window.matchMedia = q => /pointer:\\s*coarse/.test(q) ? mm('(max-width: 0px)') : mm(q);"})
    d.refresh(); time.sleep(2)
    assert vis('set-view') and not js("return !!document.querySelector('#types input[type=time]')") and js("return document.querySelectorAll('#types .tinput').length") > 0
    S = "#types .trow:nth-child(2) [data-f=start_time]"; E = "#types .trow:nth-child(2) [data-f=end_time]"   # E 이브닝
    js(f"document.querySelector('{S}').focus()"); time.sleep(.2)
    assert js(f"return !document.querySelector('{S}').parentElement.querySelector('.tlist').hidden")
    assert js(f"return document.querySelectorAll('{S} ~ .tlist [data-time]').length") == 48
    js(f"const i = document.querySelector('{S}'); i.value = '1530'; i.dispatchEvent(new Event('input', {{bubbles: true}})); i.blur()"); time.sleep(.2)
    assert js(f"return document.querySelector('{S}').value") == '15:30'
    js(f"document.querySelector('{E}').focus()"); time.sleep(.2)
    labels = js(f"return [...document.querySelectorAll('{E} ~ .tlist [data-time]')].map(b => b.textContent)")
    assert '23:308시간' in labels, labels[44:]          # 시간 · 근무 길이
    js(f"document.querySelector('{E} ~ .tlist [data-time=\"23:30\"]').click()"); time.sleep(.2)
    assert js(f"return document.querySelector('{E}').value") == '23:30' and js(f"return document.querySelector('{E} ~ .tlist').hidden")
    js(f"const i = document.querySelector('{E}'); i.focus(); i.dispatchEvent(new KeyboardEvent('keydown', {{key: 'ArrowUp', bubbles: true}}))")
    assert js(f"return document.querySelector('{E}').value") == '23:40'
    js(f"const i = document.querySelector('{E}'); i.value = '25:00'; i.dispatchEvent(new Event('input', {{bubbles: true}})); i.blur()"); time.sleep(.2)
    assert js(f"return document.querySelector('{E}').classList.contains('bad')")   # 틀린 시간은 빨갛게
    js(f"const i = document.querySelector('{E}'); i.focus(); i.value = '7'; i.dispatchEvent(new Event('input', {{bubbles: true}})); i.blur()"); time.sleep(.2)
    assert js(f"return document.querySelector('{E}').value") == '07:00'
    click('#type-save'); time.sleep(1)
    assert types_db()['E']['start_time'] == '15:30' and types_db()['E']['end_time'] == '07:00'
    d.execute_cdp_cmd('Page.removeScriptToEvaluateOnNewDocument', {'identifier': pc['identifier']})
    d.refresh(); time.sleep(2)
    # 이 휴대폰 · 처음 보일 사람 (localStorage)
    js("const s = document.getElementById('home-person'); s.value = s.options[0].value; s.dispatchEvent(new Event('change'))")
    assert js("return localStorage.getItem('duty_home_person')") == js("return document.getElementById('home-person').options[0].value")
    # 뒤로가기: 설정 닫기 → 고치기 끝 → 닫을 것 없음
    assert js('return window.ledgerBack()') is True; time.sleep(.8)
    assert not vis('set-view') and txt('people').startswith('예예쌤') and '교육' in txt('brush')
    click('#edit-fab'); time.sleep(.2)                                  # (위에서 새로고침해 고치기가 끝났으므로 다시)
    brush('D')
    assert js('return window.ledgerBack()') is True and not vis('brush-sec') and txt('edit-btn') == '고치기'
    assert js('return window.ledgerBack()') is False
    # 앱의 다른 탭으로 가면(appTabHidden) 고치기 끝, 앱의 위쪽 '설정'(appOpenSettings)은 근무표 설정을 엶
    click('#edit-btn'); js('window.appTabHidden()')
    assert not vis('brush-sec')
    assert js('return window.appOpenSettings()') is True; time.sleep(.4)
    assert vis('set-view'); js('window.ledgerBack()'); time.sleep(.6)
    d.save_screenshot(os.path.join(SHOTS, 'duty_pc.png'))
    print('DUTY E2E OK')
finally:
    d.quit()
