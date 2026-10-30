"""수집 사이트(에펨코리아·디시인사이드) 구분.

- 카테고리 키: 에펨코리아는 게시판 mid 그대로('car'), 디시인사이드는 'dc:' + 갤러리 id('dc:car_new1')
- 글 ID: 에펨코리아는 글 번호 그대로('10482627360'), 디시인사이드는 'dc-갤러리id-글번호'('dc-car_new1-11561402')
  (갤러리마다 글 번호가 따로 매겨지므로 갤러리 id까지 넣어 겹치지 않게 함)
"""
import re

FMKOREA = 'fmkorea'
DCINSIDE = 'dcinside'
SITE_NAMES = {FMKOREA: '에펨코리아', DCINSIDE: '디시인사이드'}
# 기본 이름·짧은 표시. 관리 화면에서 바꾼 값은 DB에 저장되며 storage.site_labels()로 읽음
SITE_SHORT = {FMKOREA: 'FM', DCINSIDE: 'DC'}

DC_BOARD_PREFIX = 'dc:'
DC_POST_PREFIX = 'dc-'
# 디시 갤러리 id (예: car_new1)
DC_GALLERY_RE = re.compile(r'[a-z0-9_]{1,40}')
POST_ID_RE = re.compile(r'\d{1,20}|dc-[a-z0-9_]{1,40}-\d{1,20}')

def board_site(board):
    """카테고리 키의 사이트"""
    return DCINSIDE if str(board).startswith(DC_BOARD_PREFIX) else FMKOREA

def post_site(post_id):
    """글 ID의 사이트"""
    return DCINSIDE if str(post_id).startswith(DC_POST_PREFIX) else FMKOREA

def dc_gallery(board):
    """'dc:car_new1' → 'car_new1'"""
    return board[len(DC_BOARD_PREFIX):]

def dc_post_id(gallery, no):
    return f"{DC_POST_PREFIX}{gallery}-{no}"

def is_post_id(value):
    """요청으로 받은 글 ID가 수집한 글 ID 형식인지 (SQL·주소에 넣기 전 검사)"""
    return isinstance(value, str) and POST_ID_RE.fullmatch(value) is not None

def post_number(post_id):
    """글 ID 끝의 글 번호 (같은 게시판 안에서 최신 글일수록 큼)"""
    return int(str(post_id).rsplit('-', 1)[-1])

# 사이트별 수집기. 셀레늄을 쓰는 모듈이라 웹서버 등 수집하지 않는 쪽에서는 불러오지 않도록 함수 안에서 가져옴
def _collector(site):
    if site == DCINSIDE:
        import dcinside
        return dcinside
    import scraper
    return scraper

def get_list_page_posts(driver, board, keyword, page=1):
    return _collector(board_site(board)).get_list_page_posts(driver, board, keyword, page)

def scrape_post_detail(driver, post_info):
    return _collector(post_site(post_info['id'])).scrape_post_detail(driver, post_info)

def check_board(driver, board):
    return _collector(board_site(board)).check_board(driver, board)
