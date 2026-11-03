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
# 크롬이 응답하지 않으면(셀레늄 응답 대기 시간 초과) 표시하고, 그 뒤 명령은 기다리지 않고 바로 실패 (종료 명령만 보냄)
import urllib3
class FakeBase:
    sent = []
    def execute(self, command, params=None):
        self.sent.append(command)
        if command == 'get':
            raise urllib3.exceptions.ReadTimeoutError(None, '/session/x/url', 'Read timed out. (read timeout=120)')
        return {'value': 1}
class Guarded(m.HungGuard, FakeBase):
    pass
g = Guarded()
assert g.execute('executeScript') == {'value': 1} and not g.hung
try:
    g.execute('get'); raise AssertionError('시간 초과가 전달되지 않음')
except urllib3.exceptions.ReadTimeoutError:
    pass
assert g.hung
try:
    g.execute('findElement'); raise AssertionError('멈춘 크롬에 명령을 보냄')
except m.ChromeHungError:
    pass
g.execute('quit')
assert g.sent == ['executeScript', 'get', 'quit'], g.sent
# 메인 루프는 키워드마다 확인해 멈춘 크롬만 새로 띄움
quits = []
g.quit = lambda: quits.append(1)
assert m.restart_if_hung(g) == 'NEW' and quits == [1]
alive = Alive()
assert m.restart_if_hung(alive) is alive
print('DRIVER OK')
