import re

# 에펨코리아는 X(트위터) 링크를 '링크 자동 변환 중...' 임시 상자로 넣어 두고 페이지의 스크립트로 트윗 화면(iframe)으로 바꿈.
# 수집 시점에 아직 바뀌지 않았으면 트윗 ID로 같은 트윗 화면을 직접 넣음 (사진·동영상까지 보이고, 높이는 app.js가 맞춤)
X_STATUS_RE = re.compile(r'https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status(?:es)?/(\d+)')
# 트윗 화면 iframe 주소(platform.twitter.com/embed/Tweet.html?...&id=트윗ID&...)의 트윗 ID
X_EMBED_ID_RE = re.compile(r'[?&](?:amp;)?id=(\d+)')
X_PLACEHOLDER_SELECTOR ='blockquote.twitter-tweet, blockquote.fm-twitter-tweet'
X_EMBED_URL = 'https://platform.twitter.com/embed/Tweet.html?id={}&dnt=true'

def _build_x_iframe(soup, tweet_id):
    """트윗 화면(iframe). 에펨코리아 페이지 스크립트가 만드는 것과 같은 X 공식 화면"""
    return soup.new_tag('iframe', attrs={
        'src': X_EMBED_URL.format(tweet_id), 'title': 'X Post', 'frameborder': '0', 'allowfullscreen': 'true',
        'style': "width: 100%; max-width: 100%; border-radius: 6px; margin-top: 8px;"})

def _rendered_tweet_ids(root):
    """페이지 스크립트가 이미 트윗 화면(사진 포함 iframe)으로 바꿔 둔 트윗 ID들"""
    ids = set()
    for iframe in root.select('iframe[src*="platform.twitter.com/embed"]'):
        match = X_EMBED_ID_RE.search(iframe['src'])
        if match:
            ids.add(match.group(1))
    return ids

def convert_x_embeds(soup, root):
    """root 안의 X 임시 상자를 트윗 화면(iframe)으로 교체하고, 바꾼 개수를 반환.
    수집 시점에 이미 트윗 화면으로 바뀐 트윗은 남은 원래 상자만 지움 (같은 트윗이 두 번 뜨지 않도록)"""
    converted = 0
    rendered = _rendered_tweet_ids(root)
    for quote in root.select(X_PLACEHOLDER_SELECTOR):
        match = None
        for a in quote.find_all('a', href=True):
            match = X_STATUS_RE.search(a['href'])
            if match:
                break
        if not match:
            continue
        if match.group(2) in rendered:
            quote.decompose()
        else:
            quote.replace_with(_build_x_iframe(soup, match.group(2)))
            rendered.add(match.group(2))
        converted += 1
    return converted

def x_cards_to_iframes(soup, root):
    """예전에 만든 글자 트윗 카드(div.x-embed, 사진이 없음)를 트윗 화면(iframe)으로 바꾸고 바꾼 개수를 반환.
    같은 트윗의 화면이 이미 있으면 카드만 지움 (이미 저장된 글 정리용)"""
    rendered = _rendered_tweet_ids(root)
    changed = 0
    for card in root.select('div.x-embed'):
        link = card.select_one('a.x-embed-link[href]')
        match = X_STATUS_RE.search(link['href']) if link else None
        if not match:
            continue
        if match.group(2) in rendered:
            card.decompose()
        else:
            card.replace_with(_build_x_iframe(soup, match.group(2)))
            rendered.add(match.group(2))
        changed += 1
    return changed

# 에펨코리아는 인스타그램 링크를 임시 상자(blockquote.instagram-media)로 넣어 두고, 페이지 스크립트가 그 옆에 게시물 화면(iframe)을
# 만든 뒤 상자는 지우지 않고 instagram-media-registered로 이름만 바꿔 둠 → 그대로 저장하면 같은 게시물이 회색 상자로 한 번 더 뜸
INSTAGRAM_POST_RE = re.compile(r'instagram\.com/(?:[A-Za-z0-9_.]+/)?(?:p|reel|tv)/([A-Za-z0-9_-]+)')
INSTAGRAM_PLACEHOLDER_SELECTOR = 'blockquote.instagram-media, blockquote.instagram-media-registered'

def remove_duplicate_instagram_placeholders(root):
    """인스타그램 게시물 화면(iframe)과 같은 게시물을 가리키는 임시 상자를 지우고, 지운 개수를 반환"""
    rendered = set()
    for iframe in root.select('iframe[src*="instagram.com"]'):
        match = INSTAGRAM_POST_RE.search(iframe['src'])
        if match:
            rendered.add(match.group(1))
    removed = 0
    for quote in root.select(INSTAGRAM_PLACEHOLDER_SELECTOR):
        urls = [quote.get('data-instgrm-permalink', '')] + [a['href'] for a in quote.find_all('a', href=True)]
        match = next((m for m in (INSTAGRAM_POST_RE.search(u) for u in urls) if m), None)
        if match and match.group(1) in rendered:
            quote.decompose()
            removed += 1
    return removed

# 동영상이 아닌 SNS 게시물 화면(iframe). 본문의 iframe은 동영상 목록에 넣는데, 이런 화면까지 넣으면
# '동영상' 보기·동영상 표시·동영상 알림에 인스타그램·X 글이 섞이므로 뺌
SNS_EMBED_RE = re.compile(r'^(?:https?:)?//(?:[\w-]+\.)*(?:instagram\.com|twitter\.com|x\.com|threads\.net)/', re.IGNORECASE)

def is_sns_embed(url):
    return bool(SNS_EMBED_RE.match(url or ''))
