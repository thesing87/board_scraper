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

# 에펨코리아 '사람 확인' 화면은 다시 열지 않음 (다시 열어도 그대로라 막힌 동안 요청만 늘어남)
class ListPage:
    def __init__(self, html, title): self.page_source, self.title, self.opened = html, title, 0
    def get(self, url): self.opened += 1
    def execute_script(self, script): return ''
scraper.WebDriverWait = lambda d, t: type('W', (), {'until': lambda self, c: True})()
# (scraper.time과 sites.time은 같은 time 모듈이라 요청 간격·화면 대기도 waits에 함께 쌓임)
if True:  # 아래 두 경우를 한 묶음으로
    waits.clear()
    human_check = ListPage('<html><body><h1>접속 확인 중입니다</h1><div>사람인지 확인이 완료되면 사이트에 자동으로 접속됩니다.</div></body></html>',
                           '에펨코리아 보안 시스템')
    try:
        sites.get_list_page_posts(human_check, 'car', '싼타페'); raise SystemExit('no block raised')
    except scraper.ChallengeError:
        pass
    assert human_check.opened == 1 and sites.LIST_RETRY_SECONDS not in waits, (human_check.opened, waits)
    waits.clear()
    # 그 밖의 목록이 아닌 페이지(일시적인 오류 화면 등)는 전처럼 한 번 더 열어 봄
    error_page = ListPage('<html><body>504 Gateway Time-out</body></html>', '504 Gateway Time-out')
    try:
        sites.get_list_page_posts(error_page, 'car', '싼타페'); raise SystemExit('no block raised')
    except scraper.ChallengeError:
        raise SystemExit('error page treated as human check')
    except scraper.BlockedError:
        pass
    assert error_page.opened == 2 and waits.count(sites.LIST_RETRY_SECONDS) == 1, (error_page.opened, waits)
print('NO RETRY ON HUMAN CHECK OK')

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
# 시험에서는 쉬는 시간이 실제로 흐르지 않으므로 에펨코리아도 매 주기 확인하게 함 (FM_CHECK_INTERVAL은 test_request_gap에서)
m.FM_CHECK_INTERVAL = 0
state = {'cycle': 0, 'sleeps': [], 'telegram': []}
BLOCKED_CYCLES = {1, 3, 4}          # 1: 한 번만 실패, 3~4: 이어서 실패
def fake_board(driver, board, page=1):
    if state['cycle'] in BLOCKED_CYCLES:
        raise m.BlockedError('게시판 목록이 아닌 페이지 응답 (제목: www.fmkorea.com)')
    return []
def fake_list(driver, board, keyword, page=1):
    return [{'id': '101', 'link': '/101', 'title': 't', 'author': 'a', 'date': 'd', 'list_comment_count': 0, 'list_views': None, 'list_votes': None}]
m.get_list_page_posts = fake_list
import common; common.search_every_cycle(m)
m.get_board_page_posts = fake_board
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

# --- 4) 에펨코리아만 막히면 에펨코리아만 쉬고, 디시인사이드는 원래 주기로 계속 수집
storage.add_category('dc:car_new1')
storage.set_category_checked('dc:car_new1', True, page_name='자동차 갤러리')
storage.save_group(None, '디시 싼타페', [{'board': 'dc:car_new1', 'keyword': '싼타페'}])
storage.save_keyword_post('dc:car_new1', '싼타페', {'id': 'dc-car_new1-7', 'title': 't', 'author': 'a', 'date': 'd', 'views': '1',
                          'votes': '0', 'comment_count': '0', 'link': 'https://gall.dcinside.com/7', 'content': [], 'videos': [],
                          'comments': []}, is_new=False)
storage.mark_first_page_filled('dc:car_new1', '싼타페')
# 보관한 글: 막힌 사이트의 글은 풀릴 때까지 열지 않음
storage.save_keyword_post('car', '싼타페', {'id': '55', 'title': 'old', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                          'comment_count': '0', 'link': '/55', 'content': [], 'videos': [], 'comments': []}, is_new=False)
m.saved_posts_to_check = lambda minutes, exclude, limit: [{'id': '55', 'title': 'old', 'author': 'a', 'date': 'd', 'link': '/55',
                                                           'list_comment_count': 0}]
m.mark_saved_checked = lambda post_id: None
state = {'cycle': 0, 'sleeps': [], 'telegram': [], 'lists': [], 'details': []}
FM_BLOCKED = {1, 3}                  # 1주기에 막힘 → 180초 뒤(3주기) 다시 확인해도 막힘 → 360초 뒤(7주기) 복구
# 에펨코리아는 게시판 글 목록을 먼저 읽으므로 차단은 게시판 목록에서 드러남 (디시는 키워드 검색 목록)
def mixed_board(driver, board, page=1):
    state['lists'].append((state['cycle'], sites.board_site(board)))
    if state['cycle'] in FM_BLOCKED:
        raise m.BlockedError('게시판 목록이 아닌 페이지 응답 (제목: 에펨코리아 보안 시스템)')
    return []
def mixed_list(driver, board, keyword, page=1):
    if board == 'car':
        return [{'id': '101', 'link': '/101', 'title': 't', 'author': 'a', 'date': 'd', 'list_comment_count': 0, 'list_views': None, 'list_votes': None}]
    state['lists'].append((state['cycle'], sites.board_site(board)))
    return [{'id': 'dc-car_new1-7', 'link': 'https://gall.dcinside.com/7', 'title': 't', 'author': 'a', 'date': 'd',
             'list_comment_count': 0, 'list_views': None, 'list_votes': None}]
def fake_detail(driver, info, all_comment_pages=True):
    state['details'].append((state['cycle'], info['id']))
    return dict(info, views='1', votes='0', comment_count='0', content=[], videos=[], comments=[])
m.get_list_page_posts = mixed_list
m.get_board_page_posts = mixed_board
m.scrape_post_detail = fake_detail
def mixed_sleep(s):
    state['sleeps'].append(s)
    state['cycle'] += 1
    if state['cycle'] > 8:
        raise KeyboardInterrupt
m.time.sleep = mixed_sleep
with contextlib.redirect_stdout(io.StringIO()):
    m.main()
assert state['sleeps'] == [90] * 9, state['sleeps']                                           # 전체 주기는 그대로
assert [c for c, s in state['lists'] if s == 'dcinside'] == list(range(9)), state['lists']    # 디시는 매 주기 수집
assert [c for c, s in state['lists'] if s == 'fmkorea'] == [0, 1, 3, 7, 8], state['lists']    # 에펨코리아만 쉼 (180초, 360초)
assert state['telegram'] == [(3, '⚠️ 에펨코리아 접속 차단 의심'),
                             (7, '✅ 에펨코리아 접속이 정상으로 돌아왔습니다. (차단 의심 2회 후 복구)')], state['telegram']
assert [c for c, i in state['details'] if i == '55'] == [0, 7, 8], state['details']           # 막힌 동안 에펨코리아 글은 열지 않음
status = m.runtime_status.snapshot()
assert status['block_streak'] == 0 and status['blocked_label'] == '' and status['block_retry_at'] is None, status
print('PER-SITE BACKOFF OK')

# --- 5) 사람 확인 화면으로 막히면 잠깐씩 늘려 가며 확인하지 않고 길게 쉼 (첫 번째부터 알림), 수집기를 다시 띄워도 이어서 쉼
m.FM_CHALLENGE_REST = 270            # 시험용: 주기 3번(90초 x 3) 동안 쉼
assert m.wait_text(6 * 3600) == '6시간 0분' and m.wait_text(240) == '4분 0초'
def run_main(challenge_cycles, last_cycle):
    state.update(cycle=0, sleeps=[], telegram=[], lists=[], details=[])
    def board(driver, board, page=1):
        state['lists'].append((state['cycle'], sites.board_site(board)))
        if state['cycle'] in challenge_cycles:
            raise scraper.ChallengeError('게시판 목록이 아닌 페이지 응답 (제목: 에펨코리아 보안 시스템)')
        return []
    def sleep(s):
        state['sleeps'].append(s)
        state['cycle'] += 1
        if state['cycle'] > last_cycle:
            raise KeyboardInterrupt
    m.get_board_page_posts, m.time.sleep = board, sleep
    with contextlib.redirect_stdout(io.StringIO()):
        m.main()
    return [c for c, s in state['lists'] if s == 'fmkorea'], [c for c, s in state['lists'] if s == 'dcinside']

# 1주기에 사람 확인 화면 → 2~3주기는 요청 없음 → 4주기에 다시 확인해 복구
fm, dc = run_main({1}, 5)
assert fm == [0, 1, 4, 5] and dc == list(range(6)), (fm, dc)
assert state['telegram'] == [(1, '⚠️ 에펨코리아 접속 차단 의심'),
                             (4, '✅ 에펨코리아 접속이 정상으로 돌아왔습니다. (차단 의심 1회 후 복구)')], state['telegram']
assert not storage.get_meta(m.BLOCK_REST_META + 'fmkorea')             # 풀리면 쉬는 기록을 지움
# 쉬는 중에 수집기를 다시 띄우면 처음부터 두드리지 않고 남은 시간만큼 이어서 쉼 (복구 알림도 감)
fm, _ = run_main({1}, 1)
assert fm == [0, 1] and float(storage.get_meta(m.BLOCK_REST_META + 'fmkorea')) > m.time.time()
fm, dc = run_main(set(), 4)
assert fm == [3, 4] and dc == list(range(5)), (fm, dc)
assert state['telegram'] == [(3, '✅ 에펨코리아 접속이 정상으로 돌아왔습니다. (차단 의심 1회 후 복구)')], state['telegram']
print('CHALLENGE REST OK')
