"""서로 다른 키워드(다른 게시판)에 같은 새 글이 걸릴 때 알림: 알림은 한 번만, 처음 수집한 키워드의 게시판이
알림을 꺼 두었으면 나중에 걸린 키워드의 게시판(알림 켬)에서 보냄"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, importlib.util, contextlib, io
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

storage.init_db()
casper, _ = storage.save_group(None, '캐스퍼', [{'board': 'car', 'keyword': '캐스퍼'}])
ev, _ = storage.save_group(None, '전기차', [{'board': 'car', 'keyword': 'EV'}])
order = storage.load_keywords()['car']
assert sorted(order) == ['EV', '캐스퍼'], order

class FakeDriver:
    def execute_script(self, s): return 1
    def quit(self): pass
m.create_driver = lambda: FakeDriver()
m.run_api_server = lambda: None
m.send_telegram_message = lambda text: None
m.restart_if_hung = lambda driver: driver
state = {'cycle': 0, 'new_id': None, 'alerts': []}

def info(pid, title):
    return {'id': pid, 'title': title, 'author': 'a', 'date': '', 'link': f'/{pid}', 'list_comment_count': 0,
            'list_views': '1', 'list_votes': '0'}
def fake_list(driver, board, keyword, page=1):
    # 첫 주기는 지난 글 하나(첫 페이지 저장), 다음 주기부터 두 키워드 모두에 걸리는 새 글
    posts = [info('100', '캐스퍼 EV 지난 글')]
    if state['new_id']:
        posts.insert(0, info(state['new_id'], '캐스퍼 일렉트릭 EV 시승기'))
    return posts
def fake_detail(driver, post_info, all_comment_pages=True):
    return dict(post_info, views='1', votes='0', comment_count='0', content=[], videos=[], comments=[])
def fake_sleep(s):
    state['cycle'] += 1
    raise KeyboardInterrupt
m.get_list_page_posts = fake_list
m.scrape_post_detail = fake_detail
m.send_post_alert = lambda post, boards, keyword, board_name, *urls: state['alerts'].append((post['id'], boards, keyword))
m.time.sleep = fake_sleep

def run_cycle(new_id):
    state.update(new_id=new_id, alerts=[])
    with contextlib.redirect_stdout(io.StringIO()):
        m.main()
    return state['alerts']

assert run_cycle(None) == []   # 첫 주기: 첫 페이지 저장만 (알림 없음)

def set_alerts(casper_on, ev_on):
    for gid, on in ((casper, casper_on), (ev, ev_on)):
        storage.set_group_alert(gid, 'alert', on)
        storage.set_group_alert(gid, 'video_alert', on)

# 1) 처음 확인하는 키워드의 게시판은 알림 끔, 나중 키워드의 게시판은 알림 켬 → 나중 키워드에서 한 번
first, second = order
names = {'캐스퍼': '캐스퍼', 'EV': '전기차'}
set_alerts(casper_on=(second == '캐스퍼'), ev_on=(second == 'EV'))
alerts = run_cycle('201')
assert alerts == [('201', [names[second]], second)], alerts
print('LATER KEYWORD ALERT OK')

# 2) 처음 키워드에서 알림을 보냈으면 나중 키워드에서는 보내지 않음 (둘 다 알림 켬)
set_alerts(True, True)
alerts = run_cycle('202')
assert alerts == [('202', [names[first]], first)], alerts
print('NO DUPLICATE OK')

# 3) 둘 다 알림 끔 → 알림 없음. 기억은 남았다가 하루 한 번 정리로 지워짐
set_alerts(False, False)
assert run_cycle('203') == []
with storage._db() as conn:
    assert conn.execute("SELECT post_id FROM unalerted_posts").fetchall()[0]['post_id'] == '203'
    conn.execute("UPDATE unalerted_posts SET collected_at = '2000-01-01 00:00:00'")
    conn.commit()
assert storage.prune_unalerted_posts(24) == 1
print('UNALERTED OK')
