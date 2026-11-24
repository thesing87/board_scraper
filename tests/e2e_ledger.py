"""가계부 화면(/ledger/): 가입 요청 → 허락 전 로그인 안내 → 관리자 기기는 자동 로그인·사용자 허락 →
메인(맨 위 요약 · 확인할 결제 · 내역/달력/분석 · 사람 칩) → ＋ 입력 창(금액·분류 아이콘·메모) → 분류 추가(색·아이콘)·색 바꾸기 →
메모 자동완성 → 일별(달력의 날짜)·월별·사람 거르기·원형 그래프 → 내 기록 고치기·지우기, 남의 기록은 못 고침 →
메뉴의 가계부는 로그인한 기기에만, 휴대폰 넘침 없음"""
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
# 헤드리스 크롬은 손가락 기기(pointer: coarse)로 나타나 PC 화면을 시험할 수 없음 → 마우스 PC로 (키패드 없음·금액 칸에 커서)
d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source':
    "const mm = window.matchMedia.bind(window); window.matchMedia = q => /pointer:\s*coarse/.test(q) ? mm('(max-width: 0px)') : mm(q);"})
js = d.execute_script
vis = lambda i: js(f"const e = document.getElementById('{i}'); return !!e && !e.hidden && e.offsetHeight > 0")
txt = lambda i: js(f"return document.getElementById('{i}').textContent.replace(/\\s+/g, ' ').trim()")
navs = lambda: js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)")
def typ(i, v):
    js("const e = document.getElementById(arguments[0]); e.value = arguments[1]; e.dispatchEvent(new Event('input', {bubbles: true}))", i, v)
def click(sel):
    js("document.querySelector(arguments[0]).click()", sel)
def tap(by, value):
    # 사람이 누르듯 (가운데로 스크롤해 위쪽 고정 메뉴에 가리지 않게)
    el = d.find_element(by, value)
    js("arguments[0].scrollIntoView({block: 'center'})", el); time.sleep(.1)
    el.click()
def open_all():
    # (예전: 접는 칸을 모두 펼침) 이제 접는 칸이 없음
    pass
def sheet():
    # 오른쪽 아래 ＋ → 입력 창
    click('#fab'); time.sleep(.3)
    assert vis('sheet-wrap') and vis('amount')
rows = lambda: js("return document.querySelectorAll('#list [data-entry]').length")
cat_names = lambda sel='#cats .chip .cn': js(f"return [...document.querySelectorAll('{sel}')].map(c => c.textContent.trim())")
def view(v):
    click(f'#views [data-view="{v}"]'); time.sleep(.2)
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
    # 메인에는 매일 쓰는 것만: 결제 알림 연결·사용자 허락·버린 알림 목록은 머리줄 '설정' 화면에 (처음엔 닫힘).
    assert vis('set-open') and not vis('set-view') and not vis('auto') and not vis('admin')
    # 순서: 맨 위 요약 → 보기(내역·달력·분석) → 거르기(사람 칩·지출/수입) → 내역. 입력 창은 ＋를 누를 때만
    order = js("return [...document.querySelectorAll('#hero, #views, #app .filter, #pane-list')].map(e => e.id || e.className)")
    assert order == ['hero', 'views', 'filter', 'pane-list'], order
    assert vis('fab') and not vis('sheet-wrap') and vis('pane-list') and not vis('totals') and not vis('pane-ana')
    assert txt('period') == f'{date.today().year}년 {date.today().month}월' and txt('m-ex-label') == '이번 달 지출'
    font = lambda sel: js(f"return getComputedStyle(document.querySelector('{sel}')).fontSize")
    assert font('body') == '14px' and font('.hero-amt') == '30px'      # PC
    # 보기: 달력·분석을 누르면 그 칸만
    view('cal'); assert vis('totals') and not vis('pane-list') and not vis('type-seg')
    view('ana'); assert vis('pane-ana') and not vis('totals')
    view('list'); assert vis('pane-list') and vis('type-seg')
    # ＋ → 입력 창: 날짜는 짧게 '11/23 (일)', ✕로 닫힘, PC는 키패드 없음(자판으로)
    sheet()
    import datetime as _dt
    _t = _dt.date.today()
    assert txt('used-on-show') == f"{_t.month}/{_t.day} ({'월화수목금토일'[_t.weekday()]})", txt('used-on-show')
    js("const i = document.getElementById('used-on'); i.value = '2025-12-31'; i.dispatchEvent(new Event('change', {bubbles: true}))")
    assert txt('used-on-show') == '25/12/31'
    js("const i = document.getElementById('used-on'); i.value = arguments[0]; i.dispatchEvent(new Event('input', {bubbles: true}))", _t.isoformat())
    assert not vis('keypad') and js("return document.activeElement.id") == 'amount', (vis('keypad'), js("return document.activeElement.id"))
    click('#entry-close'); time.sleep(.2)
    assert not vis('sheet-wrap')
    assert js("return document.querySelector('#who-me .av').textContent") == '임'      # 아이콘은 이름 첫 글자
    assert txt('set-dot') == '1' and not vis('admin')               # 허락을 기다리는 사람: 머리줄 '설정'에 숫자 점
    click('#set-open'); time.sleep(.3)                                  # → 설정, 사용자 허락 탭부터
    assert vis('set-view') and vis('admin') and txt('pending-count') == '1' and js("return location.hash") == '#settings'
    assert not vis('hero') and not vis('inbox-sec') and not vis('fab')   # 설정에서는 메인 칸이 숨음
    click('[data-admin="approve"]'); time.sleep(1)
    assert '기다리는 사람 없음' in txt('pending') and '지은' in txt('members') and not vis('set-dot')
    assert 'ledger' in navs()
    # 가계부 설정에는 앱 파일 탭이 없음 (전체 설정으로 옮김)
    assert not js("return !!document.querySelector('[data-tab=appfile]')")
    click('#set-back'); time.sleep(.5)                                  # ← 또는 뒤로가기로 메인
    assert not vis('set-view') and vis('set-open') and js("return location.hash") == ''
    # 앱 파일 올리기 (전체 설정 /yeye/#settings, 관리자): 고르기 전엔 버튼 꺼짐, APK가 아니면 거절, 올리면 받기 버튼
    d.get(BASE + '/yeye/#settings'); time.sleep(1.5)
    assert vis('set-view') and vis('app-up') and not vis('phone-card') and '임기범 (관리자)' in txt('who')
    assert '아직 올라간 앱이 없어요' in txt('app-state') and js("return document.getElementById('app-upload').disabled") and not vis('app-get')
    bad = os.path.join(tempfile.mkdtemp(), 'x.apk'); open(bad, 'wb').write(b'not apk')
    d.find_element('id', 'app-file').send_keys(bad); time.sleep(.2)
    click('#app-upload'); time.sleep(1)
    assert '(APK) 파일이 아니에요' in txt('app-msg'), txt('app-msg')
    d.find_element('id', 'app-file').send_keys(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'ledger-notify-1.0.apk')); time.sleep(.2)
    click('#app-upload'); time.sleep(1.5)
    assert '올렸어요: 1.0' in txt('app-msg') and '1.0 · 24KB' in txt('app-state') and '임기범' in txt('app-state'), txt('app-state')
    assert vis('app-get') and js("return document.getElementById('app-get').getAttribute('href')") == '/api/ledger/app.apk'
    click('#set-back'); time.sleep(.6)
    assert not vis('set-view') and vis('duty-card') and vis('ledger-card')
    # 가계부의 결제 알림 연결 칸(앱 밖)에는 받기 버튼만 그대로
    d.get(BASE + '/ledger/'); time.sleep(2); open_all()
    assert '1.0 · 24KB' in txt('app-info') and js("return document.getElementById('app-link').getAttribute('href')") == '/api/ledger/app.apk'
    print('ADMIN OK')

    # ---- 입력: 금액(쉼표), 분류(아이콘 + 이름), 메모. 저장하면 창이 닫힘
    sheet()
    assert cat_names()[:6] == ['식비', '카페', '교통', '생활', '쇼핑', '의료'], cat_names()
    assert [x.strip() for x in js("return [...document.querySelectorAll('#cats .chip .ci')].map(c => c.textContent)")][:3] == ['🍚', '☕', '🚌']   # 이름으로 짐작한 아이콘
    typ('amount', '42000')
    assert js("return document.getElementById('amount').value") == '42,000'
    typ('memo', '이마트 장보기')
    click('#save'); time.sleep(1.2)
    e = entries()
    assert len(e) == 1 and e[0]['amount'] == 42000 and e[0]['memo'] == '이마트 장보기' and e[0]['used_on'] == TODAY
    assert not vis('sheet-wrap')
    assert txt('m-ex') == '42,000원' and rows() == 1 and txt('m-in') == '0원' and txt('m-left') == '−42,000원'
    assert js("return document.getElementById('m-bar').style.width") == '100%'   # 수입 없이 지출만
    # 금액 없이 저장하면 안내
    sheet()
    click('#save'); time.sleep(.3)
    assert txt('entry-msg') == '금액을 넣어 주세요.' and vis('sheet-wrap')
    # ---- 분류 추가: 색을 골라야, 아이콘 고르기, 미리보기, 추가하면 바로 선택
    click('#cat-add')
    assert vis('addbox') and vis('add-icons')
    typ('new-name', '반려동물'); click('#add-ok'); time.sleep(.3)
    assert txt('add-msg') == '색을 골라 주세요.'
    click('[data-add-color="#2BA7B8"]')
    click('[data-add-icon="🐶"]')
    assert '반려동물' in txt('new-preview') and js("return document.querySelector('[data-add-icon=\"🐶\"]').classList.contains('on')")
    click('#add-ok'); time.sleep(1)
    assert js("return document.querySelector('#cats .chip.on .cn').textContent.trim()") == '반려동물'
    with storage._db() as conn:
        assert conn.execute("SELECT icon FROM ledger_categories WHERE name = '반려동물'").fetchone()[0] == '🐶'
    typ('amount', '15000'); typ('memo', '사료')
    click('#save'); time.sleep(1.2)
    assert txt('m-ex') == '57,000원' and rows() == 2
    # 원형 그래프: 소비형태가 둘이면 조각 둘, 범례에 비율
    assert js("return document.querySelectorAll('#donut path').length") == 2
    assert '74%' in txt('legend') and '26%' in txt('legend'), txt('legend')
    # ---- 편집: 색·아이콘 바꾸기
    sheet()
    click('#cat-edit')
    click('#cats [data-cat]')            # 식비
    assert js("return !!document.querySelector('[data-pop]')")
    click('[data-pop-color="#378ADD"]'); time.sleep(1)
    click('[data-pop-icon="🍺"]'); time.sleep(1)                # 창은 열린 채
    with storage._db() as conn:
        assert tuple(conn.execute("SELECT color, icon FROM ledger_categories WHERE name = '식비'").fetchone()) == ('#378ADD', '🍺')
    assert js("return document.querySelector('#cats [data-cat] .ci').textContent.trim()") == '🍺'
    click('#cat-edit'); time.sleep(.2)
    # ---- 최근 메모 드롭다운: 고르면 메모와 그 소비형태
    js("document.getElementById('memo').focus()"); time.sleep(.3)
    assert vis('memo-dd') and js("return [...document.querySelectorAll('#memo-dd .m')].map(e => e.textContent)") == ['사료', '이마트 장보기']
    js("document.querySelectorAll('#memo-dd [data-memo]')[1].dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
    assert js("return document.getElementById('memo').value") == '이마트 장보기'
    # 지출 입력의 메모도 치면 자동완성 (앞에서부터 맞는 것 먼저)
    js("const m = document.getElementById('memo'); m.value = '사'; m.dispatchEvent(new Event('input', {bubbles: true}))"); time.sleep(.2)
    assert js("return [...document.querySelectorAll('#memo-dd .m')].map(e => e.textContent)") == ['사료'], js("return document.getElementById('memo-dd').textContent")
    js("const m = document.getElementById('memo'); m.value = '이마트 장보기'; m.dispatchEvent(new Event('input', {bubbles: true}))")
    assert js("return document.querySelector('#cats .chip.on .cn').textContent.trim()") == '식비'
    typ('memo', '')
    print('ENTRY OK')

    # ---- 수입: 고르면 입력 칸이 파랗게, 수입 종류만, 요약·기록·분석에 수입
    click('#kind-income')
    assert js("return document.getElementById('entry').classList.contains('income')") and txt('entry-title') == '수입 입력'
    assert cat_names('#cats [data-cat] .cn') == ['급여', '부수입', '용돈', '이자·환급']
    js("document.getElementById('memo').focus()"); time.sleep(.3)
    assert not vis('memo-dd')                                   # 수입 쪽 메모는 아직 없음
    typ('amount', '3200000'); typ('memo', '11월 월급')
    click('#save'); time.sleep(1.2)
    assert txt('m-in') == '3,200,000원' and txt('m-ex') == '57,000원' and txt('m-left') == '3,143,000원'
    assert js("return document.getElementById('m-left').className") == '' and js("return document.getElementById('m-bar').style.width") == '2%'
    first = js("return document.querySelector('#list [data-entry]').textContent.replace(/\\s+/g, ' ')")
    assert '급여' in first and '+3,200,000원' in first, first
    assert '+3,143,000원' in txt('list')      # 날짜 머리줄: 그날 합계
    # 기록 거르기: 수입만
    click('#type-seg [data-type="income"]'); time.sleep(.3)
    assert rows() == 1 and txt('m-ex') == '57,000원'          # 요약은 그대로
    click('#type-seg [data-type="all"]')
    # 분석: 수입
    click('#ana-seg [data-ana="income"]'); time.sleep(.3)
    assert '급여' in txt('legend') and '100%' in txt('legend') and '식비' not in txt('legend')
    click('#ana-seg [data-ana="expense"]')
    # 수입 기록을 누르면 수입 쪽으로 고치기
    click('#kind-expense'); time.sleep(.2)
    click('#list [data-entry]'); time.sleep(.3)
    assert vis('sheet-wrap') and txt('entry-title') == '기록 고치기' and js("return document.getElementById('entry').classList.contains('income')")
    click('#edit-cancel'); time.sleep(.2)
    assert not vis('sheet-wrap')
    click('#kind-expense'); time.sleep(.2)
    # 기록 줄: 분류 아이콘 · 메모가 첫 줄(크게), 분류·이름은 아래 작은 줄, 날짜 머리줄은 '24일 월요일'과 그날 합계
    row = js("const b = [...document.querySelectorAll('#list [data-entry]')].find(x => x.textContent.includes('사료')); return [b.querySelector('.memo').textContent.trim(), b.querySelector('.line2 .who-tag').textContent.trim(), b.querySelector('.memo').offsetTop < b.querySelector('.line2').offsetTop, parseFloat(getComputedStyle(b.querySelector('.memo')).fontSize) > parseFloat(getComputedStyle(b.querySelector('.who-tag')).fontSize)]")
    assert row == ['사료', '임임기범', True, True], row
    head = js("return document.querySelector('#list .dayh').textContent.replace(/\\s+/g, ' ').trim()")
    assert head == f"{_t.day}일 {'월화수목금토일'[_t.weekday()]}요일+3,143,000원", head
    assert js("return [...document.querySelectorAll('#list .it .ci')].length") == rows()
    # 합계(일별 달력): 오늘 칸에 수입·지출, 누르면 그날 기록만, 다시 누르면 이 달
    cell = js(f"return document.querySelector('#cal [data-day=\"{TODAY}\"]').textContent.replace(/\\s+/g, ' ').trim()")
    assert '+320만' in cell and '−5.7만' in cell, cell
    view('cal')
    click(f'#cal [data-day="{TODAY}"]'); time.sleep(.3)      # 그날 내역으로
    assert '이날' in txt('m-ex-label') and js(f"return document.querySelector('#cal [data-day=\"{TODAY}\"]').classList.contains('sel')")
    assert vis('pane-list') and txt('period').startswith(f'{_t.month}월 {_t.day}일 (')
    click('#period'); time.sleep(.3)                          # 기간을 누르면 이 달 전체
    assert '이번 달' in txt('m-ex-label')
    # 합계(월별): 올해 수입·지출·합계, 달마다 표, 달을 누르면 그 달로
    view('cal')
    click('#tot-seg [data-tot="month"]'); time.sleep(1.2)
    assert vis('tot-month') and not vis('tot-day') and txt('y-in') == '+3,200,000원' and txt('y-ex') == '−57,000원'
    month_no = int(TODAY[5:7])
    assert js(f"return document.querySelector('#mtable tr.cur').textContent.replace(/\\s+/g, ' ').trim()").startswith(f'{month_no}월'), txt('mtable')
    assert '+3,143,000원' in js("return document.querySelector('#mtable tr.sum').textContent")
    click('#y-prev'); time.sleep(1)
    assert txt('y-in') == '+0원' and '–' not in txt('y-label')
    click('#y-next'); time.sleep(1)
    js("document.querySelector('#mtable tr.cur').click()"); time.sleep(1)
    assert vis('tot-day') and '이번 달' in txt('m-ex-label')
    view('list')
    print('INCOME OK')

    # ---- 내 기록 고치기·지우기
    pick = "[...document.querySelectorAll('#list [data-entry]')].find(b => b.textContent.includes('사료')).click()"
    js(pick)                               # 사료 15,000원 → 고치기 창
    assert vis('sheet-wrap') and vis('edit-row') and txt('entry-title') == '기록 고치기' and js("return document.getElementById('amount').value") == '15,000'
    typ('amount', '16000'); click('#save'); time.sleep(1.2)
    assert [x['amount'] for x in entries()] == [42000, 16000, 3200000] and not vis('sheet-wrap')
    # 줄의 '지우기'(휴대폰에서 왼쪽으로 밀면 나옴): 확인 창에서 취소하면 그대로
    js("window.confirm = () => false")
    js("[...document.querySelectorAll('#list [data-del]')].find(b => b.parentElement.textContent.includes('사료')).click()"); time.sleep(.5)
    assert len(entries()) == 3
    js(pick)
    # 지우기 확인 창에 지울 기록 내용 (날짜·메모·소비형태·금액·쓴 사람), 취소하면 그대로
    js("window.__asked = []; window.confirm = m => { window.__asked.push(m); return false; }"); click('#edit-delete'); time.sleep(.5)
    asked = js("return window.__asked[0]")
    assert asked.startswith('이 기록을 지울까요?') and '사료' in asked and '−16,000원' in asked and '되돌릴 수 없어요' in asked, asked
    assert len(entries()) == 3
    js("window.confirm = () => true"); click('#edit-delete'); time.sleep(1.2)
    assert [x['amount'] for x in entries()] == [42000, 3200000]
    print('EDIT OK')

    # ---- 지은으로 로그인: 관리자 칸 없음, 남의 기록은 못 고침, 거르기
    js("localStorage.removeItem('admin_token')")
    click('#logout'); time.sleep(1)
    assert vis('auth') and 'ledger' in navs()             # 이 페이지에서는 보임
    typ('login-name', '지은'); typ('login-pw', 'pw12')
    js("document.getElementById('login-form').requestSubmit()"); time.sleep(2)
    assert vis('app') and not vis('admin') and '지은' in txt('who-me')
    assert js("return document.querySelector('[data-tab=users]').hidden")   # 관리자 탭 없음
    assert not js("return document.querySelector('#list [data-entry]').classList.contains('mine')")
    click('#list [data-entry]'); time.sleep(.3)
    assert not vis('sheet-wrap') and not js("return !!document.querySelector('#list [data-del]')")   # 남의 기록: 고치기·지우기 없음
    typ('amount', '5600'); typ('memo', '스타벅스'); click('#cats [data-cat]:nth-child(2)')   # 카페
    click('#save'); time.sleep(1.2)
    assert rows() == 3
    # 사람 칩: 지은만 (칩이 검게), 요약도 지은 것
    assert [b.strip() for b in js("return [...document.querySelectorAll('#people [data-who]')].map(b => b.textContent)")] == ['전체', '임기범', '지은']
    jieun = js("return [...document.querySelectorAll('#people [data-who]')].find(b => b.textContent.includes('지은')).dataset.who")
    tap('css selector', f'#people [data-who="{jieun}"]'); time.sleep(.3)
    assert js(f"return document.querySelector('#people [data-who=\"{jieun}\"]').classList.contains('on')")
    assert txt('m-ex') == '5,600원' and '지은' in txt('m-ex-label') and rows() == 1
    click('#people [data-who="0"]'); time.sleep(.3)
    # 기록 칸은 쓴 사람의 색, 사람마다 다름
    colrows = js("return [...document.querySelectorAll('#list .it')].map(b => [b.textContent.includes('지은'), getComputedStyle(b).backgroundColor])")
    colors = {who: bg for who, bg in colrows}
    assert len(colors) == 2 and all(bg != 'rgba(0, 0, 0, 0)' for bg in colors.values()), colrows
    assert all(colors[who] == bg for who, bg in colrows), colrows
    assert not js("return document.querySelector('#list .list-sum')") and rows() == 3
    click('#type-seg [data-type="expense"]'); time.sleep(.3)
    click(f'#people [data-who="{jieun}"]'); time.sleep(.3)
    assert rows() == 1
    click('#people [data-who="0"]'); click('#type-seg [data-type="all"]'); time.sleep(.3)
    # 일별(달력의 날짜): 오늘 기록, 하루 앞으로 가면 없음, 기간을 누르면 이 달
    view('cal'); click(f'#cal [data-day="{TODAY}"]'); time.sleep(.3)
    t = date.today()
    assert txt('period').startswith(f'{t.month}월 {t.day}일 (') and rows() == 3 and '이날' in txt('m-ex-label')
    click('#prev'); time.sleep(1)
    assert rows() == 0 and '기록이 없어요' in txt('list')
    click('#period'); time.sleep(.3)
    # 다른 페이지 메뉴에도 가계부 (이 기기는 가계부에 로그인)
    d.get(BASE + '/'); time.sleep(1)
    assert 'ledger' in navs() and 'card' not in navs()
    print('MEMBER OK')

    # ---- 결제 알림 자동 기록: 연결 주소 만들기 → 알림 받기 → 대기함에서 분류 고르기 → 규칙 → 확정·취소
    d.get(BASE + '/ledger/'); time.sleep(2); open_all()
    assert not vis('inbox-sec') and '아직 연결 주소' in txt('hook-state')
    assert not js("return document.documentElement.classList.contains('in-app')")   # 브라우저에서는 앱 연결 버튼 없음
    # 관리자가 올린 앱을 받을 수 있음 (받기 버튼 → 같은 파일)
    assert js("return !document.getElementById('app-get').hidden") and not vis('admin')
    size = js("return fetch('/api/ledger/app.apk', {credentials: 'same-origin'}).then(r => r.status === 200 ? r.arrayBuffer() : null).then(b => b && b.byteLength)")
    assert size == os.path.getsize(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'ledger-notify-1.0.apk')), size
    click('#set-open'); time.sleep(.3)                                  # 설정 > 결제 알림 연결 (첫 탭)
    assert vis('auto') and not vis('admin')
    js("window.confirm = () => true")
    click('#hook-create'); time.sleep(1)
    url = js("return document.getElementById('hook-url').value")
    assert vis('hook-url-box') and url.startswith(BASE + '/api/ledger/hook/') and '한 번만' in txt('hook-state')
    click('#set-back'); time.sleep(.4)
    md = f'{date.today().month}/{date.today().day}'
    import urllib.request
    def send(text):
        with urllib.request.urlopen(urllib.request.Request(url, data=text.encode(), method='POST', headers={'Content-Type': 'text/plain'})) as r:
            return r.status
    assert send(f'[삼성카드] 지*님 {md} 12:41 4,800원 일시불 블루보틀 성수점') == 200
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    # 한 줄(가게·때·카드 / 금액 / ✓ / ✕), 분류가 없으면 줄 아래 분류 한 줄 (접힌 채로 바로 고름)
    assert vis('inbox-sec') and txt('inbox-count') == '1' and '블루보틀 성수점' in txt('inbox') and js("return !!document.querySelector('#inbox .ib-quick')")
    assert not js("return !!document.querySelector('#inbox .body')")
    # 기록·분류(state)가 대기함보다 늦게 와도 대기함 내용이 나옴 (알림을 눌러 앱을 열 때 자주 그럼)
    slow = d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source':
        "const f0 = window.fetch; window.fetch = (u, o) => String(u).includes('/api/ledger/state') ? new Promise(r => setTimeout(r, 1500)).then(() => f0(u, o)) : f0(u, o);"})
    d.refresh(); time.sleep(3.5)
    assert '블루보틀 성수점' in txt('inbox') and js("return document.querySelectorAll('#inbox [data-item]').length") == 1, txt('inbox')
    d.execute_cdp_cmd('Page.removeScriptToEvaluateOnNewDocument', {'identifier': slow['identifier']})
    d.refresh(); time.sleep(2); open_all()
    assert js("return document.querySelector('#inbox [data-ib-ok]').disabled")
    cafe = js("return [...document.querySelectorAll('#inbox [data-ib-cat]')].find(c => c.textContent.includes('카페')).dataset.ibCat")
    click(f'#inbox [data-ib-cat="{cafe}"]'); time.sleep(1)
    assert not js("return document.querySelector('#inbox [data-ib-ok]').disabled") and not js("return !!document.querySelector('#inbox .ib-quick')")
    assert '카페' in js("return document.querySelector('#inbox .ib-m small').textContent")
    click('#inbox [data-ib-toggle]'); time.sleep(.3)            # 줄을 누르면 펼쳐 고치기
    rule_btn = js("return document.querySelector('#inbox [data-ib-rule]').textContent")
    assert '"블루보틀"는 늘 카페' in rule_btn, rule_btn
    click('#inbox [data-ib-rule]'); time.sleep(1)
    assert '"블루보틀"이 든 가게' in txt('rules') and '규칙 "블루보틀" → 카페' in txt('inbox')
    # 늘 고치는 모드: 금액·가게·날짜 칸이 처음부터 열려 있음 ('고치기' 버튼 없음). 칸 이름은 항목마다 (ib-amount-<id>)
    iid = js("return document.querySelector('#inbox [data-item]').dataset.item")
    A, M, D = f'ib-amount-{iid}', f'ib-merchant-{iid}', f'ib-date-{iid}'
    DD = f'#inbox [data-item="{iid}"] .dd'
    assert vis(A) and vis(M) and vis(D) and not js("return !!document.querySelector('#inbox [data-ib-edit], #inbox [data-ib-save]')")
    def saved():
        with storage._db() as conn:
            r = conn.execute("SELECT amount, merchant, category_id FROM ledger_inbox WHERE id = ?", (int(iid),)).fetchone()
            return dict(r)
    # 가게·금액 칸의 X: 한 번에 지우고 그 칸에 커서, 빈 칸이면 X 숨김. 1분마다 대기함을 새로 그려도 친 값은 그대로
    shown = lambda i: js(f"return getComputedStyle(document.querySelector('[data-clear=\"{i}\"]')).display !== 'none'")
    assert shown(M) and shown(A)
    click(f'[data-clear="{M}"]')
    assert js(f"return document.getElementById('{M}').value") == '' and js("return document.activeElement.id") == M
    assert not shown(M) and shown(A)
    # 가게 칸을 비우면 '최근 메모', 치면 지난 메모 전체에서 자동완성 (맞는 글자는 노랗게), 고르면 가게 이름이 그 메모로 (바로 저장)
    dd = lambda: js(f"const d = document.querySelector('{DD}'); return d && !d.hidden ? [...d.querySelectorAll('[data-ibmemo] .m')].map(m => m.textContent) : null")
    assert dd() and '이마트 장보기' in dd() and '최근 메모' in js(f"return document.querySelector('{DD}').textContent"), dd()
    js(f"const i = document.getElementById('{M}'); i.value = '장 보'; i.dispatchEvent(new Event('input', {{bubbles: true}}))"); time.sleep(.2)
    assert dd() == ['이마트 장보기'], dd()                                                      # 띄어쓰기 무시
    js(f"const i = document.getElementById('{M}'); i.value = '이마'; i.dispatchEvent(new Event('input', {{bubbles: true}}))"); time.sleep(.2)
    assert dd()[0] == '이마트 장보기' and js(f"return document.querySelector('{DD} mark').textContent") == '이마', dd()
    js(f"document.querySelector('{DD} [data-ibmemo]').dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}))"); time.sleep(.8)
    assert js(f"return document.getElementById('{M}').value") == '이마트 장보기' and not dd() and saved()['merchant'] == '이마트 장보기'
    js(f"document.getElementById('{M}').value = ''")
    typ(M, '블루')
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    assert js(f"return document.getElementById('{M}').value") == '블루' and js("return document.activeElement.id") == M
    typ(M, '블루보틀 성수점')
    # PC는 한 줄 세 칸, 휴대폰은 윗줄 금액·날짜·아랫줄 가게 한 줄 전부
    box = lambda c: js(f"const r = document.querySelector('#inbox .{c}').getBoundingClientRect(); return [Math.round(r.top), Math.round(r.width)]")
    assert box('e-shop')[0] == box('e-amt')[0] == box('e-date')[0], (box('e-amt'), box('e-shop'), box('e-date'))
    d.set_window_size(400, 860); time.sleep(.5)
    # 휴대폰 폭: 가계부 안의 글자 1px 작게 (위쪽 사이트 메뉴는 그대로)
    font = lambda sel: js(f"return getComputedStyle(document.querySelector('{sel}')).fontSize")
    assert font('body') == '13px' and font('.hero-amt') == '29px', (font('body'), font('.hero-amt'))
    assert box('e-amt')[0] == box('e-date')[0] < box('e-shop')[0] and box('e-shop')[1] > 250, (box('e-amt'), box('e-shop'), box('e-date'))
    assert js("return document.documentElement.scrollWidth <= window.innerWidth")
    d.set_window_size(1280, 900); time.sleep(.5)
    # 칸을 벗어나면 바로 저장 (가게·금액)
    typ(A, '5300')
    js(f"['{M}', '{A}'].forEach(i => document.getElementById(i).dispatchEvent(new Event('change', {{bubbles: true}})))"); time.sleep(1.2)
    assert saved()['amount'] == 5300 and saved()['merchant'] == '블루보틀 성수점', saved()
    assert js(f"return document.getElementById('{A}').value") == '5,300'
    # 새 분류: 분류 칩 끝 '＋ 새 분류' → 이름·색 → 만들고 고르기 (이름·색이 없으면 못 만듦)
    click(f'#inbox [data-item="{iid}"] [data-nb-open]'); time.sleep(.2)
    assert vis('nb-name') and js("return document.activeElement.id") == 'nb-name'
    click('[data-nb-save]'); time.sleep(.3)
    assert '이름을 넣어 주세요' in txt('nb-msg')
    typ('nb-name', '생활용품')
    click('[data-nb-save]'); time.sleep(.3)
    assert '색을 골라 주세요' in txt('nb-msg')
    click('[data-nb-color]'); time.sleep(.2)
    assert txt('nb-name') == '' and js("return document.getElementById('nb-name').value") == '생활용품' and '생활용품' in txt('nb-prev')
    assert js('return window.ledgerBack()') is True and not js("return !!document.getElementById('nb-name')")   # 뒤로가기로 닫힘
    click(f'#inbox [data-item="{iid}"] [data-nb-open]'); time.sleep(.2)
    typ('nb-name', '생활용품'); click('[data-nb-color]'); click('[data-nb-save]'); time.sleep(1.8)
    with storage._db() as conn:
        newcat = conn.execute("SELECT id, kind FROM ledger_categories WHERE name = '생활용품'").fetchone()
    assert newcat and newcat['kind'] == 'expense' and saved()['category_id'] == newcat['id'], saved()
    assert not js("return !!document.getElementById('nb-name')") and js(f"return document.querySelector('#inbox [data-ib-cat=\"{newcat['id']}\"]').classList.contains('on')")
    assert '생활용품' in js("return [...document.querySelectorAll('#cats .chip')].map(c => c.textContent).join()")   # 지출 입력에도 바로
    # 확정: 고친 금액·가게와 새 분류로 기록
    before = len(entries())
    click('#inbox [data-ib-ok]'); time.sleep(1.5)
    assert not vis('inbox-sec') and len(entries()) == before + 1 and entries()[-1]['memo'] == '블루보틀 성수점' and entries()[-1]['amount'] == 5300 and entries()[-1]['category_id'] == newcat['id']
    assert '블루보틀 성수점' in txt('list')
    # 다음 알림은 규칙으로 바로 분류 → 모두 확정
    assert send(f'[삼성카드] {md} 15:00 6,100원 일시불 블루보틀 한남점') == 200
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    assert '카페' in txt('inbox') and not js("return document.querySelector('#inbox [data-ib-ok]').disabled")
    click('#inbox-all'); time.sleep(1.5)
    assert not vis('inbox-sec') and entries()[-1]['amount'] == 6100
    # 규칙이 없어도 같은 가게의 지난 기록('이마트 장보기' → 식비)으로 분류를 미리 골라 둠 → 바로 확정
    assert send(f'[삼성카드] {md} 18:20 7,700원 일시불 이마트 장보기') == 200
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    click('#inbox [data-ib-toggle]'); time.sleep(.3)
    assert "추천 식비 · '이마트 장보기'" in txt('inbox'), txt('inbox')
    assert js("return document.querySelector('#inbox .chip.on').textContent.trim()") == '식비'
    assert not js("return document.querySelector('#inbox [data-ib-ok]').disabled")
    click('#inbox [data-ib-ok]'); time.sleep(1.5)
    with storage._db() as conn:
        food = conn.execute("SELECT id FROM ledger_categories WHERE name = '식비'").fetchone()[0]
    assert not vis('inbox-sec') and entries()[-1]['amount'] == 7700 and entries()[-1]['category_id'] == food
    # 버리기 → 5초 '되돌리기' → 대기함으로, 다시 버리면 '버린 알림 1 ›' 목록에서 되살리기
    assert send(f'[삼성카드] {md} 18:40 3,300원 일시불 편의점') == 200
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    click('#inbox [data-ib-del]'); time.sleep(1)
    assert not vis('inbox-sec') and vis('undo') and '편의점 3,300원' in txt('undo-msg'), txt('undo-msg')
    click('#undo-btn'); time.sleep(1)
    assert vis('inbox-sec') and '편의점' in txt('inbox') and not vis('undo') and js("return document.getElementById('tab-trash-n').hidden")
    click('#inbox [data-ib-del]'); time.sleep(5.6)
    # 버린 알림은 메인에 보이지 않고 설정 > 버린 알림 탭에만 (탭에 개수)
    assert not vis('undo') and not js("return !!document.getElementById('trash-btn')") and txt('tab-trash-n') == '1' and not vis('trash-list')
    click('#set-open'); time.sleep(.3); click('[data-tab="trash"]'); time.sleep(.2)
    assert vis('set-view') and vis('trash-list') and '편의점' in txt('trash-list') and '버림' in txt('trash-list')
    assert not js("return !!document.querySelector('#trash-list [data-ignore]')")   # 앱 밖에서는 '이런 알림 안 받기' 없음
    click('#trash-list [data-restore]'); time.sleep(1)
    assert '버린 알림이 없어요' in txt('trash-list') and js("return document.getElementById('tab-trash-n').hidden")
    click('#set-back'); time.sleep(.4)
    assert vis('inbox-sec') and '편의점' in txt('inbox')
    click('#inbox [data-ib-del]'); time.sleep(1)
    # 취소 알림: 맞는 기록을 찾아 지움
    assert send(f'[삼성카드] 승인취소 6,100원 블루보틀 한남점 {md} 15:10') == 200
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    assert js("return document.querySelector('#inbox [data-ib-ok]').getAttribute('aria-label')") == '취소 확정'
    click('#inbox [data-ib-toggle]'); time.sleep(.3)
    assert '같은 결제를 찾았어요' in txt('inbox'), txt('inbox')
    n = len(entries())
    click('#inbox [data-ib-ok]'); time.sleep(1.5)
    assert len(entries()) == n - 1 and not vis('inbox-sec')
    # 시험 알림 → 버리기
    click('#hook-test'); time.sleep(1.2)
    assert vis('inbox-sec') and '1,000원' in txt('inbox') and '마지막으로 받은 알림' in txt('hook-state')
    click('#inbox [data-ib-del]'); time.sleep(1)
    assert not vis('inbox-sec')
    # ---- YeYe홈 앱 안에서 열었을 때 (앱이 넣는 window.LedgerApp 흉내): 앱 받기 안내는 숨고 '이 휴대폰 앱에 연결' → 새 연결 주소를 앱에 넣음
    d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': "window.__got = []; window.confirm = () => true; window.LedgerApp = {version: () => '1.2', connected: () => window.__got.length > 0, connect: u => { window.__got.push(u); return true; }, openSettings: () => {}, pickIgnore: t => { window.__ign = t; }};"})
    d.get(BASE + '/ledger/'); time.sleep(2); open_all()
    assert js("return document.documentElement.classList.contains('in-app')") and vis('app-hint')   # 연결 전: 메인에 한 줄 안내
    click('#app-hint-btn'); time.sleep(.3)                              # → 설정 > 결제 알림 연결
    assert vis('app-connect') and not vis('app-get') and '아직 연결되지' in txt('app-connect-state'), txt('app-connect-state')
    assert not js("const n = document.querySelector('.site-nav'); return !!n && n.offsetHeight > 0")   # 앱에서는 메뉴 줄(다른 탭) 없음
    click('#app-connect-btn'); time.sleep(1.2)
    got = js('return window.__got')
    assert len(got) == 1 and got[0].startswith(BASE + '/api/ledger/hook/'), got
    assert '이 휴대폰 앱(1.2)' in txt('app-connect-state') and txt('app-connect-btn') == '다시 연결' and js("return document.getElementById('app-hint').hidden")
    with urllib.request.urlopen(urllib.request.Request(got[0], data='[삼성카드] 승인 3,300원 앱연결'.encode(), method='POST', headers={'Content-Type': 'text/plain'})) as r:
        assert r.status == 200                                          # 앱에 넣은 새 주소로 받아짐
    # 버린 알림의 '이런 알림 안 받기' (앱 1.9 이상, pickIgnore가 있을 때만): 그 알림의 원래 글을 앱에 넘김
    click('[data-tab="trash"]'); time.sleep(.3)
    assert vis('trash-list') and js("return document.querySelectorAll('#trash-list [data-ignore]').length") >= 1, txt('trash-list')
    click('#trash-list [data-ignore]'); time.sleep(.3)
    ign = js('return window.__ign') or ''
    assert '원' in ign and len(ign) <= 300, ign
    # ---- 앱의 뒤로가기(window.ledgerBack): 설정이 열려 있으면 설정부터, 그다음 열린 것을 하나씩, 닫을 게 없으면 false
    assert vis('set-view') and js('return window.ledgerBack()') is True; time.sleep(.5)
    assert not vis('set-view') and js("return location.hash") == ''
    click('#cat-edit'); time.sleep(.2)
    assert js('return window.ledgerBack()') is True and txt('cat-edit') == '편집'          # 편집 모드 끝
    click('#fab'); time.sleep(.2)
    assert js('return window.ledgerBack()') is True and not vis('sheet-wrap')                # 입력 창 닫힘
    assert js('return window.ledgerBack()') is False
    print('AUTO OK')

    # ---- 휴대폰: 넘침 없음
    d.set_window_size(390, 844); time.sleep(.3)
    d.get(BASE + '/ledger/'); time.sleep(2); open_all()
    assert vis('app') and js("return document.documentElement.scrollWidth <= innerWidth + 1")
    click('#fab'); time.sleep(.3)
    assert js("return document.documentElement.scrollWidth <= innerWidth + 1")
    # 스크립트 오류 없음 (로그인 전 401·허락 전 403 같은 응답 코드 기록은 정상)
    logs = d.get_log('browser')
    assert not [m for m in logs if m['level'] == 'SEVERE' and 'Failed to load resource' not in m['message']], logs
    print('LEDGER UI OK')
finally:
    d.quit()
    srv.shutdown()
