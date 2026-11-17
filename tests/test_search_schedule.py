"""에펨코리아 수집 방식: 키워드 검색만, 키워드마다 한 시간에 한 번씩 주기마다 몇 개로 나눠서.
차례가 아닌 키워드는 그 주기에 아무 요청도 보내지 않음"""
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

# --- 1) 검색 목록 주소, 사람 확인 화면이면 ChallengeError
class Page:
    def __init__(self, html, title):
        self.page_source, self.title, self.opened = html, title, []
    def get(self, url): self.opened.append(url)
    def execute_script(self, script): return ''
scraper.WebDriverWait = lambda d, t: type('W', (), {'until': lambda self, c: True})()
real_sleep, scraper.time.sleep = scraper.time.sleep, lambda s: None
normal = ('<div class="bd_lst_wrp"><table class="bd_lst"><tbody><tr class="notice"><td class="title"><a href="/1">공지</a></td></tr>'
          '<tr><td class="title"><a class="hx" href="/8001">싼타페 후기</a><a class="replyNum">3</a></td>'
          '<td class="m_no">10</td><td class="m_no m_no_voted">1</td></tr></tbody></table></div>')
page = Page(normal, '싼타페 - 자동차 - 에펨코리아')
rows = scraper.get_list_page_posts(page, 'car', '싼타페')
assert [(r['id'], r['title'], r['list_comment_count']) for r in rows] == [('8001', '싼타페 후기', 3)], rows
assert len(page.opened) == 1 and 'mid=car' in page.opened[0] and 'search_keyword=' in page.opened[0], page.opened
try:
    scraper.get_list_page_posts(Page('<html><body>접속 확인 중입니다</body></html>', '에펨코리아 보안 시스템'), 'car', '싼타페')
    raise SystemExit('no block raised')
except scraper.ChallengeError as e:
    assert '보안 시스템' in str(e), e
assert not hasattr(scraper, 'get_board_page_posts') and not hasattr(m, 'read_board_rows')    # 제목으로 찾는 수집은 없앰
scraper.time.sleep = real_sleep
print('SEARCH LIST PAGE OK')

# --- 2) 검색 일정: 키워드마다 한 시간에 한 번, 한 주기에 몰리지 않게 나눔
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
            plan.succeeded(key, now)
    now += 300
assert sorted(searched) == sorted(keys) and len(searched) == 29, len(searched)   # 한 시간 동안 키워드마다 한 번씩
# 검색에 실패한 키워드는 기록하지 않아 다음 주기에 다시 차례가 됨 (가장 오래된 것부터)
plan.plan(keys, now)
first = sorted(plan.planned)
plan.plan(keys, now + 300)
assert sorted(plan.planned) == first, (first, plan.planned)
# 모은 글이 없는(새로 등록한) 키워드는 차례가 아니어도 검색 (첫 페이지를 채워야 함). 방금 검색했으면 다시 하지 않음
new_key = ('car', '새키워드')
assert plan.wants(new_key, False, now) and not plan.wants(new_key, True, now)
plan.succeeded(new_key, now)
assert not plan.wants(new_key, False, now + 300)
# 간격이 0이면 매 주기 모든 키워드
m.FM_SEARCH_INTERVAL = 0
plan.plan(keys, now)
assert plan.planned == set(keys)
print('SEARCH SCHEDULE OK')

# --- 3) 새 글 고르기
stored = [row(105, 'x'), row(103, 'x'), row(101, 'x')]
listing = [row(106, 'n'), row(105, 'x'), row(104, 'missed'), row(103, 'x'), row(102, 'old'), row(100, 'old')]
ids = lambda posts: [p['id'] for p in posts]
assert ids(m.pick_new_posts(listing, stored, 'dcinside')) == ['106']                 # 디시: 모은 글이 나오면 멈춤
assert ids(m.pick_new_posts(listing, stored, 'fmkorea')) == ['106', '104']           # 에펨: 모은 글 사이에 빠진 글까지, 더 오래된 글은 제외
far = [row(120, 'n'), row(110, 'n'), row(99, 'old')]
assert ids(m.pick_new_posts(far, stored, 'fmkorea')) == ['120', '110']               # 목록에 모은 글이 없으면 가장 새 글보다 새 글만
print('PICK NEW OK')

# --- 4) 메인 루프: 주기마다 차례인 키워드만 검색하고 나머지는 요청 없음. 새 글은 그 키워드의 차례에 찾아 알림
storage.init_db()
KEYWORDS = ['k1', 'k2', 'k3', 'k4']
gid, _ = storage.save_group(None, '차', [{'board': 'car', 'keyword': k} for k in KEYWORDS])
storage.set_group_alert(gid, 'alert', True)
for n, k in enumerate(KEYWORDS, 1):
    storage.save_keyword_post('car', k, {'id': str(100 + n), 'title': f'{k} 지난 글', 'author': 'a', 'date': 'd', 'views': '1',
                              'votes': '0', 'comment_count': '0', 'link': f'https://www.fmkorea.com/{100 + n}', 'content': [],
                              'videos': [], 'comments': [], 'list_comment_count': 0}, is_new=False)
class FakeDriver:
    hung = False
    def execute_script(self, s): return 1
    def execute_cdp_cmd(self, *a): return {}
    def get(self, url): pass
    def quit(self): pass
m.create_driver = lambda: FakeDriver()
m.FM_CHECK_INTERVAL, m.FM_SEARCH_INTERVAL = 300, 1200      # 키워드 4개 → 5분 주기마다 하나씩, 키워드마다 20분에 한 번
state = {'cycle': 0, 'search': [], 'detail': [], 'alerts': [], 'telegram': [], 'sleeps': []}
clock = [1_000_000.0]
m.time.time = lambda: clock[0]
def fake_search(driver, board, keyword, page=1):
    state['search'].append((state['cycle'], keyword))
    n = KEYWORDS.index(keyword) + 1
    rows = [row(100 + n, f'{keyword} 지난 글')]
    if keyword == 'k1' and state['cycle'] >= 1:
        rows = [row(201, 'k1 새 글')] + rows            # 주기 1에 올라온 글: k1의 다음 차례(주기 4)에 찾음
    return rows
def fake_detail(driver, info, all_comment_pages=True):
    state['detail'].append((state['cycle'], info['id']))
    return dict(info, views='1', votes='0', comment_count=str(info.get('list_comment_count') or 0),
                content=[f"<p>{BODY.get(info['id'], info['title'])}</p>"], videos=[], comments=[])
BODY = {}
def fake_sleep(s):
    state['sleeps'].append(s)
    clock[0] += 300
    state['cycle'] += 1
    if state['cycle'] > LAST_CYCLE:
        raise KeyboardInterrupt
m.get_list_page_posts = fake_search
m.scrape_post_detail = fake_detail
m.send_post_alert = lambda post, boards, keyword, board_name, *urls: state['alerts'].append((state['cycle'], post['id']))
m.send_telegram_message = lambda text, reply_markup=None: state['telegram'].append((state['cycle'], text.splitlines()[0]))
m.time.sleep = fake_sleep
LAST_CYCLE = 4
with contextlib.redirect_stdout(io.StringIO()):
    m.main()
assert state['search'] == [(0, 'k1'), (1, 'k2'), (2, 'k3'), (3, 'k4'), (4, 'k1')], state['search']
assert state['alerts'] == [(4, '201')] and state['detail'] == [(4, '201')], (state['alerts'], state['detail'])
assert state['sleeps'] == [90] * 5 and state['telegram'] == [], (state['sleeps'], state['telegram'])
assert [p['id'] for p in storage.recent_keyword_posts('car', 'k1', 10)] == ['201', '101']
print('SEARCH TURNS OK')

# --- 5) 일시정지를 풀어 다시 수집: 차례를 기다리지 않고 바로 검색하고, 멈춘 동안 올라온 글은 알리지 않음. 그 뒤의 새 글은 알림
storage.set_group_paused(gid, True)             # 이 시험은 새 키워드 하나만
gid2, _ = storage.save_group(None, '쏘렌토', [{'board': 'car', 'keyword': '쏘렌토'}])
storage.set_group_alert(gid2, 'alert', True)
storage.save_keyword_post('car', '쏘렌토', {'id': '90', 'title': '쏘렌토 지난 글', 'author': 'a', 'date': 'd', 'views': '1',
                          'votes': '0', 'comment_count': '0', 'link': 'https://www.fmkorea.com/90', 'content': [],
                          'videos': [], 'comments': [], 'list_comment_count': 0}, is_new=False)
BODY.update({'350': '멈춘 동안 올라온, 본문에만 쏘렌토가 있는 글'})
def resume_search(driver, board, keyword, page=1):
    state['search'].append(state['cycle'])
    c = state['cycle']
    rows = [row(90, '쏘렌토 지난 글')]
    if c >= 2:
        rows = [row(401, '쏘렌토 멈춘 동안 글'), row(350, '패밀리카 고민')] + rows
    if c >= 5:
        rows = [row(402, '쏘렌토 다시 켠 뒤 글')] + rows
    return rows
def resume_sleep(s):
    clock[0] += 300
    state['cycle'] += 1
    if state['cycle'] == 1:
        storage.set_group_paused(gid2, True)     # 주기 1~2: 일시정지
    if state['cycle'] == 3:
        storage.set_group_paused(gid2, False)    # 주기 3에 다시 켬 (지난 검색에서 20분이 지나지 않았어도 바로 검색)
    if state['cycle'] > 7:
        raise KeyboardInterrupt
m.get_list_page_posts = resume_search
m.time.sleep = resume_sleep
state.update(cycle=0, search=[], detail=[], alerts=[], telegram=[], sleeps=[])
with contextlib.redirect_stdout(io.StringIO()):
    m.main()
assert state['search'] == [0, 3, 7], state['search']
# 401·350(멈춘 동안)은 알림 없이 새 글로만, 402(다시 켜고 한 번 확인한 뒤)는 알림
assert state['alerts'] == [(7, '402')], state['alerts']
assert [p['id'] for p in storage.recent_keyword_posts('car', '쏘렌토', 10)] == ['402', '401', '350', '90']
print('RESUME QUIET OK')
