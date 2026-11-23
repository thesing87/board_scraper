"""디시인사이드 갤러리 수집기 (공통 도구는 scraper.py). 크롬 없이 HTTP 요청(requests)으로 읽음.

- 카테고리 키는 'dc:갤러리id', 글 ID는 'dc-갤러리id-글번호' (sites.py)
- 목록·글 화면은 HTML 그대로 받아 읽음. 댓글은 디시 글 화면이 쓰는 댓글 API(/board/comment/, JSON)로 받음
- 디시 이미지는 디시 페이지에서 연 것처럼(Referer) 받아야 열리므로, 글 화면에서 받은 뒤 저장해 보여줌 (images.py).
  받지 못한 이미지는 원문으로 가는 안내 링크로 바꿔 저장

예전에는 크롬(셀레늄)으로 열었는데, NAS(메모리 1.8GB)에서 크롬이 CPU·메모리를 가장 많이 써 스왑으로 NAS 전체가 느려지고
'Timed out receiving message from renderer'로 목록을 못 읽는 일이 잦았음. 디시 목록·글은 자바스크립트 없이도 HTML에 다 있음
"""
import re
import time
import random
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
from config import log_msg, short_err, COMMENT_PAGE_LIMIT
from images import save_post_image, clear_post_images, MAX_IMAGES_PER_POST
from scraper import BlockedError, parse_count, content_lines, comment_lines
from sites import dc_gallery, dc_post_id

BASE_URL = 'https://gall.dcinside.com'
COMMENT_URL = BASE_URL + '/board/comment/'
# 삭제됐거나 없는 글은 /derror/deleted/... 안내 페이지로 넘어감.
# 2026-11-20부터는 서버가 바로 넘기지 않고, 응답 404에 그 주소로 넘기는 스크립트만 줌
# (<script>location.replace("/derror/deleted/car_new1/gallery/gallery/11582043");</script>)
DELETED_URL_MARK = '/derror/deleted/'
DELETED_SCRIPT_RE = re.compile(r"""location\.(?:replace\(|href\s*=)\s*["'][^"']*/derror/deleted/""")
DELETED_PAGE_PHRASES = ('삭제했거나 존재하지 않는', '삭제된 게시물', '존재하지 않는 게시물')
# 이미지·동영상 대신 넣는 원문 링크 모양
LINK_STYLE = "color: #1877f2; text-decoration: underline; font-weight: bold;"
# 저장한 본문 이미지 모양
IMAGE_STYLE = "width: 100%; height: auto; border-radius: 6px; margin-top: 8px; display: block;"
# 디시는 3번째 이미지부터 '불러오는 중' 그림을 src에 두고 진짜 주소는 data-original에 둠 (화면을 내릴 때 바꿔 끼움)
LAZY_PLACEHOLDER = 'gallview_loading'
# 보통 크롬과 같은 브라우저 정보 (없으면 디시가 다른 화면을 줄 수 있음)
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/131.0.0.0 Safari/537.36')
# (연결, 응답) 대기 시간(초)
TIMEOUT = (10, 30)
IMAGE_TIMEOUT = (10, 20)
# 페이지를 연 뒤 다음 요청까지 쉬는 시간 (사람이 보는 속도와 비슷하게)
PAUSE_RANGE = (0.5, 1.2)


class DcClient:
    """디시에 요청을 보내는 연결 하나 (쿠키를 이어 씀). 크롬 드라이버 자리에 넘겨 씀"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        })

    def get(self, url, **kwargs):
        kwargs.setdefault('timeout', TIMEOUT)
        return self.session.get(url, **kwargs)

    def post(self, url, **kwargs):
        kwargs.setdefault('timeout', TIMEOUT)
        return self.session.post(url, **kwargs)

    def close(self):
        self.session.close()


def create_client():
    return DcClient()


def list_url(gallery, keyword=None, page=1):
    url = f"{BASE_URL}/board/lists/?id={quote(gallery)}"
    if keyword:
        url += f"&s_type=search_subject_memo&s_keyword={quote(keyword)}"
    return url + (f"&page={page}" if page > 1 else '')


def view_url(gallery, no):
    return f"{BASE_URL}/board/view/?id={quote(gallery)}&no={no}"


def _pause():
    time.sleep(random.uniform(*PAUSE_RANGE))


def _open(client, url):
    """페이지 HTML을 받음. 응답 코드가 오류면 예외 (호출한 쪽이 키워드 정보와 함께 기록)"""
    res = client.get(url)
    _pause()
    if res.status_code >= 500:
        raise Exception(f"디시 서버 오류 {res.status_code}")
    res.encoding = res.encoding if res.encoding and res.encoding.lower() != 'iso-8859-1' else 'utf-8'
    return res


def _page_title(soup):
    return ' '.join((soup.title.get_text() if soup.title else '').split())


def _log_unexpected(res, soup, target):
    """목록이 아닌 페이지가 왔을 때 무엇이 왔는지 기록 (차단 화면인지, 일시적인 오류 화면인지 나중에 가려 보려고)"""
    text = ' '.join((soup.body.get_text(' ') if soup.body else '').split())[:200]
    log_msg(f"[차단 의심] {target} 목록이 아닌 페이지: 응답 코드 {res.status_code}, 주소 {res.url}, "
            f"내용 \"{text or '(빈 화면)'}\"", "DEBUG")


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


def get_list_page_posts(client, board, keyword, page=1):
    gallery = dc_gallery(board)
    # 페이지 로드 실패는 호출한 쪽(메인 루프)에서 키워드 정보와 함께 한 번만 기록
    res = _open(client, list_url(gallery, keyword, page))
    soup = BeautifulSoup(res.text, 'html.parser')
    if not soup.select_one('table.gall_list'):
        _log_unexpected(res, soup, f"{board}/{keyword}")
        raise BlockedError(f"갤러리 목록이 아닌 페이지 응답 (응답 {res.status_code}, 제목: {_page_title(soup)[:60] or '제목 없음'})")
    post_list = _parse_list_rows(soup, gallery)
    log_msg(f"[수집] 목록 {board}/{keyword}: {len(post_list)}건", "DEBUG")
    return post_list


def gallery_title(page_title):
    """'자동차 갤러리 - 커뮤니티 포털 디시인사이드' 형태의 창 제목에서 갤러리 이름"""
    parts = [p.strip() for p in (page_title or '').split(' - ') if p.strip()]
    if parts and '디시인사이드' in parts[-1]:
        parts.pop()
    return parts[-1][:30] if parts else ''


def check_board(client, board):
    """새로 추가한 디시 갤러리 확인: 첫 목록이 수집기가 읽는 표(table.gall_list) 형태로 글을 보여주는지.
    (True, 갤러리 이름) 또는 (False, 사유). 페이지를 못 열면 예외 그대로 (호출한 쪽에서 다음 주기에 재시도)"""
    gallery = dc_gallery(board)
    res = _open(client, list_url(gallery))
    soup = BeautifulSoup(res.text, 'html.parser')
    page_title = _page_title(soup)
    if not soup.select_one('table.gall_list'):
        return False, f"갤러리 목록(표)이 없는 페이지 (제목: {page_title[:60] or '제목 없음'})"
    if not _parse_list_rows(soup, gallery):
        return False, "목록 표에서 글을 읽지 못함"
    return True, gallery_title(page_title)


def _is_deleted_page(res):
    return (DELETED_URL_MARK in (res.url or '') or DELETED_SCRIPT_RE.search(res.text) is not None
            or any(p in res.text for p in DELETED_PAGE_PHRASES))


# ==========================================
# 댓글 (글 화면이 부르는 댓글 API: 페이지마다 JSON)
# ==========================================
def _comment(item):
    """댓글 API의 댓글 한 개 → 저장 형태. 광고(댓글돌이)·삭제된 댓글·내용 없는 것은 None"""
    if str(item.get('no') or '0') == '0' or item.get('nicktype') == 'COMMENT_BOY' or item.get('del_yn') == 'Y':
        return None
    memo = item.get('memo') or ''
    if 'written_dccon' in memo:
        # 디시콘(이모티콘) 이미지는 다른 사이트에서 열리지 않으므로 표시만
        lines = ['(디시콘)']
    else:
        box = BeautifulSoup(f'<p class="usertxt">{memo}</p>', 'html.parser').p
        lines = comment_lines(box)
        if not lines:
            return None
    name = (item.get('name') or '').strip() or '익명'
    ip = (item.get('ip') or '').strip()
    is_reply = str(item.get('depth') or '0') != '0'
    return {
        'author': f"{name}({ip})" if ip else name,
        'date': (item.get('reg_date') or '').strip(),
        'votes': '0',
        'content': lines,
        'is_reply': is_reply,
        'depth': 1 if is_reply else 0
    }


def _comment_pages(pagination):
    """댓글 페이지 번호 줄(HTML)에 보이는 가장 큰 페이지 번호 (페이지가 하나면 1)"""
    numbers = [int(n) for n in re.findall(r'viewComments\((\d+)', pagination or '')]
    current = re.search(r'<em>(\d+)</em>', pagination or '')
    if current:
        numbers.append(int(current.group(1)))
    return max(numbers or [1])


def _fetch_comment_page(client, gallery, no, esno, page, referer):
    res = client.post(COMMENT_URL, data={
        'id': gallery, 'no': no, 'cmt_id': gallery, 'cmt_no': no, 'focus_cno': '', 'focus_pno': '',
        'e_s_n_o': esno, 'comment_page': page, 'sort': 'D', 'prevCnt': '', 'board_type': '', '_GALLTYPE_': 'G',
    }, headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': referer, 'Origin': BASE_URL,
                'Accept': 'application/json, text/javascript, */*; q=0.01'})
    if res.status_code != 200:
        raise Exception(f"댓글 {page}페이지 응답 {res.status_code}")
    try:
        return res.json()
    except ValueError:
        raise Exception(f"댓글 {page}페이지가 JSON이 아님")


def _read_comments(client, gallery, no, esno, referer, post_id, all_pages):
    """댓글 1페이지(가장 최근)와, all_pages면 2페이지부터 오래된 쪽 페이지까지. 오래된 댓글부터 순서대로.
    COMMENT_PAGE_LIMIT를 넘는 오래된 페이지는 읽지 않음. 2페이지부터 읽은 댓글은 other_page 표시 (storage._upsert_post 참고)"""
    first = _fetch_comment_page(client, gallery, no, esno, 1, referer)
    seen = set()

    def parse(data):
        out = []
        for item in data.get('comments') or []:
            key = item.get('no')
            if key in seen:
                continue
            seen.add(key)
            c = _comment(item)
            if c:
                out.append(c)
        return out

    comments = parse(first)
    total = parse_count(first.get('total_cnt'))
    if not all_pages:
        return comments, total
    last = min(_comment_pages(first.get('pagination')), COMMENT_PAGE_LIMIT)
    pages = []
    page = 2
    while page <= last:
        _pause()
        # 일부 페이지만 저장하면 빠진 댓글이 다음에 새 댓글로 잡히므로 실패하면 이번 갱신은 실패로 (다음 주기에 재시도)
        data = _fetch_comment_page(client, gallery, no, esno, page, referer)
        pages.append([dict(c, other_page=True) for c in parse(data)])
        # 페이지 번호 줄은 10개씩 보이므로 넘어갈 때마다 끝 페이지를 다시 셈
        last = min(max(last, _comment_pages(data.get('pagination'))), COMMENT_PAGE_LIMIT)
        page += 1
    if pages:
        log_msg(f"[수집] 상세 #{post_id}: 댓글 1~{len(pages) + 1}페이지 읽음", "DEBUG")
    return [c for page_comments in reversed(pages) for c in page_comments] + comments, total


# ==========================================
# 본문 이미지
# ==========================================
def _image_url(img):
    src = img.get('src') or ''
    real = img.get('data-original') or ''
    if real and ('lazy' in (img.get('class') or []) or LAZY_PLACEHOLDER in src):
        src = real
    if src.startswith('//'):
        src = 'https:' + src
    return '' if not src.startswith('http') or LAZY_PLACEHOLDER in src else src


def _save_body_images(client, content_area, post_id, referer):
    """본문 이미지를 디시 글 화면에서 연 것처럼 받아 저장. {본문 img 순번: 대시보드 주소}. 받지 못한 것은 빠짐 (원문 링크로)"""
    saved = {}
    clear_post_images(post_id)
    for index, img in enumerate(content_area.select('img')[:MAX_IMAGES_PER_POST]):
        url = _image_url(img)
        if not url:
            continue
        try:
            res = client.get(url, headers={'Referer': referer, 'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'},
                             timeout=IMAGE_TIMEOUT)
            if res.status_code != 200:
                raise Exception(f"응답 {res.status_code}")
            path = save_post_image(post_id, index, res.content)
            if path:
                saved[index] = path
        except Exception as e:
            log_msg(f"[수집] #{post_id} 이미지 {index + 1} 저장 실패: {short_err(e)}", "DEBUG")
    return saved


def scrape_post_detail(client, post_info, all_comment_pages=True):
    link = post_info['link']
    post_id = post_info['id']
    # 페이지 로드 실패는 호출한 쪽(메인 루프)에서 키워드 정보와 함께 한 번만 기록
    res = _open(client, link)
    if _is_deleted_page(res):
        return None
    soup = BeautifulSoup(res.text, 'html.parser')
    content_area = soup.select_one('.write_div')
    if not content_area:
        raise Exception(f"본문(.write_div) 없음 - 일시적 로드 실패 추정 (응답 {res.status_code})")
    gallery = dc_gallery_from_link(link) or ''
    no = re.search(r'[?&]no=(\d+)', link)
    esno_tag = soup.select_one('#e_s_n_o')

    title_tag = soup.select_one('.title_subject')
    date_tag = soup.select_one('.gall_date')
    views_tag = soup.select_one('.gall_count')
    votes_tag = soup.select_one('.up_num')
    comment_tag = soup.select_one('.gall_comment')
    writer_tag = soup.select_one('.gall_writer')

    # 디시 움짤(MP4 <video data-src=GIF 주소>): 디시 화면은 MP4를 못 틀면 GIF 그림으로 바꿔 보여 줌(change_gif).
    # 이 대시보드에서는 디시 MP4가 열리지 않으므로 처음부터 GIF 그림으로 받아 저장 (크기가 커 못 받으면 원문 링크로)
    for clip in content_area.select('video[data-src]'):
        gif = soup.new_tag('img', src=clip['data-src'])
        clip.replace_with(gif)
    # 본문 이미지는 다른 사이트(이 대시보드)에서는 열리지 않으므로 받아 저장한 이미지로 바꿈. 못 받은 것은 원문 링크로
    saved = _save_body_images(client, content_area, post_id, res.url)
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
    comments, total = [], 0
    comment_count = parse_count(comment_tag.get_text()) if comment_tag else 0
    if gallery and no and esno_tag and (comment_count or not comment_tag):
        comments, total = _read_comments(client, gallery, no.group(1), esno_tag.get('value') or '', res.url, post_id, all_comment_pages)

    log_msg(f"[수집] 상세 #{post_id}: 이미지 {img_count}(저장 {len(saved)}), 동영상 {len(video_list)}, 댓글 {len(comments)}", "DEBUG")
    return {
        'id': post_id,
        'title': ' '.join(title_tag.get_text().split()) if title_tag else post_info['title'],
        'author': _writer(writer_tag) if writer_tag else post_info['author'],
        'date': (date_tag.get('title') or date_tag.get_text(strip=True)) if date_tag else post_info['date'],
        'views': str(parse_count(views_tag.get_text())) if views_tag else '0',
        'votes': str(parse_count(votes_tag.get_text())) if votes_tag else '0',
        'comment_count': str(comment_count) if comment_tag else str(total or len(comments)),
        'link': link, 'content': paragraphs, 'videos': video_list, 'comments': comments
    }


def dc_gallery_from_link(link):
    m = re.search(r'[?&]id=([^&#]+)', link or '')
    return m.group(1) if m else None
