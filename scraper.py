import time
import random
import re
from urllib.parse import quote, urlparse
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from config import log_msg

def extract_post_id(link):
    if not link: return "0"
    match = re.search(r'document_srl=(\d+)', link)
    if match: return match.group(1)
    path = urlparse(link).path
    match_path = re.search(r'/(\d+)', path)
    if match_path: return match_path.group(1)
    return str(int(time.time()))

def get_list_page_posts(driver, board, keyword, page=1):
    encoded_keyword = quote(keyword)
    list_url = f"https://www.fmkorea.com/index.php?mid={board}&search_target=title_content&search_keyword={encoded_keyword}&page={page}"
    log_msg(f"[정찰조 Selenium] 목록 페이지 진입 시도 -> Board: {board}, Keyword: {keyword}", "DEBUG")
    
    try:
        driver.get(list_url)
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'table.bd_lst, body'))
        )
    except Exception as e:
        log_msg(f"⚠️ 목록 페이지 브라우저 진입 에러: {e}", "ERROR")
        return []
        
    delay = random.uniform(0.5, 1.2)
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
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '.xe_content, .top_area, body'))
        )
    except Exception as drive_err:
        log_msg(f"⚠️ 상세 페이지 브라우저 호출 오류: {drive_err}", "ERROR")
        raise drive_err
        
    delay = random.uniform(0.5, 1.2)
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
