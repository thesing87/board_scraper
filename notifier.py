import re
import html
from datetime import datetime

import requests
from config import log_msg, short_err, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

_missing_config_warned = False

PREVIEW_LENGTH = 90        # 새 글 알림의 본문 미리보기 글자 수
CAPTION_LIMIT = 1024       # 텔레그램 사진 설명 최대 길이
_TAG_RE = re.compile(r'<[^>]+>')
_VIDEO_BLOCK_RE = re.compile(r'<video\b.*?</video>', re.I | re.S)
_URL_RE = re.compile(r'https?://\S+')
_POSTER_RE = re.compile(r'<video\b[^>]*\bposter="([^"]+)"', re.I)
# 에펨코리아에 올린 첨부 이미지만 (이모티콘·아이콘 제외)
_ATTACH_IMG_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]*/files/attach/[^"]+)"', re.I)

def _redact(text):
    """요청 URL이 포함된 예외 메시지에 봇 토큰이 노출되지 않도록 가림"""
    return text.replace(TELEGRAM_TOKEN, '***') if TELEGRAM_TOKEN else text

def _configured():
    global _missing_config_warned
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        return True
    if not _missing_config_warned:
        log_msg("[알림] TELEGRAM_TOKEN/TELEGRAM_CHAT_ID 미설정 - 텔레그램 발송을 건너뜁니다.", "WARN")
        _missing_config_warned = True
    return False

def _call(method, payload):
    """텔레그램 API 호출. 성공하면 True, 실패 사유는 DEBUG 로그로 남김"""
    try:
        res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", json=payload, timeout=10)
        if res.status_code == 200:
            return True
        log_msg(f"[알림] {method} 실패({res.status_code}): {short_err(_redact(res.text))}", "DEBUG")
    except Exception as e:
        log_msg(f"[알림] {method} 오류: {short_err(_redact(str(e)))}", "DEBUG")
    return False

def send_telegram_message(text, reply_markup=None):
    if not _configured():
        return
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if _call("sendMessage", payload):
        return
    # 특수문자로 Markdown 파싱이 실패하는 경우가 있어 일반 텍스트로 한 번 더 시도
    payload.pop("parse_mode", None)
    if not _call("sendMessage", payload):
        log_msg("[알림] 텔레그램 발송 실패", "ERROR")

# ==========================================
# 새 글 알림 (정보 카드형, 이미지·동영상 글은 썸네일 사진과 함께)
# ==========================================
def _plain_text(lines):
    """미리보기용 본문 글자: 동영상 대체 문구('Video 태그를 지원하지 않는…')와 주소는 뺌"""
    joined = _VIDEO_BLOCK_RE.sub(' ', ' '.join(lines or []))
    text = _URL_RE.sub(' ', html.unescape(_TAG_RE.sub(' ', joined)))
    return ' '.join(text.split())

def _absolute(url):
    url = html.unescape(url or '').strip().replace('/./', '/')
    if url.startswith('//'):
        return 'https:' + url
    return url if url.startswith(('http://', 'https://')) else ''

def find_thumbnail(content_lines):
    """본문의 첫 동영상 썸네일, 없으면 첫 첨부 이미지 주소 (없으면 빈 문자열)"""
    joined = '\n'.join(content_lines or [])
    for pattern in (_POSTER_RE, _ATTACH_IMG_RE):
        match = pattern.search(joined)
        if match and _absolute(match.group(1)):
            return _absolute(match.group(1))
    return ''

def _count(value):
    """조회·댓글 수를 천 단위 쉼표로 (숫자가 아니면 그대로)"""
    digits = str(value or 0).replace(',', '').strip()
    return f"{int(digits):,}" if digits.isdigit() else str(value)

def build_post_alert(post, boards, keyword, board_name):
    """알림 본문(HTML): 게시판·시각 머리글 / 굵은 제목 / 인용 상자에 본문 미리보기 /
    키워드·카테고리 한 줄, 작성자·조회·댓글 한 줄"""
    esc = html.escape
    has_video = bool(post.get('videos'))
    header = f"{'🎬' if has_video else '🔔'} <b>{esc(', '.join(boards))}</b>"
    if has_video:
        header += " · 동영상"
    header += f" · {datetime.now().strftime('%H:%M')}"

    # 인용 상자(blockquote)는 앞뒤 줄바꿈을 따로 넣지 않아도 제목·정보와 떨어져 보임
    body = f"{header}\n\n<b>{esc(post.get('title', ''))}</b>\n"
    preview = _plain_text(post.get('content'))
    if preview:
        if len(preview) > PREVIEW_LENGTH:
            preview = preview[:PREVIEW_LENGTH].rstrip() + '…'
        body += f"<blockquote>{esc(preview)}</blockquote>"
    else:
        body += "\n"
    stats = []
    if post.get('author'):
        stats.append(f"👤 {esc(post['author'])}")
    stats += [f"👁 {_count(post.get('views'))}", f"💬 {_count(post.get('comment_count'))}"]
    return body + f"🏷 {esc(keyword)} · {esc(board_name)}\n" + '   '.join(stats)

def send_post_alert(post, boards, keyword, board_name, dashboard_url='', original_url=''):
    """새 글 알림 발송. 썸네일이 있으면 사진+설명으로, 사진 발송이 안 되면 글로 대신 보냄"""
    if not _configured():
        return
    buttons = []
    if dashboard_url.startswith(('http://', 'https://')):
        buttons.append({"text": "📱 대시보드", "url": dashboard_url})
    if original_url.startswith(('http://', 'https://')):
        buttons.append({"text": "🔗 원문", "url": original_url})
    base = {"chat_id": TELEGRAM_CHAT_ID, "parse_mode": "HTML"}
    if buttons:
        base["reply_markup"] = {"inline_keyboard": [buttons]}

    text = build_post_alert(post, boards, keyword, board_name)
    thumbnail = find_thumbnail(post.get('content'))
    if thumbnail and len(text) <= CAPTION_LIMIT:
        if _call("sendPhoto", {**base, "photo": thumbnail, "caption": text}):
            return
        log_msg("[알림] 썸네일 사진 발송 실패 → 글로 발송", "DEBUG")
    if _call("sendMessage", {**base, "text": text, "link_preview_options": {"is_disabled": True}}):
        return
    # HTML 파싱 실패 등에 대비해 서식 없는 글로 한 번 더 시도
    fallback = {k: v for k, v in base.items() if k != "parse_mode"}
    plain = html.unescape(_TAG_RE.sub('', text.replace('</blockquote>', '\n')))
    if not _call("sendMessage", {**fallback, "text": plain}):
        log_msg("[알림] 텔레그램 새 글 알림 발송 실패", "ERROR")
