"""만화 뷰어(/comics/): NAS의 만화 폴더(COMICS_DIR, 컨테이너에는 읽기 전용으로 연결)를 둘러보고 책을 한 장씩 보냄.

- 책: 압축 파일(.cbz·.zip) 또는 이미지가 든 폴더. 압축은 풀지 않고 요청한 한 장만 꺼내 보냄 (zip은 목차가 파일 끝에 있어 바로 찾아감)
- 경로는 모두 만화 폴더 기준 상대 경로('/' 구분). 만화 폴더 밖(.. 이나 심볼릭 링크)으로 나가는 경로는 거부
- 페이지마다 가로·세로 크기를 이미지 머리에서 읽어 둠 → 화면이 처음부터 양면(가로로 긴) 페이지를 반으로 나눠 보여 줌
- 읽던 위치는 DB(comic_progress)에 저장
"""
import os
import re
import struct
import threading
import zipfile
from collections import OrderedDict

from config import COMICS_DIR
from storage import _db, _now

ARCHIVE_EXTS = ('.cbz', '.zip')
IMAGE_TYPES = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif',
    '.webp': 'image/webp', '.avif': 'image/avif', '.bmp': 'image/bmp',
}
# 목록에서 숨길 이름: 시놀로지 색인 폴더, 맥이 압축에 넣는 폴더, 숨김 파일
HIDDEN_RE = re.compile(r'^(\.|@eaDir$|#recycle$|__MACOSX$)')
# 압축 하나의 페이지 수 상한 (깨진·엉뚱한 파일로 응답이 너무 커지지 않게)
MAX_PAGES = 5000
# 한 페이지 이미지 크기 상한 (웹서버 메모리 한도가 작으므로)
MAX_PAGE_BYTES = 50 * 1024 * 1024
# 이미지 크기를 찾으려고 머리에서 읽어 보는 최대 바이트 (JPEG는 EXIF 뒤에 크기가 있어 넉넉히)
DIM_READ_BYTES = 512 * 1024
# 책 정보(페이지 목록·크기)를 기억해 두는 책 수
BOOK_CACHE_SIZE = 16

_book_cache = OrderedDict()
_book_cache_lock = threading.Lock()


def configured():
    return bool(COMICS_DIR) and os.path.isdir(COMICS_DIR)


def natural_key(name):
    """'2권' < '10권' 처럼 숫자를 숫자로 비교하는 정렬 키"""
    return [(0, int(part), '') if part.isdigit() else (1, 0, part) for part in re.split(r'(\d+)', name.lower()) if part]


def resolve(rel):
    """상대 경로 → 실제 경로. 만화 폴더 밖이거나 숨긴 이름이 들어 있으면 None"""
    rel = (rel or '').replace('\\', '/').strip('/')
    parts = [p for p in rel.split('/') if p]
    if any(p in ('.', '..') or HIDDEN_RE.match(p) for p in parts):
        return None
    root = os.path.realpath(COMICS_DIR)
    full = os.path.realpath(os.path.join(root, *parts))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


def _is_image(name):
    return os.path.splitext(name)[1].lower() in IMAGE_TYPES


def _is_archive(name):
    return name.lower().endswith(ARCHIVE_EXTS)


def _join(rel, name):
    return f"{rel}/{name}" if rel else name


def list_dir(rel):
    """폴더 안의 하위 폴더·책. 폴더에 이미지가 바로 들어 있으면 그 폴더도 책(images 장 수)으로 볼 수 있음. 없는 폴더면 None"""
    rel = (rel or '').replace('\\', '/').strip('/')
    full = resolve(rel)
    if not full or not os.path.isdir(full):
        return None
    dirs, books, images = [], [], 0
    with os.scandir(full) as it:
        for entry in it:
            if HIDDEN_RE.match(entry.name):
                continue
            try:
                if entry.is_dir():
                    dirs.append({'name': entry.name, 'path': _join(rel, entry.name), **_dir_counts(entry.path)})
                elif entry.is_file():
                    if _is_archive(entry.name):
                        books.append({'name': os.path.splitext(entry.name)[0], 'path': _join(rel, entry.name),
                                      'size': entry.stat().st_size})
                    elif _is_image(entry.name):
                        images += 1
            except OSError:
                continue
    dirs.sort(key=lambda d: natural_key(d['name']))
    books.sort(key=lambda b: natural_key(b['name']))
    progress = progress_for([b['path'] for b in books] + ([rel] if images else []))
    for b in books:
        b['progress'] = progress.get(b['path'])
    return {'path': rel, 'name': os.path.basename(rel) if rel else '', 'dirs': dirs, 'books': books,
            'images': images, 'images_progress': progress.get(rel) if images else None}


# ==========================================
# 이미지 크기 (JPEG·PNG·GIF·WebP 머리에서). 알 수 없으면 None
# ==========================================
def image_size(head):
    try:
        if head[:8] == b'\x89PNG\r\n\x1a\n':
            return struct.unpack('>II', head[16:24])
        if head[:6] in (b'GIF87a', b'GIF89a'):
            return struct.unpack('<HH', head[6:10])
        if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
            chunk = head[12:16]
            if chunk == b'VP8X':
                return (int.from_bytes(head[24:27], 'little') + 1, int.from_bytes(head[27:30], 'little') + 1)
            if chunk == b'VP8 ':
                w, h = struct.unpack('<HH', head[26:30])
                return (w & 0x3FFF, h & 0x3FFF)
            if chunk == b'VP8L':
                bits = int.from_bytes(head[21:25], 'little')
                return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        if head[:2] == b'\xff\xd8':
            i = 2
            while i + 9 < len(head):
                if head[i] != 0xFF:
                    i += 1
                    continue
                marker = head[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                    i += 1 if marker == 0xFF else 2
                    continue
                length = struct.unpack('>H', head[i + 2:i + 4])[0]
                # SOF0~SOF15 (DHT C4·JPG C8·DAC CC 제외)
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack('>HH', head[i + 5:i + 9])
                    return (w, h)
                i += 2 + length
    except struct.error:
        return None
    return None


def _read_head(fileobj):
    data = b''
    while len(data) < DIM_READ_BYTES:
        chunk = fileobj.read(64 * 1024)
        if not chunk:
            break
        data += chunk
        size = image_size(data)
        if size:
            return size
    return image_size(data)


# ==========================================
# 책 (압축 파일 또는 이미지 폴더)
# ==========================================
def _load_book(full):
    """[(이미지 이름, (가로, 세로) 또는 None)] (이름 자연 정렬)"""
    if os.path.isdir(full):
        names = sorted((n for n in os.listdir(full) if _is_image(n) and not HIDDEN_RE.match(n)
                        and os.path.isfile(os.path.join(full, n))), key=natural_key)[:MAX_PAGES]
        pages = []
        for n in names:
            try:
                with open(os.path.join(full, n), 'rb') as f:
                    pages.append((n, _read_head(f)))
            except OSError:
                pages.append((n, None))
        return pages
    with zipfile.ZipFile(full) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and _is_image(i.filename)
                 and not any(HIDDEN_RE.match(p) for p in i.filename.split('/'))]
        infos.sort(key=lambda i: natural_key(i.filename))
        pages = []
        for info in infos[:MAX_PAGES]:
            try:
                with zf.open(info) as f:
                    pages.append((info.filename, _read_head(f)))
            except Exception:
                pages.append((info.filename, None))
        return pages


def _book_pages(full):
    stat = os.stat(full)
    key = (full, stat.st_mtime_ns, stat.st_size)
    with _book_cache_lock:
        if key in _book_cache:
            _book_cache.move_to_end(key)
            return _book_cache[key]
    pages = _load_book(full)
    with _book_cache_lock:
        _book_cache[key] = pages
        while len(_book_cache) > BOOK_CACHE_SIZE:
            _book_cache.popitem(last=False)
    return pages


def _book_full(rel):
    """책의 실제 경로. 압축 파일이나 폴더가 아니면 None"""
    full = resolve(rel)
    if not full or not rel:
        return None
    if (os.path.isfile(full) and _is_archive(full)) or os.path.isdir(full):
        return full
    return None


def _neighbors(rel):
    """같은 폴더에서 이 책의 앞뒤 책 (압축 파일끼리, 이름 순)"""
    parent = rel.rsplit('/', 1)[0] if '/' in rel else ''
    listing = list_dir(parent)
    if not listing:
        return None, None
    paths = [b['path'] for b in listing['books']]
    if rel not in paths:
        return None, None
    i = paths.index(rel)
    pick = lambda j: {'path': paths[j], 'name': listing['books'][j]['name']} if 0 <= j < len(paths) else None
    return pick(i - 1), pick(i + 1)


def book_info(rel):
    """책의 페이지 수·크기·읽던 위치·앞뒤 책. 없는 책이면 None"""
    rel = (rel or '').replace('\\', '/').strip('/')
    full = _book_full(rel)
    if not full:
        return None
    try:
        pages = _book_pages(full)
    except (zipfile.BadZipFile, OSError):
        return None
    prev_book, next_book = _neighbors(rel) if os.path.isfile(full) else (None, None)
    name = os.path.basename(rel)
    return {
        'path': rel,
        'name': os.path.splitext(name)[0] if os.path.isfile(full) else name,
        'folder': rel.rsplit('/', 1)[0] if '/' in rel else '',
        'count': len(pages),
        'sizes': [list(size) if size else None for _, size in pages],
        'progress': progress_for([rel]).get(rel),
        'prev': prev_book,
        'next': next_book,
    }


def page_image(rel, index):
    """(이미지 바이트, 형식, 내용 지문용 키) 또는 None"""
    rel = (rel or '').replace('\\', '/').strip('/')
    full = _book_full(rel)
    if not full:
        return None
    try:
        pages = _book_pages(full)
        if not 0 <= index < len(pages):
            return None
        name = pages[index][0]
        content_type = IMAGE_TYPES[os.path.splitext(name)[1].lower()]
        stat = os.stat(full)
        tag = f"{stat.st_mtime_ns}-{stat.st_size}-{index}"
        if os.path.isdir(full):
            path = os.path.join(full, name)
            if os.path.getsize(path) > MAX_PAGE_BYTES:
                return None
            with open(path, 'rb') as f:
                return f.read(), content_type, tag
        with zipfile.ZipFile(full) as zf:
            info = zf.getinfo(name)
            if info.file_size > MAX_PAGE_BYTES:
                return None
            return zf.read(info), content_type, tag
    except (zipfile.BadZipFile, KeyError, OSError):
        return None


def _dir_counts(full):
    """목록의 폴더 칸에 보여 줄 개수: 안에 든 책(압축 파일)·하위 폴더·이미지 수 (못 읽으면 0)"""
    books = dirs = images = 0
    try:
        with os.scandir(full) as it:
            for entry in it:
                if HIDDEN_RE.match(entry.name):
                    continue
                if entry.is_dir():
                    dirs += 1
                elif _is_archive(entry.name):
                    books += 1
                elif _is_image(entry.name):
                    images += 1
    except OSError:
        pass
    return {'books': books, 'dirs': dirs, 'images': images}


# 폴더(시리즈)의 표지를 찾을 때 하위 폴더로 내려가는 최대 깊이
COVER_SEARCH_DEPTH = 3

def _cover_source(full, depth=COVER_SEARCH_DEPTH):
    """폴더의 표지로 쓸 파일: 폴더 안 첫 이미지 → 첫 책(압축 파일) → 첫 하위 폴더 안에서 다시. 없으면 None"""
    try:
        with os.scandir(full) as it:
            entries = sorted((e for e in it if not HIDDEN_RE.match(e.name)), key=lambda e: natural_key(e.name))
    except OSError:
        return None
    for test in (lambda e: e.is_file() and _is_image(e.name), lambda e: e.is_file() and _is_archive(e.name)):
        found = next((e.path for e in entries if test(e)), None)
        if found:
            return found
    if depth > 0:
        for e in entries:
            if e.is_dir():
                found = _cover_source(e.path, depth - 1)
                if found:
                    return found
    return None


def cover_image(rel):
    """목록의 표지: 첫 이미지만 꺼냄 (페이지 크기를 읽지 않아 책이 많은 폴더도 가벼움). 폴더(시리즈)는 안에 든 첫 이미지나 첫 책의 표지.
    (바이트, 형식, 지문용 키) 또는 None"""
    rel = (rel or '').replace(chr(92), '/').strip('/')
    full = _book_full(rel)
    if not full:
        return None
    try:
        if os.path.isdir(full):
            full = _cover_source(full)
            if not full:
                return None
        stat = os.stat(full)
        tag = f"c{stat.st_mtime_ns}-{stat.st_size}"
        if _is_image(full):
            if stat.st_size > MAX_PAGE_BYTES:
                return None
            with open(full, 'rb') as f:
                return f.read(), IMAGE_TYPES[os.path.splitext(full)[1].lower()], tag
        with zipfile.ZipFile(full) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir() and _is_image(i.filename)
                     and not any(HIDDEN_RE.match(p) for p in i.filename.split('/'))]
            if not infos:
                return None
            info = min(infos, key=lambda i: natural_key(i.filename))
            if info.file_size > MAX_PAGE_BYTES:
                return None
            return zf.read(info), IMAGE_TYPES[os.path.splitext(info.filename)[1].lower()], tag
    except (zipfile.BadZipFile, OSError):
        return None


# ==========================================
# 읽던 위치
# ==========================================
def progress_for(paths):
    """{경로: {'page', 'pages', 'updated_at'}}"""
    paths = list(paths)
    if not paths:
        return {}
    result = {}
    with _db() as conn:
        for start in range(0, len(paths), 500):
            chunk = paths[start:start + 500]
            rows = conn.execute(f"SELECT path, page, pages, updated_at FROM comic_progress WHERE path IN ({','.join('?' * len(chunk))})",
                                chunk).fetchall()
            for r in rows:
                result[r['path']] = {'page': r['page'], 'pages': r['pages'], 'updated_at': r['updated_at']}
    return result


def save_progress(rel, page, pages):
    with _db() as conn, conn:
        conn.execute("INSERT INTO comic_progress(path, page, pages, updated_at) VALUES(?, ?, ?, ?) "
                     "ON CONFLICT(path) DO UPDATE SET page = excluded.page, pages = excluded.pages, updated_at = excluded.updated_at",
                     (rel, page, pages, _now()))


def recent(limit=6):
    """최근 읽은 책 (다 읽은 책 포함). 지금은 없는 책은 빼고 보냄"""
    with _db() as conn:
        rows = conn.execute("SELECT path, page, pages, updated_at FROM comic_progress ORDER BY updated_at DESC LIMIT ?",
                            (limit * 3,)).fetchall()
    items = []
    for r in rows:
        full = resolve(r['path'])
        if not full or not os.path.exists(full):
            continue
        name = os.path.basename(r['path'])
        items.append({'path': r['path'], 'name': os.path.splitext(name)[0] if os.path.isfile(full) else name,
                      'folder': r['path'].rsplit('/', 1)[0] if '/' in r['path'] else '',
                      'progress': {'page': r['page'], 'pages': r['pages'], 'updated_at': r['updated_at']}})
        if len(items) >= limit:
            break
    return items
