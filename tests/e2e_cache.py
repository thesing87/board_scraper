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

# 1) 서버 예열: 주기마다 첫 화면 조회를 실행
calls = []
real_state, real_page = web_server.build_state, web_server.build_posts_page
web_server.WARMUP_INTERVAL_SECONDS = 0.3
web_server.build_state = lambda: (calls.append('state'), real_state())[1]
web_server.build_posts_page = lambda *a, **k: (calls.append('posts'), real_page(*a, **k))[1]
threading.Thread(target=web_server._keep_warm, daemon=True).start()
time.sleep(1.2)
print('warm calls', calls[:6])
assert calls.count('state') >= 2 and calls.count('posts') >= 2
web_server.WARMUP_INTERVAL_SECONDS = 3600

# 2) 지난 화면 즉시 표시: 서버 /api/state를 일부러 느리게
delay = {'s': 0}
def slow_state():
    time.sleep(delay['s'])
    return real_state()
web_server.build_state = slow_state
web_server.build_posts_page = real_page
srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18099), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:18099/'
o = Options()
for a in ['--headless=new', '--window-size=1440,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get(BASE); time.sleep(3)
    first_ids = js("return [...document.querySelectorAll('.post-card')].map(c => c.id)")
    assert first_ids and js("return !!localStorage.getItem('state_cache_v1') && !!localStorage.getItem('feed_cache_v1')")
    # 새 탭처럼 sessionStorage를 비우고, 서버가 4초 걸리는 상황에서 다시 접속
    js("sessionStorage.clear()")
    delay['s'] = 4
    reads_before = len(storage.unread_summary()['unread_ids'])
    d.get(BASE); time.sleep(0.8)
    early = js("""return {status: document.getElementById('status-text').textContent, cached: app.showingCached,
        title: (document.querySelector('.feed-title') || {}).textContent, ids: [...document.querySelectorAll('.post-card')].map(c => c.id),
        nav: document.querySelectorAll('.kw-item').length}""")
    print('0.8s after load', {k: (v if k != 'ids' else len(v)) for k, v in early.items()})
    assert early['cached'] and early['status'].startswith('지난 화면') and early['ids'] == first_ids and early['nav'] > 2
    # 지난 화면에서 스크롤해도 읽음 처리하지 않음
    js("scrollTo(0, document.body.scrollHeight)"); time.sleep(1)
    assert js("return app.readQueue.size") == 0
    time.sleep(5)
    late = js("return {status: document.getElementById('status-text').textContent, cached: app.showingCached, n: document.querySelectorAll('.post-card').length}")
    print('after server answered', late)
    assert not late['cached'] and late['status'].startswith('수집 중') and late['n'] > 0
    # 캐시가 없으면 예전처럼 서버 응답 후 표시 (오류 없음)
    js("localStorage.clear(); sessionStorage.clear()")
    delay['s'] = 0
    d.get(BASE); time.sleep(2.5)
    assert js("return document.querySelectorAll('.post-card').length") > 0
    errs = [l for l in d.get_log('browser') if l['level'] == 'SEVERE']
    assert not errs, errs
    print('CACHE E2E PASSED')
finally:
    d.quit()
