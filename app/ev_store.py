"""유지비 계산기(/ev/)의 저장한 조건. 표(ev_presets)는 storage.py의 스키마에 함께 있고 같은 DB 파일을 씀"""
import json
from storage import _db, _now

def ev_presets():
    """저장한 조건 (최근 저장 순)"""
    with _db() as conn:
        rows = conn.execute("SELECT id, name, values_json, created_at FROM ev_presets ORDER BY id DESC").fetchall()
    return [{'id': r['id'], 'name': r['name'], 'values': json.loads(r['values_json']), 'created_at': r['created_at']} for r in rows]

def add_ev_preset(name, values, max_count):
    """저장. 이미 max_count개면 None"""
    with _db() as conn, conn:
        if conn.execute("SELECT COUNT(*) FROM ev_presets").fetchone()[0] >= max_count:
            return None
        return conn.execute("INSERT INTO ev_presets(name, values_json, created_at) VALUES(?, ?, ?)",
                            (name, json.dumps(values), _now())).lastrowid

def delete_ev_preset(preset_id):
    """삭제. 없는 항목이면 False"""
    with _db() as conn, conn:
        return conn.execute("DELETE FROM ev_presets WHERE id = ?", (preset_id,)).rowcount > 0
