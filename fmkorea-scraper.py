from selenium.webdriver import Chrome
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import random
import re
import os
import platform
import json
import requests
from urllib.parse import quote, urlparse, parse_qs
from datetime import datetime
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import threading
from dotenv import load_dotenv

load_dotenv()

try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# ==========================================
# 0. 커스텀 로그 함수 정의
# ==========================================
def log_msg(message, level="INFO"):
    """모든 로그에 24시간 표기 방식의 현재 시간을 추가하여 출력하는 전역 로그 함수"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] [{level}] {message}")

# ==========================================
# 1. 게시판 정의 및 환경변수 로드
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

# ==========================================
# 2. 파일 I/O 헬퍼 함수
# ==========================================
def load_keywords_from_file():
    log_msg(f"키워드 파일 로드 시도: {KEYWORDS_FILE}", "DEBUG")
    if not os.path.exists(KEYWORDS_FILE):
        log_msg("키워드 설정 파일이 존재하지 않아 환경변수 기반으로 신규 생성을 진행합니다.", "INFO")
        initial_config = {}
        for board in BOARD_MAP.keys():
            env_str = os.environ.get(f'KEYWORDS_{board.upper()}', '')
            if board == 'car' and not env_str:
                env_str = os.environ.get('KEYWORDS', '')
            initial_config[board] = [k.strip() for k in env_str.split(',') if k.strip()]
        
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(initial_config, f, ensure_ascii=False, indent=4)
        log_msg("초기 키워드 설정 파일 생성이 완료되었습니다.", "INFO")
        return initial_config
    
    try:
        with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            log_msg(f"키워드 설정 로드 성공 (등록된 게시판 데이터 세트: {len(data)})", "DEBUG")
            return data
    except Exception as e:
        log_msg(f"⚠️ 키워드 파일 로드 중 오류 발생: {e}", "ERROR")
        return {board: [] for board in BOARD_MAP.keys()}

def save_keywords_to_file(config_data):
    log_msg("키워드 파일 디스크 저장을 시도합니다.", "DEBUG")
    try:
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        log_msg("키워드 설정 데이터 변경사항이 성공적으로 저장되었습니다.", "INFO")
        return True
    except Exception as e:
        log_msg(f"⚠️ 키워드 파일 저장 중 오류 발생: {e}", "ERROR")
        return False

def load_board_config():
    log_msg(f"게시판 알림 설정 파일 로드 시도: {BOARD_CONFIG_FILE}", "DEBUG")
    if not os.path.exists(BOARD_CONFIG_FILE):
        log_msg("게시판 알림 설정 파일이 존재하지 않아 초기화를 진행합니다.", "INFO")
        initial_config = {board: {"alert": True} for board in BOARD_MAP.keys()}
        with open(BOARD_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(initial_config, f, ensure_ascii=False, indent=4)
        return initial_config
    try:
        with open(BOARD_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            for board in BOARD_MAP.keys():
                if board not in config:
                    config[board] = {"alert": True}
            log_msg("게시판 알림 구성 정보 로드 성공", "DEBUG")
            return config
    except Exception as e:
        log_msg(f"⚠️ 게시판 설정 파일 로드 중 오류 발생: {e}", "ERROR")
        return {board: {"alert": True} for board in BOARD_MAP.keys()}

def save_board_config(config_data):
    log_msg("게시판 알림 환경 설정 파일 디스크 쓰기를 시도합니다.", "DEBUG")
    try:
        with open(BOARD_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        log_msg("게시판 알림 토글 설정이 디스크에 성공적으로 저장되었습니다.", "INFO")
        return True
    except Exception as e:
        log_msg(f"⚠️ 게시판 설정 파일 저장 중 오류 발생: {e}", "ERROR")
        return False

# ==========================================
# 3. 내장 경량 API 웹 서버
# ==========================================
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

# ==========================================
# 4. 크롤러 코어 함수
# ==========================================
def extract_post_id(link):
    if not link: return "0"
    match = re.search(r'document_srl=(\d+)', link)
    if match: return match.group(1)
    path = urlparse(link).path
    match_path = re.search(r'/(\d+)', path)
    if match_path: return match_path.group(1)
    return str(int(time.time()))

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: 
        log_msg("텔레그램 연동 환경변수가 부재하여 메시지 발송을 취소합니다.", "DEBUG")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: 
        res = requests.post(url, json=payload, timeout=10)
        log_msg(f"텔레그램 발송 요청 완료 (응답 코드: {res.status_code})", "DEBUG")
    except Exception as e: 
        log_msg(f"⚠️ 텔레그램 알림 메시지 발송 예외 발생: {e}", "ERROR")

def load_backup_data():
    log_msg(f"디스크 백업 JSON 데이터 복원 로드 시도: {JSON_BACKUP_FILE}", "DEBUG")
    if os.path.exists(JSON_BACKUP_FILE):
        try:
            with open(JSON_BACKUP_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                log_msg(f"기존 백업 복원 성공 (총 키워드 조합 데이터 개수: {len(data)})", "INFO")
                return data
        except Exception as e:
            log_msg(f"⚠️ 백업 데이터 로드 실패 (파일 손상 가능성): {e}", "ERROR")
    else:
        log_msg("수집 백업 데이터 파일이 감지되지 않아 빈 상태로 시작합니다.", "INFO")
    return {}

def save_backup_data(all_keywords_data):
    log_msg("전체 데이터 캐시 -> 디스크 JSON 백업 쓰기 요청 수신", "DEBUG")
    try:
        with open(JSON_BACKUP_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_keywords_data, f, ensure_ascii=False, indent=4)
        log_msg("JSON 데이터 백업 디스크 저장 성공 완료", "DEBUG")
    except Exception as e:
        log_msg(f"⚠️ 데이터 백업 저장 실패: {e}", "ERROR")

def get_list_page_posts(driver, board, keyword, page=1):
    encoded_keyword = quote(keyword)
    list_url = f"https://www.fmkorea.com/index.php?mid={board}&search_target=title_content&search_keyword={encoded_keyword}&page={page}"
    log_msg(f"[정찰조 Selenium] 목록 페이지 진입 시도 -> Board: {board}, Keyword: {keyword}", "DEBUG")
    
    try:
        driver.get(list_url)
    except Exception as e:
        log_msg(f"⚠️ 목록 페이지 브라우저 진입 에러: {e}", "ERROR")
        return []
        
    delay = random.uniform(5.0, 7.0)
    log_msg(f"목록 렌더링 대기용 지연 버퍼 구동: {delay:.2f}초", "DEBUG")
    time.sleep(delay)
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    posts = soup.select('table.bd_lst tbody tr:not(.notice)')
    
    post_list = []
    for post in posts:
        title_tag = post.select_one('td.title a.hx') or post.select_one('td.title a')
        if title_tag:
            link = title_tag.get('href')
            if link and not link.startswith('http'):
                link = f"https://www.fmkorea.com{link if link.startswith('/') else '/' + link}"
            
            reply_tag = title_tag.select_one('.replyNum')
            if reply_tag: reply_tag.extract()
            title = title_tag.text.strip()
            
            author_tag = post.select_one('.author')
            author = author_tag.text.strip() if author_tag else "익명"
            date_tag = post.select_one('.time')
            date = date_tag.text.strip() if date_tag else "날짜 모름"
            
            post_id = extract_post_id(link)
            post_list.append({'link': link, 'title': title, 'author': author, 'date': date, 'id': post_id})
            
    log_msg(f"[정찰조] 목록 파싱 결과: {len(post_list)}개의 게시글 발견 완료", "DEBUG")
    return post_list

def scrape_post_detail(driver, post_info):
    link = post_info['link']
    title = post_info['title']
    author = post_info['author']
    date = post_info['date']
    post_id = post_info.get('id', extract_post_id(link))
    
    log_msg(f"[타격대 Selenium] 본문 상세 스크래핑 진입 -> ID: {post_id} | Title: {title[:18]}...", "INFO")
    
    try:
        driver.get(link)
    except Exception as drive_err:
        log_msg(f"⚠️ 상세 페이지 브라우저 호출 오류: {drive_err}", "ERROR")
        raise drive_err
        
    delay = random.uniform(4.0, 7.0)
    log_msg(f"상세 로딩 보장용 지연 대기: {delay:.2f}초", "DEBUG")
    time.sleep(delay)
    
    page_source = driver.page_source
    if "삭제된 문서입니다" in page_source or "권한이 없습니다" in page_source or "존재하지 않는" in page_source:
        log_msg(f"🗑️ [원문 삭제 감지] 글 ID: {post_id}는 원문이 폭파되었거나 접근할 수 없습니다.", "WARN")
        return None
    
    detail_soup = BeautifulSoup(page_source, 'html.parser')
    
    content_area = detail_soup.select_one('.xe_content')
    if not content_area:
        log_msg(f"🗑️ [원문 부재 감지] 글 ID: {post_id}의 본문 데이터 DOM 구조가 소멸되어 삭제로 간주합니다.", "WARN")
        return None
    
    full_date_tag = detail_soup.select_one('.top_area .date, span.date.m_no')
    if full_date_tag and len(full_date_tag.text.strip()) > 5:
        date = full_date_tag.text.strip()
        
    views, votes, comment_count = "0", "0", "0"
    try:
        view_span = detail_soup.find(string=re.compile('조회 수'))
        if view_span: views = view_span.find_next('b').text.strip()
        vote_span = detail_soup.find(string=re.compile('추천 수'))
        if vote_span: votes = vote_span.find_next('b').text.strip()
        comment_span = detail_soup.find(string=re.compile('댓글'))
        if comment_span: comment_count = comment_span.find_next('b').text.strip()
        log_msg(f"글 메타데이터 수집 완료 -> 조회: {views}, 추천: {votes}, 댓글 수: {comment_count}", "DEBUG")
    except Exception as meta_err:
        log_msg(f"글 메타데이터 파싱 중 일부 누락/스킵: {meta_err}", "DEBUG")
    
    paragraphs = []
    video_list = []
    if content_area:
        log_msg(f"본문 태그 클리닝 및 미디어 구조화 시작 (ID: {post_id})", "DEBUG")
        for trash in content_area.select('.mejs__offscreen, .mejs__poster, .mejs__poster-img, .mejs__time-total, .mejs__currenttime, .mejs__duration, .mejs__controls, button, svg, ul, meta'):
            trash.extract()
            
        for a_trash in content_area.select('a.mejs__horizontal-volume-slider'):
            a_trash.extract()

        for a_tag in content_area.find_all('a'):
            a_tag['target'] = '_blank'
            a_tag['style'] = "color: #1877f2; text-decoration: underline; font-weight: bold;"

        for a_tag in content_area.find_all('a'):
            a_tag['target'] = '_blank'
            a_tag['style'] = "color: #1877f2; text-decoration: underline; font-weight: bold;"

        # 🎯 1. 에펨코리아 고정형 pc 미디어 wrapper 및 플레이어 고정값 완전 파괴
        for wrapper in content_area.select('.auto_media_wrapper'):
            if wrapper.get('style'): del wrapper['style']
            wrapper['style'] = "width: 100% !important; max-width: 100% !important; height: auto !important; display: block; margin-bottom: 10px;"

        # 🎯 2. height_keep 강제 패딩(57%) 비율 박스 해제 및 최신 규격으로 전환
        for hk in content_area.select('.height_keep'):
            if hk.get('style'): del hk['style']
            hk['style'] = "padding: 0 !important; padding-bottom: 0 !important; width: 100% !important; max-width: 100% !important; height: auto !important; aspect-ratio: 16 / 9 !important; display: block;"

        # 🎯 3. 자바스크립트가 강제로 꽂아넣은 미디어플레이어 컨테이너(mejs) 고정 픽셀값 박살내기
        for mejs in content_area.select('.mejs__container, .mejs__video, .mejs__inner, .mejs__mediaelement'):
            if mejs.get('style'): del mejs['style']
            if mejs.get('width'): del mejs['width']
            if mejs.get('height'): del mejs['height']
            mejs['style'] = "width: 100% !important; max-width: 100% !important; height: auto !important; aspect-ratio: 16 / 9 !important;"

        # 🎯 4. 영상 밑에 귀신같이 박혀있는 쓰레기 12px 여백 박스 및 빈 p 태그 전량 소거
        for empty_div in content_area.select('div[style*="height:12px"], div[style*="height: 12px"]'):
            empty_div.extract() # 👈 본문에서 아예 삭제처리하여 공백 누수 차단
            
        # 🎯 [최종 고도화] video 태그 분석 및 가로/세로형 가변 비율 적용
        for video in content_area.select('video'):
            # 원래 비디오가 가지고 있던 고정 스타일 속성 전량 파괴
            if video.get('width'): del video['width']
            if video.get('height'): del video['height']
            if video.get('style'): del video['style']
            
            source = video.select_one('source')
            src = video.get('src') or (source.get('src') if source else None)
            if src:
                if src.startswith('//'): src = 'https:' + src
                video_list.append(src)
                video['src'] = src
                
            video['controls'] = 'controls'
            video['playsinline'] = 'true'
            
            # 에펨 원본 데이터에서 가로/세로 크기 속성 추출 추출
            ori_w = int(video.get('data-original-width', 0) or video.get('data-x-width', 0) or 0)
            ori_h = int(video.get('data-original-height', 0) or video.get('data-x-height', 0) or 0)
            
            # 💡 판단: 만약 세로(height)가 가로(width)보다 긴 '쇼츠형 세로 영상'이라면?
            if ori_h > ori_w and ori_w > 0:
                # 세로형 쇼츠 전용 반응형 스타일 주입 (최대 높이를 제한하여 폰 화면을 다 가리지 않게 함)
                video['style'] = (
                    "width: 100% !important; max-width: 450px !important; "
                    "aspect-ratio: 9 / 16 !important; height: auto !important; "
                    "max-height: 75vh !important; background-color: #000; "
                    "margin: 10px auto !important; border-radius: 12px; "
                    "object-fit: contain; display: block;"
                )
            else:
                # 일반 가로형 영상 스타일 주입
                video['style'] = (
                    "width: 100% !important; max-width: 100% !important; "
                    "aspect-ratio: 16 / 9 !important; height: auto !important; "
                    "border-radius: 8px; object-fit: contain; display: block; margin: 10px 0;"
                )
        
        for iframe in content_area.select('iframe'):
            src = iframe.get('src')
            video_list.append(src)
            if src:
                if src.startswith('//'): src = 'https:' + src
                iframe['src'] = src
                iframe['style'] = "width: 100%; max-width: 100%; border-radius: 6px; margin-top: 8px;"

        img_count = 0
        for img in content_area.select('img'):
            real_src = (
                img.get('data-original') or 
                img.get('original') or 
                img.get('attach_target') or 
                img.get('native-src') or 
                img.get('src')
            )
            
            if not real_src or 'blank.gif' in real_src or 'pixel.gif' in real_src:
                img.extract()
                continue
                
            if real_src.startswith('//'): real_src = 'https:' + real_src
            elif real_src.startswith('/'): real_src = 'https://www.fmkorea.com' + real_src
            
            img['src'] = real_src
            img['alt'] = '첨부이미지'
            img['style'] = "width: 100%; height: auto; border-radius: 6px; margin-top: 8px; display: block;"
            if 'loading' in img.attrs: del img['loading']
            img_count += 1
            
        log_msg(f"본문 내 유효 첨부이미지 파싱 완료 -> 총 {img_count}개 정형화됨", "DEBUG")

        for br in content_area.find_all("br"): 
            br.replace_with("\n")
            
        for block in content_area.find_all(['p', 'div', 'li', 'h1', 'h2', 'h3']): 
            block.insert_after('\n')
            
        raw_html = content_area.decode_contents()
        raw_html = re.sub(r'<script.*?>.*?</script>', '', raw_html, flags=re.DOTALL)
        raw_html = re.sub(r'<!--.*?-->', '', raw_html, flags=re.DOTALL) 
        raw_html = raw_html.replace('\\', '')
        
        lines = raw_html.split('\n')
        empty_count = 0
        for line in lines:
            line_str = line.strip()
            if line_str == '':
                empty_count += 1
                if empty_count <= 2: 
                    paragraphs.append('')
            else:
                empty_count = 0
                paragraphs.append(line_str)
        
        while paragraphs and paragraphs[0] == '': paragraphs.pop(0)
        while paragraphs and paragraphs[-1] == '': paragraphs.pop()
    
    comments = []
    comment_items = detail_soup.select('.fdb_lst_ul > li.fdb_itm, ul#comment > li.fdb_itm, .fdb_lst > li.fdb_itm')
    if not comment_items: comment_items = detail_soup.select('.fdb_lst_ul > li')

    log_msg(f"댓글 영역 스캔 시작 -> 파싱 대상 DOM 개수: {len(comment_items)}개", "DEBUG")
    for item in comment_items:
        c_author_tag = item.select_one('.meta a')
        c_author = c_author_tag.text.strip() if c_author_tag else "익명"
        c_date_tag = item.select_one('.meta .date')
        c_date = c_date_tag.text.strip() if c_date_tag else ""
        c_votes_tag = item.select_one('.voted_count')
        c_votes = c_votes_tag.text.strip() if c_votes_tag else "0"
        
        c_content_area = item.select_one('.comment-content .xe_content, .xe_content')
        c_paragraphs = []
        if c_content_area:
            for a_tag in c_content_area.find_all('a'):
                href = a_tag.get('href', '')
                if href.startswith('#comment') or 'member_' in " ".join(a_tag.get('class', [])):
                    a_tag['style'] = "color: #1877f2; font-weight: bold; background-color: #e7f3ff; padding: 2px 6px; border-radius: 10px; text-decoration: none; margin-right: 5px; display: inline-block;"
                    if not a_tag.text.strip().startswith('@'): a_tag.string = f"@{a_tag.text.strip()}"

            for br in c_content_area.find_all("br"): br.replace_with("\n")
            for block in c_content_area.find_all(['p', 'div', 'li']):
                block.insert_after('\n')
                block.unwrap()
            
            c_raw_text = c_content_area.decode_contents()
            c_raw_text = re.sub(r'<!--.*?-->', '', c_raw_text, flags=re.DOTALL)
            c_raw_text = c_raw_text.replace('\\', '')
            
            c_lines = [line.strip() for line in c_raw_text.split('\n')]
            
            c_empty_count = 0
            for line in c_lines:
                if line == '':
                    c_empty_count += 1
                    if c_empty_count <= 2: c_paragraphs.append(line)
                else:
                    c_empty_count = 0
                    c_paragraphs.append(line)
            
            while c_paragraphs and c_paragraphs[0] == '': c_paragraphs.pop(0)
            while c_paragraphs and c_paragraphs[-1] == '': c_paragraphs.pop()

        style = item.get('style', '')
        classes = item.get('class', [])
        
        is_reply = False
        if any(k in "".join(classes).lower() for k in ['indent', 'depth', 'reply', 'respond']):
            is_reply = True
        elif 'margin-left' in style or 'padding-left' in style:
            if not re.search(r'(?:margin-left|padding-left)\s*:\s*0(px|%|em)?(?![\d])', style):
                is_reply = True
            
        comments.append({
            'author': c_author, 
            'date': c_date, 
            'votes': c_votes, 
            'content': c_paragraphs, 
            'is_reply': is_reply
        })
    
    log_msg(f"상세 글 스크래핑 완료 (정제 완료된 최종 댓글 개수: {len(comments)}개)", "INFO")
    return {
        'id': post_id, 'title': title, 'author': author, 'date': date, 'views': views, 'votes': votes,
        'comment_count': comment_count, 'link': link, 'content': paragraphs, 'images': [], 'videos': video_list, 'comments': comments
    }

# ==========================================
# 5. UI 빌더
# ==========================================
def generate_multiboard_html(all_keywords_data, output_file):
    log_msg("HTML 정적 대시보드 파일 템플릿 컴파일 빌드를 시작합니다.", "DEBUG")
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tabs_html = ""
    boards_html = ""
    
    active_config = load_keywords_from_file()
    board_alert_config = load_board_config()
    
    flattened_keywords = []
    for board, keywords in active_config.items():
        for keyword in keywords:
            combined_key = f"{board}::{keyword}"
            board_data = all_keywords_data.get(combined_key, [])
            
            new_posts_count = sum(1 for post in board_data if post.get('is_new', False))
            
            latest_post_date = ""
            if board_data and len(board_data) > 0:
                latest_post_date = board_data[0].get('date', '')
            
            flattened_keywords.append({
                'board': board,
                'keyword': keyword,
                'combined_key': combined_key,
                'board_data': board_data,
                'new_posts_count': new_posts_count,
                'total_count': len(board_data),
                'latest_post_date': latest_post_date
            })
    
    flattened_keywords.sort(
        key=lambda x: (
            x['new_posts_count'] > 0, 
            x['latest_post_date'], 
            x['total_count']
        ), 
        reverse=True
    )
    
    js_tab_meta_json = {}
    
    for global_idx, item in enumerate(flattened_keywords):
        board = item['board']
        keyword = item['keyword']
        board_data = item['board_data']
        new_posts_count = item['new_posts_count']
        
        board_name = BOARD_MAP.get(board, board)
        active_class = "active" if global_idx == 0 else ""
        display_style = "block" if global_idx == 0 else "none"
        
        js_tab_meta_json[f"board-{global_idx}"] = [p['id'] for p in board_data if p.get('is_new', False)]
        
        new_tag_in_tab = f'<span class="new-dot" id="dot-board-{global_idx}">🔴 </span>' if new_posts_count > 0 else f'<span class="new-dot" id="dot-board-{global_idx}" style="display:none;">🔴 </span>'
        
        tab_clean_text = f"[{board_name}] {keyword} ({len(board_data)})"
        
        tabs_html += f"""
        <div class="tab-wrapper" data-board-id="board-{global_idx}">
            <button class="tab-btn {active_class}" data-tab-name="{tab_clean_text}" onclick="openTab(event, 'board-{global_idx}')">{new_tag_in_tab}{tab_clean_text}</button>
            <button class="tab-del-btn" onclick="manageKeyword('delete', '{keyword}', '{board}')">×</button>
        </div>
        """
        
        pagination_markup = f"""
            <div class="pagination-control" style="display: flex; justify-content: center; align-items: center; gap: 8px; margin: 15px 0;">
                <button class="page-nav-btn btn-first" onclick="goToExtremePage('board-{global_idx}', 'first')" title="첫 페이지로">⏮️</button>
                <button class="page-nav-btn btn-prev" onclick="changePage('board-{global_idx}', -1)">◀ 이전</button>
                <span class="page-indicator" style="font-size: 14px; font-weight: bold; color: #4e5154; margin: 0 5px;">1 / 1</span>
                <button class="page-nav-btn btn-next" onclick="changePage('board-{global_idx}', 1)">다음 ▶</button>
                <button class="page-nav-btn btn-last" onclick="goToExtremePage('board-{global_idx}', 'last')" title="마지막 페이지로">⏭️</button>
            </div>
        """

        board_content = f"""
        <div id="board-{global_idx}" class="tab-content" style="display: {display_style};" data-current-page="1" data-tab-name="{tab_clean_text}">
            <div class="update-info">🔄 업데이트: {now} | {board_name} 게시판 -> [{keyword}] 총 {len(board_data)}개 글</div>
            
            {pagination_markup}
            
            <div class="posts-container">
        """
        
        if not board_data:
            board_content += '<div class="post-card" style="text-align:center; color:#65676b;">수집된 게시글이 없습니다. 모니터링 중 새 글이 등록되면 수집을 시작합니다.</div>'
        else:
            for post_idx, post in enumerate(board_data):
                content_html = ""
                for block in post['content']:
                    if block == '':
                        content_html += "<div style='height:12px;'></div>"
                    elif block.startswith('<img') or block.startswith('<video') or block.startswith('<div') or block.startswith('<iframe'):
                        content_html += block  
                    else:
                        content_html += f"<p style='margin: 6px 0; line-height: 1.6;'>{block}</p>" 
                
                is_new = post.get('is_new', False)
                card_class = "post-card new-post" if is_new else "post-card"
                new_badge = '<span class="new-badge">NEW</span>' if is_new else ''
                sync_badge = '<span class="sync-badge">🔄 동기화중</span>' if post_idx < MAX_POSTS_TO_SYNC_COMMENTS else ""
                
                comments_html = ""
                if post['comments']:
                    comments_html += f'<div class="post-comments-section"><h3>💬 댓글 ({post["comment_count"]})</h3>'
                    for c in post['comments']:
                        c_content_html = "".join([f"<p style='margin: 3px 0;'>{t}</p>" if t else "<br>" for t in c['content']])
                        
                        is_reply = c.get('is_reply', False)
                        indent_class = "comment-reply" if is_reply else ""
                        reply_icon = '<span style="color:#adb5bd; margin-right:5px; font-weight:bold; display:inline-block !important;">└</span>' if is_reply else ''
                        
                        if c['author'] == post['author']:
                            bg_color = "#fff0f0"
                            author_display = f'{reply_icon}<strong style="color: #ff4747;">{c["author"]} <span style="background-color: #ff4747; color: white; padding: 2px 5px; border-radius: 4px; font-size: 10px; margin-left: 3px; vertical-align: text-bottom;">작성자</span></strong>'
                        else:
                            bg_color = "#f8f9fa"
                            author_display = f"{reply_icon}<strong>{c['author']}</strong>"
                        
                        comments_html += f"""
                        <div class="comment {indent_class}" style="background: {bg_color};">
                            <div class="comment-meta">
                                <div>{author_display} <span style="margin-left:6px; font-size:11px; color:#90949c;">{c['date']}</span></div>
                                <div style="color: #ff4747; font-weight: bold;">👍 {c['votes']}</div>
                            </div>
                            <div class="comment-body">{c_content_html}</div>
                        </div>
                        """
                    comments_html += '</div>'
                
                board_content += f"""
                <div class="{card_class}" id="post-{post['id']}" data-is-new="{str(is_new).lower()}">
                    <div class="post-header">
                        <div class="post-title">{post['title']}{new_badge}{sync_badge}</div>
                        <div class="post-meta">
                            <span>✍️ {post['author']}</span>
                            <span>👁️ {post['views']}</span>
                            <span>👍 {post['votes']}</span>
                            <span>🕒 {post['date']}</span>
                        </div>
                    </div>
                    <div class="post-body">
                        <div class="post-content">{content_html}</div>
                        <div style="margin-top: 15px; display: flex; gap: 10px;">
                            <a href="{post['link']}" target="_blank" class="original-link-btn" onclick="event.stopPropagation();">🔗 에프엠코리아 원문</a>
                        </div>
                        {comments_html}
                    </div>
                </div>
                """
        
        board_content += f"""
            </div>
            {pagination_markup}
        </div>
        """
        boards_html += board_content

    board_options = "".join([f'<option value="{k}">{v}</option>' for k, v in BOARD_MAP.items()])

    alert_toggles_html = ""
    for b_key, b_val in BOARD_MAP.items():
        is_alert_on = board_alert_config.get(b_key, {}).get("alert", True)
        checked_attr = "checked" if is_alert_on else ""
        status_label = "🔔 알림 활성" if is_alert_on else "🔕 알림 꺼짐"
        status_class = "status-on" if is_alert_on else "status-off"
        
        alert_toggles_html += f"""
        <div class="toggle-item">
            <span class="toggle-label">🎯 {b_val}</span>
            <div style="display: flex; align-items: center; gap: 10px;">
                <span class="toggle-status {status_class}">{status_label}</span>
                <label class="switch">
                    <input type="checkbox" {checked_attr} onchange="toggleBoardAlert('{b_key}', this)">
                    <span class="slider round"></span>
                </label>
            </div>
        </div>
        """

    js_meta_string = json.dumps(js_tab_meta_json)

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, minimum-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>통합 멀티 키워드 미니 게시판</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Malgun Gothic', sans-serif; background-color: #f0f2f5; margin: 0; padding: 10px; color: #1c1e21; box-sizing: border-box; }}
        .container {{ width: 100%; max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; }}
        
        .panel-toggle-btn {{ background: #4e5154; color: white; border: none; width: 100%; padding: 10px; font-size: 13px; font-weight: bold; border-radius: 8px; cursor: pointer; margin-bottom: 8px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.1); transition: background 0.2s; display: flex; align-items: center; justify-content: center; gap: 6px; }}
        .panel-toggle-btn:hover {{ background: #3c3f41; }}
        
        .admin-panel {{ background: #fff; padding: 12px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: none; flex-direction: column; gap: 12px; transition: all 0.3s ease; }}
        .admin-title {{ font-size: 13px; font-weight: bold; color: #1c1e21; margin-bottom: 2px; border-bottom: 1px dashed #e4e6eb; padding-bottom: 6px; }}
        .admin-row {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
        .admin-select {{ padding: 8px; border: 1px solid #ccd0d5; border-radius: 6px; font-size: 13px; background: white; }}
        .admin-input {{ flex: 1; min-width: 120px; padding: 8px 12px; border: 1px solid #ccd0d5; border-radius: 6px; font-size: 13px; outline: none; }}
        .admin-btn {{ background: #1877f2; color: #fff; border: none; padding: 0 16px; font-size: 13px; font-weight: bold; border-radius: 6px; cursor: pointer; white-space: nowrap; height: 36px; }}

        .refresh-btn {{ display: none; }}

        .alert-management-zone {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; padding-top: 4px; }}
        .toggle-item {{ display: flex; justify-content: space-between; align-items: center; background: #f8f9fa; padding: 6px 10px; border-radius: 6px; border: 1px solid #e4e6eb; }}
        .toggle-label {{ font-size: 13px; font-weight: bold; color: #4e5154; }}
        .toggle-status {{ font-size: 11px; font-weight: bold; padding: 2px 6px; border-radius: 4px; }}
        .toggle-status.status-on {{ background-color: #e2f9e9; color: #1e7e34; }}
        .toggle-status.status-off {{ background-color: #fff0f0; color: #dc3545; }}

        .switch {{ position: relative; display: inline-block; width: 38px; height: 22px; }}
        .switch input {{ opacity: 0; width: 0; height: 0; }}
        .slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .3s; }}
        .slider:before {{ position: absolute; content: ""; height: 16px; width: 16px; left: 3px; bottom: 3px; background-color: white; transition: .3s; }}
        input:checked + .slider {{ background-color: #1877f2; }}
        input:focus + .slider {{ box-shadow: 0 0 1px #1877f2; }}
        input:checked + .slider:before {{ transform: translateX(16px); }}
        .slider.round {{ border-radius: 22px; }}
        .slider.round:before {{ border-radius: 50%; }}

        .tab-container {{ 
            display: flex; 
            gap: 6px; 
            margin-bottom: 15px; 
            border-bottom: 2px solid #e4e6eb; 
            padding-bottom: 10px; 
            overflow-x: auto; 
            white-space: nowrap;
            -webkit-overflow-scrolling: touch; 
            width: 100%;
            box-sizing: border-box;
            cursor: grab;
        }}
        .tab-container:active {{ cursor: grabbing; }}
        .tab-container::-webkit-scrollbar {{ display: none; }}
        
        .tab-wrapper {{ display: flex; align-items: center; background-color: #e4e6eb; border-radius: 20px; overflow: hidden; flex-shrink: 0; user-select: none; }}
        .tab-btn {{ background: none; border: none; padding: 8px 12px 8px 16px; font-size: 13px; font-weight: bold; cursor: pointer; color: #4e5154; outline: none; white-space: nowrap; }}
        .tab-wrapper:has(.tab-btn.active) {{ background-color: #1877f2; }}
        .tab-btn.active {{ color: white; }}
        .tab-del-btn {{ background: none; border: none; padding: 8px 12px 8px 4px; font-size: 14px; cursor: pointer; color: #8d949e; font-weight: bold; outline: none; }}
        .tab-wrapper:has(.tab-btn.active) .tab-del-btn {{ color: #e4e6eb; }}
        
        .post-card {{ background: white; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); word-break: break-all; transition: border 0.2s ease, background-color 1s ease; }}
        .post-card.new-post {{ border: 2px solid #1877f2; }}
        .new-badge {{ display: inline-block; background: #1877f2; color: white; font-size: 10px; padding: 2px 6px; border-radius: 10px; margin-left: 5px; }}
        .sync-badge {{ display: inline-block; background: #28a745; color: white; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; }}
        .post-header {{ border-bottom: 1px solid #e4e6eb; padding-bottom: 8px; margin-bottom: 12px; }}
        .post-title {{ font-size: 16px; font-weight: bold; margin-bottom: 8px; color: #1877f2; line-height: 1.4; }}
        .post-meta {{ font-size: 12px; color: #65676b; display: flex; flex-wrap: wrap; gap: 10px; }}
        .post-content {{ font-size: 14px; line-height: 1.6; color: #1c1e21; }}
        .post-content img {{ width: 100%; height: auto; border-radius: 6px; margin-top: 8px; display: block; }}
        .original-link-btn {{ display: inline-block; padding: 8px 14px; background: #e4e6eb; color: #333; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: bold; text-align: center; }}
        .update-info {{ text-align: center; color: #65676b; font-size: 12px; margin-bottom: 15px; padding: 8px; background: white; border-radius: 6px; }}
        .post-comments-section {{ margin-top: 15px; border-top: 2px solid #e4e6eb; padding-top: 12px; }}
        .comment {{ padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; font-size: 13px; }}
        .comment-reply {{ margin-left: 12px; border-left: 2px solid #ccd0d5; }}
        .comment-meta {{ display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }}
        
        .page-nav-btn {{
            background-color: #fff;
            border: 1px solid #ccd0d5;
            color: #1c1e21;
            padding: 6px 10px;
            font-size: 13px;
            font-weight: bold;
            border-radius: 6px;
            cursor: pointer;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            transition: all 0.2s ease;
        }}
        .page-nav-btn:hover {{ background-color: #f2f3f5; }}
        .page-nav-btn:disabled {{ background-color: #e4e6eb; color: #bcc0c4; cursor: not-allowed; border-color: #e4e6eb; }}

        .floating-actions {{
            position: fixed;
            bottom: 25px;
            /* 화면 중앙에서 본문 너비의 절반(400px)만큼 우측으로 밀고, 15px 여백을 둠 */
            left: calc(50% + 400px + 15px); 
            display: flex;
            flex-direction: column;
            gap: 12px;
            z-index: 9999;
        }}

        @media (max-width: 830px) {{
            .floating-actions {{
                left: auto;
                right: 25px;
            }}
        }}

        .scroll-top-btn, .floating-refresh-btn {{
            width: 48px;
            height: 48px;
            color: white;
            border: none;
            border-radius: 50%;
            font-size: 20px;
            font-weight: bold;
            cursor: pointer;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
        }}

        .floating-refresh-btn {{
            background-color: #28a745;
        }}
        .floating-refresh-btn:hover {{
            background-color: #218838;
            transform: translateY(-3px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.3);
        }}

        .scroll-top-btn {{
            background-color: #1877f2;
            opacity: 0;
            visibility: hidden;
        }}
        .scroll-top-btn.visible {{ opacity: 1; visibility: visible; }}
        .scroll-top-btn:hover {{ background-color: #145dbf; transform: translateY(-3px); box-shadow: 0 6px 12px rgba(0, 0, 0, 0.3); }}
        /* 1. 일반 video 태그 및 iframe 영상이 화면을 벗어나지 않도록 방지 */
        .post-card video, 
        .post-card iframe, 
        .post-card embed, 
        .post-card object {{
            max-width: 100%;       /* 👈 게시물 폭을 절대 넘지 않도록 제한 */
            height: auto;          /* 👈 폭에 맞춰 높이 자동 조절 */
            box-sizing: border-box;
        }}

        /* 2. 유튜브 등 iframe 영상의 16:9 비율을 모바일에서도 유지하고 싶을 때 (선택사항) */
        /* 만약 영상이 가로세로 비율이 깨지거나 찌그러진다면, 영상을 감싸는 부모 태그에 적용하면 좋습니다. */
        .video-wrapper {{
            position: relative;
            padding-bottom: 56.25%; /* 16:9 비율 유지 */
            padding-top: 25px;
            height: 0;
        }}
        .video-wrapper iframe {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }}
        /* 상단 고정 네비게이션 배너 스타일 */
        .top-nav-banner {{
            position: sticky;
            top: 0;
            left: 0;
            width: 100%;
            max-width: 800px;
            background: linear-gradient(135deg, #1e293b, #0f172a); /* 세련된 다크 그레이/네이비 톤 */
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            z-index: 9999; /* 다른 요소보다 항상 위에 위치 */
            padding: 15px 0;
            margin: 0 auto;
            margin-bottom: 10px;
            border-radius: 8px;
        }}

        .nav-container {{
            position: relative;
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px;
            box-sizing: border-box;
        }}

        .nav-logo {{
            position: absolute; left: 50%; transform: translateX(-50%);
            font-size: 1.1rem;
            font-weight: 700;
            color: #f8fafc;
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: color 0.2s ease;
        }}

        .nav-logo:hover {{
            color: #38bdf8; /* 호버 시 스카이블루 포인트 */
        }}

        /* 모바일 대응 화면 여백 확보 */
        @media (max-width: 768px) {{
            .nav-container {{
                padding: 0 15px;
            }}
            .nav-logo {{
                font-size: 1rem;
            }}
        }}

        /* 대시보드 스타일 태그 내 기존 미디어 wrapper 관련 CSS를 아래와 같이 유연하게 통합 변경합니다 */
        .auto_media_wrapper, 
        .auto_media_wrapper.full.pc,
        .height_keep {{
            width: 100% !important;
            max-width: 100% !important;
            height: auto !important;      /* 👈 고정 높이 완벽 제거 */
            padding: 0 !important;
            padding-bottom: 0 !important; /* 👈 악성 57% 패딩 완벽 제거 */
            margin: 8px auto !important;
            display: block !important;
        }}

        /* 105라인 부근 고정 이미지 스타일 아래에 추가 또는 변경 */
        .post-content img {{ max-width: 100%; height: auto; border-radius: 6px; margin: 6px 0; display: block; }}

        /* 🎯 [여기서부터 복사해서 붙여넣으세요] 영상 모바일 탈출 방지 치트키 */
        .post-content video {{
            width: 100% !important;        /* 인라인 width 속성 강제 무시 */
            max-width: 100% !important;    /* 게시물 가로폭 절대 안 넘게 제한 */
            height: auto !important;       /* 고정 높이(500px 등)를 무시하고 가로 비율에 맞춤 */
            max-height: 70vh !important;   /* 모바일 화면 세로를 너무 가득 채우지 않도록 제한 */
            object-fit: contain;
            border-radius: 8px;
            margin: 8px 0;
            display: block;
        }}

        /* iframe(유튜브)은 원본 비율을 파이썬이 알기 어려우므로 기본 16:9를 주되 가변 허용 */
        .post-content iframe, 
        .xe_content iframe {{
            width: 100% !important;
            max-width: 100% !important;
            aspect-ratio: 16 / 9 !important;
            height: auto !important;
            border-radius: 8px;
            display: block;
        }}

        /* 에펨코리아 자체 미디어플레이어 컨테이너가 가로로 터지는 현상 방지 */
        .mejs__container, .mejs__embed, .mejs__player {{
            width: 100% !important;
            max-width: 100% !important;
            height: auto !important;
        }}
    </style>
    
    <script>
        (function() {{
            try {{
                let readIds = JSON.parse(localStorage.getItem('read_post_ids') || '[]');
                let tabMeta = {js_meta_string}; 
                let styleRules = "";

                if (readIds.length > 0) {{
                    readIds.forEach(id => {{
                        styleRules += `#post-${{id}} {{ border: none !important; }}\\n`;
                        styleRules += `#post-${{id}} .new-badge {{ display: none !important; }}\\n`;
                    }});
                }}

                for (let boardId in tabMeta) {{
                    let newIdsInTab = tabMeta[boardId];
                    if (newIdsInTab.length > 0) {{
                        let isAllRead = newIdsInTab.every(id => readIds.includes(String(id)));
                        if (isAllRead) {{
                            styleRules += `#dot-${{boardId}} {{ display: none !important; }}\\n`;
                        }}
                    }}
                }}

                if (styleRules) {{
                    const styleEl = document.createElement('style');
                    styleEl.innerHTML = styleRules;
                    document.head.appendChild(styleEl);
                }}
            }} catch(e) {{}}
        }}).call(this);
    </script>
    
    <script>
        const POSTS_PER_PAGE = 10;

        function toggleAdminPanel() {{
            const panel = document.getElementById('admin-panel-zone');
            const btn = document.getElementById('panel-toggle-trigger');
            if (panel.style.display === 'none' || panel.style.display === '') {{
                panel.style.display = 'flex';
                btn.innerHTML = '⚙️ 실시간 모니터링 관리 패널 접기 ▲';
                localStorage.setItem('admin_panel_open', 'true');
            }} else {{
                panel.style.display = 'none';
                btn.innerHTML = '⚙️ 실시간 모니터링 관리 패널 열기 ▼';
                localStorage.setItem('admin_panel_open', 'false');
            }}
        }}

        function refreshCurrentTab() {{
            const activeTabContent = document.querySelector('.tab-content[style*="display: block"]');
            if (activeTabContent) {{
                const currentBoardId = activeTabContent.id;
                const currentPage = activeTabContent.getAttribute('data-current-page') || '1';
                
                sessionStorage.setItem('last_active_board', currentBoardId);
                sessionStorage.setItem('last_active_page', currentPage);
                sessionStorage.setItem('is_refreshing', 'true');
            }}
            window.location.reload();
        }}

        function updatePagination(boardId) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;
            
            const posts = boardEl.querySelectorAll('.posts-container > .post-card');
            const controls = boardEl.querySelectorAll('.pagination-control');
            
            if (posts.length === 0) {{
                controls.forEach(ctrl => ctrl.style.display = 'none');
                return;
            }}
            
            let currentPage = parseInt(boardEl.getAttribute('data-current-page') || '1');
            const totalPages = Math.ceil(posts.length / POSTS_PER_PAGE);
            
            if (currentPage > totalPages) currentPage = totalPages;
            if (currentPage < 1) currentPage = 1;
            boardEl.setAttribute('data-current-page', currentPage);
            
            const startIdx = (currentPage - 1) * POSTS_PER_PAGE;
            const endIdx = startIdx + POSTS_PER_PAGE;
            
            posts.forEach((post, index) => {{
                if (index >= startIdx && index < endIdx) {{
                    post.style.display = 'block';
                }} else {{
                    post.style.display = 'none';
                }}
            }});
            
            controls.forEach(ctrl => {{
                const indicator = ctrl.querySelector('.page-indicator');
                if (indicator) indicator.innerText = currentPage + " / " + totalPages;
                
                const firstBtn = ctrl.querySelector('.btn-first');
                const prevBtn = ctrl.querySelector('.btn-prev');
                const nextBtn = ctrl.querySelector('.btn-next');
                const lastBtn = ctrl.querySelector('.btn-last');
                
                if (firstBtn) firstBtn.disabled = (currentPage === 1);
                if (prevBtn) prevBtn.disabled = (currentPage === 1);
                if (nextBtn) nextBtn.disabled = (currentPage === totalPages);
                if (lastBtn) lastBtn.disabled = (currentPage === totalPages);
            }});
        }}

        function changePage(boardId, direction) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;
            
            let currentPage = parseInt(boardEl.getAttribute('data-current-page') || '1');
            currentPage += direction;
            boardEl.setAttribute('data-current-page', currentPage);
            updatePagination(boardId);
            
            const containerOffset = document.querySelector('.tab-container').offsetTop + 50;
            window.scrollTo({{ top: containerOffset, behavior: 'smooth' }});
        }}

        function goToExtremePage(boardId, target) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;
            
            const posts = boardEl.querySelectorAll('.posts-container > .post-card');
            const totalPages = Math.ceil(posts.length / POSTS_PER_PAGE) || 1;
            
            let targetPage = (target === 'first') ? 1 : totalPages;
            boardEl.setAttribute('data-current-page', targetPage);
            updatePagination(boardId);
            
            const containerOffset = document.querySelector('.tab-container').offsetTop + 50;
            window.scrollTo({{ top: containerOffset, behavior: 'smooth' }});
        }}

        function savePostsToReadList(boardId) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;

            const allCards = boardEl.querySelectorAll('.posts-container > .post-card');
            if (allCards.length === 0) return;

            let readIds = [];
            try {{ readIds = JSON.parse(localStorage.getItem('read_post_ids') || '[]'); }} catch(e) {{}}

            let hasNewRead = false;
            allCards.forEach(card => {{
                const idMatch = card.id.replace('post-', '');
                if (idMatch && !readIds.includes(idMatch)) {{
                    readIds.push(idMatch);
                    hasNewRead = true;
                }}
            }});

            if (hasNewRead) {{
                if (readIds.length > 1500) readIds = readIds.slice(readIds.length - 1500);
                localStorage.setItem('read_post_ids', JSON.stringify(readIds));
            }}
        }}

        function clearPostBadgesInDOM(boardId) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;

            const cards = boardEl.querySelectorAll('.posts-container > .post-card');
            cards.forEach(card => {{
                card.classList.remove('new-post');
                card.style.border = 'none';
                const badge = card.querySelector('.new-badge');
                if (badge) badge.remove();
            }});
        }}

        function syncTabDotState(boardId) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;

            let readIds = [];
            try {{ readIds = JSON.parse(localStorage.getItem('read_post_ids') || '[]'); }} catch(e) {{}}

            const allNewCards = boardEl.querySelectorAll('.posts-container > .post-card[data-is-new="true"]');
            let hasUnreadPost = false;

            for (let card of allNewCards) {{
                const id = card.id.replace('post-', '');
                if (!readIds.includes(id)) {{
                    hasUnreadPost = true;
                    break;
                }}
            }}

            const globalIdx = boardId.replace('board-', '');
            const targetDot = document.getElementById('dot-board-' + globalIdx);
            if (targetDot) {{
                targetDot.style.display = hasUnreadPost ? 'inline' : 'none';
            }}
        }}

        function openTab(evt, boardId) {{
            const previousActiveTab = document.querySelector('.tab-content[style*="display: block"]');
            if (previousActiveTab && previousActiveTab.id !== boardId) {{
                savePostsToReadList(previousActiveTab.id);
                clearPostBadgesInDOM(previousActiveTab.id);
            }}

            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tab-content");
            for (i = 0; i < tabcontent.length; i++) {{ tabcontent[i].style.display = "none"; }}
            tablinks = document.getElementsByClassName("tab-btn");
            for (i = 0; i < tablinks.length; i++) {{ tablinks[i].className = tablinks[i].className.replace(" active", ""); }}
            
            const targetBoard = document.getElementById(boardId);
            targetBoard.style.display = "block";
            if (evt) evt.currentTarget.className += " active";
            
            updatePagination(boardId);
            
            const globalIdx = boardId.replace('board-', '');
            const targetDot = document.getElementById('dot-board-' + globalIdx);
            if (targetDot) targetDot.style.display = 'none';
        }}

        function restoreAllTabsState() {{
            const allContents = document.querySelectorAll('.tab-content');
            
            let readIds = [];
            try {{ readIds = JSON.parse(localStorage.getItem('read_post_ids') || '[]'); }} catch(e) {{}}

            allContents.forEach(content => {{
                const boardId = content.id;
                
                const cards = content.querySelectorAll('.posts-container > .post-card');
                cards.forEach(card => {{
                    const id = card.id.replace('post-', '');
                    if (readIds.includes(id)) {{
                        card.classList.remove('new-post');
                        card.style.border = 'none';
                        const badge = card.querySelector('.new-badge');
                        if (badge) badge.remove();
                    }}
                }});

                syncTabDotState(boardId);
            }});
            
            const activeContent = document.querySelector('.tab-content[style*="display: block"]');
            if (activeContent) {{
                updatePagination(activeContent.id);
                
                if (sessionStorage.getItem('is_refreshing') === 'true') {{
                    savePostsToReadList(activeContent.id);
                    sessionStorage.removeItem('is_refreshing');
                    clearPostBadgesInDOM(activeContent.id);
                }} else {{
                    const globalIdx = activeContent.id.replace('board-', '');
                    const targetDot = document.getElementById('dot-board-' + globalIdx);
                    if (targetDot) targetDot.style.display = 'none';
                }}
            }}
        }}

        function scrollToTop() {{
            window.scrollTo({{ top: 0, behavior: 'smooth' }});
        }}

        function toggleBoardAlert(boardKey, checkboxElement) {{
            let pwd = document.getElementById('admin-pwd-input').value.trim();
            if (!pwd) {{ 
                alert('알림 설정을 변경하려면 패널 우측의 관리자 암호를 먼저 입력해 주세요.'); 
                checkboxElement.checked = !checkboxElement.checked;
                return; 
            }}
            
            const targetStatus = checkboxElement.checked;
            const apiUrl = '/api/toggle-alert?board=' + encodeURIComponent(boardKey) + 
                           '&enabled=' + targetStatus + 
                           '&password=' + encodeURIComponent(pwd);
            
            fetch(apiUrl, {{
                method: 'GET',
                headers: {{ 'Accept': 'application/json' }}
            }})
            .then(res => res.json())
            .then(data => {{
                alert(data.message);
                if (data.success) {{ 
                    location.reload(); 
                }} else {{
                    checkboxElement.checked = !targetStatus;
                }}
            }})
            .catch(err => {{
                alert('알림 상태 요청 중 오류가 발생했습니다.');
                checkboxElement.checked = !targetStatus;
            }});
        }}

        // 🌟 텔레그램 연동 앵커 정밀 타겟 추적 함수 (시작점 정렬 + 상단 여백 보정 완료)
        function handleTelegramAnchorLink() {{
            const hash = window.location.hash;
            if (hash && hash.startsWith('#post-')) {{
                const targetPost = document.getElementById(hash.replace('#', ''));
                if (targetPost) {{
                    const parentTab = targetPost.closest('.tab-content');
                    if (parentTab) {{
                        const boardId = parentTab.id;
                        
                        // 1. 페이지 위치 역산 계산 엔진
                        const allCardsInTab = Array.from(parentTab.querySelectorAll('.posts-container > .post-card'));
                        const postIndex = allCardsInTab.indexOf(targetPost);
                        
                        if (postIndex !== -1) {{
                            const targetPage = Math.ceil((postIndex + 1) / POSTS_PER_PAGE);
                            parentTab.setAttribute('data-current-page', targetPage);
                        }}
                        
                        // 2. 대시보드 탭 UI 강제 전환 활성화
                        const tabcontents = document.getElementsByClassName("tab-content");
                        for (let i = 0; i < tabcontents.length; i++) {{ tabcontents[i].style.display = "none"; }}
                        parentTab.style.display = "block";
                        
                        const tablinks = document.getElementsByClassName("tab-btn");
                        for (let i = 0; i < tablinks.length; i++) {{ tablinks[i].classList.remove("active"); }}
                        const matchWrapperBtn = document.querySelector(`.tab-wrapper[data-board-id="${{boardId}}"] .tab-btn`);
                        if (matchWrapperBtn) matchWrapperBtn.classList.add("active");
                        
                        // 3. 페이지네이션 갱신 (숨겨진 display: none 해제)
                        updatePagination(boardId);
                        
                        // 4. 글 시작점(start) 이동 및 탭 레이아웃에 가려지지 않도록 상단 여백(-60px) 자동 보정
                        setTimeout(() => {{
                            // 1. 게시글의 화면상 절대 위치(Y축) 계산
                            const elementPosition = targetPost.getBoundingClientRect().top + window.pageYOffset;
                            
                            // 2. 원하는 상단 여백 설정 (숫자가 커질수록 게시글이 화면 아래쪽으로 내려옵니다)
                            const offset = 60; // 👈 60~100 사이의 값으로 조절해보세요 (기본 상단바 두께만큼)
                            const offsetPosition = elementPosition - offset;

                            // 3. 계산된 위치로 부드럽게 스크롤 이동
                            window.scrollTo({{
                                top: offsetPosition,
                                behavior: 'smooth'
                            }});

                            // 하이라이트 효과는 그대로 유지
                            targetPost.style.backgroundColor = '#fff9c4'; 
                            setTimeout(() => {{ targetPost.style.backgroundColor = ''; }}, 2500);
                        }}, 400);
                    }}
                }} else {{
                    const postId = hash.replace('#post-', '');
                    if (postId) {{
                        window.location.replace('https://www.fmkorea.com/' + postId);
                    }}
                }}
            }}
        }}

        window.addEventListener('beforeunload', () => {{
            const activeContent = document.querySelector('.tab-content[style*="display: block"]');
            if (activeContent) {{
                savePostsToReadList(activeContent.id);
            }}
        }});

        window.addEventListener('DOMContentLoaded', () => {{
            const savedBoard = sessionStorage.getItem('last_active_board');
            const savedPage = sessionStorage.getItem('last_active_page');
            
            sessionStorage.removeItem('last_active_board');
            sessionStorage.removeItem('last_active_page');
            
            if (savedBoard && document.getElementById(savedBoard)) {{
                const tabcontents = document.getElementsByClassName("tab-content");
                for (let i = 0; i < tabcontents.length; i++) {{ tabcontents[i].style.display = "none"; }}
                const tablinks = document.getElementsByClassName("tab-btn");
                for (let i = 0; i < tablinks.length; i++) {{ tablinks[i].classList.remove("active"); }}
                
                const targetBoard = document.getElementById(savedBoard);
                targetBoard.style.display = "block";
                
                const matchWrapper = document.querySelector('.tab-wrapper[data-board-id="' + savedBoard + '"] .tab-btn');
                if (matchWrapper) matchWrapper.classList.add("active");
                
                if (savedPage) targetBoard.setAttribute('data-current-page', savedPage);
                updatePagination(savedBoard);
            }} else {{
                const activeTabContent = document.querySelector('.tab-content[style*="display: block"]');
                if (activeTabContent) {{
                    updatePagination(activeTabContent.id);
                }} else {{
                    const allTabs = document.querySelectorAll('.tab-content');
                    allTabs.forEach(t => updatePagination(t.id));
                }}
            }}
            
            restoreAllTabsState();

            // DOM 렌더링 즉시 텔레그램 진입 좌표 추적 작동 개시
            handleTelegramAnchorLink();

            if (localStorage.getItem('admin_panel_open') === 'true') {{
                document.getElementById('admin-panel-zone').style.display = 'flex';
                document.getElementById('panel-toggle-trigger').innerHTML = '⚙️ 실시간 모니터링 관리 패널 접기 ▲';
            }}

            const topBtn = document.getElementById('floating-top-btn');
            window.addEventListener('scroll', () => {{
                if (window.scrollY > 300) {{
                    topBtn.classList.add('visible');
                }} else {{
                    topBtn.classList.remove('visible');
                }}
            }});
        }});

        window.addEventListener('hashchange', handleTelegramAnchorLink);

        function manageKeyword(action, targetKw, targetBoard) {{
            let kw = targetKw || document.getElementById('new-kw-input').value.trim();
            let pwd = document.getElementById('admin-pwd-input').value.trim();
            let board = targetBoard || document.getElementById('board-select').value;
            
            if (!kw) {{ alert('키워드를 입력해 주세요.'); return; }}
            if (!pwd) {{ alert('인증 관리자 비밀번호를 입력해야 합니다.'); return; }}
            
            if (action === 'delete') {{
                if (!confirm("'" + kw + "' 키워드를 정말 삭제하시겠습니까?")) return;
            }}
            
            const btn = window.event ? window.event.target : null;
            if (btn) btn.disabled = true;

            fetch('/api/keyword', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ action: action, keyword: kw, board: board, password: pwd }})
            }})
            .then(res => res.json())
            .then(data => {{
                alert(data.message);
                if (data.success) {{ location.reload(); }}
            }})
            .catch(err => {{
                alert('요청 중 오류가 발생했습니다.');
            }})
            .finally(() => {{
                if (btn) btn.disabled = false;
            }});
        }}
    </script>
</head>
<body>
    <header class="top-nav-banner">
        <div class="nav-container">
            <a href="/" class="nav-logo">
                <span class="icon">🏠</span> 실시간 모니터링 대시보드
            </a>
        </div>
    </header>
    <div class="container">
        <button id="panel-toggle-trigger" class="panel-toggle-btn" onclick="toggleAdminPanel()">⚙️ 실시간 모니터링 관리 패널 열기 ▼</button>

        <div class="admin-panel" id="admin-panel-zone">
            <div class="admin-title">🛠️ 키워드 실시간 모니터링 관리 패널</div>
            <div class="admin-row">
                <select id="board-select" class="admin-select">
                    {board_options}
                </select>
                <input type="text" id="new-kw-input" class="admin-input" placeholder="추가할 키워드 입력">
                <input type="password" id="admin-pwd-input" class="admin-input" style="max-width:140px;" placeholder="관리자 암호">
                <button class="admin-btn" onclick="manageKeyword('add')">➕ 등록</button>
            </div>
            
            <div class="admin-title" style="margin-top: 4px;">🔔 게시판별 텔레그램 알림 토글 제어 (관리자 암호 필요)</div>
            <div class="alert-management-zone">
                {alert_toggles_html}
            </div>
        </div>

        <div class="tab-container" id="tab-scroll-container">
            {tabs_html}
        </div>

        {boards_html}
    </div>

    <div class="floating-actions">
        <button class="floating-refresh-btn" onclick="refreshCurrentTab()" title="현재 키워드 즉시 새로고침">🔄</button>
        <button id="floating-top-btn" class="scroll-top-btn" onclick="scrollToTop()" title="맨 위로 이동">▲</button>
    </div>

    <script>
        const slider = document.getElementById('tab-scroll-container');
        let isDown = false;
        let startX;
        let scrollLeft;

        slider.addEventListener('mousedown', (e) => {{
            isDown = true;
            slider.classList.add('active');
            startX = e.pageX - slider.offsetLeft;
            scrollLeft = slider.scrollLeft;
        }});
        slider.addEventListener('mouseleave', () => {{
            isDown = false;
            slider.classList.remove('active');
        }});
        slider.addEventListener('mouseup', () => {{
            isDown = false;
            slider.classList.remove('active');
        }});
        slider.addEventListener('mousemove', (e) => {{
            if(!isDown) return;
            e.preventDefault();
            const x = e.pageX - slider.offsetLeft;
            const walk = (x - startX) * 2;
            slider.scrollLeft = scrollLeft - walk;
        }});
    </script>
</body>
</html>
"""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        log_msg(f"HTML 빌드 및 index.html 디스크 파일 출력 완료 (총 키워드 조합: {len(flattened_keywords)}개)", "INFO")
    except Exception as e:
        log_msg(f"⚠️ HTML 템플릿 물리 저장 중 오류 발생: {e}", "ERROR")

# ==========================================
# 6. 메인 크롤러 루프 환경 구성
# ==========================================
log_msg("백그라운드 API 제어용 서버 스레드 분리 가동 개시 준비", "DEBUG")
api_thread = threading.Thread(target=run_api_server, daemon=True)
api_thread.start()

options = Options()
services = Service()
if IS_LINUX:
    log_msg("리눅스(Linux) 환경 감지로 인한 Headless 플래그 및 보호 우회 속성 강제 주입", "INFO")
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
else:
    DDNS_URL = "127.0.0.1:8081"
try:
    log_msg("Selenium 웹드라이버 시동 및 내부 크롬 프로세스 인스턴스 할당 시작", "DEBUG")
    driver = Chrome(options=options, service=services)
    log_msg("Selenium 크롬 웹 드라이버 정상 준비 완료", "INFO")
except Exception as chrome_err:
    log_msg(f"❌ 크롬 웹 드라이버 엔진 실행 프로세스 도중 크리티컬 오류로 중단됨: {chrome_err}", "CRITICAL")
    exit()

backup_data = load_backup_data()
with data_lock:
    config_data = load_keywords_from_file()
    for board, keywords in config_data.items():
        for keyword in keywords:
            combined_key = f"{board}::{keyword}"
            
            loaded_data = backup_data.get(combined_key, [])
            if len(loaded_data) > MAX_DATA_PER_KEYWORD:
                loaded_data = loaded_data[:MAX_DATA_PER_KEYWORD]
                
            all_keywords_data[combined_key] = loaded_data
            log_msg(f"메모리 캐시 변수 초기 데이터 매핑 완료: {combined_key} (수집 누적 글: {len(all_keywords_data[combined_key])}개)", "DEBUG")

with data_lock:
    generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)

log_msg("🎉 통합 미니 게시판 시스템 초기화 완료 (기존 백업 데이터로 대시보드 복원 성공)", "INFO")
log_msg("📡 메인 백그라운드 실시간 모니터링 감시 무한 루프 엔진을 가동합니다.", "INFO")

try:
    is_first_scan = {}
    is_initial_run = True

    while True:
        if not is_initial_run:
            log_msg(f"⏳ 다음 실시간 스캔 쿼리 탐색 주기까지 {CHECK_INTERVAL}초 대기 프로세스 진행", "DEBUG")
            time.sleep(CHECK_INTERVAL)
        
        is_initial_run = False

        with data_lock:
            config_data = load_keywords_from_file()
            board_alert_config = load_board_config()
            
        log_msg("🔍 실시간 주기적 크롤링 스캔 작업 세션 개시", "INFO")
        has_changes = False
        
        for board, keywords in config_data.items():
            board_name = BOARD_MAP.get(board, board)
            
            for keyword in keywords:
                combined_key = f"{board}::{keyword}"
                log_msg(f"   ▶ 순회 작업 진행 타겟 -> [{board_name}] - 키워드: {keyword}", "DEBUG")
                
                with data_lock:
                    if combined_key not in all_keywords_data:
                        all_keywords_data[combined_key] = []
                    board_data = all_keywords_data[combined_key]
                
                if board_data:
                    log_msg(f"      - 기존 캐시 데이터 갱신을 위한 상위 {MAX_POSTS_TO_SYNC_COMMENTS}개 타겟 딥 스캔 진입", "DEBUG")
                    posts_to_sync = board_data[:MAX_POSTS_TO_SYNC_COMMENTS]
                    posts_to_remove = []
                    
                    for idx, old_post in enumerate(posts_to_sync):
                        try:
                            log_msg(f"      [동기화 딥스캔] 글 ID: {old_post['id']} 상세 페이지 갱신 추적 시작", "DEBUG")
                            updated_post = scrape_post_detail(driver, old_post)
                            
                            if updated_post is None:
                                log_msg(f"      [삭제 확정] 글 ID: {old_post['id']}가 원문에서 유실되었습니다. 대시보드 리스트에서 제거 조치합니다.", "INFO")
                                posts_to_remove.append(old_post['id'])
                                continue
                            
                            updated_post['is_new'] = old_post.get('is_new', False) 
                            
                            if (old_post['comment_count'] != updated_post['comment_count'] or 
                                len(old_post['comments']) != len(updated_post['comments']) or
                                old_post['votes'] != updated_post['votes']):
                                
                                log_msg(f"      [변경 사항 감지] 글 ID: {old_post['id']} 메타/댓글 데이터 변경됨. 캐시 즉시 업데이트.", "INFO")
                                with data_lock:
                                    board_data[idx] = updated_post
                                has_changes = True
                        except Exception as sync_ex:
                            log_msg(f"      ⚠️ 기존 글 ID {old_post['id']} 백그라운드 갱신 스킵 (예외 피드백): {sync_ex}", "WARN")
                    
                    if posts_to_remove:
                        with data_lock:
                            all_keywords_data[combined_key] = [p for p in board_data if p['id'] not in posts_to_remove]
                        has_changes = True
                
                try:
                    log_msg(f"      - 새 글 목록 모니터링 수집 쿼리 가동 중...", "DEBUG")
                    new_post_list = get_list_page_posts(driver, board, keyword, page=1)
                except Exception as list_ex:
                    log_msg(f"      ⚠️ [{board_name} - {keyword}] 목록 파싱 실패로 이번 주기 패스 처리: {list_ex}", "WARN")
                    continue
                
                if combined_key not in is_first_scan:
                    is_first_scan[combined_key] = False if board_data else True

                new_posts = []
                if board_data:
                    existing_ids = {post['id'] for post in board_data}
                    for p in new_post_list:
                        if p['id'] in existing_ids: 
                            break
                        new_posts.append(p)
                else:
                    if is_first_scan[combined_key]:
                        log_msg(f"   📦 [{board_name} - {keyword}] 최초 빌드: 리스트의 최신 글 1개만 베이스라인 데이터로 강제 적재합니다.", "INFO")
                        if new_post_list:
                            try:
                                first_post_info = new_post_list[0]
                                post_data = scrape_post_detail(driver, first_post_info)
                                if post_data:
                                    post_data['is_new'] = False
                                    with data_lock:
                                        all_keywords_data[combined_key] = [post_data]
                                    log_msg(f"   📦 [{board_name} - {keyword}] 최초 기준점 빌드 매핑 성공", "INFO")
                            except Exception as e:
                                log_msg(f"      ⚠️ 베이스라인 최신 글 1개 데이터 수집 실패 예외 로그: {e}", "ERROR")
                                
                        is_first_scan[combined_key] = False
                        has_changes = True
                        continue
                    else:
                        new_posts = new_post_list
                
                if new_posts:
                    log_msg(f"   🆕 [{board_name}] 교차 검증을 거친 실시간 신규 새 글 {len(new_posts)}개 탐지 성공!", "INFO")
                        
                    for post_info in reversed(new_posts):
                        try:
                            log_msg(f"   🆕 신규 글 상세 딥 크롤링 프로세스 전개 -> ID: {post_info['id']}", "INFO")
                            post_data = scrape_post_detail(driver, post_info)
                            
                            if post_data is None:
                                continue
                                
                            post_data['is_new'] = True
                            
                            with data_lock:
                                all_keywords_data[combined_key] = [post_data] + all_keywords_data[combined_key]
                                
                                if len(all_keywords_data[combined_key]) > MAX_DATA_PER_KEYWORD:
                                    all_keywords_data[combined_key] = all_keywords_data[combined_key][:MAX_DATA_PER_KEYWORD]
                                    
                                generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)
                            save_backup_data(all_keywords_data)
                            
                            has_video = len(post_data.get('videos', [])) > 0
                            is_alert_enabled = board_alert_config.get(board, {}).get("alert", True)
                            
                            if is_alert_enabled or has_video:
                                video_badge = " [🎬 동영상 포함 강제알림]" if (not is_alert_enabled and has_video) else ""
                                log_msg(f"   🚀 텔레그램 연동 채널 알림 발송을 개시합니다. (게시글 ID: {post_data['id']})", "INFO")
                                telegram_text = (
                                    f"🔔 *[{board_name} - {keyword}]{video_badge} 실시간 새 글!*\n\n"
                                    f"📌 *제목:* {post_data['title']}\n"
                                    f"✍️ *작성자:* {post_data['author']}\n\n"
                                    f"📂 [게시판 확인]({DDNS_URL}#post-{post_data['id']})"
                                )
                                send_telegram_message(telegram_text)
                            else:
                                log_msg(f"      🔕 [{board_name}] 알림 토글 비활성화 상태(동영상 요소 없음) - 텔레그램 발송을 안전하게 생략합니다.", "INFO")
                        except Exception as deep_ex:
                            log_msg(f"      ⚠️ 새 글 상세 크롤링 처리 도중 예외로 인한 패스 스킵 피드백: {deep_ex}", "ERROR")
                    has_changes = True
        
        if has_changes:
            log_msg("🔄 이번 주기 캐시 변경 내역 발생 확인 -> index.html 동적 렌더링 동기화 즉시 갱신 진행", "INFO")
            with data_lock:
                generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)
            save_backup_data(all_keywords_data)
        else:
            log_msg("🔍 이번 턴 실시간 모니터링 감시 주기 종료: 변경 발생 데이터 없음", "DEBUG")

except KeyboardInterrupt:
    log_msg("⛔ 사용자의 KeyboardInterrupt 입력을 감지하여 실시간 모니터링 엔진 시스템을 안전하게 중단합니다.", "WARN")
except Exception as e:
    log_msg(f"🚨 크롤러 런타임 코어 루프 엔진 무너짐 치명적 시스템 에러 발생: {e}", "CRITICAL")
finally:
    log_msg("최종 시스템 할당 리소스 및 메모리 웹 드라이버 인스턴스 반환 절차 개시", "INFO")
    try:
        driver.quit()
        log_msg("Selenium 웹드라이버 엔진 종료 정상 완료", "INFO")
    except Exception as ex:
        log_msg(f"드라이버 인스턴스 해제 시도 실패 또는 이미 프로세스가 꺼져 있습니다: {ex}", "DEBUG")