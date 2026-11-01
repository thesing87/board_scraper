"""수집기 동작 상태 (관리 패널 '수집 상태' 표시용). 재시작하면 처음부터 다시 쌓임.
수집기는 상태가 바뀔 때마다 파일(OUTPUT_DIR/runtime_status.json)에도 써 두고, 따로 도는 웹서버 프로세스는 그 파일을 읽음.
(수집기 안에서 웹서버를 함께 띄우면 메모리 그대로 씀)"""
import os
import json
import threading
from datetime import datetime

from config import RECENT_PROBLEMS, OUTPUT_DIR

STATUS_FILE = os.path.join(OUTPUT_DIR, 'runtime_status.json')

_lock = threading.Lock()
_writer = False                  # 이 프로세스가 수집기인지 (start_writer)
_save_failed = False
_status = {
    'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'cycles': 0,
    'last_cycle': None,          # {'finished_at', 'seconds', 'new', 'updated', 'deleted', 'errors'}
    'block_streak': 0,           # 차단 의심 연속 횟수 (0이면 정상)
    'next_check_at': None,       # 다음 수집 주기 시작 예정 시각
    'progress_at': None,         # 주기 안에서 마지막으로 키워드 확인을 시작한 시각 (멈춤 감시용)
    'chrome_started_at': None,
    'chrome_restarts': 0,        # 주기적 재시작·응답 없음으로 새로 띄운 횟수
    'last_backup': None,         # {'at', 'file'}
    'last_prune': None,          # {'at', 'deleted'}
}

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _save():
    """수집기의 상태와 최근 경고·오류를 파일로 (반쯤 쓴 파일을 읽지 않게 임시 파일에 쓴 뒤 교체). _lock 안에서 호출"""
    global _save_failed
    if not _writer:
        return
    data = dict(_status, recent_problems=list(RECENT_PROBLEMS))
    try:
        partial = STATUS_FILE + '.part'
        with open(partial, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(partial, STATUS_FILE)
        _save_failed = False
    except OSError as e:
        if not _save_failed:
            # log_msg를 쓰면 RECENT_PROBLEMS를 거쳐 다시 여기로 올 수 있어 화면에만 한 번 알림
            print(f"[{now()}] [WARN ] [시스템] 수집 상태 파일 저장 실패: {e}", flush=True)
            _save_failed = True

def start_writer():
    """이 프로세스가 수집기임을 표시. 이후 상태가 바뀔 때마다 파일에도 씀"""
    global _writer
    with _lock:
        _writer = True
        _save()

def update(**fields):
    with _lock:
        _status.update(fields)
        _save()

def increment(field):
    with _lock:
        _status[field] += 1
        _save()

def _parse(ts):
    try:
        return datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return None

def stalled_seconds(data, watch_started):
    """수집기가 예정보다 몇 초째 움직이지 않는지 (snapshot 기준). 기준은 다음 주기 예정 시각(쉬는 동안은 정상)·
    마지막 키워드 확인·수집기 시작 중 가장 늦은 시각이고, 수집기 상태가 아예 없으면 감시를 시작한 시각"""
    marks = [_parse(data.get(k)) for k in ('next_check_at', 'progress_at', 'started_at')] + [watch_started]
    return max(0, (_parse(data['now']) - max(t for t in marks if t)).total_seconds())

def _read_saved():
    """수집기가 써 둔 상태 (없거나 읽지 못하면 None)"""
    try:
        with open(STATUS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def snapshot():
    """관리 패널에 보여 줄 상태. 따로 도는 웹서버면 수집기가 써 둔 파일 기준이고,
    최근 경고·오류에는 웹서버 자신의 것도 합쳐 시각순으로 보여줌"""
    with _lock:
        data = dict(_status)
    problems = list(RECENT_PROBLEMS)
    if not _writer:
        saved = _read_saved()
        if saved:
            problems = sorted(saved.pop('recent_problems', []) + problems, key=lambda p: p.get('time', ''))[-RECENT_PROBLEMS.maxlen:]
            data = saved
        else:
            # 수집기가 아직 상태를 쓰지 않음 (막 시작했거나 멈춤) → 수집 기록이 없는 것으로 보여줌
            data = dict(data, started_at=None)
    data['now'] = now()
    data['recent_problems'] = problems[::-1]  # 최신이 먼저
    return data
