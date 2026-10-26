import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, threading, time, json, urllib.request
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN')
import storage, web_server
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18097), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:18097/'
SHOTS = shot_dir('unread_shots')
summary = storage.unread_summary()
print('unread total', summary['total'])
assert summary['total'] > 20

o = Options()
for a in ['--headless=new', '--window-size=1440,900']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
W = time.sleep
def view():
    return js("""return {title: document.querySelector('.feed-title').textContent, sub: document.querySelector('.feed-sub').textContent,
        page: app.page, ids: [...document.querySelectorAll('.post-card')].map(c => c.id.slice(5)),
        nav: [...document.querySelectorAll('.kw-item')].slice(0, 2).map(b => b.textContent.replace(/\\s+/g, ' ').trim())}""")
try:
    # 1) 처음 들어오면 안 읽은 글 모아보기
    d.get(BASE); W(2.5)
    v = view(); print('first screen', v['title'], '|', v['sub'], '|', v['nav'])
    # 화면에 다 보인 짧은 글은 바로 읽음 처리되므로 지금 서버 기준 개수와 비교
    now_total = storage.unread_summary()['total']
    assert v['title'] == '안 읽은 글' and f"{now_total}개" in v['sub'] and v['nav'][0] == f'안 읽은 글 {now_total}'
    assert v['ids'] == summary['unread_ids'][:10]
    d.save_screenshot(os.path.join(SHOTS, '1_unread.png'))

    # 2) 1페이지를 읽어도 2페이지가 밀리지 않음 (연 시각 기준 목록 유지)
    storage.mark_posts_read(v['ids'])
    js("document.querySelector('[data-action=\"page\"][data-target=\"next\"]').click()"); W(1.5)
    v2 = view(); print('page 2 first ids', v2['ids'][:3])
    assert v2['page'] == 2 and v2['ids'] == summary['unread_ids'][10:20]

    # 3) 새로고침 버튼 → 이미 읽은 글은 빠짐
    js("document.querySelector('.desktop-only[data-action=\"refresh\"]').click()"); W(2)
    js("app.page = 1; loadPosts()"); W(1.5)
    v3 = view(); now = storage.unread_summary()
    print('after refresh', v3['ids'][:2], v3['sub'])
    assert v3['ids'][:5] == now['unread_ids'][:5] and not set(v3['ids']) & set(v['ids']) and f"{now['total']}개" in v3['sub'], v3

    # 4) 안 읽은 글 보기 중 새 글이 들어오면 배너
    post = {'id': '10999999990', 'title': '새로 들어온 글', 'author': 't', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/10999999990', 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}
    storage.save_keyword_post('car', '싼타페', post, is_new=True)
    js("return pollState()"); W(1.5)
    banner = js("const b = document.getElementById('new-banner'); return b.hidden ? '' : b.textContent.trim()")
    print('banner', banner)
    assert '새 글 1개' in banner

    # 5) 다 읽으면 다음 방문의 첫 화면은 전체. 이미 읽은 글을 다시 읽어도(읽은 시각 갱신)
    #    '안 읽은 글' 보기에 다시 나타나지 않음 (전체 화면에서 맨 위 글이 다시 읽음 처리됨)
    storage.mark_posts_read(storage.unread_summary()['unread_ids'])
    assert storage.unread_summary()['total'] == 0
    js("sessionStorage.clear()"); d.get(BASE); W(2.5)
    v5 = view(); print('no unread first screen', v5['title'])
    assert v5['title'] == '전체'
    # 안 읽은 글 보기로 가면 빈 화면 + 전체 보기 버튼
    js("document.querySelector('[data-action=\"open-unread\"]').click()"); W(1.2)
    empty = js("return document.querySelector('.empty-card').textContent.trim()")
    print('empty', empty)
    assert '안 읽은 글이 없습니다' in empty and '전체 보기' in empty
    js("document.querySelector('.empty-card [data-action=\"open-all\"]').click()"); W(1.2)
    assert view()['title'] == '전체'
    # 홈 버튼도 같은 규칙
    js("document.querySelector('[data-action=\"open-unread\"]').click()"); W(1.2)
    js("document.querySelector('a.brand-name').click()"); W(1.2)
    assert view()['title'] == '전체'

    # 6) 모바일 칩 맨 앞이 안 읽은 글
    d.set_window_size(390, 844); d.get(BASE); W(2.5)
    chips = js("return [...document.querySelectorAll('#chip-row .chip')].slice(0, 2).map(c => c.textContent.replace(/\\s+/g, ' ').trim())")
    print('chips', chips)
    assert chips[0].startswith('안 읽은 글')
    d.save_screenshot(os.path.join(SHOTS, '2_mobile.png'))
    errs = [l for l in d.get_log('browser') if l['level'] == 'SEVERE']
    assert not errs, errs
    print('UNREAD E2E PASSED')
finally:
    d.quit()
