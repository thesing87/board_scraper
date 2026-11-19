"""댓글이 여러 페이지인 글: 모든 페이지를 읽어 합치고, 앞 페이지에 달린 새 답글도 새 댓글로 잡는지.
디시인사이드 댓글 API(1페이지가 최신)를 가짜 연결로 흉내냄"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, time, json
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', TELEGRAM_TOKEN='', COMMENT_PAGE_LIMIT='3')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
time.sleep = lambda *_: None   # 페이지 사이 대기 생략
from bs4 import BeautifulSoup
import dcinside, storage

# --- 2) 디시인사이드 댓글 API: 1페이지가 최신, 페이지 번호 줄은 일부만 보임(2페이지를 열면 3·4페이지 번호가 보임),
#        COMMENT_PAGE_LIMIT까지만, 오래된 댓글부터 순서대로, 2페이지부터 읽은 댓글은 other_page
def item(no, nick, text, depth='0'):
    return {'no': str(no), 'name': nick, 'ip': '', 'reg_date': '11.02 10:00:00', 'depth': depth, 'memo': text}

def page(current, last_link, items):
    links = ''.join(f"<a href=\"javascript:viewComments({p},'D',true)\">{p}</a>" if p != current else f'<em>{p}</em>'
                    for p in range(1, last_link + 1))
    return {'total_cnt': 40, 'pagination': links, 'comments': items}

DC_PAGES = {1: page(1, 2, [item(10, 'p1', '하나'), item(11, 'p1답', '답', '1')]),
            2: page(2, 4, [item(20, 'p2', '둘'), item(10, 'p1', '하나')]),     # 겹친 댓글은 한 번만
            3: page(3, 4, [item(30, 'p3', '셋')])}

class Res:
    status_code = 200
    def __init__(self, data): self.data = data
    def json(self): return self.data

class DcClient:
    def __init__(self): self.pages = []
    def post(self, url, data=None, headers=None, **kw):
        self.pages.append(data['comment_page'])
        return Res(DC_PAGES[data['comment_page']])

client = DcClient()
comments, total = dcinside._read_comments(client, 'car_new1', '1', 'esno', 'https://gall.dcinside.com/board/view/?id=car_new1&no=1', 'dc-x-1', True)
assert client.pages == [1, 2, 3], client.pages      # COMMENT_PAGE_LIMIT=3이라 4페이지는 안 읽음
assert [c['author'] for c in comments] == ['p3', 'p2', 'p1', 'p1답'], comments
assert [bool(c.get('other_page')) for c in comments] == [True, True, False, False] and comments[3]['is_reply'] and total == 40
# 첫 화면 댓글만 (삭제 여부 확인처럼 댓글이 필요 없을 때)
client = DcClient()
comments, _ = dcinside._read_comments(client, 'car_new1', '1', 'esno', 'x', 'dc-x-1', False)
assert client.pages == [1] and [c['author'] for c in comments] == ['p1', 'p1답']
print('DC PAGES OK')

# --- 3) 저장: 첫 화면 페이지만 저장하던 글을 처음 모든 페이지로 읽으면 다른 페이지 댓글은 새 댓글 아님,
#        그 뒤로는 앞 페이지에 달린 답글도 새 댓글
storage.init_db()

def post(comments):
    return {'id': '7', 'title': 't', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': str(len(comments)),
            'link': '/7', 'content': ['본문'], 'videos': [], 'comments': comments}

def comment(author, other_page=False):
    c = {'author': author, 'date': '', 'votes': '0', 'content': [author + ' 내용']}
    return dict(c, other_page=True) if other_page else c

def stored():
    with storage._db() as conn:
        row = conn.execute("SELECT b.comments_json, p.all_comment_pages FROM posts p JOIN post_bodies b ON b.post_id = p.id "
                           "WHERE p.id = '7'").fetchone()
        return {c['author']: c.get('first_seen') for c in json.loads(row['comments_json'])}, row['all_comment_pages']

storage.save_keyword_post('humor', 't', post([comment('last')]), is_new=True)
with storage._db() as conn, conn:   # 이 기능 전에 저장된 글처럼
    conn.execute("UPDATE posts SET all_comment_pages = 0")
storage._now = lambda: '2026-11-02 12:00:00'
storage.update_post(post([comment('old', other_page=True), comment('last'), comment('new')]))
seen_at, all_pages = stored()
assert seen_at['old'] is None and seen_at['new'] == '2026-11-02 12:00:00' and all_pages == 1, (seen_at, all_pages)
with storage._db() as conn:
    assert 'other_page' not in conn.execute("SELECT comments_json FROM post_bodies WHERE post_id = '7'").fetchone()[0]
storage._now = lambda: '2026-11-02 13:00:00'
storage.update_post(post([comment('old', other_page=True), comment('reply', other_page=True), comment('last'), comment('new')]))
seen_at, _ = stored()
assert seen_at['reply'] == '2026-11-02 13:00:00' and seen_at['old'] is None and seen_at['new'] == '2026-11-02 12:00:00', seen_at
print('COMMENT PAGES OK')
