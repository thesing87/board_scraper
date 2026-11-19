"""
NAS 상태 (대시보드 'NAS 상태' 카드, 관리자 전용): CPU·메모리·스왑·디스크, 컨테이너(수집기·웹·메일·변환)가 살아 있는지,
동영상 변환 진행

- CPU·메모리·부하·켜진 시간은 /proc에서 읽음. 컨테이너 안에서도 /proc/stat·meminfo·loadavg·uptime은 NAS 전체 값
- 디스크는 웹서버 컨테이너에 연결된 폴더(output·동영상·만화)마다. 같은 디스크(볼륨)면 하나로 묶음
- 컨테이너끼리는 서로를 볼 수 없으므로(도커 소켓을 열지 않음) 각자 남긴 기록의 시각으로 판단
  수집기: runtime_status.json, 메일: card_mail_status(meta), 변환: convert_heartbeat(meta, video_worker.py가 1분마다)
"""
import json
import os
import shutil
import threading
import time
from datetime import datetime

from config import OUTPUT_DIR, VIDEOS_DIR, COMICS_DIR
from storage import _db, get_meta
import runtime_status

CPU_SAMPLE_SECONDS = 0.4
# 이만큼 소식이 없으면 멈춘 것으로 봄 (초)
COLLECTOR_STALE = 15 * 60
CONVERT_STALE = 5 * 60
MAIL_STALE = 3 * 3600
CONV_SIZE_TTL = 600
# 남은 공간이 이만큼 안에서 같으면 같은 디스크 (재는 사이에 조금 바뀔 수 있음)
SAME_DISK_SLACK = 1024 ** 3
CONVERT_HEARTBEAT_META = 'convert_heartbeat'

STARTED_AT = time.time()
_conv_size = {'at': 0.0, 'bytes': 0, 'files': 0}
_conv_lock = threading.Lock()


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _cpu_times():
    parts = _read('/proc/stat').splitlines()[0].split()[1:]
    values = [int(v) for v in parts]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_percent():
    """지금 CPU 사용률 (%). 잠깐 두 번 재서 비교"""
    total1, idle1 = _cpu_times()
    time.sleep(CPU_SAMPLE_SECONDS)
    total2, idle2 = _cpu_times()
    span = total2 - total1
    return round(100 * (1 - (idle2 - idle1) / span), 1) if span > 0 else 0.0


def memory():
    info = {}
    for line in _read('/proc/meminfo').splitlines():
        key, _, rest = line.partition(':')
        info[key] = int(rest.split()[0]) * 1024
    total = info.get('MemTotal', 0)
    available = info.get('MemAvailable', info.get('MemFree', 0))
    swap_total = info.get('SwapTotal', 0)
    return {'total': total, 'used': max(0, total - available),
            'swap_total': swap_total, 'swap_used': max(0, swap_total - info.get('SwapFree', 0))}


def disks():
    """연결된 폴더마다 디스크 사용량. 같은 디스크면 이름을 이어 붙여 하나로"""
    out = {}
    for label, path in (('DB·이미지·변환본', OUTPUT_DIR), ('동영상', VIDEOS_DIR), ('만화', COMICS_DIR)):
        if not path or not os.path.isdir(path):
            continue
        try:
            usage = shutil.disk_usage(path)
            dev = os.stat(path).st_dev
        except OSError:
            continue
        total, free = usage.total, usage.free
        # 시놀로지는 같은 볼륨이라도 공유 폴더(서브볼륨)마다 장치 번호가 달라, 전체 크기·남은 공간이 같으면 같은 디스크로 봄
        same = next((d for d in out.values() if d['dev'] == dev or (d['total'] == total and abs(d['free'] - free) < SAME_DISK_SLACK)), None)
        if same:
            same['label'] += f" · {label}"
        else:
            out[len(out)] = {'dev': dev, 'label': label, 'total': total, 'used': max(0, total - free), 'free': free}
    return [{k: v for k, v in d.items() if k != 'dev'} for d in out.values()]


def _age(stamp, now):
    """'YYYY-MM-DD HH:MM:SS' 기록이 지금으로부터 몇 초 전인지 (없으면 None)"""
    if not stamp:
        return None
    try:
        return max(0, (now - datetime.strptime(stamp[:19], '%Y-%m-%d %H:%M:%S')).total_seconds())
    except ValueError:
        return None


def services():
    now = datetime.now()
    items = []
    # 수집기: 마지막 키워드 확인·주기 끝·시작 중 가장 늦은 시각
    status = runtime_status.snapshot()
    last = status.get('last_cycle') or {}
    marks = [a for a in (_age(status.get('progress_at'), now), _age(last.get('finished_at'), now),
                         _age(status.get('started_at'), now)) if a is not None]
    age = min(marks) if marks else None
    detail = f"주기 {last.get('seconds', 0):.0f}초 · 새 글 {last.get('new', 0)}" if last else '시작 중'
    if status.get('block_streak'):
        detail = f"차단 의심 {status.get('block_streak')}번 · " + detail
    items.append({'key': 'collector', 'name': '수집기', 'age': age,
                  'ok': age is not None and age < COLLECTOR_STALE and not status.get('block_streak'), 'detail': detail})
    # 웹서버: 이 답을 하고 있으므로 살아 있음
    items.append({'key': 'web', 'name': '웹서버', 'age': 0, 'ok': True,
                  'detail': f"켜진 지 {_duration(time.time() - STARTED_AT)}"})
    # 메일 감시
    mail = {}
    try:
        mail = json.loads(get_meta('card_mail_status') or '{}')
    except ValueError:
        mail = {}
    age = _age(mail.get('checked_at'), now)
    state = mail.get('state')
    items.append({'key': 'mail', 'name': '메일 감시', 'age': age,
                  'ok': state == 'ok' and age is not None and age < MAIL_STALE if state != 'off' else None,
                  'detail': {'ok': '카드 메일 확인 중', 'off': '꺼짐', 'error': mail.get('message') or '오류'}.get(state, '기록 없음')})
    # 동영상 변환 작업기
    age = _age(get_meta(CONVERT_HEARTBEAT_META), now)
    items.append({'key': 'convert', 'name': '동영상 변환', 'age': age, 'ok': age is not None and age < CONVERT_STALE,
                  'detail': '작업기 동작 중' if age is not None and age < CONVERT_STALE else '소식 없음'})
    return items


def _duration(seconds):
    seconds = int(seconds)
    if seconds >= 86400:
        return f"{seconds // 86400}일 {seconds % 86400 // 3600}시간"
    if seconds >= 3600:
        return f"{seconds // 3600}시간 {seconds % 3600 // 60}분"
    return f"{max(1, seconds // 60)}분"


def _conv_dir_size():
    """변환본 폴더 크기 (파일이 많아 CONV_SIZE_TTL마다 다시 셈)"""
    import video_convert
    with _conv_lock:
        if time.time() - _conv_size['at'] < CONV_SIZE_TTL:
            return _conv_size['bytes'], _conv_size['files']
        total = files = 0
        for root, _, names in os.walk(video_convert.CONV_DIR):
            for name in names:
                if name.endswith('.mp4') and not name.endswith('.part.mp4'):
                    try:
                        total += os.path.getsize(os.path.join(root, name))
                        files += 1
                    except OSError:
                        pass
        _conv_size.update(at=time.time(), bytes=total, files=files)
        return total, files


def conversion():
    with _db() as conn:
        counts = {r['state']: r['n'] for r in conn.execute("SELECT state, COUNT(*) AS n FROM video_jobs GROUP BY state")}
        running = [dict(r) for r in conn.execute(
            "SELECT path, kind, progress, speed FROM video_jobs WHERE state = 'running' ORDER BY updated_at DESC LIMIT 2")]
    size, files = _conv_dir_size()
    for r in running:
        r['name'] = os.path.splitext(os.path.basename(r['path']))[0]
    return {'queued': counts.get('queued', 0), 'running': running, 'done': counts.get('done', 0),
            'failed': counts.get('failed', 0), 'size': size, 'files': files}


def _try(read):
    """/proc을 못 읽는 곳(윈도우 시험 PC 등)에서는 그 값만 비움 (카드 전체가 오류가 되지 않게)"""
    try:
        return read()
    except (OSError, ValueError, IndexError, KeyError):
        return None


def snapshot():
    load = _try(lambda: [float(v) for v in _read('/proc/loadavg').split()[:3]])
    return {
        'cpu': _try(cpu_percent),
        'cpus': os.cpu_count() or 1,
        'load': load,
        'uptime': _try(lambda: _duration(float(_read('/proc/uptime').split()[0]))),
        'memory': _try(memory),
        'disks': disks(),
        'services': services(),
        'conversion': conversion(),
        'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
