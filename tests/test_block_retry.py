"""차단 의심 오탐 줄이기: 목록이 아닌 페이지가 한 번 오면 잠시 뒤 한 번 더 열어 보고,
텔레그램 알림은 차단 의심이 두 주기 이어졌을 때만 (알렸을 때만 복구도 알림)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, importlib.util, io, contextlib
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='INFO', TELEGRAM_TOKEN='', CHECK_INTERVAL='90', RUN_WEB_SERVER='0')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, sites, scraper, dcinside

# --- 1) 목록 다시 시도 (sites.get_list_page_posts)
waits = []
sites.time.sleep = waits.append
class Flaky:
    def __init__(self, failures):
        self.failures, self.calls = failures, 0
    def __call__(self, driver, board, keyword, page=1):
        self.calls += 1
        if self.calls <= self.failures:
            raise scraper.BlockedError('갤러리 목록이 아닌 페이지 응답 (제목: gall.dcinside.com)')
        return [{'id': 'dc-car_new1-1'}]
real = dcinside.get_list_page_posts
try:
    dcinside.get_list_page_posts = once = Flaky(1)
    assert sites.get_list_page_posts(None, 'dc:car_new1', '싼타페') == [{'id': 'dc-car_new1-1'}]
    assert once.calls == 2 and waits == [sites.LIST_RETRY_SECONDS], (once.calls, waits)      # 한 번 실패는 다시 열어 성공
    dcinside.get_list_page_posts = twice = Flaky(2)
    try:
        sites.get_list_page_posts(None, 'dc:car_new1', '싼타페'); raise SystemExit('no block raised')
    except scraper.BlockedError:
        pass
    assert twice.calls == 2                                                                  # 두 번 다 실패하면 차단 의심
    dcinside.get_list_page_posts = ok = Flaky(0)
    sites.get_list_page_posts(None, 'dc:car_new1', '싼타페')
    assert ok.calls == 1 and len(waits) == 2                                                 # 정상이면 기다리지 않음
finally:
    dcinside.get_list_page_posts = real
print('LIST RETRY OK')

# --- 2) 목록이 아닌 페이지의 내용 기록: 읽지 못해도 수집은 계속
class Page:
    def __init__(self, result): self.result = result
    def execute_script(self, script):
        if isinstance(self.result, Exception): raise self.result
        return self.result
out = io.StringIO()
with contextlib.redirect_stdout(out):
    os.environ['LOG_LEVEL'] = 'DEBUG'
    scraper.log_unexpected_page(Page({'status': 429, 'url': 'https://gall.dcinside.com/x', 'text': ''}), 'dc:car_new1/싼타페')
    scraper.log_unexpected_page(Page(RuntimeError('boom')), 'dc:car_new1/싼타페')
with open(os.path.join(os.environ['OUTPUT_DIR'], 'logs', 'debug.log'), encoding='utf-8') as f:
    logged = f.read()
assert '응답 코드 429' in logged and '(빈 화면)' in logged and '내용을 읽지 못함: boom' in logged, logged
print('PAGE LOG OK')

# --- 3) 메인 루프: 한 주기만 실패하면 알림 없음, 두 주기 이어지면 알림과 복구 알림
storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
storage.save_keyword_post('car', '싼타페', {'id': '101', 'title': 't', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                          'comment_count': '0', 'link': '/101', 'content': [], 'videos': [], 'comments': []}, is_new=False)
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class FakeDriver:
    hung = False
    def execute_script(self, s): return 1
    def execute_cdp_cmd(self, *a): return {}
    def get(self, url): pass
    def quit(self): pass
m.create_driver = lambda: FakeDriver()
state = {'cycle': 0, 'sleeps': [], 'telegram': []}
BLOCKED_CYCLES = {1, 3, 4}          # 1: 한 번만 실패, 3~4: 이어서 실패
def fake_list(driver, board, keyword, page=1):
    if state['cycle'] in BLOCKED_CYCLES:
        raise m.BlockedError('게시판 목록이 아닌 페이지 응답 (제목: www.fmkorea.com)')
    return [{'id': '101', 'link': '/101', 'title': 't', 'author': 'a', 'date': 'd', 'list_comment_count': 0, 'list_views': None, 'list_votes': None}]
m.get_list_page_posts = fake_list
m.send_telegram_message = lambda text, reply_markup=None: state['telegram'].append((state['cycle'], text.splitlines()[0]))
def fake_sleep(s):
    state['sleeps'].append(s)
    state['cycle'] += 1
    if state['cycle'] > 5:
        raise KeyboardInterrupt
m.time.sleep = fake_sleep
with contextlib.redirect_stdout(io.StringIO()):
    m.main()
assert state['sleeps'] == [90, 180, 90, 180, 360, 90], state['sleeps']        # 대기 늘리기는 그대로
assert state['telegram'] == [(4, '⚠️ 에펨코리아 접속 차단 의심'),
                             (5, '✅ 에펨코리아 접속이 정상으로 돌아왔습니다. (차단 의심 2회 후 복구)')], state['telegram']
print('BLOCK ALERT OK')
