import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket, json, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, card_store
from datetime import date, timedelta
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# 카드 혜택 한도: API(로그인·입력 검사)와 화면(접기·최근 입력·날짜·수정·삭제·월 이동·대시보드 카드)
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def post(body):
    req = urllib.request.Request(BASE + '/api/card', json.dumps(body).encode(), {'Content-Type': 'application/json'})
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)

TOKEN = web_server.ADMIN_TOKEN
today = date.today()
tomorrow = (today + timedelta(days=1)).isoformat()
prev_month_day = today.replace(day=1) - timedelta(days=1)
assert post({'action': 'list'})[0] == 401   # 소비 내역은 조회도 로그인 필요
web_server._clear_auth_failures('127.0.0.1')
for bad in [{'date': tomorrow, 'place': 'a', 'amount': 1}, {'date': '2026-02-30', 'place': 'a', 'amount': 1},
            {'date': today.isoformat(), 'place': ' ', 'amount': 1}, {'date': today.isoformat(), 'place': 'a\nb', 'amount': 1},
            {'date': today.isoformat(), 'place': 'a', 'amount': 0}, {'date': today.isoformat(), 'place': 'a', 'amount': True},
            {'date': today.isoformat(), 'place': 'a' * 31, 'amount': 1}]:
    assert post({'action': 'add', 'password': TOKEN, **bad})[0] == 400, bad
assert post({'action': 'list', 'month': '2026-13', 'password': TOKEN})[0] == 400
assert post({'action': 'delete', 'id': 999, 'password': TOKEN})[0] == 400
for d, p, a in [(prev_month_day, '이마트', 5000), (today, '스타벅스', 1950), (today, 'GS25', 420), (today, '스타벅스', 1950)]:
    assert post({'action': 'add', 'date': d.isoformat(), 'place': p, 'amount': a, 'password': TOKEN})[0] == 200
_, data = post({'action': 'list', 'password': TOKEN})
assert data['limit'] == 30000 and data['today'] == today.isoformat() and len(data['items']) == 3, data
assert [(x['place'], x['amount']) for x in data['recent']] == [('스타벅스', 1950), ('GS25', 420), ('이마트', 5000)], data['recent']
print('API OK')

o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
text = lambda i: js(f"return document.getElementById('{i}').textContent")
hidden = lambda i: js(f"return document.getElementById('{i}').hidden")
try:
    # 로그인 전: 로그인 칸만, 대시보드 카드는 안내문
    d.get(BASE + '/'); time.sleep(1.5)
    assert '로그인' in text('benefit-body')
    d.get(BASE + '/card/'); time.sleep(1)
    assert not hidden('login') and hidden('content')
    js("document.getElementById('login-password').value='틀림'; document.getElementById('login').requestSubmit()"); time.sleep(1)
    assert text('login-error') and hidden('content')
    web_server._clear_auth_failures('127.0.0.1')
    js("document.getElementById('login-password').value='Secr3t!'; document.getElementById('login').requestSubmit()"); time.sleep(1.5)
    assert hidden('login') and not hidden('content')
    assert text('used') == '4,320' and '25,680' in text('left'), text('left')

    # 기본은 둘 다 접힘, 눌러서 펼침
    assert hidden('entry') and hidden('history')
    assert '기준' in text('entry-summary')
    js("document.getElementById('entry-fold').click()")
    js("document.getElementById('history-fold').click()")
    assert not hidden('entry') and not hidden('history') and text('entry-summary') == ''

    # 최근 입력은 칸만 채우고 등록하지 않음
    assert js("return document.querySelectorAll('#quick button').length") == 3
    js("document.querySelector('#quick button').click()")
    assert js("return [document.getElementById('place').value, document.getElementById('amount').value]") == ['스타벅스', '1,950']
    assert text('used') == '4,320' and js("return document.querySelector('#quick button').classList.contains('is-on')")
    # 빈 값 검사
    js("document.getElementById('place').value=''; document.getElementById('entry-form').requestSubmit()")
    assert '사용처' in text('entry-error')
    # 드롭다운: 글자로 거르고, 고르면 칸을 채움
    js("const p=document.getElementById('place'); p.value='이마'; p.dispatchEvent(new Event('input'))")
    assert not hidden('dropdown') and js("return document.querySelectorAll('#dropdown button').length") == 1
    js("document.querySelector('#dropdown button').click()")
    assert hidden('dropdown') and js("return document.getElementById('amount').value") == '5,000'
    js("document.getElementById('entry-form').requestSubmit()"); time.sleep(1)
    assert text('used') == '9,320' and not hidden('undo')
    assert js("return document.getElementById('place').value") == ''
    # 등록 취소
    js("document.getElementById('undo-btn').click()"); time.sleep(1)
    assert text('used') == '4,320' and hidden('undo')

    # 날짜 버튼
    js("document.querySelector('.dates [data-offset=\"1\"]').click()")
    assert js("return document.getElementById('date').value") == (today - timedelta(days=1)).isoformat()
    js("document.querySelector('.dates [data-offset=\"0\"]').click()")
    # 글자 그대로 표시, 80%부터 경고색, 누적
    js("document.getElementById('place').value='<b>새곳</b>'; document.getElementById('amount').value='24,000'; document.getElementById('entry-form').requestSubmit()"); time.sleep(1)
    assert js("return document.getElementById('hero').classList.contains('warn')")
    assert js("return [...document.querySelectorAll('.row-name')].map(e => e.textContent)")[0] == '<b>새곳</b>'
    assert '28,320' in js("return document.querySelector('.row .sub').textContent")

    # 이력에서 금액 수정 → 초과, 사용처 필터, 삭제
    js("const i=document.querySelector('.row .amt'); i.value='30,000'; i.dispatchEvent(new Event('change',{bubbles:true}))"); time.sleep(1)
    assert js("return document.getElementById('hero').classList.contains('over')") and text('left') == '4,320원 초과'
    js("[...document.querySelectorAll('#chips button')].find(b => b.textContent==='스타벅스').click()")
    assert js("return document.querySelectorAll('.row').length") == 2
    assert text('count') == '2건 · 3,900원', text('count')
    js("[...document.querySelectorAll('#chips button')].find(b => b.textContent==='전체').click()")
    js("document.querySelector('.row .del').click()"); time.sleep(1)
    assert text('used') == '4,320'

    # 이력에서 날짜를 지난달로 옮기면 이번 달 합계에서 빠짐 (맨 위 = 나중에 등록한 스타벅스 1,950)
    js("const i=document.querySelector('.row input[type=date]'); i.value=arguments[0]; i.dispatchEvent(new Event('change',{bubbles:true}))", prev_month_day.isoformat()); time.sleep(1)
    assert text('used') == '2,370', text('used')
    # 달 이동
    js("document.getElementById('prev').click()"); time.sleep(1)
    assert text('used') == '6,950', text('used')
    js("document.getElementById('next').click()"); time.sleep(1)

    # 대시보드 카드
    d.get(BASE + '/'); time.sleep(1.5)
    assert '2,370' in text('benefit-body') and '남은 한도 27,630원' in text('benefit-body')
    assert js("return document.querySelector('#card-benefit .card-head').getAttribute('href')") == '/card/'
    print('PAGE OK')

    # 메일로 찾은 결제: 차감할 가게면 바로 합계에, 아니면 '차감 안 한 결제'에서 가게 추가
    now_text = today.isoformat() + ' 10:00'
    assert card_store.record_card_payment('9001', now_text, '스타벅스_주문', 3600) == 'matched'
    assert card_store.record_card_payment('9002', now_text, '이디야커피 역삼점', 4500) == 'other'
    d.get(BASE + '/card/'); time.sleep(1.5)
    assert text('used') == '5,970' and '메일 연결 전' in text('mail-bar')
    assert text('keyword-count') == '2곳' and text('others-count') == '1건'
    assert hidden('keywords-body') and hidden('others-body')
    js("document.getElementById('keyword-fold').click(); document.getElementById('others-fold').click(); document.getElementById('history-fold').click()")
    assert not hidden('keywords-body') and not hidden('others-body')
    assert js("return [...document.querySelectorAll('.row-name')].filter(e => e.querySelector('.mail-tag')).length") == 1
    card_store.set_card_mail_status('ok', mode='idle')
    js("document.querySelector('[data-add-keyword]').click()"); time.sleep(1)
    assert text('used') == '10,470' and text('others-count') == '0건' and '이디야커피' in text('keywords')
    assert '메일 자동 확인 중' in text('mail-bar')
    # 가게를 지워도 이미 차감한 금액은 그대로
    js("document.querySelector('[data-keyword=\"이디야커피\"]').click()"); time.sleep(1)
    assert text('used') == '10,470' and text('keyword-count') == '2곳'
    # 직접 추가
    js("document.getElementById('keyword').value='메가커피'; document.getElementById('keyword-form').requestSubmit()"); time.sleep(1)
    assert '메가커피' in text('keywords') and js("return document.getElementById('keyword').value") == ''
    print('MAIL UI OK')

    # 모바일: 가로 넘침 없음
    d.set_window_size(390, 844); time.sleep(0.8)
    js("document.getElementById('entry-fold').click()"); time.sleep(0.3)
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('MOBILE OK')
finally:
    d.quit()
    srv.shutdown()
