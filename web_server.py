import os
import json
import hmac
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from config import (
    log_msg,
    ADMIN_PASSWORD,
    INSECURE_ADMIN_PASSWORDS,
    BOARD_MAP,
    HTML_OUTPUT_FILE,
    all_keywords_data,
    data_lock
)
from storage import (
    load_board_config,
    save_board_config,
    load_keywords_from_file,
    save_keywords_to_file,
    save_backup_data
)
from ui_builder import generate_multiboard_html

MAX_BODY_BYTES = 10 * 1024
MAX_KEYWORD_LENGTH = 50

# 비밀번호 무차별 대입 방지: IP별로 일정 시간 내 실패 횟수를 넘기면 잠금
AUTH_MAX_FAILURES = 5
AUTH_WINDOW_SECONDS = 600
AUTH_LOCKOUT_SECONDS = 600
auth_failures = {}
auth_lock = threading.Lock()

ADMIN_API_ENABLED = ADMIN_PASSWORD not in INSECURE_ADMIN_PASSWORDS
if not ADMIN_API_ENABLED:
    log_msg("⚠️ ADMIN_PASSWORD가 설정되지 않았거나 기본 예시값입니다. 키워드/알림 관리 API를 비활성화합니다.", "WARN")

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
            log_msg(f"[API 서버] 🚫 인증 실패 누적으로 {ip}를 {AUTH_LOCKOUT_SECONDS}초간 차단합니다.", "WARN")

def _clear_auth_failures(ip):
    with auth_lock:
        auth_failures.pop(ip, None)

class KeywordAPIServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return

    def _send_json(self, status, success, message):
        body = json.dumps({'success': success, 'message': message}, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

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
            log_msg(f"[API 서버] 🚫 차단된 IP의 {action_name} 요청 거부: {ip}", "WARN")
            self._send_json(429, False, '❌ 인증 실패가 반복되어 잠시 차단되었습니다. 10분 후 다시 시도해 주세요.')
            return False
        if not isinstance(password, str) or not hmac.compare_digest(password.strip().encode('utf-8'), ADMIN_PASSWORD.encode('utf-8')):
            _record_auth_failure(ip)
            log_msg(f"[API 서버] ❌ 비밀번호 불일치로 {action_name} 작업이 거부되었습니다. (IP: {ip})", "WARN")
            self._send_json(401, False, '❌ 인증 비밀번호가 일치하지 않습니다.')
            return False
        _clear_auth_failures(ip)
        return True

    def do_GET(self):
        pure_path = self.path.split('?')[0]
        log_msg(f"[API 서버] GET 요청 수신 -> Path: {pure_path}", "DEBUG")

        if pure_path == '/' or pure_path == '/index.html':
            try:
                log_msg("[API 서버] 대시보드 메인 HTML 페이지 렌더링 응답 개시", "DEBUG")

                if not os.path.exists(HTML_OUTPUT_FILE):
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write("⏳ 대시보드 파일 초기 생성 중입니다. 잠시 후 새로고침 해주세요.".encode('utf-8'))
                    return

                with open(HTML_OUTPUT_FILE, 'rb') as f:
                    content = f.read()

                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('X-Frame-Options', 'DENY')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                log_msg("[API 서버] ℹ️ 전송 중 브라우저 연결 끊김 감지 (사용자 새로고침 혹은 창 닫음)", "INFO")
                return
            except Exception as e:
                log_msg(f"⚠️ [API 서버] HTML 템플릿 반환 실패: {e}", "ERROR")
                try:
                    self.send_response(500)
                    self.end_headers()
                except Exception:
                    pass
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        pure_path = self.path.split('?')[0]
        log_msg(f"[API 서버] POST 요청 수신 -> Path: {pure_path}", "DEBUG")

        if pure_path == '/api/toggle-alert':
            self._handle_toggle_alert()
        elif pure_path == '/api/keyword':
            self._handle_keyword()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_toggle_alert(self):
        try:
            params = self._read_json_body()
            board = str(params.get('board', '')).strip()
            alert_type = str(params.get('type', 'alert')).strip()
            if alert_type not in ['alert', 'video_alert']:
                alert_type = 'alert'
            enabled = params.get('enabled') is True

            log_msg(f"[API 서버] 알림 토글 API 호출됨 (Target Board: {board}, Type: {alert_type}, Enabled: {enabled})", "INFO")

            if not self._authorize(params.get('password', ''), '알림 토글'):
                return

            if board not in BOARD_MAP:
                log_msg(f"[API 서버] ❌ 유효하지 않은 게시판 인자 전달됨: {board}", "WARN")
                self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
                return

            with data_lock:
                current_board_config = load_board_config()
                if board not in current_board_config:
                    current_board_config[board] = {"alert": True, "video_alert": True}
                current_board_config[board][alert_type] = enabled
                save_board_config(current_board_config)
                generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)

            status_str = "켜짐" if enabled else "꺼짐"
            type_str = "동영상 알림" if alert_type == "video_alert" else "일반 알림"
            icon_str = "🎬" if alert_type == "video_alert" else "🔔"
            msg = f"{icon_str} {BOARD_MAP[board]} 게시판의 {type_str}이 {status_str} 상태로 변경되었습니다."
            log_msg(f"[API 서버] {msg}", "INFO")
            self._send_json(200, True, msg)
        except Exception as e:
            log_msg(f"⚠️ [API 서버] 알림 토글 API 내부 크리티컬 에러 발생: {e}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

    def _handle_keyword(self):
        try:
            params = self._read_json_body()
            action = params.get('action')
            keyword = str(params.get('keyword', '')).strip()
            board = str(params.get('board', 'car')).strip()

            log_msg(f"[API 서버] 키워드 제어 요청 수신 (Action: {action}, Board: {board}, Keyword: {keyword[:MAX_KEYWORD_LENGTH]})", "INFO")

            if not self._authorize(params.get('password', ''), '키워드 매니징'):
                return

            if action not in ('add', 'delete'):
                self._send_json(400, False, '❌ 지원하지 않는 작업입니다.')
                return
            if board not in BOARD_MAP:
                log_msg(f"[API 서버] ❌ 유효하지 않은 게시판 인자 전달됨: {board}", "WARN")
                self._send_json(400, False, '❌ 존재하지 않는 게시판입니다.')
                return
            if not keyword:
                log_msg("[API 서버] 공백 키워드 수신으로 요청을 무시합니다.", "WARN")
                self._send_json(400, False, '❌ 키워드를 입력해 주세요.')
                return
            if len(keyword) > MAX_KEYWORD_LENGTH or any(ch in keyword for ch in '\r\n\t'):
                self._send_json(400, False, f'❌ 키워드는 줄바꿈 없이 {MAX_KEYWORD_LENGTH}자 이하로 입력해 주세요.')
                return

            with data_lock:
                current_config = load_keywords_from_file()
                if board not in current_config:
                    current_config[board] = []

                combined_key = f"{board}::{keyword}"

                if action == 'add':
                    if keyword in current_config[board]:
                        msg = '이미 존재하는 키워드입니다.'
                        log_msg(f"[API 서버] 키워드 중복 추가 생략 처리: {combined_key}", "WARN")
                    else:
                        current_config[board].append(keyword)
                        save_keywords_to_file(current_config)
                        if combined_key not in all_keywords_data:
                            all_keywords_data[combined_key] = []
                        msg = f'🎯 {BOARD_MAP.get(board, board)} -> [{keyword}] 추가되었습니다.'
                        log_msg(f"[API 서버] 신규 키워드 등록 완료: {combined_key}", "INFO")

                else:
                    if keyword in current_config[board]:
                        current_config[board].remove(keyword)
                        save_keywords_to_file(current_config)
                        if combined_key in all_keywords_data:
                            del all_keywords_data[combined_key]
                        msg = f'🗑️ {BOARD_MAP.get(board, board)} -> [{keyword}] 삭제되었습니다.'
                        log_msg(f"[API 서버] 키워드 영구 제거 완료: {combined_key}", "INFO")
                    else:
                        msg = '존재하지 않는 키워드입니다.'
                        log_msg(f"[API 서버] 삭제 거부 (존재하지 않는 키워드): {combined_key}", "WARN")

                generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)
                save_backup_data(all_keywords_data)

            self._send_json(200, True, msg)
        except Exception as e:
            log_msg(f"⚠️ [API 서버] 키워드 포스트 제어 에러 발생: {e}", "ERROR")
            try:
                self._send_json(500, False, '❌ 요청 처리 중 서버 오류가 발생했습니다.')
            except Exception:
                pass

def run_api_server():
    server_address = ('', 8081)
    httpd = ThreadedHTTPServer(server_address, KeywordAPIServer)
    log_msg("🌐 [API 서버] 비블로킹 멀티스레드 제어 웹서버가 8081포트에서 정식 가동되었습니다.", "INFO")
    httpd.serve_forever()
