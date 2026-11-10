"""통계 화면: 최근 N일 동안 처음 수집한 글 수를 날짜·시간대·게시판·키워드별로 (같은 글은 한 번만)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, urllib.request
from datetime import datetime, timedelta
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server

def post(pid):
    return {'id': pid, 'title': pid, 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/' + pid, 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}

storage.init_db()
g1, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}, {'board': 'car', 'keyword': '싼하'}])
g2, _ = storage.save_group(None, '캐스퍼', [{'board': 'car', 'keyword': '캐스퍼'}])
g3, _ = storage.save_group(None, '빈 게시판', [{'board': 'car', 'keyword': '없음'}])
today = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
when = {'501': today, '502': today.replace(hour=21), '503': today - timedelta(days=1), '504': today - timedelta(days=6),
        '505': today - timedelta(days=7), '506': today - timedelta(days=40)}
for pid, kw in [('501', '싼타페'), ('502', '싼타페'), ('503', '캐스퍼'), ('504', '싼타페'), ('505', '캐스퍼'), ('506', '싼타페')]:
    storage.save_keyword_post('car', kw, post(pid), is_new=True)
storage.save_keyword_post('car', '싼하', post('501'), is_new=True)      # 같은 글이 두 키워드에: 한 번만 셈
with storage._db() as conn, conn:
    for pid, at in when.items():
        conn.execute("UPDATE posts SET created_at = ? WHERE id = ?", (at.strftime('%Y-%m-%d %H:%M:%S'), pid))

s = storage.stats_summary(7)
assert s['days'] == 7 and s['total'] == 4 and s['previous'] == 1, s
assert [d['count'] for d in s['daily']] == [1, 0, 0, 0, 0, 1, 2] and s['daily'][-1]['date'] == today.strftime('%Y-%m-%d')
assert sum(s['hours']) == 4 and s['hours'][9] == 3 and s['hours'][21] == 1
assert [(g['name'], g['count']) for g in s['groups']] == [('싼타페', 3), ('캐스퍼', 1), ('빈 게시판', 0)], s['groups']
assert [(k['keyword'], k['count']) for k in s['keywords']] == [('싼타페', 3), ('싼하', 1), ('캐스퍼', 1)], s['keywords']
only = storage.stats_summary(7, g2)
assert only['total'] == 1 and only['previous'] == 1 and len(only['groups']) == 3 and [k['keyword'] for k in only['keywords']] == ['캐스퍼']
wide = storage.stats_summary(90)
assert wide['total'] == 6 and len(wide['daily']) == 90 and wide['previous'] == 0
print('STATS QUERY OK')

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def get(path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}') as res:
        return res.status, res.read()
data = json.loads(get('/api/stats?days=7')[1])
assert data['total'] == 4 and data['keywords'][0]['board_name'] == '자동차'
assert json.loads(get('/api/stats?days=999')[1])['days'] == 30                 # 없는 기간 값은 기본 30일
assert json.loads(get(f'/api/stats?days=7&group={g2}')[1])['total'] == 1
for path in ('/stats/', '/stats.js', '/stats.css'):
    assert get(path)[0] == 200
assert b'card-stats' in get('/')[1]
print('STATS OK')
