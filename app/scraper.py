"""수집기 공통 도구 (디시인사이드 수집기 dcinside.py가 씀): 차단 의심 오류, 목록이 아닌 페이지 기록, 숫자 읽기,
본문·댓글 HTML을 줄 단위로 정리.

예전에는 에펨코리아 수집기였으나, 에펨코리아는 이용약관상 자동 수집을 하지 말아 달라는 운영자 답변을 받아 수집 기능을 없앰
"""
import re
from config import log_msg, short_err
from sanitize import sanitize_tree

class BlockedError(Exception):
    """목록 페이지가 정상 게시판 화면이 아님 (접속 차단·보안 확인·점검 페이지 등으로 추정)"""


def log_unexpected_page(driver, target):
    """목록이 아닌 페이지가 왔을 때 무엇이 왔는지 기록 (차단 화면인지, 서버의 일시적인 오류 화면인지 나중에 가려 보려고):
    응답 코드, 실제 주소, 화면에 보이는 글의 앞부분"""
    try:
        info = driver.execute_script("""
            const nav = performance.getEntriesByType('navigation')[0];
            return {status: nav && nav.responseStatus, url: location.href,
                    text: (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 200)};
        """) or {}
        log_msg(f"[차단 의심] {target} 목록이 아닌 페이지: 응답 코드 {info.get('status') or '알 수 없음'}, "
                f"주소 {info.get('url')}, 내용 \"{info.get('text') or '(빈 화면)'}\"", "DEBUG")
    except Exception as e:
        log_msg(f"[차단 의심] {target} 목록이 아닌 페이지의 내용을 읽지 못함: {short_err(e)}", "DEBUG")


def parse_count(text):
    """'1,234'처럼 표시된 숫자 문자열을 정수로 변환 (숫자가 없으면 0)"""
    digits = re.sub(r'[^\d]', '', str(text or ''))
    return int(digits) if digits else 0


def content_lines(content_area):
    """본문 영역을 정화한 뒤 줄 단위 HTML 목록으로 (빈 줄은 최대 2개까지, 앞뒤 빈 줄 제거)"""
    sanitize_tree(content_area)
    for br in content_area.find_all("br"):
        br.replace_with("\n")
    for block in content_area.find_all(['p', 'div', 'li', 'h1', 'h2', 'h3']):
        block.insert_after('\n')

    raw_html = content_area.decode_contents()
    raw_html = re.sub(r'<script.*?>.*?</script>', '', raw_html, flags=re.DOTALL)
    raw_html = re.sub(r'<!--.*?-->', '', raw_html, flags=re.DOTALL)

    paragraphs = []
    empty_count = 0
    for line in raw_html.split('\n'):
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
    return paragraphs

def comment_lines(c_content_area):
    """댓글 내용 영역을 정화한 뒤 줄 단위 HTML 목록으로 (블록 태그는 풀어서 줄바꿈으로)"""
    sanitize_tree(c_content_area)
    for br in c_content_area.find_all("br"): br.replace_with("\n")
    for block in c_content_area.find_all(['p', 'div', 'li']):
        block.insert_after('\n')
        block.unwrap()

    c_raw_text = c_content_area.decode_contents()
    c_raw_text = re.sub(r'<!--.*?-->', '', c_raw_text, flags=re.DOTALL)

    c_paragraphs = []
    c_empty_count = 0
    for line in (line.strip() for line in c_raw_text.split('\n')):
        if line == '':
            c_empty_count += 1
            if c_empty_count <= 2: c_paragraphs.append(line)
        else:
            c_empty_count = 0
            c_paragraphs.append(line)
    while c_paragraphs and c_paragraphs[0] == '': c_paragraphs.pop(0)
    while c_paragraphs and c_paragraphs[-1] == '': c_paragraphs.pop()
    return c_paragraphs
