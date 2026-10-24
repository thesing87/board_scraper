import os
import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from config import (
    log_msg,
    DB_FILE,
    KEYWORDS_FILE,
    BOARD_CONFIG_FILE,
    JSON_BACKUP_FILE,
    BOARD_MAP
)

DEFAULT_BOARD_ALERT = {"alert": True, "video_alert": True}
SCHEMA_VERSION = 1

_init_lock = threading.Lock()
_initialized = False

# ==========================================
# SQLite 연결 및 스키마
# ==========================================
def _connect():
    """스레드마다 독립된 연결을 쓰도록 호출 시점마다 새 연결을 생성"""
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def _create_schema(conn):
    conn.executescript("""
        PRAGMA journal_mode = WAL;

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS posts (
            id             TEXT PRIMARY KEY,
            title          TEXT NOT NULL DEFAULT '',
            author         TEXT NOT NULL DEFAULT '',
            date           TEXT NOT NULL DEFAULT '',
            views          TEXT NOT NULL DEFAULT '0',
            votes          TEXT NOT NULL DEFAULT '0',
            comment_count  TEXT NOT NULL DEFAULT '0',
            link           TEXT NOT NULL DEFAULT '',
            content_json   TEXT NOT NULL DEFAULT '[]',
            videos_json    TEXT NOT NULL DEFAULT '[]',
            comments_json  TEXT NOT NULL DEFAULT '[]',
            is_deleted     INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS keywords (
            board    TEXT NOT NULL,
            keyword  TEXT NOT NULL,
            PRIMARY KEY (board, keyword)
        );

        -- 키워드와 글의 다대다 연결. rowid 순서가 곧 수집 순서(최신이 가장 큼)
        CREATE TABLE IF NOT EXISTS keyword_posts (
            board       TEXT NOT NULL,
            keyword     TEXT NOT NULL,
            post_id     TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            is_new      INTEGER NOT NULL DEFAULT 0,
            matched_at  TEXT NOT NULL,
            UNIQUE (board, keyword, post_id)
        );
        CREATE INDEX IF NOT EXISTS idx_keyword_posts_post ON keyword_posts(post_id);

        CREATE TABLE IF NOT EXISTS board_config (
            board        TEXT PRIMARY KEY,
            alert        INTEGER NOT NULL DEFAULT 1,
            video_alert  INTEGER NOT NULL DEFAULT 1
        );
    """)

def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _get_meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row['value'] if row else None

def _set_meta(conn, key, value):
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

def _read_legacy_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log_msg(f"[DB] 기존 JSON 읽기 실패로 이전 건너뜀: {os.path.basename(path)} ({e})", "ERROR")
        return None

def _mark_legacy_migrated(path):
    """이전이 끝난 JSON 파일은 지우지 않고 이름만 바꿔 백업으로 보존"""
    if os.path.exists(path):
        try:
            os.replace(path, f"{path}.migrated")
        except OSError as e:
            log_msg(f"[DB] 이전 완료 파일 이름 변경 실패: {os.path.basename(path)} ({e})", "WARN")

def _migrate_legacy_files(conn):
    """기존 JSON 저장 방식(keywords_config / board_config / board_data_backup)의 데이터를 DB로 1회 이전"""
    from sanitize import sanitize_lines

    keywords_data = _read_legacy_json(KEYWORDS_FILE)
    if keywords_data is None:
        log_msg("[DB] 기존 키워드 파일 없음 → 환경변수로 초기 키워드 구성")
        keywords_data = {}
        for board in BOARD_MAP.keys():
            env_str = os.environ.get(f'KEYWORDS_{board.upper()}', '')
            if board == 'car' and not env_str:
                env_str = os.environ.get('KEYWORDS', '')
            keywords_data[board] = [k.strip() for k in env_str.split(',') if k.strip()]
    for board, keywords in keywords_data.items():
        for keyword in keywords:
            conn.execute("INSERT OR IGNORE INTO keywords(board, keyword) VALUES(?, ?)", (board, keyword))

    board_cfg = _read_legacy_json(BOARD_CONFIG_FILE) or {}
    for board, cfg in board_cfg.items():
        conn.execute(
            "INSERT OR REPLACE INTO board_config(board, alert, video_alert) VALUES(?, ?, ?)",
            (board, int(cfg.get('alert', True)), int(cfg.get('video_alert', True)))
        )

    backup = _read_legacy_json(JSON_BACKUP_FILE) or {}
    post_count = 0
    for combined_key, posts in backup.items():
        if '::' not in combined_key:
            continue
        board, keyword = combined_key.split('::', 1)
        # 목록은 최신순이므로 오래된 글부터 넣어야 rowid 순서가 수집 순서와 일치
        for post in reversed(posts):
            if not post.get('id'):
                continue
            post['content'] = sanitize_lines(post.get('content', []))
            for comment in post.get('comments', []):
                comment['content'] = sanitize_lines(comment.get('content', []))
            _upsert_post(conn, post)
            if post.get('is_deleted'):
                conn.execute("UPDATE posts SET is_deleted = 1 WHERE id = ?", (str(post['id']),))
            _link_keyword_post(conn, board, keyword, post['id'], post.get('is_new', False))
            post_count += 1

    # 이미 삭제된 키워드의 잔여 백업 데이터는 이전하지 않음
    conn.execute("DELETE FROM keyword_posts WHERE (board, keyword) NOT IN (SELECT board, keyword FROM keywords)")
    conn.execute("DELETE FROM posts WHERE id NOT IN (SELECT post_id FROM keyword_posts)")

    log_msg(f"[DB] 기존 JSON 데이터 이전 완료: 키워드 {sum(len(v) for v in keywords_data.values())}개, 글 연결 {post_count}건")
    return [KEYWORDS_FILE, BOARD_CONFIG_FILE, JSON_BACKUP_FILE]

def init_db():
    """스키마 생성 및 최초 1회 기존 데이터 이전. 여러 번 호출해도 안전"""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        migrated_files = []
        with closing(_connect()) as conn:
            _create_schema(conn)
            with conn:
                if _get_meta(conn, 'schema_version') is None:
                    log_msg(f"[DB] 새 DB 생성: {DB_FILE}")
                    migrated_files = _migrate_legacy_files(conn)
                    _set_meta(conn, 'schema_version', SCHEMA_VERSION)
                for board in BOARD_MAP.keys():
                    conn.execute("INSERT OR IGNORE INTO board_config(board) VALUES(?)", (board,))
        # 커밋이 끝난 뒤에만 기존 파일을 정리하여, 이전 도중 실패하면 다음 기동 시 다시 시도
        for path in migrated_files:
            _mark_legacy_migrated(path)
        _initialized = True

def _db():
    init_db()
    return closing(_connect())

# ==========================================
# 키워드
# ==========================================
def load_keywords():
    """{board: [keyword, ...]} 형태로 등록 순서대로 반환"""
    result = {board: [] for board in BOARD_MAP.keys()}
    with _db() as conn:
        for row in conn.execute("SELECT board, keyword FROM keywords ORDER BY rowid"):
            result.setdefault(row['board'], []).append(row['keyword'])
    return result

def add_keyword(board, keyword):
    """추가되면 True, 이미 있으면 False"""
    with _db() as conn, conn:
        cur = conn.execute("INSERT OR IGNORE INTO keywords(board, keyword) VALUES(?, ?)", (board, keyword))
        return cur.rowcount > 0

def remove_keyword(board, keyword):
    """키워드와 그 수집 데이터 연결을 삭제하고, 어느 키워드에도 속하지 않게 된 글을 정리. 삭제되면 True"""
    with _db() as conn, conn:
        cur = conn.execute("DELETE FROM keywords WHERE board = ? AND keyword = ?", (board, keyword))
        if cur.rowcount == 0:
            return False
        conn.execute("DELETE FROM keyword_posts WHERE board = ? AND keyword = ?", (board, keyword))
        conn.execute("DELETE FROM posts WHERE id NOT IN (SELECT post_id FROM keyword_posts)")
        return True

# ==========================================
# 게시판 알림 설정
# ==========================================
def load_board_config():
    config = {board: dict(DEFAULT_BOARD_ALERT) for board in BOARD_MAP.keys()}
    with _db() as conn:
        for row in conn.execute("SELECT board, alert, video_alert FROM board_config"):
            config[row['board']] = {"alert": bool(row['alert']), "video_alert": bool(row['video_alert'])}
    return config

def set_board_alert(board, alert_type, enabled):
    if alert_type not in ('alert', 'video_alert'):
        raise ValueError(f"지원하지 않는 알림 종류: {alert_type}")
    with _db() as conn, conn:
        conn.execute("INSERT OR IGNORE INTO board_config(board) VALUES(?)", (board,))
        conn.execute(f"UPDATE board_config SET {alert_type} = ? WHERE board = ?", (int(bool(enabled)), board))

# ==========================================
# 게시글
# ==========================================
def _upsert_post(conn, post):
    now = _now()
    conn.execute("""
        INSERT INTO posts(id, title, author, date, views, votes, comment_count, link,
                          content_json, videos_json, comments_json, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title, author = excluded.author, date = excluded.date,
            views = excluded.views, votes = excluded.votes, comment_count = excluded.comment_count,
            link = excluded.link, content_json = excluded.content_json, videos_json = excluded.videos_json,
            comments_json = excluded.comments_json, updated_at = excluded.updated_at
    """, (
        str(post['id']), post.get('title', ''), post.get('author', ''), post.get('date', ''),
        str(post.get('views', '0')), str(post.get('votes', '0')), str(post.get('comment_count', '0')),
        post.get('link', ''),
        json.dumps(post.get('content', []), ensure_ascii=False),
        json.dumps(post.get('videos', []), ensure_ascii=False),
        json.dumps(post.get('comments', []), ensure_ascii=False),
        now, now
    ))

def _link_keyword_post(conn, board, keyword, post_id, is_new):
    conn.execute(
        "INSERT OR IGNORE INTO keyword_posts(board, keyword, post_id, is_new, matched_at) VALUES(?, ?, ?, ?, ?)",
        (board, keyword, str(post_id), int(bool(is_new)), _now())
    )

def save_keyword_post(board, keyword, post, is_new):
    """새로 수집한 글을 저장하고 키워드에 연결"""
    with _db() as conn, conn:
        _upsert_post(conn, post)
        _link_keyword_post(conn, board, keyword, post['id'], is_new)

def update_post(post):
    """동기화로 갱신된 글 내용(조회수·댓글 등)을 저장"""
    with _db() as conn, conn:
        _upsert_post(conn, post)

def mark_post_deleted(post_id):
    with _db() as conn, conn:
        conn.execute("UPDATE posts SET is_deleted = 1, updated_at = ? WHERE id = ?", (_now(), str(post_id)))

def _row_to_post(row):
    post = {
        'id': row['id'], 'title': row['title'], 'author': row['author'], 'date': row['date'],
        'views': row['views'], 'votes': row['votes'], 'comment_count': row['comment_count'], 'link': row['link'],
        'content': json.loads(row['content_json']), 'images': [], 'videos': json.loads(row['videos_json']),
        'comments': json.loads(row['comments_json']), 'is_new': bool(row['is_new'])
    }
    if row['is_deleted']:
        post['is_deleted'] = True
    return post

_HAS_VIDEO_SQL = "p.videos_json != '[]'"

def query_keyword_posts(board, keyword, offset=0, limit=10, video_only=False):
    """키워드에 연결된 글을 최신순으로 조회하여 (전체 개수, 글 목록) 반환"""
    where = "kp.board = ? AND kp.keyword = ?" + (f" AND {_HAS_VIDEO_SQL}" if video_only else "")
    params = (board, keyword)
    with _db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM keyword_posts kp JOIN posts p ON p.id = kp.post_id WHERE {where}", params
        ).fetchone()[0]
        rows = conn.execute(f"""
            SELECT p.*, kp.is_new FROM keyword_posts kp
            JOIN posts p ON p.id = kp.post_id
            WHERE {where}
            ORDER BY kp.rowid DESC LIMIT ? OFFSET ?
        """, params + (limit, offset)).fetchall()
    return total, [_row_to_post(r) for r in rows]

def list_keyword_tabs(new_window=100):
    """대시보드 탭 목록용 키워드별 요약 (글 수, 최근 new 글 ID, 최신 글 날짜)"""
    tabs = []
    with _db() as conn:
        for kw in conn.execute("SELECT board, keyword FROM keywords ORDER BY rowid").fetchall():
            board, keyword = kw['board'], kw['keyword']
            total = conn.execute(
                "SELECT COUNT(*) FROM keyword_posts WHERE board = ? AND keyword = ?", (board, keyword)
            ).fetchone()[0]
            recent = conn.execute("""
                SELECT kp.post_id, kp.is_new, p.date FROM keyword_posts kp
                JOIN posts p ON p.id = kp.post_id
                WHERE kp.board = ? AND kp.keyword = ?
                ORDER BY kp.rowid DESC LIMIT ?
            """, (board, keyword, new_window)).fetchall()
            tabs.append({
                'board': board,
                'keyword': keyword,
                'total': total,
                'new_ids': [r['post_id'] for r in recent if r['is_new']],
                'latest_date': recent[0]['date'] if recent else ''
            })
    return tabs

def locate_post(post_id):
    """글이 연결된 키워드와 그 키워드 목록 안에서의 순번(0부터, 최신순)을 반환. 없으면 None"""
    with _db() as conn:
        link = conn.execute(
            "SELECT rowid, board, keyword FROM keyword_posts WHERE post_id = ? ORDER BY rowid DESC LIMIT 1", (str(post_id),)
        ).fetchone()
        if not link:
            return None
        index = conn.execute(
            "SELECT COUNT(*) FROM keyword_posts WHERE board = ? AND keyword = ? AND rowid > ?",
            (link['board'], link['keyword'], link['rowid'])
        ).fetchone()[0]
    return {'board': link['board'], 'keyword': link['keyword'], 'index': index}
