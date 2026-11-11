"""'모두 읽음'·'모두 확인': 화면이 받은 ID 수(최대 500)와 상관없이 게시판·묶음·전체를 한 번에.
화면이 받은 상태의 시각(until) 뒤에 모인 글·달린 댓글은 그대로 새 글·새 댓글로 남김"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server

def post(pid):
    return {'id': pid, 'title': pid, 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/' + pid, 'content': [], 'videos': [], 'comments': []}

storage.init_db()
g1, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
g2, _ = storage.save_group(None, '캐스퍼', [{'board': 'car', 'keyword': '캐스퍼'}])
fid = storage.save_folder(None, '현대')
storage.arrange_group(g2, fid, None)
UNTIL = '2026-11-11 12:00:00'
with storage._db() as conn, conn:
    for i in range(1200):                                   # 1,200개 (화면이 받는 ID는 500개까지)
        storage._upsert_post(conn, post(f'{100000 + i}'))
        storage._link_keyword_post(conn, 'car', '싼타페', f'{100000 + i}', True)
    for i in range(30):
        storage._upsert_post(conn, post(f'{200000 + i}'))
        storage._link_keyword_post(conn, 'car', '캐스퍼', f'{200000 + i}', True)
    conn.execute("UPDATE keyword_posts SET matched_at = '2026-11-11 11:00:00'")
    # 보던 상태 뒤에 모인 새 글 2개
    conn.execute("UPDATE keyword_posts SET matched_at = '2026-11-11 12:05:00' WHERE post_id IN ('101198', '101199')")
counts = lambda: {g['name']: (g['unread_count'], len(g['unread_ids'])) for g in storage.list_groups()}
assert counts() == {'싼타페': (1200, 500), '캐스퍼': (30, 30)}, counts()

# 게시판 하나만, 개수 제한 없이 (until 뒤에 모인 2개는 남음). 다른 게시판은 그대로
assert storage.mark_feed_read('unread', UNTIL, group_id=g1) == 1198
assert counts() == {'싼타페': (2, 2), '캐스퍼': (30, 30)}, counts()
with storage._db() as conn:
    r = conn.execute("SELECT read_at, first_read_at FROM read_posts WHERE post_id = '100000'").fetchone()
assert r['read_at'] == UNTIL and r['first_read_at']
# 묶음 단위
assert storage.mark_feed_read('unread', UNTIL, folder_id=fid) == 30 and counts()['캐스퍼'] == (0, 0)
print('READ ALL UNREAD OK')

# 새 댓글: until 전에 달린 댓글만 확인 처리, 뒤에 달린 댓글은 계속 새 댓글
with storage._db() as conn, conn:
    conn.execute("UPDATE posts SET last_comment_at = '2026-11-11 11:30:00' WHERE id IN ('100001', '100002', '200001')")
    conn.execute("UPDATE posts SET last_comment_at = '2026-11-11 12:10:00' WHERE id IN ('100003', '200001')")
    conn.execute("UPDATE read_posts SET read_at = '2026-11-11 11:00:00' WHERE post_id IN ('100001', '100002', '100003', '200001')")
comment_counts = lambda: {g['name']: g['comment_count'] for g in storage.list_groups()}
assert comment_counts() == {'싼타페': 3, '캐스퍼': 1}
assert storage.mark_feed_read('comments', UNTIL, group_id=g1) == 3
assert comment_counts() == {'싼타페': 1, '캐스퍼': 1}, comment_counts()   # 12:10 댓글이 달린 100003만 남음
print('READ ALL COMMENTS OK')

# API: 암호 없이, 잘못된 값은 400, until이 없거나 미래면 지금까지
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def call(body):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/read-all', data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
for bad in ({'kind': 'all'}, {'kind': 'unread', 'group': '1'}, {'kind': 'unread', 'until': '어제'}, {'kind': 'unread', 'folder': True}):
    assert call(bad)[0] == 400, bad
with storage._db() as conn, conn:   # 남은 2개를 지금보다 앞에 모인 것으로
    conn.execute("UPDATE keyword_posts SET matched_at = '2026-01-01 00:00:00' WHERE post_id IN ('101198', '101199')")
    conn.execute("UPDATE posts SET last_comment_at = '2026-01-01 00:00:00' WHERE id IN ('100003', '200001')")
    conn.execute("UPDATE read_posts SET read_at = '2025-12-31 00:00:00' WHERE post_id IN ('100003', '200001')")
code, body = call({'kind': 'unread', 'until': '2999-01-01 00:00:00'})
assert code == 200 and body['count'] == 2 and counts()['싼타페'] == (0, 0), (code, body)
assert call({'kind': 'comments'})[1]['count'] == 2 and comment_counts() == {'싼타페': 0, '캐스퍼': 0}, comment_counts()
print('READ ALL API OK')
