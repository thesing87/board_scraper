import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, time
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', KEYWORDS_BASEBALL='삼성')
import storage, scraper

# 에펨코리아 페이지 스크립트가 만든 게시물 화면(iframe)과, 이름만 바뀌어 남은 원래 임시 상자
RENDERED = ('<div class="instagram-iframe"><iframe class="instagram-media" '
            'src="https://www.instagram.com/p/De_Q5dCSLKp/embed/captioned/?cr=1&amp;v=14"></iframe>'
            '<blockquote class="instagram-media-registered"><div><a href="https://www.instagram.com/p/De_Q5dCSLKp/?utm_source=ig_embed">'
            '<div>View this post on Instagram</div></a></div></blockquote></div>')
# 화면으로 바뀌지 않은 상자(다른 게시물)는 링크라도 남도록 그대로 둠
UNRENDERED = ('<blockquote class="instagram-media" data-instgrm-permalink="https://www.instagram.com/reel/OtherPost1/">'
              '<a href="https://www.instagram.com/reel/OtherPost1/">View this post on Instagram</a></blockquote>')

def scrape(html):
    page = '<html><body><div class="xe_content">' + html + '</div></body></html>'
    class D:
        page_source = page
        def get(self, url): pass
    scraper.WebDriverWait = lambda d, t: type('W', (), {'until': lambda self, c: True})()
    real_sleep = time.sleep
    time.sleep = lambda s: None
    try:
        return scraper.scrape_post_detail(D(), {'link': 'x', 'title': '삼성 t', 'author': 'a', 'date': 'd', 'id': '1'})
    finally:
        time.sleep = real_sleep

# 1) 새로 수집하는 글: 게시물 화면은 남기고 같은 게시물의 상자만 지움
html = '\n'.join(scrape('<p>본문</p>' + RENDERED + UNRENDERED)['content'])
assert 'instagram.com/p/De_Q5dCSLKp/embed' in html, html
assert 'instagram-media-registered' not in html and 'De_Q5dCSLKp/?utm_source' not in html, html
assert 'OtherPost1' in html, html
print('new post placeholder removed OK')

# 2) 이미 저장된 글은 기동 시 1회 정리
storage.init_db()
post = {'id': '10999999002', 'title': '삼성 인스타', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
        'link': '/10999999002', 'content': ['<p>본문</p>', RENDERED], 'videos': [], 'comments': []}
storage.save_keyword_post('baseball', '삼성', post, is_new=False)
storage.remove_stored_duplicate_instagram_placeholders()
_, rows = storage.query_all_posts(0, 10)
stored = '\n'.join(rows[0]['content'])
assert 'instagram.com/p/De_Q5dCSLKp/embed' in stored and 'instagram-media-registered' not in stored, stored
print('Instagram OK')
