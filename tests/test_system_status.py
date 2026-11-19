"""NAS 상태(system_status.py, 대시보드 'NAS 상태' 카드): /proc에서 CPU·메모리·부하 읽기, 같은 디스크는 하나로,
컨테이너가 남긴 기록 시각으로 살아 있는지 판단, 동영상 변환 집계, API는 관리자만"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import TESTS_DIR
import tempfile, json, socket, threading, urllib.request, urllib.error
from datetime import datetime, timedelta

OUT = tempfile.mkdtemp()
VIDEOS = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=OUT, LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', VIDEOS_DIR=VIDEOS,
                  COMICS_DIR=os.path.join(OUT, 'none'))
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, runtime_status, system_status as ss, video_convert

storage.init_db()
stat_calls = []
PROC = {
    '/proc/meminfo': "MemTotal:        1870848 kB\nMemFree:          100000 kB\nMemAvailable:     870848 kB\nSwapTotal:       3220480 kB\nSwapFree:        2420480 kB\n",
    '/proc/loadavg': "2.00 1.60 1.48 3/400 12345\n",
    '/proc/uptime': "1946000.12 3000000.00\n",
}


def fake_read(path):
    if path == '/proc/stat':
        stat_calls.append(1)
        # 두 번째 측정까지 1000틱 중 idle 250 → 75%
        return "cpu  100 0 100 800 0 0 0\n" if len(stat_calls) % 2 else "cpu  475 0 475 1050 0 0 0\n"
    return PROC[path]


ss._read = fake_read
ss.CPU_SAMPLE_SECONDS = 0

# ---- CPU·메모리
assert ss.cpu_percent() == 75.0
mem = ss.memory()
assert mem['total'] == 1870848 * 1024 and mem['used'] == 1000000 * 1024 and mem['swap_used'] == 800000 * 1024, mem

# ---- 디스크: output과 동영상이 같은 디스크면 하나로
disks = ss.disks()
assert len(disks) == 1 and disks[0]['label'] == 'DB·이미지·변환본 · 동영상' and disks[0]['total'] > 0 and disks[0]['free'] <= disks[0]['total'], disks

# ---- 컨테이너: 기록 시각으로 판단
fmt = lambda d: d.strftime('%Y-%m-%d %H:%M:%S')
now = datetime.now()
runtime_status._status.update(started_at=fmt(now - timedelta(hours=2)), progress_at=fmt(now - timedelta(seconds=30)),
                              last_cycle={'finished_at': fmt(now - timedelta(minutes=1)), 'seconds': 26, 'new': 3}, block_streak=0)
runtime_status._writer = True   # 이 프로세스의 상태를 그대로 씀 (파일 대신)
storage.set_meta('card_mail_status', json.dumps({'state': 'ok', 'checked_at': fmt(now - timedelta(minutes=10))}))
storage.set_meta('convert_heartbeat', fmt(now - timedelta(minutes=20)))
svc = {s['key']: s for s in ss.services()}
assert svc['collector']['ok'] and '새 글 3' in svc['collector']['detail'], svc['collector']
assert svc['web']['ok'] and svc['mail']['ok']
assert svc['convert']['ok'] is False and svc['convert']['detail'] == '소식 없음'      # 20분째 소식 없음
storage.set_meta('convert_heartbeat', fmt(now))
storage.set_meta('card_mail_status', json.dumps({'state': 'off', 'checked_at': fmt(now)}))
svc = {s['key']: s for s in ss.services()}
assert svc['convert']['ok'] and svc['mail']['ok'] is None and svc['mail']['detail'] == '꺼짐'
runtime_status._status.update(progress_at=fmt(now - timedelta(hours=1)), last_cycle={'finished_at': fmt(now - timedelta(hours=1))},
                              started_at=fmt(now - timedelta(hours=2)))
assert {s['key']: s for s in ss.services()}['collector']['ok'] is False      # 한 시간째 움직이지 않음

# ---- 동영상 변환 집계
video_convert.enqueue('a.avi', 'transcode')
video_convert.enqueue('b.avi', 'transcode')
assert video_convert._claim('a.avi')
video_convert._set('a.avi', progress=0.42, speed=1.5)
os.makedirs(os.path.join(video_convert.CONV_DIR, 'ab'))
open(os.path.join(video_convert.CONV_DIR, 'ab', 'x.mp4'), 'wb').write(b'0' * 1000)
open(os.path.join(video_convert.CONV_DIR, 'ab', 'y.part.mp4'), 'wb').write(b'0' * 5000)   # 만드는 중인 것은 안 셈
conv = ss.conversion()
assert conv['queued'] == 1 and conv['running'][0]['name'] == 'a' and conv['running'][0]['progress'] == 0.42, conv
assert conv['size'] == 1000 and conv['files'] == 1, conv

# ---- 한 번에
snap = ss.snapshot()
assert snap['load'] == [2.0, 1.6, 1.48] and snap['uptime'] == '22일 12시간' and snap['cpu'] == 75.0, snap

# /proc을 못 읽는 곳에서도 카드 전체가 오류가 되지 않고 그 값만 비움
def broken(path):
    raise FileNotFoundError(path)
ss._read = broken
snap = ss.snapshot()
assert snap['cpu'] is None and snap['memory'] is None and snap['load'] is None and snap['uptime'] is None and snap['disks'], snap
ss._read = fake_read

# ---- API: 관리자 키가 있어야
import web_server
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def post(body):
    r = urllib.request.Request(f'http://127.0.0.1:{port}/api/system', data=json.dumps(body).encode(), method='POST',
                               headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, None


assert post({})[0] == 401
web_server._clear_auth_failures('127.0.0.1')
code, data = post({'password': web_server.ADMIN_TOKEN})
assert code == 200 and data['memory']['total'] and data['conversion']['queued'] == 1 and len(data['services']) == 4, data
srv.shutdown()
print('SYSTEM STATUS OK')
