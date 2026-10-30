"""디시인사이드 갤러리 수집기 (scraper.py의 에펨코리아 수집기와 같은 형태의 값을 돌려줌).

- 카테고리 키는 'dc:갤러리id', 글 ID는 'dc-갤러리id-글번호' (sites.py)
- 디시 이미지는 디시 페이지가 아닌 곳에서는 열리지 않으므로, 크롬이 받은 본문 이미지 파일을 저장해 보여줌 (images.py).
  꺼내지 못한 이미지는 원문으로 가는 안내 링크로 바꿔 저장
"""
import re
import time
import base64
import random
from urllib.parse import quote
from bs4 import BeautifulSoup
from selenium.common.exceptions import UnexpectedAlertPresentException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from config import log_msg, short_err
from images import save_post_image, clear_post_images, MAX_IMAGES_PER_POST
from scraper import BlockedError, parse_count, content_lines, comment_lines
from sites import dc_gallery, dc_post_id

BASE_URL = 'https://gall.dcinside.com'
# 삭제됐거나 없는 글은 /derror/deleted/... 안내 페이지로 넘어감
DELETED_URL_MARK = '/derror/deleted/'
DELETED_PAGE_PHRASES = ('삭제했거나 존재하지 않는', '삭제된 게시물', '존재하지 않는 게시물')
# 이미지·동영상 대신 넣는 원문 링크 모양 (에펨코리아 본문 링크와 같게)
LINK_STYLE = "color: #1877f2; text-decoration: underline; font-weight: bold;"
# 저장한 본문 이미지 모양 (에펨코리아 본문 이미지와 같게)
IMAGE_STYLE = "width: 100%; height: auto; border-radius: 6px; margin-top: 8px; display: block;"
# 본문 이미지가 다 받아질 때까지 기다리는 최대 시간
IMAGE_WAIT_SECONDS = 6

def list_url(gallery, keyword=None, page=1):
    url = f"{BASE_URL}/board/lists/?id={quote(gallery)}"
    if keyword:
        url += f"&s_type=search_subject_memo&s_keyword={quote(keyword)}"
    return url + (f"&page={page}" if page > 1 else '')

def view_url(gallery, no):
    return f"{BASE_URL}/board/view/?id={quote(gallery)}&no={no}"

def _open(driver, url, ready_css):
    driver.get(url)
    WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, ready_css)))
    time.sleep(random.uniform(0.5, 1.2))

def _writer(tag):
    """작성자 표시: 닉네임 + 유동 IP 앞자리(있으면). 예: 'ㅇㅇ(58.29)', '차갤러'"""
    if not tag:
        return '익명'
    nick = (tag.get('data-nick') or '').strip() or '익명'
    ip = (tag.get('data-ip') or '').strip()
    return f"{nick}({ip})" if ip else nick

def _parse_list_rows(soup, gallery):
    """목록 표(table.gall_list)의 글 행을 글 정보로. 공지·설문·광고 행은 글 번호 칸이 숫자가 아니라서 뺌"""
    post_list = []
    for row in soup.select('table.gall_list tbody tr.ub-content'):
        num = row.select_one('.gall_num')
        no = (num.get_text(strip=True) if num else '')
        if not no.isdigit() or row.get('data-no') != no:
            continue
        title_tag = row.select_one('.gall_tit a:not(.reply_numbox)')
        if not title_tag:
            continue
        # 검색어 강조(<b>) 등 안쪽 태그로 제목이 끊기지 않게 글자만 이어 붙인 뒤 공백 정리
        title = ' '.join(title_tag.get_text().split())
        date_tag = row.select_one('.gall_date')
        reply = row.select_one('.reply_num')
        views = row.select_one('.gall_count')
        votes = row.select_one('.gall_recommend')
        post_list.append({
            'id': dc_post_id(gallery, no), 'link': view_url(gallery, no), 'title': title,
            'author': _writer(row.select_one('.gall_writer')),
            'date': (date_tag.get('title') or date_tag.get_text(strip=True)) if date_tag else '날짜 모름',
            # '[3]' 또는 음성 댓글이 있으면 '[3/1]' → 앞 숫자가 댓글 수
            'list_comment_count': parse_count(re.split(r'/', reply.get_text())[0]) if reply else 0,
            'list_views': str(parse_count(views.get_text())) if views else None,
            'list_votes': str(parse_count(votes.get_text())) if votes else None,
        })
    return post_list

def get_list_page_posts(driver, board, keyword, page=1):
    gallery = dc_gallery(board)
    # 페이지 로드 실패는 호출한 쪽(메인 루프)에서 키워드 정보와 함께 한 번만 기록
    _open(driver, list_url(gallery, keyword, page), 'table.gall_list, body')
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    if not soup.select_one('table.gall_list'):
        page_title = (driver.title or '').strip()[:60] or '제목 없음'
        raise BlockedError(f"갤러리 목록이 아닌 페이지 응답 (제목: {page_title})")
    post_list = _parse_list_rows(soup, gallery)
    log_msg(f"[수집] 목록 {board}/{keyword}: {len(post_list)}건", "DEBUG")
    return post_list

def gallery_title(page_title):
    """'자동차 갤러리 - 커뮤니티 포털 디시인사이드' 형태의 창 제목에서 갤러리 이름"""
    parts = [p.strip() for p in (page_title or '').split(' - ') if p.strip()]
    if parts and '디시인사이드' in parts[-1]:
        parts.pop()
    return parts[-1][:30] if parts else ''

def check_board(driver, board):
    """새로 추가한 디시 갤러리 확인: 첫 목록이 수집기가 읽는 표(table.gall_list) 형태로 글을 보여주는지.
    (True, 갤러리 이름) 또는 (False, 사유). 페이지를 못 열면 예외 그대로 (호출한 쪽에서 다음 주기에 재시도)"""
    gallery = dc_gallery(board)
    _open(driver, list_url(gallery), 'table.gall_list, body')
    page_title = (driver.title or '').strip()
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    if not soup.select_one('table.gall_list'):
        return False, f"갤러리 목록(표)이 없는 페이지 (제목: {page_title[:60] or '제목 없음'})"
    if not _parse_list_rows(soup, gallery):
        return False, "목록 표에서 글을 읽지 못함"
    return True, gallery_title(page_title)

def _is_deleted_page(driver):
    return DELETED_URL_MARK in (driver.current_url or '') or any(p in driver.page_source for p in DELETED_PAGE_PHRASES)

def _comment(li, is_reply):
    """댓글 한 개 (광고·삭제 안내 등 내용이 없는 행은 None)"""
    box = li.select_one('.cmt_info') or li
    text_area = box.select_one('.usertxt')
    dccon = box.select_one('.written_dccon')
    if text_area:
        lines = comment_lines(text_area)
    elif dccon:
        # 디시콘(이모티콘) 이미지는 다른 사이트에서 열리지 않으므로 표시만
        lines = ['(디시콘)']
    else:
        return None
    date_tag = box.select_one('.date_time')
    return {
        'author': _writer(box.select_one('.gall_writer')),
        'date': date_tag.get_text(strip=True) if date_tag else '',
        'votes': '0',
        'content': lines,
        'is_reply': is_reply,
        'depth': 1 if is_reply else 0
    }

def _parse_comments(soup):
    """댓글 목록: 댓글(li.ub-content) 바로 뒤의 형제 li 안 .reply_list에 그 댓글의 답글이 들어 있음"""
    comments = []
    for li in soup.select('.cmt_list > li'):
        classes = li.get('class') or []
        if 'ub-content' in classes:
            if 'dory' in classes:
                continue
            item = _comment(li, False)
            if item:
                comments.append(item)
        for reply in li.select('.reply_list > li.ub-content'):
            item = _comment(reply, True)
            if item:
                comments.append(item)
    return comments

def _save_body_images(driver, post_id):
    """본문 이미지를 크롬이 받은 파일 그대로 꺼내(CDP Page.getResourceContent) 저장. {본문 img 순번: 대시보드 주소}.
    디시 페이지가 정상적으로 받은 파일만 쓰며 따로 요청하지 않음. 실패한 이미지는 빠짐 (원문 링크로 대체됨)"""
    saved = {}
    try:
        # 열린 직후에는 아직 받는 중일 수 있어 본문 이미지가 다 받아질 때까지 잠시 기다림
        WebDriverWait(driver, IMAGE_WAIT_SECONDS).until(lambda d: d.execute_script(
            "return [...document.querySelectorAll('.write_div img')].every(i => i.complete)"))
    except Exception:
        pass
    try:
        urls = driver.execute_script(
            "return [...document.querySelectorAll('.write_div img')].map(i => i.complete && i.naturalWidth ? (i.currentSrc || i.src) : '')")
        frame_id = driver.execute_cdp_cmd('Page.getFrameTree', {})['frameTree']['frame']['id']
    except Exception as e:
        log_msg(f"[수집] #{post_id} 이미지 목록 확인 실패: {short_err(e)}", "DEBUG")
        return saved
    clear_post_images(post_id)
    for index, url in enumerate(urls[:MAX_IMAGES_PER_POST]):
        if not url:
            continue
        try:
            resource = driver.execute_cdp_cmd('Page.getResourceContent', {'frameId': frame_id, 'url': url})
            data = base64.b64decode(resource['content']) if resource.get('base64Encoded') else resource['content'].encode('latin-1')
            path = save_post_image(post_id, index, data)
            if path:
                saved[index] = path
        except Exception as e:
            log_msg(f"[수집] #{post_id} 이미지 {index + 1} 저장 실패: {short_err(e)}", "DEBUG")
    return saved

def scrape_post_detail(driver, post_info):
    link = post_info['link']
    post_id = post_info['id']
    try:
        # 페이지 로드 실패는 호출한 쪽(메인 루프)에서 키워드 정보와 함께 한 번만 기록
        _open(driver, link, '.write_div, .derror, body')
        if _is_deleted_page(driver):
            return None
        # 댓글은 페이지가 열린 뒤 따로 불러오므로 댓글 수가 있으면 목록이 채워질 때까지 잠시 기다림
        try:
            WebDriverWait(driver, 4).until(lambda d: d.find_elements(By.CSS_SELECTOR, '.cmt_list > li')
                                           or '댓글 0' in (d.find_element(By.CSS_SELECTOR, '.gall_comment').text or ''))
        except Exception:
            pass
    except UnexpectedAlertPresentException as alert_ex:
        # 삭제된 글 등은 안내 창(alert)을 띄우기도 함
        if any(word in (alert_ex.alert_text or '') for word in ('삭제', '존재하지')):
            return None
        raise

    page_source = driver.page_source
    soup = BeautifulSoup(page_source, 'html.parser')
    content_area = soup.select_one('.write_div')
    if not content_area:
        if _is_deleted_page(driver):
            return None
        raise Exception("본문(.write_div) 없음 - 일시적 로드 실패 추정")

    title_tag = soup.select_one('.title_subject')
    date_tag = soup.select_one('.gall_date')
    views_tag = soup.select_one('.gall_count')
    votes_tag = soup.select_one('.up_num')
    comment_tag = soup.select_one('.gall_comment')

    # 본문 이미지는 다른 사이트(이 대시보드)에서는 열리지 않으므로, 크롬이 받은 파일을 꺼내 저장한 이미지로 바꿈.
    # 꺼내지 못한 이미지는 원문으로 가는 안내 링크로 (본문 img 순서는 페이지와 page_source가 같음)
    saved = _save_body_images(driver, post_id)
    img_count = 0
    for index, img in enumerate(content_area.select('img')):
        img_count += 1
        if saved.get(index):
            img.attrs = {'src': saved[index], 'alt': '첨부이미지', 'style': IMAGE_STYLE}
            continue
        note = soup.new_tag('a', href=link, target='_blank', style=LINK_STYLE)
        note.string = f"[이미지 {img_count} · 원문에서 보기]"
        img.replace_with(note)

    video_list = []
    for video in content_area.select('video, iframe, embed'):
        source = video.select_one('source')
        src = video.get('src') or (source.get('src') if source else None)
        if src and src.startswith('//'):
            src = 'https:' + src
        if src:
            video_list.append(src)
        # 디시 동영상 플레이어도 다른 사이트에서는 열리지 않을 수 있어 원문 링크를 함께 둠
        note = soup.new_tag('a', href=link, target='_blank', style=LINK_STYLE)
        note.string = "[동영상 · 원문에서 보기]"
        video.replace_with(note)

    for a_tag in content_area.find_all('a'):
        a_tag['target'] = '_blank'
        if not a_tag.get('style'):
            a_tag['style'] = LINK_STYLE

    paragraphs = content_lines(content_area)
    comments = _parse_comments(soup)

    log_msg(f"[수집] 상세 #{post_id}: 이미지 {img_count}(저장 {len(saved)}), 동영상 {len(video_list)}, 댓글 {len(comments)}", "DEBUG")
    return {
        'id': post_id,
        'title': ' '.join(title_tag.get_text().split()) if title_tag else post_info['title'],
        'author': _writer(soup.select_one('.gall_writer')) if soup.select_one('.gall_writer') else post_info['author'],
        'date': (date_tag.get('title') or date_tag.get_text(strip=True)) if date_tag else post_info['date'],
        'views': str(parse_count(views_tag.get_text())) if views_tag else '0',
        'votes': str(parse_count(votes_tag.get_text())) if votes_tag else '0',
        'comment_count': str(parse_count(comment_tag.get_text())) if comment_tag else str(len(comments)),
        'link': link, 'content': paragraphs, 'videos': video_list, 'comments': comments
    }
