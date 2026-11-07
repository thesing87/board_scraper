import os
import re
import json
import time
import html
import sqlite3
import threading
from contextlib import closing, contextmanager
try:
    import fcntl
except ImportError:  # Windows(개발용)는 수집기·웹서버를 한 프로세스로만 돌리므로 프로세스 간 잠금이 필요 없음
    fcntl = None
from datetime import datetime, timedelta
from config import (
    log_msg,
    short_err,
    DB_FILE,
    BACKUP_DIR,
    KEYWORDS_FILE,
    BOARD_CONFIG_FILE,
    JSON_BACKUP_FILE,
    BOARD_MAP
)
from sites import board_site, is_post_id, SITE_NAMES, SITE_SHORT, MULTI_SITE

SCHEMA_VERSION = 1

# 연결 하나의 SQLite 페이지 캐시 크기(KiB). 연결은 조회마다 새로 열고 닫으므로 오래 붙잡지 않음
CACHE_KIB = 16 * 1024
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
    # 연결마다의 페이지 캐시(기본 2MB)가 글 표의 작은 칸 페이지보다 작으면 한 조회 안에서도 같은 페이지를 거듭 읽음
    conn.execute(f"PRAGMA cache_size = -{CACHE_KIB}")
    return conn

# 글 표의 칸 (새 DB의 표와 예전 DB를 옮길 때 같은 정의). 글 수 세기·목록 고르기에 쓰는 작은 칸만 두고,
# 본문·댓글 JSON과 검색 텍스트는 post_bodies에 따로 둠: 한 표에 함께 두면 작은 칸만 읽는 조회도 글마다 본문이 든
# 페이지를 디스크에서 읽어, 메모리에서 밀려난 뒤 첫 화면이 수십 초 걸렸음 (상태 조회 한 번에 DB 크기의 10배를 읽음)
POSTS_COLUMNS = """
            id             TEXT PRIMARY KEY,
            title          TEXT NOT NULL DEFAULT '',
            author         TEXT NOT NULL DEFAULT '',
            date           TEXT NOT NULL DEFAULT '',
            views          TEXT NOT NULL DEFAULT '0',
            votes          TEXT NOT NULL DEFAULT '0',
            comment_count  TEXT NOT NULL DEFAULT '0',
            link           TEXT NOT NULL DEFAULT '',
            list_comment_count INTEGER,
            all_comment_pages INTEGER NOT NULL DEFAULT 0,
            is_deleted     INTEGER NOT NULL DEFAULT 0,
            has_video      INTEGER NOT NULL DEFAULT 0,   -- 동영상 목록이 있음 ('동영상' 보기)
            has_image      INTEGER NOT NULL DEFAULT 0,   -- 첨부 이미지가 있음 ('이미지' 보기, _has_image)
            image_count    INTEGER NOT NULL DEFAULT 0,   -- 모아보기에 보일 첨부 이미지 수 (post_images)
            video_count    INTEGER NOT NULL DEFAULT 0,   -- 모아보기에 보일 동영상 수 (post_videos)
            last_comment_at TEXT,                        -- 가장 최근에 처음 본 댓글의 시각 ('새 댓글' 보기)
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
"""
POST_BODIES_COLUMNS = """
            post_id        TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
            videos_json    TEXT NOT NULL DEFAULT '[]',
            content_json   TEXT NOT NULL DEFAULT '[]',
            comments_json  TEXT NOT NULL DEFAULT '[]',
            search_text    TEXT                          -- 제목·본문·댓글의 태그를 뺀 텍스트 (대시보드 검색용)
"""

def _create_schema(conn):
    conn.executescript("""
        PRAGMA journal_mode = WAL;

        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS posts (""" + POSTS_COLUMNS + """        );
        CREATE TABLE IF NOT EXISTS post_bodies (""" + POST_BODIES_COLUMNS + """        );

        -- 대시보드 읽음 기록 (PC·휴대폰 어디서 읽어도 공유). read_at 이후 달린 댓글을 '새 댓글'로 표시
        CREATE TABLE IF NOT EXISTS read_posts (
            post_id        TEXT PRIMARY KEY,
            read_at        TEXT NOT NULL,   -- 마지막으로 읽은 시각 (이후 달린 댓글이 '새 댓글')
            first_read_at  TEXT             -- 처음 읽은 시각 (다시 읽어도 그대로, '안 읽은 글' 보기 기준)
        );

        -- 보관함: 별표를 단 글 (기기 간 공유). 오래된 글 정리에서 빠짐 (키워드·게시판을 지우면 함께 지워짐)
        CREATE TABLE IF NOT EXISTS saved_posts (
            post_id     TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
            saved_at    TEXT NOT NULL,
            checked_at  TEXT              -- 수집기가 새 댓글을 확인하려고 마지막으로 연 시각
        );

        CREATE TABLE IF NOT EXISTS keywords (
            board    TEXT NOT NULL,
            keyword  TEXT NOT NULL,
            paused   INTEGER NOT NULL DEFAULT 0,   -- 일시정지: 모은 글은 그대로 두고 수집만 멈춤
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

        -- 사용자가 만든 게시판: 등록한 키워드의 글을 중복 없이 한 피드로.
        -- 게시판은 한 사이트의 키워드만 담고, 이름은 사이트 안에서만 겹치지 않으면 됨 (FM 싼타페·DC 싼타페)
        CREATE TABLE IF NOT EXISTS keyword_groups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            site        TEXT NOT NULL DEFAULT 'fmkorea',  -- sites.py의 사이트 (fmkorea·dcinside)
            name        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            alert       INTEGER NOT NULL DEFAULT 1,   -- 새 글 텔레그램 알림
            video_alert INTEGER NOT NULL DEFAULT 1,   -- 동영상 글 알림 (alert가 꺼져 있어도 동영상 글은 알림)
            digest      INTEGER NOT NULL DEFAULT 0,   -- 하루 요약 알림 (매일 DIGEST_HOUR에 전날 인기 글)
            UNIQUE (site, name)
        );
        -- 텔레그램에 연결하지 못해 보내지 못한 알림. 수집기가 다음 주기부터 다시 보냄 (notifier.retry_pending_alerts)
        CREATE TABLE IF NOT EXISTS pending_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            payload     TEXT NOT NULL,              -- sendMessage로 보낼 내용 JSON (chat_id 제외)
            what        TEXT NOT NULL,              -- 로그용 알림 종류 (새 글 알림 등)
            attempts    INTEGER NOT NULL DEFAULT 0, -- 다시 보내 본 횟수
            created_at  TEXT NOT NULL
        );

        -- 사이드바에서 게시판을 묶어 보여 주는 묶음 (사용자가 만들고 이름·순서를 정함). 게시판은 묶음 하나에 들어가거나 묶음 없이 둠
        CREATE TABLE IF NOT EXISTS group_folders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            position    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS keyword_group_members (
            group_id  INTEGER NOT NULL REFERENCES keyword_groups(id) ON DELETE CASCADE,
            board     TEXT NOT NULL,
            keyword   TEXT NOT NULL,
            PRIMARY KEY (group_id, board, keyword)
        );
        -- 키워드별 무시할 표현: 이 표현을 지운 뒤에도 키워드가 남아 있는 글만 모음 (예: '싼하'에 '투싼하')
        CREATE TABLE IF NOT EXISTS keyword_ignores (
            board    TEXT NOT NULL,
            keyword  TEXT NOT NULL,
            phrase   TEXT NOT NULL,   -- 입력한 그대로
            PRIMARY KEY (board, keyword, phrase)
        );

        -- 수집할 게시판(카테고리: 에펨코리아 게시판 또는 디시 갤러리). rowid 순서가 화면 표시 순서
        -- 관리 화면에서 추가하면 pending, 수집기가 다음 주기에 열어 보고 ok(수집) 또는 invalid(수집 안 함)로 바꿈
        CREATE TABLE IF NOT EXISTS categories (
            key         TEXT PRIMARY KEY,           -- 에펨코리아 게시판 mid 또는 'dc:' + 디시 갤러리 id (sites.py)
            name        TEXT NOT NULL DEFAULT '',   -- 비어 있으면 확인할 때 게시판 제목으로 채움
            status      TEXT NOT NULL DEFAULT 'pending',
            message     TEXT NOT NULL DEFAULT '',   -- 확인 실패 사유
            checked_at  TEXT,
            created_at  TEXT NOT NULL
        );

        -- 예전 카테고리별 알림 설정. 게시판별 알림으로 옮길 때 초기값으로만 사용
        CREATE TABLE IF NOT EXISTS board_config (
            board        TEXT PRIMARY KEY,
            alert        INTEGER NOT NULL DEFAULT 1,
            video_alert  INTEGER NOT NULL DEFAULT 1
        );

        -- 검색에는 걸렸지만 키워드가 그대로 들어 있지 않아 거른 글. 재시작 후에도 같은 글을 다시 열지 않도록 기억
        CREATE TABLE IF NOT EXISTS rejected_posts (
            board        TEXT NOT NULL,
            keyword      TEXT NOT NULL,
            post_id      TEXT NOT NULL,
            rejected_at  TEXT NOT NULL,
            PRIMARY KEY (board, keyword, post_id)
        );

        -- 새 글로 수집했지만 알림을 보내지 않은 글 (그 키워드의 게시판이 모두 알림을 꺼 둠 등).
        -- 다른 키워드(다른 게시판)에서 같은 글이 걸렸을 때, 그 게시판이 알림을 원하면 그때 한 번 보내려고 기억
        CREATE TABLE IF NOT EXISTS unalerted_posts (
            post_id      TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
            collected_at TEXT NOT NULL
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
    if 'all_comment_pages' not in columns:
        # 댓글이 여러 페이지인 글의 모든 페이지를 읽어 저장했는지 (_upsert_post 참고)
        conn.execute("ALTER TABLE posts ADD COLUMN all_comment_pages INTEGER NOT NULL DEFAULT 0")
        log_msg("[DB] posts.all_comment_pages 컬럼 추가")
    if 'content_json' in columns and 'search_text' not in columns:
        # 제목·본문·댓글의 태그를 뺀 텍스트 (대시보드 검색용)
        conn.execute("ALTER TABLE posts ADD COLUMN search_text TEXT")
        log_msg("[DB] posts.search_text 컬럼 추가")
    if 'content_json' in {row['name'] for row in conn.execute("PRAGMA table_info(posts)")}:
        _split_posts(conn)
    post_columns = {row['name'] for row in conn.execute("PRAGMA table_info(posts)")}
    for name in ('image_count', 'video_count'):
        if name not in post_columns:
            # 모아보기를 글이 아닌 이미지·동영상 개수로 나누려고 글마다 개수를 둠 (본문을 읽지 않고 페이지를 정함)
            conn.execute(f"ALTER TABLE posts ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
            log_msg(f"[DB] posts.{name} 컬럼 추가")
    read_columns = {row['name'] for row in conn.execute("PRAGMA table_info(read_posts)")}
    if 'first_read_at' not in read_columns:
        # 다시 읽으면 read_at이 갱신되어, '안 읽은 글' 보기(연 시각 이후 읽은 글 포함)에 이미 읽은 글이 섞이던 문제
        with conn:
            conn.execute("ALTER TABLE read_posts ADD COLUMN first_read_at TEXT")
            conn.execute("UPDATE read_posts SET first_read_at = read_at")
        log_msg("[DB] read_posts.first_read_at 컬럼 추가")
    if 'checked_at' not in {row['name'] for row in conn.execute("PRAGMA table_info(saved_posts)")}:
        conn.execute("ALTER TABLE saved_posts ADD COLUMN checked_at TEXT")
        log_msg("[DB] saved_posts.checked_at 컬럼 추가")
    if 'paused' not in {row['name'] for row in conn.execute("PRAGMA table_info(keywords)")}:
        conn.execute("ALTER TABLE keywords ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
        log_msg("[DB] keywords.paused 컬럼 추가")
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
    if 'site' not in {row['name'] for row in conn.execute("PRAGMA table_info(keyword_groups)")}:
        _add_group_site(conn)
    group_columns = {row['name'] for row in conn.execute("PRAGMA table_info(keyword_groups)")}
    if 'folder_id' not in group_columns:
        # 게시판이 속한 묶음(group_folders, 없으면 묶음 없음)과 사이드바 표시 순서
        conn.execute("ALTER TABLE keyword_groups ADD COLUMN folder_id INTEGER")
        conn.execute("ALTER TABLE keyword_groups ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE keyword_groups SET position = id")
        log_msg("[DB] keyword_groups.folder_id·position 컬럼 추가")
    if 'digest' not in {row['name'] for row in conn.execute("PRAGMA table_info(keyword_groups)")}:
        conn.execute("ALTER TABLE keyword_groups ADD COLUMN digest INTEGER NOT NULL DEFAULT 0")
        log_msg("[DB] keyword_groups.digest 컬럼 추가")

def _add_group_site(conn):
    """게시판에 사이트 칸을 넣고 이름 중복 규칙을 '사이트 안에서만'으로 바꿈. SQLite는 기존 UNIQUE를 고칠 수 없어
    표를 새로 만들어 옮김 (게시판 번호는 그대로라 키워드·알림·읽음 기록은 영향 없음).
    옛 표를 지울 때 게시판 키워드(ON DELETE CASCADE)가 함께 지워지지 않도록 외래 키 검사를 잠시 끔"""
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            conn.execute("""
                CREATE TABLE keyword_groups_new (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    site        TEXT NOT NULL DEFAULT 'fmkorea',
                    name        TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    alert       INTEGER NOT NULL DEFAULT 1,
                    video_alert INTEGER NOT NULL DEFAULT 1,
                    UNIQUE (site, name)
                )
            """)
            # 사이트는 등록된 키워드의 카테고리로 정함 (디시 갤러리 키워드가 있으면 디시인사이드)
            conn.execute("""
                INSERT INTO keyword_groups_new(id, site, name, created_at, alert, video_alert)
                SELECT g.id,
                       CASE WHEN EXISTS (SELECT 1 FROM keyword_group_members m WHERE m.group_id = g.id AND m.board LIKE 'dc:%')
                            THEN 'dcinside' ELSE 'fmkorea' END,
                       g.name, g.created_at, g.alert, g.video_alert
                FROM keyword_groups g
            """)
            conn.execute("DROP TABLE keyword_groups")
            conn.execute("ALTER TABLE keyword_groups_new RENAME TO keyword_groups")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    log_msg("[DB] 게시판에 사이트 칸 추가 (게시판 이름은 사이트 안에서만 겹치지 않으면 됨)")

def _split_posts(conn):
    """예전 글 표(본문·댓글 JSON이 함께 있음)를 작은 글 표와 본문 표(post_bodies)로 나눠 옮김 (POSTS_COLUMNS 설명 참고).
    동영상·이미지 여부와 마지막 댓글 시각은 본문·댓글 JSON에서 계산해 채우고, 다 옮긴 뒤 빈 공간을 정리(VACUUM)해
    작은 글 표가 디스크에 모여 있게 함. 옮기기 전 DB는 백업 폴더에 남김.
    옛 표를 지울 때 키워드 연결·보관함(ON DELETE CASCADE)이 지워지지 않도록 외래 키 검사를 잠시 끔"""
    started = time.time()
    conn.commit()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup = os.path.join(BACKUP_DIR, f"board-before-posts-split-{datetime.now().strftime('%Y%m%d%H%M%S')}.db")
    with closing(sqlite3.connect(backup)) as dest:
        conn.backup(dest)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            conn.execute("CREATE TABLE posts_new (" + POSTS_COLUMNS + ")")
            conn.execute(f"""
                INSERT INTO posts_new(id, title, author, date, views, votes, comment_count, link, list_comment_count,
                                      all_comment_pages, is_deleted, has_video, has_image, last_comment_at, created_at, updated_at)
                SELECT id, title, author, date, views, votes, comment_count, link, list_comment_count,
                       all_comment_pages, is_deleted, videos_json != '[]', {_HAS_IMAGE_JSON_SQL},
                       (SELECT MAX(json_extract(c.value, '$.first_seen')) FROM json_each(comments_json) c),
                       created_at, updated_at
                FROM posts ORDER BY rowid
            """)
            conn.execute("DROP TABLE IF EXISTS post_bodies")
            conn.execute("CREATE TABLE post_bodies (" + POST_BODIES_COLUMNS + ")")
            conn.execute("""
                INSERT INTO post_bodies(post_id, videos_json, content_json, comments_json, search_text)
                SELECT id, videos_json, content_json, comments_json, search_text FROM posts ORDER BY rowid
            """)
            conn.execute("DROP TABLE posts")
            conn.execute("ALTER TABLE posts_new RENAME TO posts")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    log_msg(f"[DB] 글 표를 작은 표와 본문 표로 나눔 (동영상·이미지·마지막 댓글 칸 추가, {time.time() - started:.0f}초, "
            f"이전 DB: {os.path.basename(backup)})")
    try:
        conn.execute("VACUUM")
        log_msg(f"[DB] 빈 공간 정리 완료 ({time.time() - started:.0f}초)")
    except sqlite3.OperationalError as e:
        # 다른 프로세스가 DB를 읽고 있으면 실패할 수 있음. 표는 이미 옮겨졌으므로 정리만 건너뜀
        log_msg(f"[DB] 빈 공간 정리는 건너뜀: {short_err(e)}", "WARN")

def _backfill_search_text(conn):
    """검색 텍스트가 없는 기존 글을 1회 채움. 한 번 끝나면 다시 확인하지 않음
    (새 글은 저장할 때 채우므로, 매번 확인하면 프로세스가 시작할 때마다 모든 글을 디스크에서 읽음)"""
    if _get_meta(conn, 'search_text_backfilled'):
        return
    rows = conn.execute("""
        SELECT p.id, p.title, b.content_json, b.comments_json FROM post_bodies b JOIN posts p ON p.id = b.post_id
        WHERE b.search_text IS NULL
    """).fetchall()
    for row in rows:
        post = {'title': row['title'], 'content': json.loads(row['content_json']), 'comments': json.loads(row['comments_json'])}
        conn.execute("UPDATE post_bodies SET search_text = ? WHERE post_id = ?", (_search_text(post), row['id']))
    _set_meta(conn, 'search_text_backfilled', '1')
    if rows:
        log_msg(f"[DB] 검색 텍스트 생성: 글 {len(rows)}건")

def _backfill_media_counts(conn):
    """기존 글의 이미지·동영상 수를 1회 채움 (이미지·동영상이 있는 글의 본문만 읽음)"""
    if _get_meta(conn, 'media_counts_backfilled'):
        return
    rows = conn.execute("""
        SELECT p.id, b.content_json, b.videos_json FROM posts p JOIN post_bodies b ON b.post_id = p.id
        WHERE p.has_image = 1 OR p.has_video = 1
    """).fetchall()
    for row in rows:
        conn.execute("UPDATE posts SET image_count = ?, video_count = ? WHERE id = ?",
                     (len(post_images(json.loads(row['content_json']))), len(post_videos(json.loads(row['videos_json']))), row['id']))
    _set_meta(conn, 'media_counts_backfilled', '1')
    if rows:
        log_msg(f"[DB] 모아보기용 이미지·동영상 수 계산: 글 {len(rows)}건")

@contextmanager
def _init_process_lock():
    """수집기와 웹서버 컨테이너가 동시에 시작하면 둘 다 스키마 확인·추가와 1회 이전을 하므로, 파일 잠금으로 한쪽씩 하게 함
    (먼저 끝낸 쪽이 만든 칸·표시를 다른 쪽은 이미 있는 것으로 보고 건너뜀)"""
    if fcntl is None:
        yield
        return
    with open(DB_FILE + '.init-lock', 'a') as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)

def init_db():
    """스키마 생성 및 최초 1회 기존 데이터 이전. 여러 번(여러 프로세스에서) 호출해도 안전"""
    global _initialized
    if _initialized:  # 이후 DB를 쓸 때마다 불리므로 끝난 뒤에는 잠금 없이 바로 돌아감
        return
    with _init_lock, _init_process_lock():
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
                _backfill_media_counts(conn)
                _migrate_keywords_to_boards(conn)
                _seed_categories(conn)
                _migrate_site_folders(conn)
                _migrate_top_order(conn)
        # 커밋이 끝난 뒤에만 기존 파일을 정리하여, 이전 도중 실패하면 다음 기동 시 다시 시도
        for path in migrated_files:
            _mark_legacy_migrated(path)
        _initialized = True

def _db():
    init_db()
    return closing(_connect())

# ==========================================
# 카테고리 (수집할 에펨코리아 게시판·디시 갤러리. 처음 한 번 config.BOARD_MAP으로 채우고 이후 관리 화면에서 추가·삭제)
# ==========================================
def _seed_categories(conn):
    """카테고리 표를 1회 채움: BOARD_MAP의 기본 게시판과, 키워드가 이미 등록된 그 밖의 게시판(이름은 mid)"""
    if _get_meta(conn, 'categories_seeded'):
        return
    now = _now()
    seeds = list(BOARD_MAP.items()) + [(r['board'], r['board']) for r in conn.execute("SELECT DISTINCT board FROM keywords")]
    conn.executemany("""
        INSERT OR IGNORE INTO categories(key, name, status, checked_at, created_at) VALUES(?, ?, 'ok', ?, ?)
    """, [(key, name, now, now) for key, name in seeds])
    _set_meta(conn, 'categories_seeded', '1')

def category_names():
    """{mid: 표시 이름} 모든 카테고리 (확인 전·실패 포함, 이름이 비어 있으면 mid)"""
    with _db() as conn:
        return {r['key']: r['name'] or r['key'] for r in conn.execute("SELECT key, name FROM categories ORDER BY rowid")}

def list_categories():
    """관리 화면용 카테고리 목록: 상태, 확인 실패 사유, 등록된 키워드 수와 그 키워드를 쓰는 게시판 이름"""
    with _db() as conn:
        rows = conn.execute("SELECT * FROM categories ORDER BY rowid").fetchall()
        result = []
        for r in rows:
            keyword_count = conn.execute("SELECT COUNT(*) FROM keywords WHERE board = ?", (r['key'],)).fetchone()[0]
            groups = [g['name'] for g in conn.execute("""
                SELECT DISTINCT g.name FROM keyword_group_members m JOIN keyword_groups g ON g.id = m.group_id
                WHERE m.board = ? ORDER BY g.id
            """, (r['key'],))]
            result.append({'key': r['key'], 'name': r['name'] or r['key'], 'site': board_site(r['key']), 'status': r['status'],
                           'message': r['message'], 'checked_at': r['checked_at'],
                           'keyword_count': keyword_count, 'groups': groups})
    return result

def add_category(key, name=''):
    """확인 전(pending) 카테고리 추가. 이미 있으면 ValueError"""
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM categories WHERE key = ?", (key,)).fetchone():
            raise ValueError('이미 등록된 카테고리입니다.')
        conn.execute("INSERT INTO categories(key, name, created_at) VALUES(?, ?, ?)", (key, name, _now()))

def rename_category(key, name):
    """이름 변경. 없는 카테고리면 False"""
    with _db() as conn, conn:
        return conn.execute("UPDATE categories SET name = ? WHERE key = ?", (name, key)).rowcount > 0

def recheck_category(key):
    """확인에 실패한 카테고리를 다음 수집 주기에 다시 확인하도록 되돌림. 없거나 실패 상태가 아니면 False"""
    with _db() as conn, conn:
        return conn.execute("UPDATE categories SET status = 'pending', message = '' WHERE key = ? AND status = 'invalid'",
                            (key,)).rowcount > 0

def delete_category(key):
    """카테고리 삭제. 키워드가 등록되어 있으면(그 키워드를 쓰는 게시판 이름과 함께) ValueError, 없는 카테고리면 False"""
    with _db() as conn, conn:
        groups = [g['name'] for g in conn.execute("""
            SELECT DISTINCT g.name FROM keyword_group_members m JOIN keyword_groups g ON g.id = m.group_id
            WHERE m.board = ? ORDER BY g.id
        """, (key,))]
        if groups:
            raise ValueError(f"키워드가 등록되어 있어 삭제할 수 없습니다. ({', '.join(groups)} 게시판에서 이 카테고리 키워드를 먼저 빼 주세요)")
        if conn.execute("SELECT 1 FROM keywords WHERE board = ?", (key,)).fetchone():
            raise ValueError('키워드가 등록되어 있어 삭제할 수 없습니다.')
        return conn.execute("DELETE FROM categories WHERE key = ?", (key,)).rowcount > 0

# ==========================================
# 사이트 이름·짧은 표시 (관리 화면에서 편집. 저장한 값이 없으면 sites.py의 기본값)
# ==========================================
def site_labels():
    """{site: {'name': 이름, 'short': 짧은 표시}} (예: {'dcinside': {'name': '디시인사이드', 'short': 'DC'}})"""
    with _db() as conn:
        saved = json.loads(_get_meta(conn, 'site_labels') or '{}')
    return {site: {'name': (saved.get(site) or {}).get('name') or SITE_NAMES[site],
                   'short': (saved.get(site) or {}).get('short') or SITE_SHORT[site]} for site in SITE_NAMES}

def set_site_label(site, name, short):
    """사이트 이름·짧은 표시 저장. 없는 사이트면 ValueError"""
    if site not in SITE_NAMES:
        raise ValueError('존재하지 않는 사이트입니다.')
    with _db() as conn, conn:
        saved = json.loads(_get_meta(conn, 'site_labels') or '{}')
        saved[site] = {'name': name, 'short': short}
        _set_meta(conn, 'site_labels', json.dumps(saved, ensure_ascii=False))

def pending_categories():
    """수집기가 확인할 카테고리 mid 목록 (추가한 순서)"""
    with _db() as conn:
        return [r['key'] for r in conn.execute("SELECT key FROM categories WHERE status = 'pending' ORDER BY rowid")]

def set_category_checked(key, ok, page_name='', message=''):
    """확인 결과 기록. 이름이 비어 있으면 게시판 제목(page_name)으로 채움"""
    with _db() as conn, conn:
        conn.execute("""
            UPDATE categories SET status = ?, message = ?, checked_at = ?,
                   name = CASE WHEN name = '' THEN ? ELSE name END
            WHERE key = ?
        """, ('ok' if ok else 'invalid', message, _now(), page_name, key))

# ==========================================
# 키워드 (게시판에 등록된 키워드가 곧 수집 대상. 직접 추가·삭제하지 않고 게시판 저장 시 자동 정리)
# ==========================================
def load_keywords():
    """{board: [keyword, ...]} 형태로 등록 순서대로 반환. 확인을 통과한(ok) 카테고리의 일시정지하지 않은 키워드만 수집 대상"""
    with _db() as conn:
        result = {r['key']: [] for r in conn.execute("SELECT key FROM categories WHERE status = 'ok' ORDER BY rowid")}
        for row in conn.execute("SELECT board, keyword FROM keywords WHERE paused = 0 ORDER BY rowid"):
            if row['board'] in result:
                result[row['board']].append(row['keyword'])
    return result

def _keyword_ignores(conn, board, keyword):
    return [r['phrase'] for r in conn.execute(
        "SELECT phrase FROM keyword_ignores WHERE board = ? AND keyword = ? ORDER BY rowid", (board, keyword))]

def load_keyword_ignores():
    """{(board, keyword): [무시할 표현, ...]} (표현이 있는 키워드만)"""
    result = {}
    with _db() as conn:
        for row in conn.execute("SELECT board, keyword, phrase FROM keyword_ignores ORDER BY rowid"):
            result.setdefault((row['board'], row['keyword']), []).append(row['phrase'])
    return result

def _set_keyword_ignores(conn, board, keyword, phrases):
    """키워드의 무시할 표현을 통째로 바꾸고, 이미 모은 글 중 새 표현 때문에 키워드가 없어진 글을 그 키워드에서 뺌.
    (표현을 빼서 다시 모아야 할 글은 이미 지나간 글이라 되돌리지 않음) 뺀 글 수 반환"""
    from matching import norm, keyword_in_post
    unique = {}
    for phrase in phrases:
        if norm(phrase) and norm(phrase) not in unique:
            unique[norm(phrase)] = phrase.strip()
    old = _keyword_ignores(conn, board, keyword)
    if {norm(p) for p in old} == set(unique):
        return 0
    conn.execute("DELETE FROM keyword_ignores WHERE board = ? AND keyword = ?", (board, keyword))
    # 거른 글은 바뀐 표현으로 다시 판별해야 하므로 잊음 (표현을 빼면 다시 모아질 수 있음)
    conn.execute("DELETE FROM rejected_posts WHERE board = ? AND keyword = ?", (board, keyword))
    conn.executemany("INSERT INTO keyword_ignores(board, keyword, phrase) VALUES(?, ?, ?)",
                     [(board, keyword, p) for p in unique.values()])
    # 무시할 표현 때문에만 빠지는 글 (표현 없이는 키워드가 있던 글)만 정리. 예전 방식으로 모은 다른 글은 건드리지 않음
    removed = []
    for row in conn.execute("""
        SELECT p.id, p.title, b.content_json FROM keyword_posts kp JOIN posts p ON p.id = kp.post_id
        JOIN post_bodies b ON b.post_id = p.id
        WHERE kp.board = ? AND kp.keyword = ?
    """, (board, keyword)).fetchall():
        content = json.loads(row['content_json'])
        if keyword_in_post(keyword, row['title'], content) and not keyword_in_post(keyword, row['title'], content, unique.values()):
            removed.append(row['id'])
    for post_id in removed:
        conn.execute("DELETE FROM keyword_posts WHERE board = ? AND keyword = ? AND post_id = ?", (board, keyword, post_id))
    if removed:
        conn.execute("DELETE FROM posts WHERE id NOT IN (SELECT post_id FROM keyword_posts)")
        conn.execute("DELETE FROM read_posts WHERE post_id NOT IN (SELECT id FROM posts)")
        log_msg(f"[DB] {board}/{keyword} 무시할 표현 적용: 이미 모은 글 {len(removed)}건 뺌")
    return len(removed)

def _drop_orphan_keywords(conn):
    """어느 게시판에도 속하지 않게 된 키워드와 그 수집 데이터를 삭제하고 삭제한 (board, keyword) 목록 반환"""
    orphans = [(r['board'], r['keyword']) for r in conn.execute("""
        SELECT board, keyword FROM keywords
        WHERE (board, keyword) NOT IN (SELECT board, keyword FROM keyword_group_members)
    """).fetchall()]
    for board, keyword in orphans:
        conn.execute("DELETE FROM keywords WHERE board = ? AND keyword = ?", (board, keyword))
        conn.execute("DELETE FROM keyword_posts WHERE board = ? AND keyword = ?", (board, keyword))
        conn.execute("DELETE FROM keyword_ignores WHERE board = ? AND keyword = ?", (board, keyword))
        conn.execute("DELETE FROM rejected_posts WHERE board = ? AND keyword = ?", (board, keyword))
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
def _feed_from(group_id=None, folder_id=None):
    """피드 글 연결의 FROM 절과 파라미터. group_id가 없으면 모든 게시판(등록 키워드 전체),
    folder_id가 있으면 그 묶음의 모든 게시판"""
    sql = """
        FROM keyword_posts kp
        JOIN keywords k ON k.board = kp.board AND k.keyword = kp.keyword
    """
    if folder_id is not None:
        # 묶음 안의 게시판끼리 같은 키워드를 써도 글이 두 번 잡히지 않게 키워드를 한 번씩만
        return sql + """JOIN (SELECT DISTINCT board, keyword FROM keyword_group_members
                      WHERE group_id IN (SELECT id FROM keyword_groups WHERE folder_id = ?)) fm
                ON fm.board = kp.board AND fm.keyword = kp.keyword
        """, (folder_id,)
    if group_id is None:
        return sql, ()
    return sql + "JOIN keyword_group_members gm ON gm.board = kp.board AND gm.keyword = kp.keyword AND gm.group_id = ?\n", (group_id,)

def _feed_summary(conn, id_limit, group_id=None, folder_id=None):
    """중복 제거한 글 수, 동영상 글 수, 안 읽은 새 글 수(전부)와 최신순 ID(최대 id_limit개),
    새 댓글이 달린 글 수와 최근 댓글순 ID(최대 id_limit개), 최신 글 날짜"""
    base, params = _feed_from(group_id, folder_id)
    # 보기별 글 수를 한 번에 셈 (글마다 작은 칸만 읽음)
    total, video_count, image_count, deleted_count, saved_count = conn.execute(f"""
        SELECT COUNT(DISTINCT kp.post_id),
               COUNT(DISTINCT CASE WHEN {_HAS_VIDEO_SQL} THEN kp.post_id END),
               COUNT(DISTINCT CASE WHEN {_HAS_IMAGE_SQL} THEN kp.post_id END),
               COUNT(DISTINCT CASE WHEN p.is_deleted = 1 THEN kp.post_id END),
               COUNT(DISTINCT sp.post_id)
        {base} JOIN posts p ON p.id = kp.post_id
        LEFT JOIN saved_posts sp ON sp.post_id = kp.post_id
    """, params).fetchone()
    comment_ids = _new_comment_ids(conn, group_id, folder_id)
    unread = conn.execute(f"""
        SELECT kp.post_id, MAX(kp.rowid) AS last_rowid {base}
        LEFT JOIN read_posts rp ON rp.post_id = kp.post_id
        WHERE {_UNREAD_SQL}
        GROUP BY kp.post_id ORDER BY last_rowid DESC
    """, params).fetchall()
    latest = conn.execute(f"""
        SELECT p.date {base}
        JOIN posts p ON p.id = kp.post_id
        ORDER BY kp.rowid DESC LIMIT 1
    """, params).fetchone()
    return {
        'total': total,
        'video_count': video_count,
        'image_count': image_count,
        'deleted_count': deleted_count,
        'saved_count': saved_count,
        'unread_count': len(unread),
        'unread_ids': [r['post_id'] for r in unread[:id_limit]],
        'comment_count': len(comment_ids),
        'comment_ids': comment_ids[:id_limit],
        'latest_date': latest['date'] if latest else ''
    }

def feed_summary(id_limit=500):
    """모든 게시판을 합친 통합 피드 요약"""
    with _db() as conn:
        return _feed_summary(conn, id_limit)

def list_groups(id_limit=500):
    """게시판 목록: 등록 키워드, 알림 설정, 중복 제거한 글 수, 안 읽은 새 글 수·ID, 최신 글 날짜"""
    groups = []
    with _db() as conn:
        for g in conn.execute("""
            SELECT id, site, name, alert, video_alert, digest, folder_id, position FROM keyword_groups ORDER BY position, id
        """).fetchall():
            members = [dict(board=r['board'], keyword=r['keyword'], paused=bool(r['paused']),
                            ignores=_keyword_ignores(conn, r['board'], r['keyword']))
                       for r in conn.execute("""
                SELECT m.board, m.keyword, k.paused FROM keyword_group_members m
                JOIN keywords k ON k.board = m.board AND k.keyword = m.keyword
                WHERE m.group_id = ? ORDER BY k.rowid
            """, (g['id'],)).fetchall()]
            # 게시판은 한 사이트의 키워드만 담음 (save_group에서 검사). 사이드바에서 사이트별로 묶어 보여줌
            groups.append({'id': g['id'], 'name': g['name'], 'site': g['site'], 'members': members,
                           'alert': bool(g['alert']), 'video_alert': bool(g['video_alert']), 'digest': bool(g['digest']),
                           'folder_id': g['folder_id'], 'position': g['position'],
                           **_feed_summary(conn, id_limit, g['id'])})
    return groups

def _site_label(labels, site):
    return '여러 사이트' if site == MULTI_SITE else labels[site]['name']

def save_group(group_id, name, members, merge_ids=(), folder_id=None):
    """게시판 생성(group_id=None) 또는 수정. 새 키워드는 수집 대상으로 등록하고,
    어느 게시판에도 남지 않은 키워드는 수집 데이터와 함께 삭제. (게시판 ID, 삭제된 키워드 목록) 반환.
    member에 ignores(무시할 표현 목록)가 있으면 그 키워드의 표현을 바꿈 (키워드에 붙으므로 같은 키워드를 쓰는 게시판 모두에 적용).
    paused가 있으면 그 키워드의 일시정지를 바꿈 (마찬가지로 같은 키워드를 쓰는 게시판 모두에 적용).
    게시판의 사이트는 등록한 키워드의 사이트(여러 사이트면 MULTI_SITE)이며, 이름은 같은 사이트 안에서만 겹치지 않으면 됨.
    merge_ids의 게시판은 저장한 뒤 지움 (그 게시판의 키워드를 이 게시판으로 옮겨 합칠 때, 알림 설정은 이 게시판 것).
    새 게시판은 folder_id 묶음의 맨 뒤에 둠 (없으면 묶음 없이). 기존 게시판의 묶음·순서는 arrange_group으로 바꿈.
    이름 중복 등은 ValueError"""
    pairs = list(dict.fromkeys((m['board'], m['keyword']) for m in members))
    if not pairs:
        raise ValueError('키워드를 하나 이상 등록해 주세요.')
    labels = site_labels()
    sites = {board_site(b) for b, _ in pairs}
    site = sites.pop() if len(sites) == 1 else MULTI_SITE
    merge_ids = [i for i in dict.fromkeys(merge_ids) if i != group_id]
    with _db() as conn, conn:
        if group_id is not None and not conn.execute("SELECT 1 FROM keyword_groups WHERE id = ?", (group_id,)).fetchone():
            raise ValueError('존재하지 않는 게시판입니다.')
        for merge_id in merge_ids:
            if not conn.execute("SELECT 1 FROM keyword_groups WHERE id = ?", (merge_id,)).fetchone():
                raise ValueError('합칠 게시판이 없습니다.')
        # 합쳐서 지울 게시판과는 이름이 같아도 됨 (FM 싼타페 + DC 싼타페 → 싼타페)
        clash = conn.execute(f"""
            SELECT id FROM keyword_groups WHERE site = ? AND name = ? AND id != ?
            {f"AND id NOT IN ({','.join('?' * len(merge_ids))})" if merge_ids else ''}
        """, (site, name, group_id or -1, *merge_ids)).fetchone()
        if clash:
            raise ValueError(f"{_site_label(labels, site)}에 같은 이름의 게시판이 이미 있습니다.")
        for merge_id in merge_ids:
            conn.execute("DELETE FROM keyword_group_members WHERE group_id = ?", (merge_id,))
            conn.execute("DELETE FROM keyword_groups WHERE id = ?", (merge_id,))
        if group_id is None:
            if folder_id is not None and not conn.execute("SELECT 1 FROM group_folders WHERE id = ?", (folder_id,)).fetchone():
                raise ValueError('존재하지 않는 묶음입니다.')
            position = _end_position(conn, folder_id)
            group_id = conn.execute("INSERT INTO keyword_groups(site, name, created_at, folder_id, position) VALUES(?, ?, ?, ?, ?)",
                                    (site, name, _now(), folder_id, position)).lastrowid
        else:
            conn.execute("UPDATE keyword_groups SET site = ?, name = ? WHERE id = ?", (site, name, group_id))
            conn.execute("DELETE FROM keyword_group_members WHERE group_id = ?", (group_id,))
        conn.executemany("INSERT OR IGNORE INTO keywords(board, keyword) VALUES(?, ?)", pairs)
        conn.executemany("INSERT OR IGNORE INTO keyword_group_members(group_id, board, keyword) VALUES(?, ?, ?)",
                         [(group_id, b, k) for b, k in pairs])
        for m in members:
            if 'ignores' in m:
                _set_keyword_ignores(conn, m['board'], m['keyword'], m['ignores'])
            if 'paused' in m:
                conn.execute("UPDATE keywords SET paused = ? WHERE board = ? AND keyword = ?",
                             (int(bool(m['paused'])), m['board'], m['keyword']))
        return group_id, _drop_orphan_keywords(conn)

# ==========================================
# 묶음 (사이드바에서 게시판을 묶어 보여 줌. 묶음 제목을 누르면 묶음 안 모든 게시판의 글)
# ==========================================
def _migrate_site_folders(conn):
    """묶음을 도입하기 전 사이드바의 사이트별 묶음을 1회 묶음으로 옮김 (여러 사이트 게시판은 '통합').
    게시판이 한 사이트뿐이면 사이트 묶음이 보이지 않았으므로 묶음을 만들지 않음"""
    if _get_meta(conn, 'site_folders_migrated'):
        return
    names = {MULTI_SITE: '통합', **SITE_NAMES}
    sites = [r['site'] for r in conn.execute("SELECT site FROM keyword_groups GROUP BY site ORDER BY MIN(position), MIN(id)")]
    if len(sites) < 2:
        sites = []
    for position, site in enumerate(sites, 1):
        folder_id = conn.execute("INSERT INTO group_folders(name, position, created_at) VALUES(?, ?, ?)",
                                 (names.get(site, site), position, _now())).lastrowid
        conn.execute("UPDATE keyword_groups SET folder_id = ? WHERE site = ?", (folder_id, site))
    _set_meta(conn, 'site_folders_migrated', '1')
    if sites:
        log_msg(f"[DB] 사이트별 게시판 묶음 {len(sites)}개를 묶음으로 이전")

def list_folders(id_limit=500):
    """묶음 목록 (표시 순서): 이름과 묶음 안 모든 게시판을 합친 피드 요약 (게시판과 같은 형태)"""
    with _db() as conn:
        return [{'id': r['id'], 'name': r['name'], 'position': r['position'], **_feed_summary(conn, id_limit, folder_id=r['id'])}
                for r in conn.execute("SELECT id, name, position FROM group_folders ORDER BY position, id").fetchall()]

def save_folder(folder_id, name):
    """묶음 만들기(folder_id=None, 맨 뒤에) 또는 이름 바꾸기. 묶음 ID 반환, 이름 중복·없는 묶음은 ValueError"""
    with _db() as conn, conn:
        if conn.execute("SELECT 1 FROM group_folders WHERE name = ? AND id != ?", (name, folder_id or -1)).fetchone():
            raise ValueError('같은 이름의 묶음이 이미 있습니다.')
        if folder_id is None:
            position = _end_position(conn, None)
            return conn.execute("INSERT INTO group_folders(name, position, created_at) VALUES(?, ?, ?)",
                                (name, position, _now())).lastrowid
        if conn.execute("UPDATE group_folders SET name = ? WHERE id = ?", (name, folder_id)).rowcount == 0:
            raise ValueError('존재하지 않는 묶음입니다.')
        return folder_id

def delete_folder(folder_id):
    """묶음 삭제. 안에 있던 게시판은 지우지 않고 묶음 없이 둠. 없는 묶음이면 False"""
    with _db() as conn, conn:
        # 안의 게시판은 묶음이 있던 자리에 (묶음 안 순서대로) 놓음
        items = []
        for item in _top_items(conn):
            if item == ('f', folder_id):
                items += [('g', r[0]) for r in conn.execute(
                    "SELECT id FROM keyword_groups WHERE folder_id = ? ORDER BY position, id", (folder_id,))]
            else:
                items.append(item)
        conn.execute("UPDATE keyword_groups SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
        deleted = conn.execute("DELETE FROM group_folders WHERE id = ?", (folder_id,)).rowcount > 0
        _renumber_top(conn, [i for i in items if i != ('f', folder_id)])
        return deleted

def _move(conn, table, item_id, direction, where='1 = 1', params=()):
    """같은 범위(where) 안에서 항목을 한 칸 위('up')·아래('down')로 옮기고 순서를 1부터 다시 매김"""
    ids = [r[0] for r in conn.execute(f"SELECT id FROM {table} WHERE {where} ORDER BY position, id", params)]
    if item_id not in ids:
        return
    i = ids.index(item_id)
    j = i - 1 if direction == 'up' else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
    conn.executemany(f"UPDATE {table} SET position = ? WHERE id = ?", [(n, item_id_) for n, item_id_ in enumerate(ids, 1)])

# 맨 위 단계(사이드바에서 '전체' 아래)의 순서: 묶음 없는 게시판과 묶음을 한 줄로 섞어 position으로 정렬.
# 묶음 안 게시판의 position은 그 묶음 안 순서
def _top_items(conn):
    """맨 위 단계 항목을 표시 순서로: ('g', 게시판 ID) 또는 ('f', 묶음 ID). 같은 position이면 게시판 먼저"""
    rows = [(r[1], 0, r[0], 'g') for r in conn.execute("SELECT id, position FROM keyword_groups WHERE folder_id IS NULL")]
    rows += [(r[1], 1, r[0], 'f') for r in conn.execute("SELECT id, position FROM group_folders")]
    return [(kind, item_id) for _, _, item_id, kind in sorted(rows)]

def _renumber_top(conn, items):
    for n, (kind, item_id) in enumerate(items, 1):
        table = 'keyword_groups' if kind == 'g' else 'group_folders'
        conn.execute(f"UPDATE {table} SET position = ? WHERE id = ?", (n, item_id))

def _end_position(conn, folder_id):
    """folder_id 묶음 안(None이면 맨 위 단계)의 맨 뒤 position"""
    if folder_id is not None:
        return conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM keyword_groups WHERE folder_id = ?", (folder_id,)).fetchone()[0]
    return max(conn.execute("SELECT COALESCE(MAX(position), 0) FROM keyword_groups WHERE folder_id IS NULL").fetchone()[0],
               conn.execute("SELECT COALESCE(MAX(position), 0) FROM group_folders").fetchone()[0]) + 1

def _move_top(conn, item, direction):
    """맨 위 단계에서 한 칸 옮김. 사이드바에 보이지 않는 빈 묶음은 건너뜀 (옮기는 것이 빈 묶음이면 그대로 한 칸)"""
    items = _top_items(conn)
    if item not in items:
        return
    filled = {r[0] for r in conn.execute("SELECT DISTINCT folder_id FROM keyword_groups WHERE folder_id IS NOT NULL")}
    hidden = lambda t: t[0] == 'f' and t[1] not in filled
    step = -1 if direction == 'up' else 1
    i = items.index(item)
    j = i + step
    while not hidden(item) and 0 <= j < len(items) and hidden(items[j]):
        j += step
    if 0 <= j < len(items):
        items.pop(i)
        items.insert(j, item)
    _renumber_top(conn, items)

def _migrate_top_order(conn):
    """묶음 없는 게시판과 묶음을 한 줄 순서로 합치기 전에는 묶음 없는 게시판이 늘 묶음보다 앞이었으므로,
    1회 그 순서대로 번호를 다시 매김"""
    if _get_meta(conn, 'top_order_merged'):
        return
    loose = [('g', r[0]) for r in conn.execute("SELECT id FROM keyword_groups WHERE folder_id IS NULL ORDER BY position, id")]
    folders = [('f', r[0]) for r in conn.execute("SELECT id FROM group_folders ORDER BY position, id")]
    _renumber_top(conn, loose + folders)
    _set_meta(conn, 'top_order_merged', '1')

def move_folder(folder_id, direction):
    """묶음을 맨 위 단계(묶음 없는 게시판과 함께)에서 한 칸 옮김. 없는 묶음이면 False"""
    with _db() as conn, conn:
        if not conn.execute("SELECT 1 FROM group_folders WHERE id = ?", (folder_id,)).fetchone():
            return False
        _move_top(conn, ('f', folder_id), direction)
        return True

def arrange_group(group_id, folder_id=..., direction=None):
    """게시판을 다른 묶음으로 옮기거나(folder_id, None이면 묶음 없음, 옮긴 묶음의 맨 뒤로) 한 칸 옮김(direction).
    묶음 안 게시판은 그 묶음 안에서, 묶음 없는 게시판은 묶음들과 섞인 맨 위 단계에서 옮김.
    게시판 이름 반환, 없는 게시판은 None, 없는 묶음은 ValueError"""
    with _db() as conn, conn:
        row = conn.execute("SELECT name, folder_id FROM keyword_groups WHERE id = ?", (group_id,)).fetchone()
        if not row:
            return None
        if folder_id is not ... and folder_id != row['folder_id']:
            if folder_id is not None and not conn.execute("SELECT 1 FROM group_folders WHERE id = ?", (folder_id,)).fetchone():
                raise ValueError('존재하지 않는 묶음입니다.')
            position = _end_position(conn, folder_id)
            conn.execute("UPDATE keyword_groups SET folder_id = ?, position = ? WHERE id = ?", (folder_id, position, group_id))
        if direction:
            current = conn.execute("SELECT folder_id FROM keyword_groups WHERE id = ?", (group_id,)).fetchone()['folder_id']
            if current is None:   # 묶음 없는 게시판은 묶음들 사이로도 옮김
                _move_top(conn, ('g', group_id), direction)
            else:
                _move(conn, 'keyword_groups', group_id, direction, 'folder_id = ?', (current,))
        return row['name']

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
    """게시판 알림(전체·동영상·하루 요약) 켜기·끄기. 게시판 이름 반환, 없는 게시판이면 None"""
    if alert_type not in ('alert', 'video_alert', 'digest'):
        raise ValueError(f"지원하지 않는 알림 종류: {alert_type}")
    with _db() as conn, conn:
        row = conn.execute("SELECT name FROM keyword_groups WHERE id = ?", (group_id,)).fetchone()
        if not row:
            return None
        conn.execute(f"UPDATE keyword_groups SET {alert_type} = ? WHERE id = ?", (int(bool(enabled)), group_id))
        return row['name']

SAVED_COMMENT_ALERT_META = 'saved_comment_alert'

def saved_comment_alert():
    """보관한 글에 새 댓글이 달리면 텔레그램으로 알릴지 (기본 켬)"""
    with _db() as conn:
        return _get_meta(conn, SAVED_COMMENT_ALERT_META) != '0'

def set_saved_comment_alert(enabled):
    with _db() as conn, conn:
        _set_meta(conn, SAVED_COMMENT_ALERT_META, '1' if enabled else '0')

def digest_groups():
    """하루 요약을 켠 게시판 [{'id', 'name'}]"""
    with _db() as conn:
        return [dict(r) for r in conn.execute("SELECT id, name FROM keyword_groups WHERE digest = 1 ORDER BY id")]

def digest_posts(group_id, since, limit=5):
    """게시판에 since 이후 새로 모인 글 수와, 그중 추천·댓글이 많은 글 limit개 (원문이 삭제된 글 제외)"""
    base, params = _feed_from(group_id)
    with _db() as conn:
        rows = conn.execute(f"""
            SELECT p.id, p.title, p.link, p.votes, p.comment_count, p.views
            {base} JOIN posts p ON p.id = kp.post_id
            WHERE kp.is_new = 1 AND kp.matched_at >= ? AND p.is_deleted = 0
            GROUP BY p.id
        """, params + (since,)).fetchall()
    def score(r):
        num = lambda v: int(str(v or 0).replace(',', '')) if str(v or 0).replace(',', '').isdigit() else 0
        return (num(r['votes']) + num(r['comment_count']), num(r['views']))
    top = sorted(rows, key=score, reverse=True)[:limit]
    return len(rows), [dict(r) for r in top]

# ==========================================
# 보내지 못한 텔레그램 알림 (notifier)
# ==========================================
def add_pending_alert(payload, what):
    with _db() as conn, conn:
        conn.execute("INSERT INTO pending_alerts(payload, what, created_at) VALUES(?, ?, ?)", (payload, what, _now()))

def pending_alerts(limit):
    """오래된 것부터 limit개 [{id, payload, what, attempts, created_at}]"""
    with _db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM pending_alerts ORDER BY id LIMIT ?", (limit,))]

def delete_pending_alert(alert_id):
    with _db() as conn, conn:
        conn.execute("DELETE FROM pending_alerts WHERE id = ?", (alert_id,))

def bump_pending_alert(alert_id):
    with _db() as conn, conn:
        conn.execute("UPDATE pending_alerts SET attempts = attempts + 1 WHERE id = ?", (alert_id,))

def get_meta(key):
    with _db() as conn:
        return _get_meta(conn, key)

def set_meta(key, value):
    with _db() as conn, conn:
        _set_meta(conn, key, value)

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

def _carry_comment_first_seen(old_comments, new_comments, now, old_all_pages=True):
    """다시 수집한 댓글에 처음 수집된 시각(first_seen)을 이어붙임. 이전에 없던 댓글만 지금 시각이 됨
    (first_seen이 없는 예전 댓글은 '예전부터 있던 댓글'로 남겨 새 댓글로 표시되지 않게 함).
    첫 화면의 댓글 페이지만 저장하던 글(old_all_pages=False)을 처음으로 모든 페이지까지 읽었을 때, 다른 페이지(other_page)에서
    처음 본 댓글은 원래 있던 댓글이므로 새 댓글로 표시하지 않음. 새 댓글로 표시한 댓글 목록을 돌려줌"""
    added = []
    remaining = {}
    for c in old_comments:
        remaining.setdefault(_comment_key(c), []).append(c.get('first_seen'))
    for c in new_comments:
        seen = remaining.get(_comment_key(c))
        if seen:
            c['first_seen'] = seen.pop(0)
        else:
            c['first_seen'] = None if c.get('other_page') and not old_all_pages else now
            if c['first_seen']:
                added.append(c)
    return added

def _upsert_post(conn, post):
    """글 저장. 이미 있던 글이면 이번에 처음 본 댓글 목록을 돌려줌"""
    now = _now()
    existing = conn.execute("""
        SELECT b.comments_json, p.all_comment_pages FROM posts p JOIN post_bodies b ON b.post_id = p.id WHERE p.id = ?
    """, (str(post['id']),)).fetchone()
    comments = [dict(c) for c in post.get('comments', [])]
    added = []
    if existing:
        added = _carry_comment_first_seen(json.loads(existing['comments_json']), comments, now, bool(existing['all_comment_pages']))
    else:
        for c in comments:
            c.setdefault('first_seen', now)
    for c in comments:
        c.pop('other_page', None)
    content_json = json.dumps(post.get('content', []), ensure_ascii=False)
    videos = post.get('videos', [])
    last_comment_at = max((c['first_seen'] for c in comments if c.get('first_seen')), default=None)
    conn.execute("""
        INSERT INTO posts(id, title, author, date, views, votes, comment_count, link, list_comment_count, all_comment_pages,
                          has_video, has_image, image_count, video_count, last_comment_at, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title, author = excluded.author, date = excluded.date,
            views = excluded.views, votes = excluded.votes, comment_count = excluded.comment_count,
            link = excluded.link,
            list_comment_count = COALESCE(excluded.list_comment_count, posts.list_comment_count),
            all_comment_pages = 1,
            has_video = excluded.has_video, has_image = excluded.has_image,
            image_count = excluded.image_count, video_count = excluded.video_count, last_comment_at = excluded.last_comment_at,
            updated_at = excluded.updated_at
    """, (
        str(post['id']), post.get('title', ''), post.get('author', ''), post.get('date', ''),
        str(post.get('views', '0')), str(post.get('votes', '0')), str(post.get('comment_count', '0')),
        post.get('link', ''), post.get('list_comment_count'),
        int(bool(videos)), int(_has_image(content_json)),
        len(post_images(post.get('content', []))), len(post_videos(videos)), last_comment_at,
        now, now
    ))
    conn.execute("""
        INSERT INTO post_bodies(post_id, videos_json, content_json, comments_json, search_text) VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            videos_json = excluded.videos_json, content_json = excluded.content_json,
            comments_json = excluded.comments_json, search_text = excluded.search_text
    """, (
        str(post['id']), json.dumps(videos, ensure_ascii=False), content_json,
        json.dumps(comments, ensure_ascii=False), _search_text(dict(post, comments=comments))
    ))
    return added

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

# 처음 등록할 때 최신 글 1개만 저장하던 시절에 등록한 디시 키워드는, 기동 후 첫 수집 때 목록 첫 페이지의 글로 1회 채움
# (fmkorea-scraper.fill_first_page). 채운 키워드를 'board|keyword' 목록으로 기억
FIRST_PAGE_FILLED_META = 'dc_first_page_filled'

def first_page_filled_keys():
    with _db() as conn:
        return set(json.loads(_get_meta(conn, FIRST_PAGE_FILLED_META) or '[]'))

def mark_first_page_filled(board, keyword):
    with _db() as conn, conn:
        done = set(json.loads(_get_meta(conn, FIRST_PAGE_FILLED_META) or '[]'))
        done.add(f"{board}|{keyword}")
        _set_meta(conn, FIRST_PAGE_FILLED_META, json.dumps(sorted(done), ensure_ascii=False))

def fill_keyword_posts(board, keyword, ordered_ids, new_posts):
    """키워드의 글 연결을 ordered_ids(오래된 글 → 최신 글) 순서로 다시 넣음. new_posts {id: 글}은 새로 저장하고 이미 본 글로,
    이미 연결된 글은 원래의 새 글 여부·수집 시각을 유지. 수집 순서(rowid)가 목록 순서와 같아지도록 기존 연결도 지웠다가 다시 넣음"""
    with _db() as conn, conn:
        for post_id in ordered_ids:
            if post_id in new_posts:
                _upsert_post(conn, new_posts[post_id])
                is_new, matched_at = 0, _now()
            else:
                row = conn.execute("SELECT is_new, matched_at FROM keyword_posts WHERE board = ? AND keyword = ? AND post_id = ?",
                                   (board, keyword, post_id)).fetchone()
                if not row:
                    continue
                is_new, matched_at = row['is_new'], row['matched_at']
                conn.execute("DELETE FROM keyword_posts WHERE board = ? AND keyword = ? AND post_id = ?", (board, keyword, post_id))
            conn.execute("INSERT INTO keyword_posts(board, keyword, post_id, is_new, matched_at) VALUES(?, ?, ?, ?, ?)",
                         (board, keyword, post_id, is_new, matched_at))

def update_post(post):
    """동기화로 갱신된 글 내용(조회수·댓글 등)을 저장하고 이번에 처음 본 댓글 목록을 돌려줌"""
    with _db() as conn, conn:
        return _upsert_post(conn, post)

def is_post_saved(post_id):
    with _db() as conn:
        return conn.execute("SELECT 1 FROM saved_posts WHERE post_id = ?", (str(post_id),)).fetchone() is not None

def saved_posts_to_check(minutes, exclude_ids, limit):
    """새 댓글을 확인할 보관한 글: 원문이 남아 있고, 마지막 확인이 minutes분 넘게 지났고, exclude_ids(키워드 목록으로 이미
    감시하는 글)가 아닌 글을 오래 확인 안 한 순으로 limit개. 상세 페이지를 여는 데 필요한 칸만"""
    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
    with _db() as conn:
        rows = conn.execute("""
            SELECT p.id, p.title, p.author, p.date, p.link, p.list_comment_count FROM saved_posts sp
            JOIN posts p ON p.id = sp.post_id
            WHERE p.is_deleted = 0 AND (sp.checked_at IS NULL OR sp.checked_at < ?)
            ORDER BY COALESCE(sp.checked_at, '') , sp.saved_at
        """, (cutoff,)).fetchall()
    return [dict(r) for r in rows if r['id'] not in exclude_ids][:limit]

def mark_saved_checked(post_id):
    with _db() as conn, conn:
        conn.execute("UPDATE saved_posts SET checked_at = ? WHERE post_id = ?", (_now(), str(post_id)))

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
        'content': json.loads(row['content_json']), 'videos': json.loads(row['videos_json']),
        'comments': json.loads(row['comments_json']), 'is_new': bool(row['is_new']),
        'list_comment_count': row['list_comment_count'],
        'read_at': row['read_at'] if 'read_at' in keys else None,
        'is_saved': bool(row['saved_at']) if 'saved_at' in keys else False
    }
    if 'keyword_links' in keys and row['keyword_links']:
        # 통합 피드: 이 글이 걸린 키워드 목록 [{board, keyword}]
        post['keywords'] = [dict(zip(('board', 'keyword'), link.split('\x1f', 1))) for link in row['keyword_links'].split('\x1e')]
    if row['is_deleted']:
        post['is_deleted'] = True
    return post

_HAS_VIDEO_SQL = "p.has_video = 1"
# 첨부 이미지가 있는 글: 에펨코리아 첨부(/files/attach/)나 수집할 때 저장한 디시 이미지(/images/dc-) 본문 img
# (이모티콘·아이콘·링크 미리보기 그림만 있는 글은 빼려고 첨부 경로로 판별)
_HAS_IMAGE_SQL = "p.has_image = 1"
# 글 표를 다시 만들 때 본문 JSON에서 이미지 여부를 계산하는 식 (_has_image와 같은 기준, LIKE는 영문 대소문자 무시)
_HAS_IMAGE_JSON_SQL = ("(content_json LIKE '%<img%' AND "
                       "(content_json LIKE '%/files/attach/%' OR content_json LIKE '%/images/dc-%'))")

def _has_image(content_json):
    lowered = content_json.lower()
    return '<img' in lowered and ('/files/attach/' in lowered or '/images/dc-' in lowered)

# 모아보기에 보일 이미지: 본문 img 중 에펨코리아 첨부(/files/attach/)와 수집할 때 저장한 디시 이미지(/images/글ID/...)
# (이모티콘·아이콘·링크 미리보기 그림은 뺌)
_IMG_SRC_RE = re.compile(r'<img\b[^>]*?\ssrc="([^"]+)"', re.I)
_MEDIA_IMAGE_RE = re.compile(r'(https?://[^/]+(/[^?#]*)?/files/attach/|/images/[a-z0-9_-]+/)', re.I)
_YOUTUBE_EMBED_RE = re.compile(r'youtube(?:-nocookie)?\.com/embed/([\w-]{6,})')

def post_images(content):
    """본문 블록에서 모아보기용 이미지 주소 (중복 제외, 본문 순서)"""
    urls = []
    for block in content or []:
        for src in _IMG_SRC_RE.findall(str(block)):
            src = html.unescape(src)
            if src.startswith('//'):
                src = 'https:' + src
            if _MEDIA_IMAGE_RE.match(src) and src not in urls:
                urls.append(src)
    return urls

def post_videos(videos):
    """동영상 목록을 모아보기 항목으로: 유튜브(미리보기 이미지 있음)·동영상 파일·그 밖의 재생 화면(iframe)"""
    items = []
    for src in videos or []:
        if not re.match(r'https?://', src or ''):
            continue
        youtube = _YOUTUBE_EMBED_RE.search(src)
        if youtube:
            items.append({'type': 'youtube', 'src': src, 'thumb': f'https://i.ytimg.com/vi/{youtube.group(1)}/hqdefault.jpg'})
        else:
            items.append({'type': 'file' if re.search(r'\.(mp4|webm|mov)([?#]|$)', src, re.I) else 'embed', 'src': src})
    return items

# 인기순 점수: 추천 수 + 댓글 수 (쉼표가 든 숫자 문자열)
_POPULAR_SQL = ("(CAST(REPLACE(p.votes, ',', '') AS INTEGER) + "
                "CAST(REPLACE(p.comment_count, ',', '') AS INTEGER))")

def _search_conditions(query):
    """검색어를 공백으로 나눠 모든 단어가 포함된 글만 (대소문자 무시, LIKE 특수문자 이스케이프)"""
    terms = [t for t in (query or '').lower().split() if t][:5]
    sql = ''.join(" AND b.search_text LIKE ? ESCAPE '\\'" for _ in terms)
    params = tuple('%' + t.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%' for t in terms)
    return sql, params

def recent_keyword_posts(board, keyword, limit):
    """수집기가 매 주기 비교에 쓰는 키워드별 최근 글 (최신순). 본문·댓글 JSON은 읽지 않고
    새 글 판별·목록 값 비교·상세 페이지 재요청에 필요한 칸만 반환"""
    with _db() as conn:
        rows = conn.execute("""
            SELECT p.id, p.title, p.author, p.date, p.link, p.views, p.votes, p.comment_count,
                   p.list_comment_count, p.is_deleted
            FROM keyword_posts kp JOIN posts p ON p.id = kp.post_id
            WHERE kp.board = ? AND kp.keyword = ?
            ORDER BY kp.rowid DESC LIMIT ?
        """, (board, keyword, limit)).fetchall()
    return [dict(r, is_deleted=bool(r['is_deleted'])) for r in rows]

# 안 읽은 새 글: 새 글로 수집됐고 아직 읽음 기록이 없는 글
_UNREAD_SQL = "kp.is_new = 1 AND rp.read_at IS NULL"

def query_all_posts(offset=0, limit=10, video_only=False, query=None, group_id=None, unread_since=None, deleted_only=False,
                    image_only=False, saved_only=False, folder_id=None, popular=False, since=None):
    """게시판에 등록된 키워드의 글을 한 번씩만(중복 제거) 최신 수집순으로 조회.
    group_id가 있으면 그 게시판만, folder_id가 있으면 그 묶음의 게시판만, query가 있으면 검색 결과.
    unread_since가 있으면 안 읽은 새 글만: 그 시각 이후에 읽은 글은 계속 포함해
    보는 도중 읽음 처리가 되어도 페이지가 밀리지 않게 함.
    deleted_only면 원문이 삭제된 글만, 최근 삭제 순 (삭제된 글은 더 갱신하지 않으므로 updated_at이 삭제 확인 시각).
    saved_only면 보관함(별표를 단 글)만, 최근 보관 순.
    popular면 추천+댓글이 많은 순(보기의 순서보다 우선), since가 있으면 그 시각 이후 처음 수집한 글만"""
    search_sql, search_params = _search_conditions(query)
    feed_sql, params = _feed_from(group_id, folder_id)
    params += search_params
    # 수집 기간·안 읽은 글 조건
    filter_sql = ''
    if since is not None:
        filter_sql += "AND p.created_at >= ? "
        params += (since,)
    if unread_since is not None:
        filter_sql += "AND kp.is_new = 1 AND (rp.read_at IS NULL OR rp.first_read_at > ?)"
        params += (unread_since,)
    base = f"""
        {feed_sql}
        JOIN posts p ON p.id = kp.post_id
        {'JOIN post_bodies b ON b.post_id = p.id' if search_sql else ''}
        LEFT JOIN read_posts rp ON rp.post_id = p.id
        LEFT JOIN saved_posts sp ON sp.post_id = p.id
        WHERE 1 = 1 {f'AND {_HAS_VIDEO_SQL}' if video_only else ''} {f'AND {_HAS_IMAGE_SQL}' if image_only else ''}
            {'AND p.is_deleted = 1' if deleted_only else ''} {'AND sp.saved_at IS NOT NULL' if saved_only else ''}
            {search_sql} {filter_sql}
    """
    order = (f'{_POPULAR_SQL} DESC, last_rowid DESC' if popular else
             'p.updated_at DESC, last_rowid DESC' if deleted_only else
             'sp.saved_at DESC, last_rowid DESC' if saved_only else 'last_rowid DESC')
    with _db() as conn:
        total = conn.execute(f"SELECT COUNT(DISTINCT p.id) {base}", params).fetchone()[0]
        # 한 페이지의 글을 작은 칸만으로 먼저 고르고, 본문·댓글은 그 글들만 읽음 (모든 글의 본문을 읽지 않게)
        page = conn.execute(f"""
            SELECT p.id, MAX(kp.is_new) AS is_new, MAX(kp.rowid) AS last_rowid,
                   GROUP_CONCAT(kp.board || char(31) || kp.keyword, char(30)) AS keyword_links
            {base}
            GROUP BY p.id
            ORDER BY {order} LIMIT ? OFFSET ?
        """, params + (limit, offset)).fetchall()
        full = {r['id']: dict(r) for r in conn.execute(f"""
            SELECT p.*, b.videos_json, b.content_json, b.comments_json, rp.read_at, sp.saved_at FROM posts p
            JOIN post_bodies b ON b.post_id = p.id
            LEFT JOIN read_posts rp ON rp.post_id = p.id
            LEFT JOIN saved_posts sp ON sp.post_id = p.id
            WHERE p.id IN ({','.join('?' * len(page))})
        """, [r['id'] for r in page])}
    return total, [_row_to_post({**full[r['id']], 'is_new': r['is_new'], 'keyword_links': r['keyword_links']})
                   for r in page if r['id'] in full]

def query_media(kind, offset, limit, group_id=None, folder_id=None, popular=False, since=None):
    """동영상·이미지 모아보기: 피드 글의 이미지(kind='image')나 동영상('video')을 글 순서(최신 수집순 또는 인기순)대로
    한 줄로 이어 offset부터 limit개. (전체 개수, 항목 목록) 반환. 페이지는 글마다 저장해 둔 개수로 정하고,
    본문은 그 페이지에 걸친 글만 읽음"""
    count_col = 'p.image_count' if kind == 'image' else 'p.video_count'
    feed_sql, params = _feed_from(group_id, folder_id)
    since_sql = ''
    if since is not None:
        since_sql = 'AND p.created_at >= ?'
        params += (since,)
    order = f'{_POPULAR_SQL} DESC, last_rowid DESC' if popular else 'last_rowid DESC'
    with _db() as conn:
        rows = conn.execute(f"""
            SELECT p.id, {count_col} AS n, MAX(kp.rowid) AS last_rowid,
                   GROUP_CONCAT(kp.board || char(31) || kp.keyword, char(30)) AS keyword_links
            {feed_sql}
            JOIN posts p ON p.id = kp.post_id
            WHERE {count_col} > 0 {since_sql}
            GROUP BY p.id
            ORDER BY {order}
        """, params).fetchall()
        total = sum(r['n'] for r in rows)
        # 이 페이지에 걸친 글과 그 글 안에서 건너뛸 개수
        picked, start = [], 0
        for r in rows:
            if start + r['n'] > offset and start < offset + limit:
                picked.append((r, max(0, offset - start)))
            start += r['n']
            if start >= offset + limit:
                break
        bodies = {b['id']: b for b in conn.execute(f"""
            SELECT p.id, p.title, p.link, b.content_json, b.videos_json FROM posts p JOIN post_bodies b ON b.post_id = p.id
            WHERE p.id IN ({','.join('?' * len(picked))})
        """, [r['id'] for r, _ in picked])}
    items = []
    for r, skip in picked:
        body = bodies.get(r['id'])
        if not body:
            continue
        media = ([{'type': 'image', 'src': src} for src in post_images(json.loads(body['content_json']))] if kind == 'image'
                 else post_videos(json.loads(body['videos_json'])))
        post = {'id': body['id'], 'title': body['title'], 'link': body['link'],
                'keywords': [dict(zip(('board', 'keyword'), link.split('\x1f', 1))) for link in r['keyword_links'].split('\x1e')]}
        for i, m in enumerate(media):
            if i >= skip and len(items) < limit:
                items.append({**m, 'index': i + 1, 'of': len(media), 'post': post})
    return total, items

def _new_comment_ids(conn, group_id=None, folder_id=None):
    """이미 읽은 글 중 마지막으로 읽은 뒤 수집된 댓글이 있는 글 ID (가장 최근 새 댓글 순).
    아직 안 읽은 글은 '안 읽은 글'에 나오므로 제외"""
    base, params = _feed_from(group_id, folder_id)
    # 피드의 글만 골라 그 글의 마지막 댓글 시각과 읽은 시각을 비교 (읽은 모든 글을 훑지 않게)
    rows = conn.execute(f"""
        SELECT p.id FROM (SELECT DISTINCT kp.post_id {base}) f
        JOIN posts p ON p.id = f.post_id
        JOIN read_posts rp ON rp.post_id = p.id
        WHERE p.last_comment_at > rp.read_at
        ORDER BY p.last_comment_at DESC
    """, params).fetchall()
    return [r['id'] for r in rows]

def query_posts_by_ids(post_ids):
    """지정한 글들을 그 순서대로 조회 (새 댓글 모아보기: 화면을 연 때의 목록을 페이지로 나눠 보여줌)"""
    ids = [str(i) for i in post_ids if is_post_id(str(i))]
    if not ids:
        return []
    feed_sql, params = _feed_from()
    with _db() as conn:
        rows = conn.execute(f"""
            SELECT p.*, b.videos_json, b.content_json, b.comments_json, rp.read_at, sp.saved_at, MAX(kp.is_new) AS is_new,
                   GROUP_CONCAT(kp.board || char(31) || kp.keyword, char(30)) AS keyword_links
            {feed_sql}
            JOIN posts p ON p.id = kp.post_id
            JOIN post_bodies b ON b.post_id = p.id
            LEFT JOIN read_posts rp ON rp.post_id = p.id
            LEFT JOIN saved_posts sp ON sp.post_id = p.id
            WHERE p.id IN ({','.join('?' * len(ids))})
            GROUP BY p.id
        """, params + tuple(ids)).fetchall()
    by_id = {r['id']: _row_to_post(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]

def dashboard_summary(recent_limit=3):
    """메인 대시보드의 키워드 게시판 카드: 오늘(0시 이후) 처음 수집한 글 수, 최근 수집한 글(제목·게시판·추천·댓글·수집 시각·읽음)"""
    today = datetime.now().strftime('%Y-%m-%d 00:00:00')
    with _db() as conn:
        today_count = conn.execute("SELECT COUNT(*) FROM posts WHERE created_at >= ?", (today,)).fetchone()[0]
        rows = conn.execute("""
            SELECT p.id, p.title, p.votes, p.comment_count, p.created_at, rp.post_id IS NOT NULL AS is_read,
                   (SELECT g.name FROM keyword_posts kp
                    JOIN keyword_group_members gm ON gm.board = kp.board AND gm.keyword = kp.keyword
                    JOIN keyword_groups g ON g.id = gm.group_id
                    WHERE kp.post_id = p.id ORDER BY g.position, g.id LIMIT 1) AS group_name
            FROM posts p
            LEFT JOIN read_posts rp ON rp.post_id = p.id
            WHERE p.is_deleted = 0
            ORDER BY p.created_at DESC, p.id DESC LIMIT ?
        """, (recent_limit,)).fetchall()
    return {'today_count': today_count,
            'recent': [{'id': r['id'], 'title': r['title'], 'votes': r['votes'], 'comment_count': r['comment_count'],
                        'collected_at': r['created_at'], 'is_read': bool(r['is_read']), 'group': r['group_name'] or ''}
                       for r in rows]}

def recent_post_ids(limit_per_keyword):
    """키워드별 최근 글 ID 집합 (메인 루프가 목록의 댓글 수로 매 주기 변화를 감시하는 범위, 일시정지한 키워드는 감시 안 함)"""
    ids = set()
    with _db() as conn:
        for kw in conn.execute("SELECT board, keyword FROM keywords WHERE paused = 0").fetchall():
            ids.update(r['post_id'] for r in conn.execute(
                "SELECT post_id FROM keyword_posts WHERE board = ? AND keyword = ? ORDER BY rowid DESC LIMIT ?",
                (kw['board'], kw['keyword'], limit_per_keyword)))
    return ids

def _update_content(conn, post_id, content, post):
    """저장된 글의 본문만 바꿈 (검색 텍스트·이미지 여부도 함께)"""
    content_json = json.dumps(content, ensure_ascii=False)
    conn.execute("UPDATE post_bodies SET content_json = ?, search_text = ? WHERE post_id = ?",
                 (content_json, _search_text(post), post_id))
    conn.execute("UPDATE posts SET has_image = ?, image_count = ? WHERE id = ?",
                 (int(_has_image(content_json)), len(post_images(content)), post_id))

def fix_stored_x_embeds():
    """이미 저장된 글 중 X(트위터) '링크 자동 변환 중' 임시 상자가 남은 글을 트윗 화면으로 1회 변환"""
    from bs4 import BeautifulSoup
    from embeds import convert_x_embeds
    from sanitize import sanitize_tree
    with _db() as conn:
        if _get_meta(conn, 'x_embeds_fixed'):
            return
        rows = conn.execute("SELECT p.id, p.title, b.content_json, b.comments_json FROM posts p JOIN post_bodies b ON b.post_id = p.id "
                            "WHERE b.content_json LIKE '%twitter-tweet%'").fetchall()
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
            _update_content(conn, row['id'], new_content, post)
        fixed += 1
    with _db() as conn, conn:
        _set_meta(conn, 'x_embeds_fixed', '1')
    if fixed:
        log_msg(f"[DB] 저장된 글의 X 트윗 카드 변환: {fixed}건")

def replace_stored_x_cards():
    """이미 저장된 글의 글자 트윗 카드(사진이 보이지 않음)를 트윗 화면(iframe)으로 1회 변환.
    같은 트윗의 화면이 이미 있으면 글자 카드만 지움"""
    from bs4 import BeautifulSoup
    from embeds import x_cards_to_iframes
    with _db() as conn:
        if _get_meta(conn, 'x_cards_to_iframes'):
            return
        rows = conn.execute("SELECT p.id, p.title, b.content_json, b.comments_json FROM posts p JOIN post_bodies b ON b.post_id = p.id "
                            "WHERE b.content_json LIKE '%x-embed%'").fetchall()
    fixed = 0
    for row in rows:
        soup = BeautifulSoup('\n'.join(json.loads(row['content_json'])), 'html.parser')
        if not x_cards_to_iframes(soup, soup):
            continue
        new_content = soup.decode().split('\n')
        post = {'title': row['title'], 'content': new_content, 'comments': json.loads(row['comments_json'])}
        with _db() as conn, conn:
            _update_content(conn, row['id'], new_content, post)
        fixed += 1
    with _db() as conn, conn:
        _set_meta(conn, 'x_cards_to_iframes', '1')
    if fixed:
        log_msg(f"[DB] 저장된 글의 X 글자 카드를 트윗 화면으로 변환: {fixed}건")

# 2026-10-31 오전~저녁 배포본은 크롬이 이미지 주소를 막는 방식이라, 에펨코리아 페이지가 불러오지 못한 이미지콘을
# '삭제된 이미지콘' 그림으로 바꾼 채 저장됨. 그 사이 수집된 글만 다시 수집해 되돌림 (기동 시 1회, fmkorea-scraper.py)
BLOCKED_IMAGECON_MARK = 'imagecon_deleted.svg'
BLOCKED_IMAGES_SINCE = '2026-10-31 08:59:00'

# 처음에는 본문만 확인해 댓글의 이미지콘이 빠졌으므로 댓글까지 보고 한 번 더 처리 (처리 여부 표시 이름을 바꿈)
BLOCKED_IMAGECONS_META = 'blocked_imagecons_refetched_with_comments'

def posts_with_blocked_imagecons():
    """이미지 차단 때문에 본문이나 댓글의 이미지콘이 '삭제됨' 그림으로 저장된 글
    [{id, link, title, author, date, list_comment_count}]. 이미 한 번 처리했으면 빈 목록"""
    mark = f'%{BLOCKED_IMAGECON_MARK}%'
    with _db() as conn:
        if _get_meta(conn, BLOCKED_IMAGECONS_META):
            return []
        rows = conn.execute("""
            SELECT p.id, p.link, p.title, p.author, p.date, p.list_comment_count FROM posts p
            JOIN post_bodies b ON b.post_id = p.id
            WHERE p.updated_at >= ? AND p.is_deleted = 0 AND (b.content_json LIKE ? OR b.comments_json LIKE ?)
        """, (BLOCKED_IMAGES_SINCE, mark, mark)).fetchall()
    return [dict(r) for r in rows]

def mark_blocked_imagecons_refetched():
    with _db() as conn, conn:
        _set_meta(conn, BLOCKED_IMAGECONS_META, '1')

def remove_stored_duplicate_instagram_placeholders():
    """이미 저장된 글 중 인스타그램 게시물 화면(iframe)과 같은 게시물의 임시 상자가 함께 남은 글에서 상자를 1회 정리"""
    from bs4 import BeautifulSoup
    from embeds import remove_duplicate_instagram_placeholders
    with _db() as conn:
        if _get_meta(conn, 'instagram_duplicate_placeholders_removed'):
            return
        rows = conn.execute("SELECT p.id, p.title, b.content_json, b.comments_json FROM posts p JOIN post_bodies b ON b.post_id = p.id "
                            "WHERE b.content_json LIKE '%instagram-media%' AND b.content_json LIKE '%instagram.com%'").fetchall()
    fixed = 0
    for row in rows:
        soup = BeautifulSoup('\n'.join(json.loads(row['content_json'])), 'html.parser')
        if not remove_duplicate_instagram_placeholders(soup):
            continue
        new_content = soup.decode().split('\n')
        post = {'title': row['title'], 'content': new_content, 'comments': json.loads(row['comments_json'])}
        with _db() as conn, conn:
            _update_content(conn, row['id'], new_content, post)
        fixed += 1
    with _db() as conn, conn:
        _set_meta(conn, 'instagram_duplicate_placeholders_removed', '1')
    if fixed:
        log_msg(f"[DB] 인스타그램 게시물 화면과 겹친 임시 상자 정리: {fixed}건")

def remove_stored_sns_videos():
    """이미 저장된 글의 동영상 목록에서 인스타그램·X 등 SNS 게시물 화면을 1회 뺌 ('동영상' 보기에 섞이지 않도록)"""
    from embeds import is_sns_embed
    with _db() as conn:
        if _get_meta(conn, 'sns_videos_removed'):
            return
        rows = conn.execute("SELECT post_id AS id, videos_json FROM post_bodies WHERE videos_json != '[]'").fetchall()
    fixed = 0
    with _db() as conn, conn:
        for row in rows:
            videos = json.loads(row['videos_json'])
            kept = [v for v in videos if not is_sns_embed(v)]
            if len(kept) != len(videos):
                conn.execute("UPDATE post_bodies SET videos_json = ? WHERE post_id = ?", (json.dumps(kept, ensure_ascii=False), row['id']))
                conn.execute("UPDATE posts SET has_video = ?, video_count = ? WHERE id = ?",
                             (int(bool(kept)), len(post_videos(kept)), row['id']))
                fixed += 1
        _set_meta(conn, 'sns_videos_removed', '1')
    if fixed:
        log_msg(f"[DB] 동영상 목록에서 SNS 게시물 화면 정리: 글 {fixed}건")

# ==========================================
# 유지 관리 (하루 한 번: 백업, 오래된 글 정리)
# ==========================================
_BACKUP_NAME_RE = re.compile(r'board-\d{8}\.db')

def backup_db(backup_dir, keep):
    """DB를 sqlite 온라인 백업으로 하루 한 파일(board-YYYYMMDD.db)씩 복사하고 최근 keep개만 남김.
    만든 파일 경로를 반환하고, 오늘 백업이 이미 있으면 None"""
    os.makedirs(backup_dir, exist_ok=True)
    path = os.path.join(backup_dir, f"board-{datetime.now():%Y%m%d}.db")
    if os.path.exists(path):
        return None
    # 수집 중에도 일관된 사본을 만들고, 도중에 실패해도 반쪽 파일이 백업으로 남지 않게 임시 이름으로 쓴 뒤 교체
    partial = path + '.part'
    with _db() as src, closing(sqlite3.connect(partial)) as dst:
        src.backup(dst)
    os.replace(partial, path)
    backups = sorted(name for name in os.listdir(backup_dir) if _BACKUP_NAME_RE.fullmatch(name))
    for old in backups[:-keep] if keep > 0 else []:
        os.remove(os.path.join(backup_dir, old))
    return path

def prune_old_posts(days, keep_per_keyword):
    """수집한 지 days일이 지난 글을 삭제하고 삭제한 글 수를 반환 (days가 0 이하면 안 함).
    보관함에 담은 글과, 각 키워드의 최근 keep_per_keyword개(새 글 판별 기준)는 남김
    (지우면 검색 1페이지에 아직 있는 오래된 글이 새 글로 다시 잡혀 알림이 감)"""
    if days <= 0:
        return 0
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    with _db() as conn, conn:
        deleted = conn.execute("""
            DELETE FROM posts WHERE created_at < ? AND id NOT IN (SELECT post_id FROM saved_posts) AND id NOT IN (
                SELECT post_id FROM (
                    SELECT post_id, ROW_NUMBER() OVER (PARTITION BY board, keyword ORDER BY rowid DESC) AS rn
                    FROM keyword_posts
                ) WHERE rn <= ?
            )
        """, (cutoff, keep_per_keyword)).rowcount
        if deleted:
            # 글과 키워드 연결은 외래 키(ON DELETE CASCADE)로 함께 지워짐
            conn.execute("DELETE FROM read_posts WHERE post_id NOT IN (SELECT id FROM posts)")
    return deleted

def load_rejected_posts():
    """거른 글 {(board, keyword, post_id)}"""
    with _db() as conn:
        return {(r['board'], r['keyword'], r['post_id']) for r in conn.execute("SELECT board, keyword, post_id FROM rejected_posts")}

def add_rejected_post(board, keyword, post_id):
    with _db() as conn, conn:
        conn.execute("INSERT OR IGNORE INTO rejected_posts(board, keyword, post_id, rejected_at) VALUES(?, ?, ?, ?)",
                     (board, keyword, str(post_id), _now()))

def add_unalerted_post(post_id):
    """새 글로 수집했지만 알림을 보내지 않은 글로 기억"""
    with _db() as conn, conn:
        conn.execute("INSERT OR IGNORE INTO unalerted_posts(post_id, collected_at) VALUES(?, ?)", (str(post_id), _now()))

def take_unalerted_post(post_id):
    """알림을 보내지 않은 글이면 기억에서 지우고 True (다른 키워드에서 한 번만 알림을 보내도록)"""
    with _db() as conn, conn:
        return conn.execute("DELETE FROM unalerted_posts WHERE post_id = ?", (str(post_id),)).rowcount > 0

def prune_unalerted_posts(hours):
    """hours시간 지난 기억 삭제 (같은 글은 보통 같은 주기나 몇 주기 안에 다른 키워드에서도 걸림). 삭제한 수 반환"""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
    with _db() as conn, conn:
        return conn.execute("DELETE FROM unalerted_posts WHERE collected_at < ?", (cutoff,)).rowcount

def prune_rejected_posts(keep_per_keyword):
    """키워드마다 최근에 거른 keep_per_keyword개만 남기고 삭제한 수 반환.
    거른 글 기억은 검색 목록 첫 페이지에 아직 보이는 글에만 쓸모가 있으므로 오래된 것은 지워도 됨"""
    with _db() as conn, conn:
        return conn.execute("""
            DELETE FROM rejected_posts WHERE rowid IN (
                SELECT rowid FROM (
                    SELECT rowid, ROW_NUMBER() OVER (PARTITION BY board, keyword ORDER BY rejected_at DESC, rowid DESC) AS rn
                    FROM rejected_posts
                ) WHERE rn > ?
            )
        """, (keep_per_keyword,)).rowcount

def existing_post_ids(post_ids):
    """주어진 글 ID 중 DB에 남아 있는 것의 집합 (정리된 글의 이미지 폴더를 찾을 때 씀)"""
    ids = [str(i) for i in post_ids if is_post_id(str(i))]
    found = set()
    with _db() as conn:
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            found.update(r['id'] for r in conn.execute(
                f"SELECT id FROM posts WHERE id IN ({','.join('?' * len(chunk))})", chunk))
    return found

def mark_posts_read(post_ids):
    """읽음 기록 저장. 이미 읽은 글은 마지막 읽은 시각만 갱신(그 이후 달린 댓글만 '새 댓글'이 되도록),
    처음 읽은 시각은 그대로 둠. 모은 글이 아닌 ID는 저장하지 않음 (암호 없이 부르는 API라 쓸모없는 기록이 쌓이지 않게).
    저장한 글 수 반환"""
    ids = sorted(existing_post_ids(post_ids))
    if not ids:
        return 0
    now = _now()
    with _db() as conn, conn:
        conn.executemany(
            "INSERT INTO read_posts(post_id, read_at, first_read_at) VALUES(?, ?, ?) "
            "ON CONFLICT(post_id) DO UPDATE SET read_at = excluded.read_at",
            [(i, now, now) for i in ids]
        )
    return len(ids)

def set_post_saved(post_id, saved):
    """보관함에 담기·빼기. 모은 글이 아니면 False"""
    post_id = str(post_id)
    with _db() as conn, conn:
        if not conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone():
            return False
        if saved:
            conn.execute("INSERT OR IGNORE INTO saved_posts(post_id, saved_at) VALUES(?, ?)", (post_id, _now()))
        else:
            conn.execute("DELETE FROM saved_posts WHERE post_id = ?", (post_id,))
    return True

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
