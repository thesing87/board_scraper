import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, threading, time, json, sqlite3
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN')
import storage, web_server, config
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# 1) 새 DB: 예전 카테고리 설정(자동차=동영상만, 야구=꺼짐)을 게시판이 이어받음
storage.init_db()
g = {x['name']: x for x in storage.list_groups()}
print({n: (x['alert'], x['video_alert']) for n, x in g.items()})
assert (g['싼타페']['alert'], g['싼타페']['video_alert']) == (False, True)
assert (g['삼성']['alert'], g['삼성']['video_alert']) == (False, False)

# 2) 이미 쓰던 DB(알림 컬럼 없음)에 컬럼 추가 시에도 이어받음
db = sqlite3.connect(config.DB_FILE)
db.execute("ALTER TABLE keyword_groups DROP COLUMN alert"); db.execute("ALTER TABLE keyword_groups DROP COLUMN video_alert")
db.execute("UPDATE board_config SET alert = 1 WHERE board = 'baseball'"); db.commit()
storage._initialized = False; storage.init_db()
g = {x['name']: x for x in storage.list_groups()}
assert (g['삼성']['alert'], g['삼성']['video_alert']) == (True, False) and g['싼타페']['alert'] is False

# 3) 수집기가 쓰는 알림 대상: 같은 키워드가 두 게시판에 있으면 둘 다 반환
gid, _ = storage.save_group(None, '싼 모음', [{'board': 'car', 'keyword': '싼타페'}, {'board': 'car', 'keyword': '싼하'}])
assert storage.set_group_alert(gid, 'alert', False) == '싼 모음' and storage.set_group_alert(9999, 'alert', True) is None
t = storage.load_alert_targets()
print('targets 싼타페', t[('car', '싼타페')])
assert [x['name'] for x in t[('car', '싼타페')]] == ['싼타페', '싼 모음']

srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18094), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:18094/'
SHOTS = shot_dir('alert_shots')
o = Options()
for a in ['--headless=new', '--window-size=1440,900', '--force-device-scale-factor=1']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get(BASE); time.sleep(2.5)
    summary = js("return document.getElementById('alert-summary').textContent")
    print('sidebar summary', summary.split('\n'))
    assert '싼타페 · 동영상 글만' in summary and '삼성 · 전체 알림' in summary and '싼 모음 · 동영상 글만' in summary
    # 4) 관리 패널: 게시판별 스위치로 '싼타페' 전체 알림 켜기
    js("document.querySelector('.topbar [data-action=\"open-settings\"]').click()"); time.sleep(0.4)
    rows = js("return [...document.querySelectorAll('#settings-alerts .alert-row-name')].map(e => e.textContent)")
    print('alert rows', rows)
    assert rows == [x['name'] for x in storage.list_groups()]
    js(f"""document.getElementById('admin-pwd-input').value = 'Secr3t!';
        document.querySelector('[data-action="toggle-alert"][data-group-id="{g['싼타페']['id']}"][data-type="alert"]').click();""")
    time.sleep(1.2)
    d.save_screenshot(os.path.join(SHOTS, 'settings.png'))
    after = {x['name']: x for x in storage.list_groups()}
    assert after['싼타페']['alert'] is True and after['캐스퍼']['alert'] is False
    assert '싼타페 · 전체 알림' in js("return document.getElementById('alert-summary').textContent")
    # 암호 없이 바꾸면 거부되고 스위치가 원래대로
    js("window.alert = () => {}; document.getElementById('admin-pwd-input').value = '';"
       f"document.querySelector('[data-action=\"toggle-alert\"][data-group-id=\"{g['캐스퍼']['id']}\"][data-type=\"alert\"]').click();")
    time.sleep(0.5)
    assert js(f"return document.querySelector('[data-action=\"toggle-alert\"][data-group-id=\"{g['캐스퍼']['id']}\"][data-type=\"alert\"]').checked") is False
    errs = [l for l in d.get_log('browser') if l['level'] == 'SEVERE']
    assert not errs, errs
    print('ALERTS E2E PASSED')
finally:
    d.quit()
