import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', KEYWORDS_BASEBALL='')
import storage

storage.init_db()

def post(pid, title):
    return {'id': pid, 'title': title, 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/' + pid, 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}

car_id, _ = storage.save_group(None, '자동차', [{'board': 'car', 'keyword': '싼타페'}])
ball_id, _ = storage.save_group(None, '야구', [{'board': 'baseball', 'keyword': '라이온즈'}])
for pid, kw, board in (('401', '싼타페', 'car'), ('402', '싼타페', 'car'), ('403', '라이온즈', 'baseball'), ('404', '싼타페', 'car')):
    storage.save_keyword_post(board, kw, post(pid, kw + ' 글 ' + pid), is_new=False)

# 401은 먼저, 402는 나중에 삭제 확인 (삭제 확인 시각 = updated_at)
for pid, when in (('401', '2026-10-30 09:00:00'), ('402', '2026-10-30 10:00:00'), ('403', '2026-10-30 11:00:00')):
    storage.mark_post_deleted(pid)
    with storage._db() as conn, conn:
        conn.execute("UPDATE posts SET updated_at = ? WHERE id = ?", (when, pid))

# 전체: 삭제된 글만, 최근 삭제 순
total, rows = storage.query_all_posts(0, 10, deleted_only=True)
assert total == 3 and [r['id'] for r in rows] == ['403', '402', '401'], (total, [r['id'] for r in rows])
assert all(r.get('is_deleted') for r in rows)
# 게시판: 그 게시판의 삭제된 글만
total, rows = storage.query_all_posts(0, 10, group_id=car_id, deleted_only=True)
assert total == 2 and [r['id'] for r in rows] == ['402', '401'], (total, [r['id'] for r in rows])
print('query OK')

# 보기 칸 글 수
assert storage.feed_summary()['deleted_count'] == 3
groups = {g['id']: g for g in storage.list_groups()}
assert groups[car_id]['deleted_count'] == 2 and groups[ball_id]['deleted_count'] == 1
print('DELETED VIEW OK')
