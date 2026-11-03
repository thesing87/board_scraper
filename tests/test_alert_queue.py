import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, json
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='TEST', TELEGRAM_CHAT_ID='1')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, notifier

calls, plan = [], []
class Res:
    def __init__(self, code): self.status_code = code; self.text = 'x'
def fake_post(url, json=None, data=None, files=None, timeout=None):
    calls.append((url.rsplit('/', 1)[1], json))
    step = plan.pop(0) if plan else 200
    if step == 'timeout':
        raise TimeoutError('Read timed out')
    return Res(step)
notifier.requests.post = fake_post

post = {'id': '901', 'title': '싼타페 <출고>', 'author': 'a', 'views': '1', 'comment_count': '2', 'videos': [],
        'content': ['<p>본문</p>', '<img src="https://image.fmkorea.com/files/attach/new5/a.jpg">']}
def reset():
    calls.clear(); plan.clear(); notifier._offline_until = 0
queued = lambda: storage.pending_alerts(10)

# --- 1) 텔레그램에 연결하지 못하면 대기열에 넣고, 잠시 동안은 보내 보지 않고 바로 대기열로 (수집이 멈추지 않게)
reset(); plan.extend(['timeout'])
notifier.send_post_alert(post, ['싼타페'], '싼타페', '자동차', 'http://dash#post-901', 'https://www.fmkorea.com/901')
assert [c[0] for c in calls] == ['sendPhoto'], calls                 # 사진에서 시간 초과 → 글은 보내 보지 않음
assert len(queued()) == 1 and queued()[0]['what'] == '새 글 알림'
saved = json.loads(queued()[0]['payload'])
assert saved['parse_mode'] == 'HTML' and 'chat_id' not in saved and '싼타페 &lt;출고&gt;' in saved['text']
assert saved['reply_markup']['inline_keyboard'][0][0]['url'] == 'http://dash#post-901'
calls.clear()
notifier.send_telegram_message('⚠️ 차단 의심')                          # 연결이 안 되는 중 → 바로 대기열
assert calls == [] and [a['what'] for a in queued()] == ['새 글 알림', '상태 알림']
print('QUEUE OK')

# --- 2) 서버 오류(5xx)·요청 과다(429)도 나중에 다시, 형식 오류(400)는 서식 없는 글로 한 번 더 (대기열에 넣지 않음)
reset(); plan.extend([502])
notifier.send_telegram_message('복구')
assert len(queued()) == 3 and notifier._offline()
reset(); plan.extend([400, 200])
assert notifier._send_html({'parse_mode': 'HTML'}, '<b>a</b><blockquote>b</blockquote>', '하루 요약')
assert [('parse_mode' in c[1]) for c in calls] == [True, False] and calls[1][1]['text'] == 'a' + 'b\n' and len(queued()) == 3
print('CLASSIFY OK')

# --- 3) 다음 주기에 오래된 것부터 다시 보냄: 원래 보내려던 시각을 맨 위에 붙이고, 보낸 것은 대기열에서 뺌
reset()
assert notifier.retry_pending_alerts() == 3 and queued() == []
assert [c[0] for c in calls] == ['sendMessage'] * 3
first = calls[0][1]
assert first['chat_id'] == '1' and first['text'].startswith('⏱ ') and '에 보내지 못한 알림' in first['text']
assert '싼타페 &lt;출고&gt;' in first['text'] and first['reply_markup']['inline_keyboard'][0][1]['text'] == '🔗 원문'
assert calls[1][1]['text'].endswith('⚠️ 차단 의심') and 'parse_mode' not in calls[1][1]
# 또 연결이 안 되면 시도 횟수만 늘리고 다음 주기로 (나머지는 보내 보지 않음)
reset(); plan.extend(['timeout'])
notifier.send_telegram_message('하나')
notifier.send_telegram_message('둘')
assert len(queued()) == 2 and len(calls) == 1
reset(); plan.extend(['timeout'])
assert notifier.retry_pending_alerts() == 0 and len(calls) == 1
assert [a['attempts'] for a in queued()] == [1, 0]
# 연결이 안 되는 중에는 다시 보내 보지도 않음
calls.clear()
assert notifier.retry_pending_alerts() == 0 and calls == []
# 24시간이 지난 알림은 포기하고 뺌
notifier._offline_until = 0
with storage._db() as conn, conn:
    conn.execute("UPDATE pending_alerts SET created_at = '2000-01-01 00:00:00' WHERE id = (SELECT MIN(id) FROM pending_alerts)")
assert notifier.retry_pending_alerts() == 1 and queued() == []
assert calls[-1][1]['text'].endswith('둘')
print('RETRY OK')
