"""아파트 매매 실거래가 저장소 (/apt/ 화면, 메인 대시보드 카드, apt_trades.py의 수집).
표는 storage.py의 스키마에 함께 있고 같은 DB 파일을 씀.

- 관심 단지(apt_watches): 지역(시군구 코드 5자리) + 단지(apt_seq) + 전용면적(㎡ 반올림, 없으면 모든 면적)
- 거래(apt_trades): 관심 단지의 거래를 모든 면적으로 저장하고, 볼 때 관심 면적으로 거름. 금액은 만원 단위
"""
import json
from datetime import datetime, timedelta
from storage import _db, _now, _get_meta, _set_meta

SYNC_STATUS_META = 'apt_sync_status'
# 새로 올라온 거래로 표시하는 기간(일)
NEW_TRADE_DAYS = 3

def list_watches():
    """관심 단지 (표시 순서)"""
    with _db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM apt_watches ORDER BY position, id")]

def add_watch(lawd_cd, apt_seq, apt_name, umd_name, area=None):
    """관심 단지 등록 (맨 뒤에). 관심 단지 ID 반환, 같은 단지·면적이 이미 있으면 ValueError"""
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM apt_watches WHERE lawd_cd = ? AND apt_seq = ? AND area IS ?",
                        (lawd_cd, apt_seq, area)).fetchone():
            raise ValueError('이미 등록한 단지·면적입니다.')
        position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM apt_watches").fetchone()[0]
        return conn.execute("""
            INSERT INTO apt_watches(lawd_cd, apt_seq, apt_name, umd_name, area, alert, position, created_at)
            VALUES(?, ?, ?, ?, ?, 1, ?, ?)
        """, (lawd_cd, apt_seq, apt_name, umd_name, area, position, _now())).lastrowid

def delete_watch(watch_id):
    """관심 단지 삭제. 그 단지를 보는 관심 단지가 더 없으면 모아 둔 거래도 지움. 없는 ID면 False"""
    with _db() as conn, conn:
        row = conn.execute("SELECT lawd_cd, apt_seq FROM apt_watches WHERE id = ?", (watch_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM apt_watches WHERE id = ?", (watch_id,))
        if not conn.execute("SELECT 1 FROM apt_watches WHERE lawd_cd = ? AND apt_seq = ?", tuple(row)).fetchone():
            conn.execute("DELETE FROM apt_trades WHERE lawd_cd = ? AND apt_seq = ?", tuple(row))
        return True

def set_watch_alert(watch_id, enabled):
    with _db() as conn, conn:
        return conn.execute("UPDATE apt_watches SET alert = ? WHERE id = ?", (int(bool(enabled)), watch_id)).rowcount > 0

def mark_watches_synced(watch_ids):
    with _db() as conn, conn:
        conn.executemany("UPDATE apt_watches SET synced_at = ? WHERE id = ?", [(_now(), i) for i in watch_ids])

def save_trades(trades, backfill):
    """거래 저장. 새로 저장한 거래 목록을 돌려줌 (이미 있는 거래는 취소 여부만 갱신).
    backfill이면 처음 채우는 지난 거래라 '새 거래' 표시·알림 대상이 아님"""
    added = []
    now = _now()
    with _db() as conn, conn:
        for t in trades:
            key = (t['lawd_cd'], t['apt_seq'], t['area'], t['floor'], t['deal_date'], t['amount'])
            row = conn.execute("""
                SELECT id, canceled FROM apt_trades
                WHERE lawd_cd = ? AND apt_seq = ? AND area = ? AND floor = ? AND deal_date = ? AND amount = ?
            """, key).fetchone()
            if row:
                if row['canceled'] != int(t['canceled']):
                    conn.execute("UPDATE apt_trades SET canceled = ?, cancel_date = ? WHERE id = ?",
                                 (int(t['canceled']), t.get('cancel_date') or None, row['id']))
                continue
            conn.execute("""
                INSERT INTO apt_trades(lawd_cd, apt_seq, apt_name, umd_name, area, floor, amount, deal_date, build_year,
                                       canceled, cancel_date, dealing, backfill, first_seen_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, key[:2] + (t['apt_name'], t['umd_name']) + key[2:4] + (t['amount'], t['deal_date'], t.get('build_year'),
                            int(t['canceled']), t.get('cancel_date') or None, t.get('dealing') or '', int(backfill), now))
            added.append(t)
    return added

def _watch_trades(conn, watch, limit=None):
    """관심 단지의 거래 (관심 면적만, 최근 계약 순)"""
    sql = "SELECT * FROM apt_trades WHERE lawd_cd = ? AND apt_seq = ?"
    params = [watch['lawd_cd'], watch['apt_seq']]
    if watch['area'] is not None:
        sql += " AND CAST(ROUND(area) AS INTEGER) = ?"
        params.append(watch['area'])
    sql += " ORDER BY deal_date DESC, id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in conn.execute(sql, params)]

def _is_new(trade):
    cutoff = (datetime.now() - timedelta(days=NEW_TRADE_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    return not trade['backfill'] and not trade['canceled'] and trade['first_seen_at'] >= cutoff

def _public_trade(t):
    return {'date': t['deal_date'], 'area': t['area'], 'floor': t['floor'], 'amount': t['amount'], 'canceled': bool(t['canceled']),
            'dealing': t['dealing'], 'is_new': _is_new(t)}

def previous_trade(lawd_cd, apt_seq, area, before_date, exclude_amount_floor=None):
    """같은 단지·같은 면적(㎡ 반올림)의 직전 거래 (취소된 거래 제외). 새 거래 알림의 '직전 대비'용"""
    with _db() as conn:
        row = conn.execute("""
            SELECT * FROM apt_trades WHERE lawd_cd = ? AND apt_seq = ? AND CAST(ROUND(area) AS INTEGER) = ?
              AND canceled = 0 AND deal_date < ? ORDER BY deal_date DESC, id DESC LIMIT 1
        """, (lawd_cd, apt_seq, int(round(area)), before_date)).fetchone()
    return dict(row) if row else None

def watch_summaries(spark_months=12):
    """대시보드 카드·목록 화면: 관심 단지마다 최근 거래, 직전 거래 대비 차이, 최고가와 그 대비 비율,
    최근 spark_months개월의 월 평균가 추이, 새 거래 여부"""
    since = (datetime.now() - timedelta(days=31 * spark_months)).strftime('%Y-%m-01')
    result = []
    with _db() as conn:
        for w in conn.execute("SELECT * FROM apt_watches ORDER BY position, id").fetchall():
            w = dict(w)
            trades = [t for t in _watch_trades(conn, w) if not t['canceled']]
            latest = trades[0] if trades else None
            prev = trades[1] if len(trades) > 1 else None
            peak = max((t['amount'] for t in trades), default=None)
            months = {}
            for t in trades:
                if t['deal_date'] >= since:
                    months.setdefault(t['deal_date'][:7], []).append(t['amount'])
            result.append({
                'id': w['id'], 'lawd_cd': w['lawd_cd'], 'apt_seq': w['apt_seq'], 'name': w['apt_name'], 'umd': w['umd_name'],
                'area': w['area'], 'alert': bool(w['alert']), 'synced': bool(w['synced_at']), 'trade_count': len(trades),
                'latest': _public_trade(latest) if latest else None,
                'diff': latest['amount'] - prev['amount'] if latest and prev else None,
                'peak': peak,
                'peak_ratio': round((latest['amount'] - peak) / peak * 100, 1) if latest and peak else None,
                'spark': [{'month': m, 'amount': round(sum(v) / len(v))} for m, v in sorted(months.items())],
            })
    return result

def watch_detail(watch_id):
    """상세 화면: 관심 단지와 그 단지의 모든 거래(모든 면적, 최근 계약 순), 면적별 거래 수"""
    with _db() as conn:
        w = conn.execute("SELECT * FROM apt_watches WHERE id = ?", (watch_id,)).fetchone()
        if not w:
            return None
        w = dict(w)
        trades = _watch_trades(conn, {**w, 'area': None})
    areas = {}
    for t in trades:
        areas[int(round(t['area']))] = areas.get(int(round(t['area'])), 0) + 1
    build_year = next((t['build_year'] for t in trades if t['build_year']), None)
    return {'id': w['id'], 'name': w['apt_name'], 'umd': w['umd_name'], 'lawd_cd': w['lawd_cd'], 'area': w['area'],
            'alert': bool(w['alert']), 'synced': bool(w['synced_at']), 'build_year': build_year,
            'areas': [{'area': a, 'count': c} for a, c in sorted(areas.items())],
            'trades': [_public_trade(t) for t in trades]}

def sync_status():
    """마지막 수집 상태 {'at', 'ok', 'message'} (한 번도 안 했으면 None)"""
    with _db() as conn:
        raw = _get_meta(conn, SYNC_STATUS_META)
    return json.loads(raw) if raw else None

def set_sync_status(ok, message=''):
    with _db() as conn, conn:
        _set_meta(conn, SYNC_STATUS_META, json.dumps({'at': _now(), 'ok': bool(ok), 'message': message}, ensure_ascii=False))
