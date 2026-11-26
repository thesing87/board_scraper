"""동영상 썸네일: 영상 길이의 가운데(50%) 장면을 뽑음. 길이를 모르면 10초 → 처음 장면.
변환 작업기가 썸네일 없는 영상을 최근 것부터 찾아 미리 만들고, 쓰지 않게 된 썸네일은 지움 (ffmpeg는 가짜로 바꿔 시험)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, subprocess, types

VIDEOS = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', VIDEOS_DIR=VIDEOS)
import videos, video_convert, storage
storage.init_db()

open(os.path.join(VIDEOS, 'a.mp4'), 'wb').write(b'a' * 10)
open(os.path.join(VIDEOS, 'b.mp4'), 'wb').write(b'b' * 10)
videos._ffmpeg = lambda: 'ffmpeg'
seeks = []
DURATION = {'a.mp4': '  Duration: 01:00:00.00, start: 0.000000, bitrate: 1000 kb/s', 'b.mp4': ''}


def fake_run(args, **kw):
    name = os.path.basename(args[args.index('-i') + 1])
    if '-frames:v' not in args:
        return types.SimpleNamespace(stderr=DURATION[name])
    seek = args[args.index('-ss') + 1]
    seeks.append((name, seek))
    if name == 'a.mp4' or seek == '0':
        open(args[-1], 'wb').write(b'jpg')
    return types.SimpleNamespace(stderr='')


subprocess.run = fake_run
data, tag = videos.thumbnail('a.mp4')
assert data == b'jpg' and tag.startswith('m')
assert seeks == [('a.mp4', '1800.00')], seeks
# 한 번 뽑으면 저장한 것을 씀
seeks.clear()
assert videos.thumbnail('a.mp4')[0] == b'jpg' and seeks == []
# 길이를 모르면 10초 → 처음
assert videos.thumbnail('b.mp4')[0] == b'jpg'
assert seeks == [('b.mp4', '10'), ('b.mp4', '0')], seeks

# ---- 미리 만들기: 썸네일 없는 영상만, 최근에 들어온 것부터, 방금 바뀐(복사 중일 수 있는) 영상은 미룸
import time
now = time.time()
os.makedirs(os.path.join(VIDEOS, '새 폴더'))
for name, age in (('old.mp4', 3000), ('new.mp4', 600), ('zz_copying.mp4', 10)):
    full = os.path.join(VIDEOS, '새 폴더', name)
    open(full, 'wb').write(name.encode())
    os.utime(full, (now - age, now - age))
    DURATION[name] = '  Duration: 00:10:00.00'
missing = [os.path.basename(f) for f, _ in video_convert.missing_thumbnails(now=now)]
assert missing == ['new.mp4', 'old.mp4'], missing          # a·b는 이미 있음, copying은 미룸
# 전에 실패한 썸네일은 빼고
skip = {videos.thumb_path(os.path.join(VIDEOS, '새 폴더', 'new.mp4'))[0]}
assert [os.path.basename(f) for f, _ in video_convert.missing_thumbnails(skip, now=now)] == ['old.mp4']
for full, path in video_convert.missing_thumbnails(now=now):
    assert videos.make_thumbnail(full) == path and os.path.exists(path)
assert video_convert.missing_thumbnails(now=now) == []
# 폴더 썸네일은 그 폴더 첫 영상의 것을 그대로 씀 (따로 뽑지 않음)
seeks.clear()
assert videos.thumbnail('새 폴더')[0] == b'jpg' and seeks == []

# ---- 정리: 지금 영상의 썸네일은 두고, 영상이 바뀌거나 없어진 썸네일은 하루가 지나면 지움
gone = os.path.join(videos.THUMB_DIR, 'zz', 'zz.jpg')
os.makedirs(os.path.dirname(gone), exist_ok=True)
open(gone, 'wb').write(b'x')
fresh = os.path.join(videos.THUMB_DIR, 'zz', 'fresh.jpg')
open(fresh, 'wb').write(b'x')
os.utime(gone, (now - 2 * 86400, now - 2 * 86400))
kept = [videos.thumb_path(os.path.join(VIDEOS, n))[0] for n in ('a.mp4', 'b.mp4')]
for k in kept:
    os.utime(k, (now - 2 * 86400, now - 2 * 86400))
assert video_convert.cleanup_thumbnails(now=now) == 1
assert not os.path.exists(gone) and os.path.exists(fresh) and all(os.path.exists(k) for k in kept)
print('OK')
