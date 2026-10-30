import os
import re
import json
import html
from datetime import datetime

import requests
from config import log_msg, short_err, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from sites import post_site
from storage import site_labels
from images import image_file, IMAGE_URL_PREFIX

_missing_config_warned = False

PREVIEW_LENGTH = 90        # 새 글 알림의 본문 미리보기 글자 수
CAPTION_LIMIT = 1024       # 텔레그램 사진 설명 최대 길이
_TAG_RE = re.compile(r'<[^>]+>')
_VIDEO_BLOCK_RE = re.compile(r'<video\b.*?</video>', re.I | re.S)
_URL_RE = re.compile(r'https?://\S+')
_POSTER_RE = re.compile(r'<video\b[^>]*\bposter="([^"]+)"', re.I)
# 에펨코리아에 올린 첨부 이미지만 (이모티콘·아이콘 제외)
_ATTACH_IMG_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]*/files/attach/[^"]+)"', re.I)
# 수집할 때 NAS에 저장한 이미지 (디시인사이드 본문 이미지, images.py)
_SAVED_IMG_RE = re.compile(r'<img\b[^>]*\bsrc="(' + re.escape(IMAGE_URL_PREFIX) + r'[^"]+)"', re.I)
# 디시 본문에서 저장하지 못한 이미지·동영상 대신 넣은 원문 링크 문구 (미리보기에서는 뺌, dcinside.py)
_ORIGINAL_NOTE_RE = re.compile(r'\[(?:이미지 \d+|동영상) · 원문에서 보기\]')
# 유튜브 영상 ID (퍼가기 iframe·watch·youtu.be·shorts 주소)
_YOUTUBE_RE = re.compile(
    r'(?:youtube(?:-nocookie)?\.com/(?:embed/|shorts/|live/|v/|watch\?(?:[^"\s<>]*?&(?:amp;)?)?v=)|youtu\.be/)'
    r'([A-Za-z0-9_-]{11})', re.I)

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

def send_telegram_message(text):
    """차단 의심·복구 같은 상태 알림 (서식 없는 글)"""
    if not _configured():
        return
    if not _call("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, "text": text}):
        log_msg("[알림] 텔레그램 발송 실패", "ERROR")

# ==========================================
# 새 글 알림 (정보 카드형, 이미지·동영상 글은 썸네일 사진과 함께)
# ==========================================
def _plain_text(lines):
    """미리보기용 본문 글자: 동영상 대체 문구('Video 태그를 지원하지 않는…')와 주소는 뺌"""
    joined = _VIDEO_BLOCK_RE.sub(' ', ' '.join(lines or []))
    text = _URL_RE.sub(' ', html.unescape(_TAG_RE.sub(' ', joined)))
    return ' '.join(_ORIGINAL_NOTE_RE.sub(' ', text).split())

def _absolute(url):
    url = html.unescape(url or '').strip().replace('/./', '/')
    if url.startswith('//'):
        return 'https:' + url
    return url if url.startswith(('http://', 'https://')) else ''

def find_thumbnail(content_lines):
    """본문의 첫 동영상 썸네일, 없으면 유튜브 영상 썸네일, 없으면 첫 첨부 이미지 주소 (없으면 빈 문자열)"""
    joined = '\n'.join(content_lines or [])
    match = _POSTER_RE.search(joined)
    if match and _absolute(match.group(1)):
        return _absolute(match.group(1))
    match = _YOUTUBE_RE.search(joined)
    if match:
        # hqdefault는 모든 영상에 있음 (maxresdefault는 없는 영상이 있어 사진 발송이 실패할 수 있음)
        return f"https://img.youtube.com/vi/{match.group(1)}/hqdefault.jpg"
    match = _ATTACH_IMG_RE.search(joined)
    if match and _absolute(match.group(1)):
        return _absolute(match.group(1))
    return ''

def find_saved_image(content_lines):
    """본문의 첫 저장 이미지 파일 (경로, 형식). 없으면 None. 디시 이미지는 텔레그램 서버가 주소로 받아 갈 수 없어
    NAS에 저장된 파일을 직접 올려 보냄"""
    match = _SAVED_IMG_RE.search('\n'.join(content_lines or []))
    return image_file(html.unescape(match.group(1))[len(IMAGE_URL_PREFIX):]) if match else None

def _upload_photo(base, caption, image):
    """저장된 이미지 파일을 사진으로 올려 보냄 (multipart). 성공하면 True"""
    path, content_type = image
    payload = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else str(v)) for k, v in base.items()}
    payload['caption'] = caption
    try:
        with open(path, 'rb') as f:
            res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", data=payload,
                                files={'photo': (os.path.basename(path), f, content_type)}, timeout=30)
        if res.status_code == 200:
            return True
        log_msg(f"[알림] sendPhoto(파일) 실패({res.status_code}): {short_err(_redact(res.text))}", "DEBUG")
    except Exception as e:
        log_msg(f"[알림] sendPhoto(파일) 오류: {short_err(_redact(str(e)))}", "DEBUG")
    return False

def _count(value):
    """조회·댓글 수를 천 단위 쉼표로 (숫자가 아니면 그대로)"""
    digits = str(value or 0).replace(',', '').strip()
    return f"{int(digits):,}" if digits.isdigit() else str(value)

def build_post_alert(post, boards, keyword, board_name):
    """알림 본문(HTML): 사이트([FM]·[DC])·게시판·시각 머리글 / 굵은 제목 / 인용 상자에 본문 미리보기 /
    키워드·카테고리 한 줄, 작성자·조회·댓글 한 줄.
    사이트는 휴대폰 알림 목록에 보이는 첫 줄 맨 앞에 두어 열어 보지 않아도 어느 사이트 글인지 알 수 있게 함"""
    esc = html.escape
    has_video = bool(post.get('videos'))
    site = site_labels()[post_site(post.get('id', ''))]['short']
    header = f"{'🎬' if has_video else '🔔'} [{site}] <b>{esc(', '.join(boards))}</b>"
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
    # 인터넷 주소로 쓸 썸네일이 없으면 NAS에 저장된 본문 이미지(디시)를 파일로 올림
    saved_image = None if thumbnail else find_saved_image(post.get('content'))
    if (thumbnail or saved_image) and len(text) <= CAPTION_LIMIT:
        sent = (_call("sendPhoto", {**base, "photo": thumbnail, "caption": text}) if thumbnail
                else _upload_photo(base, text, saved_image))
        if sent:
            return
        log_msg("[알림] 썸네일 사진 발송 실패 → 글로 발송", "DEBUG")
    if _call("sendMessage", {**base, "text": text, "link_preview_options": {"is_disabled": True}}):
        return
    # HTML 파싱 실패 등에 대비해 서식 없는 글로 한 번 더 시도
    fallback = {k: v for k, v in base.items() if k != "parse_mode"}
    plain = html.unescape(_TAG_RE.sub('', text.replace('</blockquote>', '\n')))
    if not _call("sendMessage", {**fallback, "text": plain}):
        log_msg("[알림] 텔레그램 새 글 알림 발송 실패", "ERROR")
