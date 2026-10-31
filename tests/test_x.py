import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, time, json
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', KEYWORDS_BASEBALL='삼성')
import storage, scraper, embeds

# 에펨코리아가 페이지 스크립트로 바꾸기 전의 'x.com 링크 자동 변환 중' 임시 상자
PLACEHOLDER = ('<blockquote class="twitter-tweet"><p><i class="fa-spinner"></i> x.com 링크 자동 변환 중...</p>'
               '<a href="https://x.com/someone/status/1851234567890123456">https://x.com/someone/status/1851234567890123456</a></blockquote>')
# 이미 트윗 화면(iframe)으로 바뀐 트윗의 남은 임시 상자 → 트윗 화면을 하나 더 만들지 않고 상자만 지움
RENDERED = ('<iframe src="https://platform.twitter.com/embed/Tweet.html?id=1850000000000000001"></iframe>'
            '<blockquote class="twitter-tweet"><a href="https://twitter.com/other/status/1850000000000000001">t</a></blockquote>')
# 예전 방식으로 저장된 글자 트윗 카드 (사진이 보이지 않음)
OLD_CARD = ('<div class="x-embed"><div class="x-embed-head"><span class="x-embed-logo">X</span></div>'
            '<div class="x-embed-text">트윗 본문</div>'
            '<a class="x-embed-link" href="https://x.com/claudeai/status/2116220869479428500">X에서 보기</a></div>')
EMBED = 'https://platform.twitter.com/embed/Tweet.html?id={}&amp;dnt=true'

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

# 1) 새로 수집하는 글: 임시 상자 → 트윗 ID로 만든 X 트윗 화면(iframe, 사진까지 보임)
res = scrape('<p>본문</p>' + PLACEHOLDER)
html = '\n'.join(res['content'])
assert EMBED.format('1851234567890123456') in html and 'x-embed' not in html, html
assert '자동 변환 중' not in html and 'fa-spinner' not in html and '<script' not in html
assert res['videos'] == [], res['videos']   # SNS 게시물 화면은 동영상이 아님
print('new post iframe OK')

# 2) 이미 트윗 화면이 있는 트윗은 하나 더 만들지 않음
res = scrape(RENDERED)
html = '\n'.join(res['content'])
assert html.count('platform.twitter.com/embed') == 1 and 'twitter-tweet' not in html, html
print('rendered tweet kept, no duplicate OK')

# 3) 이미 저장된 글: 임시 상자는 트윗 화면으로, 예전 글자 카드도 트윗 화면으로 (기동 시 1회)
storage.init_db()
def save(pid, content):
    storage.save_keyword_post('baseball', '삼성', {'id': pid, 'title': '삼성 트윗', 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
                                                 'comment_count': '0', 'link': '/' + pid, 'content': content, 'videos': [], 'comments': []},
                              is_new=False)
save('10999999001', ['<p>본문</p>', PLACEHOLDER])
save('10999999002', ['<p>본문</p>', OLD_CARD])
save('10999999003', [RENDERED.split('<blockquote')[0].replace('1850000000000000001', '2116220869479428500'), OLD_CARD])
storage.fix_stored_x_embeds()
storage.replace_stored_x_cards()
stored = {r['id']: '\n'.join(r['content']) for r in storage.query_all_posts(0, 10)[1]}
assert EMBED.format('1851234567890123456') in stored['10999999001'] and '자동 변환 중' not in stored['10999999001']
assert EMBED.format('2116220869479428500') in stored['10999999002'] and 'x-embed' not in stored['10999999002'], stored['10999999002']
# 같은 트윗의 화면이 이미 있던 글은 카드만 지움
assert stored['10999999003'].count('platform.twitter.com/embed') == 1 and 'x-embed' not in stored['10999999003'], stored['10999999003']
# 두 번째 호출은 아무것도 안 함 (1회만)
save('10999999004', [OLD_CARD])
storage.replace_stored_x_cards()
assert 'x-embed' in '\n'.join(next(r for r in storage.query_all_posts(0, 10)[1] if r['id'] == '10999999004')['content'])
print('X OK')
