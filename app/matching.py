import re
import html

# 수집 키워드가 글에 들어 있는지 판별. 수집기(새 글)와 저장소(무시할 표현을 바꿨을 때 이미 모은 글 다시 확인)가
# 같은 규칙을 쓰도록 한곳에 둠
_TAG_RE = re.compile(r'<[^>]+>')

def norm(text):
    """대소문자 무시, 연속 공백은 하나로"""
    return ' '.join(str(text or '').split()).casefold()

def keyword_in_post(keyword, title, content_lines=None, ignores=()):
    """키워드가 제목·본문에 띄어쓰기까지 그대로 있는지 (대소문자 무시, 연속 공백은 하나로 봄)
    에펨코리아 검색은 띄어쓰기를 무시해 '투싼 하브'도 '싼하'로 찾으므로 수집 전에 한 번 더 확인.
    본문은 줄 단위로 저장되므로 줄 안의 태그(링크·굵게 등)는 지우고 줄 사이만 띄움.
    ignores(무시할 표현)는 지운 뒤에 키워드를 찾음: '싼하'에 '투싼하'를 지정하면 '투싼하브'만 있는 글은 빠지고
    다른 곳에 '싼하'가 따로 있는 글은 그대로 모음"""
    body = ' '.join(html.unescape(_TAG_RE.sub('', line)) for line in content_lines or [])
    text = norm(f"{title or ''} {body}")
    for phrase in ignores:
        phrase = norm(phrase)
        if phrase:
            # 지운 자리의 앞뒤 글자가 이어 붙어 키워드가 새로 생기지 않도록 줄바꿈(본문에는 없는 문자)으로 끊음
            text = text.replace(phrase, '\n')
    return norm(keyword) in text
