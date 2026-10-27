import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, importlib.util
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ['OUTPUT_DIR'] = tmp
os.environ['ADMIN_PASSWORD'] = 'Secr3t!'
os.environ['TELEGRAM_TOKEN'] = ''
os.environ['LOG_LEVEL'] = sys.argv[1] if len(sys.argv) > 1 else 'INFO'

spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import storage

class FakeDriver:
    def execute_script(self, s): return 1
    def quit(self): pass

m.create_driver = lambda: (m.log_msg("[시스템] 크롬 드라이버 준비 완료 (headless)"), FakeDriver())[1]
m.run_api_server = lambda: None

cycle = {'n': 0}
def fake_list(driver, board, keyword, page=1):
    _, recent = storage.query_keyword_posts(board, keyword, 0, 20)
    items = [{'id': p['id'], 'link': p['link'], 'title': p['title'], 'author': p['author'], 'date': p['date']} for p in recent]
    if cycle['n'] == 0 and keyword == '싼하':
        items.insert(0, {'id': '99990001', 'link': 'https://www.fmkorea.com/99990001', 'title': '[테스트] 싼타페 하이브리드 출고 후기 - 연비가 생각보다 훨씬 좋네요', 'author': 'a', 'date': 'd'})
    if keyword == '캐스퍼':
        raise Exception("Message: timeout: Timed out receiving message from renderer: 4.998\n  (Session info: chrome=130.0)\nStacktrace:\n#0 0x55d0 <unknown>\n#1 0x55d1 <unknown>")
    return items

def fake_detail(driver, info):
    if info['id'] == '99990001':
        return dict(info, views='1', votes='0', comment_count='0', content=['본문'], images=[], videos=['https://x/v.mp4'], comments=[])
    _, recent = storage.query_keyword_posts('car', '싼하', 0, 3)
    if cycle['n'] == 0 and info['id'] == recent[1]['id']:
        return None   # 원문 삭제
    p = dict(info); p.setdefault('comments', []); p.setdefault('comment_count', '0'); p.setdefault('votes', '0')
    if cycle['n'] == 0 and info['id'] == recent[0]['id']:
        p['comments'] = p['comments'] + [{'author': 'x', 'date': '', 'votes': '0', 'content': ['c'], 'is_reply': False}]
    return p

m.get_list_page_posts = fake_list
m.scrape_post_detail = fake_detail
m.CHECK_INTERVAL = 0
def fake_sleep(s):
    cycle['n'] += 1
    if cycle['n'] >= 2:
        raise KeyboardInterrupt
m.time.sleep = fake_sleep
m.main()
