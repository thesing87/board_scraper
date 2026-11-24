"""FM키워드 줄 읽은 글 기록: 다른 키워드에서 읽은 글이 쌓여 500개를 넘어도, 이 키워드에서 찾아 읽은 글의 읽음은 밀려나지 않음
(예전에는 번호순으로 오래된 것부터 버려 '새 N'이 다시 늘었음)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: F401  (경로)
import tempfile, json
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage

storage.init_db()
BASE = 9000000000
storage.fm_seen_init('baseball', '삼성', BASE)
found = [BASE + i for i in range(1, 11)]
storage.fm_seen_found('baseball', '삼성', found)
for no in found[:6]:                          # 이 키워드에서 찾은 새 글 6개를 읽음
    storage.fm_seen_read(no)

def state():
    with storage._db() as conn:
        r = conn.execute("SELECT read_ids, found_ids FROM fm_seen WHERE keyword = '삼성'").fetchone()
    return json.loads(r['read_ids']), json.loads(r['found_ids'])

def unread():
    read, f = state()
    return [i for i in f if i not in set(read)]

assert unread() == found[6:], unread()
for i in range(700):                          # 다른 키워드의 글 700개를 읽음 (모든 키워드에 적힘)
    storage.fm_seen_read(BASE + 1000 + i)
read, _ = state()
assert len(read) == storage.MAX_FM_READ_IDS, len(read)
assert unread() == found[6:], unread()        # 읽은 6개는 그대로 읽음
assert all(no in read for no in found[:6])
assert BASE + 1000 + 699 in read and BASE + 1000 not in read   # 찾은 적 없는 글은 오래된 것부터 버림

# 찾은 글의 읽음만으로 넘치면 그중 오래된 것부터
assert storage._trim_fm_read_ids(list(range(600)), range(600)) == list(range(100, 600))
assert storage._trim_fm_read_ids([5, 3, 3], []) == [3, 5]
print('ok')
