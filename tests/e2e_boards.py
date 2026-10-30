import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, threading, time, json, sqlite3, urllib.request, urllib.error
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN')
import storage, web_server, config
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
db = sqlite3.connect(config.DB_FILE)
kws = db.execute('select board, keyword from keywords order by rowid').fetchall()
groups = storage.list_groups()
print('keywords', len(kws), 'boards', [(g['name'], len(g['members'])) for g in groups])
# 1) 기존 키워드마다 같은 이름의 게시판으로 이전 (재기동해도 다시 만들지 않음)
assert len(groups) == len(kws) and all(len(g['members']) == 1 and g['members'][0]['keyword'] == g['name'] for g in groups)
storage._initialized = False; storage.init_db()
assert len(storage.list_groups()) == len(kws)

srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18093), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:18093/'
SHOTS = shot_dir('board_shots')

# 키워드 단독 API는 사라짐
try:
    urllib.request.urlopen(urllib.request.Request(BASE + 'api/keyword', data=b'{}', method='POST'))
    raise AssertionError('keyword api still alive')
except urllib.error.HTTPError as e:
    assert e.code == 404
state = json.load(urllib.request.urlopen(BASE + 'api/state'))
assert 'tabs' not in state and state['all']['total'] == db.execute('select count(distinct post_id) from keyword_posts').fetchone()[0]

def distinct_count(pairs):
    q = ' OR '.join('(board=? AND keyword=?)' for _ in pairs)
    return db.execute(f'select count(distinct post_id) from keyword_posts where {q}', [x for p in pairs for x in p]).fetchone()[0]

o = Options()
for a in ['--headless=new', '--window-size=1440,900', '--force-device-scale-factor=1']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
wait = time.sleep
by_name = {g['name']: g for g in groups}
def show_all():
    # 게시판을 열면 기본 보기(안 읽은 글 등)로 열리므로 글 수는 '모든 글' 보기로 바꿔서 확인
    js("document.querySelector('#view-bar-tabs [data-action=\"set-view\"][data-filter=\"all\"]').click()"); wait(1.5)
try:
    d.get(BASE); wait(2.5)
    side = js("return [...document.querySelectorAll('#keyword-groups .kw-item')].map(b => b.textContent.replace(/\\s+/g, ' ').trim())")
    views = js("return [...document.querySelectorAll('#view-bar-tabs .view-bar-tab')].map(b => b.textContent.replace(/\\s+/g, ' ').trim())")
    heads = js("return [...document.querySelectorAll('.kw-group-name')].map(e => e.textContent)")
    in_topbar = js("return !!document.querySelector('.topbar #view-bar-tabs')")
    print('sidebar', side, views, in_topbar, heads)
    # 사이드바는 게시판(전체 + 사용자 게시판)만, 보기 5개는 상단 바 가운데 보기 탭
    assert len(side) == len(kws) + 1 and side[0].startswith('전체') and len(views) == 5 and heads == []
    assert in_topbar and js("return document.querySelectorAll('#keyword-groups [data-action=\"set-view\"]').length") == 0
    d.save_screenshot(os.path.join(SHOTS, '1_sidebar.png'))

    # 2) 게시판 하나 열기
    gid = by_name['싼타페']['id']
    js(f"document.querySelector('[data-action=\"open-group\"][data-group-id=\"{gid}\"]').click()"); wait(1.5)
    assert js("return document.querySelector('.feed-title').textContent").startswith('싼타페')
    show_all()
    v = js("return {title: document.querySelector('.feed-title').textContent, sub: document.querySelector('.feed-sub').textContent, chips: document.querySelectorAll('.kw-chip').length}")
    print('board view', v)
    assert v['title'] == '싼타페' and f"{distinct_count([('car', '싼타페')])}개 글" in v['sub'] and v['chips'] == 0

    # 3) 수정: 이름 변경 + 기존 키워드(싼하) + 새 키워드 등록
    js("document.querySelector('.topbar [data-action=\"open-settings\"]').click()"); wait(0.4)
    js(f"""document.getElementById('admin-pwd-input').value = 'Secr3t!';
           document.querySelector('[data-action="edit-group"][data-group-id="{gid}"]').click();""")
    wait(0.3)
    js("""const n = document.getElementById('group-name-input'); n.value = '싼타페 모음'; n.dispatchEvent(new Event('input', {bubbles: true}));
          document.getElementById('group-board-select').value = 'car';
          const k = document.getElementById('group-kw-input');
          k.value = '싼하'; document.querySelector('[data-action="add-draft-keyword"]').click();
          k.value = '테스트키워드';""")
    k = d.find_element('id', 'group-kw-input'); k.send_keys('\n'); wait(0.3)
    tags = js("return [...document.querySelectorAll('#group-keywords .kw-tag')].map(t => t.textContent.replace(/\\s+/g, ' ').trim())")
    print('draft tags', tags)
    assert len(tags) == 3
    d.save_screenshot(os.path.join(SHOTS, '2_edit_form.png'))
    js("document.getElementById('group-save-btn').click()"); wait(2)
    show_all()
    v = js("return {title: document.querySelector('.feed-title').textContent, sub: document.querySelector('.feed-sub').textContent, chips: document.querySelectorAll('.kw-chip').length, ids: [...document.querySelectorAll('.post-card')].map(c => c.id)}")
    print('edited', v['title'], v['sub'], v['chips'])
    assert v['title'] == '싼타페 모음' and f"{distinct_count([('car', '싼타페'), ('car', '싼하')])}개 글" in v['sub']
    assert v['chips'] > 0 and len(v['ids']) == len(set(v['ids']))
    assert db.execute("select 1 from keywords where keyword='테스트키워드'").fetchone()
    d.save_screenshot(os.path.join(SHOTS, '3_edited_feed.png'))

    # 4) '싼하' 게시판 삭제: 싼하는 다른 게시판에 남아 있으니 수집 데이터 유지
    before = distinct_count([('car', '싼하')])
    js("window.confirm = () => true; document.querySelector('.topbar [data-action=\"open-settings\"]').click()"); wait(0.4)
    js(f"document.querySelector('[data-action=\"delete-group\"][data-group-id=\"{by_name['싼하']['id']}\"]').click()"); wait(1.5)
    assert db.execute("select 1 from keywords where keyword='싼하'").fetchone() and distinct_count([('car', '싼하')]) == before
    assert not any(g['name'] == '싼하' for g in storage.list_groups())

    # 5) 새 키워드를 빼면 수집 대상에서도 빠짐 (확인 창 문구 검사)
    msgs = js(f"""window._msgs = []; window.confirm = m => (window._msgs.push(m), true);
        document.querySelector('[data-action="edit-group"][data-group-id="{gid}"]').click();
        const tags = [...document.querySelectorAll('#group-keywords .kw-tag')];
        tags.find(t => t.textContent.includes('테스트키워드')).querySelector('button').click();
        document.getElementById('group-save-btn').click(); return window._msgs;""")
    wait(2)
    print('confirm', msgs)
    assert msgs and '테스트키워드' in msgs[0]
    assert not db.execute("select 1 from keywords where keyword='테스트키워드'").fetchone()

    # 6) 텔레그램 링크(#post-ID) → 그 글이 속한 게시판의 해당 페이지
    pid = db.execute("select post_id from keyword_posts where board='car' and keyword='싼하' order by rowid limit 1").fetchone()[0]
    d.get(BASE + '#post-' + pid); d.refresh(); wait(3)
    v = js(f"return {{title: document.querySelector('.feed-title').textContent, found: !!document.getElementById('post-{pid}')}}")
    print('anchor', v)
    assert v['title'].startswith('싼타페 모음') and v['found']

    # 7) 모바일: 위는 보기 탭 5개, 아래 칩은 전체 + 게시판
    d.set_window_size(390, 844); d.get(BASE); wait(2.5)
    chips = js("return [...document.querySelectorAll('#chip-row .chip')].map(c => c.textContent.replace(/\\s+/g, ' ').trim())")
    tabs = js("return document.querySelectorAll('#view-tabs .view-tab').length")
    print('chips', chips, 'tabs', tabs)
    assert len(chips) == len(storage.list_groups()) + 1 and tabs == 5
    d.save_screenshot(os.path.join(SHOTS, '4_mobile.png'))
    errs = [l for l in d.get_log('browser') if l['level'] == 'SEVERE']
    assert not errs, errs
    print('BOARDS E2E PASSED')
finally:
    d.quit()
