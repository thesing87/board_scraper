import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, sqlite3, json
OUT = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=OUT, LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, config

# --- 1) 새 DB: 글 표에는 작은 칸만, 본문·댓글 JSON과 검색 텍스트는 본문 표(post_bodies)에
storage.init_db()
with sqlite3.connect(config.DB_FILE) as db:
    post_cols = [r[1] for r in db.execute('PRAGMA table_info(posts)')]
    body_cols = [r[1] for r in db.execute('PRAGMA table_info(post_bodies)')]
assert 'content_json' not in post_cols and 'has_video' in post_cols, post_cols
assert body_cols == ['post_id', 'videos_json', 'content_json', 'comments_json', 'search_text'], body_cols

def post(pid, content, videos=(), comments=()):
    return {'id': pid, 'title': pid, 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/' + pid, 'content': list(content), 'videos': list(videos), 'comments': list(comments)}

storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
storage.save_keyword_post('car', '싼타페', post('1', ['<p><img src="https://image.fmkorea.com/files/attach/new5/a.jpg"></p>']), is_new=True)
storage.save_keyword_post('car', '싼타페', post('2', ['<p><img src="/images/dc-car_new1-2/0-ab.jpg"></p>'], videos=['<video></video>']), is_new=True)
storage.save_keyword_post('car', '싼타페', post('3', ['<p><IMG src="//x/emoticon.png"> 하이브리드</p>'], comments=[{'author': 'c', 'content': ['댓글']}]), is_new=True)
flags = lambda: {r[0]: r[1:] for r in sqlite3.connect(config.DB_FILE).execute('SELECT id, has_video, has_image, last_comment_at IS NOT NULL FROM posts')}
assert flags() == {'1': (0, 1, 0), '2': (1, 1, 0), '3': (0, 0, 1)}, flags()
s = storage.feed_summary()
assert s['total'] == 3 and s['video_count'] == 1 and s['image_count'] == 2, s
# 검색은 본문 표의 검색 텍스트로
assert [p['id'] for p in storage.query_all_posts(0, 10, query='하이브리드')[1]] == ['3']
print('NEW DB OK')

# --- 2) 예전 DB(한 표에 본문까지, 동영상·이미지·마지막 댓글 칸 없음)를 열면 두 표로 나누고 칸을 계산해 채움.
#        키워드 연결·보관함·읽음 기록은 그대로
old_dir = tempfile.mkdtemp()
old_db = os.path.join(old_dir, 'board.db')
with sqlite3.connect(config.DB_FILE) as src, sqlite3.connect(old_db) as dst:
    src.backup(dst)
with sqlite3.connect(old_db) as db:
    db.execute('PRAGMA foreign_keys = OFF')
    db.execute("""CREATE TABLE posts_old (id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '',
        date TEXT NOT NULL DEFAULT '', views TEXT NOT NULL DEFAULT '0', votes TEXT NOT NULL DEFAULT '0',
        comment_count TEXT NOT NULL DEFAULT '0', link TEXT NOT NULL DEFAULT '', content_json TEXT NOT NULL DEFAULT '[]',
        videos_json TEXT NOT NULL DEFAULT '[]', comments_json TEXT NOT NULL DEFAULT '[]', list_comment_count INTEGER,
        all_comment_pages INTEGER NOT NULL DEFAULT 0, search_text TEXT, is_deleted INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    db.execute("""INSERT INTO posts_old SELECT p.id, title, author, date, views, votes, comment_count, link, content_json, videos_json,
        comments_json, list_comment_count, all_comment_pages, search_text, is_deleted, created_at, updated_at
        FROM posts p JOIN post_bodies b ON b.post_id = p.id""")
    db.execute('DROP TABLE post_bodies')
    db.execute('DROP TABLE posts')
    db.execute('ALTER TABLE posts_old RENAME TO posts')
    db.execute("UPDATE posts SET comments_json = ? WHERE id = '3'",
               (json.dumps([{'author': 'c', 'content': ['댓글'], 'first_seen': '2026-11-01 10:00:00'},
                            {'author': 'd', 'content': ['댓글2'], 'first_seen': '2026-11-02 09:00:00'}]),))
    db.execute("INSERT INTO saved_posts(post_id, saved_at) VALUES('2', '2026-11-03 10:00:00')")
    db.execute("INSERT INTO read_posts(post_id, read_at, first_read_at) VALUES('3', '2026-11-01 12:00:00', '2026-11-01 12:00:00')")
    db.commit()
    links_before = db.execute('SELECT COUNT(*) FROM keyword_posts').fetchone()[0]

storage.DB_FILE = old_db
storage.BACKUP_DIR = os.path.join(old_dir, 'backups')
storage._initialized = False
storage.init_db()
with sqlite3.connect(old_db) as db:
    assert 'content_json' not in [r[1] for r in db.execute('PRAGMA table_info(posts)')]
    rows = {r[0]: r[1:] for r in db.execute('SELECT id, has_video, has_image, last_comment_at FROM posts')}
    assert rows == {'1': (0, 1, None), '2': (1, 1, None), '3': (0, 0, '2026-11-02 09:00:00')}, rows
    assert db.execute('SELECT COUNT(*) FROM post_bodies').fetchone()[0] == 3
    assert db.execute('SELECT COUNT(*) FROM keyword_posts').fetchone()[0] == links_before == 3
    assert db.execute('SELECT post_id FROM saved_posts').fetchall() == [('2',)]
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
assert len([f for f in os.listdir(storage.BACKUP_DIR) if f.startswith('board-before-posts-split-')]) == 1
assert storage.feed_summary()['comment_ids'] == ['3']          # 읽은 뒤(11/01 12:00) 달린 댓글
assert [p['id'] for p in storage.query_all_posts(0, 10, query='하이브리드')[1]] == ['3']
# 외래 키는 새 글 표를 가리킴: 글을 지우면 본문·키워드 연결·보관함도 지워짐
with storage._db() as conn, conn:
    conn.execute("DELETE FROM posts WHERE id = '2'")
with sqlite3.connect(old_db) as db:
    assert db.execute("SELECT COUNT(*) FROM keyword_posts WHERE post_id = '2'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM post_bodies WHERE post_id = '2'").fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM saved_posts').fetchone()[0] == 0
# 다시 열어도 또 나누지 않음
storage._initialized = False
storage.init_db()
assert len(os.listdir(storage.BACKUP_DIR)) == 1
print('SPLIT OK')

# --- 3) 글 목록: 한 페이지 ID를 먼저 고른 뒤 그 글만 본문까지 읽어도 순서·키워드·읽음·보관 정보는 같음
total, posts = storage.query_all_posts(0, 10)
assert total == 2 and [p['id'] for p in posts] == ['3', '1'], [p['id'] for p in posts]
assert posts[0]['read_at'] == '2026-11-01 12:00:00' and posts[0]['keywords'] == [{'board': 'car', 'keyword': '싼타페'}]
assert posts[0]['comments'][1]['author'] == 'd' and posts[1]['is_new'] and not posts[1]['is_saved']
# 다시 저장하면 본문 표도 갱신 (새 댓글은 전에 없던 댓글만)
new = storage.update_post(dict(post('1', ['<p>바뀐 본문</p>']), comments=[{'author': 'e', 'content': ['새']}]))
assert [c['author'] for c in new] == ['e'] and storage.query_posts_by_ids(['1'])[0]['content'] == ['<p>바뀐 본문</p>']
with sqlite3.connect(old_db) as db:
    assert db.execute("SELECT has_image, last_comment_at IS NOT NULL FROM posts WHERE id = '1'").fetchone() == (0, 1)
print('PAGE QUERY OK')
