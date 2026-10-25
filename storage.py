import os
import re
import json
import html
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
            list_comment_count INTEGER,
            search_text    TEXT,
            is_deleted     INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );

        -- 대시보드 읽음 기록 (PC·휴대폰 어디서 읽어도 공유). read_at 이후 달린 댓글을 '새 댓글'로 표시
        CREATE TABLE IF NOT EXISTS read_posts (
            post_id  TEXT PRIMARY KEY,
            read_at  TEXT NOT NULL
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
        CREATE INDEX IF NOT EXISTS idx_keyword_posts_keyword ON keyword_posts(board, keyword);

        -- 사용자가 만든 게시판: 등록한 키워드의 글을 중복 없이 한 피드로
        CREATE TABLE IF NOT EXISTS keyword_groups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            created_at  TEXT NOT NULL,
            alert       INTEGER NOT NULL DEFAULT 1,   -- 새 글 텔레그램 알림
            video_alert INTEGER NOT NULL DEFAULT 1    -- 동영상 글 알림 (alert가 꺼져 있어도 동영상 글은 알림)
        );
        CREATE TABLE IF NOT EXISTS keyword_group_members (
            group_id  INTEGER NOT NULL REFERENCES keyword_groups(id) ON DELETE CASCADE,
            board     TEXT NOT NULL,
            keyword   TEXT NOT NULL,
            PRIMARY KEY (group_id, board, keyword)
        );

        -- 예전 카테고리별 알림 설정. 게시판별 알림으로 옮길 때 초기값으로만 사용
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

def _add_missing_columns(conn):
    """이미 만들어진 DB에 나중에 추가된 컬럼을 보충"""
    columns = {row['name'] for row in conn.execute("PRAGMA table_info(posts)")}
    if 'list_comment_count' not in columns:
        # 목록 페이지에 표시된 댓글 수. 이 값이 바뀐 글만 상세 페이지를 다시 열어 댓글을 갱신함
        conn.execute("ALTER TABLE posts ADD COLUMN list_comment_count INTEGER")
        log_msg("[DB] posts.list_comment_count 컬럼 추가")
    if 'search_text' not in columns:
        # 제목·본문·댓글의 태그를 뺀 텍스트 (대시보드 검색용)
        conn.execute("ALTER TABLE posts ADD COLUMN search_text TEXT")
        log_msg("[DB] posts.search_text 컬럼 추가")
    group_columns = {row['name'] for row in conn.execute("PRAGMA table_info(keyword_groups)")}
    if 'alert' not in group_columns:
        # 알림을 게시판별로 설정. 초기값은 등록 키워드 카테고리의 예전 알림 설정 (하나라도 켜져 있으면 켬)
        with conn:
            for column in ('alert', 'video_alert'):
                conn.execute(f"ALTER TABLE keyword_groups ADD COLUMN {column} INTEGER NOT NULL DEFAULT 1")
                conn.execute(f"""
                    UPDATE keyword_groups SET {column} = COALESCE((
                        SELECT MAX(bc.{column}) FROM keyword_group_members m
                        JOIN board_config bc ON bc.board = m.board WHERE m.group_id = keyword_groups.id
                    ), 1)
                """)
        log_msg("[DB] 게시판별 알림 설정 컬럼 추가")

def _backfill_search_text(conn):
    """검색 텍스트가 없는 기존 글을 1회 채움"""
    rows = conn.execute("SELECT id, title, content_json, comments_json FROM posts WHERE search_text IS NULL").fetchall()
    for row in rows:
        post = {'title': row['title'], 'content': json.loads(row['content_json']), 'comments': json.loads(row['comments_json'])}
        conn.execute("UPDATE posts SET search_text = ? WHERE id = ?", (_search_text(post), row['id']))
    if rows:
        log_msg(f"[DB] 검색 텍스트 생성: 글 {len(rows)}건")

def init_db():
    """스키마 생성 및 최초 1회 기존 데이터 이전. 여러 번 호출해도 안전"""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        migrated_files = []
        with closing(_connect()) as conn:
            _create_schema(conn)
            _add_missing_columns(conn)
            with conn:
                if _get_meta(conn, 'schema_version') is None:
                    log_msg(f"[DB] 새 DB 생성: {DB_FILE}")
                    migrated_files = _migrate_legacy_files(conn)
                    _set_meta(conn, 'schema_version', SCHEMA_VERSION)
                for board in BOARD_MAP.keys():
                    conn.execute("INSERT OR IGNORE INTO board_config(board) VALUES(?)", (board,))
                _backfill_search_text(conn)
                _migrate_keywords_to_boards(conn)
        # 커밋이 끝난 뒤에만 기존 파일을 정리하여, 이전 도중 실패하면 다음 기동 시 다시 시도
        for path in migrated_files:
            _mark_legacy_migrated(path)
        _initialized = True

def _db():
    init_db()
    return closing(_connect())

# ==========================================
# 키워드 (게시판에 등록된 키워드가 곧 수집 대상. 직접 추가·삭제하지 않고 게시판 저장 시 자동 정리)
# ==========================================
def load_keywords():
    """{board: [keyword, ...]} 형태로 등록 순서대로 반환"""
    result = {board: [] for board in BOARD_MAP.keys()}
    with _db() as conn:
        for row in conn.execute("SELECT board, keyword FROM keywords ORDER BY rowid"):
            result.setdefault(row['board'], []).append(row['keyword'])
    return result

def _drop_orphan_keywords(conn):
    """어느 게시판에도 속하지 않게 된 키워드와 그 수집 데이터를 삭제하고 삭제한 (board, keyword) 목록 반환"""
    orphans = [(r['board'], r['keyword']) for r in conn.execute("""
        SELECT board, keyword FROM keywords
        WHERE (board, keyword) NOT IN (SELECT board, keyword FROM keyword_group_members)
    """).fetchall()]
    for board, keyword in orphans:
        conn.execute("DELETE FROM keywords WHERE board = ? AND keyword = ?", (board, keyword))
        conn.execute("DELETE FROM keyword_posts WHERE board = ? AND keyword = ?", (board, keyword))
    if orphans:
        conn.execute("DELETE FROM posts WHERE id NOT IN (SELECT post_id FROM keyword_posts)")
        conn.execute("DELETE FROM read_posts WHERE post_id NOT IN (SELECT id FROM posts)")
    return orphans

def _migrate_keywords_to_boards(conn):
    """게시판에 속하지 않은 기존 키워드마다 키워드 이름의 게시판을 만들어 1회 이전"""
    if _get_meta(conn, 'keyword_boards_migrated'):
        return
    loose = conn.execute("""
        SELECT board, keyword FROM keywords
        WHERE (board, keyword) NOT IN (SELECT board, keyword FROM keyword_group_members)
        ORDER BY rowid
    """).fetchall()
    for row in loose:
        name = row['keyword']
        if conn.execute("SELECT 1 FROM keyword_groups WHERE name = ?", (name,)).fetchone():
            name = f"{row['keyword']} ({BOARD_MAP.get(row['board'], row['board'])})"
        # 알림은 그 키워드 카테고리의 예전 설정을 이어받음
        cfg = conn.execute("SELECT alert, video_alert FROM board_config WHERE board = ?", (row['board'],)).fetchone()
        group_id = conn.execute("INSERT INTO keyword_groups(name, created_at, alert, video_alert) VALUES(?, ?, ?, ?)",
                                (name, _now(), cfg['alert'] if cfg else 1, cfg['video_alert'] if cfg else 1)).lastrowid
        conn.execute("INSERT INTO keyword_group_members(group_id, board, keyword) VALUES(?, ?, ?)",
                     (group_id, row['board'], row['keyword']))
    _set_meta(conn, 'keyword_boards_migrated', '1')
    if loose:
        log_msg(f"[DB] 키워드 {len(loose)}개를 같은 이름의 게시판으로 이전")

# ==========================================
# 게시판 (하나 이상의 키워드 글을 중복 없이 한 피드로)
# ==========================================
def _feed_from(group_id=None):
    """피드 글 연결의 FROM 절과 파라미터. group_id가 없으면 모든 게시판(등록 키워드 전체)"""
    sql = """
        FROM keyword_posts kp
        JOIN keywords k ON k.board = kp.board AND k.keyword = kp.keyword
    """
    if group_id is None:
        return sql, ()
    return sql + "JOIN keyword_group_members gm ON gm.board = kp.board AND gm.keyword = kp.keyword AND gm.group_id = ?\n", (group_id,)

def _feed_summary(conn, new_window, group_id=None):
    """중복 제거한 글 수, 최근 new_window개 중 안 읽은 새 글 ID, 최신 글 날짜"""
    base, params = _feed_from(group_id)
    total = conn.execute(f"SELECT COUNT(DISTINCT kp.post_id) {base}", params).fetchone()[0]
    recent = conn.execute(f"""
        SELECT kp.post_id, MAX(kp.is_new) AS is_new, MAX(kp.rowid) AS last_rowid, p.date, rp.read_at
        {base}
        JOIN posts p ON p.id = kp.post_id
        LEFT JOIN read_posts rp ON rp.post_id = kp.post_id
        GROUP BY kp.post_id ORDER BY last_rowid DESC LIMIT ?
    """, params + (new_window,)).fetchall()
    return {
        'total': total,
        'unread_ids': [r['post_id'] for r in recent if r['is_new'] and not r['read_at']],
        'latest_date': recent[0]['date'] if recent else ''
    }

def feed_summary(new_window=100):
    """모든 게시판을 합친 통합 피드 요약"""
    with _db() as conn:
        return _feed_summary(conn, new_window)

def list_groups(new_window=100):
    """게시판 목록: 등록 키워드, 알림 설정, 중복 제거한 글 수, 안 읽은 새 글 ID, 최신 글 날짜"""
    groups = []
    with _db() as conn:
        for g in conn.execute("SELECT id, name, alert, video_alert FROM keyword_groups ORDER BY id").fetchall():
            members = [dict(board=r['board'], keyword=r['keyword']) for r in conn.execute("""
                SELECT m.board, m.keyword FROM keyword_group_members m
                JOIN keywords k ON k.board = m.board AND k.keyword = m.keyword
                WHERE m.group_id = ? ORDER BY k.rowid
            """, (g['id'],))]
            groups.append({'id': g['id'], 'name': g['name'], 'members': members,
                           'alert': bool(g['alert']), 'video_alert': bool(g['video_alert']),
                           **_feed_summary(conn, new_window, g['id'])})
    return groups

def save_group(group_id, name, members):
    """게시판 생성(group_id=None) 또는 수정. 새 키워드는 수집 대상으로 등록하고,
    어느 게시판에도 남지 않은 키워드는 수집 데이터와 함께 삭제. (게시판 ID, 삭제된 키워드 목록) 반환.
    이름 중복 등은 ValueError"""
    pairs = list(dict.fromkeys((m['board'], m['keyword']) for m in members))
    if not pairs:
        raise ValueError('키워드를 하나 이상 등록해 주세요.')
    with _db() as conn, conn:
        clash = conn.execute("SELECT id FROM keyword_groups WHERE name = ? AND id != ?", (name, group_id or -1)).fetchone()
        if clash:
            raise ValueError('같은 이름의 게시판이 이미 있습니다.')
        if group_id is None:
            group_id = conn.execute("INSERT INTO keyword_groups(name, created_at) VALUES(?, ?)", (name, _now())).lastrowid
        else:
            if not conn.execute("SELECT 1 FROM keyword_groups WHERE id = ?", (group_id,)).fetchone():
                raise ValueError('존재하지 않는 게시판입니다.')
            conn.execute("UPDATE keyword_groups SET name = ? WHERE id = ?", (name, group_id))
            conn.execute("DELETE FROM keyword_group_members WHERE group_id = ?", (group_id,))
        conn.executemany("INSERT OR IGNORE INTO keywords(board, keyword) VALUES(?, ?)", pairs)
        conn.executemany("INSERT OR IGNORE INTO keyword_group_members(group_id, board, keyword) VALUES(?, ?, ?)",
                         [(group_id, b, k) for b, k in pairs])
        return group_id, _drop_orphan_keywords(conn)

def delete_group(group_id):
    """게시판 삭제. 다른 게시판에 없는 키워드는 수집 데이터와 함께 삭제.
    삭제된 키워드 목록 반환, 없는 게시판이면 None"""
    with _db() as conn, conn:
        conn.execute("DELETE FROM keyword_group_members WHERE group_id = ?", (group_id,))
        if conn.execute("DELETE FROM keyword_groups WHERE id = ?", (group_id,)).rowcount == 0:
            return None
        return _drop_orphan_keywords(conn)

def post_exists(post_id):
    """다른 키워드로 이미 수집된 글인지 (같은 글 중복 알림 방지용)"""
    with _db() as conn:
        return conn.execute("SELECT 1 FROM posts WHERE id = ?", (str(post_id),)).fetchone() is not None

# ==========================================
# 게시판 알림 설정
# ==========================================
def load_alert_targets():
    """{(board, keyword): [{'name', 'alert', 'video_alert'}, ...]} 키워드가 등록된 게시판들의 알림 설정"""
    targets = {}
    with _db() as conn:
        for row in conn.execute("""
            SELECT m.board, m.keyword, g.name, g.alert, g.video_alert FROM keyword_group_members m
            JOIN keyword_groups g ON g.id = m.group_id ORDER BY g.id
        """):
            targets.setdefault((row['board'], row['keyword']), []).append(
                {'name': row['name'], 'alert': bool(row['alert']), 'video_alert': bool(row['video_alert'])})
    return targets

def set_group_alert(group_id, alert_type, enabled):
    """게시판 알림 켜기·끄기. 게시판 이름 반환, 없는 게시판이면 None"""
    if alert_type not in ('alert', 'video_alert'):
        raise ValueError(f"지원하지 않는 알림 종류: {alert_type}")
    with _db() as conn, conn:
        row = conn.execute("SELECT name FROM keyword_groups WHERE id = ?", (group_id,)).fetchone()
        if not row:
            return None
        conn.execute(f"UPDATE keyword_groups SET {alert_type} = ? WHERE id = ?", (int(bool(enabled)), group_id))
        return row['name']

# ==========================================
# 게시글
# ==========================================
_TAG_RE = re.compile(r'<[^>]+>')

def _plain_text(lines):
    return html.unescape(_TAG_RE.sub(' ', ' '.join(lines or []))).strip()

def _comment_key(comment):
    # 댓글 날짜는 '3 시간 전'처럼 상대 표기라 매번 바뀌므로 작성자와 내용으로 같은 댓글인지 판별
    return comment.get('author', '') + '\x1f' + ' '.join(_plain_text(comment.get('content')).split())

def _search_text(post):
    parts = [post.get('title', ''), _plain_text(post.get('content'))]
    for comment in post.get('comments', []):
        parts.append(comment.get('author', ''))
        parts.append(_plain_text(comment.get('content')))
    return ' '.join(' '.join(parts).split()).lower()

def _carry_comment_first_seen(old_comments, new_comments, now):
    """다시 수집한 댓글에 처음 수집된 시각(first_seen)을 이어붙임. 이전에 없던 댓글만 지금 시각이 됨
    (first_seen이 없는 예전 댓글은 '예전부터 있던 댓글'로 남겨 새 댓글로 표시되지 않게 함)"""
    remaining = {}
    for c in old_comments:
        remaining.setdefault(_comment_key(c), []).append(c.get('first_seen'))
    for c in new_comments:
        seen = remaining.get(_comment_key(c))
        c['first_seen'] = seen.pop(0) if seen else now
    return new_comments

def _upsert_post(conn, post):
    now = _now()
    existing = conn.execute("SELECT comments_json FROM posts WHERE id = ?", (str(post['id']),)).fetchone()
    comments = [dict(c) for c in post.get('comments', [])]
    if existing:
        _carry_comment_first_seen(json.loads(existing['comments_json']), comments, now)
    else:
        for c in comments:
            c.setdefault('first_seen', now)
    conn.execute("""
        INSERT INTO posts(id, title, author, date, views, votes, comment_count, link,
                          content_json, videos_json, comments_json, list_comment_count, search_text, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title, author = excluded.author, date = excluded.date,
            views = excluded.views, votes = excluded.votes, comment_count = excluded.comment_count,
            link = excluded.link, content_json = excluded.content_json, videos_json = excluded.videos_json,
            comments_json = excluded.comments_json,
            list_comment_count = COALESCE(excluded.list_comment_count, posts.list_comment_count),
            search_text = excluded.search_text,
            updated_at = excluded.updated_at
    """, (
        str(post['id']), post.get('title', ''), post.get('author', ''), post.get('date', ''),
        str(post.get('views', '0')), str(post.get('votes', '0')), str(post.get('comment_count', '0')),
        post.get('link', ''),
        json.dumps(post.get('content', []), ensure_ascii=False),
        json.dumps(post.get('videos', []), ensure_ascii=False),
        json.dumps(comments, ensure_ascii=False),
        post.get('list_comment_count'),
        _search_text(dict(post, comments=comments)),
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

def update_list_stats(post_id, views=None, votes=None, list_comment_count=None):
    """상세 페이지를 열지 않고 목록 페이지 값(조회·추천·목록 댓글 수)만 반영. None인 값은 유지"""
    with _db() as conn, conn:
        conn.execute("""
            UPDATE posts SET
                views = COALESCE(?, views), votes = COALESCE(?, votes),
                list_comment_count = COALESCE(?, list_comment_count)
            WHERE id = ?
        """, (views, votes, list_comment_count, str(post_id)))

def mark_post_deleted(post_id):
    with _db() as conn, conn:
        conn.execute("UPDATE posts SET is_deleted = 1, updated_at = ? WHERE id = ?", (_now(), str(post_id)))

def _row_to_post(row):
    keys = row.keys()
    post = {
        'id': row['id'], 'title': row['title'], 'author': row['author'], 'date': row['date'],
        'views': row['views'], 'votes': row['votes'], 'comment_count': row['comment_count'], 'link': row['link'],
        'content': json.loads(row['content_json']), 'images': [], 'videos': json.loads(row['videos_json']),
        'comments': json.loads(row['comments_json']), 'is_new': bool(row['is_new']),
        'list_comment_count': row['list_comment_count'],
        'read_at': row['read_at'] if 'read_at' in keys else None
    }
    if 'keyword_links' in keys and row['keyword_links']:
        # 통합 피드: 이 글이 걸린 키워드 목록 [{board, keyword}]
        post['keywords'] = [dict(zip(('board', 'keyword'), link.split('\x1f', 1))) for link in row['keyword_links'].split('\x1e')]
    if row['is_deleted']:
        post['is_deleted'] = True
    return post

_HAS_VIDEO_SQL = "p.videos_json != '[]'"

def _search_conditions(query):
    """검색어를 공백으로 나눠 모든 단어가 포함된 글만 (대소문자 무시, LIKE 특수문자 이스케이프)"""
    terms = [t for t in (query or '').lower().split() if t][:5]
    sql = ''.join(" AND p.search_text LIKE ? ESCAPE '\\'" for _ in terms)
    params = tuple('%' + t.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%' for t in terms)
    return sql, params

def query_keyword_posts(board, keyword, offset=0, limit=10, video_only=False):
    """키워드에 연결된 글을 최신순으로 조회하여 (전체 개수, 글 목록) 반환"""
    where = "kp.board = ? AND kp.keyword = ?" + (f" AND {_HAS_VIDEO_SQL}" if video_only else "")
    params = (board, keyword)
    with _db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM keyword_posts kp JOIN posts p ON p.id = kp.post_id WHERE {where}", params
        ).fetchone()[0]
        rows = conn.execute(f"""
            SELECT p.*, kp.is_new, rp.read_at FROM keyword_posts kp
            JOIN posts p ON p.id = kp.post_id
            LEFT JOIN read_posts rp ON rp.post_id = p.id
            WHERE {where}
            ORDER BY kp.rowid DESC LIMIT ? OFFSET ?
        """, params + (limit, offset)).fetchall()
    return total, [_row_to_post(r) for r in rows]

# 안 읽은 새 글: 새 글로 수집됐고 아직 읽음 기록이 없는 글
_UNREAD_SQL = "kp.is_new = 1 AND rp.read_at IS NULL"

def query_all_posts(offset=0, limit=10, video_only=False, query=None, group_id=None, unread_since=None):
    """게시판에 등록된 키워드의 글을 한 번씩만(중복 제거) 최신 수집순으로 조회.
    group_id가 있으면 그 게시판만, query가 있으면 검색 결과.
    unread_since가 있으면 안 읽은 새 글만: 그 시각 이후에 읽은 글은 계속 포함해
    보는 도중 읽음 처리가 되어도 페이지가 밀리지 않게 함"""
    search_sql, search_params = _search_conditions(query)
    feed_sql, params = _feed_from(group_id)
    params += search_params
    unread_sql = ''
    if unread_since is not None:
        unread_sql = "AND kp.is_new = 1 AND (rp.read_at IS NULL OR rp.read_at > ?)"
        params += (unread_since,)
    base = f"""
        {feed_sql}
        JOIN posts p ON p.id = kp.post_id
        LEFT JOIN read_posts rp ON rp.post_id = p.id
        WHERE 1 = 1 {f'AND {_HAS_VIDEO_SQL}' if video_only else ''} {search_sql} {unread_sql}
    """
    with _db() as conn:
        total = conn.execute(f"SELECT COUNT(DISTINCT p.id) {base}", params).fetchone()[0]
        rows = conn.execute(f"""
            SELECT p.*, rp.read_at, MAX(kp.is_new) AS is_new, MAX(kp.rowid) AS last_rowid,
                   GROUP_CONCAT(kp.board || char(31) || kp.keyword, char(30)) AS keyword_links
            {base}
            GROUP BY p.id
            ORDER BY last_rowid DESC LIMIT ? OFFSET ?
        """, params + (limit, offset)).fetchall()
    return total, [_row_to_post(r) for r in rows]

def unread_summary(id_limit=500):
    """안 읽은 새 글 모아보기 요약: 글 수(중복 제거)와 최신순 글 ID(최대 id_limit개)"""
    base, params = _feed_from()
    with _db() as conn:
        rows = conn.execute(f"""
            SELECT kp.post_id, MAX(kp.rowid) AS last_rowid {base}
            LEFT JOIN read_posts rp ON rp.post_id = kp.post_id
            WHERE {_UNREAD_SQL}
            GROUP BY kp.post_id ORDER BY last_rowid DESC
        """, params).fetchall()
    return {'total': len(rows), 'unread_ids': [r['post_id'] for r in rows[:id_limit]]}

def latest_alert_group():
    """가장 최근에 텔레그램 알림이 간 새 글의 게시판 ID (알림 설정 기준). 없으면 None"""
    base, params = _feed_from()
    with _db() as conn:
        row = conn.execute(f"""
            SELECT gm.group_id {base}
            JOIN keyword_group_members gm ON gm.board = kp.board AND gm.keyword = kp.keyword
            JOIN keyword_groups g ON g.id = gm.group_id
            JOIN posts p ON p.id = kp.post_id
            WHERE kp.is_new = 1 AND (g.alert = 1 OR (g.video_alert = 1 AND {_HAS_VIDEO_SQL}))
            ORDER BY kp.rowid DESC, gm.group_id LIMIT 1
        """, params).fetchone()
    return row[0] if row else None

def recent_post_ids(limit_per_keyword):
    """키워드별 최근 글 ID 집합 (메인 루프가 목록의 댓글 수로 매 주기 변화를 감시하는 범위)"""
    ids = set()
    with _db() as conn:
        for kw in conn.execute("SELECT board, keyword FROM keywords").fetchall():
            ids.update(r['post_id'] for r in conn.execute(
                "SELECT post_id FROM keyword_posts WHERE board = ? AND keyword = ? ORDER BY rowid DESC LIMIT ?",
                (kw['board'], kw['keyword'], limit_per_keyword)))
    return ids

def fix_stored_x_embeds():
    """이미 저장된 글 중 X(트위터) '링크 자동 변환 중' 임시 상자가 남은 글을 트윗 카드로 1회 변환"""
    from bs4 import BeautifulSoup
    from embeds import convert_x_embeds
    from sanitize import sanitize_tree
    with _db() as conn:
        if _get_meta(conn, 'x_embeds_fixed'):
            return
        rows = conn.execute("SELECT id, title, content_json, comments_json FROM posts WHERE content_json LIKE '%twitter-tweet%'").fetchall()
    fixed = 0
    for row in rows:
        content = json.loads(row['content_json'])
        soup = BeautifulSoup('\n'.join(content), 'html.parser')
        if not convert_x_embeds(soup, soup):
            continue
        sanitize_tree(soup)
        new_content = soup.decode().split('\n')
        post = {'title': row['title'], 'content': new_content, 'comments': json.loads(row['comments_json'])}
        with _db() as conn, conn:
            conn.execute("UPDATE posts SET content_json = ?, search_text = ? WHERE id = ?",
                         (json.dumps(new_content, ensure_ascii=False), _search_text(post), row['id']))
        fixed += 1
    with _db() as conn, conn:
        _set_meta(conn, 'x_embeds_fixed', '1')
    if fixed:
        log_msg(f"[DB] 저장된 글의 X 트윗 카드 변환: {fixed}건")

def mark_posts_read(post_ids):
    """읽음 기록 저장. 이미 읽은 글은 읽은 시각을 갱신(그 이후 달린 댓글만 '새 댓글'이 되도록)"""
    ids = [str(i) for i in post_ids if str(i).isdigit()]
    if not ids:
        return 0
    now = _now()
    with _db() as conn, conn:
        conn.executemany(
            "INSERT INTO read_posts(post_id, read_at) VALUES(?, ?) ON CONFLICT(post_id) DO UPDATE SET read_at = excluded.read_at",
            [(i, now) for i in ids]
        )
    return len(ids)

def locate_post(post_id):
    """글이 속한 첫 게시판과 그 게시판 피드 안에서의 순번(0부터, 최신순)을 반환.
    게시판이 없으면 group은 None(통합 피드 기준). 수집되지 않은 글이면 None"""
    post_id = str(post_id)
    with _db() as conn:
        group_id = conn.execute("""
            SELECT MIN(gm.group_id) FROM keyword_posts kp
            JOIN keyword_group_members gm ON gm.board = kp.board AND gm.keyword = kp.keyword
            WHERE kp.post_id = ?
        """, (post_id,)).fetchone()[0]
        base, params = _feed_from(group_id)
        last = conn.execute(f"SELECT MAX(kp.rowid) {base} WHERE kp.post_id = ?", params + (post_id,)).fetchone()[0]
        if last is None:
            return None
        index = conn.execute(f"""
            SELECT COUNT(*) FROM (SELECT MAX(kp.rowid) AS last_rowid {base} GROUP BY kp.post_id)
            WHERE last_rowid > ?
        """, params + (last,)).fetchone()[0]
    return {'group': group_id, 'index': index}
