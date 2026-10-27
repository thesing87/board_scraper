import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', KEYWORDS_BASEBALL='삼성')
import storage

storage.init_db()

def post(pid, comments):
    return {'id': pid, 'title': '삼성 ' + pid, 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': str(len(comments)),
            'link': '/' + pid, 'content': ['본문'], 'videos': [], 'comments': comments}

def comment(author, text):
    return {'author': author, 'date': '', 'votes': '0', 'content': [text]}

def set_seen(pid, first_seen_by_author, read_at=None):
    # 댓글이 처음 수집된 시각과 읽은 시각을 원하는 값으로 맞춤 (실제로는 수집·읽음 시각이 _now()로 들어감)
    import json
    with storage._db() as conn, conn:
        row = conn.execute("SELECT comments_json FROM posts WHERE id = ?", (pid,)).fetchone()
        comments = json.loads(row['comments_json'])
        for c in comments:
            c['first_seen'] = first_seen_by_author[c['author']]
        conn.execute("UPDATE posts SET comments_json = ? WHERE id = ?", (json.dumps(comments, ensure_ascii=False), pid))
        if read_at:
            conn.execute("INSERT OR REPLACE INTO read_posts(post_id, read_at, first_read_at) VALUES(?, ?, ?)", (pid, read_at, read_at))

# 101: 읽은 뒤 댓글이 하나 달림 (마지막 새 댓글 10:05)
storage.save_keyword_post('baseball', '삼성', post('101', [comment('a', '1'), comment('b', '2')]), is_new=True)
set_seen('101', {'a': '2026-10-27 09:00:00', 'b': '2026-10-27 10:05:00'}, read_at='2026-10-27 10:00:00')
# 102: 읽은 뒤 댓글이 달림 (마지막 새 댓글 10:30) → 101보다 먼저
storage.save_keyword_post('baseball', '삼성', post('102', [comment('a', '1'), comment('c', '3')]), is_new=True)
set_seen('102', {'a': '2026-10-27 09:00:00', 'c': '2026-10-27 10:30:00'}, read_at='2026-10-27 10:00:00')
# 103: 읽은 뒤 새 댓글 없음
storage.save_keyword_post('baseball', '삼성', post('103', [comment('a', '1')]), is_new=True)
set_seen('103', {'a': '2026-10-27 09:00:00'}, read_at='2026-10-27 10:00:00')
# 104: 아직 안 읽은 글 → '안 읽은 글'에 나오므로 제외
storage.save_keyword_post('baseball', '삼성', post('104', [comment('a', '1')]), is_new=True)
set_seen('104', {'a': '2026-10-27 11:00:00'})

summary = storage.new_comment_summary()
assert summary == {'total': 2, 'unread_ids': ['102', '101']}, summary
print('summary OK')

posts = storage.query_posts_by_ids(['101', '102', '999', 'x'])
assert [p['id'] for p in posts] == ['101', '102'], [p['id'] for p in posts]
assert posts[0]['read_at'] == '2026-10-27 10:00:00' and len(posts[0]['comments']) == 2
assert posts[0]['keywords'] == [{'board': 'baseball', 'keyword': '삼성'}]
print('by ids OK')

# 다시 읽으면 목록에서 빠짐
storage.mark_posts_read(['102'])
assert storage.new_comment_summary()['unread_ids'] == ['101']
print('NEW COMMENTS OK')
