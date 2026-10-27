"""수집기 동작 상태 (관리 패널 '수집 상태' 표시용).
수집기와 웹서버가 같은 프로세스에서 돌아가므로 메모리로 공유하고, 재시작하면 처음부터 다시 쌓임"""
import threading
from datetime import datetime

from config import RECENT_PROBLEMS

_lock = threading.Lock()
_status = {
    'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'cycles': 0,
    'last_cycle': None,          # {'finished_at', 'seconds', 'new', 'updated', 'deleted', 'errors'}
    'block_streak': 0,           # 차단 의심 연속 횟수 (0이면 정상)
    'next_check_at': None,       # 다음 수집 주기 시작 예정 시각
    'chrome_started_at': None,
    'chrome_restarts': 0,        # 주기적 재시작·응답 없음으로 새로 띄운 횟수
    'last_backup': None,         # {'at', 'file'}
    'last_prune': None,          # {'at', 'deleted'}
}

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def update(**fields):
    with _lock:
        _status.update(fields)

def increment(field):
    with _lock:
        _status[field] += 1

def snapshot():
    with _lock:
        data = dict(_status)
    data['now'] = now()
    data['recent_problems'] = list(RECENT_PROBLEMS)[::-1]  # 최신이 먼저
    return data
