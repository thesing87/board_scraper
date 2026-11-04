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

# 사진 6장(+이모티콘)·동영상 1개가 있는 글, 사진 2장만 있는 글(본문 글자 없음), 글자만 있는 글
storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
img = lambda n: f'<img src="https://image.fmkorea.com/files/attach/new5/{n}.jpg" width="800">'
def save(pid, content, videos=()):
    storage.save_keyword_post('car', '싼타페', {'id': pid, 'title': f'글 {pid}', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                                'comment_count': '0', 'link': f'/{pid}', 'content': content,
                                                'videos': list(videos), 'comments': []}, is_new=True)
save('801', ['<p>글자만 있는   글입니다</p>', '', '<p>둘째 <b>줄</b></p>'])
save('802', [img('x'), img('y')])
save('803', ['<p>출고 후기</p>', '<img src="https://www.fmkorea.com/modules/emoticon/x.gif">'] + [img(f'a{i}') for i in range(6)],
     ['https://mediag5jvqbd.fmkorea.com/files/attach/new5/v.mp4'])
db = sqlite3.connect(config.DB_FILE)

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
visible = lambda sel: js("return [...document.querySelectorAll(arguments[0])].filter(e => e.offsetWidth > 0).length", sel)
try:
    d.get(f'http://127.0.0.1:{port}/'); time.sleep(2.5)
    js("app.filter = 'all'; openView(ALL_KEY, 1)"); time.sleep(1.5)
    # 1) 펼친 화면에서는 미리보기를 숨기고, 접으면 본문 한 줄과 썸네일
    assert visible('.fold-preview') == 0
    js("toggleFold()"); time.sleep(0.5)
    db.execute('DELETE FROM read_posts'); db.commit()   # 접기 전 첫 화면에서 읽힌 짧은 글 기록은 지우고 봄
    assert js("return document.querySelector('#post-801 .fold-excerpt').textContent") == '글자만 있는 글입니다 둘째 줄'
    assert js("return document.querySelector('#post-801 .fold-thumbs')") is None
    assert js("return document.querySelector('#post-802 .fold-excerpt')") is None and visible('#post-802 .fold-thumb') == 2
    assert js("return document.querySelector('#post-801 .fold-excerpt').offsetHeight") < 24   # 한 줄
    # 2) 7개(동영상 먼저, 이모티콘 제외) → 3개 + '+4', 누르면 전부, 다시 누르면 3개 (글은 펼치지 않음)
    assert visible('#post-803 .fold-thumb') == 4
    assert js("return document.querySelector('#post-803 .fold-thumb').classList.contains('is-video')")
    more = "document.querySelector('#post-803 .fold-more')"
    assert js(f"return {more}.textContent") == '+4'
    js(f"{more}.click()"); time.sleep(0.2)
    assert visible('#post-803 .fold-thumb') == 8 and js(f"return {more}.textContent") == '접기'
    assert not js("return document.getElementById('post-803').classList.contains('is-open')")
    js(f"{more}.click()"); time.sleep(0.2)
    assert visible('#post-803 .fold-thumb') == 4
    print('PREVIEW OK')

    # 3) 썸네일 → 그 글의 사진·동영상만 크게 보기, '이 글로 이동'은 그 자리에서 글을 펼침 (주소는 그대로)
    js("document.querySelectorAll('#post-803 .fold-thumb')[1].click()"); time.sleep(0.5)
    assert js("return document.querySelector('.mv-foot').textContent").startswith('2 / 7')
    js("document.querySelector('#media-viewer [data-action=goto-post]').click()"); time.sleep(0.8)
    assert js("return document.getElementById('media-viewer').hidden")
    assert js("return document.getElementById('post-803').classList.contains('is-open')") and js("return location.hash") == ''
    assert visible('#post-803 .fold-preview') == 0 and visible('#post-803 .post-content') == 1
    # 접힌 채 화면에 보인 글도 읽음
    time.sleep(2)
    assert {'801', '802', '803'} <= {r[0] for r in db.execute('SELECT post_id FROM read_posts')}
    print('PREVIEW VIEWER OK')

    # 4) 모바일: 썸네일 4칸
    d.set_window_size(390, 900); time.sleep(0.8)
    js("app.openPostIds.clear(); applyFold()")
    assert js("return getComputedStyle(document.querySelector('#post-803 .fold-thumbs')).gridTemplateColumns.split(' ').length") == 4
    print('PREVIEW MOBILE OK')
finally:
    d.quit()
    srv.shutdown()
