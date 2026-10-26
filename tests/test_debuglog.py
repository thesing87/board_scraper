import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, io, tempfile, contextlib, threading
tmp = tempfile.mkdtemp()
os.environ['OUTPUT_DIR'] = tmp
os.environ['LOG_LEVEL'] = 'INFO'
import config

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    config.log_msg('[수집] 디버그 메시지', 'DEBUG')
    config.log_msg('[새 글] 인포 메시지')
    config.log_msg('[오류] 경고 메시지', 'WARN')
screen = buf.getvalue().splitlines()
debug_lines = open(config.DEBUG_LOG_FILE, encoding='utf-8').read().splitlines()
assert len(screen) == 2 and all('DEBUG' not in l for l in screen), screen
assert len(debug_lines) == 3 and '[DEBUG] [수집] 디버그 메시지' in debug_lines[0], debug_lines
print('screen:', screen)
print('file  :', debug_lines)

# 순환: 용량 제한을 작게 바꿔 여러 스레드에서 기록
config._debug_handler.maxBytes = 2000
with contextlib.redirect_stdout(io.StringIO()):
    ts = [threading.Thread(target=lambda i=i: [config.log_msg(f'thread {i} line {j} ' + 'x' * 50, 'DEBUG') for j in range(100)]) for i in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
files = sorted(os.listdir(os.path.dirname(config.DEBUG_LOG_FILE)))
sizes = {f: os.path.getsize(os.path.join(os.path.dirname(config.DEBUG_LOG_FILE), f)) for f in files}
assert files == ['debug.log', 'debug.log.1', 'debug.log.2', 'debug.log.3'], files
assert all(s <= 2200 for s in sizes.values()), sizes
print('rotation:', sizes)
print('DEBUG LOG OK')
