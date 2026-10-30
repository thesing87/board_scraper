import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, threading, time, json, sqlite3
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN')
import storage, web_server, config
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

storage.init_db()
srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18090), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:18090/'
SHOTS = shot_dir('p1_shots')
db = sqlite3.connect(config.DB_FILE)
read_count = lambda: db.execute('select count(*) from read_posts').fetchone()[0]

o = Options()
for a in ['--headless=new', '--window-size=1440,900', '--force-device-scale-factor=1']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
wait = time.sleep
ok = []
try:
    # 0) 예전 브라우저 읽음 기록(localStorage) → 서버로 이전
    d.get(BASE); wait(2)
    legacy = [r[0] for r in db.execute('select post_id from keyword_posts where is_new=1 limit 3')]
    js("localStorage.setItem('read_post_ids', JSON.stringify(arguments[0])); sessionStorage.clear();", legacy)
    d.get(BASE); wait(2.5)
    js("app.filter = 'all'; openView(ALL_KEY, 1)"); wait(1.5)  # 첫 화면은 안 읽은 글 보기 → 전체 게시판의 모든 글로 전환
    migrated = db.execute(f"select count(*) from read_posts where post_id in ({','.join('?'*len(legacy))})", legacy).fetchone()[0]
    assert migrated == len(legacy) and js("return localStorage.getItem('read_post_ids')") is None, migrated
    ok.append('legacy reads migrated to server')

    # 1) 통합 피드가 기본, 키워드 표시
    info = js("""return { title: document.querySelector('.feed-title').textContent,
        allActive: document.querySelector('.kw-item.active').textContent.replace(/\\s+/g,' ').trim(),
        kwChips: document.querySelectorAll('.kw-chip').length, cards: document.querySelectorAll('.post-card').length }""")
    print('all view', info)
    assert info['title'] == '전체' and info['allActive'].startswith('전체') and info['kwChips'] >= 10
    d.save_screenshot(os.path.join(SHOTS, '1_all_feed.png'))
    ok.append('all feed default with keyword chips')

    # 2) 스크롤 읽음: 카드 끝을 지나가면 서버에 기록
    passed_ids = js("return [...document.querySelectorAll('.post-card')].slice(0, 3).map(c => c.id.replace('post-', ''))")
    later_id = js("return document.querySelectorAll('.post-card')[8].id.replace('post-', '')")
    js("window.scrollTo(0, document.querySelectorAll('.post-card')[2].getBoundingClientRect().bottom + window.scrollY)")
    wait(3)
    read_now = {r[0] for r in db.execute('select post_id from read_posts')}
    print('scroll read', [i in read_now for i in passed_ids], 'later card read?', later_id in read_now)
    assert all(i in read_now for i in passed_ids) and later_id not in read_now
    ok.append('scroll-based read recorded on server')

    # 3) 모두 읽음
    js("window.scrollTo(0,0)")
    unread_before = js("return document.querySelector('.feed-sub').textContent")
    js("document.querySelector('[data-action=\"mark-all-read\"]').click()"); wait(2.5)
    st = json.loads(d.execute_script("return fetch('/api/state').then(r=>r.text())"))
    print('mark all', unread_before, '-> unread', len(st['all']['unread_ids']))
    assert len(st['all']['unread_ids']) == 0 and js("return document.querySelectorAll('.badge-new').length") == 0
    ok.append('mark all read')

    # 4) 검색
    box = d.find_element(By.ID, 'search-input'); box.send_keys('싼타페 하이브리드'); box.send_keys(Keys.ENTER); wait(1.5)
    s = js("""return { title: document.querySelector('.feed-title').textContent, sub: document.querySelector('.feed-sub').textContent,
        marks: document.querySelectorAll('.post-title mark').length, navActive: document.querySelectorAll('.kw-item.active').length }""")
    print('search', s)
    assert s['title'].startswith('검색: 싼타페 하이브리드') and '12건' in s['sub'] and s['navActive'] == 0
    d.save_screenshot(os.path.join(SHOTS, '2_search.png'))
    js("document.querySelector('[data-action=\"clear-search\"]').click()"); wait(1.2)
    assert js("return document.querySelector('.feed-title').textContent") == '전체'
    ok.append('search + clear')

    # 5) 새 댓글 강조: 읽은 글에 댓글이 새로 수집되면 표시
    target = db.execute("select post_id, read_at from read_posts order by read_at desc limit 1").fetchone()[0]
    wait(1.1)
    _, rows = storage.query_all_posts(0, 400)
    post = next(p for p in rows if p['id'] == target)
    post['comments'] = [dict(c) for c in post['comments']] + [{'author': '새댓글러', 'date': '방금', 'votes': '0', 'content': ['방금 달린 새 댓글입니다'], 'is_reply': False}]
    for c in post['comments']:
        c.pop('first_seen', None)
    storage.update_post(post)
    d.get(BASE + '#post-' + target); wait(3)
    n = js("""const c = document.getElementById('post-' + arguments[0]);
        return { badge: c.querySelector('.badge-new-comments') && c.querySelector('.badge-new-comments').textContent,
                 highlighted: c.querySelectorAll('.comment.is-new-comment').length,
                 who: c.querySelector('.comment.is-new-comment .comment-author') && c.querySelector('.comment.is-new-comment .comment-author').textContent }""", target)
    print('new comments', n)
    assert n['badge'] == '새 댓글 1' and n['highlighted'] == 1 and n['who'] == '새댓글러'
    js("const c=document.getElementById('post-'+arguments[0]); window.scrollTo(0, c.getBoundingClientRect().top + window.scrollY - 70)", target)
    wait(0.8)
    d.save_screenshot(os.path.join(SHOTS, '3_new_comment.png'))
    ok.append('new comment badge + highlight')

    # 6) 새 글 배너: 화면을 보는 중에 새 글이 수집되면 배너 → 누르면 맨 위에 표시
    js("sessionStorage.clear()"); d.get(BASE); wait(2.5); js("app.filter = 'all'; openView(ALL_KEY, 1)"); wait(1.5)
    any_kw = db.execute('select board, keyword from keywords limit 1').fetchone()
    newp = dict(rows[0]); newp.update(id='10999999901', title='배너 테스트 새 글', comments=[], is_deleted=False)
    storage.save_keyword_post(any_kw[0], any_kw[1], newp, is_new=True)
    js("return pollState()"); wait(1.5)
    banner = js("const b=document.getElementById('new-banner'); return { hidden: b.hidden, text: b.textContent.trim() }")
    print('banner', banner)
    assert not banner['hidden'] and '새 글 1개' in banner['text']
    d.save_screenshot(os.path.join(SHOTS, '4_banner.png'))
    js("document.getElementById('new-banner').click()"); wait(1.5)
    first = js("const c=document.querySelector('.post-card'); return { id: c.id, isNew: !!c.querySelector('.badge-new'), bannerHidden: document.getElementById('new-banner').hidden }")
    print('after banner click', first)
    assert first['id'] == 'post-10999999901' and first['isNew'] and first['bannerHidden']
    ok.append('new post banner')

    # 7) 키워드 탭 이동·통합 피드 복귀, 콘솔 오류 없음
    js("document.querySelectorAll('[data-action=\"open-group\"]')[1].click()"); wait(1.2)
    kw_title = js("return document.querySelector('.feed-title').textContent")
    js("document.querySelector('.kw-item[data-action=\"open-all\"]').click()"); wait(1.2)
    # 게시판을 바꾸면 그 게시판의 기본 보기로 열리므로 제목 앞부분(게시판 이름)만 비교
    assert js("return document.querySelector('.feed-title').textContent").startswith('전체') and not kw_title.startswith('전체')
    errors = [l for l in d.get_log('browser') if l['level'] == 'SEVERE']
    print('console errors', errors)
    assert not errors
    ok.append('tab switching, no console errors')

    # 8) 모바일 폭: 검색 펼치기와 게시판 칩 (맨 앞이 전체)
    d.set_window_size(390, 844); d.get(BASE); wait(2.5)
    m = js("""document.querySelector('[data-action="toggle-search"]').click();
        return { chipFirst: document.querySelector('#chip-row .chip').textContent.replace(/\\s+/g,' ').trim(),
                 searchVisible: getComputedStyle(document.getElementById('search-form')).display !== 'none',
                 overflow: document.documentElement.scrollWidth > innerWidth }""")
    print('mobile', m)
    assert m['chipFirst'].startswith('전체') and m['searchVisible'] and not m['overflow']
    wait(0.5)
    d.save_screenshot(os.path.join(SHOTS, '5_mobile.png'))
    ok.append('mobile chips + search toggle')
finally:
    d.quit()
    print('\nPASSED:', ok)
