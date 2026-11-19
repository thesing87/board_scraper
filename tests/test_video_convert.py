"""동영상 변환(video_convert.py·video_worker.py): ffmpeg 출력에서 형식 읽기, 그대로·포장만·화면까지 변환 판정,
작업 넣기·밤 예약·지금 변환으로 바꾸기·취소, 빠른 줄(remux)·느린 줄 나눔과 밤 시간, 폴더 예약,
(ffmpeg가 있으면) 실제 변환 → 변환본을 서버가 대신 보냄 → 원본이 바뀌면 옛 변환본 정리"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import TESTS_DIR
import tempfile, shutil, subprocess, json, threading, socket, urllib.request, urllib.parse
from datetime import datetime

FIX = os.environ.get('VIDEO_FIXTURES') or os.path.join(TESTS_DIR, 'fixtures', 'videos')
VIDEOS = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', VIDEOS_DIR=VIDEOS)
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, videos, video_convert as vc

storage.init_db()
FFMPEG = shutil.which('ffmpeg')

# ---- ffmpeg 출력 읽기
sample = """Input #0, avi, from 'a.avi':
  Duration: 01:02:03.50, start: 0.000000, bitrate: 1200 kb/s
  Stream #0:0: Video: mpeg4 (Advanced Simple Profile) (XVID / 0x44495658), yuv420p, 720x480 [SAR 1:1 DAR 3:2], 1000 kb/s, 29.97 fps
  Stream #0:1: Audio: mp3 (U[0][0][0] / 0x0055), 48000 Hz, stereo, fltp, 192 kb/s
"""
info = vc._parse_probe(sample)
assert info == {'video': 'mpeg4', 'audio': 'mp3', 'width': 720, 'height': 480, 'duration': 3723.5}, info
cover = vc._parse_probe("  Duration: 00:00:10.00\n  Stream #0:0: Video: mjpeg, yuvj420p, 300x300 (attached pic)\n  Stream #0:1: Video: h264 (High), yuv420p, 1280x720\n")
assert cover['video'] == 'h264' and cover['height'] == 720

# ---- 판정
assert vc.mode_of({'video': 'h264', 'audio': 'aac'}, '.mp4') == 'direct'
assert vc.mode_of({'video': 'h264', 'audio': 'ac3'}, '.mp4') == 'remux'      # 크롬이 AC3 소리를 못 냄
assert vc.mode_of({'video': 'h264', 'audio': 'mp3'}, '.avi') == 'remux'      # 포장만
assert vc.mode_of({'video': 'hevc', 'audio': 'aac'}, '.mkv') == 'direct'
assert vc.mode_of({'video': 'mpeg4', 'audio': 'aac'}, '.mp4') == 'transcode'
assert vc.mode_of({'video': 'wmv3', 'audio': 'wmav2'}, '.wmv') == 'transcode'
assert vc.mode_of({'video': None, 'audio': 'mp3'}, '.mp4') == 'direct'
assert round(vc.estimate_seconds({'duration': 3600, 'height': 480}, 'transcode')) == 900
assert vc.estimate_seconds({'duration': 3600, 'height': 1080}, 'transcode') > vc.estimate_seconds({'duration': 3600, 'height': 720}, 'transcode')
assert vc.estimate_seconds({'duration': 3600}, 'remux') < 120

# 변환 명령: remux는 화면 복사, transcode는 720p까지 줄여 H.264, 맞지 않는 소리는 AAC
cmd = vc.build_command('ffmpeg', 'in', 'out', {'video': 'h264', 'audio': 'ac3', 'height': 1080}, 'remux')
assert cmd[cmd.index('-c:v') + 1] == 'copy' and cmd[cmd.index('-c:a') + 1] == 'aac' and cmd[-1] == 'out'
cmd = vc.build_command('ffmpeg', 'in', 'out', {'video': 'mpeg4', 'audio': 'mp3', 'height': 1080}, 'transcode')
assert cmd[cmd.index('-c:v') + 1] == 'libx264' and 'min(720,ih)' in cmd[cmd.index('-vf') + 1] and cmd[cmd.index('-c:a') + 1] == 'copy'
assert '+faststart' in cmd

# ---- 작업: 밤 예약 → 지금 변환으로, 진행 중이면 그대로, 취소
os.makedirs(os.path.join(VIDEOS, 'f'))
shutil.copy(os.path.join(FIX, 's.avi'), os.path.join(VIDEOS, 'f', 'a.avi'))
shutil.copy(os.path.join(FIX, 's.mp4'), os.path.join(VIDEOS, 'f', 'b.mp4'))
shutil.copy(os.path.join(FIX, 'mpeg4.mp4'), os.path.join(VIDEOS, 'f', 'c.mp4'))
vc.enqueue('f/a.avi', 'transcode', night=True)
assert vc.job('f/a.avi')['state'] == 'queued' and vc.job('f/a.avi')['night']
day, night = datetime(2026, 1, 1, 14), datetime(2026, 1, 1, 2)
assert vc.next_job('slow', day) is None and vc.next_job('slow', night) == ('f/a.avi', 'transcode')
vc.enqueue('f/a.avi', 'transcode', night=False)
assert not vc.job('f/a.avi')['night'] and vc.next_job('slow', day) == ('f/a.avi', 'transcode')
assert vc.next_job('fast', day) is None   # 빠른 줄은 remux만
vc.enqueue('f/b.mp4', 'remux')
assert vc.next_job('fast', day) == ('f/b.mp4', 'remux')
assert vc._claim('f/b.mp4') and not vc._claim('f/b.mp4')   # 한 줄만 가져감
vc.enqueue('f/b.mp4', 'remux', night=True)                 # 진행 중이면 그대로
assert vc.job('f/b.mp4')['state'] == 'running' and not vc.job('f/b.mp4')['night']
vc.cancel('f/b.mp4')
assert vc.job('f/b.mp4')['state'] == 'cancel'               # 작업기가 보고 멈춤
vc.recover()
assert vc.job('f/b.mp4') is None and vc.job('f/a.avi')['state'] == 'queued'
vc.cancel('f/a.avi')
assert vc.job('f/a.avi') is None

# ---- 목록 표시·폴더 예약 (MP4는 형식을 조사해 둔 것만 판정, 모르면 None)
listing = vc.annotate(videos.list_dir('f'))
by = {v['name']: v for v in listing['videos']}
assert by['a']['convert'] is True and by['b']['convert'] is None and all(v['playable'] for v in by.values())
assert vc.enqueue_folder('f') == 3                            # 모르는 MP4도 넣고 작업기가 조사해 필요 없으면 지움
assert all(vc.job(p)['night'] for p in ('f/a.avi', 'f/b.mp4', 'f/c.mp4'))
assert vc.enqueue_folder('f') == 0 and vc.enqueue_folder('none') is None
for p in ('f/a.avi', 'f/b.mp4', 'f/c.mp4'):
    vc.cancel(p)

# ---- 자동 변환: 폴더 전체(하위 폴더 포함, 숨긴 폴더 제외)를 훑어 변환이 필요한 것만 자동 변환으로 (아무 때나, 직접 넣은 작업 뒤에)
os.makedirs(os.path.join(VIDEOS, 'f', 'sub'))
os.makedirs(os.path.join(VIDEOS, '@eaDir'))
shutil.copy(os.path.join(FIX, 'mpeg4.mp4'), os.path.join(VIDEOS, 'f', 'sub', 'd.mp4'))
shutil.copy(os.path.join(FIX, 'mpeg4.mp4'), os.path.join(VIDEOS, '@eaDir', 'x.mp4'))
# 형식 조사는 ffmpeg 없이도 되게 바꿔 끼움 (a·b는 그대로 되는 파일, mpeg4는 화면 변환)
real_probe = vc.probe
vc.probe = lambda rel, full=None: {'mode': 'transcode' if rel.endswith(('c.mp4', 'd.mp4')) else 'direct'}
assert [r for r, _ in vc._walk_videos()] == ['f/a.avi', 'f/b.mp4', 'f/c.mp4', 'f/sub/d.mp4']
vc.enqueue('f/a.avi', 'transcode')
vc._set('f/a.avi', state='failed', error='x')                 # 전에 실패한 것은 다시 넣지 않음
assert vc.scan_library() == (4, 2)
assert vc.job('f/b.mp4') is None                               # 그대로 재생되는 MP4는 넣지 않음
assert all(vc.job(p)['auto'] and not vc.job(p)['night'] and vc.job(p)['kind'] == 'transcode' for p in ('f/c.mp4', 'f/sub/d.mp4'))
assert vc.next_job('slow', day) == ('f/c.mp4', 'transcode')    # 낮에도 돎
vc.enqueue('f/x.avi', 'transcode', night=True)
vc.enqueue('f/y.avi', 'transcode')
assert vc.next_job('slow', day) == ('f/y.avi', 'transcode')    # 지금 변환이 먼저
assert vc.next_job('slow', night) == ('f/y.avi', 'transcode')
vc.cancel('f/y.avi')
assert vc.next_job('slow', night) == ('f/x.avi', 'transcode')  # 밤에는 밤 예약이 자동보다 먼저
vc.cancel('f/x.avi')
assert vc.scan_library() == (4, 0)                             # 이미 대기 중
assert vc.scan_library(lambda: False) == (0, 0)
vc.cancel('f/c.mp4')                                           # 자동 변환 취소: 다음 훑기에서 다시 넣지 않음
assert vc.job('f/c.mp4')['state'] == 'skipped' and vc.scan_library() == (4, 0)
vc.enqueue('f/c.mp4', 'transcode')                             # 직접 누르면 됨
assert vc.job('f/c.mp4')['state'] == 'queued' and not vc.job('f/c.mp4')['auto']
vc.enqueue('f/sub/d.mp4', 'transcode')                         # 자동 → 지금 변환
assert not vc.job('f/sub/d.mp4')['auto']
for p in ('f/a.avi', 'f/c.mp4', 'f/sub/d.mp4'):
    vc.cancel(p)
shutil.rmtree(os.path.join(VIDEOS, 'f', 'sub'))
shutil.rmtree(os.path.join(VIDEOS, '@eaDir'))
vc.probe = real_probe

if not FFMPEG:
    print('test_video_convert: OK (ffmpeg 없음: 실제 변환은 건너뜀)')
    sys.exit(0)

# ==========================================
# 실제 변환 (ffmpeg가 있는 곳: NAS 컨테이너 등)
# ==========================================
st = vc.status('f/b.mp4')
assert st['mode'] == 'direct' and not st['converted']
assert vc.status('f/c.mp4')['mode'] == 'transcode' and vc.status('f/a.avi')['mode'] == 'transcode'
# 포장만 바꾸면 되는 영상: H.264 화면을 AVI에 넣고 소리는 PCM
subprocess.run([FFMPEG, '-v', 'error', '-y', '-i', os.path.join(FIX, 's.mp4'), '-t', '6', '-c:v', 'copy', '-c:a', 'pcm_s16le',
                os.path.join(VIDEOS, 'f', 'd.avi')], check=True)
assert vc.status('f/d.avi')['mode'] == 'remux'
# 폴더 예약으로 들어온 그대로 재생되는 MP4는 작업기가 조사하고 지움
vc.enqueue('f/b.mp4', 'auto', night=True)
assert vc._claim('f/b.mp4') and vc.run_job('f/b.mp4', 'auto') == 'skip' and vc.job('f/b.mp4') is None

for rel, kind in (('f/d.avi', 'remux'), ('f/a.avi', 'transcode')):
    vc.enqueue(rel, kind)
    assert vc._claim(rel)
    assert vc.run_job(rel, kind) == 'done', vc.job(rel)
    full = videos.video_file(rel)
    out = vc.converted_file(full)
    assert out and vc.job(rel)['state'] == 'done' and vc.job(rel)['progress'] == 1
    probe = vc._parse_probe(subprocess.run([FFMPEG, '-hide_banner', '-i', out], capture_output=True, text=True).stderr)
    assert probe['video'] == 'h264' and probe['audio'] == 'aac' and probe['duration'] > 1, probe
    assert vc.status(rel)['converted']

# 서버: 변환본을 대신 보내고(Range 포함), 내려받기는 원본
import web_server
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'
r = urllib.request.Request(BASE + '/api/videos/session', data=json.dumps({'password': 'Secr3t!'}).encode(), method='POST',
                           headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(r) as res:
    cookie = res.headers['Set-Cookie'].split(';')[0]


def get(path, headers=None):
    with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={'Cookie': cookie, **(headers or {})})) as res:
        return res.status, res.read(), res.headers


converted = open(vc.converted_file(videos.video_file('f/a.avi')), 'rb').read()
code, body, h = get('/api/videos/file?p=' + urllib.parse.quote('f/a.avi'))
assert code == 200 and h['Content-Type'] == 'video/mp4' and body == converted
code, body, h = get('/api/videos/file?p=' + urllib.parse.quote('f/a.avi'), {'Range': 'bytes=100-199'})
assert code == 206 and body == converted[100:200]
assert get('/api/videos/file?p=' + urllib.parse.quote('f/a.avi') + '&download=1')[1] == open(os.path.join(VIDEOS, 'f', 'a.avi'), 'rb').read()
listing = json.loads(get('/api/videos/list?p=f')[1])
assert {v['name']: v['converted'] for v in listing['videos']}['a'] is True
srv.shutdown()

# 원본이 바뀌면 변환본은 없는 것으로 보이고, 정리하면 옛 변환본이 지워짐
old = vc.converted_file(videos.video_file('f/a.avi'))
with open(os.path.join(VIDEOS, 'f', 'a.avi'), 'ab') as f:
    f.write(b'\0' * 10)
assert vc.converted_file(videos.video_file('f/a.avi')) is None
os.remove(os.path.join(VIDEOS, 'f', 'd.avi'))
assert vc.cleanup() == 2 and not os.path.exists(old) and vc.job('f/d.avi') is None
print('test_video_convert: OK (실제 변환 포함)')
