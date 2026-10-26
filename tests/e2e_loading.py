import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, shot_dir
import shutil, tempfile, threading, time
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(DATA_DIR, f), tmp)
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
assert calls.count('state') >= 2 and calls.count('posts') >= 2, calls
web_server.WARMUP_INTERVAL_SECONDS = 3600

# 2) 서버를 일부러 느리게: 첫 화면은 뼈대 + 진행 막대, 다 오면 한 번에 표시
delay = {'state': 0, 'posts': 0}
def slow_state():
    time.sleep(delay['state'])
    return real_state()
def slow_page(*a, **k):
    time.sleep(delay['posts'])
    return real_page(*a, **k)
web_server.build_state = slow_state
web_server.build_posts_page = slow_page
srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18099), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:18099/'
SHOTS = shot_dir('loading')
o = Options()
for a in ['--headless=new', '--window-size=1440,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
VIEW = """return {progress: !document.getElementById('top-progress').hidden,
    skeletonCards: document.querySelectorAll('#feed .sk-card').length, posts: document.querySelectorAll('.post-card:not(.sk-card)').length,
    navItems: document.querySelectorAll('.kw-item').length, navSkeleton: !!document.querySelector('#keyword-groups .sk-nav'),
    busy: document.getElementById('feed').getAttribute('aria-busy'), title: (document.querySelector('.feed-title') || {}).textContent}"""
try:
    # 예전 버전의 '지난 화면' 캐시가 남아 있어도 쓰지 않고 지움
    d.get(BASE); time.sleep(2.5)
    js("localStorage.setItem('state_cache_v1', '{}'); localStorage.setItem('feed_cache_v1', '[]'); sessionStorage.clear()")
    delay.update(state=2, posts=2)
    d.get(BASE); time.sleep(0.8)
    early = js(VIEW); print('0.8s (loading)', early)
    assert early['progress'] and early['skeletonCards'] == 2 and early['posts'] == 0 and early['navSkeleton'] and early['busy'] == 'true'
    d.save_screenshot(os.path.join(SHOTS, '1_skeleton.png'))
    time.sleep(2.7)
    mid = js(VIEW); print('3.5s (state done, posts loading)', mid)
    # 게시판 목록도 글 목록과 함께 한 번에 표시 (상태만 먼저 와도 뼈대 유지)
    assert mid['progress'] and mid['skeletonCards'] == 2 and mid['navSkeleton']
    time.sleep(2.5)
    done = js(VIEW); print('6s (done)', done)
    assert not done['progress'] and done['skeletonCards'] == 0 and done['posts'] > 0 and done['navItems'] > 2 and done['busy'] is None
    assert js("return localStorage.getItem('state_cache_v1') === null && localStorage.getItem('feed_cache_v1') === null")
    d.save_screenshot(os.path.join(SHOTS, '2_done.png'))

    # 3) 게시판 이동: 지금 화면은 그대로 두고 진행 막대만 표시
    delay.update(state=0, posts=1.5)
    first_ids = js("return [...document.querySelectorAll('.post-card')].map(c => c.id)")
    js("document.querySelector('[data-action=\"open-group\"]').click()"); time.sleep(0.5)
    moving = js("return {progress: !document.getElementById('top-progress').hidden, ids: [...document.querySelectorAll('.post-card')].map(c => c.id)}")
    print('switching board', moving['progress'], len(moving['ids']))
    assert moving['progress'] and moving['ids'] == first_ids
    time.sleep(1.8)
    assert js("return document.getElementById('top-progress').hidden")

    # 4) 상태 요청이 실패하면 오류 안내 (뼈대·진행 막대가 계속 남지 않음)
    def broken_state():
        raise RuntimeError('state down')
    web_server.build_state = broken_state
    js("sessionStorage.clear()")
    d.get(BASE); time.sleep(2)
    failed = js("return {text: document.getElementById('feed').textContent.trim(), progress: !document.getElementById('top-progress').hidden, sk: document.querySelectorAll('#feed .sk-card').length}")
    print('state failed', failed)
    assert '서버에 연결하지 못했습니다' in failed['text'] and not failed['progress'] and failed['sk'] == 0
    errs = [l for l in d.get_log('browser') if l['level'] == 'SEVERE' and 'api/state' not in l['message']]
    assert not errs, errs
    print('LOADING E2E PASSED')
finally:
    d.quit()
