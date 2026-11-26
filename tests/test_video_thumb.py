"""동영상 썸네일: 영상 길이의 가운데(50%) 장면을 뽑음. 길이를 모르면 10초 → 처음 장면 (ffmpeg는 가짜로 바꿔 시험)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, subprocess, types

VIDEOS = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', VIDEOS_DIR=VIDEOS)
import videos

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
print('OK')
