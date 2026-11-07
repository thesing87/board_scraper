import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# 넓은 화면: 첫 화면 아래쪽에서 시작해 높이가 줄어든 둘째 글의 댓글 칸이, 글을 위로 올리면 창 높이만큼 다시 늘어나는지
storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
comments = [{'author': f'u{i}', 'date': 'd', 'content': [f'댓글 {i}'], 'votes': '0', 'is_reply': False} for i in range(40)]
def save(pid, n_body, n_comments=40):
    storage.save_keyword_post('car', '싼타페', {'id': pid, 'title': f'글 {pid}', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                                'comment_count': str(n_comments), 'link': f'/{pid}', 'content': ['<p>본문</p>'] * n_body,
                                                'videos': [], 'comments': comments[:n_comments]}, is_new=False)
save('902', 200)   # 아래 글 (본문이 길어 칸이 위에 붙을 때까지 올릴 수 있음)
save('901', 4, 3)   # 위 글 (짧아서 둘째 글 칸이 첫 화면 아래쪽에서 시작)

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
box = "document.querySelector('#post-902 > .comments')"
try:
    d.get(f'http://127.0.0.1:{port}/board/'); time.sleep(2)
    js("app.filter = 'all'; openView(ALL_KEY, 1)"); time.sleep(2)
    top0 = js(f"return {box}.getBoundingClientRect().top")
    h0 = js(f"return {box}.clientHeight")
    assert top0 < js('return innerHeight') and js(f"return {box}.style.maxHeight") != '', (top0, js(f"return {box}.style.maxHeight"))
    vh = js("return innerHeight")
    # 반쯤 올리면 칸이 늘어나 창 아래 끝 근처까지
    js(f"window.scrollBy(0, {box}.getBoundingClientRect().top - 400)"); time.sleep(0.4)
    r = js(f"const r = {box}.getBoundingClientRect(); return [r.top, r.bottom]")
    assert r[1] > vh - 30 and js(f"return {box}.clientHeight") > h0, r
    # 위 메뉴 아래에 붙을 때까지 올리면 CSS 높이(창 높이 − 96)로
    js(f"window.scrollBy(0, {box}.getBoundingClientRect().top - 72 + 50)"); time.sleep(0.4)
    assert js(f"return {box}.style.maxHeight") == ''
    assert js(f"return {box}.clientHeight") >= vh - 96 - 4, js(f"return {box}.clientHeight")
    print('COMMENT BOX GROW OK')
finally:
    d.quit()
    srv.shutdown()
