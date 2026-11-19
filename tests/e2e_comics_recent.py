"""만화 이어 읽기 목록(맨 위 폴더): 읽다 만 책은 쪽수와 함께, 다 읽은 책은 같은 폴더의 다음 권을 '다음 권'으로,
× 단추로 목록에서 지우면(책은 열지 않음) 다시 열어도 안 나옴"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, socket, struct, zlib, zipfile, time, urllib.parse

COMICS = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', COMICS_DIR=COMICS)
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, comics
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options


def png(w, h, rgb):
    raw = b''.join(b'\x00' + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


for series, vols in (('나루토', (1, 2, 3)), ('원피스', (1, 2))):
    os.makedirs(os.path.join(COMICS, series))
    for v in vols:
        with zipfile.ZipFile(os.path.join(COMICS, series, f'{v}권.cbz'), 'w') as zf:
            for p in range(1, 6):
                zf.writestr(f'{p:02d}.png', png(40, 60, (v * 40, p * 30, 0)))
storage.init_db()
# 나루토 1권은 다 읽음(5쪽 중 5쪽) → 다음 권 2권, 원피스 1권은 3쪽까지 읽음
comics._now = lambda: '2026-11-20 10:00:00'
comics.save_progress('나루토/1권.cbz', 4, 5)
comics._now = lambda: '2026-11-20 11:00:00'
comics.save_progress('원피스/1권.cbz', 2, 5)

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
for a in ['--headless=new', '--window-size=1280,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
items = lambda: js("return [...document.querySelectorAll('#recent-list .recent-item')].map(a => [a.querySelector('.recent-name').textContent, a.querySelector('.recent-folder').textContent.trim(), a.getAttribute('href')])")
try:
    d.get(BASE + '/comics/')
    js("localStorage.setItem('admin_token', arguments[0])", web_server.ADMIN_TOKEN)
    d.get(BASE + '/comics/'); time.sleep(2)
    assert not js("return document.getElementById('recent').hidden")
    assert js("return document.querySelector('#recent h2').textContent") == '이어 읽기'
    got = items()
    assert [g[0] for g in got] == ['1권', '2권'], got
    assert got[0][1] == '원피스 · 3/5' and got[1][1] == '다음 권1권 다 읽음' and urllib.parse.unquote(got[1][2]) == '#b=나루토/2권.cbz', got
    # × 단추: 목록에서만 지우고 책은 열지 않음
    js("document.querySelectorAll('#recent-list .recent-forget')[1].click()"); time.sleep(1.2)
    assert [g[0] for g in items()] == ['1권'] and not js("return location.hash.startsWith('#b=')"), (items(), js("return location.hash"))
    d.get(BASE + '/comics/'); time.sleep(2)
    assert [g[1] for g in items()] == ['원피스 · 3/5'], items()
    # 누르면 그 책을 열고, 닫으면 목록으로
    js("document.querySelector('#recent-list .recent-item').click()"); time.sleep(2)
    assert js("return location.hash").startswith('#b='), js("return location.hash")
    js("document.querySelectorAll('#recent-list .recent-forget').forEach(b => b.click())")
    # 휴대폰 화면에서 넘치지 않음
    d.get(BASE + '/comics/'); time.sleep(1.5)
    d.set_window_size(390, 844); time.sleep(.5)
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('COMICS RECENT OK')
finally:
    d.quit()
    srv.shutdown()
