"""근무표 변경 알림 (FCM): 누가 근무표를 고치면, 고친 사람을 뺀 모든 사람의 휴대폰 앱(YeYe홈)에 알림을 보냄.

- 휴대폰 앱이 로그인하면 FCM 토큰을 등록함 (register). 토큰은 로그인한 기기(ledger_sessions)에 묶여 있어
  로그아웃하거나 허락이 취소되면 함께 지워짐
- 잇달아 여러 날을 고치는 일이 많아 바로 보내지 않고, 마지막으로 고친 뒤 QUIET_SECONDS 동안 더 고치는 것이 없으면
  그동안 바뀐 것을 근무표 주인·고친 사람마다 알림 하나로 모아 보냄 (고쳤다가 되돌린 날은 뺌)
- 보낸 곳까지는 meta의 duty_push_cursor(duty_changes.id)로 기억함. 처음에는 예전 변경을 알리지 않고 지금부터
- FCM HTTP v1: Firebase 서비스 계정 키(config.FCM_SERVICE_ACCOUNT)로 OAuth 토큰을 받아 보냄. 키가 없으면 보내지 않음
  (RS256 서명은 파이썬만으로 해서 패키지를 더 설치하지 않음)
"""
import base64
import hashlib
import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta

import requests

from config import log_msg, short_err, FCM_SERVICE_ACCOUNT
from storage import _db, _now, _get_meta, _set_meta
from ledger import _token_hash

QUIET_SECONDS = 30          # 마지막으로 고친 뒤 이만큼 조용하면 모아서 보냄
CHECK_SECONDS = 10          # 보낼 것이 있는지 보는 간격
LINES_SHOWN = 8             # 알림 하나에 보여 줄 날 수 (넘으면 '외 n일')
TOKEN_MAX = 4096
CHANNEL = 'duty_change'     # 앱의 알림 채널 (DutyPush.java와 같게)
WEEKDAYS = '월화수목금토일'
_TOKEN_RE = re.compile(r'^[A-Za-z0-9_:\-.]+$')


# ==========================================
# 토큰 (휴대폰)
# ==========================================
def register(session_token, fcm_token, duty=True, ledger=False):
    """로그인한 기기의 FCM 토큰을 등록 (같은 토큰이 다른 로그인으로 오면 옮김). 올바르면 True.
    duty·ledger: 근무표·가계부 변경 알림을 받을지 (앱 1.14부터 보냄, 그전 앱은 근무표만)"""
    fcm_token = str(fcm_token or '').strip()
    if not session_token or not fcm_token or len(fcm_token) > TOKEN_MAX or not _TOKEN_RE.fullmatch(fcm_token):
        return False
    with _db() as conn, conn:
        if not conn.execute("SELECT 1 FROM ledger_sessions WHERE token_hash = ?", (_token_hash(session_token),)).fetchone():
            return False
        conn.execute("""INSERT INTO duty_push_tokens(token, session_hash, updated_at, duty, ledger) VALUES(?, ?, ?, ?, ?)
                        ON CONFLICT(token) DO UPDATE SET session_hash = excluded.session_hash, updated_at = excluded.updated_at,
                                                         duty = excluded.duty, ledger = excluded.ledger""",
                     (fcm_token, _token_hash(session_token), _now(), int(bool(duty)), int(bool(ledger))))
    return True


def unregister(fcm_token):
    with _db() as conn, conn:
        conn.execute("DELETE FROM duty_push_tokens WHERE token = ?", (str(fcm_token or ''),))


def recipients(conn, kind='duty'):
    """[(토큰, 사람 id)] 허락받은 사람의 로그인한 기기 중 그 알림(duty·ledger)을 켠 것만"""
    column = {'duty': 'duty', 'ledger': 'ledger'}[kind]
    return [(r['token'], r['user_id']) for r in conn.execute(
        f"""SELECT t.token, s.user_id FROM duty_push_tokens t JOIN ledger_sessions s ON s.token_hash = t.session_hash
            JOIN ledger_users u ON u.id = s.user_id WHERE u.status = 'approved' AND t.{column} = 1""")]


# ==========================================
# 모으기
# ==========================================
def _day_label(day):
    d = date.fromisoformat(day)
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def collect(now=None):
    """보낼 알림 [{'title', 'body', 'person_id', 'tokens'}]. 아직 고치는 중이면(QUIET_SECONDS 안) 빈 목록.
    돌려준 것까지 보낸 것으로 기억함"""
    now = now or datetime.now()
    quiet = (now - timedelta(seconds=QUIET_SECONDS)).strftime('%Y-%m-%d %H:%M:%S')
    with _db() as conn, conn:
        cursor = _get_meta(conn, 'duty_push_cursor')
        last_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM duty_changes").fetchone()[0]
        if cursor is None:
            _set_meta(conn, 'duty_push_cursor', last_id)
            return []
        cursor = int(cursor)
        if last_id <= cursor:
            if last_id < cursor:        # 바뀐 기록이 지워져 번호가 줄었을 때
                _set_meta(conn, 'duty_push_cursor', last_id)
            return []
        rows = conn.execute("""SELECT c.id, c.person_id, c.day, c.type_id, c.user_id, c.changed_at,
                                      COALESCE(p.name, '') AS person, COALESCE(u.name, '') AS who
                               FROM duty_changes c LEFT JOIN duty_people p ON p.id = c.person_id
                               LEFT JOIN ledger_users u ON u.id = c.user_id WHERE c.id > ? ORDER BY c.id""",
                            (cursor,)).fetchall()
        if max(r['changed_at'] for r in rows) > quiet:
            return []
        _set_meta(conn, 'duty_push_cursor', last_id)
        types = {r['id']: r['name'] for r in conn.execute("SELECT id, name FROM duty_types")}
        groups = {}
        for r in rows:
            g = groups.setdefault((r['person_id'], r['user_id']), {'person': r['person'], 'who': r['who'], 'days': {}})
            if r['day'] not in g['days']:
                before = conn.execute("""SELECT type_id FROM duty_changes WHERE person_id = ? AND day = ? AND id <= ?
                                         ORDER BY id DESC LIMIT 1""", (r['person_id'], r['day'], cursor)).fetchone()
                g['days'][r['day']] = [before['type_id'] if before else None, None]
            g['days'][r['day']][1] = r['type_id']
        tokens = recipients(conn, 'duty')
    messages = []
    for (person_id, user_id), g in groups.items():
        lines = []
        for day in sorted(g['days']):
            before, after = g['days'][day]
            if before == after:
                continue
            name = lambda t: types.get(t, '?')
            if after is None:
                lines.append(f"{_day_label(day)} {name(before)} → 지움")
            elif before is None:
                lines.append(f"{_day_label(day)} {name(after)}")
            else:
                lines.append(f"{_day_label(day)} {name(before)} → {name(after)}")
        to = [t for t, uid in tokens if uid != user_id]
        if not lines or not to:
            continue
        shown = lines[:LINES_SHOWN] + ([f"외 {len(lines) - LINES_SHOWN}일"] if len(lines) > LINES_SHOWN else [])
        messages.append({'title': f"근무표 변경 · {g['person'] or '?'}",
                         'body': (f"{g['who']}님이 고침\n" if g['who'] else '') + '\n'.join(shown),
                         'person_id': person_id, 'tokens': to})
    return messages


# ==========================================
# FCM 보내기
# ==========================================
_access = {'token': '', 'until': 0.0}
_missing_warned = False


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _der(data, pos):
    """DER 하나: (태그, 내용 시작, 내용 끝)"""
    tag, length = data[pos], data[pos + 1]
    pos += 2
    if length & 0x80:
        n = length & 0x7f
        length = int.from_bytes(data[pos:pos + n], 'big')
        pos += n
    return tag, pos, pos + length


def _rsa_key(pem):
    """PKCS#8 PEM(서비스 계정 키) → (n, d)"""
    body = ''.join(l for l in pem.strip().splitlines() if not l.startswith('-----'))
    der = base64.b64decode(body)
    _, pos, _ = _der(der, 0)                     # PrivateKeyInfo
    _, s, pos = _der(der, pos)                   # version
    _, s, pos = _der(der, pos)                   # algorithm
    _, s, e = _der(der, pos)                     # privateKey (OCTET STRING)
    rsa = der[s:e]
    _, pos, _ = _der(rsa, 0)                     # RSAPrivateKey
    ints = []
    while len(ints) < 4:
        _, s, pos = _der(rsa, pos)
        ints.append(int.from_bytes(rsa[s:pos], 'big'))
    return ints[1], ints[3]                      # version, n, e, d


_SHA256_PREFIX = bytes.fromhex('3031300d060960864801650304020105000420')


def _rs256(message, n, d):
    """RSASSA-PKCS1-v1_5 SHA-256 서명"""
    k = (n.bit_length() + 7) // 8
    t = _SHA256_PREFIX + hashlib.sha256(message).digest()
    em = b'\x00\x01' + b'\xff' * (k - len(t) - 3) + b'\x00' + t
    return pow(int.from_bytes(em, 'big'), d, n).to_bytes(k, 'big')


def _account():
    global _missing_warned
    if not os.path.isfile(FCM_SERVICE_ACCOUNT):
        if not _missing_warned:
            log_msg(f"[휴대폰 알림] Firebase 서비스 계정 키({FCM_SERVICE_ACCOUNT})가 없어 휴대폰 알림을 보내지 않습니다.", "WARN")
            _missing_warned = True
        return None
    with open(FCM_SERVICE_ACCOUNT, encoding='utf-8') as f:
        return json.load(f)


def _access_token(account):
    """OAuth 토큰 (만료 5분 전까지 다시 씀)"""
    if _access['token'] and time.time() < _access['until']:
        return _access['token']
    now = int(time.time())
    uri = account.get('token_uri') or 'https://oauth2.googleapis.com/token'
    head = _b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())
    claims = _b64(json.dumps({'iss': account['client_email'], 'scope': 'https://www.googleapis.com/auth/firebase.messaging',
                              'aud': uri, 'iat': now, 'exp': now + 3600}).encode())
    n, d = _rsa_key(account['private_key'])
    jwt = f"{head}.{claims}.{_b64(_rs256(f'{head}.{claims}'.encode(), n, d))}"
    res = requests.post(uri, data={'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': jwt}, timeout=15)
    res.raise_for_status()
    reply = res.json()
    _access.update(token=reply['access_token'], until=time.time() + int(reply.get('expires_in', 3600)) - 300)
    return _access['token']


def _payload(token, m):
    """m에 channel·data가 있으면 그것으로 (가계부 알림, ledger_push.py), 없으면 근무표 알림"""
    return {'message': {
        'token': token,
        'notification': {'title': m['title'], 'body': m['body']},
        'data': m.get('data') or {'kind': 'duty', 'person_id': str(m['person_id'])},
        'android': {'priority': 'high', 'notification': {'channel_id': m.get('channel') or CHANNEL, 'icon': 'ic_notify'}},
    }}


def send(messages, label='근무표 알림'):
    """알림 보내기. 없어진 토큰(앱을 지움 등)은 지움. 보낸 개수"""
    if not messages:
        return 0
    account = _account()
    if not account:
        return 0
    try:
        bearer = _access_token(account)
    except Exception as e:
        log_msg(f"[{label}] Firebase 인증 실패: {short_err(e)}", "ERROR")
        return 0
    url = f"https://fcm.googleapis.com/v1/projects/{account['project_id']}/messages:send"
    sent = 0
    for m in messages:
        for token in m['tokens']:
            try:
                res = requests.post(url, json=_payload(token, m), headers={'Authorization': f'Bearer {bearer}'}, timeout=15)
            except Exception as e:
                log_msg(f"[{label}] 보내기 실패: {short_err(e)}", "WARN")
                continue
            if res.status_code == 200:
                sent += 1
            elif res.status_code == 404 or 'UNREGISTERED' in res.text or (res.status_code == 400 and 'registration token' in res.text):
                unregister(token)
                log_msg(f"[{label}] 없어진 휴대폰 토큰을 지움", "DEBUG")
            else:
                if res.status_code == 401:
                    _access['token'] = ''
                log_msg(f"[{label}] FCM 거절({res.status_code}): {short_err(res.text)}", "WARN")
    if sent:
        log_msg(f"[{label}] {len(messages)}건을 휴대폰 {sent}곳에 보냄")
    return sent


def _loop():
    while True:
        time.sleep(CHECK_SECONDS)
        try:
            send(collect())
        except Exception as e:
            log_msg(f"[근무표 알림] 오류: {short_err(e)}", "ERROR")


def start():
    """웹서버가 켜질 때 한 번 (모으고 보내는 스레드)"""
    threading.Thread(target=_loop, daemon=True, name='duty-push').start()
