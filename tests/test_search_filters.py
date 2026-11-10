"""검색 강화: 게시판·묶음 안에서만 찾기, 기간(최근 며칠에 수집한 글), 작성자 조건('작성자:닉네임')"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, urllib.request, urllib.parse
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server

def post(pid, title, author):
    return {'id': pid, 'title': title, 'author': author, 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/' + pid, 'content': ['<p>연비 이야기</p>'], 'videos': [], 'comments': []}

storage.init_db()
g1, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
g2, _ = storage.save_group(None, '캐스퍼', [{'board': 'car', 'keyword': '캐스퍼'}])
fid = storage.save_folder(None, '현대')
storage.arrange_group(g2, fid, None)
storage.save_keyword_post('car', '싼타페', post('601', '싼타페 연비 후기', '홍길동'), is_new=True)
storage.save_keyword_post('car', '싼타페', post('602', '싼타페 시승', 'Tester_1'), is_new=True)
storage.save_keyword_post('car', '캐스퍼', post('603', '캐스퍼 연비 후기', '홍길동'), is_new=True)
storage.save_keyword_post('car', '캐스퍼', post('604', '캐스퍼 오래된 글 연비', '홍길동2'), is_new=True)
with storage._db() as conn, conn:
    conn.execute("UPDATE posts SET created_at = '2000-01-01 00:00:00' WHERE id = '604'")

ids = lambda q, **kw: sorted(p['id'] for p in storage.query_all_posts(0, 50, query=q, **kw)[1])
assert ids('연비') == ['601', '602', '603', '604']
assert ids('연비', group_id=g1) == ['601', '602'] and ids('연비', folder_id=fid) == ['603', '604']   # 범위
assert ids('연비 작성자:홍길동') == ['601', '603']                    # 작성자는 정확히 그 닉네임만 (홍길동2 제외)
assert ids('작성자:홍길동') == ['601', '603']                         # 낱말 없이 작성자만
assert ids('author:tester_1') == ['602'] and ids('작성자:tester%') == []   # 대소문자 무시, 특수문자는 글자 그대로
assert ids('후기 작성자:홍길동', group_id=g2) == ['603']
assert ids('작성자:') == ['601', '602', '603', '604']                 # 닉네임이 비면 조건 없음
print('SEARCH QUERY OK')

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def api(**params):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/posts?' + urllib.parse.urlencode(params)) as res:
        return sorted(p['id'] for p in json.load(res)['posts'])
assert api(q='연비') == ['601', '602', '603', '604']
assert api(q='연비', group=g2) == ['603', '604'] and api(q='연비', folder=fid) == ['603', '604']
assert api(q='연비', sdays=7) == ['601', '602', '603'] and api(q='연비', sdays=5) == ['601', '602', '603', '604']  # 없는 기간 값은 무시
assert api(q='연비', group=g2, sdays=30) == ['603']
assert api(q='연비', sdays=7, sort='popular', days=1) == ['601', '602', '603']
assert api(q='작성자:홍길동', sdays=90) == ['601', '603']
print('SEARCH FILTERS OK')
