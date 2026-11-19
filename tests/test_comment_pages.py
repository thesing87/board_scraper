"""댓글이 여러 페이지인 글: 모든 페이지를 읽어 합치고, 앞 페이지에 달린 새 답글도 새 댓글로 잡는지.
디시인사이드는 1페이지(최신)가 보이는 실제 사이트 동작을 가짜 크롬으로 흉내냄"""
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

class Element:
    def __init__(self, text=''): self.text = text

# --- 2) 디시인사이드: 1페이지(최신)가 첫 화면, 이미지 댓글 상자는 페이지마다 반복, 페이지 번호 줄은 일부만 보임
def dc_comment(no, nick, text, prefix='comment_li'):
    return (f'<li id="{prefix}_{no}" class="ub-content"><div class="cmt_info"><span class="gall_writer" data-nick="{nick}"></span>'
            f'<p class="usertxt">{text}</p><span class="date_time">11.02 10:00:00</span></div></li>')

def dc_page(current, last_link, comments):
    links = ''.join(f"<a href=\"javascript:viewComments({p},'D',true)\">{p}</a>" if p != current else f'<em>{p}</em>'
                    for p in range(1, last_link + 1))
    pinned = f'<div class="comment_box img_comment_box"><ul class="cmt_list">{dc_comment(99, "짤", "이미지", "img_comment_li")}</ul></div>'
    return f'{pinned}<div class="comment_box"><ul class="cmt_list">{"".join(comments)}</ul></div><div class="cmt_paging">{links}</div>'

# 2페이지까지만 번호가 보이다가 2페이지를 열면 3·4페이지 번호가 보임
DC_PAGES = {2: dc_page(2, 4, [dc_comment(20, 'p2', '둘')]), 3: dc_page(3, 4, [dc_comment(30, 'p3', '셋')])}

class DcDriver:
    def __init__(self): self.calls, self.page_source, self.current = [], '', 1
    def execute_script(self, script, page):
        self.calls.append(page)
        self.current, self.page_source = page, DC_PAGES[page]
    def find_elements(self, by, css): return [Element(str(self.current))]

first_screen = BeautifulSoup(dc_page(1, 2, [dc_comment(10, 'p1', '하나')]), 'html.parser')
seen = set()
pinned, newest = dcinside._parse_comments(first_screen, seen)
assert [c['author'] for c in pinned] == ['짤'] and [c['author'] for c in newest] == ['p1']
driver = DcDriver()
older = dcinside._read_older_comment_pages(driver, first_screen, 'dc-x-1', seen)
assert driver.calls == [2, 3], driver.calls   # COMMENT_PAGE_LIMIT=3이라 4페이지는 안 읽음
assert [c['author'] for c in older] == ['p3', 'p2'], older   # 오래된 댓글부터, 이미지 댓글은 다시 넣지 않음
assert all(c['other_page'] for c in older)
assert dcinside._comment_pages(BeautifulSoup('<div>댓글 없음</div>', 'html.parser')) == 1
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
