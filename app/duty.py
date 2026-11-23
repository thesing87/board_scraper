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


def delete_type(type_id):
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM duty_days WHERE type_id = ?", (type_id,)).fetchone():
            raise DutyError('근무표에 들어간 종류는 지울 수 없어요. 그 날들을 먼저 바꿔 주세요.')
        if not conn.execute("DELETE FROM duty_types WHERE id = ?", (type_id,)).rowcount:
            raise DutyError('없는 근무 종류예요.')
