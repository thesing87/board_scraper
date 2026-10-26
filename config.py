import os
import platform
import logging
import threading
from collections import deque
from logging.handlers import RotatingFileHandler
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 커스텀 로그 함수
# ==========================================
LOG_LEVELS = {'DEBUG': 10, 'INFO': 20, 'WARN': 30, 'ERROR': 40, 'CRITICAL': 50}
# 화면(docker logs) 출력 레벨. 기본은 INFO
LOG_LEVEL = LOG_LEVELS.get(os.environ.get('LOG_LEVEL', 'INFO').strip().upper(), LOG_LEVELS['INFO'])

# DEBUG를 포함한 전체 로그는 재시작 없이 언제든 볼 수 있도록 별도 파일에 항상 기록 (용량 제한 순환)
DEBUG_LOG_MAX_BYTES = 5 * 1024 * 1024
DEBUG_LOG_BACKUP_COUNT = 3
_debug_handler = None
_debug_lock = threading.Lock()
_debug_disabled = False

def _write_debug_file(line):
    global _debug_handler, _debug_disabled
    if _debug_disabled:
        return
    try:
        with _debug_lock:
            if _debug_handler is None:
                os.makedirs(os.path.dirname(DEBUG_LOG_FILE), exist_ok=True)
                _debug_handler = RotatingFileHandler(
                    DEBUG_LOG_FILE, maxBytes=DEBUG_LOG_MAX_BYTES, backupCount=DEBUG_LOG_BACKUP_COUNT, encoding='utf-8'
                )
            _debug_handler.emit(logging.makeLogRecord({'msg': line}))
    except Exception as e:
        _debug_disabled = True
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WARN ] [시스템] 디버그 로그 파일 기록 중단: {e}", flush=True)

# 관리 패널의 '수집 상태'에 보여 줄 최근 경고·오류 (WARN 이상, 최신이 뒤)
RECENT_PROBLEMS = deque(maxlen=10)

def log_msg(message, level="INFO"):
    """전체 로그는 디버그 파일에, LOG_LEVEL 이상은 화면에도 시간과 함께 출력"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] [{level:<5}] {message}"
    _write_debug_file(line)
    if LOG_LEVELS.get(level, LOG_LEVELS['INFO']) >= LOG_LEVELS['WARN']:
        RECENT_PROBLEMS.append({'time': timestamp, 'level': level, 'message': message.splitlines()[0]})
    if LOG_LEVELS.get(level, LOG_LEVELS['INFO']) >= LOG_LEVEL:
        print(line, flush=True)

def short_err(err, limit=150):
    """Selenium 예외처럼 스택트레이스가 붙는 긴 오류 메시지를 첫 줄만 잘라서 반환"""
    text = str(err).strip().splitlines()
    first = text[0].strip() if text else type(err).__name__
    first = first.removeprefix('Message:').strip() or type(err).__name__
    return first if len(first) <= limit else first[:limit] + '…'

# ==========================================
# 게시판 정의 및 환경변수 로드
# ==========================================
BOARD_MAP = {
    'car': '자동차',
    'other_game': '종합게임',
    'digital': '컴퓨터/디지털',
    'humor': '유머',
    'hotdeal': '핫딜',
    'baseball': '야구'
}

CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', 90))
# 검색 목록 1페이지의 글 수. 이 범위의 글은 매 주기 목록의 댓글 수로 변화를 감시함 (대시보드 '동기화중' 배지 기준)
LIST_PAGE_SIZE = 20
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
# 미설정 또는 기본 예시값이면 관리 API가 비활성화됨 (web_server.py 참고)
ADMIN_PASSWORD = (os.environ.get('ADMIN_PASSWORD') or '').strip()
INSECURE_ADMIN_PASSWORDS = {'', 'admin1234'}
DDNS_URL = os.environ.get('DDNS_URL')

MAX_DATA_PER_KEYWORD = 100
# 수집한 지 이 일수가 지난 글은 하루 한 번 정리 (각 키워드의 최근 MAX_DATA_PER_KEYWORD개는 새 글 판별 기준이라 유지). 0이면 정리 안 함
RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', 180))
# DB 자동 백업: 하루 한 번 OUTPUT_DIR/backups에 복사하고 최근 이 개수만 보관
BACKUP_KEEP = int(os.environ.get('BACKUP_KEEP', 7))
# 크롬 메모리가 계속 불어나 NAS가 스왑을 쓰지 않도록 이 주기 수마다 크롬을 새로 띄움 (0이면 안 함)
CHROME_RESTART_CYCLES = int(os.environ.get('CHROME_RESTART_CYCLES', 40))

IS_LINUX = platform.system() == 'Linux'

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', 'output')
if IS_LINUX and (OUTPUT_DIR == 'output' or os.path.exists('/output')):
    OUTPUT_DIR = '/output'

os.makedirs(OUTPUT_DIR, exist_ok=True)

DB_FILE = os.path.join(OUTPUT_DIR, 'board.db')
DEBUG_LOG_FILE = os.path.join(OUTPUT_DIR, 'logs', 'debug.log')
BACKUP_DIR = os.path.join(OUTPUT_DIR, 'backups')
# 아래 JSON 파일들은 DB 도입 이전 저장 방식으로, 최초 기동 시 DB로 이전한 뒤 *.migrated로 이름이 바뀜
JSON_BACKUP_FILE = os.path.join(OUTPUT_DIR, 'board_data_backup.json')
KEYWORDS_FILE = os.path.join(OUTPUT_DIR, 'keywords_config.json')
BOARD_CONFIG_FILE = os.path.join(OUTPUT_DIR, 'board_config.json')

