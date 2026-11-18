"""표시 순서표(ctts)가 빠진 MP4 바로잡기(video_fix.py): 프레임 POC로 표시 순서를 되살려 원래 ctts와 같은 순서가 되고,
moov가 앞에 있으면 데이터 위치도 밀며, 고칠 것이 없는 파일(ctts 있음·H.264 아님)은 그대로 두고,
서버는 고친 moov를 끼운 가상의 파일을 Range로도 맞게 보내며 내려받기는 원본 그대로"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import TESTS_DIR
import tempfile, threading, socket, json, struct, shutil, urllib.request, urllib.error, urllib.parse

FIX = os.environ.get('VIDEO_FIXTURES') or os.path.join(TESTS_DIR, 'fixtures', 'videos')
VIDEOS = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', VIDEOS_DIR=VIDEOS)
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, video_fix as vf


def read_moov(data):
    pos = 0
    while pos < len(data):
        size, kind = struct.unpack_from('>I4s', data, pos)
        if kind == b'moov':
            return pos, size, vf._parse_boxes(data[pos:pos + size])[0]
        pos += size
    raise AssertionError('no moov')


def stbl_of(moov_box):
    trak = vf._video_trak(moov_box[1])
    return trak, vf._child(vf._child(vf._child(trak[1], b'mdia')[1], b'minf')[1], b'stbl')[1]


def cts_list(data):
    """프레임마다 표시 시각 (푸는 시각 + ctts)"""
    _, _, moov = read_moov(data)
    _, stbl = stbl_of(moov)
    count = len(vf._sample_offsets(stbl)[0])
    dts = vf._decode_times(stbl, count)
    body = vf._child(stbl, b'ctts')[1]
    n = struct.unpack_from('>I', body, 4)[0]
    offs = []
    for i in range(n):
        run, off = struct.unpack_from('>Ii', body, 8 + 8 * i)
        offs += [off] * run
    return [d + o for d, o in zip(dts, offs)]


def strip_ctts(data, moov_first):
    """ctts를 뺀 MP4 (문제 파일 흉내). moov_first면 moov를 mdat 앞으로 옮김"""
    start, size, moov = read_moov(data)
    _, stbl = stbl_of(moov)
    stbl[:] = [b for b in stbl if b[0] != b'ctts']
    rest = data[:start] + data[start + size:]
    if not moov_first:
        return rest + vf._build_boxes([moov])
    ftyp_end = struct.unpack_from('>I', rest, 0)[0]
    new_size = len(vf._build_boxes([moov]))
    vf._shift_chunks(moov[1], new_size, ftyp_end)
    return rest[:ftyp_end] + vf._build_boxes([moov]) + rest[ftyp_end:]


def apply(path, result):
    data = open(path, 'rb').read()
    return data[:result['moov_start']] + result['moov'] + data[result['moov_end']:]


def ranks(values):
    return [r for _, r in sorted((v, i) for i, v in enumerate(values))]


original = open(os.path.join(FIX, 's.mp4'), 'rb').read()
want = cts_list(original)
assert ranks(want) != list(range(len(want))), '시험용 영상에 B프레임(순서 바뀜)이 있어야 함'
tmp = tempfile.mkdtemp()

for moov_first in (False, True):
    path = os.path.join(tmp, f'broken_{moov_first}.mp4')
    open(path, 'wb').write(strip_ctts(original, moov_first))
    fixed = apply(path, vf.build(path))
    got = cts_list(fixed)
    # 표시 순서가 원래 ctts와 같고, 표시 시각은 원래와 일정한 차이만 남
    assert ranks(got) == ranks(want), moov_first
    assert len({g - w for g, w in zip(got, want)}) == 1, moov_first
    assert min(got) >= 0
    # 데이터 위치가 맞아 프레임 내용이 원본과 같음
    _, _, moov = read_moov(fixed)
    _, stbl = stbl_of(moov)
    offs, sizes = vf._sample_offsets(stbl)
    _, _, omoov = read_moov(original)
    _, ostbl = stbl_of(omoov)
    ooffs, osizes = vf._sample_offsets(ostbl)
    assert sizes == osizes
    assert all(fixed[a:a + n] == original[b:b + n] for a, b, n in zip(offs, ooffs, sizes)), moov_first
    # 편집 목록(elst): 첫 장면이 0초에 보이도록 시작점이 맨 앞 표시 시각
    trak, _ = stbl_of(moov)
    elst = vf._child(vf._child(trak[1], b'edts')[1], b'elst')[1]
    media = struct.unpack_from('>i', elst, 12)[0]
    assert media == min(got), (media, min(got))

# ---- 고칠 것이 없는 파일
for name, reason in (('s.mp4', 'has ctts'), ('mpeg4.mp4', 'codec')):
    try:
        vf.build(os.path.join(FIX, name))
        raise AssertionError(name)
    except vf.Unsupported as e:
        assert reason in str(e), (name, e)
assert vf.layout(os.path.join(FIX, 's.mp4')) is None
assert vf.layout(os.path.join(FIX, 's.mkv')) is None

# ---- 서버: 고친 파일을 Range로도 맞게, 내려받기는 원본
broken = strip_ctts(original, True)
open(os.path.join(VIDEOS, 'b.mp4'), 'wb').write(broken)
expected = apply(os.path.join(VIDEOS, 'b.mp4'), vf.build(os.path.join(VIDEOS, 'b.mp4')))
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'


def get(path, headers=None):
    r = urllib.request.Request(BASE + path, headers={'Cookie': cookie, **(headers or {})})
    try:
        with urllib.request.urlopen(r) as res:
            return res.status, res.read(), res.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


cookie = ''
r = urllib.request.Request(BASE + '/api/videos/session', data=json.dumps({'password': 'Secr3t!'}).encode(), method='POST',
                           headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(r) as res:
    cookie = res.headers['Set-Cookie'].split(';')[0]

code, body, headers = get('/api/videos/file?p=b.mp4')
assert code == 200 and body == expected and int(headers['Content-Length']) == len(expected)
# moov 안·moov 경계·데이터 쪽을 걸치는 Range
moov_start = 32
for a, b in ((0, 99), (moov_start + 5, moov_start + 4000), (len(expected) - 5000, len(expected) - 1), (100, len(expected) - 1)):
    code, body, headers = get('/api/videos/file?p=b.mp4', {'Range': f'bytes={a}-{b}'})
    assert code == 206 and body == expected[a:b + 1], (a, b, code, len(body))
    assert headers['Content-Range'] == f'bytes {a}-{b}/{len(expected)}'
code, body, headers = get('/api/videos/file?p=b.mp4', {'Range': 'bytes=-1000'})
assert code == 206 and body == expected[-1000:]
code, _, headers = get('/api/videos/file?p=b.mp4', {'Range': f'bytes={len(expected)}-'})
assert code == 416 and headers['Content-Range'] == f'bytes */{len(expected)}'
code, body, headers = get('/api/videos/file?p=b.mp4&download=1')
assert code == 200 and body == broken and 'attachment' in headers['Content-Disposition']
# 고친 결과는 저장해 두고 다시 씀 (원본을 다시 읽지 않음)
saved = [n for _, _, files in os.walk(vf.FIX_DIR) for n in files]
assert any(n.endswith('.moov') for n in saved) and any(n.endswith('.json') for n in saved), saved
vf._memo.clear()
orig_build = vf.build
vf.build = lambda full: (_ for _ in ()).throw(AssertionError('다시 만들면 안 됨'))
assert get('/api/videos/file?p=b.mp4')[1] == expected
vf.build = orig_build
# 미리 고치기 요청
assert get('/api/videos/prepare?p=b.mp4')[0] == 202
assert get('/api/videos/prepare?p=none.mp4')[0] == 404
srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print('test_video_fix: OK')
