import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, time
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', KEYWORDS_BASEBALL='삼성')
import storage, scraper, embeds

# X 공개 oEmbed 응답을 흉내 (네트워크 없이)
calls = []
def fake_oembed(status_url):
    calls.append(status_url)
    return {'author_name': '테스트 계정', 'text_html': '트윗 <a href="https://t.co/x">본문</a> &amp; 링크', 'date': '2026년 10월 26일'}
embeds.fetch_x_oembed = fake_oembed

# 에펨코리아가 페이지 스크립트로 바꾸기 전의 'x.com 링크 자동 변환 중' 임시 상자
PLACEHOLDER = ('<blockquote class="twitter-tweet"><p><i class="fa-spinner"></i> x.com 링크 자동 변환 중...</p>'
               '<a href="https://x.com/someone/status/1851234567890123456">https://x.com/someone/status/1851234567890123456</a></blockquote>')
# 이미 트윗 화면(iframe)으로 바뀐 트윗의 남은 임시 상자 → 글자 카드를 만들지 않고 상자만 지움
RENDERED = ('<iframe src="https://platform.twitter.com/embed/Tweet.html?id=1850000000000000001"></iframe>'
            '<blockquote class="twitter-tweet"><a href="https://twitter.com/other/status/1850000000000000001">t</a></blockquote>')

def scrape(html):
    page = '<html><body><div class="xe_content">' + html + '</div></body></html>'
    class D:
        page_source = page
        def get(self, url): pass
    scraper.WebDriverWait = lambda d, t: type('W', (), {'until': lambda self, c: True})()
    real_sleep = time.sleep
    time.sleep = lambda s: None   # scraper.time은 전역 time 모듈이므로 수집기 호출 동안만 대기 생략
    try:
        return scraper.scrape_post_detail(D(), {'link': 'x', 'title': '삼성 t', 'author': 'a', 'date': 'd', 'id': '1'})
    finally:
        time.sleep = real_sleep

# 1) 새로 수집하는 글: 임시 상자 → 스크립트 없는 트윗 카드
res = scrape('<p>본문</p>' + PLACEHOLDER)
html = '\n'.join(res['content'])
assert 'class="x-embed"' in html and '테스트 계정' in html and '@someone' in html, html
assert '자동 변환 중' not in html and 'fa-spinner' not in html and '<script' not in html
assert 'https://x.com/someone/status/1851234567890123456' in html
print('new post card OK')

# 2) 이미 트윗 화면이 있는 트윗은 카드를 만들지 않음
res = scrape(RENDERED)
html = '\n'.join(res['content'])
assert 'x-embed' not in html and 'platform.twitter.com/embed' in html, html
print('rendered tweet kept, no duplicate card OK')

# 3) 이미 저장된 글(임시 상자 상태)은 기동 시 1회 변환, 두 번째 호출은 아무것도 안 함
storage.init_db()
post = {'id': '10999999001', 'title': '삼성 트윗', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
        'link': '/10999999001', 'content': ['<p>본문</p>', PLACEHOLDER], 'videos': [], 'comments': []}
storage.save_keyword_post('baseball', '삼성', post, is_new=False)
storage.fix_stored_x_embeds()
_, rows = storage.query_all_posts(0, 10)
stored = '\n'.join(rows[0]['content'])
assert 'class="x-embed"' in stored and '자동 변환 중' not in stored, stored
before = len(calls)
storage.fix_stored_x_embeds()
assert len(calls) == before
print('X OK')
