"""테스트 공용 경로.

- 대부분의 테스트는 로컬 output/ 폴더의 예전 JSON 데이터(board_data_backup.json, keywords_config.json,
  board_config.json; git에는 올리지 않음)를 임시 폴더로 복사해 새 DB를 만든 뒤 시험함
- 일부 테스트는 실제 사이트(LIVE_URL)의 글을 받아 사용 (인터넷·NAS 필요)
- 화면 테스트는 셀레늄 + 로컬 크롬, 스크린샷은 tests/_shots/ 아래에 저장 (git 제외)
"""
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
APP_DIR = os.path.join(ROOT, 'app')
DATA_DIR = os.path.join(ROOT, 'output')
LIVE_URL = 'http://thesing87.iptime.org'

# 테스트는 기본으로 두 사이트 모두 수집하는 것으로 시험 (실제 기본값은 에펨코리아를 끔, config.DISABLED_SITES).
# 끈 사이트를 시험하는 테스트는 따로 정함 (test_disabled_sites.py)
os.environ.setdefault('DISABLED_SITES', '')

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

def shot_dir(name):
    path = os.path.join(TESTS_DIR, '_shots', name)
    os.makedirs(path, exist_ok=True)
    return path

def search_every_cycle(m):
    """수집기 모듈(fmkorea-scraper.py)을 '주기마다 모든 에펨코리아 키워드를 검색'하게 맞춤 (에펨코리아 확인·검색 간격을 0으로).
    검색 목록을 따라가는 수집 흐름(새 글·갱신·삭제 확인)을 시험하는 테스트용
    (실제로는 키워드마다 한 시간에 한 번씩 나눠서 검색함, tests/test_search_schedule.py)"""
    m.FM_CHECK_INTERVAL = 0
    m.FM_SEARCH_INTERVAL = 0
