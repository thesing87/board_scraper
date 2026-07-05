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
from urllib.parse import quote, urlparse
from datetime import datetime
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from dotenv import load_dotenv

load_dotenv()

try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

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

IS_LINUX = platform.system() == 'Linux'

if IS_LINUX:
    OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/output')
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    HTML_OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'index.html')
    JSON_BACKUP_FILE = os.path.join(OUTPUT_DIR, 'board_data_backup.json')
    KEYWORDS_FILE = os.path.join(OUTPUT_DIR, 'keywords_config.json')
else:
    HTML_OUTPUT_FILE = 'index.html'
    JSON_BACKUP_FILE = 'board_data_backup.json'
    KEYWORDS_FILE = 'keywords_config.json'

all_keywords_data = {}
data_lock = threading.Lock()

# ==========================================
# 2. 키워드 파일(JSON) I/O 헬퍼 함수
# ==========================================
def load_keywords_from_file():
    if not os.path.exists(KEYWORDS_FILE):
        initial_config = {}
        for board in BOARD_MAP.keys():
            env_str = os.environ.get(f'KEYWORDS_{board.upper()}', '')
            if board == 'car' and not env_str:
                env_str = os.environ.get('KEYWORDS', '')
            initial_config[board] = [k.strip() for k in env_str.split(',') if k.strip()]
        
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(initial_config, f, ensure_ascii=False, indent=4)
        return initial_config
    
    try:
        with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ 키워드 파일 로드 오류: {e}")
        return {board: [] for board in BOARD_MAP.keys()}

def save_keywords_to_file(config_data):
    try:
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"⚠️ 키워드 파일 저장 오류: {e}")
        return False

# ==========================================
# 3. 내장 경량 API 웹 서버
# ==========================================
class KeywordAPIServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        global all_keywords_data
        if self.path.startswith('/api/keyword'):
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                params = json.loads(post_data)
                action = params.get('action')
                keyword = params.get('keyword', '').strip()
                password = params.get('password', '').strip()
                board = params.get('board', 'car').strip()
                
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                
                if password != ADMIN_PASSWORD:
                    response_data = {'success': False, 'message': '❌ 인증 비밀번호가 일치하지 않습니다.'}
                    self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
                    return
                
                if not keyword: return

                with data_lock:
                    current_config = load_keywords_from_file()
                    if board not in current_config:
                        current_config[board] = []
                    
                    combined_key = f"{board}::{keyword}"
                    
                    if action == 'add':
                        if keyword in current_config[board]:
                            msg = '이미 존재하는 키워드입니다.'
                        else:
                            current_config[board].append(keyword)
                            save_keywords_to_file(current_config)
                            if combined_key not in all_keywords_data:
                                all_keywords_data[combined_key] = []
                            msg = f'🎯 {BOARD_MAP.get(board, board)} -> [{keyword}] 추가되었습니다.'
                            
                    elif action == 'delete':
                        if keyword in current_config[board]:
                            current_config[board].remove(keyword)
                            save_keywords_to_file(current_config)
                            if combined_key in all_keywords_data:
                                del all_keywords_data[combined_key]
                            msg = f'🗑️ {BOARD_MAP.get(board, board)} -> [{keyword}] 삭제되었습니다.'
                        else:
                            msg = '존재하지 않는 키워드입니다.'
                    
                    generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)
                    save_backup_data(all_keywords_data)

                response_data = {'success': True, 'message': msg}
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                try:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode('utf-8'))
                except: pass

def run_api_server():
    server_address = ('', 8080)
    httpd = HTTPServer(server_address, KeywordAPIServer)
    print("🌐 [API Server] 키워드 제어 웹서버가 8080포트에서 가동되었습니다.")
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
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def load_backup_data():
    if os.path.exists(JSON_BACKUP_FILE):
        try:
            with open(JSON_BACKUP_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_backup_data(all_keywords_data):
    try:
        with open(JSON_BACKUP_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_keywords_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ 데이터 백업 저장 실패: {e}")

def get_list_page_posts(driver, board, keyword, page=1):
    encoded_keyword = quote(keyword)
    list_url = f"https://www.fmkorea.com/index.php?mid={board}&search_target=title_content&search_keyword={encoded_keyword}&page={page}"
    driver.get(list_url)
    time.sleep(random.uniform(5.0, 7.0))
    
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
    return post_list

def scrape_post_detail(driver, post_info):
    link = post_info['link']
    title = post_info['title']
    author = post_info['author']
    date = post_info['date']
    post_id = post_info.get('id', extract_post_id(link))
    
    driver.get(link)
    time.sleep(random.uniform(4.0, 7.0))
    
    detail_soup = BeautifulSoup(driver.page_source, 'html.parser')
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
    except: pass
    
    content_area = detail_soup.select_one('.xe_content')
    paragraphs = []
    images = []
    videos = []  
    
    if content_area:
        for a_tag in content_area.find_all('a'):
            a_tag['target'] = '_blank'
            a_tag['style'] = "color: #1877f2; text-decoration: underline; font-weight: bold;"

        for video in content_area.select('video'):
            source = video.select_one('source')
            src = video.get('src') or (source.get('src') if source else None)
            if src:
                if src.startswith('//'): src = 'https:' + src
                elif src.startswith('/'): src = 'https://www.fmkorea.com' + src
                videos.append({'type': 'video', 'src': src})
        
        for iframe in content_area.select('iframe'):
            src = iframe.get('src')
            if src:
                if src.startswith('//'): src = 'https:' + src
                videos.append({'type': 'iframe', 'src': src})

        for img in content_area.select('img'):
            img_src = img.get('src') or img.get('data-original')
            if img_src:
                if img_src.startswith('//'): img_src = 'https:' + img_src
                elif img_src.startswith('/'): img_src = 'https://www.fmkorea.com' + img_src
                images.append(img_src)

        for img_tag in content_area.find_all('img'):
            img_tag.extract()

        for iframe_tag in content_area.find_all('iframe'):
            iframe_tag.extract()

        for trash in content_area.select('.mejs__offscreen, .mejs__poster-img, .mejs__time-total, .mejs__currenttime, .mejs__duration, button, svg, ul, meta'):
            trash.extract()
            
        for a_trash in content_area.select('a.mejs__horizontal-volume-slider'):
            a_trash.extract()

        for v_tag in content_area.find_all(['video', 'source']):
            v_tag.extract()

        for br in content_area.find_all("br"): br.replace_with("\n")
        for block in content_area.find_all(['p', 'div', 'li', 'h1', 'h2', 'h3']): 
            block.insert_after('\n')
            block.unwrap()
            
        raw_text = content_area.decode_contents()
        raw_text = re.sub(r'<script.*?>.*?</script>', '', raw_text, flags=re.DOTALL)
        raw_text = re.sub(r'<!--.*?-->', '', raw_text, flags=re.DOTALL) 
        raw_text = raw_text.replace('\\', '')
        
        lines = [line.strip() for line in raw_text.split('\n')]
        
        empty_count = 0
        for line in lines:
            if line == '':
                empty_count += 1
                if empty_count <= 2: paragraphs.append(line)
            else:
                empty_count = 0
                paragraphs.append(line)
        
        while paragraphs and paragraphs[0] == '': paragraphs.pop(0)
        while paragraphs and paragraphs[-1] == '': paragraphs.pop()
    
    comments = []
    comment_items = detail_soup.select('.fdb_lst_ul > li.fdb_itm, ul#comment > li.fdb_itm, .fdb_lst > li.fdb_itm')
    if not comment_items: comment_items = detail_soup.select('.fdb_lst_ul > li')

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
        margin_left = "0px"
        match = re.search(r'(?:margin-left|padding-left)\s*:\s*(\d+px)', style)
        if match: margin_left = match.group(1)
        elif 'indent' in item.get('class', []): margin_left = "30px"
            
        comments.append({'author': c_author, 'date': c_date, 'votes': c_votes, 'content': c_paragraphs, 'margin_left': margin_left})
    
    return {
        'id': post_id, 'title': title, 'author': author, 'date': date, 'views': views, 'votes': votes,
        'comment_count': comment_count, 'link': link, 'content': paragraphs, 'images': images, 'videos': videos, 'comments': comments
    }

# ==========================================
# 5. UI 빌더 (마우스 드래그 스크롤 완벽 지원)
# ==========================================
def generate_multiboard_html(all_keywords_data, output_file):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tabs_html = ""
    boards_html = ""
    
    active_config = load_keywords_from_file()
    
    flattened_keywords = []
    for board, keywords in active_config.items():
        for keyword in keywords:
            combined_key = f"{board}::{keyword}"
            board_data = all_keywords_data.get(combined_key, [])
            
            new_posts_count = sum(1 for post in board_data if post.get('is_new', False))
            
            flattened_keywords.append({
                'board': board,
                'keyword': keyword,
                'combined_key': combined_key,
                'board_data': board_data,
                'new_posts_count': new_posts_count,
                'total_count': len(board_data)
            })
    
    flattened_keywords.sort(key=lambda x: (x['new_posts_count'] > 0, x['new_posts_count'], x['total_count']), reverse=True)
    
    for global_idx, item in enumerate(flattened_keywords):
        board = item['board']
        keyword = item['keyword']
        board_data = item['board_data']
        new_posts_count = item['new_posts_count']
        
        board_name = BOARD_MAP.get(board, board)
        active_class = "active" if global_idx == 0 else ""
        display_style = "block" if global_idx == 0 else "none"
        
        new_tag_in_tab = f'<span class="new-dot" id="dot-board-{global_idx}">🔴 </span>' if new_posts_count > 0 else f'<span class="new-dot" id="dot-board-{global_idx}" style="display:none;">🔴 </span>'
        
        tab_clean_text = f"[{board_name}] {keyword} ({len(board_data)})"
        
        tabs_html += f"""
        <div class="tab-wrapper" data-board-id="board-{global_idx}">
            <button class="tab-btn {active_class}" data-tab-name="{tab_clean_text}" onclick="openTab(event, 'board-{global_idx}')">{new_tag_in_tab}{tab_clean_text}</button>
            <button class="tab-del-btn" onclick="manageKeyword('delete', '{keyword}', '{board}')">×</button>
        </div>
        """
        
        # 반복 사용할 공통 페이지네이션 마크업 생성 (상단/하단 배치용)
        # 클래스명으로 상/하단 버튼을 동시 제어할 수 있도록 구조 유지
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
                content_html = "".join([f"<p>{text}</p>" if text else "<p style='margin:0; height:12px;'></p>" for text in post['content']])
                images_html = "".join([f'<img src="{img_src}" alt="첨부이미지">' for img_src in post['images']])
                
                videos_html = ""
                for v in post.get('videos', []):
                    if v['type'] == 'video':
                        videos_html += f'<video src="{v["src"]}" controls style="width: 100%; max-width: 100%; margin-top: 8px; border-radius: 6px;"></video>'
                    elif v['type'] == 'iframe':
                        videos_html += f'<div style="position: relative; padding-bottom: 56.25%; height: 0; margin-top: 8px;"><iframe src="{v["src"]}" frameborder="0" allowfullscreen style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border-radius: 6px;"></iframe></div>'
                
                is_new = post.get('is_new', False)
                card_class = "post-card new-post" if is_new else "post-card"
                new_badge = '<span class="new-badge">NEW</span>' if is_new else ''
                sync_badge = '<span class="sync-badge">🔄 동기화중</span>' if post_idx < MAX_POSTS_TO_SYNC_COMMENTS else ""
                
                comments_html = ""
                if post['comments']:
                    comments_html += f'<div class="post-comments-section"><h3>💬 댓글 ({post["comment_count"]})</h3>'
                    for c in post['comments']:
                        c_content_html = "".join([f"<p style='margin: 3px 0;'>{t}</p>" if t else "<br>" for t in c['content']])
                        is_reply = c['margin_left'] != "0px"
                        indent_class = "comment-reply" if is_reply else ""
                        reply_icon = '<span style="color:#adb5bd; margin-right:5px; font-weight:bold;">└</span>' if is_reply else ''
                        
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
                        <div class="post-images">{images_html}{videos_html}</div>
                        <div style="margin-top: 15px; display: flex; gap: 10px;">
                            <a href="{post['link']}" target="_blank" class="original-link-btn" onclick="event.stopPropagation();">🔗 에프엠코리아 원문</a>
                        </div>
                        {comments_html}
                    </div>
                </div>
                """
        
        # 🎯 [요청 반영] 게시글 목록 컨테이너 바로 밑(하단)에도 페이지네이션 추가
        board_content += f"""
            </div>
            {pagination_markup}
        </div>
        """
        boards_html += board_content

    board_options = "".join([f'<option value="{k}">{v}</option>' for k, v in BOARD_MAP.items()])

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, minimum-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>통합 멀티 키워드 미니 게시판</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Malgun Gothic', sans-serif; background-color: #f0f2f5; margin: 0; padding: 10px; color: #1c1e21; box-sizing: border-box; }}
        .container {{ width: 100%; max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; }}
        .admin-panel {{ background: #fff; padding: 12px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; flex-direction: column; gap: 8px; }}
        .admin-title {{ font-size: 13px; font-weight: bold; color: #1c1e21; margin-bottom: 2px; }}
        .admin-row {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
        .admin-select {{ padding: 8px; border: 1px solid #ccd0d5; border-radius: 6px; font-size: 13px; background: white; }}
        .admin-input {{ flex: 1; min-width: 120px; padding: 8px 12px; border: 1px solid #ccd0d5; border-radius: 6px; font-size: 13px; outline: none; }}
        .admin-btn {{ background: #1877f2; color: #fff; border: none; padding: 0 16px; font-size: 13px; font-weight: bold; border-radius: 6px; cursor: pointer; white-space: nowrap; height: 36px; }}
        
        .refresh-btn {{ background: #28a745; color: #fff; border: none; padding: 0 14px; font-size: 13px; font-weight: bold; border-radius: 6px; cursor: pointer; white-space: nowrap; height: 36px; display: inline-flex; align-items: center; gap: 4px; }}
        .refresh-btn:hover {{ background: #218838; }}
        
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
        
        .post-card {{ background: white; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); word-break: break-all; transition: border 0.2s ease; }}
        .post-card.new-post {{ border: 2px solid #1877f2; }}
        .new-badge {{ display: inline-block; background: #1877f2; color: white; font-size: 10px; padding: 2px 6px; border-radius: 10px; margin-left: 5px; }}
        .sync-badge {{ display: inline-block; background: #28a745; color: white; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; }}
        .post-header {{ border-bottom: 1px solid #e4e6eb; padding-bottom: 8px; margin-bottom: 12px; }}
        .post-title {{ font-size: 16px; font-weight: bold; margin-bottom: 8px; color: #1877f2; line-height: 1.4; }}
        .post-meta {{ font-size: 12px; color: #65676b; display: flex; flex-wrap: wrap; gap: 10px; }}
        .post-content {{ font-size: 14px; line-height: 1.6; color: #1c1e21; }}
        .post-images img {{ width: 100%; height: auto; border-radius: 6px; margin-top: 8px; }}
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

        /* 🎯 [요청 반영] 언제나 화면 우하단에 고정되어 떠 있는 Top 플로팅 버튼 스타일 */
        .scroll-top-btn {{
            position: fixed;
            bottom: 25px;
            right: 25px;
            width: 48px;
            height: 48px;
            background-color: #1877f2;
            color: white;
            border: none;
            border-radius: 50%;
            font-size: 20px;
            font-weight: bold;
            cursor: pointer;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
            z-index: 9999;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
            opacity: 0; /* 기본 상태 숨김 (스크롤 시 활성화) */
            visibility: hidden;
        }}
        .scroll-top-btn.visible {{
            opacity: 1;
            visibility: visible;
        }}
        .scroll-top-btn:hover {{
            background-color: #145dbf;
            transform: translateY(-3px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.3);
        }}
    </style>
    
    <script>
        (function() {{
            let styleRules = "";
            for (let i = 0; i < localStorage.length; i++) {{
                const key = localStorage.key(i);
                if (key.startsWith('dot_hidden_') && localStorage.getItem(key) === 'true') {{
                    const tabName = key.replace('dot_hidden_', '');
                    styleRules += `.tab-btn[data-tab-name="${{tabName}}"] .new-dot {{ display: none !important; }}\\n`;
                }}
                if (key.startsWith('badges_cleared_') && localStorage.getItem(key) === 'true') {{
                    const tabName = key.replace('badges_cleared_', '');
                    styleRules += `.tab-content[data-tab-name="${{tabName}}"] .new-badge {{ display: none !important; }}\\n`;
                    styleRules += `.tab-content[data-tab-name="${{tabName}}"] .post-card.new-post {{ border: none !important; }}\\n`;
                }}
            }}
            if (styleRules) {{
                const styleEl = document.createElement('style');
                styleEl.innerHTML = styleRules;
                document.head.appendChild(styleEl);
            }}
        }})();
    </script>
    
    <script>
        const POSTS_PER_PAGE = 10;

        function getStorageKey(prefix, boardId) {{
            const btn = document.querySelector('.tab-wrapper[data-board-id="' + boardId + '"] .tab-btn');
            const txt = btn ? btn.getAttribute('data-tab-name') : boardId;
            return prefix + '_' + txt;
        }}

        function refreshCurrentTab() {{
            const activeTabContent = document.querySelector('.tab-content[style*="display: block"]');
            if (activeTabContent) {{
                const currentBoardId = activeTabContent.id;
                const currentPage = activeTabContent.getAttribute('data-current-page') || '1';
                
                sessionStorage.setItem('last_active_board', currentBoardId);
                sessionStorage.setItem('last_active_page', currentPage);
            }}
            window.location.reload();
        }}

        // 🎯 상/하단 양쪽 페이지네이션 엘리먼트들을 동시에 업데이트하도록 대폭 수정
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
            
            // 상단 컴포넌트와 하단 컴포넌트의 글자 및 버튼 상태를 전부 동기화
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

        function openTab(evt, boardId) {{
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tab-content");
            for (i = 0; i < tabcontent.length; i++) {{ tabcontent[i].style.display = "none"; }}
            tablinks = document.getElementsByClassName("tab-btn");
            for (i = 0; i < tablinks.length; i++) {{ tablinks[i].className = tablinks[i].className.replace(" active", ""); }}
            
            const targetBoard = document.getElementById(boardId);
            targetBoard.style.display = "block";
            if (evt) evt.currentTarget.className += " active";
            
            const vKey = getStorageKey('visit', boardId);
            const dKey = getStorageKey('dot_hidden', boardId);
            const bKey = getStorageKey('badges_cleared', boardId);
            
            let visitCount = parseInt(localStorage.getItem(vKey) || '0');
            visitCount += 1;
            localStorage.setItem(vKey, visitCount);
            
            const targetDot = document.getElementById('dot-' + boardId);
            if (targetDot) targetDot.style.display = 'none';
            localStorage.setItem(dKey, 'true');
            
            if (visitCount >= 2) {{
                localStorage.setItem(bKey, 'true');
                localStorage.setItem(getStorageKey('clear_time', boardId), Date.now());
                
                const newBadges = targetBoard.querySelectorAll('.new-badge');
                newBadges.forEach(badge => badge.remove());
                
                const newCards = targetBoard.querySelectorAll('.post-card.new-post');
                newCards.forEach(card => {{
                    card.classList.remove('new-post');
                    card.style.border = 'none';
                }});
            }}
            
            updatePagination(boardId);
        }}

        function restoreAllTabsState() {{
            const allContents = document.querySelectorAll('.tab-content');
            
            allContents.forEach(content => {{
                const boardId = content.id;
                const dKey = getStorageKey('dot_hidden', boardId);
                const bKey = getStorageKey('badges_cleared', boardId);
                const tKey = getStorageKey('clear_time', boardId);
                
                if (localStorage.getItem(dKey) === 'true') {{
                    const targetDot = document.getElementById('dot-' + boardId);
                    if (targetDot) targetDot.style.display = 'none';
                }}
                
                const clearTime = parseInt(localStorage.getItem(tKey) || '0');
                if (localStorage.getItem(bKey) === 'true' || clearTime > 0) {{
                    const newCards = content.querySelectorAll('.post-card');
                    newCards.forEach(card => {{
                        if (card.getAttribute('data-is-new') === 'true') {{
                            card.classList.remove('new-post');
                            card.style.border = 'none';
                            const badge = card.querySelector('.new-badge');
                            if (badge) badge.remove();
                        }}
                    }});
                }}
            }});
            
            const activeContent = document.querySelector('.tab-content[style*="display: block"]');
            if (activeContent) {{
                const boardId = activeContent.id;
                const vKey = getStorageKey('visit', boardId);
                const dKey = getStorageKey('dot_hidden', boardId);
                
                if (!localStorage.getItem(vKey)) {{
                    localStorage.setItem(vKey, '1');
                }}
                
                const targetDot = document.getElementById('dot-' + boardId);
                if (targetDot) targetDot.style.display = 'none';
                localStorage.setItem(dKey, 'true');
                
                updatePagination(boardId);
            }}
        }}

        // 🎯 [요청 반영] 플로팅 Top 버튼 클릭 시 최상단으로 부드럽게 스크롤해주는 함수
        function scrollToTop() {{
            window.scrollTo({{ top: 0, behavior: 'smooth' }});
        }}

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

            // 🎯 스크롤 위치에 따라 Top 플로팅 버튼의 표시 여부를 제어하는 리스너 등록
            const topBtn = document.getElementById('floating-top-btn');
            window.addEventListener('scroll', () => {{
                if (window.scrollY > 300) {{
                    topBtn.classList.add('visible');
                }} else {{
                    topBtn.classList.remove('visible');
                }}
            }});
        }});

        function manageKeyword(action, targetKw, targetBoard) {{
            let kw = targetKw || document.getElementById('new-kw-input').value.trim();
            let pwd = document.getElementById('admin-pwd-input').value.trim();
            let board = targetBoard || document.getElementById('board-select').value;
            
            if (!kw) {{ alert('키워드를 입력해 주세요.'); return; }}
            if (!pwd) {{ alert('인증 관리자 비밀번호를 입력해야 합니다.'); return; }}
            
            if (action === 'delete') {{
                if (!confirm("'" + kw + "' 키워드를 정말 삭제하시겠습니까?")) return;
            }}
            
            const btn = event ? event.target : null;
            if (btn) btn.disabled = true;
            
            if (action === 'delete') {{
                for (let i = localStorage.length - 1; i >= 0; i--) {{
                    const key = localStorage.key(i);
                    if (key.includes(kw)) {{
                        localStorage.removeItem(key);
                    }}
                }}
            }}

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
    <div class="container">
        <div class="admin-panel">
            <div class="admin-title">🛠️ 키워드 실시간 모니터링 관리 패널</div>
            <div class="admin-row">
                <select id="board-select" class="admin-select">
                    {board_options}
                </select>
                <input type="text" id="new-kw-input" class="admin-input" placeholder="추가할 키워드 입력">
                <input type="password" id="admin-pwd-input" class="admin-input" style="max-width:140px;" placeholder="관리자 암호">
                <button class="admin-btn" onclick="manageKeyword('add')">➕ 등록</button>
                <button class="refresh-btn" onclick="refreshCurrentTab()">🔄 현재 키워드 새로고침</button>
            </div>
        </div>

        <div class="tab-container" id="tab-scroll-container">
            {tabs_html}
        </div>

        {boards_html}
    </div>

    <!-- 🎯 [요청 반영] 화면 우하단 고정 플로팅 '맨 위로' 버튼 생성 -->
    <button id="floating-top-btn" class="scroll-top-btn" onclick="scrollToTop()" title="맨 위로 이동">▲</button>

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
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
# ==========================================
# 6. 메인 크롤러 루프 환경 구성
# ==========================================
api_thread = threading.Thread(target=run_api_server, daemon=True)
api_thread.start()

options = Options()
services = Service()
if IS_LINUX:
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')

try:
    driver = Chrome(options=options, service=services)
except Exception as chrome_err:
    print(f"❌ 크롬 실행 실패: {chrome_err}")
    exit()

backup_data = load_backup_data()
with data_lock:
    config_data = load_keywords_from_file()
    for board, keywords in config_data.items():
        for keyword in keywords:
            combined_key = f"{board}::{keyword}"
            all_keywords_data[combined_key] = backup_data.get(combined_key, [])

with data_lock:
    generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)

print(f"\n🎉 통합 게시판 초기화 완료 (과거 저장된 데이터로 index.html 복원 완료)")
print(f"📡 실시간 모니터링 준비 완료. 데이터 스캔 시점에 실시간 갱신됩니다.")

try:
    is_first_scan = {}
    is_initial_run = True

    while True:
        if not is_initial_run:
            print(f"\n⏳ {CHECK_INTERVAL}초 대기 중...")
            time.sleep(CHECK_INTERVAL)
        
        is_initial_run = False

        with data_lock:
            config_data = load_keywords_from_file()
            
        now_str = datetime.now().strftime('%H:%M:%S')
        print(f"\n🔍 [{now_str}] 실시간 모니터링 시작")
        has_changes = False
        
        for board, keywords in config_data.items():
            board_name = BOARD_MAP.get(board, board)
            
            for keyword in keywords:
                combined_key = f"{board}::{keyword}"
                print(f"   ▶ 작업 중: [{board_name}] - {keyword}")
                
                with data_lock:
                    if combined_key not in all_keywords_data:
                        all_keywords_data[combined_key] = []
                    board_data = all_keywords_data[combined_key]
                
                if board_data:
                    print(f"      - 댓글 동기화 및 상태 보존 진행 중 ({MAX_POSTS_TO_SYNC_COMMENTS}개 대상)")
                    posts_to_sync = board_data[:MAX_POSTS_TO_SYNC_COMMENTS]
                    for idx, old_post in enumerate(posts_to_sync):
                        try:
                            updated_post = scrape_post_detail(driver, old_post)
                            updated_post['is_new'] = old_post.get('is_new', False) 
                            
                            if (old_post['comment_count'] != updated_post['comment_count'] or 
                                len(old_post['comments']) != len(updated_post['comments']) or
                                old_post['votes'] != updated_post['votes']):
                                
                                with data_lock:
                                    board_data[idx] = updated_post
                                has_changes = True
                        except: pass
                
                try:
                    print(f"      - 새 글 확인 중...")
                    new_post_list = get_list_page_posts(driver, board, keyword, page=1)
                except: continue
                
                if combined_key not in is_first_scan:
                    is_first_scan[combined_key] = False if board_data else True

                new_posts = []
                if board_data:
                    existing_ids = {post['id'] for post in board_data}
                    for p in new_post_list:
                        if p['id'] in existing_ids: break
                        new_posts.append(p)
                else:
                    if is_first_scan[combined_key]:
                        print(f"   📦 [{board_name} - {keyword}] 최초 빌드: 가장 최신 글 1개만 베이스라인으로 등록합니다.")
                        if new_post_list:
                            try:
                                first_post_info = new_post_list[0]
                                post_data = scrape_post_detail(driver, first_post_info)
                                post_data['is_new'] = False
                                with data_lock:
                                    all_keywords_data[combined_key] = [post_data]
                            except Exception as e:
                                print(f"      ⚠️ 최신 글 1개 수집 중 오류: {e}")
                                
                        is_first_scan[combined_key] = False
                        has_changes = True
                        continue
                    else:
                        new_posts = new_post_list
                
                if new_posts:
                    print(f"   🆕 [{board_name}] 실시간 새 글 {len(new_posts)}개 발견!")
                        
                    for post_info in reversed(new_posts):
                        try:
                            post_data = scrape_post_detail(driver, post_info)
                            post_data['is_new'] = True
                            
                            with data_lock:
                                all_keywords_data[combined_key] = [post_data] + all_keywords_data[combined_key]
                                generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)
                            save_backup_data(all_keywords_data)
                            
                            telegram_text = (
                                f"🔔 *[{board_name} - {keyword}] 실시간 새 글!*\n\n"
                                f"📌 *제목:* {post_data['title']}\n"
                                f"✍️ *작성자:* {post_data['author']}\n\n"
                                f"📂 [게시판 확인]({DDNS_URL}#post-{post_data['id']})"
                            )
                            send_telegram_message(telegram_text)
                        except Exception as e: pass
                    has_changes = True
        
        if has_changes:
            with data_lock:
                generate_multiboard_html(all_keywords_data, HTML_OUTPUT_FILE)
            save_backup_data(all_keywords_data)

except KeyboardInterrupt:
    print(f"\n\n⛔ 모니터링 중단.")
except Exception as e:
    print(f"🚨 오류 발생: {e}")
finally:
    try: driver.quit()
    except: pass