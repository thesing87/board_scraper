"""동영상(/videos/): NAS의 동영상 폴더(VIDEOS_DIR, 컨테이너에는 읽기 전용으로 연결)를 둘러보고 브라우저에서 바로 재생.

- 바로 재생: MP4·MOV·M4V·WebM은 파일을 그대로 보냄 (Range 요청으로 원하는 위치부터). MKV는 크롬에서 재생됨
- AVI·WMV 등 브라우저가 못 여는 형식은 목록에 '재생 불가'로 표시하고 내려받기만 (변환은 하지 않음)
- 썸네일: 처음 볼 때 ffmpeg로 영상 앞부분 한 장면을 뽑아 output/video_thumbs에 저장 (파일이 바뀌면 다시 뽑음)
- 자막: 영상과 이름이 같은 .srt·.smi를 브라우저용 WebVTT로 바꿔 보냄
- 경로는 모두 동영상 폴더 기준 상대 경로('/' 구분). 폴더 밖(.. 이나 심볼릭 링크)으로 나가는 경로는 거부
- 이어 보기 위치는 DB(video_progress)에 저장
"""
import hashlib
import html
import os
import re
import shutil
import subprocess
import threading
import time

from config import VIDEOS_DIR, OUTPUT_DIR
from storage import _db, _now

# 브라우저가 바로 재생하는 형식 (MKV는 크롬·엣지·안드로이드에서 재생, 아이폰 사파리는 못 함)
PLAYABLE_TYPES = {
    '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/mp4', '.webm': 'video/webm', '.mkv': 'video/x-matroska',
}
# 목록에는 보이지만 재생은 못 하는 형식 (내려받기만)
OTHER_TYPES = {
    '.avi': 'video/x-msvideo', '.wmv': 'video/x-ms-wmv', '.asf': 'video/x-ms-asf', '.flv': 'video/x-flv',
    '.mpg': 'video/mpeg', '.mpeg': 'video/mpeg', '.ts': 'video/mp2t', '.3gp': 'video/3gpp', '.rmvb': 'application/vnd.rn-realmedia-vbr',
}
SUBTITLE_EXTS = ('.srt', '.smi', '.vtt')
HIDDEN_RE = re.compile(r'^(\.|@eaDir$|#recycle$|#snapshot$)')
THUMB_DIR = os.path.join(OUTPUT_DIR, 'video_thumbs')
THUMB_WIDTH = 480
THUMB_TIMEOUT = 25
# 썸네일 ffmpeg는 한 번에 하나만 (NAS CPU 2개·웹서버 메모리 한도 384MB)
_thumb_lock = threading.Semaphore(1)
MAX_SUBTITLE_BYTES = 5 * 1024 * 1024


def configured():
    return bool(VIDEOS_DIR) and os.path.isdir(VIDEOS_DIR)


def natural_key(name):
    return [(0, int(part), '') if part.isdigit() else (1, 0, part) for part in re.split(r'(\d+)', name.lower()) if part]


def resolve(rel):
    """상대 경로 → 실제 경로. 동영상 폴더 밖이거나 숨긴 이름이 들어 있으면 None"""
    rel = (rel or '').replace('\\', '/').strip('/')
    parts = [p for p in rel.split('/') if p]
    if any(p in ('.', '..') or HIDDEN_RE.match(p) for p in parts):
        return None
    root = os.path.realpath(VIDEOS_DIR)
    full = os.path.realpath(os.path.join(root, *parts))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


def _ext(name):
    return os.path.splitext(name)[1].lower()


def is_video(name):
    return _ext(name) in PLAYABLE_TYPES or _ext(name) in OTHER_TYPES


def content_type(name):
    return PLAYABLE_TYPES.get(_ext(name)) or OTHER_TYPES.get(_ext(name)) or 'application/octet-stream'


def _join(rel, name):
    return f"{rel}/{name}" if rel else name


def video_file(rel):
    """재생·내려받기할 영상 파일의 실제 경로. 영상 파일이 아니면 None"""
    full = resolve(rel)
    if not full or not rel or not os.path.isfile(full) or not is_video(full):
        return None
    return full


def list_dir(rel):
    """폴더 안의 하위 폴더·영상. 없는 폴더면 None"""
    rel = (rel or '').replace('\\', '/').strip('/')
    full = resolve(rel)
    if not full or not os.path.isdir(full):
        return None
    dirs, videos = [], []
    with os.scandir(full) as it:
        entries = [e for e in it if not HIDDEN_RE.match(e.name)]
    names = {e.name.lower() for e in entries}
    for entry in entries:
        try:
            if entry.is_dir():
                dirs.append({'name': entry.name, 'path': _join(rel, entry.name)})
            elif entry.is_file() and is_video(entry.name):
                stem = os.path.splitext(entry.name)[0].lower()
                videos.append({'name': os.path.splitext(entry.name)[0], 'path': _join(rel, entry.name),
                               'ext': _ext(entry.name)[1:], 'size': entry.stat().st_size,
                               'playable': _ext(entry.name) in PLAYABLE_TYPES,
                               'subtitle': any(stem + ext in names for ext in SUBTITLE_EXTS)})
        except OSError:
            continue
    dirs.sort(key=lambda d: natural_key(d['name']))
    videos.sort(key=lambda v: natural_key(v['name']))
    progress = progress_for([v['path'] for v in videos])
    for v in videos:
        v['progress'] = progress.get(v['path'])
    return {'path': rel, 'name': os.path.basename(rel) if rel else '', 'dirs': dirs, 'videos': videos}


# ==========================================
# 전체 영상 목록 (검색·최근 추가용)
# 폴더를 다 훑으면 디스크가 쉬던 뒤 몇 초 걸리므로 기억해 두고 INDEX_TTL마다 새로 훑음 (훑는 동안은 예전 목록으로 답함)
# 최근 추가는 파일이 이 폴더에 들어온 시각(ctime: 복사·이동할 때 바뀜. 수정 시각은 원래 파일 것을 그대로 가져오는 일이 많음)
# ==========================================
INDEX_TTL = 600
SEARCH_LIMIT = 120
LATEST_LIMIT = 24
_index = {'at': 0.0, 'items': [], 'root': None}
_index_lock = threading.Lock()
_index_building = threading.Lock()


def _scan_all():
    items = []
    root = VIDEOS_DIR
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted((d for d in dirs if not HIDDEN_RE.match(d)), key=natural_key)
        rel_folder = os.path.relpath(folder, root).replace(os.sep, '/')
        rel_folder = '' if rel_folder == '.' else rel_folder
        names = {n.lower() for n in files}
        for name in files:
            if HIDDEN_RE.match(name) or not is_video(name):
                continue
            try:
                st = os.stat(os.path.join(folder, name))
            except OSError:
                continue
            stem = os.path.splitext(name)[0]
            items.append({'name': stem, 'path': _join(rel_folder, name), 'folder': rel_folder, 'ext': _ext(name)[1:],
                          'size': st.st_size, 'added': max(st.st_ctime, st.st_mtime),
                          'playable': _ext(name) in PLAYABLE_TYPES,
                          'subtitle': any(stem.lower() + ext in names for ext in SUBTITLE_EXTS),
                          '_key': f"{stem} {rel_folder}".lower()})
    return items


def all_videos():
    """동영상 폴더 전체의 영상 (기억해 둔 목록). 처음이거나 오래됐으면 새로 훑음"""
    now = time.time()
    with _index_lock:
        fresh = _index['root'] == VIDEOS_DIR and now - _index['at'] < INDEX_TTL
        items = _index['items'] if _index['root'] == VIDEOS_DIR else None
    if fresh:
        return items
    # 다른 요청이 훑는 중이면 예전 목록으로 (처음이라 없으면 끝날 때까지 기다림)
    if not _index_building.acquire(blocking=items is None):
        return items
    try:
        with _index_lock:
            if _index['root'] == VIDEOS_DIR and time.time() - _index['at'] < INDEX_TTL:
                return _index['items']
        scanned = _scan_all()
        with _index_lock:
            _index.update(at=time.time(), items=scanned, root=VIDEOS_DIR)
        return scanned
    finally:
        _index_building.release()


def _public(item):
    return {k: v for k, v in item.items() if not k.startswith('_')}


def _with_progress(items):
    progress = progress_for([v['path'] for v in items])
    for v in items:
        v['progress'] = progress.get(v['path'])
    return items


def search(query, limit=SEARCH_LIMIT):
    """이름·폴더에 검색어(띄어 쓴 낱말 모두)가 들어간 영상. 이름에 들어간 것 먼저. (결과, 전체 개수)"""
    terms = [t for t in (query or '').lower().split() if t]
    if not terms:
        return [], 0
    found = [v for v in all_videos() if all(t in v['_key'] for t in terms)]
    found.sort(key=lambda v: (not all(t in v['name'].lower() for t in terms), natural_key(v['folder']), natural_key(v['name'])))
    return _with_progress([_public(v) for v in found[:limit]]), len(found)


def latest(limit=LATEST_LIMIT):
    """최근에 들어온 영상"""
    items = sorted(all_videos(), key=lambda v: v['added'], reverse=True)[:limit]
    return _with_progress([_public(v) for v in items])


# ==========================================
# 썸네일
# ==========================================
def _ffmpeg():
    return shutil.which('ffmpeg')


# 폴더 칸에 작게 모아 보여 줄 영상 수
SAMPLE_COUNT = 4
# {폴더 경로: (폴더 수정 시각, [영상 상대 경로])} — 폴더 칸마다 안을 읽으면 디스크가 쉬던 뒤 처음에 느려 기억해 둠
_samples_cache = {}
_samples_lock = threading.Lock()
SAMPLES_CACHE_SIZE = 5000


def _sample_videos(full, rel, depth=2):
    """폴더 안 영상을 이름순으로 SAMPLE_COUNT개까지 (재생되는 형식 먼저). 모자라면 하위 폴더에서 채움"""
    try:
        with os.scandir(full) as it:
            entries = sorted((e for e in it if not HIDDEN_RE.match(e.name)), key=lambda e: natural_key(e.name))
    except OSError:
        return []
    files = [e for e in entries if e.is_file() and is_video(e.name)]
    files.sort(key=lambda e: _ext(e.name) not in PLAYABLE_TYPES)
    found = [_join(rel, e.name) for e in files[:SAMPLE_COUNT]]
    if len(found) < SAMPLE_COUNT and depth > 0:
        for e in entries:
            if e.is_dir():
                found += _sample_videos(e.path, _join(rel, e.name), depth - 1)[:SAMPLE_COUNT - len(found)]
                if len(found) >= SAMPLE_COUNT:
                    break
    return found


def folder_samples(rel):
    """하위 폴더마다 칸에 보여 줄 영상들 {폴더 경로: [영상 경로]}. 없는 폴더면 None"""
    rel = (rel or '').replace('\\', '/').strip('/')
    full = resolve(rel)
    if not full or not os.path.isdir(full):
        return None
    with os.scandir(full) as it:
        subdirs = [e for e in it if not HIDDEN_RE.match(e.name) and e.is_dir()]
    out = {}
    for entry in subdirs:
        try:
            mtime = entry.stat().st_mtime_ns
        except OSError:
            continue
        sub_rel = _join(rel, entry.name)
        with _samples_lock:
            hit = _samples_cache.get(entry.path)
        if hit and hit[0] == mtime:
            out[sub_rel] = hit[1]
            continue
        samples = _sample_videos(entry.path, sub_rel)
        with _samples_lock:
            _samples_cache[entry.path] = (mtime, samples)
            if len(_samples_cache) > SAMPLES_CACHE_SIZE:
                _samples_cache.pop(next(iter(_samples_cache)))
        out[sub_rel] = samples
    return out


def _thumb_source(full):
    """폴더의 썸네일로 쓸 영상: 폴더 안 첫 영상 → 첫 하위 폴더 안에서 다시 (3단계까지)"""
    for depth in range(4):
        try:
            with os.scandir(full) as it:
                entries = sorted((e for e in it if not HIDDEN_RE.match(e.name)), key=lambda e: natural_key(e.name))
        except OSError:
            return None
        found = next((e.path for e in entries if e.is_file() and _ext(e.name) in PLAYABLE_TYPES), None)
        found = found or next((e.path for e in entries if e.is_file() and is_video(e.name)), None)
        if found:
            return found
        sub = next((e.path for e in entries if e.is_dir()), None)
        if not sub:
            return None
        full = sub
    return None


def thumbnail(rel):
    """영상(또는 폴더의 첫 영상) 앞부분 한 장면 JPEG. (바이트, 지문용 키) 또는 None. 한 번 뽑으면 파일로 저장해 둠"""
    full = resolve(rel)
    if not full or not rel:
        return None
    if os.path.isdir(full):
        full = _thumb_source(full)
    if not full or not os.path.isfile(full) or not is_video(full):
        return None
    try:
        stat = os.stat(full)
    except OSError:
        return None
    tag = f"t{stat.st_mtime_ns}-{stat.st_size}"
    key = hashlib.sha1(f"{full}|{tag}".encode('utf-8')).hexdigest()
    path = os.path.join(THUMB_DIR, key[:2], key + '.jpg')
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read(), tag
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return None
    with _thumb_lock:
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return f.read(), tag
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp.jpg'
        # 앞부분이 검은 화면인 영상이 많아 10초 뒤 장면을, 짧은 영상이면 처음 장면을
        for seek in ('10', '0'):
            try:
                subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', seek, '-i', full,
                                '-frames:v', '1', '-vf', f'scale={THUMB_WIDTH}:-2', '-q:v', '5', tmp],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=THUMB_TIMEOUT, check=False)
            except (subprocess.TimeoutExpired, OSError):
                pass
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                os.replace(tmp, path)
                with open(path, 'rb') as f:
                    return f.read(), tag
    return None


# ==========================================
# 자막 (.srt·.smi → WebVTT)
# ==========================================
def _read_text(path):
    raw = open(path, 'rb').read(MAX_SUBTITLE_BYTES)
    for enc in ('utf-8-sig', 'cp949', 'utf-16'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'replace')


def _vtt_time(ms):
    ms = max(0, int(ms))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def srt_to_vtt(text):
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    out = ['WEBVTT', '']
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = [l for l in block.split('\n') if l.strip() != '']
        idx = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if idx is None:
            continue
        out.append(lines[idx].replace(',', '.'))
        out.extend(lines[idx + 1:])
        out.append('')
    return '\n'.join(out)


def smi_to_vtt(text):
    """SAMI(.smi): <SYNC Start=ms> 마다 자막, 다음 SYNC까지 보임. 한국어(KRCC 등)가 여럿이면 첫 언어만"""
    syncs = list(re.finditer(r'<sync\s+start\s*=\s*"?(\d+)"?[^>]*>(.*?)(?=<sync\s|</body>|$)', text, re.I | re.S))
    cues = []
    lang = None
    for m in syncs:
        body = m.group(2)
        cls = re.search(r'<p[^>]*class\s*=\s*"?([\w-]+)', body, re.I)
        if cls:
            lang = lang or cls.group(1).lower()
            if cls.group(1).lower() != lang:
                continue
        body = re.sub(r'<br\s*/?>', '\n', body, flags=re.I)
        body = html.unescape(re.sub(r'<[^>]+>', '', body)).replace('\xa0', ' ')
        lines = [l.strip() for l in body.split('\n') if l.strip()]
        cues.append((int(m.group(1)), '\n'.join(lines)))
    out = ['WEBVTT', '']
    for i, (start, words) in enumerate(cues):
        if not words:
            continue
        end = cues[i + 1][0] if i + 1 < len(cues) else start + 5000
        if end <= start:
            continue
        out += [f"{_vtt_time(start)} --> {_vtt_time(end)}", words, '']
    return '\n'.join(out)


def subtitle_vtt(rel):
    """영상과 이름이 같은 자막을 WebVTT 글자로. 없으면 None"""
    full = video_file(rel)
    if not full:
        return None
    folder, stem = os.path.dirname(full), os.path.splitext(os.path.basename(full))[0].lower()
    try:
        names = {n.lower(): n for n in os.listdir(folder)}
    except OSError:
        return None
    for ext, convert in (('.vtt', lambda t: t), ('.srt', srt_to_vtt), ('.smi', smi_to_vtt)):
        name = names.get(stem + ext)
        if name:
            return convert(_read_text(os.path.join(folder, name)))
    return None


# ==========================================
# 이어 보기 위치
# ==========================================
def progress_for(paths):
    """{경로: {'position', 'duration', 'updated_at'}} (초)"""
    paths = list(paths)
    if not paths:
        return {}
    result = {}
    with _db() as conn:
        for start in range(0, len(paths), 500):
            chunk = paths[start:start + 500]
            rows = conn.execute(f"SELECT path, position, duration, updated_at FROM video_progress WHERE path IN ({','.join('?' * len(chunk))})",
                                chunk).fetchall()
            for r in rows:
                result[r['path']] = {'position': r['position'], 'duration': r['duration'], 'updated_at': r['updated_at']}
    return result


def save_progress(rel, position, duration):
    with _db() as conn, conn:
        conn.execute("INSERT INTO video_progress(path, position, duration, updated_at) VALUES(?, ?, ?, ?) "
                     "ON CONFLICT(path) DO UPDATE SET position = excluded.position, duration = excluded.duration, updated_at = excluded.updated_at",
                     (rel, position, duration, _now()))


def recent(limit=6):
    """최근 본 영상 (지금은 없는 영상은 빼고)"""
    with _db() as conn:
        rows = conn.execute("SELECT path, position, duration, updated_at FROM video_progress ORDER BY updated_at DESC LIMIT ?",
                            (limit * 3,)).fetchall()
    items = []
    for r in rows:
        if not video_file(r['path']):
            continue
        name = os.path.basename(r['path'])
        items.append({'path': r['path'], 'name': os.path.splitext(name)[0],
                      'folder': r['path'].rsplit('/', 1)[0] if '/' in r['path'] else '',
                      'playable': _ext(name) in PLAYABLE_TYPES,
                      'progress': {'position': r['position'], 'duration': r['duration'], 'updated_at': r['updated_at']}})
        if len(items) >= limit:
            break
    return items
