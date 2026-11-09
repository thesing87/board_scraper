import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage

# 안 읽은 글 보기: 연 시각 이후 읽은 글은 남고, 그 뒤 수집된 새 글은 끼어들지 않아 다음 페이지가 밀리지 않음
def post(pid):
    return {'id': pid, 'title': pid, 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/' + pid, 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}

gid, _ = storage.save_group(None, '캐스퍼', [{'board': 'car', 'keyword': '캐스퍼'}])
for i in range(1, 7):
    storage.save_keyword_post('car', '캐스퍼', post(str(800 + i)), is_new=True)
snap = '2026-01-01 12:00:00'
with storage._db() as conn, conn:
    conn.execute("UPDATE keyword_posts SET matched_at = '2026-01-01 11:00:00'")
ids = lambda rows: [p['id'] for p in rows]
page1 = ids(storage.query_all_posts(0, 3, group_id=gid, unread_since=snap)[1])
assert page1 == ['806', '805', '804'], page1
# 1페이지를 읽고, 그 사이 새 글이 수집됨
with storage._db() as conn, conn:
    for pid in page1:
        conn.execute("INSERT INTO read_posts(post_id, read_at, first_read_at) VALUES(?, '2026-01-01 12:05:00', '2026-01-01 12:05:00')", (pid,))
storage.save_keyword_post('car', '캐스퍼', post('900'), is_new=True)
with storage._db() as conn, conn:
    conn.execute("UPDATE keyword_posts SET matched_at = '2026-01-01 12:10:00' WHERE post_id = '900'")
total, rows = storage.query_all_posts(3, 3, group_id=gid, unread_since=snap)
assert total == 6 and ids(rows) == ['803', '802', '801'], (total, ids(rows))
# 새로 연 보기(새 기준 시각)에서는 읽은 글이 빠지고 새 글이 나옴
assert ids(storage.query_all_posts(0, 10, group_id=gid, unread_since='2026-01-01 13:00:00')[1]) == ['900', '803', '802', '801']
print('ok')
