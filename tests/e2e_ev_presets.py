import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket, json, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# 유지비 계산기 저장한 조건: 서버 저장(로그인 필요)·입력 검사, 화면에서 저장·불러오기·삭제·지금 값 표시, 다른 기기(브라우저)에서도 보임
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def post(body):
    req = urllib.request.Request(BASE + '/api/ev', json.dumps(body).encode(), {'Content-Type': 'application/json'})
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)

TOKEN = web_server.ADMIN_TOKEN
GOOD = {'dist': 1500, 'evEffIn': 5.2, 'evPrice': 180, 'evLoss': 8, 'iceEff': 12, 'icePrice': 1700}
assert post({'action': 'list'})[0] == 401
web_server._clear_auth_failures('127.0.0.1')
for bad in [{'name': '', 'values': GOOD}, {'name': 'a' * 21, 'values': GOOD}, {'name': 'a\nb', 'values': GOOD},
            {'name': 'x', 'values': {**GOOD, 'evLoss': 99}}, {'name': 'x', 'values': {**GOOD, 'dist': '1500'}},
            {'name': 'x', 'values': {k: v for k, v in GOOD.items() if k != 'iceEff'}}, {'name': 'x', 'values': 'no'},
            {'name': 'x', 'values': {**GOOD, 'dist': True}}]:
    assert post({'action': 'add', 'password': TOKEN, **bad})[0] == 400, bad
assert post({'action': 'delete', 'id': 99, 'password': TOKEN})[0] == 400
assert post({'action': 'add', 'name': '집밥 충전', 'values': GOOD, 'password': TOKEN})[0] == 200
assert [p['name'] for p in post({'action': 'list', 'password': TOKEN})[1]['presets']] == ['집밥 충전']
print('API OK')

o = Options()
for a in ['--headless=new', '--window-size=1280,1000']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
text = lambda i: js(f"return document.getElementById('{i}').textContent")
# 숨김은 속성뿐 아니라 실제로 화면에서 안 보이는지까지
hidden = lambda i: js(f"const e=document.getElementById('{i}'); return e.hidden && e.offsetHeight === 0")
val = lambda i: js(f"return document.getElementById('{i}').value")
try:
    # 로그인 전: 로그인 칸만, 계산기는 그대로 동작
    d.get(BASE + '/ev/'); time.sleep(1.5)
    assert not hidden('preset-login') and hidden('preset-open')
    assert js("return document.querySelectorAll('.preset').length") == 0
    js("document.getElementById('preset-password').value='Secr3t!'; document.getElementById('preset-login').requestSubmit()"); time.sleep(1.2)
    assert hidden('preset-login') and not hidden('preset-open')
    assert js("return [...document.querySelectorAll('.preset-name')].map(e => e.textContent)") == ['집밥 충전']
    assert '절약' in js("return document.querySelector('.preset-result').textContent")

    # 지금 값 저장: 이름 없으면 안내, 저장하면 맨 앞에 '지금 값'으로 표시
    js("document.getElementById('dist').value = 3000; document.getElementById('dist').dispatchEvent(new Event('input'))")
    js("document.getElementById('preset-open').click()")
    assert not hidden('preset-form')
    js("document.getElementById('preset-form').requestSubmit()")
    assert '이름' in text('preset-msg')
    js("document.getElementById('preset-name').value = '<b>출퇴근</b>'; document.getElementById('preset-form').requestSubmit()"); time.sleep(1.2)
    assert hidden('preset-form') and '저장했습니다' in text('preset-msg')
    names = js("return [...document.querySelectorAll('.preset-name')].map(e => e.textContent)")
    assert names == ['<b>출퇴근</b>', '집밥 충전'], names   # 이름은 글자 그대로
    assert js("return [...document.querySelectorAll('.preset')].map(e => e.classList.contains('is-on'))") == [True, False]

    # 불러오기: 입력 칸·요약이 그 값으로, 표시도 옮겨 감
    before = text('sumBig')
    js("document.querySelectorAll('.preset-load')[1].click()"); time.sleep(.5)
    assert [val('dist'), val('evEffIn'), val('evPrice'), val('evLoss')] == ['1500', '5.2', '180', '8']
    assert text('sumBig') != before and "'집밥 충전' 값을 불러왔습니다" == text('preset-msg')
    assert js("return [...document.querySelectorAll('.preset')].map(e => e.classList.contains('is-on'))") == [False, True]
    # 값을 손으로 바꾸면 어느 조건과도 같지 않음
    js("document.getElementById('evPrice').value = 181; document.getElementById('evPrice').dispatchEvent(new Event('input'))")
    assert js("return document.querySelectorAll('.preset.is-on').length") == 0

    # 다른 기기(새 브라우저 저장소)에서도 같은 목록
    js("localStorage.clear()")
    d.get(BASE + '/ev/'); time.sleep(1)
    assert not hidden('preset-login')
    js("localStorage.setItem('admin_token', arguments[0])", TOKEN)
    d.get(BASE + '/ev/'); time.sleep(1.2)
    assert len(js("return [...document.querySelectorAll('.preset-name')]")) == 2

    # 삭제
    js("document.querySelector('.preset-del').click()"); time.sleep(1)
    assert js("return [...document.querySelectorAll('.preset-name')].map(e => e.textContent)") == ['집밥 충전']
    assert '삭제했습니다' in text('preset-msg')
    # 휴대폰: 넘침 없음
    d.set_window_size(390, 844); time.sleep(.5)
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('PAGE OK')
finally:
    d.quit()
    srv.shutdown()
