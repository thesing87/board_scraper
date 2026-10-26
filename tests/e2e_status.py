import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA_DIR, shot_dir
import shutil, tempfile, threading, time
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(DATA_DIR, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN')
import storage, web_server, runtime_status, config
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
now = runtime_status.now()
runtime_status.update(cycles=12, chrome_started_at=now, chrome_restarts=1, next_check_at=now,
                      last_cycle={'finished_at': now, 'seconds': 64, 'new': 2, 'updated': 3, 'deleted': 0, 'errors': 1},
                      last_backup={'at': now, 'file': 'board-20261027.db'}, last_prune={'at': now, 'deleted': 4})
config.log_msg('[오류] 자동차/싼하 목록 조회 실패: timeout <b>x</b>', 'WARN')
srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18102), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
SHOTS = shot_dir('status')
o = Options()
for a in ['--headless=new', '--window-size=1440,1000']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get('http://127.0.0.1:18102/'); time.sleep(2.5)
    js("document.querySelector('.topbar [data-action=\"open-settings\"]').click()"); time.sleep(1)
    rows = js("return [...document.querySelectorAll('#settings-status .status-row')].map(r => r.textContent.replace(/\\s+/g, ' ').trim())")
    print('\n'.join(rows))
    text = ' | '.join(rows)
    assert '정상 수집 중' in text and '64초' in text and '새 글 2, 갱신 3, 오류 1' in text and '주기 12회' in text
    assert 'board-20261027.db' in text and '4건 정리' in text and '재시작 1회' in text
    # 오류 메시지의 태그는 글자로 표시 (HTML로 해석하지 않음)
    assert '<b>x</b>' in text and not js("return !!document.querySelector('#settings-status b')")
    # 차단 의심 상태 + 새로고침 버튼
    runtime_status.update(block_streak=2)
    js("document.querySelector('[data-action=\"refresh-status\"]').click()"); time.sleep(1)
    assert '차단 의심 · 연속 2회' in js("return document.getElementById('settings-status').textContent")
    card = d.find_element('id', 'settings-status')
    js("arguments[0].scrollIntoView({block: 'center'})", card); time.sleep(0.3)
    d.save_screenshot(os.path.join(SHOTS, 'status.png'))
    errs = [l for l in d.get_log('browser') if l['level'] == 'SEVERE']
    assert not errs, errs
    print('STATUS E2E PASSED')
finally:
    d.quit()
