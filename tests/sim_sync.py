import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, sqlite3, importlib.util, io, contextlib
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LOG_LEVEL='INFO')

import storage, config
# 1) 이전 버전 DB 재현: list_comment_count 컬럼이 없는 posts 테이블로 마이그레이션 후 컬럼 제거
storage.init_db()
conn = sqlite3.connect(config.DB_FILE)
conn.execute('ALTER TABLE posts DROP COLUMN list_comment_count'); conn.commit()
assert 'list_comment_count' not in [r[1] for r in conn.execute('PRAGMA table_info(posts)')]
storage._initialized = False
storage.init_db()   # 컬럼 보충 확인
assert 'list_comment_count' in [r[1] for r in conn.execute('PRAGMA table_info(posts)')]

spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class FakeDriver:
    def execute_script(self, s): return 1
    def quit(self): pass
m.create_driver = lambda: FakeDriver()
m.run_api_server = lambda: None

# 키워드 1개만 대상으로 시나리오 구성
conn.execute("DELETE FROM keyword_group_members WHERE NOT (board = 'car' AND keyword = '싼하')")
conn.execute("DELETE FROM keywords WHERE NOT (board = 'car' AND keyword = '싼하')"); conn.commit()
assert storage.load_keywords()['car'] == ['싼하']
base = storage.recent_keyword_posts('car', '싼하', 25)
assert 'content' not in base[0] and 'comments' not in base[0]
base = [p for p in base if not p.get('is_deleted')][:21]
COMMENT_UP = base[2]['id']        # 첫 주기에 댓글 2개 증가
DELETED = base[5]['id']           # 목록에서 사라짐 + 원문 삭제
EDITED = base[7]['id']            # 목록에서 사라짐 + 원문은 존재 (검색어 제거 수정)
calls = {'detail': [], 'cycle': 0}

def fake_list(driver, board, keyword, page=1):
    items = []
    if True:  # 실제처럼 새 글은 이후 주기에도 목록 맨 위에 계속 남아 있음
        items.append({'id': '10999990001', 'link': 'https://www.fmkorea.com/10999990001', 'title': '싼하 새 글', 'author': 'a', 'date': 'd',
                      'list_comment_count': 0, 'list_views': '1', 'list_votes': '0'})
    for p in base[:20]:
        if p['id'] in (DELETED, EDITED):
            continue
        lc = m.parse_count(p['comment_count']) + (2 if p['id'] == COMMENT_UP else 0)
        items.append({'id': p['id'], 'link': p['link'], 'title': p['title'], 'author': p['author'], 'date': p['date'],
                      'list_comment_count': lc, 'list_views': str(int(m.parse_count(p['views'])) + 5), 'list_votes': p['votes']})
    return items

def fake_detail(driver, info):
    calls['detail'].append((calls['cycle'], info['id']))
    if info['id'] == DELETED:
        return None
    return dict(info, views='1', votes='9', comment_count=str(m.parse_count(info.get('comment_count')) + 2),
                content=['싼하 본문'], videos=[], comments=[])

m.get_list_page_posts = fake_list
m.scrape_post_detail = fake_detail
m.CHECK_INTERVAL = 0
def fake_sleep(s):
    calls['cycle'] += 1
    if calls['cycle'] >= 3:
        raise KeyboardInterrupt
m.time.sleep = fake_sleep

out = io.StringIO()
with contextlib.redirect_stdout(out):
    m.main()
print(out.getvalue())

by_cycle = {c: [i for cc, i in calls['detail'] if cc == c] for c in range(3)}
print('detail calls per cycle:', {c: len(v) for c, v in by_cycle.items()})
print('cycle0 detail ids:', by_cycle[0])
listed = [p['id'] for p in base[:20] if p['id'] not in (DELETED, EDITED)]
extra = set(by_cycle[0]) - {'10999990001', COMMENT_UP, DELETED, EDITED}
print('base[20] id:', base[20]['id'], '| oldest listed id:', min(listed, key=int), '| extra:', extra)
# 가짜 목록은 수집 순서라 글 번호 순이 아님: 목록 최소 번호보다 큰데 목록에 없는 base[20]은 삭제 확인 대상이 맞음
assert sorted(by_cycle[0]) == sorted(['10999990001', COMMENT_UP, DELETED, EDITED]), by_cycle[0]
assert by_cycle[1] == [] and by_cycle[2] == [], by_cycle

row = conn.execute('select list_comment_count, is_deleted from posts where id=?', (COMMENT_UP,)).fetchone()
assert row[0] == m.parse_count(base[2]['comment_count']) + 2, row
assert conn.execute('select is_deleted from posts where id=?', (DELETED,)).fetchone()[0] == 1
assert conn.execute('select is_deleted from posts where id=?', (EDITED,)).fetchone()[0] == 0
other = base[10]['id']
r = conn.execute('select list_comment_count, views from posts where id=?', (other,)).fetchone()
assert r[0] == m.parse_count(base[10]['comment_count']) and r[1] == str(m.parse_count(base[10]['views']) + 5), r
assert conn.execute("select list_comment_count from posts where id='10999990001'").fetchone()[0] == 0
print('SYNC SIM OK')
