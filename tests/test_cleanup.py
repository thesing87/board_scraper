import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, time
os.environ.update(TELEGRAM_TOKEN='TEST', TELEGRAM_CHAT_ID='1', LOG_LEVEL='WARN', OUTPUT_DIR=tempfile.mkdtemp())
import scraper, notifier

# 1) 동영상 플레이어(MediaElement.js) 껍데기 제거: 에펨코리아 상세 페이지의 실제 마크업 구조
VIDEO = '''<div class="auto_media_wrapper full pc"><div class="height_keep"><div class="auto_media">
<div class="mejs__container mejs__video"><div class="mejs__inner"><div class="mejs__mediaelement"><div>
<video class="mediaelement_video" controls="controls" poster="//image.fmkorea.com/files/attach/new5/20261025/1_thumb.webp"
 preload="none" src="https://mediak5jvqbd.fmkorea.com/files/attach/new5/20261025/1.mp4" data-original-width="1280" data-original-height="720">
<source src="//mediak5jvqbd.fmkorea.com/files/attach/new5/20261025/1.mp4" type="video/mp4">Video 태그를 지원하지 않는 브라우저입니다.</video></div></div>
<div class="mejs__layers"><div class="mejs__overlay mejs__layer" style="display: none;"><div class="mejs__overlay-loading"><div class="mejs__overlay-loading-bg-img"></div></div></div>
<div class="mejs__overlay mejs__layer" style="display: none;"><div class="mejs__overlay-error"></div></div>
<div class="mejs__overlay mejs__layer mejs__overlay-play"></div></div>
<div class="custom-progress-bar"><div class="inner"></div></div><div class="volume-layer" title="볼륨 100%으로 변경"></div><div class="controls-mouse-hover"></div>
</div></div></div></div></div>'''
JUNK = ('mejs__layers', 'mejs__overlay', 'custom-progress-bar', 'volume-layer', 'controls-mouse-hover')
page = '<html><body><div class="xe_content"><p>본문</p>' + VIDEO + '</div></body></html>'
class D:
    page_source = page
    def get(self, u): pass
scraper.WebDriverWait = lambda d, t: type('W', (), {'until': lambda self, c: True})()
real_sleep = time.sleep
time.sleep = lambda s: None
try:
    res = scraper.scrape_post_detail(D(), {'link': 'x', 'title': 't', 'author': 'a', 'date': 'd', 'id': '1'})
finally:
    time.sleep = real_sleep
html = '\n'.join(res['content'])
before, after = sum(page.count(j) for j in JUNK), sum(html.count(j) for j in JUNK)
print('junk markers before', before, 'after', after, '| videos', res['videos'], '| keys', sorted(res))
assert before > 0 and after == 0 and res['videos'] and '<video' in html and 'images' not in res

# 2) 상태 알림은 서식 없는 글 한 번으로 발송
calls = []
class R: status_code = 200; text = ''
notifier.requests.post = lambda url, json=None, timeout=None: (calls.append(json), R())[1]
notifier.send_telegram_message('⚠️ 에펨코리아 접속 차단 의심\n\n자동차/싼_하 *목록*')
assert len(calls) == 1 and 'parse_mode' not in calls[0] and calls[0]['text'].endswith('*목록*')
print('CLEANUP OK')
