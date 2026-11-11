import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket, json, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, runtime_status
from datetime import datetime
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

# 메인 대시보드(/)·키워드 게시판(/board/)·유지비 계산기(/ev/)
storage.init_db()
gid = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])[0]
storage.save_group(None, '캐스퍼', [{'board': 'car', 'keyword': '캐스퍼'}])
def save(pid, kw, title, votes='0'):
    storage.save_keyword_post('car', kw, {'id': pid, 'title': title, 'author': 'a', 'date': 'd', 'views': '1', 'votes': votes,
                                          'comment_count': '0', 'link': f'/{pid}', 'content': ['<p>본문</p>'], 'videos': [], 'comments': []},
                              is_new=True)
save('601', '싼타페', '첫 글')
save('602', '싼타페', '둘째 <글>', '12')
save('603', '캐스퍼', '셋째 글')
storage.mark_posts_read(['603'])
runtime_status.update(last_cycle={'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'seconds': 100,
                                  'new': 1, 'updated': 0, 'deleted': 0, 'errors': 2})

with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

# API·주소
dash = json.load(urllib.request.urlopen(BASE + '/api/dashboard'))
assert dash['today_count'] == 3 and [p['id'] for p in dash['recent']] == ['603', '602', '601'], dash
assert dash['recent'][0]['is_read'] and dash['recent'][1]['group'] == '싼타페' and dash['collector']['errors'] == 2
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
for path in ('/board', '/ev'):
    try:
        urllib.request.build_opener(NoRedirect).open(BASE + path)
        raise AssertionError(path)
    except urllib.error.HTTPError as e:
        assert e.code == 301 and e.headers['Location'] == path + '/'
for path in ('/', '/board/', '/ev/', '/dashboard.js', '/ev.js'):
    assert urllib.request.urlopen(BASE + path).status == 200, path
print('ROUTES OK')

o = Options()
for a in ['--headless=new', '--window-size=1440,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get(BASE + '/'); time.sleep(2)
    assert d.title == '대시보드'
    assert js("return [...document.querySelectorAll('#card-board .met-value')].map(e => e.textContent)") == ['2', '0', '3']
    assert js("return document.getElementById('board-sub').textContent") == '게시판 2개 · 키워드 2개'
    assert js("return [...document.querySelectorAll('#card-board .chip')].map(c => c.textContent.replace(/\\s+/g, ' ').trim())") == ['싼타페 2']
    titles = js("return [...document.querySelectorAll('#board-body .post-title')].map(e => e.textContent)")
    assert titles == ['셋째 글', '둘째 <글>', '첫 글'], titles   # 제목은 글자 그대로 (HTML로 해석하지 않음)
    assert js("return document.querySelector('.post').classList.contains('is-read')")
    assert '추천 12' in js("return document.querySelectorAll('.post-meta')[1].textContent")
    foot = js("return document.querySelector('#card-board .card-foot').textContent.replace(/\\s+/g, ' ')")
    assert '수집 중' in foot and '오류 2' in foot, foot
    # 유지비 카드: 저장값이 없으면 계산기 기본값 (월 1,500km, 전기차 9.7만원 절약)
    assert '기본값' in js("return document.querySelector('.ev-head').textContent")
    assert js("return document.querySelector('.ev-big').textContent") == '전기차가 월 9.7만원 절약'
    print('DASHBOARD OK')

    # 칩 → 그 게시판, 최근 글 → 게시판의 그 글
    js("document.querySelector('#card-board .chip').click()"); time.sleep(2.5)
    assert d.current_url == BASE + '/board/' and js("return app.activeKey") == f'group:{gid}'
    assert js("return !!document.querySelector('.dash-link[href=\"/\"]')")
    d.get(BASE + '/'); time.sleep(1.5)
    js("document.querySelectorAll('.post')[1].click()"); time.sleep(3)
    assert js("return !!document.getElementById('post-602')") and js("return app.activeKey") == f'group:{gid}'
    # 예전 텔레그램 링크(/#post-ID)는 게시판의 그 글로
    d.get(BASE + '/#post-601'); time.sleep(3)
    assert d.current_url.startswith(BASE + '/board/') and js("return !!document.getElementById('post-601')")
    print('LINKS OK')

    # 계산기에서 값을 바꾸면 대시보드 카드에 반영 (월 3,000km → 절약액 2배)
    d.get(BASE + '/ev/'); time.sleep(1.5)
    assert js("return document.querySelector('.back').getAttribute('href')") == '/'
    assert js("return document.getElementById('sumBig').textContent") == '전기차가 9.7만원 절약'
    js("const i = document.getElementById('dist'); i.value = 3000; i.dispatchEvent(new Event('input'))")
    d.get(BASE + '/'); time.sleep(1.5)
    assert js("return document.querySelector('.ev-big').textContent") == '전기차가 월 19.4만원 절약'
    assert '마지막 입력값' in js("return document.querySelector('.ev-head').textContent")
    # 모바일: 한 줄, 최근 글 2개
    d.set_window_size(390, 844); time.sleep(0.8)
    assert js("return [...document.querySelectorAll('.post')].filter(e => e.offsetWidth > 0).length") == 2
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('EV + MOBILE OK')
finally:
    d.quit()
    srv.shutdown()
