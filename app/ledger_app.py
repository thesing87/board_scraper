"""YeYe홈 앱(android/ledger-notify) 파일: 관리자가 올린 APK 하나를 OUTPUT_DIR/ledger_app에 두고 가계부 사람들이 받아 감

- 올릴 때 APK 안의 AndroidManifest.xml(바이너리 XML)을 읽어 패키지 이름·버전을 확인 (다른 앱을 잘못 올리지 않게)
- 새로 올리면 바꿔 끼움 (임시 파일에 쓴 뒤 이름 바꾸기라 받는 중인 사람도 깨진 파일을 받지 않음)
"""
import hashlib
import io
import json
import os
import struct
import zipfile

from config import OUTPUT_DIR
from storage import _now

PACKAGE = 'kr.home.ledgernotify'
MAX_BYTES = 50 * 1024 * 1024
APP_DIR = os.path.join(OUTPUT_DIR, 'ledger_app')
APK_FILE = os.path.join(APP_DIR, 'ledger-notify.apk')
INFO_FILE = os.path.join(APP_DIR, 'ledger-notify.json')

# 안드로이드 속성의 리소스 번호 (aapt2가 속성 이름을 비워 둘 때)
ATTR_IDS = {0x0101021B: 'versionCode', 0x0101021C: 'versionName'}


class AppFileError(Exception):
    """올린 파일을 받을 수 없는 이유 (화면에 그대로 보여 줌)"""


# ==========================================
# 바이너리 XML(AXML)에서 manifest 태그의 package·versionCode·versionName 읽기
# ==========================================
def _string_pool(data, start):
    _, header_size, _, count, _, flags, strings_start, _ = struct.unpack_from('<HHIIIIII', data, start)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f'<{count}I', data, start + header_size)
    base = start + strings_start
    out = []
    for off in offsets:
        pos = base + off
        if utf8:
            # 글자 수, 바이트 수 (각각 1~2바이트) 뒤에 UTF-8
            pos += 2 if data[pos] & 0x80 else 1
            n = data[pos]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[pos + 1]
                pos += 2
            else:
                pos += 1
            out.append(data[pos:pos + n].decode('utf-8', 'replace'))
        else:
            n = struct.unpack_from('<H', data, pos)[0]
            pos += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from('<H', data, pos)[0]
                pos += 2
            out.append(data[pos:pos + n * 2].decode('utf-16-le', 'replace'))
    return out


def read_manifest(axml):
    """바이너리 AndroidManifest.xml → {'package', 'versionCode', 'versionName'}. 읽지 못하면 AppFileError"""
    try:
        if struct.unpack_from('<H', axml, 0)[0] != 0x0003:
            raise ValueError
        strings, res_ids, pos = [], [], struct.unpack_from('<H', axml, 2)[0]
        while pos + 8 <= len(axml):
            ctype, header_size, size = struct.unpack_from('<HHI', axml, pos)
            if size < 8:
                raise ValueError
            if ctype == 0x0001:
                strings = _string_pool(axml, pos)
            elif ctype == 0x0180:
                res_ids = list(struct.unpack_from(f'<{(size - header_size) // 4}I', axml, pos + header_size))
            elif ctype == 0x0102:
                name_idx, attr_start, attr_size, attr_count = struct.unpack_from('<IHHH', axml, pos + 20)
                if strings[name_idx] == 'manifest':
                    found = {}
                    for i in range(attr_count):
                        a = pos + 16 + attr_start + i * attr_size
                        _, aname, raw, _, _, dtype, value = struct.unpack_from('<IIIHBBI', axml, a)
                        key = strings[aname] if aname < len(strings) and strings[aname] else ''
                        if not key and aname < len(res_ids):
                            key = ATTR_IDS.get(res_ids[aname], '')
                        if raw != 0xFFFFFFFF:
                            found[key] = strings[raw]
                        elif dtype == 0x03:
                            found[key] = strings[value]
                        elif dtype in (0x10, 0x11):
                            found[key] = value
                    return {'package': str(found.get('package', '')), 'versionCode': int(found.get('versionCode') or 0),
                            'versionName': str(found.get('versionName', ''))}
            pos += size
    except (struct.error, IndexError, ValueError, TypeError):
        pass
    raise AppFileError('앱 정보(AndroidManifest.xml)를 읽지 못했어요.')


# ==========================================
# 올리기·정보·받기
# ==========================================
def save(data, uploader):
    """올린 APK를 확인하고 바꿔 끼움 → 새 정보"""
    if not data or len(data) > MAX_BYTES:
        raise AppFileError('파일 크기가 올바르지 않아요.')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            if 'AndroidManifest.xml' not in names or 'classes.dex' not in names:
                raise AppFileError('안드로이드 앱(APK) 파일이 아니에요.')
            manifest = read_manifest(z.read('AndroidManifest.xml'))
    except zipfile.BadZipFile:
        raise AppFileError('안드로이드 앱(APK) 파일이 아니에요.')
    if manifest['package'] != PACKAGE:
        raise AppFileError(f'YeYe홈 앱이 아니에요 ({manifest["package"] or "패키지 이름 없음"}).')
    old = info()
    if old and manifest['versionCode'] < old['versionCode']:
        raise AppFileError(f'지금 올라가 있는 {old["versionName"]}({old["versionCode"]})보다 낮은 버전이에요.')
    new = {'versionName': manifest['versionName'], 'versionCode': manifest['versionCode'], 'size': len(data),
           'sha256': hashlib.sha256(data).hexdigest(), 'uploaded_at': _now(), 'uploaded_by': uploader}
    os.makedirs(APP_DIR, exist_ok=True)
    for path, body in ((APK_FILE, data), (INFO_FILE, json.dumps(new, ensure_ascii=False).encode('utf-8'))):
        tmp = path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(body)
        os.replace(tmp, path)
    return new


def info():
    """올라가 있는 앱 정보 또는 None"""
    try:
        with open(INFO_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return data if os.path.isfile(APK_FILE) else None
    except (OSError, ValueError):
        return None


def download_name(data):
    return f"YeYe홈-{data.get('versionName') or data.get('versionCode')}.apk"
