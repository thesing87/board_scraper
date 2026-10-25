import os
import json
import hmac
import time
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

from config import (
    log_msg,
    short_err,
    ADMIN_PASSWORD,
    INSECURE_ADMIN_PASSWORDS,
    BOARD_MAP,
    LIST_PAGE_SIZE
)
from storage import (
    set_board_alert,
    load_board_config,
    query_all_posts,
    recent_post_ids,
    mark_posts_read,
    locate_post,
    list_groups,
    feed_summary,
    save_group,
    delete_group
)

MAX_BODY_BYTES = 10 * 1024
MAX_READ_IDS = 500
MAX_QUERY_LENGTH = 50
MAX_GROUP_NAME_LENGTH = 30
MAX_GROUP_MEMBERS = 50
MAX_KEYWORD_LENGTH = 50
POSTS_PER_PAGE = 10
# 탭의 '안 읽은 새 글' 표시 계산에 쓰는 키워드별 최근 글 범위
NEW_POSTS_WINDOW = 100

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
STATIC_FILES = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
    '/app.css': ('app.css', 'text/css; charset=utf-8'),
}

# 본문 HTML은 저장 시 정화되지만, 스크립트는 같은 출처의 app.js만 실행되도록 브라우저 차원에서 한 번 더 제한
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src * data: blob:; media-src * data: blob:; frame-src https: http:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

# 비밀번호 무차별 대입 방지: IP별로 일정 시간 내 실패 횟수를 넘기면 잠금
AUTH_MAX_FAILURES = 5
AUTH_WINDOW_SECONDS = 600
AUTH_LOCKOUT_SECONDS = 600
auth_failures = {}
auth_lock = threading.Lock()

ADMIN_API_ENABLED = ADMIN_PASSWORD not in INSECURE_ADMIN_PASSWORDS
if not ADMIN_API_ENABLED:
    log_msg("[API] ADMIN_PASSWORD 미설정/기본값 - 관리 기능 비활성화", "WARN")

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """요청마다 새로운 스레드를 독립 할당하여 동기 블로킹 및 접속 지연을 차단"""
    daemon_threads = True

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
    """대시보드 초기 화면 구성용 데이터: 게시판 목록, 통합 피드 요약, 카테고리(에펨코리아 게시판), 알림 설정"""
    groups = list_groups(NEW_POSTS_WINDOW)
    for group in groups:
        for member in group['members']:
            member['board_name'] = BOARD_MAP.get(member['board'], member['board'])
    return {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'posts_per_page': POSTS_PER_PAGE,
        'boards': [{'key': k, 'name': v} for k, v in BOARD_MAP.items()],
        'board_config': load_board_config(),
        # 모든 게시판을 합친 통합 피드 요약 (같은 글은 한 번만 셈)
        'all': feed_summary(NEW_POSTS_WINDOW),
        # 사용자가 만든 게시판 (등록한 키워드의 글을 중복 없이 한 피드로)
        'groups': groups
    }

def build_posts_page(page, video_only, query='', group_id=None):
    """통합 피드(group_id 없음)·게시판·검색: 여러 키워드의 글을 중복 없이"""
    total, _ = query_all_posts(0, 0, video_only, query, group_id)
    total_pages = max(1, -(-total // POSTS_PER_PAGE))
    page = min(max(1, page), total_pages)
    _, posts = query_all_posts((page - 1) * POSTS_PER_PAGE, POSTS_PER_PAGE, video_only, query, group_id)
    for post in posts:
        for link in post.get('keywords', []):
            link['board_name'] = BOARD_MAP.get(link['board'], link['board'])
    # 메인 루프가 매 주기 목록의 댓글 수로 변화를 감시하는 최근 글 표시 (필터와 무관하게 키워드 전체 기준)
    syncing_ids = recent_post_ids(LIST_PAGE_SIZE)
    for post in posts:
        post['has_video'] = len(post.get('videos', [])) > 0
        post['is_syncing'] = post['id'] in syncing_ids
        post.pop('images', None)
        post.pop('list_comment_count', None)
    return {'page': page, 'total_pages': total_pages, 'total': total, 'posts': posts}

class KeywordAPIServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return

    def _send_body(self, status, body, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_data(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self._send_body(status, body, 'application/json; charset=utf-8')

    def _send_json(self, status, success, message):
        self._send_data(status, {'success': success, 'message': message})

    def _read_json_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            raise ValueError("요청 본문 크기가 올바르지 않습니다.")
        params = json.loads(self.rfile.read(content_length).decode('utf-8'))
        if not isinstance(params, dict):
            raise ValueError("요청 본문 형식이 올바르지 않습니다.")
        return params

    def _authorize(self, password, action_name):
        """인증 성공 시 True, 실패 시 응답을 보낸 뒤 False 반환"""
        ip = self.client_address[0]
        if not ADMIN_API_ENABLED:
            self._send_json(403, False, '❌ 서버에 ADMIN_PASSWORD가 설정되지 않아 관리 기능이 비활성화되어 있습니다.')
            return False
        if _is_locked_out(ip):
            log_msg(f"[API] 차단 중인 IP 요청 거부: {ip} ({action_name})", "WARN")
            self._send_json(429, False, '❌ 인증 실패가 반복되어 잠시 차단되었습니다. 10분 후 다시 시도해 주세요.')
            return False
        if not isinstance(password, str) or not hmac.compare_digest(password.strip().encode('utf-8'), ADMIN_PASSWORD.encode('utf-8')):
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
        log_msg(f"[API] GET {pure_path}", "DEBUG")

        try:
            if pure_path in STATIC_FILES:
                self._serve_static(*STATIC_FILES[pure_path])
            elif pure_path == '/api/state':
                self._send_data(200, build_state())
            elif pure_path == '/api/posts':
                try:
                    page = int(query.get('page', ['1'])[0])
                except ValueError:
                    page = 1
                video_only = query.get('video_only', ['0'])[0] in ('1', 'true')
                search = query.get('q', [''])[0].strip()[:MAX_QUERY_LENGTH]
                group_param = query.get('group', [''])[0]
                group_id = int(group_param) if group_param.isdigit() and not search else None
                self._send_data(200, build_posts_page(page, video_only, search, group_id))
            elif pure_path == '/api/locate':
                post_id = query.get('id', [''])[0]
                location = locate_post(post_id) if post_id.isdigit() else None
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
        with open(os.path.join(STATIC_DIR, filename), 'rb') as f:
            content = f.read()
        extra = {'Content-Security-Policy': CONTENT_SECURITY_POLICY} if filename.endswith('.html') else None
        self._send_body(200, content, content_type, extra)

    def do_POST(self):
        pure_path = self.path.split('?')[0]
        log_msg(f"[API] POST {pure_path}", "DEBUG")

        if pure_path == '/api/toggle-alert':
            self._handle_toggle_alert()
        elif pure_path == '/api/read':
            self._handle_read()
        elif pure_path == '/api/group':
            self._handle_group()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_group(self):
        """게시판 만들기·수정·삭제 (관리자 암호 필요). 키워드는 게시판에 등록하는 방식으로만 관리"""
        try:
            params = self._read_json_body()
            if not self._authorize(params.get('password', ''), '게시판 관리'):
                return
            action = params.get('action')
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
            members = [{'board': m['board'].strip(), 'keyword': m['keyword'].strip()} for m in members]
            for m in members:
                if m['board'] not in BOARD_MAP:
                    self._send_json(400, False, '❌ 존재하지 않는 카테고리입니다.')
                    return
                if not m['keyword'] or len(m['keyword']) > MAX_KEYWORD_LENGTH or any(ch in m['keyword'] for ch in '\r\n\t'):
                    self._send_json(400, False, f'❌ 키워드는 줄바꿈 없이 {MAX_KEYWORD_LENGTH}자 이하로 입력해 주세요.')
                    return
            group_id = params.get('id') if action == 'update' else None
            if action == 'update' and not isinstance(group_id, int):
                self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
                return
            try:
                saved_id, dropped = save_group(group_id, name, members)
            except ValueError as ve:
                self._send_json(400, False, f'❌ {ve}')
                return
            log_msg(f"[API] 게시판 {'추가' if action == 'create' else '수정'}: {name} (키워드 {len(members)}개){self._dropped_text(dropped)}")
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
        return f" / 수집 중단 키워드: {', '.join(f'{BOARD_MAP.get(b, b)}/{k}' for b, k in dropped)}" if dropped else ''

    def _handle_read(self):
        """화면에서 읽은 글 기록 (기기 간 공유). 읽음 표시는 민감 정보가 아니라 관리자 암호 없이 허용"""
        try:
            params = self._read_json_body()
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

    def _handle_toggle_alert(self):
        try:
            params = self._read_json_body()
            board = str(params.get('board', '')).strip()
            alert_type = str(params.get('type', 'alert')).strip()
            if alert_type not in ['alert', 'video_alert']:
                alert_type = 'alert'
            enabled = params.get('enabled') is True


            if not self._authorize(params.get('password', ''), '알림 토글'):
                return

            if board not in BOARD_MAP:
                log_msg(f"[API] 잘못된 게시판 요청: {board}", "WARN")
                self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
                return

            set_board_alert(board, alert_type, enabled)

            status_str = "켜짐" if enabled else "꺼짐"
            type_str = "동영상 알림" if alert_type == "video_alert" else "일반 알림"
            icon_str = "🎬" if alert_type == "video_alert" else "🔔"
            msg = f"{icon_str} {BOARD_MAP[board]} 게시판의 {type_str}이 {status_str} 상태로 변경되었습니다."
            log_msg(f"[API] 알림 설정 변경: {BOARD_MAP[board]} {type_str} {status_str}")
            self._send_json(200, True, msg)
        except Exception as e:
            log_msg(f"[API] 알림 설정 처리 오류: {short_err(e)}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

def run_api_server():
    server_address = ('', 8081)
    httpd = ThreadedHTTPServer(server_address, KeywordAPIServer)
    log_msg("[API] 웹서버 시작 (포트 8081)")
    httpd.serve_forever()
