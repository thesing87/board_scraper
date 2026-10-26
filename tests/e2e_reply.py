import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, tempfile, threading, time, json, sqlite3, urllib.request
tmp = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN', KEYWORDS_BASEBALL='삼성')
import storage, web_server, config
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
# 실제 사이트에서 답글이 있는 글을 가져와 그대로 저장
picked = []
for pg in (1, 2, 3):
    for p in json.load(urllib.request.urlopen(LIVE_URL + f'/api/posts?page={pg}', timeout=30))['posts']:
        if sum(1 for c in p['comments'] if c.get('is_reply')) >= 2 and len(picked) < 2:
            picked.append(p)
assert picked
db = sqlite3.connect(config.DB_FILE)
for p in reversed(picked):
    old = [dict(c) for c in p['comments']]
    # 앞쪽 절반은 예전 댓글, 뒤쪽 절반은 읽은 뒤 새로 달린 댓글로 만듦
    half = len(old) // 2
    storage.save_keyword_post('baseball', '삼성', dict(p, comments=old[:half]), is_new=False)
    db.execute("INSERT OR REPLACE INTO read_posts(post_id, read_at) VALUES(?, '2000-01-01 00:00:00')", (p['id'],)); db.commit()
    time.sleep(1.1)
    storage.update_post(dict(p, comments=old))
    db.execute("UPDATE read_posts SET read_at = (SELECT MIN(json_extract(value, '$.first_seen')) FROM posts, json_each(posts.comments_json) WHERE posts.id = ?) WHERE post_id = ?", (p['id'], p['id'])); db.commit()

srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18098), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
SHOTS = shot_dir('reply_shots')
o = Options()
for a in ['--headless=new', '--window-size=1440,1000']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get('http://127.0.0.1:18098/'); time.sleep(2.5)
    js("openView(ALL_KEY, 1)"); time.sleep(1.5)
    # 답글은 단계별 들여쓰기(--depth)로만 구분 (답글 뱃지·원댓글 인용은 쓰지 않음)
    info = js("""return [...document.querySelectorAll('.post-card')].map(card => ({
        replies: card.querySelectorAll('.comment.reply').length,
        depthStyled: [...card.querySelectorAll('.comment.reply')].filter(c => c.style.getPropertyValue('--depth')).length,
        newReplies: [...card.querySelectorAll('.comment.reply.is-new-comment')].map(c => c.querySelector('.new-comment-badge').textContent),
        newTop: [...card.querySelectorAll('.comment.is-new-comment:not(.reply) .new-comment-badge')].map(b => b.textContent),
        overflowX: card.querySelector('.comments').scrollWidth > card.querySelector('.comments').clientWidth + 1
    }))""")
    for i in info:
        print(json.dumps(i, ensure_ascii=False)[:400])
        assert i['replies'] == i['depthStyled']
        assert all(b == '새 답글' for b in i['newReplies']) and all(b == '새 댓글' for b in i['newTop']) and not i['overflowX']
    assert any(i['newReplies'] for i in info)
    first = d.find_element('css selector', '.comment.reply.is-new-comment')
    js("arguments[0].scrollIntoView({block: 'center'})", first); time.sleep(0.5)
    d.save_screenshot(os.path.join(SHOTS, 'desktop.png'))
    d.set_window_size(390, 844); time.sleep(1)
    first = d.find_element('css selector', '.comment.reply.is-new-comment')
    js("arguments[0].scrollIntoView({block: 'center'})", first); time.sleep(0.5)
    d.save_screenshot(os.path.join(SHOTS, 'mobile.png'))
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    errs = [l for l in d.get_log('browser') if l['level'] == 'SEVERE']
    assert not errs, errs
    print('REPLY E2E PASSED')
finally:
    d.quit()
