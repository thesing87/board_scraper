import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, shot_dir
import os, sys, tempfile, threading, time, json, sqlite3
tmp = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN', KEYWORDS_BASEBALL='삼성')
import storage, web_server, config
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

storage.init_db()
# 답글(여러 단계)이 섞인 글 두 개를 만들어 저장 (실서버 없이)
def comment(author, text, depth=0):
    return {'author': author, 'date': '10.26', 'content': [text], 'votes': '0', 'is_reply': bool(depth), 'depth': depth}
def make_post(pid, author):
    comments = [comment('캠핑족', '2열 폴딩하면 넓어지나요?'), comment(author, '네 넓어요', 1), comment('캠핑족', '감사합니다', 2),
                comment('차덕', '트림 뭐로 하셨나요?'), comment(author, '풀옵이요', 1), comment('ㅇㅇ', '저도 궁금', 2),
                comment('지나가던', '부럽네요'), comment(author, '감사합니다', 1)]
    return {'id': pid, 'title': f'답글 시험 {pid}', 'author': author, 'date': '2026.10.26 18:00', 'views': '10', 'votes': '0',
            'comment_count': str(len(comments)), 'link': f'/{pid}', 'content': ['<p>본문</p>'], 'videos': [], 'comments': comments}
picked = [make_post('901', 'DoubleRL'), make_post('902', '수원러')]
db = sqlite3.connect(config.DB_FILE)
for p in reversed(picked):
    old = [dict(c) for c in p['comments']]
    # 앞쪽 절반은 예전 댓글, 뒤쪽 절반은 읽은 뒤 새로 달린 댓글로 만듦
    half = len(old) // 2
    storage.save_keyword_post('baseball', '삼성', dict(p, comments=old[:half]), is_new=False)
    db.execute("INSERT OR REPLACE INTO read_posts(post_id, read_at) VALUES(?, '2000-01-01 00:00:00')", (p['id'],)); db.commit()
    time.sleep(1.1)
    storage.update_post(dict(p, comments=old))
    db.execute("UPDATE read_posts SET read_at = (SELECT MIN(json_extract(value, '$.first_seen')) FROM post_bodies, json_each(post_bodies.comments_json) WHERE post_bodies.post_id = ?) WHERE post_id = ?", (p['id'], p['id'])); db.commit()

srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18098), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
SHOTS = shot_dir('reply_shots')
o = Options()
for a in ['--headless=new', '--window-size=1440,1000']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    d.get('http://127.0.0.1:18098/board/'); time.sleep(2.5)
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
    # 작성자 댓글에는 작성자 뱃지와 같은 파란 테두리
    assert js("return [...document.querySelectorAll('.comment.is-author')].every(c => c.querySelector('.op-badge') && getComputedStyle(c).boxShadow.includes('inset'))")
    authors = js("return [...document.querySelectorAll('.post-card')].map(c => c.querySelectorAll('.comment.is-author').length)")
    assert authors and all(n == 3 for n in authors), authors
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
