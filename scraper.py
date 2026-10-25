import time
import random
import re
from urllib.parse import quote, urlparse
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from config import log_msg
from sanitize import sanitize_tree
from embeds import convert_x_embeds

def extract_post_id(link):
    if not link: return "0"
    match = re.search(r'document_srl=(\d+)', link)
    if match: return match.group(1)
    path = urlparse(link).path
    match_path = re.search(r'/(\d+)', path)
    if match_path: return match_path.group(1)
    return None

class BlockedError(Exception):
    """목록 페이지가 정상 게시판 화면이 아님 (접속 차단·보안 확인·점검 페이지 등으로 추정)"""

DELETED_PAGE_PHRASES =("삭제된 글입니다", "삭제된 문서입니다", "존재하지 않습니다", "존재하지 않는", "권한이 없습니다")

def parse_count(text):
    """'1,234'처럼 표시된 숫자 문자열을 정수로 변환 (숫자가 없으면 0)"""
    digits = re.sub(r'[^\d]', '', str(text or ''))
    return int(digits) if digits else 0

def get_list_page_posts(driver, board, keyword, page=1):
    encoded_keyword = quote(keyword)
    list_url = f"https://www.fmkorea.com/index.php?mid={board}&search_target=title_content&search_keyword={encoded_keyword}&page={page}"
    # 페이지 로드 실패는 호출한 쪽(메인 루프)에서 키워드 정보와 함께 한 번만 기록
    driver.get(list_url)
    WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'table.bd_lst, body'))
    )
    time.sleep(random.uniform(0.5, 1.2))
    
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    if not soup.select_one('table.bd_lst'):
        # 검색 결과가 없을 때도 게시판 목록 틀(.bd_lst_wrp)과 안내 문구는 있음. 틀 자체가 없으면 정상 화면이 아님
        if soup.select_one('.bd_lst_wrp') and '등록된 글이 없습니다' in soup.get_text():
            log_msg(f"[수집] 목록 {board}/{keyword}: 0건 (검색 결과 없음)", "DEBUG")
            return []
        page_title = (driver.title or '').strip()[:60] or '제목 없음'
        raise BlockedError(f"게시판 목록이 아닌 페이지 응답 (제목: {page_title})")
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
            if not post_id:
                log_msg(f"[수집] 글 ID 추출 불가로 건너뜀: {link}", "WARN")
                continue

            # 목록 행에 있는 댓글·조회·추천 수. 댓글 수 변화로 상세 페이지를 다시 열지 판단함 (댓글 0개면 표시 없음)
            reply_num = post.select_one('td.title .replyNum')
            views_tag = post.select_one('td.m_no:not(.m_no_voted)')
            votes_tag = post.select_one('td.m_no_voted')
            post_list.append({
                'link': link, 'title': title, 'author': author, 'date': date, 'id': post_id,
                'list_comment_count': parse_count(reply_num.text) if reply_num else 0,
                'list_views': views_tag.text.strip() if views_tag else None,
                'list_votes': votes_tag.text.strip() if votes_tag else None,
            })

    log_msg(f"[수집] 목록 {board}/{keyword}: {len(post_list)}건", "DEBUG")
    return post_list

def scrape_post_detail(driver, post_info):
    link = post_info['link']
    title = post_info['title']
    author = post_info['author']
    date = post_info['date']
    post_id = post_info.get('id', extract_post_id(link))
    

    # 페이지 로드 실패는 호출한 쪽(메인 루프)에서 키워드 정보와 함께 한 번만 기록
    driver.get(link)
    WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, '.xe_content, .top_area, body'))
    )
    time.sleep(random.uniform(0.5, 1.2))
    
    page_source = driver.page_source
    detail_soup = BeautifulSoup(page_source, 'html.parser')

    content_area = detail_soup.select_one('.xe_content')
    if not content_area:
        # 본문이 있는 정상 글에서는 본문/댓글 속 문구로 인한 오탐을 막기 위해, 본문이 없을 때만 삭제 문구를 검사
        # 실제 삭제 글 페이지: 제목 "삭제된 글입니다.", 본문 "해당 문서가 존재하지 않습니다."
        if any(phrase in page_source for phrase in DELETED_PAGE_PHRASES):
            return None
        raise Exception("본문(.xe_content) 없음 - 일시적 로드 실패 추정")
    
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
    except Exception as meta_err:
        log_msg(f"[수집] #{post_id} 조회/추천/댓글 수 일부 파싱 실패: {meta_err}", "DEBUG")
    
    paragraphs = []
    video_list = []
    if content_area:
        for trash in content_area.select('.mejs__offscreen, .mejs__poster, .mejs__poster-img, .mejs__time-total, .mejs__currenttime, .mejs__duration, .mejs__controls, button, svg, ul, meta'):
            trash.extract()
            
        for a_trash in content_area.select('a.mejs__horizontal-volume-slider'):
            a_trash.extract()

        for a_tag in content_area.find_all('a'):
            a_tag['target'] = '_blank'
            a_tag['style'] = "color: #1877f2; text-decoration: underline; font-weight: bold;"

        for wrapper in content_area.select('.auto_media_wrapper'):
            if wrapper.get('style'): del wrapper['style']
            wrapper['style'] = "width: 100% !important; max-width: 100% !important; height: auto !important; display: block; margin-bottom: 10px;"

        for hk in content_area.select('.height_keep'):
            if hk.get('style'): del hk['style']
            hk['style'] = "padding: 0 !important; padding-bottom: 0 !important; width: 100% !important; max-width: 100% !important; height: auto !important; aspect-ratio: 16 / 9 !important; display: block;"

        for mejs in content_area.select('.mejs__container, .mejs__video, .mejs__inner, .mejs__mediaelement'):
            if mejs.get('style'): del mejs['style']
            if mejs.get('width'): del mejs['width']
            if mejs.get('height'): del mejs['height']
            mejs['style'] = "width: 100% !important; max-width: 100% !important; height: auto !important; aspect-ratio: 16 / 9 !important;"

        for empty_div in content_area.select('div[style*="height:12px"], div[style*="height: 12px"]'):
            empty_div.extract()
            
        for video in content_area.select('video'):
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
            
            ori_w = int(video.get('data-original-width', 0) or video.get('data-x-width', 0) or 0)
            ori_h = int(video.get('data-original-height', 0) or video.get('data-x-height', 0) or 0)
            
            if ori_h > ori_w and ori_w > 0:
                video['style'] = (
                    "width: 100% !important; max-width: 450px !important; "
                    "aspect-ratio: 9 / 16 !important; height: auto !important; "
                    "max-height: 75vh !important; background-color: #000; "
                    "margin: 10px auto !important; border-radius: 12px; "
                    "object-fit: contain; display: block;"
                )
            else:
                video['style'] = (
                    "width: 100% !important; max-width: 100% !important; "
                    "aspect-ratio: 16 / 9 !important; height: auto !important; "
                    "border-radius: 8px; object-fit: contain; display: block; margin: 10px 0;"
                )
        
        for iframe in content_area.select('iframe'):
            src = iframe.get('src')
            if src:
                if src.startswith('//'): src = 'https:' + src
                video_list.append(src)
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
            

        # X(트위터) '링크 자동 변환 중' 임시 상자를 트윗 카드로 교체 (페이지 스크립트가 변환하기 전에 수집되므로)
        converted = convert_x_embeds(detail_soup, content_area)
        if converted:
            log_msg(f"[수집] #{post_id} X 트윗 카드 변환 {converted}건", "DEBUG")

        sanitize_tree(content_area)

        for br in content_area.find_all("br"):
            br.replace_with("\n")
            
        for block in content_area.find_all(['p', 'div', 'li', 'h1', 'h2', 'h3']): 
            block.insert_after('\n')
            
        raw_html = content_area.decode_contents()
        raw_html = re.sub(r'<script.*?>.*?</script>', '', raw_html, flags=re.DOTALL)
        raw_html = re.sub(r'<!--.*?-->', '', raw_html, flags=re.DOTALL)
        
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

            sanitize_tree(c_content_area)
            for br in c_content_area.find_all("br"): br.replace_with("\n")
            for block in c_content_area.find_all(['p', 'div', 'li']):
                block.insert_after('\n')
                block.unwrap()
            
            c_raw_text = c_content_area.decode_contents()
            c_raw_text = re.sub(r'<!--.*?-->', '', c_raw_text, flags=re.DOTALL)
            
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
    
    log_msg(f"[수집] 상세 #{post_id}: 이미지 {img_count}, 동영상 {len(video_list)}, 댓글 {len(comments)}", "DEBUG")
    return {
        'id': post_id, 'title': title, 'author': author, 'date': date, 'views': views, 'votes': votes,
        'comment_count': comment_count, 'link': link, 'content': paragraphs, 'images': [], 'videos': video_list, 'comments': comments
    }
