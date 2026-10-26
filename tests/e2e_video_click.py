import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, threading, time, json, urllib.request
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN')
import storage, web_server
from selenium.webdriver import Chrome, ActionChains
from selenium.webdriver.chrome.options import Options

storage.init_db()
# 실제 사이트의 동영상 글을 그대로 넣어 같은 마크업으로 확인
live = json.load(urllib.request.urlopen(LIVE_URL + '/api/posts?video_only=1', timeout=20))['posts'][:2]
for p in live:
    storage.save_keyword_post('car', '싼타페', p, is_new=False)
srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18095), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
for a in ['--headless=new', '--window-size=1440,900', '--autoplay-policy=no-user-gesture-required', '--mute-audio']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get('http://127.0.0.1:18095/'); time.sleep(2.5)
    js("document.querySelector('[data-action=\"set-filter\"][data-video=\"1\"]').click()"); time.sleep(2.5)
    videos = d.find_elements('css selector', '.post-content video')
    assert len(videos) >= 2
    def state(v):
        return js("return {paused: arguments[0].paused, t: arguments[0].currentTime}", v)
    # 1) 가운데(썸네일의 재생 그림)를 누르면 재생
    v = videos[0]
    js("arguments[0].scrollIntoView({block: 'center'})", v); time.sleep(0.5)
    ActionChains(d).move_to_element(v).click().perform(); time.sleep(3)
    s1 = state(v); print('center click', s1)
    assert not s1['paused'] and s1['t'] > 0
    # 재생 중 화면 클릭은 브라우저 기본 동작 그대로 (재생 중에는 손대지 않음)
    js("arguments[0].pause()", v)
    # 2) 아래 컨트롤 막대의 작은 재생 버튼은 기존처럼 한 번만 재생 (두 번 토글되지 않음)
    v2 = videos[1]
    js("arguments[0].scrollIntoView({block: 'center'})", v2); time.sleep(0.5)
    h = v2.size['height']; w = v2.size['width']
    js("window._clicks = []; arguments[0].addEventListener('click', e => window._clicks.push([e.defaultPrevented, Math.round(arguments[0].getBoundingClientRect().bottom - e.clientY)]))", v2)
    for dy in (16, 22, 28):
        ActionChains(d).move_to_element_with_offset(v2, 0, 0).pause(0.8).move_to_element_with_offset(v2, -w // 2 + 22, h // 2 - dy).pause(0.8).click().perform(); time.sleep(2.5)
        if not state(v2)['paused']:
            break
    print('clicks seen', js('return window._clicks'))
    s2 = state(v2); print('control bar play click', s2)
    assert not s2['paused'] and s2['t'] > 0
    errs = [l for l in d.get_log('browser') if l['level'] == 'SEVERE']
    print('errors', errs)
    print('VIDEO CLICK PASSED')
finally:
    d.quit()
