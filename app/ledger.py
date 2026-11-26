"""가계부 (/ledger/): 여럿이 함께 쓰는 지출 기록. 표는 storage.py 스키마(ledger_*)에 있고 같은 DB 파일을 씀

- 사람: 관리자(LEDGER_ADMIN_NAME, 관리자 암호로 로그인)와 이름·비밀번호로 가입을 요청한 사람.
  가입 요청은 관리자가 허락해야(approved) 로그인할 수 있고, 허락받은 사람은 가계부만 씀 (다른 관리 기능은 관리자 암호가 필요)
- 로그인하면 쿠키 값(무작위)을 주고 DB에는 그 sha256만 둠. 허락을 취소하면 그 사람의 로그인도 모두 끊음
- 기록은 로그인한 사람 모두가 함께 봄. 고치기·지우기는 쓴 사람과 관리자만
- 분류(지출의 소비형태·수입의 종류)는 모두가 함께 쓰고, 색은 사람이 직접 고름. 기록에 쓰인 분류는 지우지 못함.
  기록이 지출인지 수입인지는 그 분류의 kind(expense·income)로 정함
- 기록을 넣거나·고치거나·지우면(대기함 확정 포함, 사진을 붙이거나 빼도) ledger_changes에 남김 → 고친 사람을 뺀 모두의
  휴대폰에 알림 (ledger_push.py), 고치기 창의 '수정 이력' (history)
- 기록마다 사진 PHOTO_MAX장까지 (photo_add·photo_delete). 화면이 휴대폰에서 줄인 JPEG(큰 것·썸네일)를 올리고
  OUTPUT_DIR/ledger_photos/{id}.jpg·{id}_t.jpg에 둠. 사진도 쓴 사람과 관리자만 붙이거나 뺄 수 있음
- 매달 반복 결제(자동이체·월급 등, ledger_recurring): 매월 그날(그 달에 없으면 말일) 같은 금액·분류·메모로 기록을 바로 넣음
  (run_recurring: 화면을 열 때와 웹서버가 10분마다, 서버가 꺼져 있던 달도 채움, 한 달에 한 번만). 만든 기록은 recurring_id로 이어지고
  반복을 만든 사람의 기록으로 들어감. 고치기·멈추기·지우기는 만든 사람과 관리자만, 지워도 이미 넣은 기록은 그대로
"""
import hashlib
import hmac
import json
import os
import re
import calendar
import secrets
import threading
from datetime import date, datetime, timedelta

from config import LEDGER_ADMIN_NAME, OUTPUT_DIR
from storage import _db, _now, _get_meta, _set_meta

NAME_MAX = 20
PASSWORD_MIN = 4
PASSWORD_MAX = 100
MEMO_MAX = 60
CATEGORY_NAME_MAX = 12
AMOUNT_MAX = 10 ** 10
MEMO_LIMIT = 1000   # 메모 자동완성용: 지금까지 쓴 메모(최근 순, 메모마다 마지막에 쓴 분류)
SEARCH_LIMIT = 300  # 모든 달 검색: 최근 것부터 이만큼까지
SEARCH_Q_MAX = 40
PBKDF2_ROUNDS = 120_000
PHOTO_DIR = os.path.join(OUTPUT_DIR, 'ledger_photos')
PHOTO_MAX = 3                      # 기록마다
PHOTO_BYTES = 4 * 1024 * 1024      # 큰 사진 (화면이 긴 쪽 1600px로 줄여 보냄)
THUMB_BYTES = 300 * 1024           # 썸네일 (긴 쪽 240px)
HISTORY_LIMIT = 100                # 수정 이력: 최근 것부터
HISTORY_MERGE_SECONDS = 30         # 같은 사람이 이만큼 안에 잇달아 바꾼 것은 이력 한 줄로 (저장 한 번 = 기록 + 사진들)
COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MONTH_RE = re.compile(r'^\d{4}-\d{2}$')
KINDS = ('expense', 'income')
# 처음 한 번 넣는 분류 (색은 나중에 바꿀 수 있음)
DEFAULT_CATEGORIES = [('식비', '#D85A30'), ('카페', '#EF9F27'), ('교통', '#378ADD'), ('생활', '#1D9E75'),
                      ('쇼핑', '#D4537E'), ('의료', '#534AB7')]
DEFAULT_INCOME_CATEGORIES = [('급여', '#185FA5'), ('부수입', '#2BA7B8'), ('용돈', '#9B5DE5'), ('이자·환급', '#639922')]


class LedgerError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 거절 이유"""


# ==========================================
# 비밀번호·로그인
# ==========================================
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return digest, salt


def _token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _ensure_admin(conn):
    """관리자 줄 (이름이 설정에서 바뀌면 따라 바꿈). id를 돌려줌"""
    row = conn.execute("SELECT id, name FROM ledger_users WHERE is_admin = 1").fetchone()
    if row:
        if row['name'] != LEDGER_ADMIN_NAME:
            conn.execute("UPDATE ledger_users SET name = ? WHERE id = ?", (LEDGER_ADMIN_NAME, row['id']))
        return row['id']
    return conn.execute("INSERT INTO ledger_users(name, is_admin, status, created_at, approved_at) VALUES(?, 1, 'approved', ?, ?)",
                        (LEDGER_ADMIN_NAME, _now(), _now())).lastrowid


def _seed_categories(conn):
    now = _now()
    if not _get_meta(conn, 'ledger_categories_seeded'):
        conn.executemany("INSERT OR IGNORE INTO ledger_categories(name, color, kind, position, created_at) VALUES(?, ?, 'expense', ?, ?)",
                         [(n, c, i, now) for i, (n, c) in enumerate(DEFAULT_CATEGORIES)])
        _set_meta(conn, 'ledger_categories_seeded', 1)
    # 수입은 나중에 생겨, 이미 쓰던 가계부에도 한 번만 넣음 (지운 수입 종류가 되살아나지 않게)
    if not _get_meta(conn, 'ledger_income_seeded'):
        base = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM ledger_categories").fetchone()[0]
        conn.executemany("INSERT OR IGNORE INTO ledger_categories(name, color, kind, position, created_at) VALUES(?, ?, 'income', ?, ?)",
                         [(n, c, base + i, now) for i, (n, c) in enumerate(DEFAULT_INCOME_CATEGORIES)])
        _set_meta(conn, 'ledger_income_seeded', 1)


def _clean_name(name):
    name = ' '.join(str(name or '').split())
    if not name or len(name) > NAME_MAX:
        raise LedgerError(f'이름은 1~{NAME_MAX}자로 넣어 주세요.')
    return name


def signup(name, password):
    """가입 요청 (관리자가 허락할 때까지 기다림)"""
    name = _clean_name(name)
    if not isinstance(password, str) or not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise LedgerError(f'비밀번호는 {PASSWORD_MIN}자 이상으로 넣어 주세요.')
    with _db() as conn, conn:
        _ensure_admin(conn)
        if conn.execute("SELECT 1 FROM ledger_users WHERE name = ?", (name,)).fetchone():
            raise LedgerError('이미 있는 이름이에요. 다른 이름을 써 주세요.')
        digest, salt = hash_password(password)
        conn.execute("INSERT INTO ledger_users(name, pw_hash, salt, status, created_at) VALUES(?, ?, ?, 'pending', ?)",
                     (name, digest, salt, _now()))


def login(name, password, admin_check):
    """이름·비밀번호가 맞으면 (쿠키에 넣을 값, 사람). 관리자 이름이면 admin_check(password)로 확인.
    틀리면 LedgerError('wrong'), 허락 전이면 LedgerError('pending')"""
    name = ' '.join(str(name or '').split())
    if not isinstance(password, str) or not password:
        raise LedgerError('wrong')
    with _db() as conn, conn:
        admin_id = _ensure_admin(conn)
        # 이름 없이 관리자 암호(또는 대시보드 로그인 키)만 오면 관리자 (관리자 기기에서 자동 로그인)
        if not name and admin_check(password):
            row = conn.execute("SELECT * FROM ledger_users WHERE id = ?", (admin_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM ledger_users WHERE name = ?", (name,)).fetchone()
        if not row:
            raise LedgerError('wrong')
        if row['is_admin']:
            if not admin_check(password):
                raise LedgerError('wrong')
        else:
            digest, _ = hash_password(password, row['salt'])
            if not hmac.compare_digest(digest, row['pw_hash'] or ''):
                raise LedgerError('wrong')
            if row['status'] != 'approved':
                raise LedgerError('pending')
        token = secrets.token_urlsafe(32)
        now = _now()
        conn.execute("INSERT INTO ledger_sessions(token_hash, user_id, created_at, last_seen) VALUES(?, ?, ?, ?)",
                     (_token_hash(token), row['id'], now, now))
        return token, _public_user(row, admin_id)


def _public_user(row, admin_id=None):
    return {'id': row['id'], 'name': row['name'], 'admin': bool(row['is_admin'])}


def user_for_token(token):
    """쿠키 값으로 로그인한 사람 (허락이 취소됐거나 없으면 None). 마지막으로 쓴 시각은 하루에 한 번만 고침"""
    if not token or len(token) > 200:
        return None
    th = _token_hash(token)
    with _db() as conn:
        row = conn.execute("""SELECT u.*, s.last_seen FROM ledger_sessions s JOIN ledger_users u ON u.id = s.user_id
                              WHERE s.token_hash = ?""", (th,)).fetchone()
        if not row or row['status'] != 'approved':
            return None
        if (row['last_seen'] or '')[:10] != _now()[:10]:
            with conn:
                conn.execute("UPDATE ledger_sessions SET last_seen = ? WHERE token_hash = ?", (_now(), th))
        return _public_user(row)


def logout(token):
    if token:
        with _db() as conn, conn:
            conn.execute("DELETE FROM ledger_sessions WHERE token_hash = ?", (_token_hash(token),))


# ==========================================
# 관리자: 가입 요청 허락·거절, 허락 취소
# ==========================================
def people():
    """{'pending': [...], 'members': [...]} (관리자 화면용)"""
    with _db() as conn, conn:
        _ensure_admin(conn)
        rows = conn.execute("SELECT id, name, is_admin, status, created_at, approved_at FROM ledger_users ORDER BY is_admin DESC, id").fetchall()
    pending = [{'id': r['id'], 'name': r['name'], 'requested_at': r['created_at']} for r in rows if r['status'] == 'pending']
    members = [{'id': r['id'], 'name': r['name'], 'admin': bool(r['is_admin']), 'approved_at': r['approved_at']}
               for r in rows if r['status'] == 'approved']
    return {'pending': pending, 'members': members}


def _target(conn, user_id):
    row = conn.execute("SELECT * FROM ledger_users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise LedgerError('없는 사람이에요.')
    if row['is_admin']:
        raise LedgerError('관리자는 바꿀 수 없어요.')
    return row


def approve(user_id):
    with _db() as conn, conn:
        _target(conn, user_id)
        conn.execute("UPDATE ledger_users SET status = 'approved', approved_at = ? WHERE id = ?", (_now(), user_id))


def reject(user_id):
    """가입 요청 거절 (요청을 지워 그 이름으로 다시 요청할 수 있게). 이미 허락한 사람은 revoke로"""
    with _db() as conn, conn:
        row = _target(conn, user_id)
        if row['status'] != 'pending':
            raise LedgerError('허락을 기다리는 사람이 아니에요.')
        if conn.execute("SELECT 1 FROM ledger_entries WHERE user_id = ?", (user_id,)).fetchone():
            raise LedgerError('기록이 있는 사람은 지울 수 없어요.')
        conn.execute("DELETE FROM ledger_users WHERE id = ?", (user_id,))


def revoke(user_id):
    """허락 취소: 다시 허락을 기다리는 상태로, 로그인한 기기는 모두 끊음 (쓴 기록은 그대로)"""
    with _db() as conn, conn:
        _target(conn, user_id)
        conn.execute("UPDATE ledger_users SET status = 'pending', approved_at = NULL WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM ledger_sessions WHERE user_id = ?", (user_id,))


# ==========================================
# 기록·소비형태
# ==========================================
def _month_range(month):
    if not MONTH_RE.fullmatch(month or ''):
        month = date.today().strftime('%Y-%m')
    return month, f'{month}-01', f'{month}-99'


def state(month):
    """그 달의 기록(모두의 것), 소비형태, 함께 쓰는 사람, 최근 메모(소비형태와 함께), 매달 반복 결제"""
    month, start, end = _month_range(month)
    run_recurring()
    with _db() as conn, conn:
        _ensure_admin(conn)
        _seed_categories(conn)
        entries = conn.execute("""SELECT id, user_id, amount, used_on, category_id, memo, created_at, recurring_id FROM ledger_entries
                                  WHERE used_on >= ? AND used_on < ? ORDER BY used_on DESC, id DESC""", (start, end)).fetchall()
        cats = conn.execute("SELECT id, name, color, kind, icon FROM ledger_categories ORDER BY position, id").fetchall()
        members = conn.execute("""SELECT id, name, is_admin FROM ledger_users
                                  WHERE status = 'approved' OR id IN (SELECT DISTINCT user_id FROM ledger_entries)
                                  ORDER BY is_admin DESC, id""").fetchall()
        memos = conn.execute("""SELECT memo, category_id, MAX(id) AS last_id FROM ledger_entries WHERE memo != ''
                                GROUP BY memo ORDER BY last_id DESC LIMIT ?""", (MEMO_LIMIT,)).fetchall()
        # 지난달과 비교 (요약·분석): 지난달 기록은 사람·분류·날짜·금액만 (사람 거르기·같은 날까지 합계는 화면에서)
        y, m = int(month[:4]), int(month[5:7])
        prev = f'{y - 1}-12' if m == 1 else f'{y}-{m - 1:02d}'
        prev_rows = conn.execute("""SELECT user_id, category_id, used_on, amount FROM ledger_entries
                                    WHERE used_on >= ? AND used_on < ?""", (f'{prev}-01', f'{prev}-99')).fetchall()
        entries = _with_photos(conn, entries)
        recurring = _recurring_list(conn)
    return {'month': month,
            'recurring': recurring,
            'entries': entries,
            'prev': {'month': prev, 'entries': [dict(r) for r in prev_rows]},
            'categories': [dict(r) for r in cats],
            'members': [{'id': r['id'], 'name': r['name'], 'admin': bool(r['is_admin'])} for r in members],
            'memos': [{'memo': r['memo'], 'category_id': r['category_id']} for r in memos]}


def _with_photos(conn, rows):
    """기록 목록(Row)을 dict로, 사진이 있으면 photos: [사진 id, ...] (붙인 순서)"""
    entries = [dict(r) for r in rows]
    ids = [e['id'] for e in entries]
    photos = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in conn.execute(f"SELECT id, entry_id FROM ledger_photos WHERE entry_id IN ({','.join('?' * len(chunk))}) ORDER BY id",
                              chunk):
            photos.setdefault(r['entry_id'], []).append(r['id'])
    for e in entries:
        e['photos'] = photos.get(e['id'], [])
    return entries


def _search_like(text):
    """LIKE 안에서 글자 그대로 찾게 % _ \\ 를 막음"""
    return '%' + text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def search(q):
    """모든 달에서 찾기: 메모·분류 이름에 q가 들어 있거나(띄어쓰기·대소문자 무시), q가 숫자면 그 금액.
    최근 것부터 SEARCH_LIMIT건. 돌려줌 {q, entries, more(더 있는지)}"""
    q = ' '.join(str(q or '').split())[:SEARCH_Q_MAX]
    if not q:
        return {'q': '', 'entries': [], 'more': False}
    like = _search_like(q.replace(' ', '').lower())
    digits = q.replace(',', '').replace('원', '').strip()
    amount = int(digits) if digits.isdigit() and len(digits) <= 11 else -1
    with _db() as conn:
        rows = conn.execute("""SELECT e.id, e.user_id, e.amount, e.used_on, e.category_id, e.memo, e.created_at
                               FROM ledger_entries e JOIN ledger_categories c ON c.id = e.category_id
                               WHERE lower(replace(e.memo, ' ', '')) LIKE ? ESCAPE '\\'
                                  OR lower(replace(c.name, ' ', '')) LIKE ? ESCAPE '\\' OR e.amount = ?
                               ORDER BY e.used_on DESC, e.id DESC LIMIT ?""", (like, like, amount, SEARCH_LIMIT + 1)).fetchall()
        entries = _with_photos(conn, rows[:SEARCH_LIMIT])
    return {'q': q, 'entries': entries, 'more': len(rows) > SEARCH_LIMIT}


def recent(limit=3):
    """앱 홈 탭 '최근 기록': 달과 상관없이 쓴 날 최근 순(같은 날이면 나중에 넣은 것), 쓴 사람 이름·분류와 함께"""
    with _db() as conn:
        rows = conn.execute("""SELECT e.id, e.amount, e.used_on, e.memo, e.user_id, COALESCE(u.name, '') AS who,
                                      c.name AS category, c.kind, c.color, c.icon
                               FROM ledger_entries e JOIN ledger_categories c ON c.id = e.category_id
                               LEFT JOIN ledger_users u ON u.id = e.user_id
                               ORDER BY e.used_on DESC, e.id DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def year_totals(year):
    """그해 달마다·사람마다·지출/수입마다 합계 [{month: 'YYYY-MM', user_id, kind, total}] (월별 합계 화면, 거르기는 화면에서)"""
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = date.today().year
    if not 2000 <= year <= 2100:
        year = date.today().year
    with _db() as conn:
        rows = conn.execute("""SELECT substr(e.used_on, 1, 7) AS month, e.user_id, c.kind, SUM(e.amount) AS total
                               FROM ledger_entries e JOIN ledger_categories c ON c.id = e.category_id
                               WHERE e.used_on >= ? AND e.used_on < ? GROUP BY month, e.user_id, c.kind ORDER BY month""",
                            (f'{year}-01-01', f'{year + 1}-01-01')).fetchall()
    return {'year': year, 'totals': [dict(r) for r in rows]}


def _entry_values(amount, used_on, category_id, memo, conn):
    if type(amount) is not int or not 0 < amount < AMOUNT_MAX:
        raise LedgerError('금액을 넣어 주세요.')
    if not isinstance(used_on, str) or not DATE_RE.fullmatch(used_on):
        raise LedgerError('날짜가 올바르지 않아요.')
    try:
        date.fromisoformat(used_on)
    except ValueError:
        raise LedgerError('날짜가 올바르지 않아요.')
    if type(category_id) is not int or not conn.execute("SELECT 1 FROM ledger_categories WHERE id = ?", (category_id,)).fetchone():
        raise LedgerError('소비형태를 골라 주세요.')
    memo = ' '.join(str(memo or '').split())[:MEMO_MAX]
    return amount, used_on, category_id, memo


def _snapshot(conn, entry_id):
    """변경 기록(ledger_changes)에 남길 그때의 기록 (분류 이름도 그때 것으로)"""
    r = conn.execute("""SELECT e.amount, e.used_on, e.memo, e.user_id, c.name AS category, c.kind,
                               (SELECT COUNT(*) FROM ledger_photos p WHERE p.entry_id = e.id) AS photos
                        FROM ledger_entries e JOIN ledger_categories c ON c.id = e.category_id WHERE e.id = ?""", (entry_id,)).fetchone()
    return json.dumps(dict(r), ensure_ascii=False) if r else None


def _log_change(conn, entry_id, actor_id, before, after):
    """누가 기록을 넣거나·고치거나·지움 (before·after는 _snapshot, 없으면 None). 휴대폰 알림(ledger_push.py)이 읽음"""
    conn.execute("INSERT INTO ledger_changes(entry_id, user_id, before, after, changed_at) VALUES(?, ?, ?, ?, ?)",
                 (entry_id, actor_id, before, after, _now()))


def add_entry(user, amount, used_on, category_id, memo, repeat_day=None):
    """기록 넣기. repeat_day(1~31)를 주면 이 기록으로 매달 반복 결제도 만듦 (다음 달 그날부터)"""
    with _db() as conn, conn:
        values = _entry_values(amount, used_on, category_id, memo, conn)
        now = _now()
        entry_id = conn.execute("""INSERT INTO ledger_entries(user_id, amount, used_on, category_id, memo, created_at, updated_at)
                                   VALUES(?, ?, ?, ?, ?, ?, ?)""", (user['id'], *values, now, now)).lastrowid
        if repeat_day is not None:
            _start_recurring(conn, entry_id, repeat_day)
        _log_change(conn, entry_id, user['id'], None, _snapshot(conn, entry_id))
        return entry_id


def _own_entry(conn, user, entry_id):
    row = conn.execute("SELECT user_id FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise LedgerError('없는 기록이에요.')
    if row['user_id'] != user['id'] and not user['admin']:
        raise LedgerError('내가 쓴 기록만 고칠 수 있어요.')


def edit_entry(user, entry_id, amount, used_on, category_id, memo, repeat_day=None, apply_future=False):
    """기록 고치기. 반복 결제가 넣은 기록이면 apply_future로 그 반복의 금액·분류·메모도 같이 (다음 달부터),
    반복이 아닌 기록에 repeat_day를 주면 이 기록으로 매달 반복 결제를 만듦"""
    with _db() as conn, conn:
        _own_entry(conn, user, entry_id)
        values = _entry_values(amount, used_on, category_id, memo, conn)
        before = _snapshot(conn, entry_id)
        conn.execute("UPDATE ledger_entries SET amount = ?, used_on = ?, category_id = ?, memo = ?, updated_at = ? WHERE id = ?",
                     (*values, _now(), entry_id))
        rec = conn.execute("""SELECT r.id FROM ledger_entries e JOIN ledger_recurring r ON r.id = e.recurring_id
                              WHERE e.id = ?""", (entry_id,)).fetchone()
        if rec and apply_future:
            conn.execute("UPDATE ledger_recurring SET amount = ?, category_id = ?, memo = ?, updated_at = ? WHERE id = ?",
                         (values[0], values[2], values[3], _now(), rec['id']))
        elif not rec and repeat_day is not None:
            _start_recurring(conn, entry_id, repeat_day)
        after = _snapshot(conn, entry_id)
        if after != before:   # 바꾼 것 없이 저장만 누른 것은 남기지 않음
            _log_change(conn, entry_id, user['id'], before, after)


def delete_entry(user, entry_id):
    with _db() as conn, conn:
        _own_entry(conn, user, entry_id)
        before = _snapshot(conn, entry_id)
        photos = [r['id'] for r in conn.execute("SELECT id FROM ledger_photos WHERE entry_id = ?", (entry_id,))]
        conn.execute("DELETE FROM ledger_entries WHERE id = ?", (entry_id,))
        _log_change(conn, entry_id, user['id'], before, None)
    for photo_id in photos:
        _remove_photo_files(photo_id)


def history(entry_id):
    """그 기록의 수정 이력 (최근 것부터 HISTORY_LIMIT개): [{who, changed_at, before, after}] (before·after는 _snapshot 또는 None).
    한 번 저장하면 기록 고치기와 사진 올리기·빼기가 따로 남으므로, 같은 사람이 HISTORY_MERGE_SECONDS 안에 잇달아 바꾼 것은
    한 줄로 묶음 (처음의 before·마지막의 after). 묶어서 바뀐 것이 없으면 뺌. 기록은 로그인한 모두가 보므로 이력도 모두가 봄"""
    with _db() as conn:
        rows = conn.execute("""SELECT c.user_id, c.before, c.after, c.changed_at, COALESCE(u.name, '') AS who FROM ledger_changes c
                               LEFT JOIN ledger_users u ON u.id = c.user_id WHERE c.entry_id = ? ORDER BY c.id""",
                            (entry_id,)).fetchall()
    load = lambda v: json.loads(v) if v else None
    at = lambda v: datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
    groups = []
    for r in rows:
        g = groups[-1] if groups else None
        if (g and g['user_id'] == r['user_id'] and g['after'] is not None
                and (at(r['changed_at']) - at(g['changed_at'])).total_seconds() <= HISTORY_MERGE_SECONDS):
            g.update(after=load(r['after']), changed_at=r['changed_at'])
        else:
            groups.append({'user_id': r['user_id'], 'who': r['who'], 'changed_at': r['changed_at'],
                           'before': load(r['before']), 'after': load(r['after'])})
    shown = [{k: g[k] for k in ('who', 'changed_at', 'before', 'after')} for g in groups
             if not (g['before'] is not None and g['before'] == g['after'])]
    return shown[::-1][:HISTORY_LIMIT]


# ==========================================
# 사진
# ==========================================
def photo_path(photo_id, thumb=False):
    return os.path.join(PHOTO_DIR, f"{int(photo_id)}{'_t' if thumb else ''}.jpg")


def _is_jpeg(data):
    return len(data) > 100 and data[:3] == b'\xff\xd8\xff'


def _remove_photo_files(photo_id):
    for thumb in (False, True):
        try:
            os.remove(photo_path(photo_id, thumb))
        except FileNotFoundError:
            pass


def photo_add(user, entry_id, photo, thumb):
    """기록에 사진 하나 붙임 (photo·thumb: JPEG 바이트) → 사진 id"""
    if not _is_jpeg(photo) or not _is_jpeg(thumb):
        raise LedgerError('사진(JPEG)이 아니에요.')
    if len(photo) > PHOTO_BYTES or len(thumb) > THUMB_BYTES:
        raise LedgerError('사진이 너무 커요.')
    os.makedirs(PHOTO_DIR, exist_ok=True)
    with _db() as conn, conn:
        _own_entry(conn, user, entry_id)
        if conn.execute("SELECT COUNT(*) FROM ledger_photos WHERE entry_id = ?", (entry_id,)).fetchone()[0] >= PHOTO_MAX:
            raise LedgerError(f'사진은 {PHOTO_MAX}장까지 붙일 수 있어요.')
        before = _snapshot(conn, entry_id)
        photo_id = conn.execute("INSERT INTO ledger_photos(entry_id, user_id, created_at) VALUES(?, ?, ?)",
                                (entry_id, user['id'], _now())).lastrowid
        try:
            for data, is_thumb in ((photo, False), (thumb, True)):
                path = photo_path(photo_id, is_thumb)
                with open(path + '.tmp', 'wb') as f:
                    f.write(data)
                os.replace(path + '.tmp', path)
        except OSError:
            _remove_photo_files(photo_id)
            raise
        conn.execute("UPDATE ledger_entries SET updated_at = ? WHERE id = ?", (_now(), entry_id))
        _log_change(conn, entry_id, user['id'], before, _snapshot(conn, entry_id))
        return photo_id


def photo_delete(user, photo_id):
    with _db() as conn, conn:
        row = conn.execute("SELECT entry_id FROM ledger_photos WHERE id = ?", (photo_id,)).fetchone()
        if not row:
            raise LedgerError('없는 사진이에요.')
        _own_entry(conn, user, row['entry_id'])
        before = _snapshot(conn, row['entry_id'])
        conn.execute("DELETE FROM ledger_photos WHERE id = ?", (photo_id,))
        conn.execute("UPDATE ledger_entries SET updated_at = ? WHERE id = ?", (_now(), row['entry_id']))
        _log_change(conn, row['entry_id'], user['id'], before, _snapshot(conn, row['entry_id']))
    _remove_photo_files(photo_id)


def photo_exists(photo_id):
    with _db() as conn:
        return bool(conn.execute("SELECT 1 FROM ledger_photos WHERE id = ?", (photo_id,)).fetchone())


def _category_values(name, color):
    name = ' '.join(str(name or '').split())
    if not name or len(name) > CATEGORY_NAME_MAX:
        raise LedgerError(f'이름은 1~{CATEGORY_NAME_MAX}자로 넣어 주세요.')
    if not isinstance(color, str) or not COLOR_RE.fullmatch(color):
        raise LedgerError('색을 골라 주세요.')
    return name, color.upper()


ICON_MAX = 8   # 이모지 하나 (여러 글자로 된 이모지까지)


def _icon_value(icon):
    icon = str(icon or '').strip()
    if len(icon) > ICON_MAX or any(c.isspace() for c in icon):
        raise LedgerError('아이콘을 다시 골라 주세요.')
    return icon


def add_category(name, color, kind='expense', icon=''):
    name, color = _category_values(name, color)
    icon = _icon_value(icon)
    if kind not in KINDS:
        raise LedgerError('지출인지 수입인지 골라 주세요.')
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM ledger_categories WHERE name = ?", (name,)).fetchone():
            raise LedgerError('이미 있는 이름이에요.')
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM ledger_categories").fetchone()[0]
        return conn.execute("INSERT INTO ledger_categories(name, color, kind, position, created_at, icon) VALUES(?, ?, ?, ?, ?, ?)",
                            (name, color, kind, position, _now(), icon)).lastrowid


def edit_category(category_id, name, color, icon=None):
    """이름·색(·아이콘, None이면 그대로) 바꾸기 (기록은 소비형태 번호로 이어져 있어 이름을 바꿔도 함께 바뀜)"""
    name, color = _category_values(name, color)
    icon = None if icon is None else _icon_value(icon)
    with _db() as conn, conn:
        if not conn.execute("SELECT 1 FROM ledger_categories WHERE id = ?", (category_id,)).fetchone():
            raise LedgerError('없는 소비형태예요.')
        if conn.execute("SELECT 1 FROM ledger_categories WHERE name = ? AND id != ?", (name, category_id)).fetchone():
            raise LedgerError('이미 있는 이름이에요.')
        conn.execute("UPDATE ledger_categories SET name = ?, color = ?, icon = COALESCE(?, icon) WHERE id = ?", (name, color, icon, category_id))


def reorder_categories(ids):
    """분류 순서 바꾸기: ids(모든 분류 번호, 보일 순서대로). 빠진 분류는 그 뒤에 원래 순서대로"""
    if not isinstance(ids, list) or not ids or not all(type(i) is int for i in ids) or len(set(ids)) != len(ids):
        raise LedgerError('순서를 다시 보내 주세요.')
    with _db() as conn, conn:
        known = [r['id'] for r in conn.execute("SELECT id FROM ledger_categories ORDER BY position, id")]
        if not set(ids) <= set(known):
            raise LedgerError('없는 분류가 있어요.')
        order = ids + [i for i in known if i not in set(ids)]
        conn.executemany("UPDATE ledger_categories SET position = ? WHERE id = ?", [(n, i) for n, i in enumerate(order)])


def delete_category(category_id):
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM ledger_entries WHERE category_id = ?", (category_id,)).fetchone():
            raise LedgerError('기록에 쓰인 소비형태는 지울 수 없어요.')
        if conn.execute("SELECT 1 FROM ledger_recurring WHERE category_id = ?", (category_id,)).fetchone():
            raise LedgerError('반복 결제에 쓰인 분류는 지울 수 없어요.')
        if not conn.execute("DELETE FROM ledger_categories WHERE id = ?", (category_id,)).rowcount:
            raise LedgerError('없는 소비형태예요.')


# ==========================================
# 매달 반복 결제 (자동이체·월급 등)
# ==========================================
RECURRING_MAX = 100          # 모두 합쳐
RECURRING_CATCHUP = 24       # 서버가 오래 꺼져 있었어도 반복마다 이만큼(달)까지만 채움
RECURRING_MATCH_DAYS = 3     # 결제 알림이 반복일 앞뒤 이만큼 안이고 금액이 같으면 '반복 결제로 이미 기록됨'
_recurring_lock = threading.Lock()


def _on_day(y, m, day):
    """y년 m월의 day일 (그 달에 없으면 말일)"""
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def _month_after(d, day):
    """d가 든 달의 다음 달 day일"""
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return _on_day(y, m, day)


def _next_after(day, after):
    """after 다음(after는 빼고) 처음 오는 매월 day일"""
    d = _on_day(after.year, after.month, day)
    return d if d > after else _month_after(after, day)


def _repeat_day(day):
    if type(day) is not int or not 1 <= day <= 31:
        raise LedgerError('반복할 날을 골라 주세요.')
    return day


def _start_recurring(conn, entry_id, day):
    """이 기록으로 매달 반복 결제를 만들고 기록을 이어 둠. 처음 넣을 날은 기록한 날·오늘 다음의 그날 (지난 달을 거슬러 넣지 않음)"""
    day = _repeat_day(day)
    if conn.execute("SELECT COUNT(*) FROM ledger_recurring").fetchone()[0] >= RECURRING_MAX:
        raise LedgerError(f'반복 결제는 {RECURRING_MAX}개까지 만들 수 있어요.')
    e = conn.execute("SELECT user_id, amount, used_on, category_id, memo FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone()
    nxt = _next_after(day, max(date.fromisoformat(e['used_on']), date.today()))
    now = _now()
    rec_id = conn.execute("""INSERT INTO ledger_recurring(user_id, amount, category_id, memo, day, next_on, created_at, updated_at)
                             VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                          (e['user_id'], e['amount'], e['category_id'], e['memo'], day, nxt.isoformat(), now, now)).lastrowid
    conn.execute("UPDATE ledger_entries SET recurring_id = ? WHERE id = ?", (rec_id, entry_id))
    return rec_id


def _recurring_list(conn):
    return [dict(r) for r in conn.execute("""SELECT id, user_id, amount, category_id, memo, day, next_on, paused FROM ledger_recurring
                                             ORDER BY paused, day, id""")]


def recurring_list():
    with _db() as conn:
        return _recurring_list(conn)


def run_recurring(today=None):
    """반복일이 된(지난) 반복 결제의 기록을 넣음 (서버가 꺼져 있던 달도, 한 달에 한 번만). 넣은 수"""
    today = today or date.today()
    made = 0
    with _recurring_lock, _db() as conn, conn:
        for r in conn.execute("SELECT * FROM ledger_recurring WHERE paused = 0 AND next_on <= ?", (today.isoformat(),)).fetchall():
            nxt, n = date.fromisoformat(r['next_on']), 0
            while nxt <= today and n < RECURRING_CATCHUP:
                now = _now()
                entry_id = conn.execute("""INSERT INTO ledger_entries(user_id, amount, used_on, category_id, memo, created_at, updated_at, recurring_id)
                                           VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                                        (r['user_id'], r['amount'], nxt.isoformat(), r['category_id'], r['memo'], now, now, r['id'])).lastrowid
                _log_change(conn, entry_id, r['user_id'], None, _snapshot(conn, entry_id))
                nxt, n, made = _month_after(nxt, r['day']), n + 1, made + 1
            if nxt <= today:
                nxt = _next_after(r['day'], today)
            conn.execute("UPDATE ledger_recurring SET next_on = ? WHERE id = ?", (nxt.isoformat(), r['id']))
    return made


def _own_recurring(conn, user, rec_id):
    row = conn.execute("SELECT * FROM ledger_recurring WHERE id = ?", (rec_id,)).fetchone()
    if not row:
        raise LedgerError('없는 반복 결제예요.')
    if row['user_id'] != user['id'] and not user['admin']:
        raise LedgerError('내가 만든 반복 결제만 고칠 수 있어요.')
    return row


def edit_recurring(user, rec_id, amount, day, category_id, memo):
    """반복 결제 고치기 (다음에 넣을 것부터). 날을 바꾸면 다음에 넣을 달은 그대로 두고 그 달의 새 날로"""
    with _db() as conn, conn:
        row = _own_recurring(conn, user, rec_id)
        day = _repeat_day(day)
        amount, _, category_id, memo = _entry_values(amount, row['next_on'], category_id, memo, conn)
        nxt = date.fromisoformat(row['next_on'])
        if day != row['day']:
            nxt = _on_day(nxt.year, nxt.month, day)
        conn.execute("UPDATE ledger_recurring SET amount = ?, day = ?, category_id = ?, memo = ?, next_on = ?, updated_at = ? WHERE id = ?",
                     (amount, day, category_id, memo, nxt.isoformat(), _now(), rec_id))
    run_recurring()   # 새 날이 이미 지났으면 그 달 것을 바로


def pause_recurring(user, rec_id, paused):
    """멈추기·다시 시작. 다시 시작할 때 멈춘 동안 지난 달은 채우지 않음 (오늘부터 처음 오는 그날)"""
    with _db() as conn, conn:
        row = _own_recurring(conn, user, rec_id)
        nxt = date.fromisoformat(row['next_on'])
        if not paused and nxt < date.today():
            nxt = _next_after(row['day'], date.today() - timedelta(days=1))
        conn.execute("UPDATE ledger_recurring SET paused = ?, next_on = ?, updated_at = ? WHERE id = ?",
                     (1 if paused else 0, nxt.isoformat(), _now(), rec_id))
    run_recurring()


def delete_recurring(user, rec_id):
    """반복 결제 지우기. 이미 넣은 기록은 그대로 (반복 표시만 없어짐)"""
    with _db() as conn, conn:
        _own_recurring(conn, user, rec_id)
        conn.execute("UPDATE ledger_entries SET recurring_id = NULL WHERE recurring_id = ?", (rec_id,))
        conn.execute("DELETE FROM ledger_recurring WHERE id = ?", (rec_id,))


def _recurring_match(conn, item):
    """결제 알림과 같은 반복 결제: 금액이 같고, 반복이 넣은 기록이 알림 날 앞뒤 RECURRING_MATCH_DAYS일 안에 있거나
    곧 넣을 날(next_on)이 그 안이면 {memo, used_on, done(이미 넣었는지)}. 알림 이름이 반복의 메모와 달라도 (예: '신한은행 자동이체' → 'XX 보험')"""
    lo, hi = f'-{RECURRING_MATCH_DAYS} days', f'+{RECURRING_MATCH_DAYS} days'
    e = conn.execute("""SELECT memo, used_on FROM ledger_entries WHERE recurring_id IS NOT NULL AND amount = ?
                        AND used_on BETWEEN date(?, ?) AND date(?, ?) ORDER BY ABS(julianday(used_on) - julianday(?)) LIMIT 1""",
                     (item['amount'], item['used_on'], lo, item['used_on'], hi, item['used_on'])).fetchone()
    if e:
        return {'memo': e['memo'], 'used_on': e['used_on'], 'done': True}
    r = conn.execute("""SELECT memo, next_on FROM ledger_recurring WHERE paused = 0 AND amount = ?
                        AND next_on BETWEEN date(?, ?) AND date(?, ?) LIMIT 1""",
                     (item['amount'], item['used_on'], lo, item['used_on'], hi)).fetchone()
    return {'memo': r['memo'], 'used_on': r['next_on'], 'done': False} if r else None


# ==========================================
# 자동 기록: 휴대폰 결제 알림 → 확인 대기함 → 확정하면 기록 (ledger_parse.py가 알림 글을 읽음)
# 휴대폰(매크로드로이드 등)은 사람마다 받은 연결 주소(/api/ledger/hook/<키>)로 알림 글을 보냄
# ==========================================
HOOK_MAX_PER_HOUR = 120
HOOK_DUPLICATE_MINUTES = 10
CANCEL_MATCH_DAYS = 60
RULE_PATTERN_MAX = 20
TEST_NOTICE = '[삼성카드] 테스트 승인 1,000원 일시불 {date} {time} 가계부 연결 시험'


def create_hook_key(user):
    """새 연결 키 (예전 키는 더 못 씀). 키 글자는 이때 한 번만 돌려줌"""
    key = secrets.token_urlsafe(24)
    with _db() as conn, conn:
        conn.execute("""INSERT INTO ledger_hook_keys(user_id, key_hash, hint, created_at) VALUES(?, ?, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET key_hash = excluded.key_hash, hint = excluded.hint,
                        created_at = excluded.created_at, last_used = NULL, last_status = NULL""",
                     (user['id'], _token_hash(key), key[-4:], _now()))
    return key


def hook_info(user):
    with _db() as conn:
        row = conn.execute("SELECT hint, created_at, last_used, last_status FROM ledger_hook_keys WHERE user_id = ?", (user['id'],)).fetchone()
    return dict(row) if row else None


def _rule_category(conn, merchant):
    from ledger_parse import rule_key
    key = rule_key(merchant)
    if not key:
        return None
    for r in conn.execute("SELECT pattern, category_id FROM ledger_rules ORDER BY length(pattern) DESC, id"):
        if rule_key(r['pattern']) and rule_key(r['pattern']) in key:
            return r['category_id']
    return None


def _store_notice(conn, user_id, text, parsed):
    category = None if parsed['cancel'] else _rule_category(conn, parsed['merchant'])
    return conn.execute("""INSERT INTO ledger_inbox(user_id, raw, amount, merchant, card, used_on, used_time, is_cancel, category_id, created_at)
                           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (user_id, text[:500], parsed['amount'], parsed['merchant'], parsed['card'], parsed['used_on'],
                         parsed['time'], 1 if parsed['cancel'] else 0, category, _now())).lastrowid


def hook_key_valid(key):
    """허락받은 사람의 연결 키인지 (앱이 새 버전을 확인·받을 때)"""
    if not key or len(key) > 100:
        return False
    with _db() as conn:
        return conn.execute("""SELECT 1 FROM ledger_hook_keys k JOIN ledger_users u ON u.id = k.user_id
                               WHERE k.key_hash = ? AND u.status = 'approved'""", (_token_hash(key),)).fetchone() is not None


def receive_hook(key, text):
    """연결 키로 온 알림 글. 결과: 'saved'·'ignored'(결제 알림 아님)·'duplicate'·'too_many', 모르는 키면 None"""
    found = receive_hook_detail(key, text)
    return found and found[0]


def receive_hook_detail(key, text):
    """receive_hook과 같고, 대기함에 넣었으면 넣은 내용도: (결과, {amount, merchant, card, cancel, category}) — 앱의 '금액 인식 알림'용.
    넣지 않았으면 내용은 None, 모르는 키면 None"""
    from ledger_parse import parse
    if not key or len(key) > 100:
        return None
    with _db() as conn, conn:
        row = conn.execute("""SELECT k.user_id FROM ledger_hook_keys k JOIN ledger_users u ON u.id = k.user_id
                              WHERE k.key_hash = ? AND u.status = 'approved'""", (_token_hash(key),)).fetchone()
        if not row:
            return None
        user_id, now = row['user_id'], _now()
        text = str(text or '').strip()
        parsed = parse(text)
        if not parsed:
            result = 'ignored'
        elif conn.execute("SELECT 1 FROM ledger_inbox WHERE user_id = ? AND raw = ? AND created_at >= datetime(?, ?)",
                          (user_id, text[:500], now, f'-{HOOK_DUPLICATE_MINUTES} minutes')).fetchone():
            result = 'duplicate'
        elif conn.execute("SELECT COUNT(*) FROM ledger_inbox WHERE user_id = ? AND created_at >= datetime(?, '-1 hour')",
                          (user_id, now)).fetchone()[0] >= HOOK_MAX_PER_HOUR:
            result = 'too_many'
        else:
            notice_id = _store_notice(conn, user_id, text, parsed)
            result = 'saved'
        item = None
        if result == 'saved':
            cat = conn.execute("SELECT c.name FROM ledger_inbox i JOIN ledger_categories c ON c.id = i.category_id "
                               "WHERE i.id = ?", (notice_id,)).fetchone()
            item = {'amount': parsed['amount'], 'merchant': parsed['merchant'], 'card': parsed['card'],
                    'cancel': bool(parsed['cancel']), 'category': cat['name'] if cat else None}
        conn.execute("UPDATE ledger_hook_keys SET last_used = ?, last_status = ? WHERE user_id = ?", (now, result, user_id))
        return result, item


def send_test_notice(user):
    """'시험 알림 보내기': 연결 주소로 온 것처럼 대기함에 시험 결제 하나"""
    from ledger_parse import parse
    now = _now()
    text = TEST_NOTICE.format(date=f'{int(now[5:7])}/{int(now[8:10])}', time=now[11:16])
    with _db() as conn, conn:
        _store_notice(conn, user['id'], text, parse(text))


def _cancel_match(conn, item):
    """취소 알림과 맞는 기록: 같은 사람·같은 금액·같은 가게, 취소일 이전 CANCEL_MATCH_DAYS일 안에서 가장 최근"""
    from ledger_parse import rule_key
    rows = conn.execute("""SELECT id, used_on, memo FROM ledger_entries WHERE user_id = ? AND amount = ? AND used_on <= ?
                           AND used_on >= date(?, ?) ORDER BY used_on DESC, id DESC""",
                        (item['user_id'], item['amount'], item['used_on'], item['used_on'], f'-{CANCEL_MATCH_DAYS} days')).fetchall()
    key = rule_key(item['merchant'])
    for r in rows:
        memo = rule_key(r['memo'])
        if not key or not memo or key in memo or memo in key:
            return {'id': r['id'], 'used_on': r['used_on']}
    return None


def _history_map(conn):
    """지난 기록의 분류 추천: {가게 글자(rule_key): (분류 ID, 그 분류로 쓴 횟수, 메모)}. 가계부를 함께 쓰는 사람 모두의 지출 기록에서,
    메모가 같은 가게(띄어쓰기·(주) 등을 빼고 같은 글자)로 가장 많이 쓴 분류 (같으면 최근에 쓴 것)"""
    from ledger_parse import rule_key
    found = {}   # key -> {category_id: (횟수, 최근 (used_on, id), 그 최근 기록의 메모)}
    for r in conn.execute("""SELECT e.id, e.memo, e.used_on, e.category_id FROM ledger_entries e
                             JOIN ledger_categories c ON c.id = e.category_id WHERE c.kind = 'expense' AND e.memo != ''"""):
        key = rule_key(r['memo'])
        if not key:
            continue
        cats = found.setdefault(key, {})
        count, last, memo = cats.get(r['category_id'], (0, ('', 0), ''))
        if (r['used_on'], r['id']) > last:
            last, memo = (r['used_on'], r['id']), r['memo']
        cats[r['category_id']] = (count + 1, last, memo)
    out = {}
    for key, cats in found.items():
        cat, (count, _, memo) = max(cats.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        out[key] = (cat, count, memo)
    return out


def _suggest(history, item):
    """분류가 없는 결제 알림의 추천 {category_id, memo, count} (규칙이 먼저라 규칙으로 정해진 것·취소는 없음)"""
    from ledger_parse import rule_key
    if item['is_cancel'] or item['category_id'] is not None:
        return None
    found = history.get(rule_key(item['merchant']))
    return {'category_id': found[0], 'count': found[1], 'memo': found[2]} if found else None


def inbox(user):
    """내 확인 대기함 (최근 순). 취소 알림은 지울 기록을 찾아 붙임. 분류가 없는 결제는 지난 기록의 추천(suggest)을 붙임"""
    with _db() as conn:
        rows = conn.execute("SELECT * FROM ledger_inbox WHERE user_id = ? AND discarded_at IS NULL ORDER BY used_on DESC, used_time DESC, id DESC",
                            (user['id'],)).fetchall()
        history = _history_map(conn) if rows else {}
        items = []
        for r in rows:
            item = {k: r[k] for k in ('id', 'raw', 'amount', 'merchant', 'card', 'used_on', 'used_time', 'category_id', 'created_at')}
            item['cancel'] = bool(r['is_cancel'])
            if item['cancel']:
                item['match'] = _cancel_match(conn, r)
            item['suggest'] = _suggest(history, r)
            item['recurring'] = None if item['cancel'] else _recurring_match(conn, r)
            items.append(item)
    return items


def rules():
    with _db() as conn:
        return [dict(r) for r in conn.execute("SELECT id, pattern, category_id FROM ledger_rules ORDER BY pattern")]


def _own_item(conn, user, item_id, discarded=False):
    """내 대기함의 알림 (discarded=True면 버린 알림 중에서)"""
    row = conn.execute("SELECT * FROM ledger_inbox WHERE id = ?", (item_id,)).fetchone()
    if not row or row['user_id'] != user['id'] or (row['discarded_at'] is not None) != discarded:
        raise LedgerError('없는 알림이에요.')
    return row


def update_item(user, item_id, category_id=None, amount=None, merchant=None, used_on=None):
    """확정 전에 분류·금액·가게·날짜 고치기 (보낸 것만)"""
    with _db() as conn, conn:
        row = _own_item(conn, user, item_id)
        amount = row['amount'] if amount is None else amount
        used_on = row['used_on'] if used_on is None else used_on
        merchant = row['merchant'] if merchant is None else ' '.join(str(merchant).split())[:MEMO_MAX]
        category_id = row['category_id'] if category_id is None else category_id
        if type(amount) is not int or not 0 < amount < AMOUNT_MAX:
            raise LedgerError('금액을 넣어 주세요.')
        try:
            if not DATE_RE.fullmatch(str(used_on)):
                raise ValueError
            date.fromisoformat(used_on)
        except ValueError:
            raise LedgerError('날짜가 올바르지 않아요.')
        if category_id is not None and not conn.execute("SELECT 1 FROM ledger_categories WHERE id = ?", (category_id,)).fetchone():
            raise LedgerError('없는 분류예요.')
        conn.execute("UPDATE ledger_inbox SET amount = ?, merchant = ?, used_on = ?, category_id = ? WHERE id = ?",
                     (amount, merchant, used_on, category_id, item_id))


def _confirm_row(conn, row, history=None):
    if row['is_cancel']:
        match = _cancel_match(conn, row)
        if match:
            before = _snapshot(conn, match['id'])
            conn.execute("DELETE FROM ledger_entries WHERE id = ?", (match['id'],))
            _log_change(conn, match['id'], row['user_id'], before, None)
    else:
        # 분류를 고르지 않았으면 지난 기록의 추천으로 (화면에 미리 골라 보여 준 것)
        suggest = _suggest(history if history is not None else _history_map(conn), row)
        category_id = row['category_id'] if row['category_id'] is not None else suggest and suggest['category_id']
        if category_id is None:
            raise LedgerError('분류를 골라 주세요.')
        now = _now()
        entry_id = conn.execute("""INSERT INTO ledger_entries(user_id, amount, used_on, category_id, memo, created_at, updated_at)
                                   VALUES(?, ?, ?, ?, ?, ?, ?)""", (row['user_id'], row['amount'], row['used_on'], category_id,
                                                                   row['merchant'][:MEMO_MAX], now, now)).lastrowid
        _log_change(conn, entry_id, row['user_id'], None, _snapshot(conn, entry_id))
    conn.execute("DELETE FROM ledger_inbox WHERE id = ?", (row['id'],))


def confirm_item(user, item_id):
    """확정: 결제는 기록으로(메모는 가게 이름), 취소는 맞는 기록을 지움"""
    with _db() as conn, conn:
        _confirm_row(conn, _own_item(conn, user, item_id))


def confirm_all(user):
    """분류가 정해진(지난 기록의 추천 포함) 결제와 지울 기록을 찾은 취소를 한꺼번에 확정. 확정한 수.
    추천은 확정을 시작할 때의 기록으로 (이번에 확정한 것이 뒤의 추천을 바꾸지 않게)"""
    done = 0
    with _db() as conn, conn:
        history = _history_map(conn)
        for row in conn.execute("SELECT * FROM ledger_inbox WHERE user_id = ? AND discarded_at IS NULL", (user['id'],)).fetchall():
            if (row['is_cancel'] and _cancel_match(conn, row)) or (not row['is_cancel'] and (row['category_id'] is not None or _suggest(history, row))):
                _confirm_row(conn, row, history)
                done += 1
    return done


DISCARD_KEEP_DAYS = 30


def discard_item(user, item_id):
    """버리기: 대기함에서 빼되 DISCARD_KEEP_DAYS일 동안 보관 (되살릴 수 있게)"""
    with _db() as conn, conn:
        _own_item(conn, user, item_id)
        conn.execute("UPDATE ledger_inbox SET discarded_at = ? WHERE id = ?", (_now(), item_id))


def restore_item(user, item_id):
    """버린 알림을 대기함으로 되살림"""
    with _db() as conn, conn:
        _own_item(conn, user, item_id, discarded=True)
        conn.execute("UPDATE ledger_inbox SET discarded_at = NULL WHERE id = ?", (item_id,))


def discarded(user):
    """내가 버린 알림 (최근 버린 순, 최근 DISCARD_KEEP_DAYS일). 그보다 오래된 것은 이때 지움"""
    with _db() as conn, conn:
        conn.execute("DELETE FROM ledger_inbox WHERE discarded_at IS NOT NULL AND discarded_at < datetime(?, ?)",
                     (_now(), f'-{DISCARD_KEEP_DAYS} days'))
        rows = conn.execute("""SELECT id, raw, amount, merchant, card, used_on, used_time, is_cancel, discarded_at FROM ledger_inbox
                               WHERE user_id = ? AND discarded_at IS NOT NULL ORDER BY discarded_at DESC, id DESC LIMIT 100""",
                            (user['id'],)).fetchall()
    # raw: 받은 알림 글 (앱의 '이런 알림 안 받기'에서 낱말을 고를 때, 300자까지)
    return [{**{k: r[k] for k in ('id', 'amount', 'merchant', 'card', 'used_on', 'used_time', 'discarded_at')},
             'cancel': bool(r['is_cancel']), 'raw': (r['raw'] or '')[:300]}
            for r in rows]


def add_rule(pattern, category_id):
    """가게 이름 규칙. 넣으면 대기함에서 아직 분류가 없는 결제에도 바로 적용"""
    from ledger_parse import rule_key
    pattern = ' '.join(str(pattern or '').split())[:RULE_PATTERN_MAX]
    if len(rule_key(pattern)) < 2:
        raise LedgerError('가게 이름에 든 글자를 두 글자 이상 넣어 주세요.')
    with _db() as conn, conn:
        if type(category_id) is not int or not conn.execute("SELECT 1 FROM ledger_categories WHERE id = ?", (category_id,)).fetchone():
            raise LedgerError('분류를 골라 주세요.')
        same = [r['id'] for r in conn.execute("SELECT id, pattern FROM ledger_rules") if rule_key(r['pattern']) == rule_key(pattern)]
        if same:
            conn.execute("UPDATE ledger_rules SET category_id = ? WHERE id = ?", (category_id, same[0]))
        else:
            conn.execute("INSERT INTO ledger_rules(pattern, category_id, created_at) VALUES(?, ?, ?)", (pattern, category_id, _now()))
        for r in conn.execute("SELECT id, merchant FROM ledger_inbox WHERE category_id IS NULL AND is_cancel = 0").fetchall():
            found = _rule_category(conn, r['merchant'])
            if found:
                conn.execute("UPDATE ledger_inbox SET category_id = ? WHERE id = ?", (found, r['id']))


def delete_rule(rule_id):
    with _db() as conn, conn:
        if not conn.execute("DELETE FROM ledger_rules WHERE id = ?", (rule_id,)).rowcount:
            raise LedgerError('없는 규칙이에요.')
