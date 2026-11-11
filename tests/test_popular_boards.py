"""게시판별 인기글: 최근 기간에 수집한 글 중 게시판마다 추천+댓글이 많은 글 몇 개씩, 사이드바 순서, 글 없는 게시판은 뺌"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, urllib.request
from datetime import datetime, timedelta
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server

def post(pid, votes, comments):
    return {'id': pid, 'title': '글 ' + pid, 'author': 'a', 'date': 'd', 'views': '1', 'votes': votes, 'comment_count': comments,
            'link': '/' + pid, 'content': [], 'videos': [], 'comments': []}

storage.init_db()
g1, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
g2, _ = storage.save_group(None, '캐스퍼', [{'board': 'car', 'keyword': '캐스퍼'}, {'board': 'car', 'keyword': '캐붕'}])
g3, _ = storage.save_group(None, '빈 게시판', [{'board': 'car', 'keyword': '없음'}])
g4, _ = storage.save_group(None, '볼보', [{'board': 'car', 'keyword': '볼보'}])
fid = storage.save_folder(None, '현대')
storage.arrange_group(g1, fid, None)          # 싼타페는 묶음 안, 나머지는 묶음 없이
for pid, kw, v, c in [('701', '싼타페', '10', '5'), ('702', '싼타페', '1,200', '3'), ('703', '싼타페', '0', '0'), ('704', '싼타페', '2', '2'),
                      ('711', '캐스퍼', '3', '3'), ('712', '캐붕', '50', '1'), ('713', '캐붕', '9', '9'),
                      ('721', '볼보', '100', '100')]:
    storage.save_keyword_post('car', kw, post(pid, v, c), is_new=True)
storage.save_keyword_post('car', '캐스퍼', post('712', '50', '1'), is_new=True)   # 한 게시판의 두 키워드에 걸린 글은 한 번만
with storage._db() as conn, conn:
    conn.execute("UPDATE posts SET created_at = ? WHERE id = '721'", ((datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S'),))
    conn.execute("UPDATE posts SET is_deleted = 1 WHERE id = '701'")
storage.mark_posts_read(['702'])

day = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
week = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
res = storage.popular_by_group(day, 3)
summary = [(g['name'], [p['id'] for p in g['posts']]) for g in res]
# 사이드바 순서: 묶음 없는 게시판(position) → 묶음(맨 뒤에 만든 묶음) 안 게시판. 볼보는 하루 안에 글이 없고, 빈 게시판도 빠짐
assert summary == [('캐스퍼', ['712', '713', '711']), ('싼타페', ['702', '704', '703'])], summary
top = res[1]['posts'][0]
assert top['score'] == 1203 and top['is_read'] and top['title'] == '글 702' and not res[1]['posts'][1]['is_read']
assert [g['name'] for g in storage.popular_by_group(week, 3)] == ['캐스퍼', '볼보', '싼타페']
assert [len(g['posts']) for g in storage.popular_by_group(day, 1)] == [1, 1]
assert [g['name'] for g in storage.popular_by_group(week, 5, group_id=g4)] == ['볼보']
assert [g['name'] for g in storage.popular_by_group(week, 5, folder_id=fid)] == ['싼타페']
print('POPULAR BOARDS QUERY OK')

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(query):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/popular?{query}') as r:
        return json.load(r)
data = get('days=1&limit=3')
assert data['days'] == 1 and [g['name'] for g in data['groups']] == ['캐스퍼', '싼타페']
assert get('days=999')['days'] == 1 and [len(g['posts']) for g in get('days=1')['groups']] == [3, 3]   # 기본 5개
assert [len(g['posts']) for g in get('days=7&limit=99')['groups']] == [3, 1, 3]                        # 상한 10
assert [g['name'] for g in get(f'days=7&group={g4}')['groups']] == ['볼보']
assert [g['name'] for g in get(f'days=7&folder={fid}')['groups']] == ['싼타페']
print('POPULAR BOARDS OK')
