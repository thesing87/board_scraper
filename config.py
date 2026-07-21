import os
import platform
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 커스텀 로그 함수
# ==========================================
def log_msg(message, level="INFO"):
    """모든 로그에 24시간 표기 방식의 현재 시간을 추가하여 출력하는 전역 로그 함수"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}")

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
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin1234')
DDNS_URL = os.environ.get('DDNS_URL')

MAX_DATA_PER_KEYWORD = 100

IS_LINUX = platform.system() == 'Linux'

OUTPUT_DIR = os.environ.get('OUTPUT_DIR', 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

HTML_OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'index.html')
JSON_BACKUP_FILE = os.path.join(OUTPUT_DIR, 'board_data_backup.json')
KEYWORDS_FILE = os.path.join(OUTPUT_DIR, 'keywords_config.json')
BOARD_CONFIG_FILE = os.path.join(OUTPUT_DIR, 'board_config.json')

all_keywords_data = {}
data_lock = threading.Lock()
