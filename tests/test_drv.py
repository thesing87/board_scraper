import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, tempfile, importlib.util
os.environ['OUTPUT_DIR'] = tempfile.mkdtemp()
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Alive:
    def execute_script(self, s): return 1
class Dead:
    quit_called = False
    def execute_script(self, s): raise RuntimeError('session deleted')
    def quit(self): Dead.quit_called = True
m.create_driver = lambda: 'NEW'
a = Alive(); assert m.ensure_driver_alive(a) is a
assert m.ensure_driver_alive(Dead()) == 'NEW' and Dead.quit_called
# 주기 끝 메모리 정리: 빈 페이지로 옮긴 뒤 메모리 부족 신호·정리 요청, 실패해도 수집을 멈추지 않음
class Recorder:
    calls = []
    def get(self, url): self.calls.append(url)
    def execute_cdp_cmd(self, cmd, params): self.calls.append(cmd)
r = Recorder(); m.release_chrome_memory(r)
assert r.calls == ['about:blank', 'Memory.simulatePressureNotification', 'HeapProfiler.collectGarbage'], r.calls
class Broken:
    def get(self, url): raise RuntimeError('chrome gone')
m.release_chrome_memory(Broken())
print('DRIVER OK')
