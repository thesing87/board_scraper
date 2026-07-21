import os
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

from config import (
    log_msg,
    ADMIN_PASSWORD,
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

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """요청마다 새로운 스레드를 독립 할당하여 동기 블로킹 및 접속 지연을 차단"""
    daemon_threads = True

class KeywordAPIServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        global all_keywords_data
        pure_path = self.path.split('?')[0]
        log_msg(f"[API 서버] GET 요청 수신 -> Path: {pure_path}", "DEBUG")
        
        if pure_path == '/api/toggle-alert':
            try:
                query_params = parse_qs(urlparse(self.path).query)
                board = query_params.get('board', [''])[0].strip()
                enabled_str = query_params.get('enabled', ['true'])[0].strip()
                enabled = enabled_str.lower() == 'true'
                password = query_params.get('password', [''])[0].strip()
                
                log_msg(f"[API 서버] 알림 토글 API 호출됨 (Target Board: {board}, Enabled: {enabled})", "INFO")
                
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                
                if password != ADMIN_PASSWORD:
                    log_msg("[API 서버] ❌ 비밀번호 불일치로 알림 토글 작업이 거부되었습니다.", "WARN")
                    response_data = {'success': False, 'message': '❌ 인증 비밀번호가 일치하지 않습니다.'}
                    self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
                    return
                
                if board not in BOARD_MAP:
                    log_msg(f"[API 서버] ❌ 유효하지 않은 게시판 인자 전달됨: {board}", "WARN")
                    response_data = {'success': False, 'message': '❌ 존재하지 않는 게시판입니다.'}
                    self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
                    return
                
                with data_lock:
                    current_board_config = load_board_config()
                    current_board_config[board]['alert'] = enabled
                    save_board_config(current_board_config)
                    generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)
                
                status_str = "켜짐" if enabled else "꺼짐"
                msg = f"🔔 {BOARD_MAP[board]} 게시판의 알림이 {status_str} 상태로 변경되었습니다."
                log_msg(f"[API 서버] {msg}", "INFO")
                response_data = {'success': True, 'message': msg}
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                log_msg(f"⚠️ [API 서버] 알림 토글 API 내부 크리티컬 에러 발생: {e}", "ERROR")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
            return

        if pure_path == '/' or pure_path == '/index.html' or self.path.startswith('/?'):
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
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                log_msg("[API 서버] ℹ️ 전송 중 브라우저 연결 끊김 감지 (사용자 새로고침 혹은 창 닫음)", "INFO")
                return
            except Exception as e:
                log_msg(f"⚠️ [API 서버] HTML 템플릿 반환 실패: {e}", "ERROR")
                try:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(f"❌ HTML 파일을 찾을 수 없습니다: {e}".encode('utf-8'))
                except Exception:
                    pass
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global all_keywords_data
        pure_path = self.path.split('?')[0]
        log_msg(f"[API 서버] POST 요청 수신 -> Path: {pure_path}", "DEBUG")
        
        if pure_path == '/api/keyword':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length).decode('utf-8')
                params = json.loads(post_data)
                action = params.get('action')
                keyword = params.get('keyword', '').strip()
                password = params.get('password', '').strip()
                board = params.get('board', 'car').strip()
                
                log_msg(f"[API 서버] 키워드 제어 요청 수신 (Action: {action}, Board: {board}, Keyword: {keyword})", "INFO")
                
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                
                if password != ADMIN_PASSWORD:
                    log_msg("[API 서버] ❌ 비밀번호 불일치로 키워드 매니징 작업이 거부되었습니다.", "WARN")
                    response_data = {'success': False, 'message': '❌ 인증 비밀번호가 일치하지 않습니다.'}
                    self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
                    return
                
                if not keyword: 
                    log_msg("[API 서버] 공백 키워드 수신으로 요청을 무시합니다.", "WARN")
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
                            
                    elif action == 'delete':
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

                response_data = {'success': True, 'message': msg}
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                log_msg(f"⚠️ [API 서버] 키워드 포스트 제어 에러 발생: {e}", "ERROR")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
            return
            
        self.send_response(404)
        self.end_headers()

def run_api_server():
    server_address = ('', 8081)
    httpd = ThreadedHTTPServer(server_address, KeywordAPIServer)
    log_msg("🌐 [API 서버] 비블로킹 멀티스레드 제어 웹서버가 8081포트에서 정식 가동되었습니다.", "INFO")
    httpd.serve_forever()
