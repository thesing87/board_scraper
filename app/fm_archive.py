"""FM키워드 줄에서 보관한 에펨코리아 글: 사용자가 브라우저에서 보고 있던 글 화면의 본문·댓글 HTML을 받아 저장할 글로 정리.

서버는 에펨코리아에 요청하지 않음 (이용약관상 자동 수집을 하지 말아 달라는 운영자 답변을 받아 수집 기능을 없앰, sites.site_enabled).
이미지·동영상은 주소만 남김 (받으려면 에펨코리아 서버에 요청해야 하므로). 본문·댓글 정리는 예전 에펨코리아 수집기와 같게
(줄 나누기·정화는 scraper.content_lines·comment_lines가 sanitize로 허용한 태그만 남김).
글 화면에 보이던 댓글 페이지(처음 열면 가장 최근 페이지)의 댓글만 저장함.
"""
import re
from bs4 import BeautifulSoup
from scraper import content_lines, comment_lines, parse_count

FM_BASE = 'https://www.fmkorea.com'
MAX_HTML = 1_500_000
MAX_TEXT = 200
# 인스타그램·X 등 SNS 게시물 화면은 동영상 목록에서 뺌
_SNS_RE = re.compile(r'instagram\.com|twitter\.com|//x\.com|platform\.twitter|threads\.net|facebook\.com', re.I)
# 동영상 플레이어(MediaElement.js)의 컨트롤·껍데기: 스크립트 없이는 빈 상자라 저장하지 않음
_PLAYER_TRASH = ('.mejs__offscreen, .mejs__poster, .mejs__poster-img, .mejs__time-total, .mejs__currenttime, .mejs__duration, '
                 '.mejs__controls, .mejs__layers, .custom-progress-bar, .volume-layer, .controls-mouse-hover, button, svg, ul, meta, '
                 'a.mejs__horizontal-volume-slider')
_VIDEO_WIDE = ("width: 100% !important; max-width: 100% !important; aspect-ratio: 16 / 9 !important; height: auto !important; "
               "border-radius: 8px; object-fit: contain; display: block; margin: 10px 0;")
_VIDEO_TALL = ("width: 100% !important; max-width: 450px !important; aspect-ratio: 9 / 16 !important; height: auto !important; "
               "max-height: 75vh !important; background-color: #000; margin: 10px auto !important; border-radius: 12px; "
               "object-fit: contain; display: block;")
_REPLY_ZERO_RE = re.compile(r'(?:margin-left|padding-left)\s*:\s*0(px|%|em)?(?![\d])')
_INDENT_RE = re.compile(r'margin-left\s*:\s*([\d.]+)%')


class ArchiveError(ValueError):
    """받은 글 화면에서 본문을 찾지 못함 등 저장할 수 없는 내용"""


def _text(value, limit=MAX_TEXT):
    return ' '.join(str(value or '').split())[:limit]


def _absolute(src):
    if src.startswith('//'):
        return 'https:' + src
    if src.startswith('/'):
        return FM_BASE + src
    return src


def _int_attr(tag, *names):
    for name in names:
        try:
            value = int(tag.get(name) or 0)
        except ValueError:
            value = 0
        if value:
            return value
    return 0


def _clean_content(area):
    """본문 영역을 예전 수집기처럼 다듬고 동영상 주소 목록 반환 (제자리에서 바꿈)"""
    for trash in area.select(_PLAYER_TRASH):
        trash.extract()
    for a in area.find_all('a'):
        a['target'] = '_blank'
        a['style'] = "color: #1877f2; text-decoration: underline; font-weight: bold;"
    for wrapper in area.select('.auto_media_wrapper'):
        wrapper['style'] = "width: 100% !important; max-width: 100% !important; height: auto !important; display: block; margin-bottom: 10px;"
    for hk in area.select('.height_keep'):
        hk['style'] = ("padding: 0 !important; padding-bottom: 0 !important; width: 100% !important; max-width: 100% !important; "
                       "height: auto !important; aspect-ratio: 16 / 9 !important; display: block;")
    for mejs in area.select('.mejs__container, .mejs__video, .mejs__inner, .mejs__mediaelement'):
        for attr in ('width', 'height'):
            mejs.attrs.pop(attr, None)
        mejs['style'] = "width: 100% !important; max-width: 100% !important; height: auto !important; aspect-ratio: 16 / 9 !important;"
    for empty in area.select('div[style*="height:12px"], div[style*="height: 12px"]'):
        empty.extract()
    videos = []
    for video in area.select('video'):
        source = video.select_one('source')
        src = video.get('src') or (source.get('src') if source else None)
        tall = _int_attr(video, 'data-original-height', 'data-x-height') > _int_attr(video, 'data-original-width', 'data-x-width') > 0
        for attr in ('width', 'height', 'style'):
            video.attrs.pop(attr, None)
        if src and not src.startswith('blob:'):
            src = _absolute(src)
            videos.append(src)
            video['src'] = src
        video['controls'] = 'controls'
        video['playsinline'] = 'true'
        video['style'] = _VIDEO_TALL if tall else _VIDEO_WIDE
    for iframe in area.select('iframe'):
        src = iframe.get('src')
        if src:
            src = _absolute(src)
            if not _SNS_RE.search(src):
                videos.append(src)
            iframe['src'] = src
            iframe['style'] = "width: 100%; max-width: 100%; border-radius: 6px; margin-top: 8px;"
    for img in area.select('img'):
        # 화면에서 늦게 불러오는 이미지는 진짜 주소가 data-original 등에 있음
        src = (img.get('data-original') or img.get('original') or img.get('attach_target') or img.get('native-src')
               or img.get('src'))
        if not src or 'blank.gif' in src or 'pixel.gif' in src or src.startswith('data:'):
            img.extract()
            continue
        img.attrs = {'src': _absolute(src), 'alt': '첨부이미지',
                     'style': "width: 100%; height: auto; border-radius: 6px; margin-top: 8px; display: block;"}
    return list(dict.fromkeys(videos))


def _parse_comments(soup):
    """(베스트 댓글, 댓글). 베스트 댓글은 첫 화면 맨 위에 같은 댓글을 한 번 더 보여 주는 것 (class comment_best)"""
    best, comments = [], []
    items = soup.select('.fdb_lst_ul > li.fdb_itm, ul#comment > li.fdb_itm, .fdb_lst > li.fdb_itm') or soup.select('.fdb_lst_ul > li')
    for item in items:
        author = item.select_one('.meta a')
        date = item.select_one('.meta .date')
        votes = item.select_one('.voted_count')
        area = item.select_one('.comment-content .xe_content, .xe_content')
        lines = []
        if area:
            for a in area.find_all('a'):
                if a.get('href', '').startswith('#comment') or 'member_' in ' '.join(a.get('class', [])):
                    a['style'] = ("color: #1877f2; font-weight: bold; background-color: #e7f3ff; padding: 2px 6px; border-radius: 10px; "
                                  "text-decoration: none; margin-right: 5px; display: inline-block;")
                    if not a.text.strip().startswith('@'):
                        a.string = f"@{a.text.strip()}"
            lines = comment_lines(area)
        style, classes = item.get('style', ''), item.get('class', [])
        is_reply = any(k in ''.join(classes).lower() for k in ('indent', 'depth', 'reply', 'respond')) or (
            ('margin-left' in style or 'padding-left' in style) and not _REPLY_ZERO_RE.search(style))
        depth = 0
        if is_reply:
            # 에펨코리아는 답글 한 단계마다 margin-left를 2%씩 늘림. 값이 없으면 1단
            indent = _INDENT_RE.search(style)
            depth = max(1, round(float(indent.group(1)) / 2)) if indent else 1
        (best if 'comment_best' in classes else comments).append({
            'author': _text(author.text if author else '') or '익명', 'date': _text(date.text if date else '', 40),
            'votes': _text(votes.text if votes else '', 20) or '0', 'content': lines, 'is_reply': is_reply, 'depth': depth})
    return best, comments


def _count_after(soup, label):
    """'조회 수 123'처럼 이름 뒤의 <b> 숫자"""
    found = soup.find(string=re.compile(label))
    bold = found.find_next('b') if found else None
    return str(parse_count(bold.text)) if bold else '0'


def parse_archive(data):
    """받은 내용 {no, head_html, content_html, comments_html, page_title}을 저장할 글로 (storage._upsert_post 형식).
    본문이 없으면 ArchiveError"""
    no = data.get('no')
    if type(no) is not int or not 0 < no < 10 ** 13:
        raise ArchiveError('글 번호가 올바르지 않습니다.')
    parts = {}
    for key in ('head_html', 'content_html', 'comments_html'):
        value = data.get(key) or ''
        if not isinstance(value, str) or len(value) > MAX_HTML:
            raise ArchiveError('글 내용이 너무 큽니다.')
        parts[key] = value
    content = BeautifulSoup(parts['content_html'], 'html.parser')
    area = content.select_one('.xe_content') or content
    if not area.get_text(strip=True) and not area.find(['img', 'video', 'iframe']):
        raise ArchiveError('글 본문을 찾지 못했습니다.')
    head = BeautifulSoup(parts['head_html'], 'html.parser')
    title_tag = head.select_one('h1 .np_18px_span, h1')
    title = _text(title_tag.get_text(' ') if title_tag else '')
    if not title:
        title = _text(re.sub(r'\s*-\s*에펨코리아.*$', '', str(data.get('page_title') or '')))
    author = head.select_one('.member_plate, .btm_area .side a, .author')
    date = head.select_one('.top_area .date, span.date.m_no, .date')
    videos = _clean_content(area)
    best, comments = _parse_comments(BeautifulSoup(parts['comments_html'], 'html.parser'))
    return {
        'id': str(no), 'title': title or '(제목 없음)', 'author': _text(author.get_text(' ') if author else ''),
        'date': _text(date.get_text(' ') if date else '', 40),
        'views': _count_after(head, '조회 수'), 'votes': _count_after(head, '추천 수'),
        'comment_count': _count_after(head, '댓글') if head.find(string=re.compile('댓글')) else str(len(comments)),
        'link': f'{FM_BASE}/{no}', 'content': content_lines(area), 'videos': videos, 'comments': best + comments,
    }
