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
from selenium.webdriver.common.by import By

# 묶음 2개(통합·에펨) + 묶음 없는 게시판 '한국시리즈'. 모바일에서 화살표로 한국시리즈를 묶음 사이·맨 아래로 옮김
storage.init_db()
ids = {n: storage.save_group(None, n, [{'board': 'car', 'keyword': n}])[0] for n in ['싼타페', '삼성', '한국시리즈']}
f1, f2 = storage.save_folder(None, '통합'), storage.save_folder(None, '에펨')
storage.arrange_group(ids['싼타페'], f1)
storage.arrange_group(ids['삼성'], f2)
post = lambda pid: {'id': pid, 'title': f'글 {pid}', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
                    'link': f'/{pid}', 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}
storage.save_keyword_post('car', '싼타페', post('701'), is_new=True)

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
o.add_argument('--headless=new')
o.add_experimental_option('mobileEmulation', {'deviceMetrics': {'width': 390, 'height': 844, 'pixelRatio': 3, 'touch': True},
                                              'userAgent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36'})
d = Chrome(options=o)
js = d.execute_script
chips = lambda: js("return [...document.querySelectorAll('#chip-row .chip > span:first-child, #chip-row .site-chip-open > span:first-child')].map(e => e.textContent.trim())")
def tap(el):
    js("arguments[0].scrollIntoView({block: 'center'})", el); time.sleep(0.2)
    x, y = js("const r = arguments[0].getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]", el)
    d.execute_cdp_cmd('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': x, 'y': y}]})
    d.execute_cdp_cmd('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    time.sleep(1.2)
try:
    d.get(f'http://127.0.0.1:{port}/'); time.sleep(2)
    assert chips() == ['전체', '한국시리즈', '통합', '에펨'], chips()
    js("localStorage.setItem('admin_token', 'Secr3t!'); updateAdminUI(); document.querySelector('[data-action=\"open-settings\"]').click()"); time.sleep(0.8)
    down = f"#settings-groups [data-action=move-group][data-group-id='{ids['한국시리즈']}'][data-direction=down]"
    tap(d.find_element(By.CSS_SELECTOR, down))
    assert chips() == ['전체', '통합', '한국시리즈', '에펨'], chips()
    tap(d.find_element(By.CSS_SELECTOR, down))
    assert chips() == ['전체', '통합', '에펨', '한국시리즈'], chips()
    # 관리 화면 게시판 목록도 같은 순서, 묶음 화살표는 맨 앞 묶음의 '위로'만 꺼짐 (한국시리즈가 맨 뒤라 에펨 '아래로'는 켜짐)
    assert js("return [...document.querySelectorAll('#settings-groups .group-row-name')].map(e => e.textContent.trim())") == ['싼타페', '삼성', '한국시리즈']
    assert js(f"return document.querySelector('[data-action=move-folder][data-folder-id=\"{f1}\"][data-direction=up]').disabled")
    assert not js(f"return document.querySelector('[data-action=move-folder][data-folder-id=\"{f2}\"][data-direction=down]').disabled")
    js(f"document.querySelector('[data-action=move-folder][data-folder-id=\"{f2}\"][data-direction=down]').click()"); time.sleep(1.2)
    assert chips() == ['전체', '통합', '한국시리즈', '에펨'], chips()
    print('MOBILE ORDER OK')

    # 새 글 배너: × 로 닫으면 같은 수로는 다시 안 뜨고, 새 글이 더 오면 다시 뜸
    d.get(f'http://127.0.0.1:{port}/'); time.sleep(2)
    js("app.filter = 'all'; openView(ALL_KEY, 1)"); time.sleep(1.2)
    banner = "document.getElementById('new-banner')"
    storage.save_keyword_post('car', '싼타페', post('702'), is_new=True)
    js("return pollState()"); time.sleep(0.8)
    assert not js(f"return {banner}.hidden") and '새 글 1개' in js(f"return {banner}.textContent")
    tap(d.find_element(By.CSS_SELECTOR, '#new-banner .new-banner-close'))
    assert js(f"return {banner}.hidden")
    js("return pollState()"); time.sleep(0.8)
    assert js(f"return {banner}.hidden")
    storage.save_keyword_post('car', '싼타페', post('703'), is_new=True)
    js("return pollState()"); time.sleep(0.8)
    assert not js(f"return {banner}.hidden") and '새 글 2개' in js(f"return {banner}.textContent")
    tap(d.find_element(By.CSS_SELECTOR, '#new-banner .new-banner-open'))
    assert js(f"return {banner}.hidden") and js("return document.querySelector('.post-card').id") == 'post-703'
    print('BANNER DISMISS OK')
finally:
    d.quit()
    srv.shutdown()
