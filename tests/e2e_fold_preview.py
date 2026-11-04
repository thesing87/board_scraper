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
save('804', ['<p>' + '아주 긴 본문 글자 ' * 60 + '</p>'])   # 한 줄이 카드 폭보다 훨씬 긴 글
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
    # 0) 조회·추천·댓글 칩: 추천 0도 표시, 조회 100·500·1000회, 추천·댓글 1·10·20개부터 4단계로 진해짐
    assert js("return [...document.querySelectorAll('#post-801 .stat')].map(s => s.textContent.trim())") == ['조회1', '추천0', '댓글0']
    assert js("return document.querySelector('#post-801 .stat-votes').className") == 'stat stat-votes'
    assert js("return [0, 1, 9, 10, 19, 20].map(n => statLevel(n, STAT_LEVELS.votes))") == ['', ' is-some', ' is-some', ' is-warm', ' is-warm', ' is-hot']
    assert js("return [0, 1, 10, 20].map(n => statLevel(n, STAT_LEVELS.comments))") == ['', ' is-some', ' is-warm', ' is-hot']
    assert js("return [99, 100, 499, 500, 999, 1000].map(n => statLevel(n, STAT_LEVELS.views))") == ['', ' is-some', ' is-some', ' is-warm', ' is-warm', ' is-hot']
    assert js("return document.querySelector('#post-801 .stat-views').className") == 'stat stat-views'   # 조회 1
    assert js("return statNumber('1,204')") == 1204
    # 1) 펼친 화면에서는 미리보기를 숨기고, 접으면 본문 한 줄과 썸네일
    assert visible('.fold-preview') == 0
    js("toggleFold()"); time.sleep(0.5)
    db.execute('DELETE FROM read_posts'); db.commit()   # 접기 전 첫 화면에서 읽힌 짧은 글 기록은 지우고 봄
    assert js("return document.querySelector('#post-801 .fold-excerpt').textContent") == '글자만 있는 글입니다 둘째 줄'
    assert js("return document.querySelector('#post-801 .fold-thumbs')") is None
    assert js("return document.querySelector('#post-802 .fold-excerpt')") is None and visible('#post-802 .fold-thumb') == 2
    assert js("return document.querySelector('#post-801 .fold-excerpt').offsetHeight") < 24   # 한 줄
    # 넓은 화면(2단 배치)에서도 긴 본문 한 줄은 카드 폭 안에서 말줄임으로 잘림
    assert js("const e = document.querySelector('#post-804 .fold-excerpt'), c = e.closest('.post-card'); "
              "return e.getBoundingClientRect().right <= c.getBoundingClientRect().right && e.scrollWidth > e.clientWidth")
    assert js("return document.documentElement.scrollWidth <= innerWidth")
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
    # 접힌 채 화면에 보인 글도 읽음 (맨 아래까지 내려 봄)
    js("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(2.5)
    # (첫 화면에 들어온 글은 위에서 기록을 지우기 전에 이미 보냈으므로 화면의 읽음 표시로 확인, 맨 아래 글은 서버 기록까지)
    assert js("return [...document.querySelectorAll('.read-sentinel')].every(e => e.dataset.read === '1')")
    assert '801' in {r[0] for r in db.execute('SELECT post_id FROM read_posts')}
    print('PREVIEW VIEWER OK')

    # 4) 모바일: 썸네일 4칸
    d.set_window_size(390, 900); time.sleep(0.8)
    js("app.openPostIds.clear(); applyFold()")
    assert js("return getComputedStyle(document.querySelector('#post-803 .fold-thumbs')).gridTemplateColumns.split(' ').length") == 4
    print('PREVIEW MOBILE OK')
finally:
    d.quit()
    srv.shutdown()
