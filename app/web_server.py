import os
import re
import json
import gzip
import hmac
import hashlib
import time
import threading
import ipaddress
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

from config import (
    log_msg,
    short_err,
    ADMIN_PASSWORD,
    INSECURE_ADMIN_PASSWORDS,
    TRUST_PROXY_HEADERS,
    CHECK_INTERVAL,
    WEB_PORT,
    LIST_PAGE_SIZE,
    COLLECTOR_STALL_MINUTES,
    DIGEST_HOUR
)
import runtime_status
from notifier import send_telegram_message
from sites import is_post_id, DC_BOARD_PREFIX, DC_GALLERY_RE
from images import image_file, IMAGE_URL_PREFIX
from storage import (
    init_db,
    set_group_alert,
    set_group_popular,
    saved_comment_alert,
    set_saved_comment_alert,
    query_all_posts,
    query_media,
    recent_post_ids,
    mark_posts_read,
    set_post_saved,
    locate_post,
    list_groups,
    feed_summary,
    query_posts_by_ids,
    dashboard_summary,
    stats_summary,
    save_group,
    delete_group,
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
    arrange_group,
    card_benefits,
    add_card_benefit,
    update_card_benefit,
    delete_card_benefit,
    add_card_keyword,
    delete_card_keyword
)

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
# 에펨코리아 게시판 mid (글 주소 'fmkorea.com/12345'와 헷갈리지 않게 숫자만인 값은 제외)
BOARD_KEY_RE = re.compile(r'(?![0-9]+$)[a-z0-9_]{1,40}')
POSTS_PER_PAGE = 10
# 인기순으로 볼 수 있는 기간(일). 없으면 전체 기간
POPULAR_DAYS = ('1', '7', '30')
# 검색에서 고를 수 있는 기간(일): 최근 그 기간에 수집한 글만. 없으면 전체 기간
SEARCH_DAYS = ('1', '7', '30', '90')
# 통계 화면에서 고를 수 있는 기간(일)
STATS_DAYS = ('7', '30', '90')
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
    '/app.css': ('app.css', 'text/css; charset=utf-8'),
    # 전기차 vs 내연기관 유지비 계산기
    '/ev/': ('ev.html', 'text/html; charset=utf-8'),
    '/ev.js': ('ev.js', 'application/javascript; charset=utf-8'),
    # 수집 통계
    '/stats/': ('stats.html', 'text/html; charset=utf-8'),
    '/stats.js': ('stats.js', 'application/javascript; charset=utf-8'),
    '/stats.css': ('stats.css', 'text/css; charset=utf-8'),
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
    """관리 화면에 입력한 게시판 주소나 이름에서 카테고리 키를 뽑음. 알아볼 수 없으면 None
    - 에펨코리아: 'hotdeal', 'https://www.fmkorea.com/hotdeal', 'fmkorea.com/index.php?mid=hotdeal&page=2' → 'hotdeal'
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
        if host != 'fmkorea.com' and not host.endswith('.fmkorea.com'):
            return None
        text = parse_qs(url.query).get('mid', [''])[0]
        if not text:
            segments = [seg for seg in url.path.split('/') if seg]
            text = segments[0] if segments and segments[0] != 'index.php' else ''
    text = text.lower()
    return text if BOARD_KEY_RE.fullmatch(text) else None

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
            elif pure_path in ('/board', '/ev', '/card', '/stats'):
                # 끝 슬래시 없이 들어오면 붙여서 (페이지 안의 상대 주소가 맞도록)
                self._send_body(301, b'', 'text/plain; charset=utf-8', {'Location': pure_path + '/'})
            elif pure_path in ('/index.html/board', '/index.html/board/'):
                # DDNS_URL에 index.html이 붙어 있을 때 보낸 예전 알림 링크 (#post-ID는 브라우저가 그대로 넘겨 줌)
                self._send_body(301, b'', 'text/plain; charset=utf-8', {'Location': '/board/'})
            elif pure_path == '/api/dashboard':
                self._send_data(200, {**dashboard_summary(), 'check_interval': CHECK_INTERVAL,
                                      'collector': runtime_status.snapshot().get('last_cycle'),
                                      'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            elif pure_path == '/api/stats':
                # 통계 화면: 최근 7·30·90일 동안 수집한 글 수 (날짜·시간대·게시판·키워드별). group이 있으면 그 게시판만
                days = query.get('days', [''])[0]
                group_param = query.get('group', [''])[0]
                stats = stats_summary(int(days) if days in STATS_DAYS else 30, int(group_param) if group_param.isdigit() else None)
                names = category_names()
                for kw in stats['keywords']:
                    kw['board_name'] = names.get(kw['board'], kw['board'])
                self._send_data(200, stats)
            elif pure_path.startswith(IMAGE_URL_PREFIX):
                self._serve_image(pure_path[len(IMAGE_URL_PREFIX):])
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

    POST_HANDLERS = {
        '/api/toggle-alert': '_handle_toggle_alert',
        '/api/read': '_handle_read',
        '/api/saved': '_handle_saved',
        '/api/group': '_handle_group',
        '/api/folder': '_handle_folder',
        '/api/category': '_handle_category',
        '/api/site': '_handle_site',
        '/api/login': '_handle_login',
        '/api/card': '_handle_card',
    }

    def do_POST(self):
        pure_path = self.path.split('?')[0]
        log_msg(f"[API] POST {pure_path} ({client_ip(self.client_address[0], self.headers)})", "DEBUG")
        handler = self.POST_HANDLERS.get(pure_path)
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
        getattr(self, handler)()

    def _handle_group(self):
        """게시판 만들기·수정·삭제 (관리자 암호 필요). 키워드는 게시판에 등록하는 방식으로만 관리"""
        try:
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
            for m in members:
                if m['board'] not in names:
                    self._send_json(400, False, '❌ 존재하지 않는 카테고리입니다.')
                    return
                if not m['keyword'] or len(m['keyword']) > MAX_KEYWORD_LENGTH or any(ch in m['keyword'] for ch in '\r\n\t'):
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
                saved_id, dropped = save_group(group_id, name, members, merge_ids, folder_id)
            except ValueError as ve:
                self._send_json(400, False, f'❌ {ve}')
                return
            merged = f" / 게시판 {len(merge_ids)}개 합침" if merge_ids else ''
            log_msg(f"[API] 게시판 {'추가' if action == 'create' else '수정'}: {name} (키워드 {len(members)}개){merged}{self._dropped_text(dropped)}")
            self._send_data(200, {'success': True, 'id': saved_id,
                                  'message': f"📚 '{name}' 게시판을 {'만들었' if action == 'create' else '수정했'}습니다."})
        except Exception as e:
            log_msg(f"[API] 게시판 처리 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    @staticmethod
    def _dropped_text(dropped):
        if not dropped:
            return ''
        names = category_names()
        return f" / 수집 중단 키워드: {', '.join(f'{names.get(b, b)}/{k}' for b, k in dropped)}"

    def _handle_folder(self):
        """묶음 만들기·이름 바꾸기·삭제·순서 (관리자 암호 필요)"""
        try:
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
        except Exception as e:
            log_msg(f"[API] 묶음 처리 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    def _handle_login(self):
        """관리자 로그인: 암호가 맞으면 로그인 키를 돌려줌 (화면은 이 키를 기억해 관리 버튼을 보이고 관리 요청에 씀).
        틀린 암호는 다른 관리 요청과 같이 실패 횟수에 세어 잠금"""
        try:
            if not self._authorize(self._body.get('password', ''), '관리자 로그인'):
                return
            log_msg(f"[API] 관리자 로그인: {client_ip(self.client_address[0], self.headers)}")
            self._send_data(200, {'success': True, 'message': '로그인했습니다.', 'token': ADMIN_TOKEN})
        except Exception as e:
            log_msg(f"[API] 로그인 처리 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

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

    def _handle_card(self):
        """카드 혜택 조회·등록·수정·삭제. 소비 내역이라 조회까지 모두 로그인 필요"""
        try:
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
        except Exception as e:
            log_msg(f"[API] 카드 혜택 처리 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    def _handle_site(self):
        """사이트 이름·짧은 표시 바꾸기 (관리자 암호 필요). 화면의 사이트 제목·FM·DC 표시와 텔레그램 알림에 쓰임"""
        try:
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
        except Exception as e:
            log_msg(f"[API] 사이트 이름 처리 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    def _handle_category(self):
        """카테고리(에펨코리아 게시판·디시 갤러리) 추가·이름 변경·다시 확인·삭제 (관리자 암호 필요).
        추가한 카테고리는 수집기가 다음 주기에 열어 보고 수집할 수 있는 게시판이면 그다음 주기부터 수집"""
        try:
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
                    self._send_json(400, False, '❌ 에펨코리아 게시판 주소(예: https://www.fmkorea.com/hotdeal)·영문 이름(mid)이나 디시 갤러리 주소(예: https://gall.dcinside.com/board/lists/?id=car_new1)를 입력해 주세요.')
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
        except Exception as e:
            log_msg(f"[API] 카테고리 처리 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    def _handle_read(self):
        """화면에서 읽은 글 기록 (기기 간 공유). 읽음 표시는 민감 정보가 아니라 관리자 암호 없이 허용"""
        try:
            params = self._body
            ids = params.get('ids')
            if not isinstance(ids, list) or len(ids) > MAX_READ_IDS:
                self._send_json(400, False, '❌ 잘못된 요청입니다.')
                return
            count = mark_posts_read(ids)
            log_msg(f"[API] 읽음 기록 {count}건", "DEBUG")
            self._send_data(200, {'success': True, 'count': count})
        except Exception as e:
            log_msg(f"[API] 읽음 기록 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    def _handle_saved(self):
        """보관함에 담기·빼기 (기기 간 공유). 읽음 기록처럼 관리자 암호 없이 허용"""
        try:
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
        except Exception as e:
            log_msg(f"[API] 보관함 처리 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    def _handle_toggle_alert(self):
        """게시판별 텔레그램 알림(전체·동영상·하루 요약)과 보관한 글 새 댓글 알림 켜기·끄기 (관리자 암호 필요)"""
        try:
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
        except Exception as e:
            log_msg(f"[API] 알림 설정 처리 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

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
    if COLLECTOR_STALL_MINUTES:
        threading.Thread(target=_watch_collector, daemon=True).start()
    log_msg(f"[API] 웹서버 시작 (포트 {WEB_PORT})")
    httpd.serve_forever()

if __name__ == '__main__':
    # 웹서버만 따로 실행 (NAS에서는 수집기와 다른 컨테이너, docker-compose.yml의 fmkorea-web).
    # 수집기가 무거운 작업을 해도 같은 프로세스가 아니므로 응답이 붙잡히지 않음
    init_db()
    run_api_server()
