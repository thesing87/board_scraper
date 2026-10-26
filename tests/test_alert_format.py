import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, json, re, urllib.request, urllib.parse
os.environ.update(TELEGRAM_TOKEN='TEST', TELEGRAM_CHAT_ID='1', LOG_LEVEL='WARN', OUTPUT_DIR=os.environ.get('TEMP', '.'))
import notifier, ast

ast.parse(open(os.path.join(ROOT, 'fmkorea-scraper.py'), encoding='utf-8').read())

B = LIVE_URL + ''
posts = json.load(urllib.request.urlopen(B + '/api/posts?video_only=1', timeout=20))['posts'][:2]
posts += [p for p in json.load(urllib.request.urlopen(B + '/api/posts?page=2', timeout=20))['posts'] if not p.get('videos')][:3]

calls = []
class Res:
    def __init__(self, code): self.status_code = code; self.text = 'x'
def fake_post(url, json=None, timeout=None):
    calls.append((url.rsplit('/', 1)[1], json))
    return Res(fail.pop(0) if fail else 200)
notifier.requests.post = fake_post

ALLOWED = re.compile(r'</?b>')
for p in posts:
    fail = []
    calls.clear()
    notifier.send_post_alert(p, ['싼타페'], '싼하', '자동차', 'http://x/#post-' + p['id'], 'https://www.fmkorea.com/' + p['id'])
    method, payload = calls[-1]
    body = payload.get('caption') or payload.get('text')
    # 허용한 태그(<b>) 외에는 모두 이스케이프되어 있어야 함
    assert not re.search(r'<(?!/?(b|blockquote)>)', body), body
    assert payload['reply_markup']['inline_keyboard'][0][0]['text'] == '📱 대시보드' and len(payload['reply_markup']['inline_keyboard']) == 1
    thumb = payload.get('photo')
    print('=' * 60)
    print(method, '| photo:', thumb)
    print(body)
    if thumb:
        req = urllib.request.Request(thumb, method='GET', headers={'User-Agent': 'TelegramBot (like TwitterBot)'})
        r = urllib.request.urlopen(req, timeout=20)
        print('thumb', r.status, r.headers.get('Content-Type'), r.headers.get('Content-Length'))

# 사진 실패 → 글로 대신 발송, HTML 실패 → 서식 없는 글
fail = [400, 200]; calls.clear()
notifier.send_post_alert(posts[0], ['삼성'], '삼성', '야구', 'http://x', 'https://y')
assert [c[0] for c in calls] == ['sendPhoto', 'sendMessage'], calls
fail = [400, 400, 200]; calls.clear()
notifier.send_post_alert(posts[0], ['삼성'], '삼성', '야구', 'http://x', 'https://y')
assert [c[0] for c in calls] == ['sendPhoto', 'sendMessage', 'sendMessage'] and 'parse_mode' not in calls[-1][1] and '<b>' not in calls[-1][1]['text']
# 특수문자 제목도 안전하게 이스케이프
t = notifier.build_post_alert({'title': 'a<b>&_*c', 'content': ['<p>x &amp; y</p>'], 'author': '<s>', 'views': '1', 'comment_count': '2'}, ['B&B'], 'k', '자동차')
print(t)
assert '<b>a&lt;b&gt;&amp;_*c</b>' in t and '&lt;s&gt;' in t and 'x &amp; y' in t
print('ALERT FORMAT OK')

