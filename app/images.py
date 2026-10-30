"""수집할 때 받아 둔 글 이미지 (지금은 디시인사이드만).

디시 이미지는 디시 페이지가 아닌 곳에서는 열리지 않으므로, 수집용 크롬이 글을 열 때 디시 페이지가 정상적으로 받은
이미지 파일을 크롬에서 그대로 꺼내 OUTPUT_DIR/images/<글 ID>/<순번>-<내용 해시>.<확장자>로 저장하고, 웹서버가 /images/...로 보여줌.
글이 정리되면(prune_old_posts 등) 하루 한 번 유지 관리에서 남은 이미지 폴더도 지움 (remove_orphan_image_dirs).
"""
import os
import re
import shutil
import hashlib
from config import log_msg, IMAGE_DIR

IMAGE_URL_PREFIX = '/images/'
# 글 하나에서 저장할 최대 이미지 수와 한 장의 최대 크기 (NAS 저장 공간 보호)
MAX_IMAGES_PER_POST = 40
MAX_IMAGE_BYTES = 15 * 1024 * 1024
# 저장 경로: 글 ID 폴더(sites.POST_ID_RE와 같은 문자) / 순번-내용해시.확장자
# (글을 고쳐 같은 순번의 이미지가 바뀌어도 주소가 달라져, 브라우저에 오래 보관된 예전 이미지가 보이지 않게 함)
IMAGE_PATH_RE = re.compile(r'([a-z0-9_-]{1,80})/(\d{1,3}-[0-9a-f]{10})\.(jpg|png|gif|webp)')
CONTENT_TYPES = {'jpg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'}

def image_ext(data):
    """파일 앞부분으로 이미지 형식 판별 (알 수 없는 형식이면 None)"""
    if data[:3] == b'\xff\xd8\xff':
        return 'jpg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    return None

def save_post_image(post_id, index, data):
    """이미지 한 장 저장. 대시보드에서 쓸 주소(/images/글ID/순번-해시.확장자)를 반환, 저장하지 않으면 None"""
    ext = image_ext(data)
    if not ext or len(data) > MAX_IMAGE_BYTES or index >= MAX_IMAGES_PER_POST:
        return None
    name = f"{index}-{hashlib.sha1(data).hexdigest()[:10]}.{ext}"
    rel = f"{post_id}/{name}"
    if not IMAGE_PATH_RE.fullmatch(rel):
        return None
    folder = os.path.join(IMAGE_DIR, post_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), 'wb') as f:
        f.write(data)
    return IMAGE_URL_PREFIX + rel

def clear_post_images(post_id):
    """글을 다시 수집하기 전에 그 글의 예전 이미지 파일을 지움 (고친 글에서 빠진 이미지가 남지 않게)"""
    folder = os.path.join(IMAGE_DIR, post_id)
    if IMAGE_PATH_RE.fullmatch(f"{post_id}/0-0000000000.jpg") and os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)

def image_file(rel):
    """웹서버 요청 경로(/images/ 뒤)를 실제 파일 경로와 형식으로. 형식이 맞지 않거나 파일이 없으면 None"""
    match = IMAGE_PATH_RE.fullmatch(rel or '')
    if not match:
        return None
    path = os.path.join(IMAGE_DIR, match.group(1), f"{match.group(2)}.{match.group(3)}")
    return (path, CONTENT_TYPES[match.group(3)]) if os.path.isfile(path) else None

def remove_orphan_image_dirs(existing_post_ids):
    """DB에 없는 글의 이미지 폴더를 지우고 지운 폴더 수를 반환.
    existing_post_ids: 폴더 이름(글 ID) 목록을 받아 DB에 남아 있는 글 ID 집합을 돌려주는 함수"""
    if not os.path.isdir(IMAGE_DIR):
        return 0
    names = [n for n in os.listdir(IMAGE_DIR) if os.path.isdir(os.path.join(IMAGE_DIR, n))]
    keep = existing_post_ids(names)
    removed = 0
    for name in names:
        if name not in keep:
            shutil.rmtree(os.path.join(IMAGE_DIR, name), ignore_errors=True)
            removed += 1
    if removed:
        log_msg(f"[DB] 정리된 글의 이미지 폴더 {removed}개 삭제", "DEBUG")
    return removed
