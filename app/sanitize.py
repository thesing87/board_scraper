import re
from bs4 import BeautifulSoup, Comment

# 외부 사이트에서 가져온 HTML을 대시보드에 그대로 삽입하므로, 허용 목록 기반으로 정화하여 XSS를 차단
REMOVE_TAGS = {
    'script', 'style', 'noscript', 'template', 'object', 'embed', 'applet', 'form',
    'input', 'textarea', 'select', 'button', 'link', 'meta', 'base', 'svg', 'math', 'frame', 'frameset'
}

ALLOWED_TAGS = {
    'a', 'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'del', 'ins', 'sub', 'sup', 'small', 'mark',
    'p', 'div', 'span', 'br', 'hr', 'blockquote', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption',
    'img', 'video', 'source', 'iframe', 'figure', 'figcaption', 'font', 'center'
}

COMMON_ATTRS = {'style', 'class', 'title', 'align'}
TAG_ATTRS = {
    'a': {'href', 'target', 'rel'},
    'img': {'src', 'alt', 'width', 'height'},
    'video': {'src', 'controls', 'playsinline', 'poster', 'muted', 'loop', 'preload',
              'data-original-width', 'data-original-height', 'data-x-width', 'data-x-height'},
    'source': {'src', 'type'},
    'iframe': {'src', 'width', 'height', 'allow', 'allowfullscreen', 'frameborder'},
    'font': {'color', 'size', 'face'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
}
URL_ATTRS = {'href', 'src', 'poster'}

_SAFE_URL_RE = re.compile(r'^(https?:)?//|^(?![a-z][a-z0-9+.\-]*:)', re.IGNORECASE)
_UNSAFE_STYLE_RE = re.compile(r'expression\s*\(|javascript\s*:|vbscript\s*:|@import|behavior\s*:', re.IGNORECASE)

def _is_safe_url(value):
    cleaned = re.sub(r'[\x00-\x20]', '', value or '')
    return bool(_SAFE_URL_RE.match(cleaned))

def sanitize_tree(root):
    """BeautifulSoup 요소 하위 트리를 제자리에서 정화"""
    for comment in root.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    for tag in root.find_all(True):
        if tag.decomposed:
            continue
        name = tag.name.lower()
        if name in REMOVE_TAGS:
            tag.decompose()
            continue
        if name not in ALLOWED_TAGS:
            tag.unwrap()
            continue

        allowed = COMMON_ATTRS | TAG_ATTRS.get(name, set())
        for attr in list(tag.attrs):
            attr_l = attr.lower()
            value = tag.attrs[attr]
            value_str = " ".join(value) if isinstance(value, list) else str(value)
            if attr_l not in allowed:
                del tag.attrs[attr]
            elif attr_l in URL_ATTRS and not _is_safe_url(value_str):
                del tag.attrs[attr]
            elif attr_l == 'style' and _UNSAFE_STYLE_RE.search(value_str):
                del tag.attrs[attr]

        if name == 'a' and tag.get('target') == '_blank':
            tag['rel'] = 'noopener noreferrer'
    return root

def sanitize_html_fragment(html_str):
    """HTML 문자열 조각을 정화하여 문자열로 반환"""
    soup = BeautifulSoup(html_str or '', 'html.parser')
    sanitize_tree(soup)
    return soup.decode()

def sanitize_lines(lines):
    """줄 단위로 저장된 본문/댓글 데이터를 하나로 합쳐 정화한 뒤 다시 줄 단위로 분리"""
    if not lines:
        return lines
    return sanitize_html_fragment('\n'.join(lines)).split('\n')
