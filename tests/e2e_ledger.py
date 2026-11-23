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
def tap(by, value):
    # 사람이 누르듯 (가운데로 스크롤해 위쪽 고정 메뉴에 가리지 않게)
    el = d.find_element(by, value)
    js("arguments[0].scrollIntoView({block: 'center'})", el); time.sleep(.1)
    el.click()
def open_all():
    # 지출 입력·분석과 달력·기록은 접는 칸이고 늘 접힌 채로 시작 → 시험에서는 모두 펼쳐 둠
    js("['entry', 'ana-fold', 'list-fold'].forEach(i => document.getElementById(i).open = true)")
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
    # 화면 맨 위는 결제 알림 자동 기록, 지출 입력·분석과 달력·기록은 접힌 채로 시작 (머리 줄은 보임)
    assert js("return document.querySelector('#app > details, #app > section').id") == 'auto'
    assert js("return ['entry', 'ana-fold', 'list-fold'].map(i => document.getElementById(i).open)") == [False, False, False]
    # 순서: 지출 입력 → 거르기 → 수입·지출·남은 돈·기록 칸 → 분석·달력 → 기록
    order = js("return [...document.querySelectorAll('#entry, #app .filter, #app .metrics, #ana-fold, #list-fold')].map(e => e.id || e.className)")
    assert order == ['entry', 'filter', 'metrics', 'ana-fold', 'list-fold'], order
    font = lambda sel: js(f"return getComputedStyle(document.querySelector('{sel}')).fontSize")
    assert font('body') == '14px' and font('.metric b') == '19px'      # PC는 그대로
    seen = lambda i: js(f"return document.getElementById('{i}').checkVisibility()")
    assert seen('entry-title') and not seen('amount') and not seen('list') and not seen('cal'), [seen(i) for i in ('entry-title', 'amount', 'list', 'cal')]
    click('#entry > summary'); time.sleep(.2)
    assert seen('amount')
    open_all()
    assert js("return document.querySelector('#who-me .av').textContent") == '임'      # 아이콘은 이름 첫 글자
    assert vis('admin') and txt('pending-count') == '1' and js("return document.getElementById('admin').open")
    click('[data-admin="approve"]'); time.sleep(1)
    assert '기다리는 사람 없음' in txt('pending') and '지은' in txt('members')
    assert 'ledger' in navs()
    # 앱 파일 올리기 (관리자 칸): 고르기 전엔 버튼 꺼짐, APK가 아니면 거절, 올리면 받기 버튼
    assert '아직 올린 앱이 없어요' in txt('app-admin-state') and js("return document.getElementById('app-upload').disabled")
    assert js("return document.getElementById('app-get').hidden && !document.getElementById('app-none').hidden")
    bad = os.path.join(tempfile.mkdtemp(), 'x.apk'); open(bad, 'wb').write(b'not apk')
    d.find_element('id', 'app-file').send_keys(bad); time.sleep(.2)
    click('#app-upload'); time.sleep(1)
    assert '(APK) 파일이 아니에요' in txt('app-msg'), txt('app-msg')
    d.find_element('id', 'app-file').send_keys(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'ledger-notify-1.0.apk')); time.sleep(.2)
    click('#app-upload'); time.sleep(1.5)
    assert '올렸어요: 1.0' in txt('app-msg') and '1.0 · 24KB' in txt('app-admin-state') and '임기범' in txt('app-admin-state'), txt('app-admin-state')
    assert '1.0 · 24KB' in txt('app-info') and js("return document.getElementById('app-link').getAttribute('href')") == '/api/ledger/app.apk'
    print('ADMIN OK')

    # ---- 입력: 금액(쉼표), 소비형태, 메모
    assert [c for c in js("return [...document.querySelectorAll('#cats .chip')].map(c => c.textContent.trim())")][:6] == ['식비', '카페', '교통', '생활', '쇼핑', '의료']
    typ('amount', '42000')
    assert js("return document.getElementById('amount').value") == '42,000'
    typ('memo', '이마트 장보기')
    click('#save'); time.sleep(1.2)
    e = entries()
    assert len(e) == 1 and e[0]['amount'] == 42000 and e[0]['memo'] == '이마트 장보기' and e[0]['used_on'] == TODAY
    assert txt('m-ex') == '−42,000원' and txt('m2') == '1건' and txt('m-in') == '+0원' and txt('m-left') == '−42,000원'
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
    assert txt('m-ex') == '−57,000원' and txt('m2') == '2건'
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

    # ---- 수입: 고르면 입력 칸이 파랗게, 수입 종류만, 요약·기록·분석에 수입
    click('#kind-income')
    assert js("return document.getElementById('entry').classList.contains('income')") and txt('entry-title') == '수입 입력'
    assert js("return [...document.querySelectorAll('#cats [data-cat]')].map(c => c.textContent.trim())") == ['급여', '부수입', '용돈', '이자·환급']
    js("document.getElementById('memo').focus()"); time.sleep(.3)
    assert not vis('memo-dd')                                   # 수입 쪽 메모는 아직 없음
    typ('amount', '3200000'); typ('memo', '11월 월급')
    click('#save'); time.sleep(1.2)
    assert txt('m-in') == '+3,200,000원' and txt('m-ex') == '−57,000원' and txt('m-left') == '3,143,000원'
    assert js("return document.getElementById('m-left').className") == 'plus'
    first = js("return document.querySelector('#list [data-entry]').textContent.replace(/\\s+/g, ' ')")
    assert '급여' in first and '수입' in first and '+3,200,000원' in first, first
    assert '+3,200,000원' in txt('list') and '−57,000원' in txt('list')      # 날짜 머리줄: 수입·지출
    # 기록 거르기: 수입만
    click('#type-seg [data-type="income"]'); time.sleep(.3)
    assert txt('count') == '1건' and txt('m-ex') == '−57,000원'          # 요약은 그대로
    click('#type-seg [data-type="all"]')
    # 분석: 수입
    click('#ana-seg [data-ana="income"]'); time.sleep(.3)
    assert '급여' in txt('legend') and '100%' in txt('legend') and '식비' not in txt('legend')
    click('#ana-seg [data-ana="expense"]')
    # 수입 기록을 누르면 수입 쪽으로 고치기
    click('#kind-expense'); time.sleep(.2)
    click('#list [data-entry]'); time.sleep(.3)
    assert txt('entry-title') == '기록 고치기' and js("return document.getElementById('entry').classList.contains('income')")
    click('#edit-cancel'); click('#kind-expense'); time.sleep(.2)
    # 기록 줄: 메모가 첫 줄(크게), 분류·이름은 아래 작은 줄, 메모가 없으면 첫 줄에 분류 이름(흐리게), 날짜 머리줄에 수입·지출·합계
    row = js("const b = [...document.querySelectorAll('#list [data-entry]')].find(x => x.textContent.includes('사료')); return [b.querySelector('.memo').textContent.trim(), b.querySelector('.line2 .who-tag').textContent.trim(), b.querySelector('.memo').offsetTop < b.querySelector('.line2').offsetTop, parseFloat(getComputedStyle(b.querySelector('.memo')).fontSize) > parseFloat(getComputedStyle(b.querySelector('.who-tag')).fontSize)]")
    assert row == ['사료', '임임기범', True, True], row
    head = js("return document.querySelector('#list .dayh').textContent.replace(/\\s+/g, ' ').trim()")
    assert '수입 +3,200,000원' in head and '지출 −57,000원' in head and '합계 +3,143,000원' in head, head
    # 합계(일별 달력): 오늘 칸에 수입·지출, 누르면 그날 기록만, 다시 누르면 이 달
    cell = js(f"return document.querySelector('#cal [data-day=\"{TODAY}\"]').textContent.replace(/\\s+/g, ' ').trim()")
    assert '+320만' in cell and '−5.7만' in cell, cell
    click(f'#cal [data-day="{TODAY}"]'); time.sleep(.3)
    assert '이날' in txt('m-ex-label') and js(f"return document.querySelector('#cal [data-day=\"{TODAY}\"]').classList.contains('sel')")
    click(f'#cal [data-day="{TODAY}"]'); time.sleep(.3)
    assert '이 달' in txt('m-ex-label')
    # 합계(월별): 올해 수입·지출·합계, 달마다 표, 달을 누르면 그 달로
    click('#tot-seg [data-tot="month"]'); time.sleep(1.2)
    assert vis('tot-month') and not vis('tot-day') and txt('y-in') == '+3,200,000원' and txt('y-ex') == '−57,000원'
    month_no = int(TODAY[5:7])
    assert js(f"return document.querySelector('#mtable tr.cur').textContent.replace(/\\s+/g, ' ').trim()").startswith(f'{month_no}월'), txt('mtable')
    assert '+3,143,000원' in js("return document.querySelector('#mtable tr.sum').textContent")
    click('#y-prev'); time.sleep(1)
    assert txt('y-in') == '+0원' and '–' not in txt('y-label')
    click('#y-next'); time.sleep(1)
    js("document.querySelector('#mtable tr.cur').click()"); time.sleep(1)
    assert vis('tot-day') and '이 달' in txt('m-ex-label')
    print('INCOME OK')

    # ---- 내 기록 고치기·지우기
    pick = "[...document.querySelectorAll('#list [data-entry]')].find(b => b.textContent.includes('사료')).click()"
    js("document.getElementById('entry').open = false")
    js(pick)                               # 사료 15,000원
    assert js("return document.getElementById('entry').open")
    assert vis('edit-row') and txt('entry-title') == '기록 고치기' and js("return document.getElementById('amount').value") == '15,000'
    typ('amount', '16000'); click('#save'); time.sleep(1.2)
    assert [x['amount'] for x in entries()] == [42000, 16000, 3200000] and not vis('edit-row')
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
    assert not js("return document.querySelector('#list [data-entry]').classList.contains('mine')")
    click('#list [data-entry]'); time.sleep(.3)
    assert not vis('edit-row')
    typ('amount', '5600'); typ('memo', '스타벅스'); click('#cats [data-cat]:nth-child(2)')   # 카페
    click('#save'); time.sleep(1.2)
    assert txt('m2') == '3건'
    # 거르기는 한 줄: ‹ 기간(해 포함) › · '월별 ▾' · '전체 ▾' (종류·사람은 고르기 창 안)
    assert txt('period') == f'{date.today().year}년 {date.today().month}월' and txt('mode-btn') == '월별 ▾' and txt('pick-btn') == '전체 ▾'
    assert not vis('pick-pop') and not vis('people')
    tops = js("return ['prev', 'period', 'next', 'mode-btn', 'pick-btn'].map(i => Math.round(document.getElementById(i).getBoundingClientRect().top + document.getElementById(i).offsetHeight / 2))")
    assert max(tops) - min(tops) <= 2, tops
    # 사람 거르기: 지은만 (창을 열고 고르면 창은 열린 채, 단추는 '지은 ▾' 파랗게, 창 밖을 누르면 닫힘)
    tap('id', 'pick-btn'); time.sleep(.3)
    assert vis('pick-pop') and vis('people')
    jieun = js("return [...document.querySelectorAll('#people [data-who]')].find(b => b.textContent.includes('지은')).dataset.who")
    tap('css selector', f'#people [data-who="{jieun}"]'); time.sleep(.3)
    assert vis('pick-pop') and txt('pick-btn') == '지은 ▾' and js("return document.getElementById('pick-btn').classList.contains('on')")
    assert txt('m-ex') == '−5,600원' and '지은' in txt('m-ex-label') and txt('count') == '1건'
    tap('id', 'count'); time.sleep(.3)
    assert not vis('pick-pop')
    click('#people [data-who="0"]'); time.sleep(.3)
    # 기록 칸은 쓴 사람의 색 (프로필 동그라미의 연한 색 + 왼쪽 띠), 사람마다 다름
    rows = js("return [...document.querySelectorAll('#list .it')].map(b => [b.textContent.includes('지은'), getComputedStyle(b).backgroundColor, getComputedStyle(b).boxShadow])")
    colors = {who: bg for who, bg, _ in rows}
    assert len(colors) == 2 and all(bg != 'rgba(0, 0, 0, 0)' for bg in colors.values()) and 'inset' in rows[0][2], rows
    assert all(colors[who] == bg for who, bg, _ in rows), rows
    # 기록 칸에는 합계 띠 없음 (기간 합계는 위 수입·지출·남은 돈 칸), 접힌 줄은 건수만
    assert not js("return document.querySelector('#list .list-sum')") and txt('count') == '3건'
    click('#type-seg [data-type="expense"]'); time.sleep(.3)
    click(f'#people [data-who="{jieun}"]'); time.sleep(.3)
    assert txt('pick-btn') == '지은 · 지출만 ▾' and txt('count') == '1건'
    click('#people [data-who="0"]'); click('#type-seg [data-type="all"]'); time.sleep(.3)
    # 일별: 오늘 기록, 하루 앞으로 가면 없음
    tap('id', 'mode-btn'); time.sleep(.2)
    tap('id', 'mode-day'); time.sleep(.3)
    t = date.today()
    assert not vis('mode-pop') and txt('mode-btn') == '일별 ▾' and txt('period').startswith(f'{t.year}.{t.month}.{t.day} (')
    assert txt('m2') == '3건' and '이날' in txt('m-ex-label')
    click('#prev'); time.sleep(1)
    assert txt('m2') == '0건' and '기록이 없어요' in txt('list')
    click('#mode-month'); time.sleep(.3)
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
    js("document.getElementById('auto').open = true")
    js("window.confirm = () => true")
    click('#hook-create'); time.sleep(1)
    url = js("return document.getElementById('hook-url').value")
    assert vis('hook-url-box') and url.startswith(BASE + '/api/ledger/hook/') and '한 번만' in txt('hook-state')
    md = f'{date.today().month}/{date.today().day}'
    import urllib.request
    def send(text):
        with urllib.request.urlopen(urllib.request.Request(url, data=text.encode(), method='POST', headers={'Content-Type': 'text/plain'})) as r:
            return r.status
    assert send(f'[삼성카드] 지*님 {md} 12:41 4,800원 일시불 블루보틀 성수점') == 200
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    assert vis('inbox-sec') and txt('inbox-count') == '1' and '블루보틀 성수점' in txt('inbox') and '규칙에 없는 가게' in txt('inbox')
    assert js("return document.querySelector('#inbox [data-ib-ok]').disabled")
    cafe = js("return [...document.querySelectorAll('#inbox [data-ib-cat]')].find(c => c.textContent.includes('카페')).dataset.ibCat")
    click(f'#inbox [data-ib-cat="{cafe}"]'); time.sleep(1)
    assert not js("return document.querySelector('#inbox [data-ib-ok]').disabled")
    rule_btn = js("return document.querySelector('#inbox [data-ib-rule]').textContent")
    assert '"블루보틀"는 늘 카페로' in rule_btn, rule_btn
    click('#inbox [data-ib-rule]'); time.sleep(1)
    assert '"블루보틀"이 든 가게' in txt('rules') and '규칙 "블루보틀" → 카페' in txt('inbox')
    # 금액 고치기
    click('#inbox [data-ib-edit]'); time.sleep(.3)
    # 가게·금액 칸의 X: 한 번에 지우고 그 칸에 커서, 빈 칸이면 X 숨김. 1분마다 대기함을 새로 그려도 친 값은 그대로
    shown = lambda i: js(f"return getComputedStyle(document.querySelector('[data-clear=\"{i}\"]')).display !== 'none'")
    assert shown('ib-merchant') and shown('ib-amount')
    click('[data-clear="ib-merchant"]')
    assert js("return document.getElementById('ib-merchant').value") == '' and js("return document.activeElement.id") == 'ib-merchant'
    assert not shown('ib-merchant') and shown('ib-amount')
    typ('ib-merchant', '블루')
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    assert js("return document.getElementById('ib-merchant').value") == '블루' and js("return document.activeElement.id") == 'ib-merchant'
    typ('ib-merchant', '블루보틀 성수점')
    # PC는 한 줄 세 칸, 휴대폰은 윗줄 금액·날짜·아랫줄 가게 한 줄 전부
    box = lambda c: js(f"const r = document.querySelector('#inbox .{c}').getBoundingClientRect(); return [Math.round(r.top), Math.round(r.width)]")
    assert box('e-shop')[0] == box('e-amt')[0] == box('e-date')[0], (box('e-amt'), box('e-shop'), box('e-date'))
    d.set_window_size(400, 860); time.sleep(.5)
    # 휴대폰 폭: 가계부 안의 글자 1px 작게 (위쪽 사이트 메뉴는 그대로)
    font = lambda sel: js(f"return getComputedStyle(document.querySelector('{sel}')).fontSize")
    assert font('body') == '13px' and font('.metric b') == '15px' and font('#inbox .amt') == '14px', (font('body'), font('.metric b'), font('#inbox .amt'))
    assert box('e-amt')[0] == box('e-date')[0] < box('e-shop')[0] and box('e-shop')[1] > 250, (box('e-amt'), box('e-shop'), box('e-date'))
    assert js("return document.documentElement.scrollWidth <= window.innerWidth")
    d.set_window_size(1280, 900); time.sleep(.5)
    typ('ib-amount', '5300'); click('#inbox [data-ib-save]'); time.sleep(1)
    assert '5,300원' in txt('inbox')
    before = len(entries())
    click('#inbox [data-ib-ok]'); time.sleep(1.5)
    assert not vis('inbox-sec') and len(entries()) == before + 1 and entries()[-1]['memo'] == '블루보틀 성수점' and entries()[-1]['amount'] == 5300
    assert '블루보틀 성수점' in txt('list')
    # 다음 알림은 규칙으로 바로 분류 → 모두 확정
    assert send(f'[삼성카드] {md} 15:00 6,100원 일시불 블루보틀 한남점') == 200
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    assert '규칙 "블루보틀" → 카페' in txt('inbox')
    click('#inbox-all'); time.sleep(1.5)
    assert not vis('inbox-sec') and entries()[-1]['amount'] == 6100
    # 규칙이 없어도 같은 가게의 지난 기록('이마트 장보기' → 식비)으로 분류를 미리 골라 둠 → 바로 확정
    assert send(f'[삼성카드] {md} 18:20 7,700원 일시불 이마트 장보기') == 200
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    assert "지난 기록 '이마트 장보기'" in txt('inbox') and '→ 식비' in txt('inbox'), txt('inbox')
    assert js("return document.querySelector('#inbox .chip.on').textContent.trim()") == '식비'
    assert not js("return document.querySelector('#inbox [data-ib-ok]').disabled")
    click('#inbox [data-ib-ok]'); time.sleep(1.5)
    with storage._db() as conn:
        food = conn.execute("SELECT id FROM ledger_categories WHERE name = '식비'").fetchone()[0]
    assert not vis('inbox-sec') and entries()[-1]['amount'] == 7700 and entries()[-1]['category_id'] == food
    # 취소 알림: 맞는 기록을 찾아 지움
    assert send(f'[삼성카드] 승인취소 6,100원 블루보틀 한남점 {md} 15:10') == 200
    js("document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(1.2)
    assert '같은 결제를 찾았어요' in txt('inbox') and '취소 확정' in txt('inbox')
    n = len(entries())
    click('#inbox [data-ib-ok]'); time.sleep(1.5)
    assert len(entries()) == n - 1 and not vis('inbox-sec')
    # 시험 알림 → 버리기
    click('#hook-test'); time.sleep(1.2)
    assert vis('inbox-sec') and '1,000원' in txt('inbox') and '마지막으로 받은 알림' in txt('hook-state')
    click('#inbox [data-ib-del]'); time.sleep(1)
    assert not vis('inbox-sec')
    # ---- YeYe가계부 앱 안에서 열었을 때 (앱이 넣는 window.LedgerApp 흉내): 앱 받기 안내는 숨고 '이 휴대폰 앱에 연결' → 새 연결 주소를 앱에 넣음
    d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': "window.__got = []; window.confirm = () => true; window.LedgerApp = {version: () => '1.2', connected: () => window.__got.length > 0, connect: u => { window.__got.push(u); return true; }, openSettings: () => {}};"})
    d.get(BASE + '/ledger/'); time.sleep(2); open_all()
    assert js("return document.documentElement.classList.contains('in-app')") and js("return document.getElementById('auto').open")
    assert vis('app-connect') and not vis('app-get') and '아직 연결되지' in txt('app-connect-state'), txt('app-connect-state')
    assert not js("const n = document.querySelector('.site-nav'); return !!n && n.offsetHeight > 0")   # 앱에서는 메뉴 줄(다른 탭) 없음
    click('#app-connect-btn'); time.sleep(1.2)
    got = js('return window.__got')
    assert len(got) == 1 and got[0].startswith(BASE + '/api/ledger/hook/'), got
    assert '이 휴대폰 앱(1.2)' in txt('app-connect-state') and txt('app-connect-btn') == '다시 연결'
    with urllib.request.urlopen(urllib.request.Request(got[0], data='[삼성카드] 승인 3,300원 앱연결'.encode(), method='POST', headers={'Content-Type': 'text/plain'})) as r:
        assert r.status == 200                                          # 앱에 넣은 새 주소로 받아짐
    # ---- 앱의 뒤로가기(window.ledgerBack): 열린 것을 하나씩 닫고, 닫을 게 없으면 false
    js("document.getElementById('auto').open = true")
    click('#cat-edit'); time.sleep(.2)
    assert js('return window.ledgerBack()') is True and txt('cat-edit') == '색·이름 편집'          # 편집 모드 끝
    assert js('return window.ledgerBack()') is True and not js("return document.getElementById('auto').open")
    if js("return !document.getElementById('admin').hidden && document.getElementById('admin').open"):
        assert js('return window.ledgerBack()') is True
    assert js('return window.ledgerBack()') is False
    print('AUTO OK')

    # ---- 휴대폰: 넘침 없음
    d.set_window_size(390, 844); time.sleep(.3)
    d.get(BASE + '/ledger/'); time.sleep(2); open_all()
    assert vis('app') and js("return document.documentElement.scrollWidth <= innerWidth + 1")
    # 스크립트 오류 없음 (로그인 전 401·허락 전 403 같은 응답 코드 기록은 정상)
    logs = d.get_log('browser')
    assert not [m for m in logs if m['level'] == 'SEVERE' and 'Failed to load resource' not in m['message']], logs
    print('LEDGER UI OK')
finally:
    d.quit()
    srv.shutdown()
