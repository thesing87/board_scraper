import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, threading, time
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN')
import storage, web_server
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18096), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:18096/'
SHOTS = shot_dir('home_shots')
o = Options()
for a in ['--headless=new', '--window-size=1440,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
W = time.sleep
def view():
    return js("return {title: document.querySelector('.feed-title').textContent, page: app.page, q: app.searchQuery, hash: location.hash, y: Math.round(scrollY), url: location.href}")
try:
    d.get(BASE); W(2.5)
    d.save_screenshot(os.path.join(SHOTS, 'desktop.png'))
    # 게시판 2페이지에서 스크롤한 뒤 제목 클릭 → 전체 1페이지, 맨 위
    js("document.querySelector('[data-action=\"open-group\"]').click()"); W(1.2)
    js("document.querySelector('[data-action=\"page\"][data-target=\"next\"]').click()"); W(1.5)
    js("scrollTo(0, 1500)"); W(0.3)
    before = view(); print('before', before)
    assert before['title'] != '전체' and before['page'] == 2
    d.find_element('css selector', 'a.brand-name').click(); W(1.5)
    after = view(); print('after title click', after)
    assert after['title'] == '안 읽은 글' and after['page'] == 1 and after['y'] == 0 and after['url'] == BASE
    # 검색 중 + 텔레그램 링크(#post-ID)로 들어온 상태에서 홈 버튼
    js("document.getElementById('search-input').value='싼타페'; document.getElementById('search-form').requestSubmit()"); W(1.5)
    js("history.replaceState(null, '', '#post-123')")
    assert view()['q'] == '싼타페'
    d.find_element('css selector', '.desktop-only[data-action="go-home"]').click(); W(1.5)
    h = view(); print('after home button', h)
    assert h['title'] == '안 읽은 글' and h['q'] == '' and h['hash'] == '' and js("return document.getElementById('search-input').value") == ''
    # 관리 패널이 열려 있어도 닫고 홈으로
    js("document.querySelector('.topbar [data-action=\"open-settings\"]').click()"); W(0.3)
    js("document.querySelector('a.brand-name').click()"); W(1)
    assert js("return document.getElementById('settings').hidden")
    # 모바일: 홈 버튼
    d.set_window_size(390, 844); d.get(BASE); W(2.5)
    js("document.querySelectorAll('#chip-row .chip')[1].click()"); W(1.2)
    d.find_element('css selector', '.mobile-only[data-action="go-home"]').click(); W(1.5)
    m = view(); print('mobile', m)
    assert m['title'] == '안 읽은 글'
    d.save_screenshot(os.path.join(SHOTS, 'mobile.png'))
    errs = [l for l in d.get_log('browser') if l['level'] == 'SEVERE']
    assert not errs, errs
    print('HOME E2E PASSED')
finally:
    d.quit()
