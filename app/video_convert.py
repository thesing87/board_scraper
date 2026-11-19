"""
브라우저가 못 여는 동영상을 브라우저용 MP4(H.264 + AAC)로 바꿔 output/video_conv에 저장

형식을 ffmpeg로 조사해(probe, DB video_probe에 기억) 세 가지로 나눔
- direct: 그대로 재생됨 (MP4·MKV 등 + H.264·HEVC·VP9·AV1 화면 + AAC·MP3·Opus 등 소리)
- remux: 화면은 그대로 재생되는데 포장(AVI·WMV 등)이나 소리(AC3·MP2·PCM·WMA)만 안 맞음
  → 화면은 복사하고 소리만 AAC로 → 1시간짜리도 1분 안팎. 재생 버튼을 누르면 바로 시작
- transcode: 화면 형식(DivX·Xvid·WMV·MPEG-1 등)을 브라우저가 못 풂
  → libx264로 다시 부호화 (720p까지 줄임). 이 NAS에서 SD는 실시간의 약 4배, 720p는 1~3배 → 누를 때 시작하거나 자동 변환이 남는 때에 차례로

변환은 웹서버가 아니라 fmkorea-convert 컨테이너(video_worker.py)가 함: CPU 몫을 가장 작게 잡아(cpu_shares)
게시판 수집·웹서버를 방해하지 않게. 웹서버는 DB(video_jobs)에 작업을 넣고 진행 상황을 읽기만 함.
줄은 둘: 빠른 줄(remux)과 느린 줄(transcode). 긴 변환이 도는 중에도 remux는 바로 됨.

변환본 이름은 원본 경로·크기·수정 시각으로 정하므로 원본이 바뀌면 자연히 새로 변환해야 하는 것으로 보임
(옛 변환본은 cleanup()이 지움)
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime

from config import OUTPUT_DIR, VIDEO_AUTO_HOURS
from storage import _db, _now
import videos

CONV_DIR = os.path.join(OUTPUT_DIR, 'video_conv')
# 브라우저가 푸는 화면·소리 형식 (ffmpeg 이름)
BROWSER_VIDEO = {'h264', 'hevc', 'vp8', 'vp9', 'av1'}
BROWSER_AUDIO = {'aac', 'mp3', 'opus', 'vorbis', 'flac'}
# MP4에 그대로 넣어도 되는 소리 (나머지는 AAC로)
MP4_AUDIO = {'aac', 'mp3'}
# 그대로 보내는 포장 (videos.PLAYABLE_TYPES와 같음)
DIRECT_CONTAINERS = set(videos.PLAYABLE_TYPES)
# 화면을 다시 부호화할 때 최대 높이 (CPU·메모리 한도 때문에 1080p는 720p로 줄임)
MAX_HEIGHT = 720
CRF = 23
AUDIO_BITRATE = '160k'
# video_jobs.night 값 (이름은 예전 '밤 예약'에서 남은 것): 0 지금 변환, AUTO 자동 변환(직접 넣은 작업 뒤에).
# 작업은 이 값 순서(지금 → 자동), 그다음 넣은 순서로 꺼냄. 예전 밤 예약(1)은 작업기가 시작할 때 자동 변환으로 바꿈
OLD_NIGHT, AUTO = 1, 2
# 자동 변환을 돌리는 시간 (시, 시작 이상 ~ 끝 미만, 자정을 넘겨도 됨). 끝나면 도는 자동 변환도 멈추고 다음 날 처음부터
AUTO_START, AUTO_END = VIDEO_AUTO_HOURS
PROBE_TIMEOUT = 30
# 미리 어림하는 변환 속도 (실시간의 몇 배). 실제로 돌면 잰 속도로 바뀜
SPEED_GUESS = ((576, 4.0), (720, 1.6), (99999, 1.0))
REMUX_SPEED_GUESS = 40.0
PROGRESS_EVERY = 3


# ==========================================
# 형식 조사
# ==========================================
def _ffmpeg():
    return shutil.which('ffmpeg')


def _parse_probe(text):
    info = {'video': None, 'audio': None, 'width': 0, 'height': 0, 'duration': 0.0}
    m = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', text)
    if m:
        info['duration'] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in text.splitlines():
        if 'Stream #' not in line:
            continue
        v = re.search(r'Video: (\w+)', line)
        if v and info['video'] is None and 'attached pic' not in line:
            info['video'] = v.group(1)
            size = re.search(r', (\d{2,5})x(\d{2,5})', line)
            if size:
                info['width'], info['height'] = int(size.group(1)), int(size.group(2))
        a = re.search(r'Audio: (\w+)', line)
        if a and info['audio'] is None:
            info['audio'] = a.group(1)
    return info


def mode_of(info, ext):
    if not info.get('video'):
        return 'direct' if ext in DIRECT_CONTAINERS else 'remux'
    if info['video'] not in BROWSER_VIDEO:
        return 'transcode'
    if ext in DIRECT_CONTAINERS and (info.get('audio') is None or info['audio'] in BROWSER_AUDIO):
        return 'direct'
    return 'remux'


def probe(rel, full=None):
    """영상의 형식 {'video','audio','width','height','duration','mode'}. 조사 못 하면 None"""
    full = full or videos.video_file(rel)
    if not full:
        return None
    st = os.stat(full)
    with _db() as conn:
        row = conn.execute("SELECT size, mtime, info FROM video_probe WHERE path = ?", (rel,)).fetchone()
    if row and row['size'] == st.st_size and row['mtime'] == st.st_mtime_ns:
        return json.loads(row['info'])
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return None
    try:
        out = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-i', full], capture_output=True, text=True,
                             errors='replace', timeout=PROBE_TIMEOUT).stderr
    except (subprocess.TimeoutExpired, OSError):
        return None
    info = _parse_probe(out)
    info['mode'] = mode_of(info, videos._ext(full))
    with _db() as conn, conn:
        conn.execute("INSERT INTO video_probe(path, size, mtime, info) VALUES(?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET "
                     "size = excluded.size, mtime = excluded.mtime, info = excluded.info",
                     (rel, st.st_size, st.st_mtime_ns, json.dumps(info)))
    return info


def cached_probes(paths):
    """DB에 기억해 둔 형식만 {경로: info} (목록에서 ffmpeg를 돌리지 않으려고)"""
    out = {}
    paths = list(paths)
    with _db() as conn:
        for start in range(0, len(paths), 500):
            chunk = paths[start:start + 500]
            for r in conn.execute(f"SELECT path, info FROM video_probe WHERE path IN ({','.join('?' * len(chunk))})", chunk):
                out[r['path']] = json.loads(r['info'])
    return out


def estimate_seconds(info, mode):
    """변환에 걸릴 시간 어림 (초)"""
    duration = (info or {}).get('duration') or 0
    if mode == 'remux':
        return duration / REMUX_SPEED_GUESS
    height = min((info or {}).get('height') or 0, MAX_HEIGHT * 10)
    speed = next(s for h, s in SPEED_GUESS if height <= h)
    return duration / speed


# ==========================================
# 변환본
# ==========================================
def output_path(full):
    st = os.stat(full)
    key = hashlib.sha1(f"{full}|{st.st_size}|{st.st_mtime_ns}".encode('utf-8')).hexdigest()
    return os.path.join(CONV_DIR, key[:2], key + '.mp4')


def converted_file(full):
    """다 만든 변환본 경로. 없으면 None"""
    try:
        path = output_path(full)
    except OSError:
        return None
    return path if os.path.isfile(path) else None


# ==========================================
# 작업 (웹서버 쪽: 넣고·빼고·읽기)
# ==========================================
def _job_dict(row):
    if not row:
        return None
    return {'state': row['state'], 'kind': row['kind'], 'auto': bool(row['night']), 'progress': row['progress'],
            'speed': row['speed'], 'error': row['error'], 'updated_at': row['updated_at']}


def job(rel):
    with _db() as conn:
        return _job_dict(conn.execute("SELECT * FROM video_jobs WHERE path = ?", (rel,)).fetchone())


def jobs_for(paths):
    out = {}
    paths = list(paths)
    with _db() as conn:
        for start in range(0, len(paths), 500):
            chunk = paths[start:start + 500]
            for r in conn.execute(f"SELECT * FROM video_jobs WHERE path IN ({','.join('?' * len(chunk))})", chunk):
                out[r['path']] = _job_dict(r)
    return out


def enqueue(rel, kind='auto', auto=False):
    """변환 작업을 넣음. 이미 대기·진행 중이면 그대로(자동 변환이 '지금 변환'으로 바뀌는 것만 반영)"""
    now = _now()
    value = AUTO if auto else 0
    with _db() as conn, conn:
        row = conn.execute("SELECT state, night FROM video_jobs WHERE path = ?", (rel,)).fetchone()
        if row and row['state'] in ('queued', 'running'):
            if row['night'] and value == 0:
                conn.execute("UPDATE video_jobs SET night = 0, kind = ?, updated_at = ? WHERE path = ?", (kind, now, rel))
            return
        conn.execute("INSERT INTO video_jobs(path, state, kind, night, progress, speed, error, created_at, updated_at) "
                     "VALUES(?, 'queued', ?, ?, 0, NULL, NULL, ?, ?) ON CONFLICT(path) DO UPDATE SET state = 'queued', "
                     "kind = excluded.kind, night = excluded.night, progress = 0, speed = NULL, error = NULL, "
                     "created_at = excluded.created_at, updated_at = excluded.updated_at",
                     (rel, kind, value, now, now))


def cancel(rel):
    """대기 중이면 지우고, 도는 중이면 멈추라고 표시 (작업기가 보고 멈춤).
    자동 변환으로 들어온 것은 지우지 않고 'skipped'로 남겨 다음 훑기에서 다시 넣지 않음"""
    with _db() as conn, conn:
        conn.execute("UPDATE video_jobs SET state = 'skipped', updated_at = ? WHERE path = ? AND state = 'queued' AND night = ?", (_now(), rel, AUTO))
        conn.execute("DELETE FROM video_jobs WHERE path = ? AND state IN ('queued', 'failed')", (rel,))
        conn.execute("UPDATE video_jobs SET state = 'cancel', updated_at = ? WHERE path = ? AND state = 'running'", (_now(), rel))


def needs_convert(v, probe_info):
    """목록의 영상 하나가 변환이 필요한지: True·False·None(아직 모름 — MP4 등은 열어 봐야 앎)"""
    if probe_info:
        return probe_info.get('mode') != 'direct'
    if '.' + v['ext'] not in DIRECT_CONTAINERS:
        return True
    return None


def annotate(listing):
    """목록(videos.list_dir)의 영상마다 변환 상태를 붙임: convert(필요 여부), converted, job"""
    items = listing.get('videos') or []
    paths = [v['path'] for v in items]
    probes = cached_probes(paths)
    jobs = jobs_for(paths)
    for v in items:
        full = videos.resolve(v['path'])
        v['converted'] = bool(full and converted_file(full))
        v['convert'] = needs_convert(v, probes.get(v['path']))
        v['job'] = jobs.get(v['path'])
        # 변환본이 있으면 재생 가능, 없으면 재생 화면에서 변환을 안내 (누르면 재생 화면이 열림)
        v['playable'] = True
    return listing


def enqueue_folder(rel):
    """폴더 안(하위 폴더 제외) 영상 중 변환이 필요하거나 아직 모르는 것을 자동 변환 순서에 넣음 (다음 훑기를 기다리지 않고). 넣은 개수"""
    listing = videos.list_dir(rel)
    if listing is None:
        return None
    annotate(listing)
    count = 0
    for v in listing['videos']:
        if v['converted'] or v['convert'] is False or (v['job'] and v['job']['state'] in ('queued', 'running')):
            continue
        enqueue(v['path'], 'auto', auto=True)
        count += 1
    return count


def _walk_videos():
    """동영상 폴더 전체(하위 폴더 포함, 숨긴 폴더 제외)의 영상 (상대 경로, 실제 경로)"""
    root = videos.resolve('')
    if not root or not os.path.isdir(root):
        return
    for top, dirs, files in os.walk(root):
        dirs[:] = sorted((d for d in dirs if not videos.HIDDEN_RE.match(d)), key=videos.natural_key)
        rel_top = os.path.relpath(top, root).replace(os.sep, '/')
        for name in sorted(files, key=videos.natural_key):
            if videos.HIDDEN_RE.match(name) or not videos.is_video(name):
                continue
            yield (name if rel_top == '.' else f'{rel_top}/{name}'), os.path.join(top, name)


def scan_library(keep_going=None):
    """자동 변환: 동영상 폴더 전체에서 변환이 필요한 영상을 찾아 자동 변환으로 넣음 (아무 때나, 직접 넣은 작업 뒤에).
    형식을 모르는 영상은 조사(DB에 기억하므로 다음 훑기에서는 바로 넘어감). 이미 변환했거나 대기·진행 중,
    전에 실패했거나 자동 변환을 취소한 영상은 넣지 않음 (재생 화면에서 직접 하면 됨). keep_going()이 False가 되면 멈춤.
    (훑은 영상 수, 넣은 수)"""
    keep_going = keep_going or (lambda: True)
    seen = added = 0
    for rel, full in _walk_videos():
        if not keep_going():
            break
        seen += 1
        current = job(rel)
        if current and current['state'] in ('queued', 'running', 'failed', 'cancel', 'skipped'):
            continue
        try:
            if converted_file(full):
                continue
            info = probe(rel, full)
        except OSError:
            continue
        if not info or info['mode'] == 'direct':
            continue
        enqueue(rel, info['mode'], auto=True)
        added += 1
    return seen, added


def status(rel):
    """재생 화면용: 형식·변환 필요 여부·작업 상태·어림 시간"""
    full = videos.video_file(rel)
    if not full:
        return None
    info = probe(rel, full)
    conv = converted_file(full)
    mode = info['mode'] if info else ('direct' if videos._ext(full) in DIRECT_CONTAINERS else 'transcode')
    return {'mode': mode, 'info': info, 'converted': bool(conv), 'job': job(rel),
            'estimate': round(estimate_seconds(info, mode)) if info else None, 'auto_hours': [AUTO_START, AUTO_END]}


# ==========================================
# 작업기 쪽 (fmkorea-convert 컨테이너의 video_worker.py가 부름)
# ==========================================
def build_command(ffmpeg, src, dst, info, mode):
    cmd = ['nice', '-n', '19'] if shutil.which('nice') else []
    cmd += [ffmpeg, '-hide_banner', '-nostdin', '-y', '-v', 'error', '-progress', 'pipe:1', '-nostats',
            '-fflags', '+genpts', '-i', src, '-map', '0:v:0', '-map', '0:a:0?', '-sn', '-dn',
            '-max_muxing_queue_size', '2048']
    if mode == 'remux':
        cmd += ['-c:v', 'copy']
        if info.get('video') == 'hevc':
            cmd += ['-tag:v', 'hvc1']
    else:
        preset = 'veryfast' if (info.get('height') or 0) <= 576 else 'superfast'
        cmd += ['-vf', f"scale=-2:'min({MAX_HEIGHT},ih)',format=yuv420p", '-c:v', 'libx264', '-preset', preset,
                '-crf', str(CRF), '-profile:v', 'high', '-threads', '2']
    if info.get('audio') in MP4_AUDIO:
        cmd += ['-c:a', 'copy']
    else:
        cmd += ['-c:a', 'aac', '-b:a', AUDIO_BITRATE, '-ac', '2']
    cmd += ['-movflags', '+faststart', '-f', 'mp4', dst]
    return cmd


def _set(rel, **fields):
    fields['updated_at'] = _now()
    with _db() as conn, conn:
        conn.execute(f"UPDATE video_jobs SET {', '.join(k + ' = ?' for k in fields)} WHERE path = ?", (*fields.values(), rel))


def auto_time(now=None):
    """자동 변환 시간인지"""
    hour = (now or datetime.now()).hour
    if AUTO_START < AUTO_END:
        return AUTO_START <= hour < AUTO_END
    return hour >= AUTO_START or hour < AUTO_END


def next_job(lane, now=None):
    """lane: 'fast'(remux만) 또는 'slow'(나머지). 지금 변환이 먼저, 자동 변환은 자동 변환 시간에만"""
    auto_ok = auto_time(now)
    with _db() as conn:
        rows = conn.execute("SELECT * FROM video_jobs WHERE state = 'queued' ORDER BY night, created_at").fetchall()
    for r in rows:
        if r['night'] and not auto_ok:
            continue
        if (lane == 'fast') != (r['kind'] == 'remux'):
            continue
        return r['path'], r['kind']
    return None


def _claim(rel):
    """대기 → 진행으로 (다른 줄이 먼저 가져가지 않았을 때만)"""
    with _db() as conn, conn:
        cur = conn.execute("UPDATE video_jobs SET state = 'running', progress = 0, updated_at = ? WHERE path = ? AND state = 'queued'",
                           (_now(), rel))
        return cur.rowcount == 1


def run_job(rel, kind):
    """작업 하나를 끝까지. 결과 상태를 돌려줌 (done·failed·cancel·skip)"""
    full = videos.video_file(rel)
    if not full:
        with _db() as conn, conn:
            conn.execute("DELETE FROM video_jobs WHERE path = ?", (rel,))
        return 'skip'
    info = probe(rel, full)
    if not info:
        _set(rel, state='failed', error='형식을 읽지 못함')
        return 'failed'
    mode = info['mode']
    if mode == 'direct' or converted_file(full):
        # 그대로 재생되거나 이미 있음 (폴더 예약으로 들어온 MP4 등)
        with _db() as conn, conn:
            conn.execute("DELETE FROM video_jobs WHERE path = ?", (rel,))
        return 'skip'
    dst = output_path(full)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + '.part.mp4'
    cmd = build_command(_ffmpeg(), full, tmp, info, mode)
    duration = info.get('duration') or 0
    started = time.time()
    last = 0
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace')
    err_lines = []
    err_reader = threading.Thread(target=lambda: err_lines.extend(proc.stderr), daemon=True)
    err_reader.start()
    cancelled = False
    for line in proc.stdout:
        if not line.startswith('out_time_us=') or time.time() - last < PROGRESS_EVERY:
            continue
        last = time.time()
        try:
            done_sec = int(line.split('=', 1)[1]) / 1e6
        except ValueError:
            continue
        current = job(rel)
        if not current or current['state'] == 'cancel':
            cancelled = True
            proc.kill()
            break
        if current['auto'] and not auto_time():
            # 자동 변환 시간이 끝남: 멈추고 대기로 돌려 다음 날 처음부터
            proc.kill()
            proc.wait()
            err_reader.join(timeout=5)
            _remove(tmp)
            _set(rel, state='queued', progress=0, speed=None)
            return 'paused'
        elapsed = max(0.1, time.time() - started)
        _set(rel, progress=min(0.999, done_sec / duration) if duration else 0, speed=round(done_sec / elapsed, 2))
    code = proc.wait()
    err_reader.join(timeout=5)
    if cancelled:
        _remove(tmp)
        with _db() as conn, conn:
            conn.execute("DELETE FROM video_jobs WHERE path = ?", (rel,))
        return 'cancel'
    if code != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        _remove(tmp)
        _set(rel, state='failed', error=(''.join(err_lines[-5:]).strip() or f'ffmpeg 종료 코드 {code}')[-500:])
        return 'failed'
    os.replace(tmp, dst)
    elapsed = max(0.1, time.time() - started)
    _set(rel, state='done', progress=1, speed=round(duration / elapsed, 2) if duration else None)
    return 'done'


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def recover():
    """작업기가 다시 시작하면 하다 만 작업을 다시 대기로, 반쯤 만든 파일은 지움"""
    with _db() as conn, conn:
        conn.execute("UPDATE video_jobs SET state = 'queued', progress = 0 WHERE state = 'running'")
        conn.execute("DELETE FROM video_jobs WHERE state = 'cancel'")
        conn.execute("UPDATE video_jobs SET night = ? WHERE night = ?", (AUTO, OLD_NIGHT))
    for root, _, files in os.walk(CONV_DIR):
        for name in files:
            if name.endswith('.part.mp4'):
                _remove(os.path.join(root, name))


def cleanup():
    """원본이 사라지거나 바뀐 변환본·작업 기록을 지움. 지운 파일 수"""
    keep = set()
    with _db() as conn:
        rows = conn.execute("SELECT path, state FROM video_jobs").fetchall()
    gone = []
    for r in rows:
        full = videos.video_file(r['path'])
        if not full:
            gone.append(r['path'])
            continue
        try:
            keep.add(os.path.basename(output_path(full)))
        except OSError:
            pass
    if gone:
        with _db() as conn, conn:
            conn.executemany("DELETE FROM video_jobs WHERE path = ?", [(p,) for p in gone])
    removed = 0
    for root, _, files in os.walk(CONV_DIR):
        for name in files:
            if name.endswith('.mp4') and not name.endswith('.part.mp4') and name not in keep:
                _remove(os.path.join(root, name))
                removed += 1
    return removed
