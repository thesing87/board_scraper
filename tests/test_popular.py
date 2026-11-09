import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile
from datetime import datetime, timedelta
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server

def post(pid, votes, comments, video=False):
    return {'id': pid, 'title': pid, 'author': 'a', 'date': 'd', 'views': '1', 'votes': votes, 'comment_count': comments,
            'link': '/' + pid, 'content': ['<p>본문</p>'], 'videos': ['v'] if video else [], 'comments': []}

gid, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
for p in [post('701', '3', '2'), post('702', '10', '1,200'), post('703', '0', '0'), post('704', '40', '5', video=True)]:
    storage.save_keyword_post('car', '싼타페', p, is_new=True)
# 704는 오래전에 수집한 글
with storage._db() as conn, conn:
    conn.execute("UPDATE posts SET created_at = '2000-01-01 00:00:00' WHERE id = '704'")

ids = lambda rows: [p['id'] for p in rows]
assert ids(storage.query_all_posts(0, 10, group_id=gid)[1]) == ['704', '703', '702', '701']          # 최신 수집 순
assert ids(storage.query_all_posts(0, 10, group_id=gid, popular=True)[1]) == ['702', '704', '701', '703']  # 추천+댓글 순 (쉼표 숫자)
since = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
total, rows = storage.query_all_posts(0, 10, group_id=gid, popular=True, since=since)
assert total == 3 and ids(rows) == ['702', '701', '703'], (total, ids(rows))                        # 기간 밖 704 제외
assert ids(storage.query_all_posts(0, 10, group_id=gid, video_only=True, popular=True)[1]) == ['704']
# 인기순은 안 읽은 글 조건과 함께 써도 됨
assert storage.query_all_posts(0, 10, group_id=gid, popular=True, since=since, unread_since='2999-01-01 00:00:00')[0] == 3
# 웹서버: sort=popular, days(1·7·30)
page = web_server.build_posts_page(1, False, group_id=gid, popular=True)
assert ids(page['posts'])[0] == '702' and page['total'] == 4
print('POPULAR OK')
