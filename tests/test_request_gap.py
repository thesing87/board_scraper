import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
sys.path.insert(0, os.path.join(ROOT, 'app'))

# 에펨코리아 요청 간격: 앞 요청이 끝난 뒤 3~6초가 지나야 다음 페이지를 엶 (페이지가 늦게 열리면 그만큼 덜 기다림)
import scraper

clock = [1000.0]
slept = []
scraper.time.monotonic = lambda: clock[0]
def fake_sleep(sec):
    slept.append(sec)
    clock[0] += sec
scraper.time.sleep = fake_sleep

class Driver:
    def __init__(self, load_seconds):
        self.load, self.opened = load_seconds, []
    def get(self, url):
        self.opened.append((url, clock[0]))
        clock[0] += self.load

d = Driver(load_seconds=1.0)
for k in range(30):
    scraper.open_page(d, f'u{k}')
starts = [t for _, t in d.opened]
ends = [t + 1.0 for t in starts]
gaps = [starts[k + 1] - ends[k] for k in range(len(starts) - 1)]
assert all(scraper.FM_REQUEST_GAP_MIN - 1e-9 <= g <= scraper.FM_REQUEST_GAP_MAX + 1e-9 for g in gaps), gaps
assert len(set(round(g, 3) for g in gaps)) > 5   # 매번 같은 간격이 아님

# 페이지가 오래 걸려도 간격은 끝난 시점부터
slow = Driver(load_seconds=20.0)
scraper.open_page(slow, 'a'); scraper.open_page(slow, 'b')
assert scraper.FM_REQUEST_GAP_MIN <= slow.opened[1][1] - (slow.opened[0][1] + 20) <= scraper.FM_REQUEST_GAP_MAX

# 이미 충분히 쉬었으면 기다리지 않음
clock[0] += 100
slept.clear()
scraper.open_page(d, 'late')
assert slept == []

# 페이지 열기가 실패해도 다음 요청은 간격을 지킴
class Broken:
    def get(self, url):
        clock[0] += 2
        raise RuntimeError('timeout')
try:
    scraper.open_page(Broken(), 'x')
except RuntimeError:
    pass
slept.clear()
scraper.open_page(d, 'after-error')
assert slept and scraper.FM_REQUEST_GAP_MIN <= slept[0] <= scraper.FM_REQUEST_GAP_MAX
print('REQUEST GAP OK')

# 메일: 기다리는 동안 25초마다 NOOP으로 연결 유지 (네이버가 쉬는 연결을 끊음)
import card_mail
mclock = [0.0]
card_mail.time.monotonic = lambda: mclock[0]
card_mail.time.sleep = lambda s: mclock.__setitem__(0, mclock[0] + s)
class Conn:
    def __init__(self): self.noops = []
    def noop(self): self.noops.append(mclock[0]); return 'OK', [b'NOOP completed.']
c = Conn()
card_mail.keep_alive_sleep(c, 90)
assert mclock[0] == 90 and c.noops == [25, 50, 75], c.noops
assert all(b - a <= card_mail.KEEPALIVE_SECONDS for a, b in zip([0] + c.noops, c.noops + [90]))
print('MAIL KEEPALIVE OK')
