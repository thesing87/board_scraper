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

# 이미 읽은 글에 새 댓글 40개: 본문이 길어 글 끝은 화면 밖, 넓은 화면에서는 댓글 칸이 따로 스크롤됨
storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
comments = [{'author': f'u{i}', 'date': 'd', 'content': [f'댓글 {i}'], 'votes': '0', 'is_reply': False} for i in range(40)]
storage.save_keyword_post('car', '싼타페', {'id': '801', 'title': '싼타페', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                            'comment_count': '40', 'link': '/801', 'content': ['<p>본문</p>'] * 200,
                                            'videos': [], 'comments': comments}, is_new=False)
storage.mark_posts_read(['801'])
db = sqlite3.connect(config.DB_FILE)
db.execute("UPDATE read_posts SET read_at = '2000-01-01 00:00:00'"); db.commit()
read_at = lambda: db.execute('SELECT read_at FROM read_posts').fetchone()[0]

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
    d.get(f'http://127.0.0.1:{port}/'); time.sleep(2)
    js("app.filter = 'comments'; openView(ALL_KEY, 1)"); time.sleep(2)
    assert js("return document.querySelectorAll('.comment.is-new-comment').length") == 40
    assert js("const c = document.querySelector('.post-card > .comments'); return c.scrollHeight > c.clientHeight")
    # 본문을 조금 내려 댓글 칸이 화면에 붙게 함 (창 스크롤로도 확인은 돌지만 마지막 새 댓글은 칸 안에 가려져 있음)
    js("window.scrollTo(0, 300)"); time.sleep(2.5)
    assert read_at().startswith('2000'), '마지막 새 댓글이 아직 안 보이므로 확인 전'
    # 창은 그대로 두고 댓글 칸만 맨 아래로 → 마지막 새 댓글을 본 것
    js("const c = document.querySelector('.post-card > .comments'); c.scrollTop = c.scrollHeight")
    time.sleep(3)
    assert js("return window.scrollY") == 300
    assert not read_at().startswith('2000'), read_at()
    print('COMMENT BOX SCROLL READ OK')
finally:
    d.quit()
    srv.shutdown()
