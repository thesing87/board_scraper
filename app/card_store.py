"""카드 혜택 한도 저장소 (/card/ 화면, 결제 메일 자동 차감). 표는 storage.py의 스키마에 함께 있고 같은 DB 파일을 씀"""
import json
from storage import _db, _now, _get_meta, _set_meta

def seed_card_keywords(conn):
    """차감할 가게 기본값을 1회만 넣음 (이후 사용자가 지운 가게가 되살아나지 않게)"""
    if _get_meta(conn, 'card_keywords_seeded'):
        return
    conn.executemany("INSERT OR IGNORE INTO card_keywords(keyword) VALUES(?)", [('스타벅스',), ('투썸플레이스',)])
    _set_meta(conn, 'card_keywords_seeded', 1)

def _card_keyword_hit(place, keywords):
    place = place.casefold()
    return any(k.casefold() in place for k in keywords)

def card_benefits(month, recent_limit=8):
    """그 달('YYYY-MM')의 차감 내역(최근 날짜·최근 등록 순), 메일로 찾았지만 차감하지 않은 결제, 차감할 가게, 메일 확인 상태와,
    달에 상관없이 직접 입력에서 최근에 쓴 사용처·금액 조합(최근 순, 중복 없이)"""
    start, end = f'{month}-01', f'{month}-99'
    with _db() as conn:
        items = conn.execute("""
            SELECT b.id, b.used_on, b.place, b.amount, m.approval_no IS NOT NULL AS from_mail
            FROM card_benefits b LEFT JOIN card_mail_payments m ON m.benefit_id = b.id
            WHERE b.used_on >= ? AND b.used_on < ? ORDER BY b.used_on DESC, b.id DESC
        """, (start, end)).fetchall()
        recent = conn.execute("""
            SELECT place, amount, MAX(id) AS last_id FROM card_benefits b
            WHERE NOT EXISTS (SELECT 1 FROM card_mail_payments m WHERE m.benefit_id = b.id)
            GROUP BY place, amount ORDER BY last_id DESC LIMIT ?
        """, (recent_limit,)).fetchall()
        others = conn.execute("""
            SELECT approval_no, paid_at, place, amount FROM card_mail_payments
            WHERE benefit_id IS NULL AND paid_at >= ? AND paid_at < ? ORDER BY paid_at DESC
        """, (start, end)).fetchall()
        keywords = conn.execute("SELECT keyword FROM card_keywords ORDER BY keyword").fetchall()
        status = _get_meta(conn, 'card_mail_status')
    return {'items': [{**dict(r), 'from_mail': bool(r['from_mail'])} for r in items],
            'recent': [{'place': r['place'], 'amount': r['amount']} for r in recent],
            'others': [dict(r) for r in others],
            'keywords': [r['keyword'] for r in keywords],
            'mail': json.loads(status) if status else {'state': 'off'}}

def _apply_card_payment(conn, approval_no, paid_at, place, amount):
    benefit_id = conn.execute("INSERT INTO card_benefits(used_on, place, amount, created_at) VALUES(?, ?, ?, ?)",
                              (paid_at[:10], place, amount, _now())).lastrowid
    conn.execute("UPDATE card_mail_payments SET benefit_id = ? WHERE approval_no = ?", (benefit_id, approval_no))

def record_card_payment(approval_no, paid_at, place, amount):
    """메일에서 읽은 결제를 저장. 차감할 가게면 한도에서 차감. 'duplicate'(이미 본 결제)·'matched'·'other'"""
    with _db() as conn, conn:
        added = conn.execute("""
            INSERT OR IGNORE INTO card_mail_payments(approval_no, paid_at, place, amount) VALUES(?, ?, ?, ?)
        """, (approval_no, paid_at, place, amount)).rowcount
        if not added:
            return 'duplicate'
        keywords = [r['keyword'] for r in conn.execute("SELECT keyword FROM card_keywords")]
        if not _card_keyword_hit(place, keywords):
            return 'other'
        _apply_card_payment(conn, approval_no, paid_at, place, amount)
        return 'matched'

def add_card_keyword(keyword):
    """차감할 가게 추가. 이미 메일로 찾아 둔 차감 전 결제 중 이 가게의 것도 함께 차감하고, 그 건수를 돌려줌"""
    with _db() as conn, conn:
        conn.execute("INSERT OR IGNORE INTO card_keywords(keyword) VALUES(?)", (keyword,))
        rows = conn.execute("SELECT approval_no, paid_at, place, amount FROM card_mail_payments WHERE benefit_id IS NULL").fetchall()
        hits = [r for r in rows if _card_keyword_hit(r['place'], [keyword])]
        for r in hits:
            _apply_card_payment(conn, r['approval_no'], r['paid_at'], r['place'], r['amount'])
    return len(hits)

def delete_card_keyword(keyword):
    """차감할 가게 삭제. 이미 차감한 내역은 그대로 두고 앞으로 오는 결제에만 적용. 없는 가게면 False"""
    with _db() as conn, conn:
        return conn.execute("DELETE FROM card_keywords WHERE keyword = ?", (keyword,)).rowcount > 0

def card_mail_position():
    """메일함에서 마지막으로 처리한 위치 (UIDVALIDITY, UID). 없으면 (None, None)"""
    with _db() as conn:
        validity, uid = _get_meta(conn, 'card_mail_uidvalidity'), _get_meta(conn, 'card_mail_uid')
    return (int(validity), int(uid)) if validity is not None and uid is not None else (None, None)

def set_card_mail_position(validity, uid):
    with _db() as conn, conn:
        _set_meta(conn, 'card_mail_uidvalidity', validity)
        _set_meta(conn, 'card_mail_uid', uid)

def set_card_mail_status(state, mode='', message=''):
    """카드 페이지에 보여 줄 메일 확인 상태 (state: off·ok·error)"""
    with _db() as conn, conn:
        _set_meta(conn, 'card_mail_status', json.dumps({'state': state, 'mode': mode, 'message': message, 'checked_at': _now()}, ensure_ascii=False))

def add_card_benefit(used_on, place, amount):
    with _db() as conn, conn:
        return conn.execute("INSERT INTO card_benefits(used_on, place, amount, created_at) VALUES(?, ?, ?, ?)",
                            (used_on, place, amount, _now())).lastrowid

def update_card_benefit(benefit_id, used_on, amount):
    """날짜·금액 수정. 없는 항목이면 False"""
    with _db() as conn, conn:
        return conn.execute("UPDATE card_benefits SET used_on = ?, amount = ? WHERE id = ?",
                            (used_on, amount, benefit_id)).rowcount > 0

def delete_card_benefit(benefit_id):
    """삭제. 없는 항목이면 False"""
    with _db() as conn, conn:
        return conn.execute("DELETE FROM card_benefits WHERE id = ?", (benefit_id,)).rowcount > 0
