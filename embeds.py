import re
import json
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
from config import log_msg, short_err

# 에펨코리아는 X(트위터) 링크를 '링크 자동 변환 중...' 임시 상자로 넣어 두고 페이지의 스크립트로 트윗 화면으로 바꿈.
# 수집 시점에는 변환 전 상자만 남으므로, X 공개 oEmbed API로 작성자·본문을 받아 스크립트 없는 트윗 카드로 직접 만듦
X_STATUS_RE = re.compile(r'https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status(?:es)?/(\d+)')
X_PLACEHOLDER_SELECTOR = 'blockquote.twitter-tweet, blockquote.fm-twitter-tweet'
OEMBED_URL = 'https://publish.twitter.com/oembed'

_oembed_cache = {}

def fetch_x_oembed(status_url):
    """트윗의 작성자 이름·본문 HTML·날짜를 반환 (실패 시 None)"""
    if status_url in _oembed_cache:
        return _oembed_cache[status_url]
    info = None
    try:
        query = urllib.parse.urlencode({'url': status_url, 'omit_script': '1', 'dnt': 'true', 'lang': 'ko'})
        req = urllib.request.Request(f"{OEMBED_URL}?{query}", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.load(res)
        quote = BeautifulSoup(data.get('html', ''), 'html.parser').select_one('blockquote')
        text = quote.select_one('p') if quote else None
        date_link = quote.find_all('a')[-1] if quote and quote.find_all('a') else None
        info = {
            'author_name': data.get('author_name', ''),
            'text_html': text.decode_contents() if text else '',
            'date': date_link.get_text(strip=True) if date_link else ''
        }
    except Exception as e:
        log_msg(f"[수집] X 트윗 정보 조회 실패({status_url}): {short_err(e)}", "DEBUG")
    _oembed_cache[status_url] = info
    return info

def _build_x_card(soup, status_url, handle, info):
    card = soup.new_tag('div', attrs={'class': 'x-embed'})
    head = soup.new_tag('div', attrs={'class': 'x-embed-head'})
    logo = soup.new_tag('span', attrs={'class': 'x-embed-logo'})
    logo.string = 'X'
    head.append(logo)
    if info and info.get('author_name'):
        name = soup.new_tag('span', attrs={'class': 'x-embed-author'})
        name.string = info['author_name']
        head.append(name)
    handle_tag = soup.new_tag('span', attrs={'class': 'x-embed-handle'})
    handle_tag.string = '@' + handle
    head.append(handle_tag)
    card.append(head)

    if info and info.get('text_html'):
        body = soup.new_tag('div', attrs={'class': 'x-embed-text'})
        for node in list(BeautifulSoup(info['text_html'], 'html.parser').contents):
            body.append(node)
        card.append(body)

    link = soup.new_tag('a', attrs={'class': 'x-embed-link', 'href': status_url, 'target': '_blank', 'rel': 'noopener noreferrer'})
    link.string = 'X에서 보기' + (f" · {info['date']}" if info and info.get('date') else '')
    card.append(link)
    return card

def convert_x_embeds(soup, root):
    """root 안의 X 임시 상자를 트윗 카드로 교체하고, 바꾼 개수를 반환"""
    converted = 0
    for quote in root.select(X_PLACEHOLDER_SELECTOR):
        match = None
        for a in quote.find_all('a', href=True):
            match = X_STATUS_RE.search(a['href'])
            if match:
                break
        if not match:
            continue
        status_url = f"https://x.com/{match.group(1)}/status/{match.group(2)}"
        quote.replace_with(_build_x_card(soup, status_url, match.group(1), fetch_x_oembed(status_url)))
        converted += 1
    return converted
