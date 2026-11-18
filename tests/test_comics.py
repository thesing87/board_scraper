"""만화 뷰어 API: 로그인 쿠키가 있어야 열리고, 압축(.cbz)·이미지 폴더를 자연 정렬로 한 장씩 보내며,
만화 폴더 밖 경로는 거부하고, 읽던 위치를 저장함"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, struct, zlib, zipfile, urllib.request, urllib.error, urllib.parse

COMICS = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='',
                  COMICS_DIR=COMICS)
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, comics

def png(w, h):
    raw = b''.join(b'\x00' + b'\xff\x00\x00' * w for _ in range(h))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')

def jpeg_head(w, h):
    # SOI + 큰 APP1(EXIF 흉내) + SOF0 만으로 크기 읽기 시험
    app1 = b'\xff\xe1' + struct.pack('>H', 2 + 3000) + b'x' * 3000
    sof = b'\xff\xc0' + struct.pack('>HBHHB', 11, 8, h, w, 1) + b'\x01\x11\x00'
    return b'\xff\xd8' + app1 + sof + b'\xff\xd9'

series = os.path.join(COMICS, '원피스')
os.makedirs(series)
for vol in (1, 2, 10):
    with zipfile.ZipFile(os.path.join(series, f'원피스 {vol}권.cbz'), 'w') as zf:
        zf.writestr('p10.png', png(4, 6))
        zf.writestr('p2.png', png(8, 6))       # 가로로 긴 양면
        zf.writestr('p1.png', png(4, 6))
        zf.writestr('__MACOSX/._p1.png', b'junk')
        zf.writestr('info.txt', b'not an image')
folder_book = os.path.join(COMICS, '낱장')
os.makedirs(folder_book)
open(os.path.join(folder_book, '01.jpg'), 'wb').write(jpeg_head(30, 40))
open(os.path.join(folder_book, '02.png'), 'wb').write(png(5, 7))
os.makedirs(os.path.join(COMICS, '@eaDir'))
open(os.path.join(os.path.dirname(COMICS), 'secret.txt'), 'w').write('x')

storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
cookie = ''

def req(path, body=None, raw=False):
    r = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=json.dumps(body).encode() if body is not None else None,
                               method='POST' if body is not None else 'GET', headers={'Content-Type': 'application/json', 'Cookie': cookie})
    try:
        with urllib.request.urlopen(r) as res:
            data = res.read()
            return res.status, (data if raw else json.loads(data)), res.headers
    except urllib.error.HTTPError as e:
        data = e.read()
        return e.code, (data if raw or not data else json.loads(data)), e.headers

q = lambda p: urllib.parse.quote(p)

# 1) 쿠키 없이는 목록·이미지·저장 모두 거부, 틀린 암호로는 쿠키를 주지 않음
assert req('/api/comics/list')[0] == 401
assert req(f'/api/comics/page?p={q("원피스/원피스 1권.cbz")}&n=0', raw=True)[0] == 401
assert req('/api/comics/progress', {'path': 'x', 'page': 0, 'pages': 1})[0] == 401
code, body, headers = req('/api/comics/session', {'password': 'wrong'})
assert code == 401 and not headers.get('Set-Cookie'), code
# 로그인 키(관리자 로그인과 같은 키)로 쿠키를 받음
token = req('/api/login', {'password': 'Secr3t!'})[1]['token']
code, body, headers = req('/api/comics/session', {'password': token})
set_cookie = headers.get('Set-Cookie')
assert code == 200 and 'HttpOnly' in set_cookie and 'SameSite=Strict' in set_cookie and 'Path=/api/comics/' in set_cookie, set_cookie
cookie = set_cookie.split(';')[0]
assert req('/api/comics/list', raw=True)[0] == 200
bad = cookie
cookie = 'comics_key=' + '0' * 64
assert req('/api/comics/list')[0] == 401
cookie = bad
print('AUTH OK')

# 2) 목록: 숨긴 폴더 제외, 자연 정렬 (1, 2, 10권), 이미지 폴더는 장 수
code, root, _ = req('/api/comics/list')
assert code == 200 and root['configured'] and [d['name'] for d in root['dirs']] == ['낱장', '원피스'], root
assert root['recent'] == []
code, lst, _ = req(f'/api/comics/list?p={q("원피스")}')
assert [b['name'] for b in lst['books']] == ['원피스 1권', '원피스 2권', '원피스 10권'], lst
assert req(f'/api/comics/list?p={q("낱장")}')[1]['images'] == 2
print('LIST OK')

# 3) 책: 이미지만 자연 정렬(p1, p2, p10), 크기, 다음 권
code, book, _ = req(f'/api/comics/book?p={q("원피스/원피스 2권.cbz")}')
assert code == 200 and book['count'] == 3 and book['sizes'] == [[4, 6], [8, 6], [4, 6]], book
assert book['prev']['name'] == '원피스 1권' and book['next']['name'] == '원피스 10권' and book['progress'] is None
code, fbook, _ = req(f'/api/comics/book?p={q("낱장")}')
assert fbook['count'] == 2 and fbook['sizes'] == [[30, 40], [5, 7]] and fbook['next'] is None, fbook
print('BOOK OK')

# 4) 이미지: 순서대로 꺼내고 오래 보관하게 함, 같은 지문이면 304
code, data, headers = req(f'/api/comics/page?p={q("원피스/원피스 2권.cbz")}&n=1', raw=True)
assert code == 200 and data == png(8, 6) and headers['Content-Type'] == 'image/png' and 'max-age' in headers['Cache-Control']
etag = headers['ETag']
r = urllib.request.Request(f'http://127.0.0.1:{port}/api/comics/page?p={q("원피스/원피스 2권.cbz")}&n=1',
                           headers={'Cookie': cookie, 'If-None-Match': etag})
try:
    urllib.request.urlopen(r)
    raise AssertionError('304가 아님')
except urllib.error.HTTPError as e:
    assert e.code == 304
assert req(f'/api/comics/page?p={q("원피스/원피스 2권.cbz")}&n=3', raw=True)[0] == 404
assert req(f'/api/comics/page?p={q("낱장")}&n=0', raw=True)[1] == jpeg_head(30, 40)
print('PAGE OK')

# 5) 만화 폴더 밖·숨긴 폴더로는 갈 수 없음
for bad_path in ('..', '../secret.txt', '원피스/../../secret.txt', '@eaDir', '/etc', 'C:/Windows'):
    assert req(f'/api/comics/list?p={q(bad_path)}')[0] in (404,), bad_path
    assert req(f'/api/comics/book?p={q(bad_path)}')[0] == 404, bad_path
assert comics.resolve('../x') is None and comics.resolve('a/../../x') is None
print('PATH OK')

# 6) 읽던 위치 저장 → 목록·책·최근 읽은 책에 보임. 범위를 벗어나거나 없는 책은 거부
assert req('/api/comics/progress', {'path': '원피스/원피스 2권.cbz', 'page': 2, 'pages': 3})[0] == 200
assert req('/api/comics/progress', {'path': '원피스/원피스 2권.cbz', 'page': 3, 'pages': 3})[0] == 400
assert req('/api/comics/progress', {'path': '없는책.cbz', 'page': 0, 'pages': 3})[0] == 404
assert req('/api/comics/progress', {'path': '../secret.txt', 'page': 0, 'pages': 3})[0] == 404
assert req(f'/api/comics/book?p={q("원피스/원피스 2권.cbz")}')[1]['progress']['page'] == 2
assert req(f'/api/comics/list?p={q("원피스")}')[1]['books'][1]['progress']['page'] == 2
assert [r['name'] for r in req('/api/comics/list')[1]['recent']] == ['원피스 2권']
print('PROGRESS OK')

# 7) 만화 폴더가 없으면 설정 안내
comics.COMICS_DIR = os.path.join(COMICS, 'none')
assert req('/api/comics/list')[1] == {'configured': False}
comics.COMICS_DIR = COMICS

# 8) 로그아웃하면 쿠키를 지움
assert 'Max-Age=0' in req('/api/comics/session', {'action': 'logout'})[2]['Set-Cookie']
print('ALL OK')

# 9) 표지: 첫 이미지만 (압축·폴더)
cookie = req('/api/comics/session', {'password': token})[2]['Set-Cookie'].split(';')[0]
code, data, headers = req(f'/api/comics/cover?p={q("원피스/원피스 10권.cbz")}', raw=True)
assert code == 200 and data == png(4, 6) and headers['ETag'], code
assert req(f'/api/comics/cover?p={q("낱장")}', raw=True)[1] == jpeg_head(30, 40)
assert req(f'/api/comics/cover?p={q("../secret.txt")}', raw=True)[0] == 404
print('COVER OK')

# 폴더(시리즈) 칸: 안에 든 책·폴더·이미지 수, 표지는 안에 든 첫 이미지나 첫 책의 첫 장 (하위 폴더까지 찾아 내려감), 없으면 404
nested = os.path.join(COMICS, '시리즈모음', '1부')
os.makedirs(nested)
with zipfile.ZipFile(os.path.join(nested, '1권.cbz'), 'w') as zf:
    zf.writestr('a.png', png(3, 9))
os.makedirs(os.path.join(COMICS, '빈폴더'))
code, body, _ = req('/api/comics/list?p=')
dirs = {d['name']: d for d in body['dirs']}
assert (dirs['원피스']['books'], dirs['원피스']['dirs']) == (3, 0), dirs['원피스']
assert (dirs['낱장']['images'], dirs['시리즈모음']['dirs'], dirs['빈폴더']['books']) == (2, 1, 0), dirs
code, data, headers = req('/api/comics/cover?p=' + urllib.parse.quote('원피스'), raw=True)
assert code == 200 and data == png(4, 6), code          # 1권의 첫 장 (p1.png)
code, data, headers = req('/api/comics/cover?p=' + urllib.parse.quote('시리즈모음'), raw=True)
assert code == 200 and data == png(3, 9), code          # 하위 폴더 안 첫 책
code, data, _ = req('/api/comics/cover?p=' + urllib.parse.quote('낱장'), raw=True)
assert code == 200 and data.startswith(b'\xff\xd8'), code   # 폴더 안 첫 이미지
assert req('/api/comics/cover?p=' + urllib.parse.quote('빈폴더'), raw=True)[0] == 404
assert req('/api/comics/cover?p=' + urllib.parse.quote('../'), raw=True)[0] == 404
print('FOLDER COVER OK')
