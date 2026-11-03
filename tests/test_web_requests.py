import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, urllib.request, urllib.error, sqlite3
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, config

storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
storage.save_keyword_post('car', '싼타페', {'id': '801', 'title': '싼타페', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                            'comment_count': '0', 'link': '/801', 'content': [], 'videos': [], 'comments': []}, is_new=True)

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def post(path, body, raw=None):
    data = raw if raw is not None else json.dumps(body).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=data, method='POST', headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as e:
        return e.code, (json.load(e) if e.code != 404 else None)

# --- 1) 형식이 깨진 요청은 서버 오류(500)가 아니라 잘못된 요청(400), 오류 기록(경고·오류 목록)도 남기지 않음
config.RECENT_PROBLEMS.clear()
for path, raw in [('/api/read', b'{not json'), ('/api/group', b'[1, 2]'), ('/api/saved', b'\xff\xfe'), ('/api/folder', b'')]:
    code, body = post(path, None, raw)
    assert code == 400 and body == {'success': False, 'message': '❌ 잘못된 요청입니다.'}, (path, code, body)
assert list(config.RECENT_PROBLEMS) == [], list(config.RECENT_PROBLEMS)
assert post('/webapi/query.cgi', {})[0] == 404                       # 모르는 경로는 그대로 404
print('BAD REQUEST OK')

# --- 2) 읽음 기록은 모은 글만 (암호 없이 부르는 API라 없는 글 ID는 저장하지 않음)
code, body = post('/api/read', {'ids': ['801', '999999', 'dc-x-1', 'not-an-id']})
assert code == 200 and body['count'] == 1, body
with sqlite3.connect(config.DB_FILE) as db:
    assert [r[0] for r in db.execute('SELECT post_id FROM read_posts')] == ['801']
# 정상 요청은 그대로
code, body = post('/api/saved', {'id': '801', 'saved': True})
assert code == 200 and body['saved'] is True
srv.shutdown()
print('READ ONLY EXISTING OK')
