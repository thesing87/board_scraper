"""가계부 (/ledger/): 여럿이 함께 쓰는 지출 기록. 표는 storage.py 스키마(ledger_*)에 있고 같은 DB 파일을 씀

- 사람: 관리자(LEDGER_ADMIN_NAME, 관리자 암호로 로그인)와 이름·비밀번호로 가입을 요청한 사람.
  가입 요청은 관리자가 허락해야(approved) 로그인할 수 있고, 허락받은 사람은 가계부만 씀 (다른 관리 기능은 관리자 암호가 필요)
- 로그인하면 쿠키 값(무작위)을 주고 DB에는 그 sha256만 둠. 허락을 취소하면 그 사람의 로그인도 모두 끊음
- 기록은 로그인한 사람 모두가 함께 봄. 고치기·지우기는 쓴 사람과 관리자만
- 분류(지출의 소비형태·수입의 종류)는 모두가 함께 쓰고, 색은 사람이 직접 고름. 기록에 쓰인 분류는 지우지 못함.
  기록이 지출인지 수입인지는 그 분류의 kind(expense·income)로 정함
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
    """그 달의 기록(모두의 것), 소비형태, 함께 쓰는 사람, 최근 메모(소비형태와 함께)"""
    month, start, end = _month_range(month)
    with _db() as conn, conn:
        _ensure_admin(conn)
        _seed_categories(conn)
        entries = conn.execute("""SELECT id, user_id, amount, used_on, category_id, memo, created_at FROM ledger_entries
                                  WHERE used_on >= ? AND used_on < ? ORDER BY used_on DESC, id DESC""", (start, end)).fetchall()
        cats = conn.execute("SELECT id, name, color, kind FROM ledger_categories ORDER BY position, id").fetchall()
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
        raise LedgerError(f'이름은 1~{CATEGORY_NAME_MAX}자로 넣어 주세요.')
    if not isinstance(color, str) or not COLOR_RE.fullmatch(color):
        raise LedgerError('색을 골라 주세요.')
    return name, color.upper()


def add_category(name, color, kind='expense'):
    name, color = _category_values(name, color)
    if kind not in KINDS:
        raise LedgerError('지출인지 수입인지 골라 주세요.')
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM ledger_categories WHERE name = ?", (name,)).fetchone():
            raise LedgerError('이미 있는 이름이에요.')
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM ledger_categories").fetchone()[0]
        return conn.execute("INSERT INTO ledger_categories(name, color, kind, position, created_at) VALUES(?, ?, ?, ?, ?)",
                            (name, color, kind, position, _now())).lastrowid


def edit_category(category_id, name, color):
    """이름·색 바꾸기 (기록은 소비형태 번호로 이어져 있어 이름을 바꿔도 함께 바뀜)"""
    name, color = _category_values(name, color)
    with _db() as conn, conn:
        if not conn.execute("SELECT 1 FROM ledger_categories WHERE id = ?", (category_id,)).fetchone():
            raise LedgerError('없는 소비형태예요.')
        if conn.execute("SELECT 1 FROM ledger_categories WHERE name = ? AND id != ?", (name, category_id)).fetchone():
            raise LedgerError('이미 있는 이름이에요.')
        conn.execute("UPDATE ledger_categories SET name = ?, color = ? WHERE id = ?", (name, color, category_id))


def delete_category(category_id):
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM ledger_entries WHERE category_id = ?", (category_id,)).fetchone():
            raise LedgerError('기록에 쓰인 소비형태는 지울 수 없어요.')
        if not conn.execute("DELETE FROM ledger_categories WHERE id = ?", (category_id,)).rowcount:
            raise LedgerError('없는 소비형태예요.')


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
        rows = conn.execute("SELECT * FROM ledger_inbox WHERE user_id = ? ORDER BY used_on DESC, used_time DESC, id DESC", (user['id'],)).fetchall()
        history = _history_map(conn) if rows else {}
        items = []
        for r in rows:
            item = {k: r[k] for k in ('id', 'raw', 'amount', 'merchant', 'card', 'used_on', 'used_time', 'category_id', 'created_at')}
            item['cancel'] = bool(r['is_cancel'])
            if item['cancel']:
                item['match'] = _cancel_match(conn, r)
            item['suggest'] = _suggest(history, r)
            items.append(item)
    return items


def rules():
    with _db() as conn:
        return [dict(r) for r in conn.execute("SELECT id, pattern, category_id FROM ledger_rules ORDER BY pattern")]


def _own_item(conn, user, item_id):
    row = conn.execute("SELECT * FROM ledger_inbox WHERE id = ?", (item_id,)).fetchone()
    if not row or row['user_id'] != user['id']:
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
            conn.execute("DELETE FROM ledger_entries WHERE id = ?", (match['id'],))
    else:
        # 분류를 고르지 않았으면 지난 기록의 추천으로 (화면에 미리 골라 보여 준 것)
        suggest = _suggest(history if history is not None else _history_map(conn), row)
        category_id = row['category_id'] if row['category_id'] is not None else suggest and suggest['category_id']
        if category_id is None:
            raise LedgerError('분류를 골라 주세요.')
        now = _now()
        conn.execute("""INSERT INTO ledger_entries(user_id, amount, used_on, category_id, memo, created_at, updated_at)
                        VALUES(?, ?, ?, ?, ?, ?, ?)""", (row['user_id'], row['amount'], row['used_on'], category_id,
                                                        row['merchant'][:MEMO_MAX], now, now))
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
        for row in conn.execute("SELECT * FROM ledger_inbox WHERE user_id = ?", (user['id'],)).fetchall():
            if (row['is_cancel'] and _cancel_match(conn, row)) or (not row['is_cancel'] and (row['category_id'] is not None or _suggest(history, row))):
                _confirm_row(conn, row, history)
                done += 1
    return done


def discard_item(user, item_id):
    with _db() as conn, conn:
        _own_item(conn, user, item_id)
        conn.execute("DELETE FROM ledger_inbox WHERE id = ?", (item_id,))


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
