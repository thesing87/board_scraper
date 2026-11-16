"""에펨코리아 수집 방식: 새 글은 게시판 글 목록(검색 아님)에서 제목으로 찾고, 키워드 검색(search.php)은 드물게만.
검색이 막혀도 제목으로 찾는 수집은 계속되고 전체 대기(차단 의심)로 번지지 않음"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, importlib.util, contextlib, io
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', TELEGRAM_TOKEN='', CHECK_INTERVAL='90', RUN_WEB_SERVER='0')
for name in [k for k in os.environ if k.startswith(('KEYWORDS_', 'FM_'))]:
    os.environ[name] = ''
    del os.environ[name]
import storage, scraper
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def row(pid, title, comments=0):
    return {'id': str(pid), 'link': f'https://www.fmkorea.com/{pid}', 'title': title, 'author': 'a', 'date': 'd',
            'list_comment_count': comments, 'list_views': '1', 'list_votes': '0'}

# --- 1) 게시판 목록 주소에는 검색어가 없고, 목록이 아닌 화면이면 차단 의심
class Page:
    def __init__(self, html, title):
        self.page_source, self.title, self.opened = html, title, []
    def get(self, url): self.opened.append(url)
    def execute_script(self, script): return ''
scraper.WebDriverWait = lambda d, t: type('W', (), {'until': lambda self, c: True})()
scraper.time.sleep = lambda s: None
normal = ('<div class="bd_lst_wrp"><table class="bd_lst"><tbody><tr class="notice"><td class="title"><a href="/1">공지</a></td></tr>'
          '<tr><td class="title"><a class="hx" href="/8001">싼타페 후기</a><a class="replyNum">3</a></td>'
          '<td class="m_no">10</td><td class="m_no m_no_voted">1</td></tr></tbody></table></div>')
page = Page(normal, '자동차 - 에펨코리아')
rows = scraper.get_board_page_posts(page, 'car', 2)
assert [(r['id'], r['title'], r['list_comment_count']) for r in rows] == [('8001', '싼타페 후기', 3)], rows
assert page.opened == ['https://www.fmkorea.com/index.php?mid=car&page=2'] and 'search' not in page.opened[0], page.opened
try:
    scraper.get_board_page_posts(Page('<html><body>접속 확인 중입니다</body></html>', '에펨코리아 보안 시스템'), 'car')
    raise SystemExit('no block raised')
except scraper.BlockedError as e:
    assert '보안 시스템' in str(e), e
print('BOARD LIST PAGE OK')

# --- 2) 검색 일정: 키워드마다 한 시간에 한 번, 한 주기에 몰리지 않게 나눔. 막히면 검색만 길게 쉼
m.FM_CHECK_INTERVAL, m.FM_SEARCH_INTERVAL = 300, 3600
keys = [('car', f'k{i}') for i in range(29)]
plan = m.SearchSchedule()
now, searched = 10_000.0, []
for cycle in range(12):
    plan.plan(keys, now)
    assert len(plan.planned) <= 3, plan.planned                      # 29개 x 300초 / 3600초 → 한 주기에 3개까지
    for key in keys:
        if plan.wants(key, True, now):
            searched.append(key)
            assert plan.succeeded(key, now) == 0
    now += 300
assert sorted(searched) == sorted(keys) and len(searched) == 29, len(searched)   # 한 시간 동안 키워드마다 한 번씩
# 모은 글이 없는(새로 등록한) 키워드는 차례가 아니어도 검색 (첫 페이지를 채워야 함). 방금 검색했으면 다시 하지 않음
plan.plan(keys, now)
new_key = ('car', '새키워드')
assert plan.wants(new_key, False, now) and not plan.wants(new_key, True, now)
plan.succeeded(new_key, now)
assert not plan.wants(new_key, False, now + 300)
# 막히면 30분 → 1시간 → 2시간 … 최대 6시간 쉬고, 다시 확인할 때는 키워드 하나만
waits = []
for _ in range(6):
    waits.append(plan.blocked(now))
    assert plan.planned == set() and not plan.wants(new_key, False, now + waits[-1] - 1)
    now += waits[-1]
    plan.plan(keys, now + 4000)
    assert len(plan.planned) == 1, plan.planned
assert waits == [1800, 3600, 7200, 14400, 21600, 21600], waits
assert plan.succeeded(keys[0], now) == 6 and plan.block_streak == 0   # 풀리면 이어서 막힌 횟수를 알려 주고 원래대로
# 음수(None)면 검색하지 않음, 0이면 매 주기 모든 키워드
m.FM_SEARCH_INTERVAL = None
plan = m.SearchSchedule(); plan.plan(keys, now)
assert plan.planned == set() and not plan.wants(new_key, False, now)
m.FM_SEARCH_INTERVAL = 0
plan.plan(keys, now)
assert plan.planned == set(keys)
print('SEARCH SCHEDULE OK')

# --- 3) 새 글 고르기
stored = [row(105, 'x'), row(103, 'x'), row(101, 'x')]
listing = [row(106, 'n'), row(105, 'x'), row(104, 'body'), row(103, 'x'), row(102, 'old'), row(100, 'old')]
ids = lambda posts: [p['id'] for p in posts]
assert ids(m.pick_new_posts(listing, stored, 'dcinside', True)) == ['106']                  # 디시: 모은 글이 나오면 멈춤
assert ids(m.pick_new_posts(listing, stored, 'fmkorea', True)) == ['106', '104']            # 검색: 모은 글 사이에 낀 글까지, 더 오래된 글은 제외
assert ids(m.pick_new_posts(listing, stored, 'fmkorea', False)) == ['106', '104', '102', '100']   # 게시판 목록: 모으지 않은 글 모두
far = [row(120, 'n'), row(110, 'n'), row(99, 'old')]
assert ids(m.pick_new_posts(far, stored, 'fmkorea', True)) == ['120', '110']               # 목록에 모은 글이 없으면 가장 새 글보다 새 글만
print('PICK NEW OK')

# --- 4) 게시판 목록 여러 쪽: 지난번에 본 글이 나올 때까지만
pages = {1: [row(n, 't') for n in range(140, 120, -1)], 2: [row(n, 't') for n in range(122, 102, -1)],
         3: [row(n, 't') for n in range(102, 82, -1)]}
opened = []
def fake_pages(driver, board, page=1):
    opened.append(page)
    if page in fail_pages:
        raise RuntimeError('timeout')
    return pages[page]
m.get_board_page_posts = fake_pages
fail_pages, top = set(), {}
assert len(m.read_board_rows(None, 'car', top)) == 20 and opened == [1] and top == {'car': 140}    # 처음엔 첫 쪽만
opened.clear(); top['car'] = 125
assert len(m.read_board_rows(None, 'car', top)) == 20 and opened == [1]                             # 첫 쪽에 지난번 글이 있음
opened.clear(); top['car'] = 110
got = m.read_board_rows(None, 'car', top)
assert opened == [1, 2] and ids(got) == [str(n) for n in range(140, 102, -1)] and top['car'] == 140   # 겹친 글은 한 번만
opened.clear(); top['car'] = 50
with contextlib.redirect_stdout(io.StringIO()):
    assert len(m.read_board_rows(None, 'car', top)) == 58 and opened == [1, 2, 3]                   # 최대 3쪽
opened.clear(); top['car'] = 110; fail_pages = {2}
with contextlib.redirect_stdout(io.StringIO()):
    assert len(m.read_board_rows(None, 'car', top)) == 20 and top['car'] == 110                     # 다음 쪽 실패: 읽은 데까지, 다음에 다시
fail_pages = {1}
try:
    m.read_board_rows(None, 'car', top); raise SystemExit('no error raised')
except RuntimeError:
    pass
print('BOARD PAGES OK')

# --- 5) 메인 루프: 제목 글은 게시판 목록으로 바로, 본문 글은 검색 차례에, 검색이 막혀도 제목 수집은 계속
storage.init_db()
gid, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
storage.set_group_alert(gid, 'alert', True)
storage.save_keyword_post('car', '싼타페', {'id': '100', 'title': '싼타페 지난 글', 'author': 'a', 'date': 'd', 'views': '1',
                          'votes': '0', 'comment_count': '0', 'link': 'https://www.fmkorea.com/100', 'content': [],
                          'videos': [], 'comments': [], 'list_comment_count': 0}, is_new=False)
class FakeDriver:
    hung = False
    def execute_script(self, s): return 1
    def execute_cdp_cmd(self, *a): return {}
    def get(self, url): pass
    def quit(self): pass
m.create_driver = lambda: FakeDriver()
m.FM_CHECK_INTERVAL = 0
m.FM_SEARCH_INTERVAL = 10 ** 9      # 기동 직후 한 번만 검색 차례 (그 뒤로는 게시판 목록만)
state = {'cycle': 0, 'board': [], 'search': [], 'detail': [], 'alerts': [], 'telegram': [], 'sleeps': []}
BODY = {'203': '본문에만 싼타페가 있는 글'}
def fake_board(driver, board, page=1):
    state['board'].append(state['cycle'])
    c = state['cycle']
    # 주기 1부터 제목에 키워드가 있는 새 글, 키워드 없는 글, 본문에만 있는 글이 올라옴
    rows = [row(100, '싼타페 지난 글'), row(99, '다른 글')]
    if c >= 1:
        rows = [row(203, '차 추천 좀'), row(202, '쏘렌토 질문'), row(201, '싼타페 새 글', comments=2 if c >= 2 else 0)] + rows
    return rows
def fake_search(driver, board, keyword, page=1):
    state['search'].append(state['cycle'])
    if state['cycle'] in SEARCH_BLOCKED:
        raise m.BlockedError('게시판 목록이 아닌 페이지 응답 (제목: 에펨코리아 보안 시스템)')
    rows = [row(100, '싼타페 지난 글')]
    if state['cycle'] >= 1:
        rows = [row(203, '차 추천 좀'), row(201, '싼타페 새 글', comments=2)] + rows
    return rows
def fake_detail(driver, info, all_comment_pages=True):
    state['detail'].append((state['cycle'], info['id']))
    body = BODY.get(info['id'], info['title'])
    return dict(info, views='1', votes='0', comment_count=str(info.get('list_comment_count') or 0),
                content=[f'<p>{body}</p>'], videos=[], comments=[])
def fake_sleep(s):
    state['sleeps'].append(s)
    state['cycle'] += 1
    if state['cycle'] > LAST_CYCLE:
        raise KeyboardInterrupt
m.get_board_page_posts = fake_board
m.get_list_page_posts = fake_search
m.scrape_post_detail = fake_detail
m.send_post_alert = lambda post, boards, keyword, board_name, *urls: state['alerts'].append((state['cycle'], post['id']))
m.send_telegram_message = lambda text, reply_markup=None: state['telegram'].append((state['cycle'], text.splitlines()[0]))
m.time.sleep = fake_sleep

# 5-1) 검색이 열려 있을 때: 주기 0에만 검색(기동 직후 차례), 이후는 게시판 목록만
SEARCH_BLOCKED, LAST_CYCLE = set(), 2
with contextlib.redirect_stdout(io.StringIO()):
    m.main()
assert state['board'] == [0, 1, 2] and state['search'] == [0], (state['board'], state['search'])
assert state['alerts'] == [(1, '201')], state['alerts']                       # 제목 글은 검색 없이 바로 알림
# 키워드 없는 글·본문에만 있는 글은 게시판 목록에서는 열지 않음. 주기 2는 목록의 댓글 수가 바뀐 글만 다시 엶
assert state['detail'] == [(1, '201'), (2, '201')], state['detail']
assert state['sleeps'] == [90, 90, 90] and state['telegram'] == [], (state['sleeps'], state['telegram'])
assert [p['id'] for p in storage.recent_keyword_posts('car', '싼타페', 10)] == ['201', '100']
print('TITLE BY BOARD LIST OK')

# 5-2) 검색 차례가 오면 본문에만 키워드가 있는 글도 찾음 (제목으로 먼저 모은 201보다 위에 있어도·아래에 있어도)
state.update(cycle=1, board=[], search=[], detail=[], alerts=[], telegram=[], sleeps=[])
LAST_CYCLE = 1
with contextlib.redirect_stdout(io.StringIO()):
    m.main()                                                                  # 새로 기동 → 첫 주기에 검색 차례
assert state['search'] == [1] and state['alerts'] == [(1, '203')], (state['search'], state['alerts'])
assert [p['id'] for p in storage.recent_keyword_posts('car', '싼타페', 10)] == ['203', '201', '100']
print('BODY BY SEARCH OK')

# 5-3) 검색이 막힘: 그 주기에도 제목 글은 수집·알림, 전체 대기는 늘지 않음, 검색은 쉬었다가 다시 확인
#      (이어서 막히면 텔레그램으로 한 번 알리고, 풀리면 복구도 알림)
def later_board(driver, board, page=1):
    state['board'].append(state['cycle'])
    return [row(300 + state['cycle'], f"싼타페 글 {state['cycle']}"), row(203, '차 추천 좀'), row(201, '싼타페 새 글', comments=2)]
m.get_board_page_posts = later_board
m.FM_SEARCH_INTERVAL = 0            # 검색이 열려 있으면 매 주기 검색
clock = [1_000_000.0]
m.time.time = lambda: clock[0]
def timed_sleep(s):
    clock[0] += 3600                 # 주기 사이에 한 시간이 지난 것으로 (검색 다시 확인 간격: 30분, 1시간, …)
    fake_sleep(s)
m.time.sleep = timed_sleep
state.update(cycle=10, board=[], search=[], detail=[], alerts=[], telegram=[], sleeps=[])
SEARCH_BLOCKED, LAST_CYCLE = {10, 11}, 12
out = io.StringIO()
with contextlib.redirect_stdout(out):
    m.main()
assert state['board'] == [10, 11, 12] and state['search'] == [10, 11, 12], (state['board'], state['search'])
assert state['alerts'] == [(10, '310'), (11, '311'), (12, '312')], state['alerts']
assert state['sleeps'] == [90, 90, 90], state['sleeps']                       # 차단 의심 대기(2배씩)로 번지지 않음
assert state['telegram'] == [(11, '⚠️ 에펨코리아 검색 차단'),
                             (12, '✅ 에펨코리아 검색이 정상으로 돌아왔습니다. (검색 차단 2회 후 복구)')], state['telegram']
assert '[검색 차단]' in out.getvalue() and '차단 의심' not in out.getvalue(), out.getvalue()
print('SEARCH BLOCK OK')

# 5-4) 막힌 뒤 쉬는 동안에는 검색을 두드리지 않음
state.update(cycle=20, board=[], search=[], detail=[], alerts=[], telegram=[], sleeps=[])
SEARCH_BLOCKED, LAST_CYCLE = {20, 21, 22}, 22
def short_sleep(s):
    clock[0] += 600                  # 10분 간격 주기: 30분을 쉬는 동안의 주기는 검색 없이 지나감
    fake_sleep(s)
m.time.sleep = short_sleep
with contextlib.redirect_stdout(io.StringIO()):
    m.main()
assert state['board'] == [20, 21, 22] and state['search'] == [20], (state['board'], state['search'])
assert state['alerts'] == [(20, '320'), (21, '321'), (22, '322')], state['alerts']
print('SEARCH REST OK')

# 5-5) 일시정지를 풀어 다시 수집: 멈춘 동안 올라온 글은 알리지 않음.
#      켠 주기가 에펨코리아를 확인할 차례가 아니어도, 그리고 멈춘 동안의 글이 한참 뒤 검색 차례에야 나와도 마찬가지
storage.set_group_paused(gid, True)             # 이 시험은 새 키워드 하나만
gid2, _ = storage.save_group(None, '쏘렌토', [{'board': 'car', 'keyword': '쏘렌토'}])
storage.set_group_alert(gid2, 'alert', True)
storage.save_keyword_post('car', '쏘렌토', {'id': '90', 'title': '쏘렌토 지난 글', 'author': 'a', 'date': 'd', 'views': '1',
                          'votes': '0', 'comment_count': '0', 'link': 'https://www.fmkorea.com/90', 'content': [],
                          'videos': [], 'comments': [], 'list_comment_count': 0}, is_new=False)
BODY.update({'350': '멈춘 동안 올라온, 본문에만 쏘렌토가 있는 글', '403': '다시 켠 뒤 올라온, 본문에만 쏘렌토가 있는 글'})
def resume_board(driver, board, page=1):
    state['board'].append(state['cycle'])
    c = state['cycle']
    rows = [row(90, '쏘렌토 지난 글')]
    if c >= 4:
        rows = [row(401, '쏘렌토 멈춘 동안 글'), row(400, '다른 글'), row(350, '패밀리카 고민')] + rows
    if c >= 6:
        rows = [row(403, '차 추천 좀'), row(402, '쏘렌토 다시 켠 뒤 글')] + rows
    return rows
def resume_search(driver, board, keyword, page=1):
    state['search'].append(state['cycle'])
    if state['cycle'] == 0:
        return [row(90, '쏘렌토 지난 글')]
    return [row(403, '차 추천 좀'), row(402, '쏘렌토 다시 켠 뒤 글'), row(401, '쏘렌토 멈춘 동안 글'),
            row(350, '패밀리카 고민'), row(90, '쏘렌토 지난 글')]
def resume_sleep(s):
    clock[0] += 60
    state['cycle'] += 1
    if state['cycle'] == 1:
        storage.set_group_paused(gid2, True)     # 주기 1~2: 일시정지
    if state['cycle'] == 3:
        storage.set_group_paused(gid2, False)    # 주기 3에 다시 켬 (에펨코리아 확인 차례가 아닌 주기)
    if state['cycle'] > 8:
        raise KeyboardInterrupt
m.get_board_page_posts = resume_board
m.get_list_page_posts = resume_search
m.time.sleep = resume_sleep
m.FM_CHECK_INTERVAL, m.FM_SEARCH_INTERVAL = 100, 400     # 주기 60초: 에펨코리아는 짝수 주기마다, 검색은 주기 0과 8
state.update(cycle=0, board=[], search=[], detail=[], alerts=[], telegram=[], sleeps=[])
out = io.StringIO()
with contextlib.redirect_stdout(out):
    m.main()
assert state['board'] == [0, 4, 6, 8] and state['search'] == [0, 8], (state['board'], state['search'])
# 401(멈춘 동안, 제목)·350(멈춘 동안, 본문: 검색 차례에야 나옴)은 알림 없음. 402·403(다시 켠 뒤)은 알림
assert state['alerts'] == [(6, '402'), (8, '403')], state['alerts']
assert [p['id'] for p in storage.recent_keyword_posts('car', '쏘렌토', 10)] == ['403', '350', '402', '401', '90']
print('RESUME QUIET OK')
