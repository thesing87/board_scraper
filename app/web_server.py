import os
import re
import json
import gzip
import hmac
import hashlib
import time
import threading
import ipaddress
import requests
from datetime import datetime, timedelta
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, quote

from config import (
    log_msg,
    short_err,
    ADMIN_PASSWORD,
    INSECURE_ADMIN_PASSWORDS,
    TRUST_PROXY_HEADERS,
    CHECK_INTERVAL,
    WEB_PORT,
    DDNS_URL,
    LIST_PAGE_SIZE,
    COLLECTOR_STALL_MINUTES,
    DIGEST_HOUR
)
import runtime_status
from notifier import send_telegram_message
from sites import is_post_id, board_site, site_enabled, SITE_NAMES, DC_BOARD_PREFIX, DC_GALLERY_RE
from images import image_file, IMAGE_URL_PREFIX
from storage import (
    init_db,
    add_fm_link,
    fm_links_by_group,
    fm_seen_init,
    fm_seen_found,
    fm_seen_read,
    fm_seen_read_all,
    remove_fm_link,
    reorder_fm_groups,
    move_fm_link,
    reorder_fm_links,
    touch_fm_link,
    keyword_pairs,
    set_group_alert,
    set_group_popular,
    saved_comment_alert,
    set_saved_comment_alert,
    query_all_posts,
    query_media,
    recent_post_ids,
    mark_posts_read,
    mark_feed_read,
    set_post_saved,
    locate_post,
    list_groups,
    feed_summary,
    query_posts_by_ids,
    dashboard_summary,
    stats_summary,
    popular_by_group,
    save_group,
    delete_group,
    set_group_paused,
    category_names,
    list_categories,
    add_category,
    rename_category,
    recheck_category,
    delete_category,
    site_labels,
    set_site_label,
    list_folders,
    save_folder,
    delete_folder,
    move_folder,
    arrange_group
)
import apt_store
import comics
import videos
import video_fix
import video_convert
import system_status
import ledger
import ledger_app
import duty
import apt_trades
from card_store import (
    card_benefits,
    add_card_benefit,
    update_card_benefit,
    delete_card_benefit,
    add_card_keyword,
    delete_card_keyword
)
from ev_store import ev_presets, add_ev_preset, delete_ev_preset

MAX_BODY_BYTES = 10 * 1024
MAX_READ_IDS = 500
MAX_QUERY_LENGTH = 50
MAX_GROUP_NAME_LENGTH = 30
MAX_GROUP_MEMBERS = 50
MAX_KEYWORD_LENGTH = 50
MAX_IGNORES_PER_KEYWORD = 20
MAX_CATEGORY_NAME_LENGTH = 20
MAX_CATEGORY_INPUT_LENGTH = 300
MAX_SITE_NAME_LENGTH = 20
MAX_SITE_SHORT_LENGTH = 4
# 인기 글 알림 기준(추천+댓글 수)의 상한
MAX_POPULAR_MIN = 100000
# 카드 혜택: 한 달 혜택 한도(원), 사용처 이름 길이, 한 건 금액 상한
CARD_BENEFIT_LIMIT = 30000
MAX_CARD_PLACE_LENGTH = 30
MAX_CARD_AMOUNT = 10000000
# 아파트 실거래가: 관심 단지 수 상한, 단지 이름 길이, 볼 수 있는 전용면적 범위(㎡)
MAX_APT_WATCHES = 30
MAX_APT_NAME_LENGTH = 40
APT_AREA_RANGE = (10, 400)
POSTS_PER_PAGE = 10
# 에펨코리아 바로가기: 게시판마다 최대 개수, 게시판 mid (숫자만인 값은 글 번호라 제외. ''은 사이트 전체 검색)
MAX_FM_LINKS = 30
FM_MID_RE = re.compile(r'(?![0-9]+$)[a-z0-9_]{1,40}')
# 인기순으로 볼 수 있는 기간(일). 없으면 전체 기간
POPULAR_DAYS = ('1', '7', '30')
# 검색에서 고를 수 있는 기간(일): 최근 그 기간에 수집한 글만. 없으면 전체 기간
SEARCH_DAYS = ('1', '7', '30', '90')
# 통계 화면에서 고를 수 있는 기간(일)
STATS_DAYS = ('7', '30', '90')
# 메인 대시보드 키워드 게시판 카드의 '최근 수집한 글'로 보내는 최대 개수 (카드를 키우면 그만큼 더 보임)
DASHBOARD_RECENT_MAX = 30
# 게시판별 인기글: 고를 수 있는 기간(일)과 게시판마다 보여 줄 글 수의 상한
POPULAR_BOARD_DAYS = ('1', '7', '30')
MAX_POPULAR_PER_BOARD = 10
# 첫 화면 조회를 미리 돌려 두는 간격 (_keep_warm)
WARMUP_INTERVAL_SECONDS = 30
# 수집기 멈춤을 확인하는 간격 (_watch_collector)
WATCH_INTERVAL_SECONDS = 60
WATCH_STARTED = datetime.now()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
STATIC_FILES = {
    # 메인 대시보드 (기능 페이지로 가는 카드와 요약)
    '/': ('dashboard.html', 'text/html; charset=utf-8'),
    '/dashboard.js': ('dashboard.js', 'application/javascript; charset=utf-8'),
    '/dashboard.css': ('dashboard.css', 'text/css; charset=utf-8'),
    # 키워드 게시판
    '/board/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
    # app.js에 이어 순서대로 불러오는 나머지 화면 스크립트
    '/app-feed.js': ('app-feed.js', 'application/javascript; charset=utf-8'),
    '/app-view.js': ('app-view.js', 'application/javascript; charset=utf-8'),
    '/app-admin.js': ('app-admin.js', 'application/javascript; charset=utf-8'),
    '/app-main.js': ('app-main.js', 'application/javascript; charset=utf-8'),
    '/app.css': ('app.css', 'text/css; charset=utf-8'),
    # 전기차 vs 내연기관 유지비 계산기
    '/ev/': ('ev.html', 'text/html; charset=utf-8'),
    '/ev.js': ('ev.js', 'application/javascript; charset=utf-8'),
    # 수집 통계
    '/stats/': ('stats.html', 'text/html; charset=utf-8'),
    '/stats.js': ('stats.js', 'application/javascript; charset=utf-8'),
    '/stats.css': ('stats.css', 'text/css; charset=utf-8'),
    # 아파트 실거래가
    '/apt/': ('apt.html', 'text/html; charset=utf-8'),
    '/apt.js': ('apt.js', 'application/javascript; charset=utf-8'),
    '/apt-regions.js': ('apt-regions.js', 'application/javascript; charset=utf-8'),
    '/apt.css': ('apt.css', 'text/css; charset=utf-8'),
    # 게임 (목록 /games/, 스도쿠 /games/sudoku/)
    '/games/': ('games.html', 'text/html; charset=utf-8'),
    '/games.js': ('games.js', 'application/javascript; charset=utf-8'),
    '/games.css': ('games.css', 'text/css; charset=utf-8'),
    '/games/sudoku/': ('sudoku.html', 'text/html; charset=utf-8'),
    '/sudoku.js': ('sudoku.js', 'application/javascript; charset=utf-8'),
    '/sudoku-engine.js': ('sudoku-engine.js', 'application/javascript; charset=utf-8'),
    '/sudoku.css': ('sudoku.css', 'text/css; charset=utf-8'),
    # 만화 뷰어 (NAS 만화 폴더, 로그인 필요)
    '/videos/': ('videos.html', 'text/html; charset=utf-8'),
    '/videos.js': ('videos.js', 'application/javascript; charset=utf-8'),
    '/videos.css': ('videos.css', 'text/css; charset=utf-8'),
    '/comics/': ('comics.html', 'text/html; charset=utf-8'),
    '/comics.js': ('comics.js', 'application/javascript; charset=utf-8'),
    '/comics.css': ('comics.css', 'text/css; charset=utf-8'),
    # 가계부 (여럿이 함께 쓰는 지출 기록, 관리자가 허락한 사람만)
    '/ledger/': ('ledger.html', 'text/html; charset=utf-8'),
    '/ledger.js': ('ledger.js', 'application/javascript; charset=utf-8'),
    '/ledger.css': ('ledger.css', 'text/css; charset=utf-8'),
    # 근무표 (가계부 계정으로 로그인, 멤버 모두가 고침)
    '/duty/': ('duty.html', 'text/html; charset=utf-8'),
    '/duty.js': ('duty.js', 'application/javascript; charset=utf-8'),
    '/duty.css': ('duty.css', 'text/css; charset=utf-8'),
    # 모든 페이지 공통 바로가기 메뉴
    '/nav.js': ('nav.js', 'application/javascript; charset=utf-8'),
    '/nav.css': ('nav.css', 'text/css; charset=utf-8'),
    # 카드 혜택 한도
    '/card/': ('card.html', 'text/html; charset=utf-8'),
    '/card.js': ('card.js', 'application/javascript; charset=utf-8'),
    '/card.css': ('card.css', 'text/css; charset=utf-8'),
    # 휴대폰 홈 화면에 앱처럼 추가할 때 쓰는 앱 정보와 아이콘
    '/manifest.webmanifest': ('manifest.webmanifest', 'application/manifest+json; charset=utf-8'),
    '/icon-192.png': ('icon-192.png', 'image/png'),
    '/icon-512.png': ('icon-512.png', 'image/png'),
    '/apple-touch-icon.png': ('apple-touch-icon.png', 'image/png'),
}

# 본문 HTML은 저장 시 정화되지만, 스크립트는 같은 출처의 app.js만 실행되도록 브라우저 차원에서 한 번 더 제한
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src * data: blob:; media-src * data: blob:; frame-src https: http:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

# 전송 줄이기: 글자로 된 응답(화면 파일·JSON)은 브라우저가 받을 수 있으면 gzip으로 줄여 보내고,
# GET 응답에는 내용 지문(ETag)을 붙여 브라우저가 가진 것과 같으면 본문 없이 304로 답함
COMPRESS_MIN_BYTES = 1024
# 브라우저가 보관하되 쓸 때마다 서버에 확인 (배포 직후에도 옛 파일을 쓰지 않음). 공용 캐시에는 두지 않음
REVALIDATE = 'private, no-cache'
COMPRESS_LEVEL = 5
COMPRESS_TYPES = ('text/', 'application/json', 'application/javascript', 'application/manifest+json')
# 화면 파일은 압축한 결과를 기억 {파일 경로: (수정 시각, 크기, 원본, 지문, 압축본)}
_static_cache = {}
_static_cache_lock = threading.Lock()

def _etag(body):
    return '"' + hashlib.sha1(body).hexdigest()[:20] + '"'

def _accepts_gzip(headers):
    return any(part.split(';')[0].strip().lower() == 'gzip' and not part.replace(' ', '').lower().endswith(';q=0')
               for part in (headers.get('Accept-Encoding') or '').split(','))

def _etag_matches(headers, etag):
    given = headers.get('If-None-Match') or ''
    # 프록시가 압축하며 약한 지문(W/)으로 바꿔 돌려보내도 같은 것으로 봄
    return etag in [tag.strip().removeprefix('W/') for tag in given.split(',')]

def load_static(path):
    """화면 파일의 (원본, 지문, 압축본). 파일이 바뀌지 않았으면 기억해 둔 것을 씀"""
    stat = os.stat(path)
    key = (stat.st_mtime_ns, stat.st_size)
    with _static_cache_lock:
        cached = _static_cache.get(path)
        if cached and cached[0] == key:
            return cached[1:]
    with open(path, 'rb') as f:
        content = f.read()
    entry = (content, _etag(content), gzip.compress(content, COMPRESS_LEVEL, mtime=0))
    with _static_cache_lock:
        _static_cache[path] = (key,) + entry
    return entry

# 비밀번호 무차별 대입 방지: IP별로 일정 시간 내 실패 횟수를 넘기면 잠금
AUTH_MAX_FAILURES = 5
AUTH_WINDOW_SECONDS = 600
AUTH_LOCKOUT_SECONDS = 600
auth_failures = {}
auth_lock = threading.Lock()

ADMIN_API_ENABLED = ADMIN_PASSWORD not in INSECURE_ADMIN_PASSWORDS
if not ADMIN_API_ENABLED:
    log_msg("[API] ADMIN_PASSWORD 미설정/기본값 - 관리 기능 비활성화", "WARN")

# 관리자 로그인 키: 암호로 한 번 로그인하면 브라우저가 암호 대신 이 키를 기억해 관리 요청에 씀.
# 암호에서 만들어지므로 서버 암호를 바꾸면 모든 기기의 로그인이 풀림 (기억한 키로는 암호를 알아낼 수 없음)
ADMIN_TOKEN = hmac.new(ADMIN_PASSWORD.encode('utf-8'), b'dashboard-admin-login-v1', 'sha256').hexdigest()

def board_key_from_input(text):
    """관리 화면에 입력한 갤러리 주소나 키에서 카테고리 키를 뽑음. 알아볼 수 없으면 None (에펨코리아는 수집하지 않음)
    - 디시인사이드 갤러리: 'https://gall.dcinside.com/board/lists/?id=car_new1', 'dc:car_new1' → 'dc:car_new1'
      (마이너·미니 갤러리는 주소 형태가 달라 아직 지원하지 않음)"""
    text = (text or '').strip()
    if text.lower().startswith(DC_BOARD_PREFIX):
        gallery = text[len(DC_BOARD_PREFIX):].strip().lower()
        return DC_BOARD_PREFIX + gallery if DC_GALLERY_RE.fullmatch(gallery) else None
    if any(ch in text for ch in '/?.:'):
        url = urlparse(text if '://' in text else 'https://' + text)
        host = (url.hostname or '').lower()
        if host == 'dcinside.com' or host.endswith('.dcinside.com'):
            gallery = parse_qs(url.query).get('id', [''])[0].lower()
            if not url.path.startswith('/board/') or not DC_GALLERY_RE.fullmatch(gallery):
                return None
            return DC_BOARD_PREFIX + gallery
    return None

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """요청마다 새로운 스레드를 독립 할당하여 동기 블로킹 및 접속 지연을 차단"""
    daemon_threads = True

def client_ip(peer, headers, trust_proxy=None):
    """암호 실패 잠금·로그에 쓸 접속자 IP. 역방향 프록시를 믿도록 설정했고(TRUST_PROXY_HEADERS) 내부 주소에서 온 요청이면
    프록시가 넣은 실제 IP를 씀: X-Real-IP, 없으면 X-Forwarded-For의 마지막 값 (앞쪽은 접속자가 꾸며 보낼 수 있음)"""
    trust_proxy = TRUST_PROXY_HEADERS if trust_proxy is None else trust_proxy
    try:
        if not trust_proxy or not ipaddress.ip_address(peer).is_private:
            return peer
        forwarded = (headers.get('X-Real-IP') or '').strip() or (headers.get('X-Forwarded-For') or '').split(',')[-1].strip()
        return str(ipaddress.ip_address(forwarded)) if forwarded else peer
    except ValueError:
        return peer

def _is_locked_out(ip):
    with auth_lock:
        entry = auth_failures.get(ip)
        if not entry:
            return False
        if entry.get('locked_until', 0) > time.time():
            return True
        if entry['first_failure'] + AUTH_WINDOW_SECONDS < time.time():
            del auth_failures[ip]
        return False

def _record_auth_failure(ip):
    now = time.time()
    with auth_lock:
        entry = auth_failures.get(ip)
        if not entry or entry['first_failure'] + AUTH_WINDOW_SECONDS < now:
            entry = {'first_failure': now, 'count': 0}
            auth_failures[ip] = entry
        entry['count'] += 1
        if entry['count'] >= AUTH_MAX_FAILURES:
            entry['locked_until'] = now + AUTH_LOCKOUT_SECONDS
            log_msg(f"[API] 인증 {AUTH_MAX_FAILURES}회 실패 → {ip} {AUTH_LOCKOUT_SECONDS}초 차단", "WARN")

def _clear_auth_failures(ip):
    with auth_lock:
        auth_failures.pop(ip, None)

def build_state():
    """대시보드 초기 화면 구성용 데이터: 게시판 목록(알림 설정 포함), 통합 피드 요약, 카테고리(에펨코리아 게시판·디시 갤러리)"""
    groups = list_groups(MAX_READ_IDS)
    names = category_names()
    for group in groups:
        for member in group['members']:
            member['board_name'] = names.get(member['board'], member['board'])
    return {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'posts_per_page': POSTS_PER_PAGE,
        # 카테고리(에펨코리아 게시판·디시 갤러리): 사이트, 확인 상태(pending·ok·invalid)와 등록된 키워드 수·사용 중인 게시판 포함
        'boards': list_categories(),
        # 사이트 이름·짧은 표시 (관리 화면에서 편집)
        'sites': site_labels(),
        # 사이드바 묶음 (순서대로): 이름과 묶음 안 모든 게시판을 합친 피드 요약 (묶음 제목 옆 안 읽은 수·묶음 전체 글 보기)
        'folders': list_folders(MAX_READ_IDS),
        # 모든 게시판을 합친 통합 피드 요약 (같은 글은 한 번만 셈). 게시판과 같이
        # 모든 글·동영상 글·안 읽은 새 글·새 댓글이 달린 글 수와 안 읽은 글·새 댓글 글 ID를 담음
        'all': feed_summary(MAX_READ_IDS),
        # 사용자가 만든 게시판 (등록한 키워드의 글을 중복 없이 한 피드로)
        'groups': groups,
        # 텔레그램: 보관한 글의 새 댓글 알림, 하루 요약을 보내는 시각
        'saved_comment_alert': saved_comment_alert(),
        'digest_hour': DIGEST_HOUR
    }

def build_posts_page(page, video_only, query='', group_id=None, unread_since=None, deleted_only=False,
                     image_only=False, saved_only=False, folder_id=None, popular=False, since=None):
    """통합 피드(group_id 없음)·게시판·묶음(folder_id)·검색·안 읽은 글·삭제된 글·보관함: 여러 키워드의 글을 중복 없이"""
    total, _ = query_all_posts(0, 0, video_only, query, group_id, unread_since, deleted_only, image_only, saved_only,
                               folder_id, popular, since)
    total_pages = max(1, -(-total // POSTS_PER_PAGE))
    page = min(max(1, page), total_pages)
    _, posts = query_all_posts((page - 1) * POSTS_PER_PAGE, POSTS_PER_PAGE, video_only, query, group_id, unread_since,
                               deleted_only, image_only, saved_only, folder_id, popular, since)
    return {'page': page, 'total_pages': total_pages, 'total': total, 'posts': _decorate_posts(posts)}

# 모아보기 한 페이지의 칸 수 (화면이 보냄: 데스크톱 이미지 12·동영상 6). 너무 크게 요청하면 이 값까지만
MAX_MEDIA_PER_PAGE = 48

def build_media_page(page, kind, per_page, group_id=None, folder_id=None, popular=False, since=None):
    """동영상·이미지 모아보기: 글이 아니라 이미지·동영상 개수로 페이지를 나눔 (페이지마다 같은 칸 수)"""
    total, _ = query_media(kind, 0, 0, group_id, folder_id, popular, since)
    total_pages = max(1, -(-total // per_page))
    page = min(max(1, page), total_pages)
    _, items = query_media(kind, (page - 1) * per_page, per_page, group_id, folder_id, popular, since)
    names = category_names()
    for item in items:
        for link in item['post']['keywords']:
            link['board_name'] = names.get(link['board'], link['board'])
    return {'page': page, 'total_pages': total_pages, 'total': total, 'per_page': per_page, 'items': items}

def _decorate_posts(posts):
    names = category_names()
    for post in posts:
        for link in post.get('keywords', []):
            link['board_name'] = names.get(link['board'], link['board'])
    # 메인 루프가 매 주기 목록의 댓글 수로 변화를 감시하는 최근 글 표시 (필터와 무관하게 키워드 전체 기준)
    syncing_ids = recent_post_ids(LIST_PAGE_SIZE)
    for post in posts:
        post['has_video'] = len(post.get('videos', [])) > 0
        post['is_syncing'] = post['id'] in syncing_ids
        post.pop('list_comment_count', None)
    return posts

class KeywordAPIServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return

    def _send_body(self, status, body, content_type, extra_headers=None,
                   cache_control='no-store, no-cache, must-revalidate, max-age=0', etag=None, gzipped=None):
        """etag가 있으면 브라우저가 가진 것과 비교해 같을 때 본문 없이 304. gzipped는 미리 압축해 둔 본문(화면 파일)"""
        extra_headers = dict(extra_headers or {})
        if etag:
            extra_headers['ETag'] = etag
            if _etag_matches(self.headers, etag):
                status, body, gzipped = 304, b'', None
        compressible = content_type.startswith(COMPRESS_TYPES) and len(body) >= COMPRESS_MIN_BYTES
        if compressible:
            extra_headers['Vary'] = 'Accept-Encoding'
            if _accepts_gzip(self.headers):
                body = gzipped if gzipped is not None else gzip.compress(body, COMPRESS_LEVEL, mtime=0)
                extra_headers['Content-Encoding'] = 'gzip'
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache_control)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        for name, value in extra_headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_data(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        if self.command == 'GET' and status == 200:
            # 조회 응답: 브라우저가 보관하되 쓸 때마다 서버에 물어봄 (내용이 그대로면 304라 다시 받지 않음)
            self._send_body(status, body, 'application/json; charset=utf-8', cache_control=REVALIDATE, etag=_etag(body))
            return
        self._send_body(status, body, 'application/json; charset=utf-8')

    def _send_json(self, status, success, message):
        self._send_data(status, {'success': success, 'message': message})

    def _read_json_body(self):
        """요청 본문 JSON(객체). 길이·형식이 맞지 않으면 ValueError (JSON 해석 오류·글자 깨짐도 ValueError의 하위)"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            raise ValueError("요청 본문 크기가 올바르지 않습니다.")
        params = json.loads(self.rfile.read(content_length).decode('utf-8'))
        if not isinstance(params, dict):
            raise ValueError("요청 본문 형식이 올바르지 않습니다.")
        return params

    def _authorize(self, password, action_name):
        """인증 성공 시 True, 실패 시 응답을 보낸 뒤 False 반환"""
        ip = client_ip(self.client_address[0], self.headers)
        if not ADMIN_API_ENABLED:
            self._send_json(403, False, '❌ 서버에 ADMIN_PASSWORD가 설정되지 않아 관리 기능이 비활성화되어 있습니다.')
            return False
        if _is_locked_out(ip):
            log_msg(f"[API] 차단 중인 IP 요청 거부: {ip} ({action_name})", "WARN")
            self._send_json(429, False, '❌ 인증 실패가 반복되어 잠시 차단되었습니다. 10분 후 다시 시도해 주세요.')
            return False
        # 암호 또는 로그인 키(ADMIN_TOKEN) 둘 다 받음
        given = password.strip().encode('utf-8') if isinstance(password, str) else b''
        if not (hmac.compare_digest(given, ADMIN_PASSWORD.encode('utf-8')) or hmac.compare_digest(given, ADMIN_TOKEN.encode('utf-8'))):
            _record_auth_failure(ip)
            log_msg(f"[API] 비밀번호 불일치: {ip} ({action_name})", "WARN")
            self._send_json(401, False, '❌ 인증 비밀번호가 일치하지 않습니다.')
            return False
        _clear_auth_failures(ip)
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        pure_path = parsed.path
        query = parse_qs(parsed.query)
        log_msg(f"[API] GET {pure_path} ({client_ip(self.client_address[0], self.headers)})", "DEBUG")

        try:
            if pure_path in STATIC_FILES:
                self._serve_static(*STATIC_FILES[pure_path])
            elif pure_path in ('/board', '/ev', '/card', '/stats', '/apt', '/games', '/games/sudoku', '/comics', '/videos'):
                # 끝 슬래시 없이 들어오면 붙여서 (페이지 안의 상대 주소가 맞도록)
                self._send_body(301, b'', 'text/plain; charset=utf-8', {'Location': pure_path + '/'})
            elif pure_path in ('/index.html/board', '/index.html/board/'):
                # DDNS_URL에 index.html이 붙어 있을 때 보낸 예전 알림 링크 (#post-ID는 브라우저가 그대로 넘겨 줌)
                self._send_body(301, b'', 'text/plain; charset=utf-8', {'Location': '/board/'})
            elif pure_path == '/api/dashboard':
                # 최근 수집한 글은 넉넉히 보내고, 화면이 카드 높이에 맞춰 보이는 만큼만 (기본 3개)
                self._send_data(200, {**dashboard_summary(DASHBOARD_RECENT_MAX), 'check_interval': CHECK_INTERVAL,
                                      'collector': runtime_status.snapshot().get('last_cycle'),
                                      'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            elif pure_path == '/api/apt':
                # 아파트 실거래가: 관심 단지마다 최근 거래·직전 대비·최고가 대비·추이 (대시보드 카드와 /apt/ 목록)
                self._send_data(200, {'configured': apt_trades.configured(), 'status': apt_store.sync_status(),
                                      'watches': apt_store.watch_summaries()})
            elif pure_path == '/api/apt/detail':
                # 관심 단지 하나의 모든 거래 (모든 면적)
                watch_param = query.get('id', [''])[0]
                detail = apt_store.watch_detail(int(watch_param)) if watch_param.isdigit() else None
                if detail is None:
                    self._send_data(404, {'found': False})
                else:
                    self._send_data(200, detail)
            elif pure_path == '/api/popular':
                # 게시판별 인기글: 최근 하루·일주일·한 달 동안 수집한 글 중 게시판마다 추천+댓글이 많은 글
                # (키워드 게시판의 '인기글' 보기는 5개, 메인 대시보드 카드는 3개). group·folder가 있으면 그 게시판·묶음만
                days = query.get('days', [''])[0]
                days = int(days) if days in POPULAR_BOARD_DAYS else 1
                limit = query.get('limit', [''])[0]
                limit = min(int(limit), MAX_POPULAR_PER_BOARD) if limit.isdigit() and int(limit) > 0 else 5
                group_param = query.get('group', [''])[0]
                folder_param = query.get('folder', [''])[0]
                since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                self._send_data(200, {'days': days, 'groups': popular_by_group(
                    since, limit, int(group_param) if group_param.isdigit() else None,
                    int(folder_param) if folder_param.isdigit() and not group_param.isdigit() else None)})
            elif pure_path == '/api/stats':
                # 통계 화면: 최근 7·30·90일 동안 수집한 글 수 (날짜·시간대·게시판·키워드별). group이 있으면 그 게시판만
                days = query.get('days', [''])[0]
                group_param = query.get('group', [''])[0]
                stats = stats_summary(int(days) if days in STATS_DAYS else 30, int(group_param) if group_param.isdigit() else None)
                names = category_names()
                for kw in stats['keywords']:
                    kw['board_name'] = names.get(kw['board'], kw['board'])
                self._send_data(200, stats)
            elif pure_path.startswith('/api/comics/'):
                self._handle_comics_get(pure_path, query)
            elif pure_path.startswith('/api/videos/'):
                self._handle_videos_get(pure_path, query)
            elif pure_path.startswith(self.LEDGER_HOOK_PREFIX):
                self._handle_ledger_hook_get(pure_path[len(self.LEDGER_HOOK_PREFIX):])
            elif pure_path.startswith('/api/ledger/'):
                self._handle_ledger_get(pure_path, query)
            elif pure_path.startswith(IMAGE_URL_PREFIX):
                self._serve_image(pure_path[len(IMAGE_URL_PREFIX):])
            elif pure_path == '/api/fm-links':
                # 에펨코리아 화면의 FM키워드 줄(설치한 스크립트)이 가져가는 키워드 목록
                self._send_data(200, {'groups': fm_links_by_group()})
            elif pure_path == '/fm-keywords.user.js':
                self._serve_userscript()
            elif pure_path == '/api/state':
                self._send_data(200, build_state())
            elif pure_path == '/api/posts' and 'ids' in query:
                # 새 댓글 모아보기: 화면을 연 때의 글 목록 중 한 페이지 분량을 그 순서대로
                ids = [i for i in query['ids'][0].split(',') if is_post_id(i)][:POSTS_PER_PAGE]
                self._send_data(200, {'posts': _decorate_posts(query_posts_by_ids(ids))})
            elif pure_path == '/api/posts':
                try:
                    page = int(query.get('page', ['1'])[0])
                except ValueError:
                    page = 1
                video_only = query.get('video_only', ['0'])[0] in ('1', 'true')
                search = query.get('q', [''])[0].strip()[:MAX_QUERY_LENGTH]
                image_only = query.get('image_only', ['0'])[0] in ('1', 'true') and not search
                group_param = query.get('group', [''])[0]
                # 검색은 기본이 모든 게시판. group·folder를 함께 보내면 그 게시판·묶음 안에서만 찾음
                group_id = int(group_param) if group_param.isdigit() else None
                # 안 읽은 글 보기: 화면을 연 시각(서버 시각 'YYYY-MM-DD HH:MM:SS') 이후 읽은 글은 계속 포함.
                # 'now'면 지금 시각을 기준으로 정해 응답에 담아 줌 (화면이 다음 페이지에도 같은 기준을 쓰도록)
                since = query.get('unread_since', [''])[0]
                if since == 'now':
                    since = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                unread_since = since if re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', since) and not search else None
                deleted_only = query.get('deleted_only', ['0'])[0] in ('1', 'true') and not search
                saved_only = query.get('saved_only', ['0'])[0] in ('1', 'true') and not search
                # 정렬: sort=popular면 추천+댓글이 많은 순, days(1·7·30)가 있으면 최근 그 기간에 수집한 글만
                popular = query.get('sort', [''])[0] == 'popular'
                days = query.get('days', [''])[0]
                since = ((datetime.now() - timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')
                         if popular and days in POPULAR_DAYS else None)
                # 검색 기간 (sdays): 인기순 기간과 함께 오면 더 짧은 쪽
                search_days = query.get('sdays', [''])[0]
                if search and search_days in SEARCH_DAYS:
                    search_since = (datetime.now() - timedelta(days=int(search_days))).strftime('%Y-%m-%d %H:%M:%S')
                    since = max(since, search_since) if since else search_since
                # 묶음 (사이드바 묶음 제목): 묶음 안 모든 게시판의 글. 게시판을 고른 경우에는 쓰지 않음
                folder_param = query.get('folder', [''])[0]
                folder_id = int(folder_param) if folder_param.isdigit() and group_id is None else None
                media = query.get('media', [''])[0]
                if media in ('image', 'video') and not search:
                    per = query.get('per', [''])[0]
                    per_page = min(int(per), MAX_MEDIA_PER_PAGE) if per.isdigit() and int(per) > 0 else 12
                    self._send_data(200, build_media_page(page, media, per_page, group_id, folder_id, popular, since))
                    return
                data = build_posts_page(page, video_only, search, group_id, unread_since, deleted_only, image_only, saved_only,
                                        folder_id, popular, since)
                if unread_since:
                    data['unread_since'] = unread_since
                self._send_data(200, data)
            elif pure_path == '/api/status':
                # 관리 패널 '수집 상태': 마지막 수집 주기, 차단 의심, 멈춤 의심, 크롬·백업, 최근 경고·오류
                status = runtime_status.snapshot()
                stalled = runtime_status.stalled_seconds(status, WATCH_STARTED)
                status['stalled_minutes'] = int(stalled // 60) if COLLECTOR_STALL_MINUTES and stalled >= COLLECTOR_STALL_MINUTES * 60 else 0
                self._send_data(200, status)
            elif pure_path == '/api/locate':
                post_id = query.get('id', [''])[0]
                location = locate_post(post_id) if is_post_id(post_id) else None
                if location is None:
                    self._send_data(404, {'found': False})
                else:
                    location['page'] = location['index'] // POSTS_PER_PAGE + 1
                    location['found'] = True
                    self._send_data(200, location)
            else:
                self.send_response(404)
                self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            log_msg("[API] 응답 중 브라우저 연결 끊김", "DEBUG")
        except Exception as e:
            log_msg(f"[API] GET {pure_path} 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    def _site_base(self):
        """이 요청이 들어온 사이트 주소 (예: https://example.synology.me). 역방향 프록시가 넘겨 준 https를 따름"""
        host = (self.headers.get('X-Forwarded-Host') or self.headers.get('Host') or f'127.0.0.1:{WEB_PORT}').split(',')[0].strip()
        proto = (self.headers.get('X-Forwarded-Proto') or '').split(',')[0].strip().lower()
        if proto not in ('http', 'https'):
            ddns = (DDNS_URL or '').strip().lower()
            proto = 'https' if ddns.startswith('https://') and host.split(':')[0] in ddns else 'http'
        return f'{proto}://{host}'

    def _serve_userscript(self):
        """Tampermonkey 설치용 FM키워드 줄 스크립트: 사이트 주소를 넣어서 내려줌 (주소가 .user.js로 끝나야 설치 화면이 뜸)"""
        base = self._site_base()
        with open(os.path.join(STATIC_DIR, 'fm-keywords.user.js'), encoding='utf-8') as f:
            script = f.read()
        script = script.replace('__SITE_HOST__', urlparse(base).hostname or '').replace('__SITE__', base)
        self._send_body(200, script.encode('utf-8'), 'text/javascript; charset=utf-8', cache_control=REVALIDATE)

    def _serve_static(self, filename, content_type):
        content, etag, gzipped = load_static(os.path.join(STATIC_DIR, filename))
        extra = {'Content-Security-Policy': CONTENT_SECURITY_POLICY} if filename.endswith('.html') else None
        self._send_body(200, content, content_type, extra, cache_control=REVALIDATE, etag=etag, gzipped=gzipped)

    def _serve_image(self, rel):
        """수집할 때 저장한 글 이미지 (images.py). 같은 주소의 파일은 바뀌지 않으므로 브라우저가 오래 보관하게 함"""
        found = image_file(rel)
        if not found:
            self.send_response(404)
            self.end_headers()
            return
        path, content_type = found
        with open(path, 'rb') as f:
            content = f.read()
        self._send_body(200, content, content_type, cache_control='private, max-age=2592000')

    # 주소: (처리 함수, 오류 기록에 쓸 이름)
    POST_HANDLERS = {
        '/api/toggle-alert': ('_handle_toggle_alert', '알림 설정 처리'),
        '/api/read': ('_handle_read', '읽음 기록'),
        '/api/read-all': ('_handle_read_all', '모두 읽음'),
        '/api/saved': ('_handle_saved', '보관함 처리'),
        '/api/group': ('_handle_group', '게시판 처리'),
        '/api/folder': ('_handle_folder', '묶음 처리'),
        '/api/category': ('_handle_category', '카테고리 처리'),
        '/api/fm-link': ('_handle_fm_link', '에펨코리아 바로가기 처리'),
        '/api/site': ('_handle_site', '사이트 이름 처리'),
        '/api/login': ('_handle_login', '로그인 처리'),
        '/api/card': ('_handle_card', '카드 혜택 처리'),
        '/api/ev': ('_handle_ev', '유지비 저장 처리'),
        '/api/apt': ('_handle_apt', '실거래가 처리'),
        '/api/comics/session': ('_handle_comics_session', '만화 로그인 처리'),
        '/api/comics/progress': ('_handle_comics_progress', '만화 읽은 위치 저장'),
        '/api/videos/session': ('_handle_videos_session', '동영상 로그인 처리'),
        '/api/videos/progress': ('_handle_videos_progress', '동영상 이어 보기 저장'),
        '/api/videos/convert': ('_handle_videos_convert', '동영상 변환 처리'),
        '/api/system': ('_handle_system', 'NAS 상태 조회'),
        '/api/ledger/session': ('_handle_ledger_session', '가계부 로그인 처리'),
        '/api/ledger/entry': ('_handle_ledger_entry', '가계부 기록 처리'),
        '/api/ledger/category': ('_handle_ledger_category', '가계부 소비형태 처리'),
        '/api/ledger/admin': ('_handle_ledger_admin', '가계부 사용자 허락 처리'),
        '/api/ledger/inbox': ('_handle_ledger_inbox', '가계부 확인 대기함 처리'),
        '/api/ledger/rule': ('_handle_ledger_rule', '가계부 가게 규칙 처리'),
        '/api/ledger/hook-key': ('_handle_ledger_hook_key', '가계부 연결 키 처리'),
        '/api/ledger/duty': ('_handle_duty', '근무표 처리'),
    }

    def do_POST(self):
        pure_path = self.path.split('?')[0]
        log_msg(f"[API] POST {pure_path} ({client_ip(self.client_address[0], self.headers)})", "DEBUG")
        # 휴대폰(매크로드로이드 등)이 보내는 결제 알림: 본문이 JSON이 아닐 수 있어 따로 받음
        # YeYe홈 앱(APK) 올리기: 본문이 파일 그대로라 JSON으로 읽지 않음
        if pure_path == '/api/ledger/app-upload':
            try:
                self._handle_ledger_app_upload()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except Exception as e:
                log_msg(f"[API] 가계부 앱 올리기 오류: {short_err(e)}", "ERROR")
                self._send_json(500, False, '❌ 처리하지 못했습니다.')
            return
        if pure_path.startswith(self.LEDGER_HOOK_PREFIX):
            try:
                self._handle_ledger_hook(pure_path[len(self.LEDGER_HOOK_PREFIX):])
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except Exception as e:
                log_msg(f"[API] 가계부 알림 받기 오류: {short_err(e)}", "ERROR")
                self._send_json(500, False, '❌ 처리하지 못했습니다.')
            return
        handler, label = self.POST_HANDLERS.get(pure_path, (None, None))
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return
        # 본문(JSON)을 먼저 읽어 둠. 형식이 깨진 요청은 서버 오류(500)가 아니라 잘못된 요청(400)으로 답하고 오류 기록을 남기지 않음
        try:
            self._body = self._read_json_body()
        except ValueError as e:
            log_msg(f"[API] 잘못된 요청 본문: {pure_path} {short_err(e)}", "DEBUG")
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        # 처리 중 예기치 못한 오류는 여기서 한 번에: 기록을 남기고 서버 오류(500)로 답함
        try:
            getattr(self, handler)()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            log_msg("[API] 응답 중 브라우저 연결 끊김", "DEBUG")
        except Exception as e:
            log_msg(f"[API] {label} 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    def _handle_group(self):
        """게시판 만들기·수정·삭제 (관리자 암호 필요). 키워드는 게시판에 등록하는 방식으로만 관리"""
        params = self._body
        if not self._authorize(params.get('password', ''), '게시판 관리'):
            return
        action = params.get('action')
        if action == 'arrange':
            # 사이드바 묶음·순서: folder_id가 있으면 그 묶음으로(null이면 묶음 없음), direction이 있으면 한 칸 위·아래로
            group_id = params.get('id')
            folder_id = params.get('folder_id', ...)
            direction = params.get('direction')
            if (not isinstance(group_id, int) or direction not in (None, 'up', 'down')
                    or not (folder_id is ... or folder_id is None or isinstance(folder_id, int))):
                self._send_json(400, False, '❌ 잘못된 요청입니다.')
                return
            try:
                name = arrange_group(group_id, folder_id, direction)
            except ValueError as ve:
                self._send_json(400, False, f'❌ {ve}')
                return
            if name is None:
                self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
                return
            log_msg(f"[API] 게시판 묶음·순서 변경: {name}", "DEBUG")
            self._send_json(200, True, '게시판을 옮겼습니다.')
            return
        if action == 'delete':
            group_id = params.get('id')
            dropped = delete_group(group_id) if isinstance(group_id, int) else None
            if dropped is None:
                self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
                return
            log_msg(f"[API] 게시판 삭제: #{group_id}{self._dropped_text(dropped)}")
            self._send_json(200, True, '🗑️ 게시판을 삭제했습니다.')
            return
        if action == 'pause':
            # 게시판 전체 일시정지·다시 수집: 그 게시판의 모든 키워드에 한 번에 적용
            group_id, paused = params.get('id'), params.get('paused')
            if not isinstance(group_id, int) or not isinstance(paused, bool):
                self._send_json(400, False, '❌ 잘못된 요청입니다.')
                return
            result = set_group_paused(group_id, paused)
            if result is None:
                self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
                return
            log_msg(f"[API] 게시판 {'일시정지' if paused else '다시 수집'}: {result[0]} (키워드 {result[1]}개)")
            self._send_json(200, True, f"'{result[0]}' 게시판 수집을 {'일시정지했' if paused else '다시 시작했'}습니다.")
            return
        if action not in ('create', 'update'):
            self._send_json(400, False, '❌ 지원하지 않는 작업입니다.')
            return
        name = str(params.get('name', '')).strip()
        members = params.get('members')
        if not name or len(name) > MAX_GROUP_NAME_LENGTH or any(ch in name for ch in '\r\n\t'):
            self._send_json(400, False, f'❌ 게시판 이름은 줄바꿈 없이 {MAX_GROUP_NAME_LENGTH}자 이하로 입력해 주세요.')
            return
        if (not isinstance(members, list) or not members or len(members) > MAX_GROUP_MEMBERS
                or not all(isinstance(m, dict) and isinstance(m.get('board'), str) and isinstance(m.get('keyword'), str) for m in members)):
            self._send_json(400, False, f'❌ 키워드를 1~{MAX_GROUP_MEMBERS}개 등록해 주세요.')
            return
        # 무시할 표현(ignores)·일시정지(paused)는 키워드마다 선택 사항. 보내지 않으면 그 키워드의 기존 값을 그대로 둠
        if not all(isinstance(m.get('paused', False), bool) for m in members):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        for m in members:
            ignores = m.get('ignores', [])
            if (not isinstance(ignores, list) or len(ignores) > MAX_IGNORES_PER_KEYWORD
                    or not all(isinstance(p, str) and p.strip() and len(p.strip()) <= MAX_KEYWORD_LENGTH
                               and not any(ch in p for ch in '\r\n\t') for p in ignores)):
                self._send_json(400, False, f'❌ 무시할 표현은 키워드마다 {MAX_IGNORES_PER_KEYWORD}개까지, '
                                            f'줄바꿈 없이 {MAX_KEYWORD_LENGTH}자 이하로 입력해 주세요.')
                return
        members = [{'board': m['board'].strip(), 'keyword': m['keyword'].strip(),
                    **({'ignores': [p.strip() for p in m['ignores']]} if 'ignores' in m else {}),
                    **({'paused': m['paused']} if 'paused' in m else {})} for m in members]
        names = category_names()
        # 에펨코리아 키워드는 새로 등록할 수 없음 (수집하지 않음). 예전부터 있던 키워드는 예전 글을 보여 주려고 그대로 둘 수 있음
        existing = keyword_pairs()
        for m in members:
            if m['board'] not in names:
                self._send_json(400, False, '❌ 존재하지 않는 카테고리입니다.')
                return
            if not site_enabled(board_site(m['board'])) and (m['board'], m['keyword']) not in existing:
                self._send_json(400, False, f"❌ {SITE_NAMES[board_site(m['board'])]}는 수집하지 않아 키워드를 새로 등록할 수 없습니다.")
                return
            if not m['keyword'] or len(m['keyword']) > MAX_KEYWORD_LENGTH or any(ch in m['keyword'] for ch in '\r\n\t'):
                self._send_json(400, False, f'❌ 키워드는 줄바꿈 없이 {MAX_KEYWORD_LENGTH}자 이하로 입력해 주세요.')
                return
        # 에펨코리아 바로가기 (수집하지 않고 검색 링크만). 보내지 않으면 그대로 둠
        fm_links = params.get('fm_links')
        if fm_links is not None:
            if (not isinstance(fm_links, list) or len(fm_links) > MAX_FM_LINKS
                    or not all(isinstance(l, dict) and isinstance(l.get('board'), str) and isinstance(l.get('keyword'), str) for l in fm_links)):
                self._send_json(400, False, f'❌ 에펨코리아 바로가기는 {MAX_FM_LINKS}개까지 등록할 수 있습니다.')
                return
            fm_links = [{'board': l['board'].strip().lower(), 'keyword': l['keyword'].strip()} for l in fm_links]
            for l in fm_links:
                if l['board'] and not FM_MID_RE.fullmatch(l['board']):
                    self._send_json(400, False, '❌ 에펨코리아 게시판 이름(주소의 영문, 예: football_world)을 확인해 주세요.')
                    return
                if not l['keyword'] or len(l['keyword']) > MAX_KEYWORD_LENGTH or any(ch in l['keyword'] for ch in '\r\n\t'):
                    self._send_json(400, False, f'❌ 키워드는 줄바꿈 없이 {MAX_KEYWORD_LENGTH}자 이하로 입력해 주세요.')
                    return
        group_id = params.get('id') if action == 'update' else None
        if action == 'update' and not isinstance(group_id, int):
            self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
            return
        # 합칠 게시판: 그 게시판의 키워드는 화면에서 members에 이미 넣어 보내고, 저장한 뒤 그 게시판은 지움
        merge_ids = params.get('merge_ids', [])
        if not isinstance(merge_ids, list) or len(merge_ids) > MAX_GROUP_MEMBERS or not all(isinstance(i, int) for i in merge_ids):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        folder_id = params.get('folder_id')
        if folder_id is not None and not isinstance(folder_id, int):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        try:
            saved_id, dropped = save_group(group_id, name, members, merge_ids, folder_id, fm_links)
        except ValueError as ve:
            self._send_json(400, False, f'❌ {ve}')
            return
        merged = f" / 게시판 {len(merge_ids)}개 합침" if merge_ids else ''
        log_msg(f"[API] 게시판 {'추가' if action == 'create' else '수정'}: {name} (키워드 {len(members)}개){merged}{self._dropped_text(dropped)}")
        self._send_data(200, {'success': True, 'id': saved_id,
                              'message': f"📚 '{name}' 게시판을 {'만들었' if action == 'create' else '수정했'}습니다."})

    @staticmethod
    def _dropped_text(dropped):
        if not dropped:
            return ''
        names = category_names()
        return f" / 수집 중단 키워드: {', '.join(f'{names.get(b, b)}/{k}' for b, k in dropped)}"

    def _fm_link_params(self):
        """바로가기 요청의 (게시판 ID, 에펨코리아 게시판 mid, 키워드). 잘못되면 응답하고 None"""
        params = self._body
        group_id, board, keyword = params.get('group_id'), params.get('board'), params.get('keyword')
        if type(group_id) is not int or not isinstance(board, str) or not isinstance(keyword, str):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return None
        board, keyword = board.strip().lower(), keyword.strip()
        if board and not FM_MID_RE.fullmatch(board):
            self._send_json(400, False, '❌ 에펨코리아 게시판 이름(주소의 영문, 예: football_world)을 확인해 주세요.')
            return None
        if not keyword or len(keyword) > MAX_KEYWORD_LENGTH or any(ch in keyword for ch in '\r\n\t'):
            self._send_json(400, False, f'❌ 키워드는 줄바꿈 없이 {MAX_KEYWORD_LENGTH}자 이하로 입력해 주세요.')
            return None
        return group_id, board, keyword

    def _handle_fm_link(self):
        """에펨코리아 바로가기: 누른 시각 기록(open, 누구나) · 추가(add)·빼기(remove, 관리자).
        {action, group_id, board, keyword[, password]}. 서버는 에펨코리아에 요청하지 않음"""
        action = self._body.get('action')
        if action in ('seen_init', 'read', 'read_all', 'found'):
            self._handle_fm_seen(action)
            return
        if action == 'client_error':
            # FM키워드 줄(탬퍼몽키)이 사용자 브라우저에서 오류로 멈췄을 때 알려 오는 한 줄 (원인을 서버 기록에서 보려고)
            message = str(self._body.get('message') or '')[:300].replace('\n', ' | ')
            where = str(self._body.get('where') or '')[:40]
            version = str(self._body.get('version') or '')[:20]
            log_msg(f"[FM키워드 줄] 브라우저 오류 ({version}, {where}): {message}", "WARN")
            self._send_json(200, True, '기록했습니다.')
            return
        if action in ('reorder', 'reorder_groups', 'move'):
            self._handle_fm_reorder(action)
            return
        if action not in ('open', 'add', 'remove'):
            self._send_json(400, False, '❌ 지원하지 않는 작업입니다.')
            return
        if action != 'open' and not self._authorize(self._body.get('password', ''), '에펨코리아 바로가기'):
            return
        found = self._fm_link_params()
        if not found:
            return
        group_id, board, keyword = found
        if action == 'open':
            at = touch_fm_link(group_id, board, keyword)
            if at is None:
                self._send_json(404, False, '❌ 없는 바로가기입니다.')
                return
            self._send_data(200, {'success': True, 'last_opened': at})
            return
        if action == 'add':
            try:
                links = add_fm_link(group_id, board, keyword)
            except ValueError as ve:
                self._send_json(400, False, f'❌ {ve}')
                return
        else:
            links = remove_fm_link(group_id, board, keyword)
            if links is None:
                self._send_json(404, False, '❌ 없는 바로가기입니다.')
                return
        log_msg(f"[API] 에펨코리아 바로가기 {'추가' if action == 'add' else '빼기'}: 게시판 #{group_id} {board or '전체'}/{keyword}")
        self._send_data(200, {'success': True, 'links': links})

    def _handle_fm_reorder(self, action):
        """FM키워드 순서 (관리자): reorder {group_id, links: [{board, keyword}]} 게시판 안 바로가기 순서 ·
        reorder_groups {ids: [게시판 ID]} 카드 순서 ·
        move {from_group, group_id, board, keyword, links} 바로가기 하나를 다른 카드로 (links는 받는 카드의 옮긴 뒤 순서)"""
        params = self._body
        if not self._authorize(params.get('password', ''), 'FM키워드 순서'):
            return
        try:
            if action == 'reorder_groups':
                ids = params.get('ids')
                if not isinstance(ids, list) or len(ids) > 1000 or any(type(i) is not int for i in ids):
                    self._send_json(400, False, '❌ 잘못된 요청입니다.')
                    return
                reorder_fm_groups(ids)
                log_msg(f"[API] FM키워드 카드 순서 바꿈: {len(ids)}개")
                self._send_data(200, {'success': True})
                return
            group_id, links = params.get('group_id'), params.get('links')
            if (type(group_id) is not int or not isinstance(links, list) or len(links) > MAX_FM_LINKS
                    or any(not isinstance(l, dict) or not isinstance(l.get('board'), str) or not isinstance(l.get('keyword'), str) for l in links)):
                self._send_json(400, False, '❌ 잘못된 요청입니다.')
                return
            order = [(l['board'], l['keyword']) for l in links]
            if action == 'move':
                from_id, board, keyword = params.get('from_group'), params.get('board'), params.get('keyword')
                if type(from_id) is not int or not isinstance(board, str) or not isinstance(keyword, str):
                    self._send_json(400, False, '❌ 잘못된 요청입니다.')
                    return
                from_links, to_links = move_fm_link(from_id, group_id, board, keyword, order)
                log_msg(f"[API] FM키워드 옮김: 게시판 #{from_id} → #{group_id} {board or '전체'}/{keyword}")
                self._send_data(200, {'success': True, 'from_links': from_links, 'links': to_links})
                return
            result = reorder_fm_links(group_id, order)
        except ValueError as ve:
            self._send_json(409, False, f'❌ {ve}')
            return
        log_msg(f"[API] FM키워드 순서 바꿈: 게시판 #{group_id}")
        self._send_data(200, {'success': True, 'links': result})

    def _handle_fm_seen(self, action):
        """새 글 기준 (FM키워드 줄, 누구나): seen_init {board, keyword, max} 처음 기준 · read {post} 글 하나 읽음 ·
        read_all {board, keyword, max} 모두 읽음 · found {board, keyword, max, ids} 검색 결과에서 확인한 새 글 번호. 글 번호는 에펨코리아 글 번호 (보고 있는 화면에서 읽은 값)"""
        params = self._body
        def number(value):
            return value if type(value) is int and 0 < value < 10 ** 13 else None
        if action == 'read':
            post = number(params.get('post'))
            if post is None:
                self._send_json(400, False, '❌ 잘못된 요청입니다.')
                return
            self._send_data(200, {'success': True, 'changed': fm_seen_read(post)})
            return
        board, keyword, top = params.get('board'), params.get('keyword'), number(params.get('max'))
        if (not isinstance(board, str) or not isinstance(keyword, str) or top is None
                or (board and not FM_MID_RE.fullmatch(board)) or not keyword.strip() or len(keyword) > MAX_KEYWORD_LENGTH):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        keyword = keyword.strip()
        if action == 'found':
            ids = params.get('ids')
            if not isinstance(ids, list) or len(ids) > 100 or any(number(i) is None for i in ids):
                self._send_json(400, False, '❌ 잘못된 요청입니다.')
                return
            found = fm_seen_found(board, keyword, ids)
            if found is None:
                self._send_json(404, False, '❌ 새 글 기준이 없습니다.')
                return
            self._send_data(200, {'success': True, 'found_ids': found})
            return
        if action == 'seen_init':
            seen_max, read_ids = fm_seen_init(board, keyword, top)
            self._send_data(200, {'success': True, 'seen_max': seen_max, 'read_ids': read_ids})
        else:
            self._send_data(200, {'success': True, 'seen_max': fm_seen_read_all(board, keyword, top), 'read_ids': []})

    def _handle_folder(self):
        """묶음 만들기·이름 바꾸기·삭제·순서 (관리자 암호 필요)"""
        params = self._body
        if not self._authorize(params.get('password', ''), '묶음 관리'):
            return
        action = params.get('action')
        folder_id = params.get('id')
        if action in ('rename', 'delete', 'move') and not isinstance(folder_id, int):
            self._send_json(400, False, '❌ 존재하지 않는 묶음입니다.')
            return
        if action in ('create', 'rename'):
            name = str(params.get('name', '')).strip()
            if not name or len(name) > MAX_GROUP_NAME_LENGTH or any(ch in name for ch in '\r\n\t'):
                self._send_json(400, False, f'❌ 묶음 이름은 줄바꿈 없이 {MAX_GROUP_NAME_LENGTH}자 이하로 입력해 주세요.')
                return
            try:
                saved_id = save_folder(folder_id if action == 'rename' else None, name)
            except ValueError as ve:
                self._send_json(400, False, f'❌ {ve}')
                return
            log_msg(f"[API] 묶음 {'추가' if action == 'create' else '이름 변경'}: {name}")
            self._send_data(200, {'success': True, 'id': saved_id, 'message': f"📁 '{name}' 묶음을 저장했습니다."})
        elif action == 'delete':
            if not delete_folder(folder_id):
                self._send_json(400, False, '❌ 존재하지 않는 묶음입니다.')
                return
            log_msg(f"[API] 묶음 삭제: #{folder_id}")
            self._send_json(200, True, '🗑️ 묶음을 삭제했습니다. 안에 있던 게시판은 묶음 없이 남습니다.')
        elif action == 'move' and params.get('direction') in ('up', 'down'):
            if not move_folder(folder_id, params['direction']):
                self._send_json(400, False, '❌ 존재하지 않는 묶음입니다.')
                return
            self._send_json(200, True, '묶음을 옮겼습니다.')
        else:
            self._send_json(400, False, '❌ 지원하지 않는 작업입니다.')

    def _handle_login(self):
        """관리자 로그인: 암호가 맞으면 로그인 키를 돌려줌 (화면은 이 키를 기억해 관리 버튼을 보이고 관리 요청에 씀).
        틀린 암호는 다른 관리 요청과 같이 실패 횟수에 세어 잠금"""
        if not self._authorize(self._body.get('password', ''), '관리자 로그인'):
            return
        log_msg(f"[API] 관리자 로그인: {client_ip(self.client_address[0], self.headers)}")
        self._send_data(200, {'success': True, 'message': '로그인했습니다.', 'token': ADMIN_TOKEN})

    # ==========================================
    # 만화 뷰어 (/comics/, comics.py)
    # 이미지(<img>)는 요청에 로그인 키를 담을 수 없으므로, 로그인 키를 한 번 보내면 만화 API에만 쓰는 쿠키로 받아 둠.
    # 쿠키 값은 관리자 로그인 키와 같아 서버 암호를 바꾸면 함께 풀림. 화면 스크립트는 읽을 수 없고(HttpOnly) 다른 사이트에서는 보내지 않음
    # ==========================================
    COMICS_COOKIE = 'comics_key'

    def _comics_authorized(self):
        if not ADMIN_API_ENABLED:
            return False
        try:
            morsel = SimpleCookie(self.headers.get('Cookie') or '').get(self.COMICS_COOKIE)
        except CookieError:
            return False
        return bool(morsel) and hmac.compare_digest(morsel.value.encode('utf-8'), ADMIN_TOKEN.encode('utf-8'))

    def _comics_cookie(self, value, max_age):
        return f"{self.COMICS_COOKIE}={value}; Path=/api/comics/; Max-Age={max_age}; HttpOnly; SameSite=Strict"

    def _handle_comics_session(self):
        """만화 로그인: 암호나 로그인 키가 맞으면 쿠키를 줌. action=logout이면 쿠키를 지움"""
        if self._body.get('action') == 'logout':
            body = json.dumps({'success': True}).encode('utf-8')
            self._send_body(200, body, 'application/json; charset=utf-8', {'Set-Cookie': self._comics_cookie('', 0)})
            return
        if not self._authorize(self._body.get('password', ''), '만화 로그인'):
            return
        body = json.dumps({'success': True, 'token': ADMIN_TOKEN}).encode('utf-8')
        self._send_body(200, body, 'application/json; charset=utf-8',
                        {'Set-Cookie': self._comics_cookie(ADMIN_TOKEN, 365 * 24 * 3600)})

    # ==========================================
    # 동영상: 만화와 같이 관리자 로그인 키로 받는 쿠키가 있어야 함 (영상·썸네일 요청에는 키를 담을 수 없어서)
    # ==========================================
    VIDEOS_COOKIE = 'videos_key'
    STREAM_CHUNK = 256 * 1024

    def _videos_authorized(self):
        if not ADMIN_API_ENABLED:
            return False
        try:
            morsel = SimpleCookie(self.headers.get('Cookie') or '').get(self.VIDEOS_COOKIE)
        except CookieError:
            return False
        return bool(morsel) and hmac.compare_digest(morsel.value.encode('utf-8'), ADMIN_TOKEN.encode('utf-8'))

    def _videos_cookie(self, value, max_age):
        return f"{self.VIDEOS_COOKIE}={value}; Path=/api/videos/; Max-Age={max_age}; HttpOnly; SameSite=Strict"

    def _handle_videos_session(self):
        """동영상 로그인: 암호나 로그인 키가 맞으면 쿠키를 줌. action=logout이면 쿠키를 지움"""
        if self._body.get('action') == 'logout':
            body = json.dumps({'success': True}).encode('utf-8')
            self._send_body(200, body, 'application/json; charset=utf-8', {'Set-Cookie': self._videos_cookie('', 0)})
            return
        if not self._authorize(self._body.get('password', ''), '동영상 로그인'):
            return
        body = json.dumps({'success': True, 'token': ADMIN_TOKEN}).encode('utf-8')
        self._send_body(200, body, 'application/json; charset=utf-8',
                        {'Set-Cookie': self._videos_cookie(ADMIN_TOKEN, 365 * 24 * 3600)})

    def _handle_videos_get(self, pure_path, query):
        if not self._videos_authorized():
            self._send_json(401, False, '❌ 로그인이 필요합니다.')
            return
        if not videos.configured():
            self._send_data(200, {'configured': False})
            return
        path = query.get('p', [''])[0]
        if pure_path == '/api/videos/list':
            listing = videos.list_dir(path)
            if listing is None:
                self._send_data(404, {'found': False})
                return
            if not listing['path']:
                listing['recent'] = videos.recent()
                for item in listing['recent']:
                    item['playable'] = True
            video_convert.annotate(listing)
            self._send_data(200, {'configured': True, **listing})
        elif pure_path == '/api/videos/status':
            # 재생 화면이 열 때: 그대로 재생되는지, 변환이 필요한지, 변환 진행 상황
            found = video_convert.status(path.replace('\\', '/').strip('/'))
            if found is None:
                self._send_data(404, {'found': False})
            else:
                self._send_data(200, found)
        elif pure_path == '/api/videos/search':
            # 동영상 폴더 전체에서 이름·폴더 검색 (videos.all_videos: 기억해 둔 전체 목록)
            found, total = videos.search(query.get('q', [''])[0][:100])
            self._send_data(200, {'videos': video_convert.annotate({'videos': found})['videos'], 'total': total})
        elif pure_path == '/api/videos/latest':
            # 최근에 들어온 영상 (목록 맨 위 '최근 추가')
            self._send_data(200, {'videos': video_convert.annotate({'videos': videos.latest()})['videos']})
        elif pure_path == '/api/videos/samples':
            samples = videos.folder_samples(path)
            if samples is None:
                self._send_data(404, {'found': False})
            else:
                self._send_data(200, {'samples': samples})
        elif pure_path == '/api/videos/thumb':
            found = videos.thumbnail(path)
            if not found:
                self.send_response(404)
                self.end_headers()
                return
            content, tag = found
            self._send_body(200, content, 'image/jpeg', cache_control='private, max-age=2592000', etag=f'"{tag}"')
        elif pure_path == '/api/videos/subs':
            text = videos.subtitle_vtt(path)
            if text is None:
                self.send_response(404)
                self.end_headers()
                return
            self._send_body(200, text.encode('utf-8'), 'text/vtt; charset=utf-8', cache_control='private, max-age=3600')
        elif pure_path == '/api/videos/file':
            full = videos.video_file(path)
            if not full:
                self.send_response(404)
                self.end_headers()
                return
            download = query.get('download', [''])[0] == '1'
            # 브라우저용으로 변환해 둔 것이 있으면 그것을 보냄 (내려받기는 원본 그대로)
            converted = None if download else video_convert.converted_file(full)
            if converted:
                self._stream_file(converted, 'video/mp4', layout=video_fix.layout(converted))
                return
            # 표시 순서표(ctts)가 빠진 MP4는 고친 moov를 끼워 보냄
            fixed = None if download else video_fix.layout(full)
            self._stream_file(full, videos.content_type(full), download=download, layout=fixed)
        elif pure_path == '/api/videos/prepare':
            # 재생 중에 다음 영상을 미리 고쳐 둠 → 다음 영상은 바로 열림
            full = videos.video_file(path)
            if full:
                video_fix.prepare(full)
            self._send_data(202 if full else 404, {'queued': bool(full)})
        else:
            self.send_response(404)
            self.end_headers()

    def _stream_file(self, full, content_type, download=False, layout=None, filename=None):
        """큰 파일을 조금씩 보냄. Range 요청이면 그 부분만 (영상의 원하는 위치로 바로 건너뛰기)
        layout: (전체 크기, [(원본 시작, 길이) 또는 bytes, ...]) — 원본 일부와 고친 조각을 이어 붙인 가상의 파일"""
        size, parts = layout if layout else (os.path.getsize(full), [(0, os.path.getsize(full))])
        start, end, status = 0, size - 1, 200
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', (self.headers.get('Range') or '').strip())
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'private, max-age=3600')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if download:
            self.send_header('Content-Disposition', f"attachment; filename*=UTF-8''{quote(filename or os.path.basename(full))}")
        self.end_headers()
        try:
            with open(full, 'rb') as f:
                pos = 0  # 가상의 파일에서 지금 조각이 시작하는 자리
                for part in parts:
                    length = len(part) if isinstance(part, bytes) else part[1]
                    lo, hi = max(start, pos), min(end + 1, pos + length)
                    if lo < hi:
                        if isinstance(part, bytes):
                            self.wfile.write(part[lo - pos:hi - pos])
                        else:
                            f.seek(part[0] + lo - pos)
                            left = hi - lo
                            while left > 0:
                                chunk = f.read(min(self.STREAM_CHUNK, left))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                left -= len(chunk)
                    pos += length
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # 건너뛰기·창 닫기로 브라우저가 받던 요청을 끊은 것 (정상)
            pass

    # ==========================================
    # 가계부 (ledger.py): 이름·비밀번호로 로그인하면 가계부 API에만 쓰는 쿠키. 관리자는 관리자 암호(또는 로그인 키)로
    # ==========================================
    LEDGER_COOKIE = 'ledger_session'
    LEDGER_COOKIE_AGE = 180 * 24 * 3600

    def _ledger_token(self):
        try:
            morsel = SimpleCookie(self.headers.get('Cookie') or '').get(self.LEDGER_COOKIE)
        except CookieError:
            return ''
        return morsel.value if morsel else ''

    def _ledger_cookie(self, value, max_age):
        return f"{self.LEDGER_COOKIE}={value}; Path=/api/ledger/; Max-Age={max_age}; HttpOnly; SameSite=Strict"

    def _ledger_user(self):
        """로그인한 사람. 없으면 401로 답하고 None"""
        user = ledger.user_for_token(self._ledger_token())
        if not user:
            self._send_json(401, False, '❌ 로그인이 필요합니다.')
        return user

    def _ledger_reply(self, fn):
        """ledger 함수를 부르고 거절 이유(LedgerError)는 400으로"""
        try:
            result = fn()
        except ledger.LedgerError as e:
            self._send_json(400, False, f'❌ {e}')
            return
        self._send_data(200, {'success': True, **(result or {})})

    @staticmethod
    def _ledger_admin_password(password):
        given = password.strip().encode('utf-8')
        return bool(ADMIN_PASSWORD) and (hmac.compare_digest(given, ADMIN_PASSWORD.encode('utf-8'))
                                         or hmac.compare_digest(given, ADMIN_TOKEN.encode('utf-8')))

    def _handle_ledger_get(self, pure_path, query):
        user = self._ledger_user()
        if not user:
            return
        if pure_path == '/api/ledger/me':
            self._send_data(200, {'user': user})
        elif pure_path == '/api/ledger/state':
            self._send_data(200, {'user': user, **ledger.state(query.get('month', [''])[0])})
        elif pure_path == '/api/ledger/inbox':
            self._send_data(200, {'items': ledger.inbox(user), 'rules': ledger.rules(), 'discarded': ledger.discarded(user), 'hook': ledger.hook_info(user),
                                  'hook_base': self._site_base() + self.LEDGER_HOOK_PREFIX, 'app': ledger_app.info()})
        elif pure_path == '/api/ledger/app':
            # 앱이 연결 주소 없이 가계부 로그인만으로 새 버전을 확인할 때
            app = ledger_app.info()
            self._send_data(200, {'app': {k: app[k] for k in ('versionCode', 'versionName', 'size', 'sha256')} if app else None})
        elif pure_path == '/api/ledger/app.apk':
            app = ledger_app.info()
            if not app:
                self._send_json(404, False, '❌ 올라간 앱이 없습니다.')
                return
            self._stream_file(ledger_app.APK_FILE, 'application/vnd.android.package-archive', download=True,
                              filename=ledger_app.download_name(app))
        elif pure_path == '/api/ledger/year':
            self._send_data(200, ledger.year_totals(query.get('year', [''])[0]))
        elif pure_path == '/api/ledger/admin' and user['admin']:
            self._send_data(200, ledger.people())
        elif pure_path == '/api/ledger/duty':
            # 근무표: 그 달(month)·고른 사람(person)의 근무와 사람들·근무 종류
            person = query.get('person', [''])[0]
            self._send_data(200, {'user': user, **duty.state(query.get('month', [''])[0], int(person) if person.isdigit() else None)})
        else:
            self._send_json(404, False, '❌ 없는 요청입니다.')

    def _handle_ledger_session(self):
        """{action: login|signup|logout, name, password}"""
        action = self._body.get('action')
        ip = client_ip(self.client_address[0], self.headers)
        if action == 'logout':
            ledger.logout(self._ledger_token())
            body = json.dumps({'success': True}).encode('utf-8')
            self._send_body(200, body, 'application/json; charset=utf-8', {'Set-Cookie': self._ledger_cookie('', 0)})
            return
        if action not in ('login', 'signup'):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        if _is_locked_out(ip):
            self._send_json(429, False, '❌ 로그인 실패가 반복되어 잠시 막혔어요. 10분 뒤에 다시 해 주세요.')
            return
        name, password = self._body.get('name'), self._body.get('password')
        if action == 'signup':
            if isinstance(name, str) and ' '.join(name.split()) == ledger.LEDGER_ADMIN_NAME:
                self._send_json(400, False, '❌ 이미 있는 이름이에요. 다른 이름을 써 주세요.')
                return
            try:
                ledger.signup(name, password)
            except ledger.LedgerError as e:
                self._send_json(400, False, f'❌ {e}')
                return
            log_msg(f"[가계부] 가입 요청: {' '.join(str(name).split())}")
            self._send_json(200, True, '가입 요청을 보냈어요. 관리자가 허락하면 로그인할 수 있어요.')
            return
        try:
            token, user = ledger.login(name, password, self._ledger_admin_password)
        except ledger.LedgerError as e:
            if str(e) == 'pending':
                self._send_json(403, False, '❌ 아직 관리자가 허락하지 않았어요.')
                return
            _record_auth_failure(ip)
            log_msg(f"[API] 가계부 로그인 실패: {ip}", "WARN")
            self._send_json(401, False, '❌ 이름 또는 비밀번호가 맞지 않아요.')
            return
        _clear_auth_failures(ip)
        body = json.dumps({'success': True, 'user': user}, ensure_ascii=False).encode('utf-8')
        self._send_body(200, body, 'application/json; charset=utf-8', {'Set-Cookie': self._ledger_cookie(token, self.LEDGER_COOKIE_AGE)})

    def _handle_ledger_entry(self):
        """{action: add|edit|delete, id, amount, used_on, category_id, memo}"""
        user = self._ledger_user()
        if not user:
            return
        b, action = self._body, self._body.get('action')
        if action == 'add':
            self._ledger_reply(lambda: {'id': ledger.add_entry(user, b.get('amount'), b.get('used_on'), b.get('category_id'), b.get('memo'))})
        elif action == 'edit' and type(b.get('id')) is int:
            self._ledger_reply(lambda: ledger.edit_entry(user, b['id'], b.get('amount'), b.get('used_on'), b.get('category_id'), b.get('memo')))
        elif action == 'delete' and type(b.get('id')) is int:
            self._ledger_reply(lambda: ledger.delete_entry(user, b['id']))
        else:
            self._send_json(400, False, '❌ 잘못된 요청입니다.')

    def _handle_ledger_category(self):
        """{action: add|edit|delete, id, name, color, kind(add: expense·income)} (분류는 로그인한 사람 누구나)"""
        if not self._ledger_user():
            return
        b, action = self._body, self._body.get('action')
        if action == 'add':
            self._ledger_reply(lambda: {'id': ledger.add_category(b.get('name'), b.get('color'), b.get('kind') or 'expense')})
        elif action == 'edit' and type(b.get('id')) is int:
            self._ledger_reply(lambda: ledger.edit_category(b['id'], b.get('name'), b.get('color')))
        elif action == 'delete' and type(b.get('id')) is int:
            self._ledger_reply(lambda: ledger.delete_category(b['id']))
        else:
            self._send_json(400, False, '❌ 잘못된 요청입니다.')

    # ---------- 자동 기록 (휴대폰 결제 알림) ----------
    LEDGER_HOOK_PREFIX = '/api/ledger/hook/'
    LEDGER_HOOK_MAX_BYTES = 4096

    def _handle_ledger_hook(self, key):
        """연결 주소로 온 알림 글 (쿠키 없이 주소의 키로 사람을 알아봄). 본문: 글 그대로, {"text": 글} JSON, text=글 폼 모두 받음"""
        ip = client_ip(self.client_address[0], self.headers)
        if _is_locked_out(ip):
            self._send_json(429, False, '❌ 잠시 뒤에 다시 보내 주세요.')
            return
        length = int(self.headers.get('Content-Length') or 0)
        if length > self.LEDGER_HOOK_MAX_BYTES:
            self._send_json(413, False, '❌ 알림 글이 너무 깁니다.')
            return
        raw = self.rfile.read(length).decode('utf-8', 'replace') if length > 0 else ''
        text = raw
        try:
            body = json.loads(raw) if raw.lstrip().startswith('{') else None
            if isinstance(body, dict):
                text = str(body.get('text') or body.get('message') or '')
        except ValueError:
            pass
        if text.startswith('text=') and 'application/x-www-form-urlencoded' in (self.headers.get('Content-Type') or ''):
            text = parse_qs(text).get('text', [''])[0]
        found = ledger.receive_hook_detail(key.strip('/'), text)
        if found is None:
            _record_auth_failure(ip)
            log_msg(f"[가계부] 모르는 연결 키로 알림: {ip}", "WARN")
            self._send_json(404, False, '❌ 연결 키가 맞지 않습니다.')
            return
        result, item = found
        log_msg(f"[가계부] 결제 알림 받음: {result}", "DEBUG")
        # 넣은 내용(금액·가게 등)은 앱이 '금액 인식 알림'을 띄울 때 씀 (예전 앱은 무시)
        self._send_data(200, {'success': True, 'result': result, **({'item': item} if item else {})})

    def _handle_ledger_hook_get(self, rest):
        """YeYe홈 앱이 연결 주소로 새 버전을 확인·받음 (쿠키 없이 주소의 키로):
        <키>/app → 올라간 앱 정보 {app: {versionCode, versionName, size, sha256} 또는 null}, <키>/app.apk → 파일"""
        ip = client_ip(self.client_address[0], self.headers)
        key, _, what = rest.partition('/')
        if what not in ('app', 'app.apk'):
            self.send_response(404)
            self.end_headers()
            return
        if _is_locked_out(ip):
            self._send_json(429, False, '❌ 잠시 뒤에 다시 시도해 주세요.')
            return
        if not ledger.hook_key_valid(key):
            _record_auth_failure(ip)
            self._send_json(404, False, '❌ 연결 키가 맞지 않습니다.')
            return
        app = ledger_app.info()
        if what == 'app':
            self._send_data(200, {'app': {k: app[k] for k in ('versionCode', 'versionName', 'size', 'sha256')} if app else None})
        elif not app:
            self._send_json(404, False, '❌ 올라간 앱이 없습니다.')
        else:
            self._stream_file(ledger_app.APK_FILE, 'application/vnd.android.package-archive', download=True,
                              filename=ledger_app.download_name(app))

    def _handle_ledger_app_upload(self):
        """관리자가 YeYe홈 앱(APK) 파일을 올림. 본문은 파일 그대로 (application/octet-stream)"""
        user = self._ledger_user()
        if not user:
            return
        if not user['admin']:
            self._send_json(403, False, '❌ 관리자만 올릴 수 있습니다.')
            return
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0 or length > ledger_app.MAX_BYTES:
            self._send_json(413, False, f'❌ 파일은 {ledger_app.MAX_BYTES // 1024 // 1024}MB까지 올릴 수 있습니다.')
            return
        chunks, left = [], length
        while left > 0:
            chunk = self.rfile.read(min(self.STREAM_CHUNK, left))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        if left:
            self._send_json(400, False, '❌ 파일을 끝까지 받지 못했습니다.')
            return
        try:
            app = ledger_app.save(b''.join(chunks), user['name'])
        except ledger_app.AppFileError as e:
            self._send_json(400, False, f'❌ {e}')
            return
        log_msg(f"[가계부] 앱 파일 올림: {app['versionName']}({app['versionCode']}) {app['size']}바이트 by {user['name']}")
        self._send_data(200, {'success': True, 'app': app})

    def _handle_ledger_inbox(self):
        """{action: update|confirm|confirm_all|discard|restore|test, id, category_id, amount, merchant, used_on}. restore는 버린 알림을 되살림"""
        user = self._ledger_user()
        if not user:
            return
        b, action, item = self._body, self._body.get('action'), self._body.get('id')
        def done(extra=None):
            return {**(extra or {}), 'items': ledger.inbox(user), 'rules': ledger.rules(), 'discarded': ledger.discarded(user)}
        if action == 'confirm_all':
            self._ledger_reply(lambda: done({'confirmed': ledger.confirm_all(user)}))
        elif action == 'test':
            self._ledger_reply(lambda: (ledger.send_test_notice(user), done())[1])
        elif action == 'restore' and type(item) is int:
            self._ledger_reply(lambda: (ledger.restore_item(user, item), done())[1])
        elif action in ('update', 'confirm', 'discard') and type(item) is int:
            def run():
                if action == 'update' or any(k in b for k in ('category_id', 'amount', 'merchant', 'used_on')):
                    ledger.update_item(user, item, b.get('category_id'), b.get('amount'), b.get('merchant'), b.get('used_on'))
                if action == 'confirm':
                    ledger.confirm_item(user, item)
                elif action == 'discard':
                    ledger.discard_item(user, item)
                return done()
            self._ledger_reply(run)
        else:
            self._send_json(400, False, '❌ 잘못된 요청입니다.')

    def _handle_ledger_rule(self):
        """가게 이름 규칙 {action: add|delete, pattern, category_id, id} (로그인한 사람 누구나)"""
        user = self._ledger_user()
        if not user:
            return
        b, action = self._body, self._body.get('action')
        if action == 'add':
            self._ledger_reply(lambda: (ledger.add_rule(b.get('pattern'), b.get('category_id')), {'items': ledger.inbox(user), 'rules': ledger.rules()})[1])
        elif action == 'delete' and type(b.get('id')) is int:
            self._ledger_reply(lambda: (ledger.delete_rule(b['id']), {'rules': ledger.rules()})[1])
        else:
            self._send_json(400, False, '❌ 잘못된 요청입니다.')

    def _handle_ledger_hook_key(self):
        """내 연결 키 새로 만들기 (예전 키는 더 못 씀). 키가 든 주소는 이 답에서만 한 번 보여 줌"""
        user = self._ledger_user()
        if not user:
            return
        if self._body.get('action') != 'create':
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        key = ledger.create_hook_key(user)
        log_msg(f"[가계부] 연결 키 새로 만듦: {user['name']}")
        self._send_data(200, {'success': True, 'url': self._site_base() + self.LEDGER_HOOK_PREFIX + key, 'hook': ledger.hook_info(user)})

    def _handle_duty(self):
        """근무표 (duty.py, 멤버 누구나): {action: set, person_id, days: {날짜: 종류 id|null}}
        · person-add|person-rename|person-delete {id, name} · type-add|type-edit|type-delete {id, code, name, start_time, end_time, color}"""
        user = self._ledger_user()
        if not user:
            return
        b, action = self._body, self._body.get('action')
        has_id = type(b.get('id')) is int
        type_args = lambda: (b.get('code'), b.get('name'), b.get('start_time'), b.get('end_time'), b.get('color'))
        handlers = {
            'set': (type(b.get('person_id')) is int, lambda: {'changed': duty.set_days(user, b['person_id'], b.get('days'))}),
            'person-add': (True, lambda: {'id': duty.add_person(b.get('name'))}),
            'person-rename': (has_id, lambda: duty.rename_person(b['id'], b.get('name'))),
            'person-delete': (has_id, lambda: duty.delete_person(b['id'])),
            'type-add': (True, lambda: {'id': duty.add_type(*type_args())}),
            'type-edit': (has_id, lambda: duty.edit_type(b['id'], *type_args())),
            'type-delete': (has_id, lambda: duty.delete_type(b['id'])),
        }
        ok, fn = handlers.get(action, (False, None))
        if not ok:
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        try:
            result = fn()
        except duty.DutyError as e:
            self._send_json(400, False, f'❌ {e}')
            return
        self._send_data(200, {'success': True, **(result or {})})

    def _handle_ledger_admin(self):
        """관리자만: {action: approve|reject|revoke, user_id}"""
        user = self._ledger_user()
        if not user:
            return
        if not user['admin']:
            self._send_json(403, False, '❌ 관리자만 할 수 있어요.')
            return
        action, target = self._body.get('action'), self._body.get('user_id')
        fn = {'approve': ledger.approve, 'reject': ledger.reject, 'revoke': ledger.revoke}.get(action)
        if not fn or type(target) is not int:
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        def run():
            fn(target)
            log_msg(f"[가계부] 관리자 {action}: 사용자 #{target}")
            return ledger.people()
        self._ledger_reply(run)

    def _handle_system(self):
        """대시보드 'NAS 상태' 카드 (관리자 전용): CPU·메모리·디스크·컨테이너·동영상 변환"""
        if not self._authorize(self._body.get('password', ''), 'NAS 상태'):
            return
        self._send_data(200, system_status.snapshot())

    def _handle_videos_convert(self):
        """변환 넣기·취소·폴더를 자동 변환에 넣기. {action: 'start'|'cancel'|'folder', path}"""
        if not self._videos_authorized():
            self._send_json(401, False, '❌ 로그인이 필요합니다.')
            return
        action, path = self._body.get('action'), self._body.get('path')
        if action not in ('start', 'cancel', 'folder') or not isinstance(path, str):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        path = path.replace('\\', '/').strip('/')
        if not videos.configured():
            self._send_json(404, False, '❌ 동영상 폴더가 없습니다.')
            return
        if action == 'folder':
            count = video_convert.enqueue_folder(path)
            if count is None:
                self._send_json(404, False, '❌ 폴더를 찾을 수 없습니다.')
                return
            self._send_data(200, {'success': True, 'queued': count, 'auto_hours': [video_convert.AUTO_START, video_convert.AUTO_END]})
            return
        if not videos.video_file(path):
            self._send_json(404, False, '❌ 영상을 찾을 수 없습니다.')
            return
        if action == 'cancel':
            video_convert.cancel(path)
            self._send_data(200, {'success': True, **video_convert.status(path)})
            return
        found = video_convert.status(path)
        if found['mode'] == 'direct' or found['converted']:
            self._send_json(400, False, '❌ 변환할 필요가 없는 영상입니다.')
            return
        video_convert.enqueue(path, found['mode'])
        self._send_data(200, {'success': True, **video_convert.status(path)})

    def _handle_videos_progress(self):
        if not self._videos_authorized():
            self._send_json(401, False, '❌ 로그인이 필요합니다.')
            return
        path, position, duration = self._body.get('path'), self._body.get('position'), self._body.get('duration')
        if (not isinstance(path, str) or type(position) not in (int, float) or type(duration) not in (int, float)
                or not 0 <= position <= max(duration, 0) + 5 or not 0 < duration <= 30 * 24 * 3600):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        path = path.replace('\\', '/').strip('/')
        if not videos.configured() or not videos.video_file(path):
            self._send_json(404, False, '❌ 영상을 찾을 수 없습니다.')
            return
        videos.save_progress(path, round(float(position), 1), round(float(duration), 1))
        self._send_json(200, True, '저장했습니다.')

    def _handle_comics_get(self, pure_path, query):
        if not self._comics_authorized():
            self._send_json(401, False, '❌ 로그인이 필요합니다.')
            return
        if not comics.configured():
            self._send_data(200, {'configured': False})
            return
        path = query.get('p', [''])[0]
        if pure_path == '/api/comics/list':
            listing = comics.list_dir(path)
            if listing is None:
                self._send_data(404, {'found': False})
                return
            if not listing['path']:
                listing['recent'] = comics.recent()
            self._send_data(200, {'configured': True, **listing})
        elif pure_path == '/api/comics/counts':
            counts = comics.folder_counts(path)
            if counts is None:
                self._send_data(404, {'found': False})
            else:
                self._send_data(200, {'counts': counts})
        elif pure_path == '/api/comics/book':
            info = comics.book_info(path)
            if info is None:
                self._send_data(404, {'found': False})
            else:
                self._send_data(200, info)
        elif pure_path in ('/api/comics/page', '/api/comics/cover'):
            n = query.get('n', [''])[0]
            if pure_path == '/api/comics/cover':
                found = comics.cover_image(path)
            else:
                found = comics.page_image(path, int(n)) if n.isdigit() else None
            if not found:
                self.send_response(404)
                self.end_headers()
                return
            content, content_type, tag = found
            # 같은 책·같은 쪽이면 내용이 바뀌지 않으므로 브라우저가 오래 보관 (책 파일이 바뀌면 지문이 달라짐)
            self._send_body(200, content, content_type, cache_control='private, max-age=2592000', etag=f'"{tag}"')
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_comics_progress(self):
        if not self._comics_authorized():
            self._send_json(401, False, '❌ 로그인이 필요합니다.')
            return
        path, page, pages = self._body.get('path'), self._body.get('page'), self._body.get('pages')
        # 이어 읽기 목록에서 지우기
        if self._body.get('action') == 'forget':
            if not isinstance(path, str) or not comics.configured():
                self._send_json(400, False, '❌ 잘못된 요청입니다.')
                return
            comics.forget_progress(path.replace('\\', '/').strip('/'))
            self._send_json(200, True, '지웠습니다.')
            return
        if (not isinstance(path, str) or type(page) is not int or type(pages) is not int
                or not 0 <= page < max(pages, 1) or not 0 < pages <= comics.MAX_PAGES):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        path = path.replace('\\', '/').strip('/')
        if not comics.configured() or not comics._book_full(path):
            self._send_json(404, False, '❌ 책을 찾을 수 없습니다.')
            return
        comics.save_progress(path, page, pages)
        self._send_json(200, True, '저장했습니다.')

    @staticmethod
    def _card_date(value):
        """'YYYY-MM-DD' 형식의 오늘까지 날짜면 그대로, 아니면 None"""
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return None
        try:
            return value if datetime.strptime(value, '%Y-%m-%d').date() <= datetime.now().date() else None
        except ValueError:
            return None

    @staticmethod
    def _card_amount(value):
        return value if type(value) is int and 0 < value <= MAX_CARD_AMOUNT else None

    # 유지비 계산기 입력값: 이름 → 허용 범위 (화면의 입력 칸과 같은 이름)
    EV_PRESET_FIELDS = {'dist': (0, 100000), 'evEffIn': (0, 50), 'evPrice': (0, 5000), 'evLoss': (0, 95),
                        'iceEff': (0, 100), 'icePrice': (0, 10000)}
    MAX_EV_PRESETS = 50
    MAX_EV_PRESET_NAME = 20

    def _handle_ev(self):
        """유지비 계산기의 저장한 조건 보기·저장·삭제. 폰과 PC가 함께 쓰도록 서버에 두고, 관리자 로그인한 기기만"""
        params = self._body
        if not self._authorize(params.get('password', ''), '유지비 저장'):
            return
        action = params.get('action')
        if action == 'list':
            self._send_data(200, {'success': True, 'presets': ev_presets()})
            return
        if action == 'delete':
            ok = isinstance(params.get('id'), int) and delete_ev_preset(params['id'])
            self._send_json(200 if ok else 400, bool(ok), '삭제했습니다.' if ok else '❌ 존재하지 않는 조건입니다.')
            return
        if action != 'add':
            self._send_json(400, False, '❌ 지원하지 않는 작업입니다.')
            return
        name = str(params.get('name') or '').strip()
        if not name or len(name) > self.MAX_EV_PRESET_NAME or any(ch in name for ch in '\r\n\t'):
            self._send_json(400, False, f'❌ 이름은 줄바꿈 없이 {self.MAX_EV_PRESET_NAME}자 이하로 입력해 주세요.')
            return
        raw = params.get('values')
        values = {}
        for key, (low, high) in self.EV_PRESET_FIELDS.items():
            value = raw.get(key) if isinstance(raw, dict) else None
            if type(value) not in (int, float) or not (low <= value <= high):
                self._send_json(400, False, '❌ 입력값이 올바르지 않습니다.')
                return
            values[key] = value
        preset_id = add_ev_preset(name, values, self.MAX_EV_PRESETS)
        if preset_id is None:
            self._send_json(400, False, f'❌ 조건은 {self.MAX_EV_PRESETS}개까지 저장할 수 있습니다. 쓰지 않는 조건을 지워 주세요.')
            return
        self._send_data(200, {'success': True, 'id': preset_id})

    def _handle_card(self):
        """카드 혜택 조회·등록·수정·삭제. 소비 내역이라 조회까지 모두 로그인 필요"""
        params = self._body
        if not self._authorize(params.get('password', ''), '카드 혜택'):
            return
        action = params.get('action')
        if action == 'list':
            month = params.get('month') or datetime.now().strftime('%Y-%m')
            if not isinstance(month, str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month):
                self._send_json(400, False, '❌ 잘못된 요청입니다.')
                return
            self._send_data(200, {'success': True, 'month': month, 'limit': CARD_BENEFIT_LIMIT,
                                  'today': datetime.now().strftime('%Y-%m-%d'),
                                  'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), **card_benefits(month)})
            return
        if action in ('keyword_add', 'keyword_delete'):
            keyword = str(params.get('keyword') or '').strip()
            if not keyword or len(keyword) > MAX_CARD_PLACE_LENGTH or any(ch in keyword for ch in '\r\n\t'):
                self._send_json(400, False, f'❌ 가게 이름은 줄바꿈 없이 {MAX_CARD_PLACE_LENGTH}자 이하로 입력해 주세요.')
                return
            if action == 'keyword_add':
                self._send_data(200, {'success': True, 'applied': add_card_keyword(keyword)})
            elif delete_card_keyword(keyword):
                self._send_json(200, True, '삭제했습니다.')
            else:
                self._send_json(400, False, '❌ 존재하지 않는 가게입니다.')
            return
        if action == 'delete':
            ok = isinstance(params.get('id'), int) and delete_card_benefit(params['id'])
        elif action in ('add', 'update'):
            used_on = self._card_date(params.get('date'))
            amount = self._card_amount(params.get('amount'))
            if used_on is None:
                self._send_json(400, False, '❌ 오늘까지의 날짜를 골라 주세요.')
                return
            if amount is None:
                self._send_json(400, False, '❌ 결제 금액을 숫자로 입력해 주세요.')
                return
            if action == 'add':
                place = str(params.get('place') or '').strip()
                if not place or len(place) > MAX_CARD_PLACE_LENGTH or any(ch in place for ch in '\r\n\t'):
                    self._send_json(400, False, f'❌ 사용처는 줄바꿈 없이 {MAX_CARD_PLACE_LENGTH}자 이하로 입력해 주세요.')
                    return
                self._send_data(200, {'success': True, 'id': add_card_benefit(used_on, place, amount)})
                return
            ok = isinstance(params.get('id'), int) and update_card_benefit(params['id'], used_on, amount)
        else:
            self._send_json(400, False, '❌ 지원하지 않는 작업입니다.')
            return
        if ok:
            self._send_json(200, True, '저장했습니다.')
        else:
            self._send_json(400, False, '❌ 존재하지 않는 항목입니다.')

    def _handle_apt(self):
        """아파트 실거래가 관심 단지 관리 (관리자 암호 필요): 단지 찾기·등록·삭제·알림 켜기끄기"""
        params = self._body
        if not self._authorize(params.get('password', ''), '실거래가 관리'):
            return
        action = params.get('action')
        if action in ('search', 'complexes'):
            # complexes: 지역의 모든 단지 (단지 고르기 목록), search: 이름이 들어간 단지
            lawd_cd = str(params.get('lawd_cd') or '').strip()
            name = str(params.get('name') or '').strip()
            if not re.fullmatch(r'\d{5}', lawd_cd) or (action == 'search' and not name) or len(name) > MAX_APT_NAME_LENGTH:
                self._send_json(400, False, f'❌ 지역 코드는 숫자 5자리, 단지 이름은 {MAX_APT_NAME_LENGTH}자 이하로 입력해 주세요.')
                return
            if not apt_trades.configured():
                self._send_json(400, False, '❌ 서버에 실거래가 인증키(APT_API_KEY)가 설정되지 않았습니다.')
                return
            try:
                results = (apt_trades.region_complexes(lawd_cd) if action == 'complexes'
                           else apt_trades.search_complexes(lawd_cd, name))
            except (apt_trades.AptApiError, requests.RequestException) as e:
                log_msg(f"[실거래] 단지 찾기 실패: {short_err(e)}", "WARN")
                self._send_json(502, False, f'❌ 실거래가 서버에서 받아오지 못했습니다: {short_err(e, 80)}')
                return
            self._send_data(200, {'success': True, 'results': results})
            return
        if action == 'add':
            lawd_cd, apt_seq = params.get('lawd_cd'), params.get('apt_seq')
            name, umd, area = params.get('name'), params.get('umd', ''), params.get('area')
            if (not isinstance(lawd_cd, str) or not re.fullmatch(r'\d{5}', lawd_cd)
                    or not isinstance(apt_seq, str) or not 0 < len(apt_seq) <= 80
                    or not isinstance(name, str) or not 0 < len(name.strip()) <= MAX_APT_NAME_LENGTH
                    or not isinstance(umd, str) or len(umd) > MAX_APT_NAME_LENGTH
                    or any(ch in name + umd + apt_seq for ch in '\r\n\t')
                    or not (area is None or (type(area) is int and APT_AREA_RANGE[0] <= area <= APT_AREA_RANGE[1]))):
                self._send_json(400, False, '❌ 잘못된 요청입니다.')
                return
            if len(apt_store.list_watches()) >= MAX_APT_WATCHES:
                self._send_json(400, False, f'❌ 관심 단지는 {MAX_APT_WATCHES}개까지 등록할 수 있습니다.')
                return
            try:
                watch_id = apt_store.add_watch(lawd_cd, apt_seq, name.strip(), umd.strip(), area)
            except ValueError as ve:
                self._send_json(400, False, f'❌ {ve}')
                return
            apt_trades.request_sync()
            log_msg(f"[API] 실거래가 관심 단지 추가: {name.strip()} {f'{area}㎡' if area else '모든 면적'} ({lawd_cd})")
            self._send_data(200, {'success': True, 'id': watch_id,
                                  'message': f"🏠 '{name.strip()}'을(를) 등록했습니다. 지난 거래를 받아 오는 중입니다."})
            return
        watch_id = params.get('id')
        if type(watch_id) is not int:
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        if action == 'delete':
            ok = apt_store.delete_watch(watch_id)
        elif action == 'alert' and isinstance(params.get('enabled'), bool):
            ok = apt_store.set_watch_alert(watch_id, params['enabled'])
        else:
            self._send_json(400, False, '❌ 지원하지 않는 작업입니다.')
            return
        if ok:
            self._send_json(200, True, '저장했습니다.')
        else:
            self._send_json(400, False, '❌ 존재하지 않는 단지입니다.')

    def _handle_site(self):
        """사이트 이름·짧은 표시 바꾸기 (관리자 암호 필요). 화면의 사이트 제목·FM·DC 표시와 텔레그램 알림에 쓰임"""
        params = self._body
        if not self._authorize(params.get('password', ''), '사이트 이름 변경'):
            return
        site = params.get('site')
        name = str(params.get('name') or '').strip()
        short = str(params.get('short') or '').strip()
        if site not in site_labels():
            self._send_json(400, False, '❌ 존재하지 않는 사이트입니다.')
            return
        if (not name or len(name) > MAX_SITE_NAME_LENGTH or not short or len(short) > MAX_SITE_SHORT_LENGTH
                or any(ch in name + short for ch in '\r\n\t')):
            self._send_json(400, False, f'❌ 사이트 이름은 {MAX_SITE_NAME_LENGTH}자, 짧은 표시는 {MAX_SITE_SHORT_LENGTH}자 이하로 줄바꿈 없이 입력해 주세요.')
            return
        set_site_label(site, name, short)
        log_msg(f"[API] 사이트 이름 변경: {site} → {name} ({short})")
        self._send_json(200, True, f"🏷️ 사이트 표시를 바꿨습니다: {name} ({short})")

    def _handle_category(self):
        """카테고리(에펨코리아 게시판·디시 갤러리) 추가·이름 변경·다시 확인·삭제 (관리자 암호 필요).
        추가한 카테고리는 수집기가 다음 주기에 열어 보고 수집할 수 있는 게시판이면 그다음 주기부터 수집"""
        params = self._body
        if not self._authorize(params.get('password', ''), '카테고리 관리'):
            return
        action = params.get('action')
        if action not in ('create', 'rename', 'recheck', 'delete'):
            self._send_json(400, False, '❌ 지원하지 않는 작업입니다.')
            return
        name = str(params.get('name') or '').strip()
        if (action == 'rename' and not name) or len(name) > MAX_CATEGORY_NAME_LENGTH or any(ch in name for ch in '\r\n\t'):
            self._send_json(400, False, f'❌ 카테고리 이름은 줄바꿈 없이 {MAX_CATEGORY_NAME_LENGTH}자 이하로 입력해 주세요.')
            return
        if action == 'create':
            raw = str(params.get('input') or '')[:MAX_CATEGORY_INPUT_LENGTH]
            key = board_key_from_input(raw)
            if key is None:
                self._send_json(400, False, '❌ 디시 갤러리 주소(예: https://gall.dcinside.com/board/lists/?id=car_new1)를 입력해 주세요. 에펨코리아는 수집하지 않습니다.')
                return
            if not site_enabled(board_site(key)):
                self._send_json(400, False, f'❌ {SITE_NAMES[board_site(key)]}는 수집하지 않도록 설정되어 게시판을 추가할 수 없습니다.')
                return
            try:
                add_category(key, name)
            except ValueError as ve:
                self._send_json(400, False, f'❌ {ve}')
                return
            log_msg(f"[API] 카테고리 추가: {key}{f' ({name})' if name else ''} → 다음 주기에 확인")
            self._send_data(200, {'success': True, 'key': key,
                                  'message': f"📂 '{name or key}' 카테고리를 추가했습니다. 다음 수집 주기(약 {CHECK_INTERVAL}초 뒤)에 게시판을 확인합니다."})
            return
        key = params.get('key')
        if not isinstance(key, str) or key not in category_names():
            self._send_json(400, False, '❌ 존재하지 않는 카테고리입니다.')
            return
        if action == 'rename':
            rename_category(key, name)
            log_msg(f"[API] 카테고리 이름 변경: {key} → {name}")
            self._send_json(200, True, f"✏️ 카테고리 이름을 '{name}'(으)로 바꿨습니다.")
        elif action == 'recheck':
            if not recheck_category(key):
                self._send_json(400, False, '❌ 확인에 실패한 카테고리만 다시 확인할 수 있습니다.')
                return
            log_msg(f"[API] 카테고리 다시 확인 요청: {key}")
            self._send_json(200, True, '🔄 다음 수집 주기에 게시판을 다시 확인합니다.')
        else:
            try:
                delete_category(key)
            except ValueError as ve:
                self._send_json(400, False, f'❌ {ve}')
                return
            log_msg(f"[API] 카테고리 삭제: {key}")
            self._send_json(200, True, '🗑️ 카테고리를 삭제했습니다.')

    def _handle_read(self):
        """화면에서 읽은 글 기록 (기기 간 공유). 읽음 표시는 민감 정보가 아니라 관리자 암호 없이 허용"""
        params = self._body
        ids = params.get('ids')
        if not isinstance(ids, list) or len(ids) > MAX_READ_IDS:
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        count = mark_posts_read(ids)
        log_msg(f"[API] 읽음 기록 {count}건", "DEBUG")
        self._send_data(200, {'success': True, 'count': count})

    def _handle_read_all(self):
        """'모두 읽음'(안 읽은 새 글)·'모두 확인'(새 댓글): 화면에 내려 준 ID 수(최대 500)와 상관없이 그 게시판·묶음·전체를 한 번에.
        until(화면이 받은 상태의 시각)까지 알던 것만 처리. 읽음 기록처럼 관리자 암호 없이 허용"""
        params = self._body
        kind = params.get('kind')
        group_id, folder_id = params.get('group'), params.get('folder')
        until = params.get('until')
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if (kind not in ('unread', 'comments') or not (group_id is None or type(group_id) is int)
                or not (folder_id is None or type(folder_id) is int)
                or not (until is None or (isinstance(until, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', until)))):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        count = mark_feed_read(kind, min(until or now, now), group_id, None if group_id is not None else folder_id)
        log_msg(f"[API] 모두 {'읽음' if kind == 'unread' else '확인'} {count}건", "DEBUG")
        self._send_data(200, {'success': True, 'count': count})

    def _handle_saved(self):
        """보관함에 담기·빼기 (기기 간 공유). 읽음 기록처럼 관리자 암호 없이 허용"""
        params = self._body
        post_id = params.get('id')
        saved = params.get('saved')
        if not isinstance(post_id, str) or not is_post_id(post_id) or not isinstance(saved, bool):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        if not set_post_saved(post_id, saved):
            self._send_json(404, False, '❌ 모은 글이 아닙니다.')
            return
        log_msg(f"[API] 보관함 {'담기' if saved else '빼기'}: {post_id}", "DEBUG")
        self._send_data(200, {'success': True, 'saved': saved})

    def _handle_toggle_alert(self):
        """게시판별 텔레그램 알림(전체·동영상·하루 요약)과 보관한 글 새 댓글 알림 켜기·끄기 (관리자 암호 필요)"""
        params = self._body
        group_id = params.get('group')
        alert_type = params.get('type')
        enabled = params.get('enabled') is True
        if not self._authorize(params.get('password', ''), '알림 토글'):
            return
        if alert_type == 'saved_comment':
            set_saved_comment_alert(enabled)
            log_msg(f"[API] 알림 설정 변경: 보관한 글 새 댓글 {'켜짐' if enabled else '꺼짐'}")
            self._send_json(200, True, f"⭐ 보관한 글의 새 댓글 알림이 {'켜짐' if enabled else '꺼짐'} 상태로 변경되었습니다.")
            return
        if alert_type == 'popular':
            # 인기 글 알림: 추천+댓글이 min 이상이 되면 알림 (0이면 끔)
            minimum = params.get('min')
            if type(minimum) is not int or not 0 <= minimum <= MAX_POPULAR_MIN or not isinstance(group_id, int):
                self._send_json(400, False, f'❌ 인기 글 기준은 0~{MAX_POPULAR_MIN:,} 사이 숫자로 입력해 주세요.')
                return
            name = set_group_popular(group_id, minimum)
            if name is None:
                self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
                return
            log_msg(f"[API] 알림 설정 변경: {name} 인기 글 알림 {f'추천+댓글 {minimum} 이상' if minimum else '꺼짐'}")
            self._send_json(200, True, f"🔥 '{name}' 게시판의 인기 글 알림을 "
                                       f"{f'추천+댓글 {minimum:,} 이상으로 정했습니다.' if minimum else '껐습니다.'}")
            return
        if alert_type not in ('alert', 'video_alert', 'digest') or not isinstance(group_id, int):
            self._send_json(400, False, '❌ 잘못된 요청입니다.')
            return
        name = set_group_alert(group_id, alert_type, enabled)
        if name is None:
            self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
            return
        status_str = "켜짐" if enabled else "꺼짐"
        type_str = {'video_alert': "동영상 알림", 'digest': "하루 요약"}.get(alert_type, "전체 알림")
        icon_str = {'video_alert': "🎬", 'digest': "📰"}.get(alert_type, "🔔")
        log_msg(f"[API] 알림 설정 변경: {name} {type_str} {status_str}")
        self._send_json(200, True, f"{icon_str} '{name}' 게시판의 {type_str}이 {status_str} 상태로 변경되었습니다.")

def _keep_warm():
    """NAS 메모리가 부족해 한동안 요청이 없으면 웹서버 쪽 메모리가 스왑으로 밀려나 첫 화면이 수 초 걸림.
    첫 화면과 같은 조회를 주기적으로 돌려 관련 코드와 DB 페이지를 메모리에 붙잡아 둠"""
    # 웹서버가 켜지자마자 한 번 돌려, 재시작 직후 첫 접속이 디스크에서 읽느라 느리지 않게 함
    while True:
        try:
            state = build_state()
            build_posts_page(1, False, unread_since=state['generated_at'])
        except Exception as e:
            log_msg(f"[API] 예열 조회 실패: {short_err(e)}", "DEBUG")
        time.sleep(WARMUP_INTERVAL_SECONDS)

def check_collector(alerted, watch_started=WATCH_STARTED):
    """수집기가 COLLECTOR_STALL_MINUTES 넘게 움직이지 않으면 한 번 알리고, 다시 움직이면 복구를 알림.
    알린 상태(멈춘 것으로 본 시각, 없으면 None)를 돌려줌"""
    status = runtime_status.snapshot()
    stalled = runtime_status.stalled_seconds(status, watch_started)
    last = (status.get('last_cycle') or {}).get('finished_at')
    if stalled >= COLLECTOR_STALL_MINUTES * 60:
        if alerted is None:
            log_msg(f"[감시] 수집기가 {stalled // 60:.0f}분째 진행 없음 → 알림", "WARN")
            send_telegram_message(
                f"⚠️ 수집기가 멈춘 것 같습니다\n\n{stalled // 60:.0f}분째 게시판 확인이 진행되지 않습니다."
                f"{f' (마지막 수집 완료 {last[11:16]})' if last else ''}\n\n"
                f"NAS에서 fmkorea-scraper 컨테이너를 확인해 주세요. 다시 동작하면 알려드립니다.")
            return status['now']
        return alerted
    if alerted is not None:
        minutes = (runtime_status._parse(status['now']) - runtime_status._parse(alerted)).total_seconds() // 60
        log_msg(f"[감시] 수집기 다시 동작 (알림 후 {minutes:.0f}분)")
        send_telegram_message(f"✅ 수집기가 다시 동작합니다. (멈춤 알림 후 {minutes:.0f}분)")
    return None

def _watch_collector():
    """따로 도는 웹서버가 수집기를 지켜봄 (수집기가 죽거나 크롬이 멈추면 수집기 스스로는 알릴 수 없음)"""
    alerted = None
    while True:
        time.sleep(WATCH_INTERVAL_SECONDS)
        try:
            alerted = check_collector(alerted)
        except Exception as e:
            log_msg(f"[감시] 수집기 상태 확인 실패: {short_err(e)}", "DEBUG")

def run_api_server():
    server_address = ('', WEB_PORT)
    httpd = ThreadedHTTPServer(server_address, KeywordAPIServer)
    threading.Thread(target=_keep_warm, daemon=True).start()
    apt_trades.start()
    if COLLECTOR_STALL_MINUTES:
        threading.Thread(target=_watch_collector, daemon=True).start()
    log_msg(f"[API] 웹서버 시작 (포트 {WEB_PORT})")
    httpd.serve_forever()

if __name__ == '__main__':
    # 웹서버만 따로 실행 (NAS에서는 수집기와 다른 컨테이너, docker-compose.yml의 fmkorea-web).
    # 수집기가 무거운 작업을 해도 같은 프로세스가 아니므로 응답이 붙잡히지 않음
    init_db()
    run_api_server()
