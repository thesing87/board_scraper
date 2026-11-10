"""전송 줄이기: 화면 파일·조회 응답은 gzip으로 줄여 보내고, 내용이 그대로면 본문 없이 304"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, gzip, http.client
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server

storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

def get(path, headers=None, method='GET', body=None):
    conn = http.client.HTTPConnection('127.0.0.1', port)
    conn.request(method, path, body=body, headers=headers or {})
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return res, data

with open(os.path.join(ROOT, 'app', 'static', 'app.js'), 'rb') as f:
    original = f.read()

# 1) 압축을 받는 브라우저에는 gzip으로, 아니면 그대로
res, data = get('/app.js', {'Accept-Encoding': 'gzip, deflate, br'})
assert res.status == 200 and res.getheader('Content-Encoding') == 'gzip' and res.getheader('Vary') == 'Accept-Encoding'
assert gzip.decompress(data) == original and len(data) < len(original) / 2, (len(data), len(original))
etag = res.getheader('ETag')
assert etag and res.getheader('Cache-Control') == 'private, no-cache'
res, data = get('/app.js')
assert res.status == 200 and res.getheader('Content-Encoding') is None and data == original
assert get('/app.js', {'Accept-Encoding': 'gzip;q=0'})[0].getheader('Content-Encoding') is None
print('GZIP OK')

# 2) 같은 내용이면 304 (프록시가 약한 지문으로 바꿔도), 다르면 다시 보냄
for tag in (etag, 'W/' + etag, f'"x", {etag}'):
    res, data = get('/app.js', {'If-None-Match': tag, 'Accept-Encoding': 'gzip'})
    assert res.status == 304 and data == b'' and res.getheader('ETag') == etag, (tag, res.status)
assert get('/app.js', {'If-None-Match': '"other"'})[0].status == 200
print('ETAG OK')

# 3) 조회 응답(JSON)도 압축·지문, 화면 페이지는 보안 머리말 유지
res, data = get('/api/posts?page=1', {'Accept-Encoding': 'gzip'})
assert res.status == 200 and res.getheader('ETag')
body = gzip.decompress(data) if res.getheader('Content-Encoding') == 'gzip' else data
assert json.loads(body)['page'] == 1
assert get('/api/posts?page=1', {'If-None-Match': res.getheader('ETag')})[0].status == 304
res, data = get('/api/state', {'Accept-Encoding': 'gzip'})
assert res.getheader('Content-Encoding') == 'gzip' and 'groups' in json.loads(gzip.decompress(data))
res, data = get('/board/', {'Accept-Encoding': 'gzip'})
assert res.getheader('Content-Security-Policy') and b'<html' in gzip.decompress(data)
# 4) 바꾸는 요청(POST)의 응답은 보관하지 않음
res, data = get('/api/read', {'Content-Type': 'application/json'}, 'POST', json.dumps({'ids': []}))
assert res.status == 200 and res.getheader('ETag') is None and 'no-store' in res.getheader('Cache-Control')
print('COMPRESS OK')
