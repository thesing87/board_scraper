import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket, sqlite3
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, config
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# 이미지 글 2개(첨부 2장 + 이모티콘, 첨부 1장), 동영상 글 1개(mp4 + 유튜브)
storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
img = lambda n, w=800: f'<img src="https://image.fmkorea.com/files/attach/new5/{n}.jpg" width="{w}">'
def save(pid, content, videos=()):
    storage.save_keyword_post('car', '싼타페', {'id': pid, 'title': f'글 {pid}', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                                'comment_count': '0', 'link': f'/{pid}', 'content': content,
                                                'videos': list(videos), 'comments': []}, is_new=True)
save('801', ['<p>본문</p>', img('a'), '<img src="https://www.fmkorea.com/modules/emoticon/x.gif">', img('b')])
save('802', [img('c')])
save('803', ['<p>영상</p>'], ['https://mediag5jvqbd.fmkorea.com/files/attach/new5/v.mp4',
                               'https://www.youtube.com/embed/_MUk-aKNZbQ?playsinline=1'])
db = sqlite3.connect(config.DB_FILE)
read_count = lambda: db.execute('SELECT COUNT(*) FROM read_posts').fetchone()[0]

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
for a in ['--headless=new', '--window-size=1440,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get(f'http://127.0.0.1:{port}/board/'); time.sleep(2)
    # 1) 이미지 보기: 글 대신 첨부 이미지만 격자로 (이모티콘 제외), 여러 장이면 몇 번째인지
    js("setFilter('image')"); time.sleep(2)
    db.execute('DELETE FROM read_posts'); db.commit()   # 첫 화면(안 읽은 글)에서 읽힌 기록은 지우고 모아보기만 봄
    cells = js("return [...document.querySelectorAll('.g-cell:not(.is-blank)')].map(c => [c.querySelector('img').getAttribute('src').split('/').pop(), c.querySelector('.g-count')?.textContent || ''])")
    assert sorted(cells) == [['a.jpg', '1/2'], ['b.jpg', '2/2'], ['c.jpg', '']], cells
    # 데스크톱: 한 페이지 12칸 고정(모자란 칸은 빈 칸), 스크롤 없이 한 화면
    assert js("return document.querySelectorAll('.g-cell.is-blank').length") == 9
    assert js("return document.documentElement.scrollHeight - innerHeight") <= 0
    assert '이미지 3개 중 1–3' in js("return document.querySelector('.feed-sub').textContent")
    assert js("return document.querySelectorAll('.post-card').length") == 0
    # 2) 크게 보기: 화살표로 넘기고 Esc로 닫음. 미디어만 봐서는 읽음 처리하지 않음
    js("document.querySelector('.g-open').click()")
    first = js("return document.querySelector('.mv-foot').textContent")
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}))")
    assert js("return document.querySelector('.mv-foot').textContent") != first and first.startswith('1 / 3')
    # A·D 키도 방향키처럼 이전·다음
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'd', bubbles: true}))")
    assert js("return document.querySelector('.mv-foot').textContent").startswith('3 / 3')
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'A', bubbles: true}))")
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'a', bubbles: true}))")
    assert js("return document.querySelector('.mv-foot').textContent").startswith('1 / 3')
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    assert js("return document.getElementById('media-viewer').hidden")
    time.sleep(2)
    assert read_count() == 0
    print('IMAGE GALLERY OK')

    # 3) 동영상 보기: mp4는 동영상, 유튜브는 미리보기 이미지. 크게 보기에서 재생
    js("setFilter('video')"); time.sleep(2)
    assert js("return app.galleryItems.map(i => i.type)") == ['file', 'youtube']
    assert 'i.ytimg.com/vi/_MUk-aKNZbQ' in js("return document.querySelectorAll('.g-open img')[0].src")
    js("document.querySelectorAll('.g-open')[1].click()")
    assert js("return document.querySelector('.mv-stage iframe').src").startswith('https://www.youtube.com/embed/')
    print('VIDEO GALLERY OK')

    # 4) 글 보기 → 그 글이 있는 화면으로 이동, '모아보기로' 버튼과 브라우저 뒤로로 돌아옴
    js("document.querySelector('#media-viewer [data-action=goto-post]').click()"); time.sleep(2.5)
    assert js("return location.hash") == '#post-803' and js("return app.filter") == 'all'
    assert js("return !!document.getElementById('post-803')") and js("return !!document.querySelector('[data-action=return-gallery]')")
    js("history.back()"); time.sleep(2.5)
    assert js("return app.filter") == 'video' and js("return document.querySelectorAll('.g-cell:not(.is-blank)').length") == 2
    js("document.querySelector('.g-go').click()"); time.sleep(2.5)
    js("document.querySelector('[data-action=return-gallery]').click()"); time.sleep(2)
    assert js("return app.filter") == 'video' and js("return location.hash") == ''
    print('GOTO POST AND BACK OK')

    # 5) 모아보기 페이지도 크게 보기와 같은 키: 좌우 화살표 또는 A·D (이미지 15장 → 2페이지)
    save('805', [img(f'p{i}') for i in range(12)])
    js("setFilter('image')"); time.sleep(2)
    page_key = lambda k: (js("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: arguments[0], bubbles: true}))", k), time.sleep(1.5))
    assert js("return app.totalPages") == 2
    page_key('d'); assert js("return app.page") == 2
    page_key('D'); assert js("return app.page") == 2      # 마지막 페이지에서는 그대로
    page_key('a'); assert js("return app.page") == 1
    page_key('ArrowRight'); assert js("return app.page") == 2
    page_key('ArrowLeft'); assert js("return app.page") == 1
    print('GALLERY PAGE KEYS OK')
finally:
    d.quit()
    srv.shutdown()
