"""가계부 (/ledger/): 여럿이 함께 쓰는 지출 기록. 표는 storage.py 스키마(ledger_*)에 있고 같은 DB 파일을 씀

- 사람: 관리자(LEDGER_ADMIN_NAME, 관리자 암호로 로그인)와 이름·비밀번호로 가입을 요청한 사람.
  가입 요청은 관리자가 허락해야(approved) 로그인할 수 있고, 허락받은 사람은 가계부만 씀 (다른 관리 기능은 관리자 암호가 필요)
- 로그인하면 쿠키 값(무작위)을 주고 DB에는 그 sha256만 둠. 허락을 취소하면 그 사람의 로그인도 모두 끊음
- 기록은 로그인한 사람 모두가 함께 봄. 고치기·지우기는 쓴 사람과 관리자만
- 소비형태는 모두가 함께 쓰고, 색은 사람이 직접 고름. 기록에 쓰인 소비형태는 지우지 못함
"""
import hashlib
import hmac
import re
import secrets
from datetime import date

from config import LEDGER_ADMIN_NAME
from storage import _db, _now, _get_meta, _set_meta

NAME_MAX = 20
PASSWORD_MIN = 4
PASSWORD_MAX = 100
MEMO_MAX = 60
CATEGORY_NAME_MAX = 12
AMOUNT_MAX = 10 ** 10
RECENT_MEMOS = 8
PBKDF2_ROUNDS = 120_000
COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MONTH_RE = re.compile(r'^\d{4}-\d{2}$')
# 처음 한 번 넣는 소비형태 (색은 나중에 바꿀 수 있음)
DEFAULT_CATEGORIES = [('식비', '#D85A30'), ('카페', '#EF9F27'), ('교통', '#378ADD'), ('생활', '#1D9E75'),
                      ('쇼핑', '#D4537E'), ('의료', '#534AB7')]


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
    if _get_meta(conn, 'ledger_categories_seeded'):
        return
    now = _now()
    conn.executemany("INSERT OR IGNORE INTO ledger_categories(name, color, position, created_at) VALUES(?, ?, ?, ?)",
                     [(n, c, i, now) for i, (n, c) in enumerate(DEFAULT_CATEGORIES)])
    _set_meta(conn, 'ledger_categories_seeded', 1)


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
    """그 달의 기록(모두의 것), 소비형태, 함께 쓰는 사람, 최근 메모(소비형태와 함께)"""
    month, start, end = _month_range(month)
    with _db() as conn, conn:
        _ensure_admin(conn)
        _seed_categories(conn)
        entries = conn.execute("""SELECT id, user_id, amount, used_on, category_id, memo, created_at FROM ledger_entries
                                  WHERE used_on >= ? AND used_on < ? ORDER BY used_on DESC, id DESC""", (start, end)).fetchall()
        cats = conn.execute("SELECT id, name, color FROM ledger_categories ORDER BY position, id").fetchall()
        members = conn.execute("""SELECT id, name, is_admin FROM ledger_users
                                  WHERE status = 'approved' OR id IN (SELECT DISTINCT user_id FROM ledger_entries)
                                  ORDER BY is_admin DESC, id""").fetchall()
        memos = conn.execute("""SELECT memo, category_id, MAX(id) AS last_id FROM ledger_entries WHERE memo != ''
                                GROUP BY memo ORDER BY last_id DESC LIMIT ?""", (RECENT_MEMOS,)).fetchall()
    return {'month': month,
            'entries': [dict(r) for r in entries],
            'categories': [dict(r) for r in cats],
            'members': [{'id': r['id'], 'name': r['name'], 'admin': bool(r['is_admin'])} for r in members],
            'memos': [{'memo': r['memo'], 'category_id': r['category_id']} for r in memos]}


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


def add_entry(user, amount, used_on, category_id, memo):
    with _db() as conn, conn:
        values = _entry_values(amount, used_on, category_id, memo, conn)
        now = _now()
        return conn.execute("""INSERT INTO ledger_entries(user_id, amount, used_on, category_id, memo, created_at, updated_at)
                               VALUES(?, ?, ?, ?, ?, ?, ?)""", (user['id'], *values, now, now)).lastrowid


def _own_entry(conn, user, entry_id):
    row = conn.execute("SELECT user_id FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise LedgerError('없는 기록이에요.')
    if row['user_id'] != user['id'] and not user['admin']:
        raise LedgerError('내가 쓴 기록만 고칠 수 있어요.')


def edit_entry(user, entry_id, amount, used_on, category_id, memo):
    with _db() as conn, conn:
        _own_entry(conn, user, entry_id)
        values = _entry_values(amount, used_on, category_id, memo, conn)
        conn.execute("UPDATE ledger_entries SET amount = ?, used_on = ?, category_id = ?, memo = ?, updated_at = ? WHERE id = ?",
                     (*values, _now(), entry_id))


def delete_entry(user, entry_id):
    with _db() as conn, conn:
        _own_entry(conn, user, entry_id)
        conn.execute("DELETE FROM ledger_entries WHERE id = ?", (entry_id,))


def _category_values(name, color):
    name = ' '.join(str(name or '').split())
    if not name or len(name) > CATEGORY_NAME_MAX:
        raise LedgerError(f'소비형태 이름은 1~{CATEGORY_NAME_MAX}자로 넣어 주세요.')
    if not isinstance(color, str) or not COLOR_RE.fullmatch(color):
        raise LedgerError('색을 골라 주세요.')
    return name, color.upper()


def add_category(name, color):
    name, color = _category_values(name, color)
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM ledger_categories WHERE name = ?", (name,)).fetchone():
            raise LedgerError('이미 있는 소비형태예요.')
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM ledger_categories").fetchone()[0]
        return conn.execute("INSERT INTO ledger_categories(name, color, position, created_at) VALUES(?, ?, ?, ?)",
                            (name, color, position, _now())).lastrowid


def edit_category(category_id, name, color):
    """이름·색 바꾸기 (기록은 소비형태 번호로 이어져 있어 이름을 바꿔도 함께 바뀜)"""
    name, color = _category_values(name, color)
    with _db() as conn, conn:
        if not conn.execute("SELECT 1 FROM ledger_categories WHERE id = ?", (category_id,)).fetchone():
            raise LedgerError('없는 소비형태예요.')
        if conn.execute("SELECT 1 FROM ledger_categories WHERE name = ? AND id != ?", (name, category_id)).fetchone():
            raise LedgerError('이미 있는 소비형태예요.')
        conn.execute("UPDATE ledger_categories SET name = ?, color = ? WHERE id = ?", (name, color, category_id))


def delete_category(category_id):
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM ledger_entries WHERE category_id = ?", (category_id,)).fetchone():
            raise LedgerError('기록에 쓰인 소비형태는 지울 수 없어요.')
        if not conn.execute("DELETE FROM ledger_categories WHERE id = ?", (category_id,)).rowcount:
            raise LedgerError('없는 소비형태예요.')
