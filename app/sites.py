"""수집 사이트(에펨코리아·디시인사이드) 구분. 수집은 디시인사이드만 함 (에펨코리아는 예전에 모은 글을 보여 주기만)

- 카테고리 키: 에펨코리아는 게시판 mid 그대로('car'), 디시인사이드는 'dc:' + 갤러리 id('dc:car_new1')
- 글 ID: 에펨코리아는 글 번호 그대로('10482627360'), 디시인사이드는 'dc-갤러리id-글번호'('dc-car_new1-11561402')
  (갤러리마다 글 번호가 따로 매겨지므로 갤러리 id까지 넣어 겹치지 않게 함)
"""
import re
import time

FMKOREA = 'fmkorea'
DCINSIDE = 'dcinside'
SITE_NAMES = {FMKOREA: '에펨코리아', DCINSIDE: '디시인사이드'}
# 기본 이름·짧은 표시. 관리 화면에서 바꾼 값은 DB에 저장되며 storage.site_labels()로 읽음
SITE_SHORT = {FMKOREA: 'FM', DCINSIDE: 'DC'}

# 여러 사이트의 키워드를 함께 담은 게시판의 사이트 값 (keyword_groups.site)
MULTI_SITE = 'multi'

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

class SiteDisabledError(RuntimeError):
    """수집기가 없는 사이트(에펨코리아)에 요청하려 함"""


def site_enabled(site):
    """수집할 수 있는 사이트인지. 에펨코리아는 이용약관상 자동 수집을 하지 말아 달라는 운영자 답변을 받아 수집 기능을 없앰
    (예전에 모은 에펨코리아 글은 그대로 볼 수 있음)"""
    return site == DCINSIDE


# 사이트별 수집기. 수집하지 않는 쪽(웹서버 등)에서는 불러오지 않도록 함수 안에서 가져옴.
# 수집기가 없는 사이트면 요청을 보내기 전에 막음
def _collector(site):
    if not site_enabled(site):
        raise SiteDisabledError(f"{SITE_NAMES.get(site, site)}는 수집하지 않음")
    import dcinside
    return dcinside

# 목록이 아닌 페이지가 한 번 왔다고 바로 차단으로 보지 않고, 이 시간(초) 뒤에 한 번 더 열어 봄.
# 사이트가 가끔 한 번씩 돌려주는 일시적인 오류 화면에 차단 의심 알림이 가지 않게 함 (디시 목록 200번에 한 번꼴)
LIST_RETRY_SECONDS = 5

def _read_with_retry(collector, read, target):
    try:
        return read()
    except collector.BlockedError as first:
        from config import log_msg
        log_msg(f"[수집] {target} {first} → {LIST_RETRY_SECONDS}초 뒤 한 번 더 시도", "DEBUG")
        time.sleep(LIST_RETRY_SECONDS)
        return read()

def get_list_page_posts(driver, board, keyword, page=1):
    """키워드 검색 목록"""
    collector = _collector(board_site(board))
    return _read_with_retry(collector, lambda: collector.get_list_page_posts(driver, board, keyword, page),
                            f"{board}/{keyword}")

def scrape_post_detail(driver, post_info, all_comment_pages=True):
    """all_comment_pages=False면 첫 화면의 댓글 페이지만 읽음 (삭제 여부 확인처럼 댓글이 필요 없을 때)"""
    return _collector(post_site(post_info['id'])).scrape_post_detail(driver, post_info, all_comment_pages)

def check_board(driver, board):
    return _collector(board_site(board)).check_board(driver, board)
