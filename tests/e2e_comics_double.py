"""만화 보기의 두 페이지 보기: 넓은 화면은 '자동'으로 두 장씩(표지·가로로 긴 양면은 혼자), 한 페이지·두 페이지를 직접 고르기,
일본식은 앞 장이 오른쪽, 읽은 위치는 보이는 뒤 장으로 저장, 휴대폰 세로 화면은 한 장씩"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, socket, struct, zlib, zipfile, time

COMICS = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', COMICS_DIR=COMICS)
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options

def png(w, h, rgb):
    raw = b''.join(b'\x00' + bytes(rgb) * w for _ in range(h))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')

# 10장: 1(표지) 2 3 4 5 6(가로로 긴 양면) 7 8 9 10
with zipfile.ZipFile(os.path.join(COMICS, '시험.cbz'), 'w') as zf:
    for i in range(1, 11):
        zf.writestr(f'{i:02d}.png', png(80, 40, (i * 20, 0, 0)) if i == 6 else png(40, 60, (i * 20, 100, 0)))

# 목록 화면용: 시리즈 폴더(책 2권)와 이미지 없는 폴더
os.makedirs(os.path.join(COMICS, '시리즈'))
for v in (1, 2):
    with zipfile.ZipFile(os.path.join(COMICS, '시리즈', f'{v}권.cbz'), 'w') as zf:
        zf.writestr('01.png', png(40, 60, (0, 0, 200)))
os.makedirs(os.path.join(COMICS, '빈폴더'))
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
for a in ['--headless=new', '--window-size=1400,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
BOOK = '/comics/#b=' + '%EC%8B%9C%ED%97%98.cbz'
def views(): return js("return [...document.querySelectorAll('#pager .slot[data-v]')].map(s => [...s.querySelectorAll('.page')].map(p => +p.dataset.p + 1).join('|'))")
def count(): return js("return document.getElementById('reader-count').textContent")
def key(k, n=1):
    for _ in range(n):
        ActionChains(d).send_keys(k).perform()
        time.sleep(.6)
try:
    d.get(BASE + '/comics/')
    js("localStorage.setItem('admin_token', arguments[0]); localStorage.removeItem('comics_settings_v1')", web_server.ADMIN_TOKEN)
    d.get(BASE + '/comics/'); time.sleep(2)
    # 목록: 폴더도 책처럼 표지·이름·몇 권인지, 표지가 없는 폴더는 이름 첫 글자, 책도 표지와 이름
    cards = js("""return [...document.querySelectorAll('#folders .folder-card')].map(a => [a.querySelector('.book-name').textContent,
        a.querySelector('.folder-badge').textContent.trim(), !!(a.querySelector('img') && a.querySelector('img').naturalWidth),
        a.querySelector('.book-cover').classList.contains('no-cover')])""")
    assert cards == [['빈폴더', '', False, True], ['시리즈', '2권', True, False]], cards
    books = js("return [...document.querySelectorAll('#books .book')].map(a => [a.querySelector('.book-name').textContent, a.querySelector('img').naturalWidth > 0])")
    assert books == [['시험', True]], books
    # 폴더를 누르면 그 폴더 목록 (보기 화면이 열리지 않음)
    js("document.querySelectorAll('#folders .folder-card')[1].click()"); time.sleep(1.2)
    assert js("return location.hash").startswith('#d=') and js("return document.getElementById('reader').hidden")
    assert js("return document.querySelectorAll('#books .book').length") == 2
    print('LIST OK')
    d.get(BASE + BOOK); time.sleep(2)

    # 넓은 화면 '자동' = 두 페이지. 일본식(기본)은 칸이 뒤집혀 있고, 칸 안에서도 앞 장이 오른쪽
    v = views()
    assert v == ['10|9', '8|7', '6', '5|4', '3|2', '1'], v
    assert count() == '1 / 10'
    assert js("return document.getElementById('reader-layout-label').textContent") == '2쪽'
    key(Keys.ARROW_LEFT)            # 일본식: 왼쪽 키가 다음
    assert count() == '2-3 / 10', count()
    # 두 장이 높이를 맞춰 화면 가운데에서 맞붙음
    r = js("""const s = [...document.querySelectorAll('#pager .slot.is-pair')].find(s => s.getBoundingClientRect().left >= 0 && s.getBoundingClientRect().left < 5);
              const [a, b] = [...s.querySelectorAll('.page')].map(p => p.getBoundingClientRect());
              return [a.right, b.left, a.height, b.height, a.width + b.width, innerWidth, innerHeight, s.querySelector('.page').dataset.p];""")
    assert abs(r[0] - r[1]) < 1.5 and abs(r[2] - r[3]) < 1.5 and r[4] <= r[5] + 1 and r[2] <= r[6] + 1, r
    assert r[7] == '2', r          # 왼쪽이 3쪽(번호 2), 오른쪽이 2쪽
    # 이미지가 붙음
    time.sleep(1)
    assert js("return [...document.querySelectorAll('#pager .slot.is-pair .page')].filter(p => p.style.backgroundImage).length") >= 2
    key(Keys.ARROW_LEFT, 2)
    assert count() == '6 / 10', count()   # 가로로 긴 양면은 혼자
    # 읽은 위치는 보이는 뒤 장
    key(Keys.ARROW_RIGHT)
    assert count() == '4-5 / 10'
    time.sleep(1.5)
    js("document.getElementById('reader-close').click()"); time.sleep(1)
    assert '5/10' in js("return document.body.innerText"), js("return document.body.innerText")[:300]
    print('AUTO DOUBLE OK')

    # 다시 열면 그 칸부터, 위쪽 버튼으로 한 페이지
    d.get('about:blank')
    d.get(BASE + BOOK); time.sleep(2)
    assert count() == '4-5 / 10', count()
    js("document.getElementById('reader-layout-btn').click()"); time.sleep(.8)
    assert len(views()) == 10 and count() == '5 / 10', (views(), count())
    assert js("return document.getElementById('reader-layout-label').textContent") == '1쪽'
    assert js("return JSON.parse(localStorage.getItem('comics_settings_v1')).layout") == 'single'
    # 설정 창: 두 페이지 + 표지 따로 끄기 → 1|2, 3|4 …
    js("document.getElementById('reader-settings-btn').click()")
    js("document.querySelector('#set-layout [data-v=double]').click()"); time.sleep(.6)
    assert not js("return document.getElementById('set-cover-row').hidden") and js("return document.getElementById('set-split-row').hidden")
    js("document.getElementById('set-cover').click()"); time.sleep(.6)
    v = views()
    assert v == ['10|9', '8|7', '6', '5', '4|3', '2|1'], v     # 6쪽 앞의 5쪽은 짝이 없어 혼자
    # 왼쪽부터 읽기: 칸 순서와 칸 안 순서가 바뀜 (앞 장이 왼쪽)
    js("document.querySelector('#set-dir [data-v=ltr]').click()"); time.sleep(.6)
    assert views() == ['1|2', '3|4', '5', '6', '7|8', '9|10'], views()
    # 위아래 넘김은 늘 한 페이지, 고르기 버튼은 잠김
    js("document.querySelector('#set-dir [data-v=vertical]').click()"); time.sleep(.6)
    assert len(views()) == 10 and js("return document.querySelector('#set-layout [data-v=double]').disabled")
    assert js("return document.getElementById('reader-layout-btn').hidden")
    print('CHOOSE OK')

    # 휴대폰 세로 화면: '자동'은 한 페이지
    js("localStorage.setItem('comics_settings_v1', JSON.stringify({dir: 'rtl', layout: 'auto', split: true, cover: true}))")
    d.get('about:blank')
    d.set_window_size(390, 844); time.sleep(.5)
    d.get(BASE + BOOK); time.sleep(2)
    assert all('|' not in x for x in views()), views()
    assert js("return document.getElementById('reader-layout-label').textContent") == '1쪽'
    # 휴대폰에서도 두 페이지를 직접 고를 수 있음
    js("document.getElementById('reader-layout-btn').click()"); time.sleep(.8)
    assert any('|' in x for x in views()), (views(), js("return localStorage.getItem('comics_settings_v1')"), js("return [innerWidth, innerHeight, document.getElementById('reader-layout-btn').hidden]"))
    assert js("return document.documentElement.scrollWidth <= innerWidth + 1")
    print('MOBILE OK')
finally:
    d.quit()
    srv.shutdown()
