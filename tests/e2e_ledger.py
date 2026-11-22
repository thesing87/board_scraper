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
    # 기록 줄: 이름은 이름표, 메모는 아래 줄에 따로, 날짜 머리줄에 수입·지출·합계
    row = js("const b = [...document.querySelectorAll('#list [data-entry]')].find(x => x.textContent.includes('사료')); return [b.querySelector('.who-tag').textContent.trim(), b.querySelector('.memo').textContent.trim()]")
    assert row == ['임임기범', '사료'], row
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
    js(pick)                               # 사료 15,000원
    assert vis('edit-row') and txt('entry-title') == '기록 고치기' and js("return document.getElementById('amount').value") == '15,000'
    typ('amount', '16000'); click('#save'); time.sleep(1.2)
    assert [x['amount'] for x in entries()] == [42000, 16000, 3200000] and not vis('edit-row')
    js(pick)
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
    # 사람 거르기: 지은만
    jieun = js("return [...document.querySelectorAll('#people [data-who]')].find(b => b.textContent.includes('지은')).dataset.who")
    click(f'#people [data-who="{jieun}"]'); time.sleep(.3)
    assert txt('m-ex') == '−5,600원' and '지은' in txt('m-ex-label') and txt('count') == '1건'
    click('#people [data-who="0"]')
    # 일별: 오늘 기록, 하루 앞으로 가면 없음
    click('#mode-day'); time.sleep(.3)
    assert txt('m2') == '3건' and '이날' in txt('m-ex-label')
    click('#prev'); time.sleep(1)
    assert txt('m2') == '0건' and '기록이 없어요' in txt('list')
    click('#mode-month'); time.sleep(.3)
    # 다른 페이지 메뉴에도 가계부 (이 기기는 가계부에 로그인)
    d.get(BASE + '/'); time.sleep(1)
    assert 'ledger' in navs() and 'card' not in navs()
    print('MEMBER OK')

    # ---- 결제 알림 자동 기록: 연결 주소 만들기 → 알림 받기 → 대기함에서 분류 고르기 → 규칙 → 확정·취소
    d.get(BASE + '/ledger/'); time.sleep(2)
    assert not vis('inbox-sec') and '아직 연결 주소' in txt('hook-state')
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
    print('AUTO OK')

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
