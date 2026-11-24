"""가계부 변경 알림 (FCM): 누가 가계부 기록을 넣거나·고치거나·지우면(결제 알림 대기함 확정 포함), 고친 사람을 뺀
모든 사람의 휴대폰 앱(YeYe홈 1.14부터, '가계부 변경 알림'을 켠 휴대폰)에 알림을 보냄.

- 기록이 바뀔 때마다 ledger.py가 ledger_changes에 그때의 기록(전·후)을 남김
- '모두 확정'처럼 잇달아 여럿을 바꾸는 일이 있어 근무표 알림(duty_push.py)처럼 마지막으로 바꾼 뒤 QUIET_SECONDS 동안
  조용하면 고친 사람마다 알림 하나로 모음. 같은 기록을 여러 번 바꾸면 처음과 마지막만 보고, 넣었다가 지운 것·되돌린 것은 뺌
- 보낸 곳까지는 meta의 ledger_push_cursor(ledger_changes.id)로 기억함. 처음에는 예전 변경을 알리지 않고 지금부터
- 휴대폰 토큰·FCM 보내기는 duty_push.py의 것을 같이 씀
"""
import json
import threading
import time
from datetime import date, datetime, timedelta

from config import log_msg, short_err
from storage import _db, _get_meta, _set_meta
import duty_push

QUIET_SECONDS = 30
CHECK_SECONDS = 10
LINES_SHOWN = 8
KEEP_DAYS = 30              # ledger_changes를 이만큼만 둠
CHANNEL = 'ledger_change'   # 앱의 알림 채널 (DutyPush.java와 같게)
WEEKDAYS = '월화수목금토일'
LABEL = '가계부 알림'


def _day(used_on):
    d = date.fromisoformat(used_on)
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def _won(e):
    return f"{'+' if e.get('kind') == 'income' else ''}{e['amount']:,}원"


FIELDS = ('amount', 'used_on', 'category', 'kind', 'memo')


def _line(before, after):
    """바뀐 기록 한 줄 ('등록 11/24(화) 식비 12,000원 · 스타벅스', '수정 11/23(월) 교통 3,000원 → 4,500원').
    넣었다가 지웠거나 되돌려 바뀐 것이 없으면 None"""
    if before is None and after is None:
        return None
    if before is None or after is None:
        e = after or before
        memo = f" · {e['memo']}" if e.get('memo') else ''
        return f"{'등록' if before is None else '삭제'} {_day(e['used_on'])} {e['category']} {_won(e)}{memo}"
    if all(before.get(k) == after.get(k) for k in FIELDS):
        return None
    change = lambda b, a: a if a == b else f"{b} → {a}"
    parts = [change(_day(before['used_on']), _day(after['used_on'])), change(before['category'], after['category']),
             change(_won(before), _won(after))]
    memo_b, memo_a = before.get('memo') or '', after.get('memo') or ''
    if memo_a != memo_b:
        parts.append(f"· {memo_b or '메모 없음'} → {memo_a or '메모 없음'}")
    elif memo_a:
        parts.append(f"· {memo_a}")
    return '수정 ' + ' '.join(parts)


def collect(now=None):
    """보낼 알림 [{'title', 'body', 'tokens', 'channel', 'data'}]. 아직 고치는 중이면(QUIET_SECONDS 안) 빈 목록.
    돌려준 것까지 보낸 것으로 기억함"""
    now = now or datetime.now()
    quiet = (now - timedelta(seconds=QUIET_SECONDS)).strftime('%Y-%m-%d %H:%M:%S')
    with _db() as conn, conn:
        cursor = _get_meta(conn, 'ledger_push_cursor')
        last_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM ledger_changes").fetchone()[0]
        if cursor is None:
            _set_meta(conn, 'ledger_push_cursor', last_id)
            return []
        cursor = int(cursor)
        if last_id <= cursor:
            if last_id < cursor:
                _set_meta(conn, 'ledger_push_cursor', last_id)
            return []
        rows = conn.execute("""SELECT c.id, c.entry_id, c.user_id, c.before, c.after, c.changed_at, COALESCE(u.name, '') AS who
                               FROM ledger_changes c LEFT JOIN ledger_users u ON u.id = c.user_id
                               WHERE c.id > ? ORDER BY c.id""", (cursor,)).fetchall()
        if max(r['changed_at'] for r in rows) > quiet:
            return []
        _set_meta(conn, 'ledger_push_cursor', last_id)
        old = (now - timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("DELETE FROM ledger_changes WHERE changed_at < ? AND id <= ?", (old, last_id))
        tokens = duty_push.recipients(conn, 'ledger')
    groups = {}
    for r in rows:
        g = groups.setdefault(r['user_id'], {'who': r['who'], 'entries': {}})
        load = lambda v: json.loads(v) if v else None
        if r['entry_id'] not in g['entries']:
            g['entries'][r['entry_id']] = [load(r['before']), None]
        g['entries'][r['entry_id']][1] = load(r['after'])
    messages = []
    for user_id, g in groups.items():
        lines = [line for line in (_line(*v) for v in g['entries'].values()) if line]
        to = [t for t, uid in tokens if uid != user_id]
        if not lines or not to:
            continue
        shown = lines[:LINES_SHOWN] + ([f"외 {len(lines) - LINES_SHOWN}건"] if len(lines) > LINES_SHOWN else [])
        messages.append({'title': f"가계부 · {g['who'] or '?'}님", 'body': '\n'.join(shown), 'tokens': to,
                         'channel': CHANNEL, 'data': {'kind': 'ledger'}})
    return messages


def _loop():
    while True:
        time.sleep(CHECK_SECONDS)
        try:
            duty_push.send(collect(), LABEL)
        except Exception as e:
            log_msg(f"[{LABEL}] 오류: {short_err(e)}", "ERROR")


def start():
    """웹서버가 켜질 때 한 번"""
    threading.Thread(target=_loop, daemon=True, name='ledger-push').start()
