import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, importlib.util, io, contextlib
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LOG_LEVEL='INFO')

# --- 1) 목록 페이지 판정 단위 테스트
import scraper
class Page:
    def __init__(self, html, title): self.page_source, self.title = html, title
    def get(self, url): pass
scraper.WebDriverWait = lambda d, t: type('W', (), {'until': lambda self, c: True})()
scraper.time.sleep = lambda s: None
normal = '<div class="bd_lst_wrp"><table class="bd_lst"><tbody><tr><td class="title"><a class="hx" href="/index.php?document_srl=123">t</a><a class="replyNum">3</a></td><td class="m_no">10</td><td class="m_no m_no_voted">1</td></tr></tbody></table></div>'
empty = '<div class="bd_lst_wrp"><p>등록된 글이 없습니다.</p></div>'
challenge = '<html><body><h1>잠시만 기다려 주세요</h1><p>보안 확인 중</p></body></html>'
rows = scraper.get_list_page_posts(Page(normal, '캐스퍼 - 자동차 - 에펨코리아'), 'car', 'x')
assert rows[0]['id'] == '123' and rows[0]['list_comment_count'] == 3, rows
assert scraper.get_list_page_posts(Page(empty, 'x - 자동차 - 에펨코리아'), 'car', 'x') == []
try:
    scraper.get_list_page_posts(Page(challenge, 'Just a moment...'), 'car', 'x'); raise SystemExit('no block raised')
except scraper.BlockedError as e:
    assert 'Just a moment' in str(e), e
print('LIST DETECT OK')

# --- 2) 메인 루프 백오프 흐름
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class FakeDriver:
    def execute_script(self, s): return 1
    def quit(self): pass
m.create_driver = lambda: FakeDriver()
m.run_api_server = lambda: None
import storage
state = {'cycle': 0, 'list_calls': [], 'sleeps': [], 'telegram': []}
# 0: 정상, 1~2: 차단 페이지, 3: 모든 목록 요청 예외(접속 불가), 4: 정상(복구)
def fake_list(driver, board, keyword, page=1):
    state['list_calls'].append(state['cycle'])
    c = state['cycle']
    if c in (1, 2):
        raise m.BlockedError('게시판 목록이 아닌 페이지 응답 (제목: Just a moment...)')
    if c == 3:
        raise TimeoutError('Message: timeout: Timed out receiving message from renderer\nStacktrace: ...')
    recent = storage.recent_keyword_posts(board, keyword, 20)
    return [{'id': p['id'], 'link': p['link'], 'title': p['title'], 'author': p['author'], 'date': p['date'],
             'list_comment_count': p.get('list_comment_count') if p.get('list_comment_count') is not None else m.parse_count(p['comment_count']),
             'list_views': None, 'list_votes': None} for p in recent if not p.get('is_deleted')]
m.get_list_page_posts = fake_list
m.scrape_post_detail = lambda d, info: dict(info, views='1', votes='0', comment_count='0', content=[], videos=[], comments=[])
m.send_telegram_message = lambda text, reply_markup=None: state['telegram'].append(text.splitlines()[0])
def fake_sleep(s):
    state['sleeps'].append(s)
    state['cycle'] += 1
    if state['cycle'] > 4:
        raise KeyboardInterrupt
m.time.sleep = fake_sleep

out = io.StringIO()
with contextlib.redirect_stdout(out):
    m.main()
print('\n'.join(l for l in out.getvalue().splitlines() if '차단' in l or '복구' in l or '주기 완료' in l))
calls_per_cycle = {c: state['list_calls'].count(c) for c in range(5)}
print('list calls per cycle:', calls_per_cycle)
print('sleeps:', state['sleeps'])
print('telegram:', state['telegram'])
kw_count = sum(len(v) for v in storage.load_keywords().values())
assert calls_per_cycle[0] == kw_count and calls_per_cycle[1] == 1 and calls_per_cycle[2] == 1, calls_per_cycle
assert calls_per_cycle[3] == kw_count and calls_per_cycle[4] == kw_count, calls_per_cycle
assert state['sleeps'] == [90, 180, 360, 720, 90], state['sleeps']
assert state['telegram'] == ['⚠️ 에펨코리아 접속 차단 의심', '✅ 에펨코리아 접속이 정상으로 돌아왔습니다. (차단 의심 3회 후 복구)'], state['telegram']
print('BACKOFF SIM OK')
