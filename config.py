import os
import platform
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 커스텀 로그 함수
# ==========================================
LOG_LEVELS = {'DEBUG': 10, 'INFO': 20, 'WARN': 30, 'ERROR': 40, 'CRITICAL': 50}
# 기본은 INFO. 상세 추적이 필요할 때만 환경변수 LOG_LEVEL=DEBUG로 실행
LOG_LEVEL = LOG_LEVELS.get(os.environ.get('LOG_LEVEL', 'INFO').strip().upper(), LOG_LEVELS['INFO'])

def log_msg(message, level="INFO"):
    """설정된 LOG_LEVEL 이상의 로그만 시간과 함께 출력"""
    if LOG_LEVELS.get(level, LOG_LEVELS['INFO']) < LOG_LEVEL:
        return
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level:<5}] {message}", flush=True)

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
MAX_POSTS_TO_SYNC_COMMENTS = int(os.environ.get('MAX_POSTS_TO_SYNC_COMMENTS', 3))
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
# 미설정 또는 기본 예시값이면 관리 API가 비활성화됨 (web_server.py 참고)
ADMIN_PASSWORD = (os.environ.get('ADMIN_PASSWORD') or '').strip()
INSECURE_ADMIN_PASSWORDS = {'', 'admin1234'}
DDNS_URL = os.environ.get('DDNS_URL')

MAX_DATA_PER_KEYWORD = 100

IS_LINUX = platform.system() == 'Linux'

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', 'output')
if IS_LINUX and (OUTPUT_DIR == 'output' or os.path.exists('/output')):
    OUTPUT_DIR = '/output'

os.makedirs(OUTPUT_DIR, exist_ok=True)

DB_FILE = os.path.join(OUTPUT_DIR, 'board.db')
# 아래 JSON 파일들은 DB 도입 이전 저장 방식으로, 최초 기동 시 DB로 이전한 뒤 *.migrated로 이름이 바뀜
JSON_BACKUP_FILE = os.path.join(OUTPUT_DIR, 'board_data_backup.json')
KEYWORDS_FILE = os.path.join(OUTPUT_DIR, 'keywords_config.json')
BOARD_CONFIG_FILE = os.path.join(OUTPUT_DIR, 'board_config.json')

