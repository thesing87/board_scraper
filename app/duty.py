"""근무표 (/duty/): 간호사 근무표처럼 날짜마다 근무(데이·이브닝·나이트·휴무 등)를 넣고 함께 보기.
표는 storage.py 스키마(duty_*)에 있고 같은 DB 파일을 씀

- 로그인은 가계부 계정 그대로 (ledger.py, 쿠키도 /api/ledger/ 아래라 API는 /api/ledger/duty)
- 허락받은 멤버는 모두 똑같이 고칠 수 있음: 근무 넣기·지우기, 사람(근무표 주인) 추가·이름 바꾸기·지우기, 근무 종류 바꾸기
- 근무표는 사람마다 하나, 근무 종류는 모두 함께 씀. 누가 무엇을 바꿨는지는 duty_changes에 남김 (최근 것만 보여 줌)
"""
import re
from datetime import date, timedelta

from storage import _db, _now, _get_meta, _set_meta

PERSON_NAME_MAX = 20
TYPE_CODE_MAX = 4
TYPE_NAME_MAX = 10
SET_MAX_DAYS = 62          # 한 번에 바꿀 수 있는 날 수 (한 달 넘게 한꺼번에 칠할 일은 없음)
NEAR_DAYS = 4              # 오늘·내일·모레·글피 (위쪽 카드·위젯)
CHANGES_SHOWN = 8
CHANGES_KEEP_DAYS = 90
COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MONTH_RE = re.compile(r'^\d{4}-\d{2}$')
TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
# 처음 한 번 넣는 근무 종류 (이름·시간·색은 나중에 바꿀 수 있음)
DEFAULT_TYPES = [('D', '데이', '07:00', '15:00', '#EF9F27'), ('E', '이브닝', '15:00', '23:00', '#D4537E'),
                 ('N', '나이트', '23:00', '07:00', '#534AB7'), ('OFF', '휴무', '', '', '#888780'),
                 ('연차', '연차', '', '', '#1D9E75')]


class DutyError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 거절 이유"""


def _seed(conn):
    if not _get_meta(conn, 'duty_types_seeded'):
        now = _now()
        conn.executemany("""INSERT OR IGNORE INTO duty_types(code, name, start_time, end_time, color, position, created_at)
                            VALUES(?, ?, ?, ?, ?, ?, ?)""", [(*t, i, now) for i, t in enumerate(DEFAULT_TYPES)])
        _set_meta(conn, 'duty_types_seeded', 1)


def _valid_day(day):
    if not isinstance(day, str) or not DATE_RE.fullmatch(day):
        return False
    try:
        date.fromisoformat(day)
    except ValueError:
        return False
    return True


# ==========================================
# 보기
# ==========================================
def state(month, person_id=None, today=None):
    """사람들, 근무 종류, 고른 사람의 그 달 근무({날짜: 종류 id}), 오늘부터 며칠(near), 최근 바뀐 것"""
    if not MONTH_RE.fullmatch(month or ''):
        month = date.today().strftime('%Y-%m')
    today = today or date.today()
    with _db() as conn, conn:
        _seed(conn)
        people = [dict(r) for r in conn.execute("SELECT id, name FROM duty_people ORDER BY position, id")]
        types = [dict(r) for r in conn.execute(
            "SELECT id, code, name, start_time, end_time, color FROM duty_types ORDER BY position, id")]
        ids = [p['id'] for p in people]
        pid = person_id if person_id in ids else (ids[0] if ids else None)
        days, near, changes = {}, {}, []
        if pid:
            days = {r['day']: r['type_id'] for r in conn.execute(
                "SELECT day, type_id FROM duty_days WHERE person_id = ? AND day >= ? AND day < ?", (pid, f'{month}-01', f'{month}-99'))}
            last = (today + timedelta(days=NEAR_DAYS - 1)).isoformat()
            near = {r['day']: r['type_id'] for r in conn.execute(
                "SELECT day, type_id FROM duty_days WHERE person_id = ? AND day >= ? AND day <= ?", (pid, today.isoformat(), last))}
            changes = [dict(r) for r in conn.execute(
                """SELECT c.day, c.type_id, c.changed_at, COALESCE(u.name, '') AS who FROM duty_changes c
                   LEFT JOIN ledger_users u ON u.id = c.user_id WHERE c.person_id = ? ORDER BY c.id DESC LIMIT ?""",
                (pid, CHANGES_SHOWN))]
    return {'month': month, 'today': today.isoformat(), 'people': people, 'types': types,
            'person_id': pid, 'days': days, 'near': near, 'changes': changes}


def summary(person_id=None, today=None):
    """앱 홈 탭: 사람마다 오늘·내일 근무, 고른 사람(없으면 첫 사람)의 이번 주 7일(오늘부터), 근무 종류"""
    today = today or date.today()
    tomorrow, last = today + timedelta(days=1), today + timedelta(days=6)
    with _db() as conn, conn:
        _seed(conn)
        people = [dict(r) for r in conn.execute("SELECT id, name FROM duty_people ORDER BY position, id")]
        types = [dict(r) for r in conn.execute(
            "SELECT id, code, name, start_time, end_time, color FROM duty_types ORDER BY position, id")]
        rows = conn.execute("SELECT person_id, day, type_id FROM duty_days WHERE day >= ? AND day <= ?",
                            (today.isoformat(), last.isoformat())).fetchall()
    days = {}
    for r in rows:
        days.setdefault(r['person_id'], {})[r['day']] = r['type_id']
    for p in people:
        mine = days.get(p['id'], {})
        p['today'], p['tomorrow'] = mine.get(today.isoformat()), mine.get(tomorrow.isoformat())
    ids = [p['id'] for p in people]
    pid = person_id if person_id in ids else (ids[0] if ids else None)
    week = [{'day': (today + timedelta(days=i)).isoformat(), 'type_id': days.get(pid, {}).get((today + timedelta(days=i)).isoformat())}
            for i in range(7)] if pid else []
    return {'today': today.isoformat(), 'people': people, 'types': types, 'person_id': pid, 'week': week}


# ==========================================
# 근무 넣기·지우기
# ==========================================
def set_days(user, person_id, days):
    """days: {날짜: 종류 id 또는 None(지움)}. 바뀐 날 수를 돌려줌"""
    if not isinstance(days, dict) or not days:
        raise DutyError('바꿀 날짜가 없어요.')
    if len(days) > SET_MAX_DAYS:
        raise DutyError(f'한 번에 {SET_MAX_DAYS}일까지만 바꿀 수 있어요.')
    if not all(_valid_day(d) for d in days):
        raise DutyError('날짜가 올바르지 않아요.')
    now = _now()
    changed = 0
    with _db() as conn, conn:
        if not conn.execute("SELECT 1 FROM duty_people WHERE id = ?", (person_id,)).fetchone():
            raise DutyError('없는 사람이에요.')
        type_ids = {r['id'] for r in conn.execute("SELECT id FROM duty_types")}
        for day, tid in days.items():
            if tid is not None and (type(tid) is not int or tid not in type_ids):
                raise DutyError('없는 근무 종류예요.')
        for day, tid in sorted(days.items()):
            old = conn.execute("SELECT type_id FROM duty_days WHERE person_id = ? AND day = ?", (person_id, day)).fetchone()
            if (old['type_id'] if old else None) == tid:
                continue
            if tid is None:
                conn.execute("DELETE FROM duty_days WHERE person_id = ? AND day = ?", (person_id, day))
            else:
                conn.execute("""INSERT INTO duty_days(person_id, day, type_id, updated_by, updated_at) VALUES(?, ?, ?, ?, ?)
                                ON CONFLICT(person_id, day) DO UPDATE SET type_id = excluded.type_id,
                                updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
                             (person_id, day, tid, user['id'], now))
            conn.execute("INSERT INTO duty_changes(person_id, day, type_id, user_id, changed_at) VALUES(?, ?, ?, ?, ?)",
                         (person_id, day, tid, user['id'], now))
            changed += 1
        old_limit = (date.today() - timedelta(days=CHANGES_KEEP_DAYS)).isoformat()
        conn.execute("DELETE FROM duty_changes WHERE changed_at < ?", (old_limit,))
    return changed


# ==========================================
# 사람 (근무표 주인)
# ==========================================
def _person_name(name):
    name = ' '.join(str(name or '').split())
    if not name or len(name) > PERSON_NAME_MAX:
        raise DutyError(f'이름은 1~{PERSON_NAME_MAX}자로 넣어 주세요.')
    return name


def add_person(name):
    name = _person_name(name)
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM duty_people WHERE name = ?", (name,)).fetchone():
            raise DutyError('이미 있는 이름이에요.')
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM duty_people").fetchone()[0]
        return conn.execute("INSERT INTO duty_people(name, position, created_at) VALUES(?, ?, ?)",
                            (name, position, _now())).lastrowid


def rename_person(person_id, name):
    name = _person_name(name)
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM duty_people WHERE name = ? AND id != ?", (name, person_id)).fetchone():
            raise DutyError('이미 있는 이름이에요.')
        if not conn.execute("UPDATE duty_people SET name = ? WHERE id = ?", (name, person_id)).rowcount:
            raise DutyError('없는 사람이에요.')


def delete_person(person_id):
    """그 사람의 근무표(넣은 근무·바뀐 기록)도 함께 지움"""
    with _db() as conn, conn:
        if not conn.execute("DELETE FROM duty_people WHERE id = ?", (person_id,)).rowcount:
            raise DutyError('없는 사람이에요.')


# ==========================================
# 근무 종류 (모두 함께 씀)
# ==========================================
def _type_values(code, name, start_time, end_time, color):
    code = ''.join(str(code or '').split())
    if not code or len(code) > TYPE_CODE_MAX:
        raise DutyError(f'짧은 글자는 1~{TYPE_CODE_MAX}자로 넣어 주세요. (예: D, OFF)')
    name = ' '.join(str(name or '').split()) or code
    if len(name) > TYPE_NAME_MAX:
        raise DutyError(f'이름은 {TYPE_NAME_MAX}자까지 넣을 수 있어요.')
    start_time, end_time = str(start_time or ''), str(end_time or '')
    if any(t and not TIME_RE.fullmatch(t) for t in (start_time, end_time)):
        raise DutyError('시간은 07:00처럼 넣어 주세요.')
    if bool(start_time) != bool(end_time):
        raise DutyError('시작과 끝 시간을 둘 다 넣거나 둘 다 비워 주세요.')
    if not isinstance(color, str) or not COLOR_RE.fullmatch(color):
        raise DutyError('색을 골라 주세요.')
    return code, name, start_time, end_time, color.upper()


def add_type(code, name, start_time, end_time, color):
    values = _type_values(code, name, start_time, end_time, color)
    with _db() as conn, conn:
        _seed(conn)
        if conn.execute("SELECT 1 FROM duty_types WHERE code = ?", (values[0],)).fetchone():
            raise DutyError('이미 있는 글자예요.')
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM duty_types").fetchone()[0]
        return conn.execute("""INSERT INTO duty_types(code, name, start_time, end_time, color, position, created_at)
                               VALUES(?, ?, ?, ?, ?, ?, ?)""", (*values, position, _now())).lastrowid


def edit_type(type_id, code, name, start_time, end_time, color):
    values = _type_values(code, name, start_time, end_time, color)
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM duty_types WHERE code = ? AND id != ?", (values[0], type_id)).fetchone():
            raise DutyError('이미 있는 글자예요.')
        if not conn.execute("UPDATE duty_types SET code = ?, name = ?, start_time = ?, end_time = ?, color = ? WHERE id = ?",
                            (*values, type_id)).rowcount:
            raise DutyError('없는 근무 종류예요.')


class TypeRowError(DutyError):
    """한 번에 저장할 때 잘못된 줄 (row: 보낸 목록의 몇 번째, 0부터)"""
    def __init__(self, row, message):
        super().__init__(message)
        self.row = row


def save_types(items):
    """근무 종류를 한 번에 저장: items = [{id(있으면 고치기, 없으면 더하기), code, name, start_time, end_time, color}, ...].
    모두 확인한 뒤에만 바꿈 (한 줄이라도 잘못되면 아무것도 안 바꾸고 그 줄을 알려 줌). 여기 없는 종류는 그대로"""
    if not isinstance(items, list) or not items or len(items) > 50:
        raise DutyError('저장할 근무 종류가 없어요.')
    rows = []
    for i, it in enumerate(items):
        if not isinstance(it, dict) or ('id' in it and it['id'] is not None and type(it['id']) is not int):
            raise TypeRowError(i, '잘못된 요청이에요.')
        try:
            rows.append((it.get('id'), _type_values(it.get('code'), it.get('name'), it.get('start_time'), it.get('end_time'), it.get('color'))))
        except DutyError as e:
            raise TypeRowError(i, str(e))
    with _db() as conn, conn:
        _seed(conn)
        known = {r['id']: r['code'] for r in conn.execute("SELECT id, code FROM duty_types")}
        ids = [tid for tid, _ in rows if tid is not None]
        for i, (tid, _) in enumerate(rows):
            if tid is not None and (tid not in known or ids.count(tid) > 1):
                raise TypeRowError(i, '없는 근무 종류예요.')
        # 글자는 겹치면 안 됨 (여기서 고치지 않는 종류의 글자와도)
        taken = {code: tid for tid, code in known.items() if tid not in ids}
        for i, (tid, v) in enumerate(rows):
            if v[0] in taken:
                raise TypeRowError(i, f"'{v[0]}' 글자가 겹쳐요.")
            taken[v[0]] = tid
        # 글자를 서로 맞바꿔도 되게 고칠 줄의 글자를 잠깐 비켜 둔 뒤 저장
        for tid in ids:
            conn.execute("UPDATE duty_types SET code = ? WHERE id = ?", (f'~tmp{tid}~', tid))
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM duty_types").fetchone()[0]
        for tid, v in rows:
            if tid is None:
                conn.execute("""INSERT INTO duty_types(code, name, start_time, end_time, color, position, created_at)
                                VALUES(?, ?, ?, ?, ?, ?, ?)""", (*v, position, _now()))
                position += 1
            else:
                conn.execute("UPDATE duty_types SET code = ?, name = ?, start_time = ?, end_time = ?, color = ? WHERE id = ?", (*v, tid))


def delete_type(type_id):
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM duty_days WHERE type_id = ?", (type_id,)).fetchone():
            raise DutyError('근무표에 들어간 종류는 지울 수 없어요. 그 날들을 먼저 바꿔 주세요.')
        if not conn.execute("DELETE FROM duty_types WHERE id = ?", (type_id,)).rowcount:
            raise DutyError('없는 근무 종류예요.')
