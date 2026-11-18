import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# 대시보드 관리자 로그인: 로그인하면 카드·만화 메뉴와 카드 혜택 카드가 보이고, 로그아웃하면 다시 숨김
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
navs = lambda: js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)")
visible = lambda i: js(f"const e = document.getElementById('{i}'); return !!e && !e.hidden && e.offsetHeight > 0")
try:
    d.get(BASE + '/'); time.sleep(1.5)
    assert not visible('card-benefit') and 'card' not in navs() and 'comics' not in navs()
    assert js("return document.getElementById('admin-label').textContent") == '로그인'
    assert not visible('login-modal')
    js("document.getElementById('admin-btn').click()")
    assert visible('login-modal') and js("return document.activeElement.id") == 'login-password'
    # 빈 암호는 보내지 않음, 틀린 암호는 안내
    js("document.getElementById('login-form').requestSubmit()")
    assert visible('login-modal')
    js("document.getElementById('login-password').value = '틀림'; document.getElementById('login-form').requestSubmit()"); time.sleep(1)
    assert js("return document.getElementById('login-error').textContent"), 'no error'
    web_server._clear_auth_failures('127.0.0.1')
    # 취소·Esc로 닫힘
    js("document.getElementById('login-cancel').click()")
    assert not visible('login-modal')
    js("document.getElementById('admin-btn').click()")
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
    assert not visible('login-modal')
    # 로그인
    js("document.getElementById('admin-btn').click()")
    js("document.getElementById('login-password').value = 'Secr3t!'; document.getElementById('login-form').requestSubmit()"); time.sleep(2.5)
    assert js("return localStorage.getItem('admin_token')") == web_server.ADMIN_TOKEN
    assert 'card' in navs() and 'comics' in navs(), navs()
    assert visible('card-benefit')
    assert js("return document.getElementById('admin-label').textContent") == '관리자'
    print('LOGIN OK')
    # 로그아웃 (확인 창)
    js("document.getElementById('admin-btn').click()")
    d.switch_to.alert.dismiss()
    assert js("return localStorage.getItem('admin_token')")
    js("document.getElementById('admin-btn').click()")
    d.switch_to.alert.accept(); time.sleep(2)
    assert not js("return localStorage.getItem('admin_token')")
    assert not visible('card-benefit') and 'card' not in navs()
    # 휴대폰: 아이콘 버튼, 넘침 없음
    d.set_window_size(390, 844); time.sleep(.5)
    assert js("return document.getElementById('admin-btn').getBoundingClientRect().width") < 40
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('LOGOUT MOBILE OK')
finally:
    d.quit()
    srv.shutdown()
