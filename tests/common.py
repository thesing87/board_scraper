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
DATA_DIR = os.path.join(ROOT, 'output')
LIVE_URL = 'http://thesing87.iptime.org'

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

def shot_dir(name):
    path = os.path.join(TESTS_DIR, '_shots', name)
    os.makedirs(path, exist_ok=True)
    return path
