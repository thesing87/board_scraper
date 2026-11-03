import os
import re
import json
import html
import time
from datetime import datetime, timedelta

import requests
from config import log_msg, short_err, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from sites import post_site
from storage import site_labels, add_pending_alert, pending_alerts, delete_pending_alert, bump_pending_alert
from images import image_file, IMAGE_URL_PREFIX

_missing_config_warned = False

# _call 결과: 보냄 / 텔레그램이 거절함(형식 오류 등, 다시 보내도 같음) / 연결 실패·시간 초과·서버 오류(나중에 다시)
OK, REJECTED, OFFLINE = 'ok', 'rejected', 'offline'
# 텔레그램에 연결하지 못하면 이 시간 동안은 보내 보지 않고 바로 대기열에 넣음 (알림마다 시간 초과를 기다리느라 수집이 멈추지 않게)
OFFLINE_SECONDS = 120
# 대기열의 알림을 이 시간이 지나도록 보내지 못하면 포기
PENDING_MAX_HOURS = 24
_offline_until = 0.0

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

def _result(method, status_code, text):
    """응답 코드를 결과로: 200은 OK, 요청이 너무 많음(429)·서버 오류(5xx)는 OFFLINE(나중에 다시), 나머지는 REJECTED"""
    global _offline_until
    if status_code == 200:
        return OK
    log_msg(f"[알림] {method} 실패({status_code}): {short_err(_redact(text))}", "DEBUG")
    if status_code == 429 or status_code >= 500:
        _offline_until = time.time() + OFFLINE_SECONDS
        return OFFLINE
    return REJECTED

def _connection_failed(method, error):
    global _offline_until
    log_msg(f"[알림] {method} 오류: {short_err(_redact(str(error)))}", "DEBUG")
    _offline_until = time.time() + OFFLINE_SECONDS
    return OFFLINE

def _offline():
    """최근 텔레그램에 연결하지 못해 잠시 바로 보내지 않는 중인지"""
    return time.time() < _offline_until

def _call(method, payload):
    """텔레그램 API 호출. OK·REJECTED·OFFLINE 중 하나 (실패 사유는 DEBUG 로그로)"""
    try:
        res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", json=payload, timeout=10)
        return _result(method, res.status_code, res.text)
    except Exception as e:
        return _connection_failed(method, e)

def _deliver(message):
    """메시지(chat_id 제외) 발송. HTML 서식이 거절되면 서식 없는 글로 한 번 더 시도. OK·REJECTED·OFFLINE"""
    result = _call("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, **message})
    if result != REJECTED or 'parse_mode' not in message:
        return result
    plain = {k: v for k, v in message.items() if k != 'parse_mode'}
    plain['text'] = html.unescape(_TAG_RE.sub('', message['text'].replace('</blockquote>', '\n')))
    return _call("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, **plain})

def _send(message, what):
    """메시지 발송. 텔레그램에 연결하지 못하면 대기열에 넣어 수집기가 다음 주기부터 다시 보내게 함. 보냈으면 True"""
    result = OFFLINE if _offline() else _deliver(message)
    if result == OFFLINE:
        add_pending_alert(json.dumps(message, ensure_ascii=False), what)
        log_msg(f"[알림] 텔레그램 연결 실패 → 대기열에 넣고 다음 주기부터 다시 보냄 ({what})", "WARN")
    elif result == REJECTED:
        log_msg(f"[알림] 텔레그램 {what} 발송 실패", "ERROR")
    return result == OK

def retry_pending_alerts(limit=10):
    """대기열의 알림을 오래된 것부터 다시 보냄 (수집기가 주기마다 호출). 보낸 알림 맨 위에 원래 보내려던 시각을 붙임.
    또 연결하지 못하면 다음 주기로 미루고, PENDING_MAX_HOURS가 지난 알림은 포기. 보낸 개수 반환"""
    if not _configured():
        return 0
    sent = 0
    expired = (datetime.now() - timedelta(hours=PENDING_MAX_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
    for alert in pending_alerts(limit):
        if alert['created_at'] < expired:
            delete_pending_alert(alert['id'])
            log_msg(f"[알림] {alert['created_at'][5:16]} {alert['what']}을 {PENDING_MAX_HOURS}시간 동안 보내지 못해 포기", "WARN")
            continue
        if _offline():
            break
        message = json.loads(alert['payload'])
        message['text'] = f"⏱ {alert['created_at'][11:16]}에 보내지 못한 알림\n\n{message['text']}"
        result = _deliver(message)
        if result == OFFLINE:
            bump_pending_alert(alert['id'])
            break
        delete_pending_alert(alert['id'])
        if result == OK:
            sent += 1
            log_msg(f"[알림] 미뤄 둔 {alert['what']} 발송 ({alert['created_at'][11:16]} 실패분, {alert['attempts'] + 1}번째 시도)")
        else:
            log_msg(f"[알림] 미뤄 둔 {alert['what']} 발송 실패 (텔레그램이 거절)", "ERROR")
    return sent

def send_telegram_message(text):
    """차단 의심·복구 같은 상태 알림 (서식 없는 글)"""
    if not _configured():
        return
    _send({"text": text}, "상태 알림")

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
    """저장된 이미지 파일을 사진으로 올려 보냄 (multipart). OK·REJECTED·OFFLINE"""
    path, content_type = image
    payload = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else str(v)) for k, v in base.items()}
    payload['caption'] = caption
    try:
        with open(path, 'rb') as f:
            res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", data=payload,
                                files={'photo': (os.path.basename(path), f, content_type)}, timeout=30)
        return _result("sendPhoto(파일)", res.status_code, res.text)
    except OSError as e:
        # 저장된 이미지 파일을 열지 못함 → 글로 대신 보냄 (텔레그램 연결 문제가 아님)
        log_msg(f"[알림] sendPhoto(파일) 이미지 열기 실패: {short_err(e)}", "DEBUG")
        return REJECTED
    except Exception as e:
        return _connection_failed("sendPhoto(파일)", e)

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

def _html_base(dashboard_url='', original_url=''):
    """HTML 서식 메시지의 공통 값과 대시보드·원문 버튼 (chat_id는 보낼 때 붙임)"""
    buttons = []
    if dashboard_url.startswith(('http://', 'https://')):
        buttons.append({"text": "📱 대시보드", "url": dashboard_url})
    if original_url.startswith(('http://', 'https://')):
        buttons.append({"text": "🔗 원문", "url": original_url})
    base = {"parse_mode": "HTML"}
    if buttons:
        base["reply_markup"] = {"inline_keyboard": [buttons]}
    return base

def _send_html(base, text, what):
    """HTML 메시지 발송 (서식이 거절되면 서식 없는 글로, 연결이 안 되면 대기열로). 보냈으면 True"""
    return _send({**base, "text": text, "link_preview_options": {"is_disabled": True}}, what)

def build_comment_alert(post, new_comments):
    """보관한 글의 새 댓글 알림 본문(HTML): 머리글 / 굵은 제목 / 새 댓글 최대 3개 (작성자: 내용)"""
    esc = html.escape
    site = site_labels()[post_site(post.get('id', ''))]['short']
    body = (f"⭐ [{site}] 보관한 글에 새 댓글 {len(new_comments)}개 · {datetime.now().strftime('%H:%M')}\n\n"
            f"<b>{esc(post.get('title', ''))}</b>\n")
    lines = []
    for c in new_comments[-3:]:
        text = _plain_text(c.get('content'))
        if len(text) > PREVIEW_LENGTH:
            text = text[:PREVIEW_LENGTH].rstrip() + '…'
        lines.append(f"{esc(c.get('author') or '익명')}: {esc(text)}")
    if len(new_comments) > 3:
        lines.insert(0, f"(앞의 {len(new_comments) - 3}개 생략)")
    return body + f"<blockquote>{chr(10).join(lines)}</blockquote>"

def send_comment_alert(post, new_comments, dashboard_url='', original_url=''):
    if not _configured():
        return
    _send_html(_html_base(dashboard_url, original_url), build_comment_alert(post, new_comments), "새 댓글 알림")

def build_digest(group_name, total, posts, post_url):
    """하루 요약 본문(HTML): 게시판·새 글 수 / 추천·댓글이 많은 글 목록 (제목은 post_url(글)로 가는 링크)"""
    esc = html.escape
    lines = [f"📰 <b>{esc(group_name)}</b> 하루 요약 · {datetime.now().strftime('%m/%d')}",
             f"최근 24시간 새 글 {total:,}개 중 인기 {len(posts)}개", ""]
    for i, p in enumerate(posts, 1):
        url = post_url(p)
        title = esc(p.get('title') or '(제목 없음)')
        lines.append(f"{i}. <a href=\"{esc(url)}\">{title}</a>" if url else f"{i}. {title}")
        lines.append(f"    👍 {_count(p.get('votes'))} · 💬 {_count(p.get('comment_count'))} · 👁 {_count(p.get('views'))}")
    return '\n'.join(lines)

def send_digest(group_name, total, posts, post_url):
    if not _configured():
        return False
    return _send_html(_html_base(), build_digest(group_name, total, posts, post_url), "하루 요약")

def send_post_alert(post, boards, keyword, board_name, dashboard_url='', original_url=''):
    """새 글 알림 발송. 썸네일이 있으면 사진+설명으로, 사진 발송이 안 되면 글로 대신 보냄"""
    if not _configured():
        return
    base = _html_base(dashboard_url, original_url)

    text = build_post_alert(post, boards, keyword, board_name)
    thumbnail = find_thumbnail(post.get('content'))
    # 인터넷 주소로 쓸 썸네일이 없으면 NAS에 저장된 본문 이미지(디시)를 파일로 올림
    saved_image = None if thumbnail else find_saved_image(post.get('content'))
    # 연결이 안 되는 중이면 사진은 건너뛰고 글로 대기열에 넣음 (다시 보낼 때는 글로)
    if (thumbnail or saved_image) and len(text) <= CAPTION_LIMIT and not _offline():
        photo_base = {"chat_id": TELEGRAM_CHAT_ID, **base}
        result = (_call("sendPhoto", {**photo_base, "photo": thumbnail, "caption": text}) if thumbnail
                  else _upload_photo(photo_base, text, saved_image))
        if result == OK:
            return
        log_msg("[알림] 썸네일 사진 발송 실패 → 글로 발송", "DEBUG")
    _send_html(base, text, "새 글 알림")
