"""FM키워드 하루 요약: 하루 한 번 DIGEST_HOUR가 지난 뒤, 지난 24시간 FM키워드 줄이 에펨코리아 검색 결과에서 찾은 새 글을
카드(게시판)·키워드마다 몇 개 찾았고 몇 개를 안 읽었는지, 안 읽은 글 제목과 함께 텔레그램으로 한 번 보냄.
대시보드 웹서버 안에서 따로 도는 작업 (web_server.run_api_server). FM_DIGEST=0이면 보내지 않음.

서버는 에펨코리아에 요청하지 않음: 글 번호·제목은 사용자가 키워드 줄로 연 검색 결과 화면에서 읽어 보낸 것 (storage.fm_seen_found).
그래서 키워드 줄에서 열어 보지 않은 키워드의 새 글은 세지 못함.
"""
import html
import threading
import time
from datetime import date, datetime, timedelta

from config import log_msg, short_err, DIGEST_HOUR, FM_DIGEST
from notifier import _configured, _html_base, _send_html
from storage import fm_digest, get_meta, set_meta

DATE_META = 'fm_digest_date'
CHECK_SECONDS = 600
# 키워드마다 보일 안 읽은 글 제목 수
TITLES_PER_KEYWORD = 3
# 텔레그램 메시지 한도(4096자) 안에서 넉넉히
MAX_LENGTH = 3800
FM_POST_URL = 'https://www.fmkorea.com/{}'


def build_message(groups, day=None):
    """요약 본문(HTML). 찾은 글이 없으면 None"""
    if not groups:
        return None
    esc = html.escape
    # 같은 글이 여러 키워드에 걸리면 한 번만 셈
    found = {no for g in groups for l in g['links'] for no in l['found_nos']}
    unread = {t['no'] for g in groups for l in g['links'] for t in l['titles']}
    lines = [f"🔎 <b>FM키워드 하루 요약</b> · {(day or datetime.now()).strftime('%m/%d')}",
             f"찾은 새 글 {len(found):,} · 안 읽음 {len(unread):,}"]
    for g in groups:
        lines += ['', f"<b>{esc(g['name'])}</b>"]
        for l in g['links']:
            where = f" <i>({esc(l['board_name'])})</i>" if l.get('board_name') else ''
            state = f"안 읽음 {l['unread']}" if l['unread'] else '다 읽음'
            lines.append(f"· {esc(l['keyword'])}{where} 새 {l['found']} ({state})")
            for t in l['titles'][:TITLES_PER_KEYWORD]:
                title = esc(t['title'] or f"글 {t['no']}")
                lines.append(f"    <a href=\"{FM_POST_URL.format(t['no'])}\">{title}</a>")
            if len(l['titles']) > TITLES_PER_KEYWORD:
                lines.append(f"    … 외 {len(l['titles']) - TITLES_PER_KEYWORD}개")
    lines += ['', '키워드 줄에서 열어 본 검색에서 찾은 글만 셈']
    text = '\n'.join(lines)
    if len(text) > MAX_LENGTH:
        # 길면 뒤쪽을 자름 (태그가 반쯤 잘리지 않게 줄 단위로)
        kept, size = [], 0
        for line in lines:
            if size + len(line) + 1 > MAX_LENGTH - 20:
                kept.append('… (길어서 줄임)')
                break
            kept.append(line)
            size += len(line) + 1
        text = '\n'.join(kept)
    return text


def send_if_due(now=None):
    """보낼 때가 되었으면 한 번 보냄. 보냈으면 True"""
    now = now or datetime.now()
    today = (now.date() if isinstance(now, datetime) else date.today()).isoformat()
    if now.hour < DIGEST_HOUR or get_meta(DATE_META) == today:
        return False
    # 먼저 기록해 발송 실패로 다시 보내지 않게 함 (연결이 안 되면 notifier가 대기열에 넣어 다시 보냄)
    set_meta(DATE_META, today)
    since = (now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
    text = build_message(fm_digest(since), now)
    if not text:
        log_msg("[FM키워드 요약] 지난 24시간 찾은 새 글 없음 → 생략", "DEBUG")
        return False
    sent = _send_html(_html_base(), text, "FM키워드 하루 요약")
    log_msg(f"[FM키워드 요약] {'발송' if sent else '발송 실패'}")
    return sent


def _run():
    while True:
        try:
            send_if_due()
        except Exception as e:
            log_msg(f"[FM키워드 요약] 실패: {short_err(e)}", "WARN")
        time.sleep(CHECK_SECONDS)


def start():
    if not FM_DIGEST:
        log_msg("[FM키워드 요약] FM_DIGEST=0 - 보내지 않음", "DEBUG")
        return False
    if not _configured():
        return False
    threading.Thread(target=_run, daemon=True).start()
    return True
