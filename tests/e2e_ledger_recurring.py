"""가계부 매달 반복 결제 화면: 입력 창의 '🔁 매달 반복'(날짜 칸의 날로 시작) → 내역 줄의 🔁 → 반복이 넣은 기록 고치기의
'매월 N일 반복 · 반복 결제 고치기 ›'·'다음 달부터도' → 설정 > 반복 결제(목록·고치기·멈추기·지우기·＋ 추가) → 확인할 결제의
'이미 기록됨' 안내, 휴대폰 넘침 없음. 스크린샷은 tests/_shots/ledger_recurring/"""
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

SHOTS = common.shot_dir('ledger_recurring')
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
T = date.today()
TODAY = T.isoformat()

o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source':
    "const mm = window.matchMedia.bind(window); window.matchMedia = q => /pointer:\\s*coarse/.test(q) ? mm('(max-width: 0px)') : mm(q);"})
js = d.execute_script
vis = lambda i: js(f"const e = document.getElementById('{i}'); return !!e && !e.hidden && e.offsetHeight > 0")
txt = lambda i: js(f"return document.getElementById('{i}').textContent.replace(/\\s+/g, ' ').trim()")
def typ(i, v):
    js("const e = document.getElementById(arguments[0]); e.value = arguments[1]; e.dispatchEvent(new Event('input', {bubbles: true}))", i, v)
def click(sel):
    js("document.querySelector(arguments[0]).click()", sel)
def shot(name):
    d.save_screenshot(os.path.join(SHOTS, name + '.png'))
def recs():
    with storage._db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM ledger_recurring ORDER BY id")]
def entries():
    with storage._db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM ledger_entries ORDER BY id")]
try:
    js_token = web_server.ADMIN_TOKEN
    d.get(BASE + '/ledger/'); time.sleep(1)
    js("localStorage.setItem('admin_token', arguments[0])", js_token)
    d.get(BASE + '/ledger/'); time.sleep(2)
    assert vis('app')

    # ---- 입력 창: '🔁 매달 반복'은 처음엔 꺼짐, 켜면 매월 (날짜 칸의 날)일
    click('#fab'); time.sleep(.3)
    # 분류는 고른 것 한 칸 (그림 · 이름 ⌄), 누르면 목록이 펼쳐지고 고르면 접힘
    assert vis('cat-pick') and not vis('cat-list') and '식비' in txt('cat-pick') and '🍚' in txt('cat-pick'), txt('cat-pick')
    click('#cat-pick'); time.sleep(.2)
    assert vis('cat-list') and vis('cat-edit') and js("return document.getElementById('cat-pick').getAttribute('aria-expanded')") == 'true'
    shot('0_cat_open')
    click('#cats [data-cat]:nth-child(2)'); time.sleep(.2)
    assert not vis('cat-list') and '카페' in txt('cat-pick') and '☕' in txt('cat-pick')
    click('#cat-pick'); time.sleep(.2); click('#cats [data-cat]:nth-child(4)'); time.sleep(.2)   # 생활
    assert not vis('cat-list') and '생활' in txt('cat-pick')
    assert vis('rp-new') and not vis('rp-linked') and not vis('rp-day-wrap')
    click('#rp-check'); time.sleep(.1)
    assert vis('rp-day-wrap') and js("return document.getElementById('rp-day').value") == str(T.day)
    # 날짜를 바꾸면 따라감 (직접 고르기 전까지)
    other = T.replace(day=15 if T.day != 15 else 16)
    js("const e = document.getElementById('used-on'); e.value = arguments[0]; e.dispatchEvent(new Event('change', {bubbles: true}))", other.isoformat())
    assert js("return document.getElementById('rp-day').value") == str(other.day)
    js("const e = document.getElementById('used-on'); e.value = arguments[0]; e.dispatchEvent(new Event('change', {bubbles: true}))", TODAY)
    js("const e = document.getElementById('rp-day'); e.value = '25'; e.dispatchEvent(new Event('change', {bubbles: true}))")
    typ('amount', '55000'); typ('memo', '신한은행 자동이체')
    shot('1_entry_repeat')
    click('#save'); time.sleep(1.2)
    assert not vis('sheet-wrap')
    r = recs()
    assert len(r) == 1 and (r[0]['day'], r[0]['amount'], r[0]['memo']) == (25, 55000, '신한은행 자동이체'), r
    first = entries()[-1]
    assert first['recurring_id'] == r[0]['id']
    # 내역 줄에 🔁
    assert js(f"return !!document.querySelector('[data-entry=\"{first['id']}\"] .rp-mark')")

    # ---- 반복이 넣은 기록 고치기: '매월 25일 반복 · 반복 결제 고치기 ›', 이름을 바꾸면 다음 달부터도
    click(f'[data-entry="{first["id"]}"]'); time.sleep(.5)
    assert vis('rp-linked') and not vis('rp-new') and '매월 25일 반복' in txt('rp-linked-text')
    assert js("return document.getElementById('rp-future').checked")
    typ('memo', 'XX 보험')
    shot('2_edit_linked')
    click('#save'); time.sleep(1.2)
    assert recs()[0]['memo'] == 'XX 보험'
    # 날짜만 바꾸면 반복은 그대로
    click(f'[data-entry="{first["id"]}"]'); time.sleep(.5)
    typ('amount', '60000'); click('#rp-future')   # 이번만 (체크 끔)
    click('#save'); time.sleep(1.2)
    assert recs()[0]['amount'] == 55000 and entries()[-1]['amount'] == 60000

    # ---- '반복 결제 고치기 ›' → 설정 > 반복 결제, 그 반복이 펼쳐짐
    click(f'[data-entry="{first["id"]}"]'); time.sleep(.5)
    click('#rp-open'); time.sleep(.8)
    assert not vis('sheet-wrap') and vis('set-view') and txt('set-title') == '반복 결제'
    assert '매월 25일' in txt('rec-list') and 'XX 보험' in txt('rec-list') and vis('rec-amount')
    shot('3_settings_open')
    typ('rec-amount', '57000')
    js("document.getElementById('rec-day').value = '20'")
    click('[data-rec-save]'); time.sleep(1.2)
    assert (recs()[0]['amount'], recs()[0]['day']) == (57000, 20) and not js("return !!document.getElementById('rec-amount')")
    assert '57,000원' in txt('rec-list') and '매월 20일' in txt('rec-list')
    # 멈추기 → '멈춤', 다시 시작
    click('.rec-row'); time.sleep(.3)
    click('[data-rec-pause]'); time.sleep(1)
    assert recs()[0]['paused'] == 1 and '멈춤' in txt('rec-list')
    shot('4_settings_paused')
    click('[data-rec-pause]'); time.sleep(1)
    assert recs()[0]['paused'] == 0
    # 설정 목록 줄에 개수
    click('#set-back'); time.sleep(.4)
    assert txt('row-repeat') == '1'

    # ---- '＋ 반복 결제 추가': 입력 창이 반복 켜진 채로
    click('[data-tab="repeat"]'); time.sleep(.4)
    click('#rec-add'); time.sleep(.8)
    assert vis('sheet-wrap') and js("return document.getElementById('rp-check').checked") and vis('rp-day-wrap')
    assert not js("return document.getElementById('app').classList.contains('settings-open')")
    click('#kind-income'); time.sleep(.2)
    typ('amount', '3000000'); typ('memo', '월급')
    click('#save'); time.sleep(1.2)
    assert len(recs()) == 2 and recs()[1]['memo'] == '월급'

    # ---- 확인할 결제: 같은 금액·앞뒤 3일 안이면 '이미 기록됨 · 버려도 돼요'
    with storage._db() as conn, conn:
        uid = conn.execute("SELECT id FROM ledger_users WHERE is_admin = 1").fetchone()[0]
        conn.execute("""INSERT INTO ledger_inbox(user_id, raw, amount, merchant, card, used_on, used_time, created_at)
                        VALUES(?, '신한은행 자동이체 60,000원 출금', 60000, '신한은행 자동이체', '신한은행', ?, '09:00', ?)""", (uid, TODAY, storage._now()))
    d.get(BASE + '/ledger/'); time.sleep(2)
    assert vis('inbox-sec') and "이미 기록됨" in txt('inbox') and "'XX 보험'" in txt('inbox'), txt('inbox')
    shot('5_inbox_hint')
    # 금액이 조금 달라도 (그달 반복 기록 60,000원의 10% 안): 차이를 함께
    with storage._db() as conn, conn:
        conn.execute("UPDATE ledger_inbox SET amount = 58500")
    d.get(BASE + '/ledger/'); time.sleep(2)
    assert "이미 기록됨" in txt('inbox') and '1,500원 덜 나옴' in txt('inbox'), txt('inbox')
    with storage._db() as conn, conn:
        conn.execute("UPDATE ledger_inbox SET amount = 70000")
    d.get(BASE + '/ledger/'); time.sleep(2)
    assert "이미 기록됨" not in txt('inbox')

    # ---- 휴대폰: 넘침 없음 (입력 창·설정)
    d.set_window_size(390, 844); time.sleep(.4)
    click('#fab'); time.sleep(.3); click('#rp-check'); time.sleep(.2)
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    shot('6_mobile_entry')
    click('#entry-close'); time.sleep(.3)
    # 저장 줄은 창 맨 아래에 붙어 늘 보임 (손가락 기기: 키패드까지 있어 창이 길어도), 고칠 때는 휴지통도
    js("document.documentElement.classList.add('touch')")
    click(f'[data-entry="{first["id"]}"]'); time.sleep(.5)
    foot = lambda: js("const s = document.getElementById('entry').getBoundingClientRect(), b = document.getElementById('save').getBoundingClientRect(),"
                      " t = document.getElementById('edit-delete').getBoundingClientRect();"
                      " return [b.top >= s.top && b.bottom <= s.bottom && b.bottom <= innerHeight, t.width > 0 && t.bottom <= innerHeight,"
                      " document.getElementById('entry').scrollHeight > document.getElementById('entry').clientHeight]")
    assert foot() == [True, True, False], foot()   # 처음 뜰 때 내용에 딱 맞음 (스크롤 없음)
    # 사진·수정 이력은 분류 줄에 (🕘 n을 누르면 그 아래에 이력)
    assert js("const r = document.getElementById('cat-pick').getBoundingClientRect(), p = document.getElementById('ph-add').getBoundingClientRect(),"
              " h = document.getElementById('hist').getBoundingClientRect(); return Math.abs(r.top - p.top) < 8 && Math.abs(r.top - h.top) < 8")
    assert not vis('hist-panel') and txt('hist-n') != ''
    click('#hist'); time.sleep(.3)
    assert vis('hist-panel') and '넣음' in txt('hist-list')
    shot('6a_mobile_hist_open')
    click('#hist'); time.sleep(.2)
    assert not vis('hist-panel') and foot() == [True, True, False]
    shot('6b_mobile_edit_top')
    js("document.getElementById('entry').scrollTop = 99999"); time.sleep(.2)
    assert foot()[:2] == [True, True], foot()
    js("document.getElementById('entry').scrollTop = 120"); time.sleep(.2)
    assert foot()[:2] == [True, True], foot()
    # 저장하지 못하면 저장 줄 안에 이유
    typ('amount', ''); click('#save'); time.sleep(.3)
    assert vis('entry-msg') and '금액' in txt('entry-msg')
    shot('6c_mobile_edit_msg')
    click('#entry-close'); time.sleep(.3)
    js("document.documentElement.classList.remove('touch')")
    click('#set-open'); time.sleep(.4); click('[data-tab="repeat"]'); time.sleep(.4); click('.rec-row'); time.sleep(.3)
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    assert js("const e = document.querySelector('.rec-ed'); return e.scrollWidth <= e.clientWidth + 1")
    shot('7_mobile_settings')
    # 지우기: 기록은 그대로
    n = len(entries())
    js("window.confirm = () => true")
    click('[data-rec-del]'); time.sleep(1)
    assert len(recs()) == 1 and len(entries()) == n and entries()[0]['recurring_id'] is None
    print('LEDGER RECURRING UI OK')
finally:
    d.quit()
    srv.shutdown()
