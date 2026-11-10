"""인기 글 알림: 게시판마다 정한 추천+댓글 기준을 넘긴 글을 한 번만 알림. 기준을 정하기 전에 모은 글은 알리지 않음"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, json, socket, urllib.request, urllib.error
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, notifier

def post(pid, votes, comments):
    return {'id': pid, 'title': '글 ' + pid, 'author': 'a', 'date': 'd', 'views': '1,000', 'votes': votes, 'comment_count': comments,
            'link': '/' + pid, 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}

storage.init_db()
g1, _ = storage.save_group(None, '핫딜', [{'board': 'hotdeal', 'keyword': '특가'}])
g2, _ = storage.save_group(None, '세일', [{'board': 'hotdeal', 'keyword': '특가'}, {'board': 'hotdeal', 'keyword': '세일'}])
storage.save_keyword_post('hotdeal', '특가', post('901', '500', '300'), is_new=True)   # 기준을 정하기 전에 모은 글
assert storage.popular_posts_to_alert() == []                                          # 꺼져 있으면 없음
assert storage.set_group_popular(g1, 50) == '핫딜' and storage.set_group_popular(999, 50) is None
with storage._db() as conn, conn:
    conn.execute("UPDATE keyword_groups SET popular_since = '2026-01-01 00:00:00' WHERE id = ?", (g1,))
    conn.execute("UPDATE posts SET created_at = '2025-12-31 00:00:00' WHERE id = '901'")
assert storage.popular_posts_to_alert() == []                                          # 예전 글은 쏟아지지 않음
storage.save_keyword_post('hotdeal', '특가', post('902', '30', '10'), is_new=True)     # 40: 아직 기준 아래
storage.save_keyword_post('hotdeal', '특가', post('903', '1,200', '15'), is_new=True)  # 쉼표 숫자
storage.save_keyword_post('hotdeal', '세일', post('904', '70', '0'), is_new=True)      # 인기 알림을 안 켠 게시판의 글
found = storage.popular_posts_to_alert()
assert [(p['id'], p['score'], p['boards']) for p in found] == [('903', 1215, ['핫딜'])], found
assert found[0]['title'] == '글 903' and found[0]['content']

# 수가 올라 기준을 넘으면 그때 알림, 알린 글은 다시 나오지 않음
storage.update_list_stats('902', '2,000', '45', 10)
assert [p['id'] for p in storage.popular_posts_to_alert()] == ['903', '902']
assert [p['id'] for p in storage.popular_posts_to_alert(limit=1)] == ['903']
storage.mark_popular_alerted('903'); storage.mark_popular_alerted('903')
assert [p['id'] for p in storage.popular_posts_to_alert()] == ['902']
# 여러 게시판이 원하면 한 번에 (게시판 이름 모두), 삭제된 글 제외, 끄면 없음
storage.set_group_popular(g2, 20)
with storage._db() as conn, conn:
    conn.execute("UPDATE keyword_groups SET popular_since = '2026-01-01 00:00:00' WHERE id = ?", (g2,))
found = {p['id']: sorted(p['boards']) for p in storage.popular_posts_to_alert()}
assert found == {'902': ['세일', '핫딜'], '904': ['세일']}, found
storage.mark_post_deleted('904')
assert [p['id'] for p in storage.popular_posts_to_alert()] == ['902']
storage.set_group_popular(g1, 0); storage.set_group_popular(g2, 0)
assert storage.popular_posts_to_alert() == []
assert [g['popular_min'] for g in storage.list_groups()] == [0, 0]
print('POPULAR QUERY OK')

text = notifier.build_popular_alert(post('903', '1,200', '15'), ['핫딜', '세일'], 1215)
assert '🔥' in text and '핫딜, 세일' in text and '글 903' in text and '1,215' in text and '👍 1,200' in text, text
print('POPULAR TEXT OK')

# 관리 요청: 암호 필요, 숫자 범위 확인
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
def call(body):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/toggle-alert', data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
assert call({'group': g1, 'type': 'popular', 'min': 30, 'password': 'no'})[0] == 401
for bad in (-1, 100001, '30', 1.5, True, None):
    assert call({'group': g1, 'type': 'popular', 'min': bad, 'password': 'Secr3t!'})[0] == 400, bad
assert call({'group': 999, 'type': 'popular', 'min': 30, 'password': 'Secr3t!'})[0] == 400
code, body = call({'group': g1, 'type': 'popular', 'min': 30, 'password': 'Secr3t!'})
assert code == 200 and body['success'] and '30' in body['message'], (code, body)
assert [g['popular_min'] for g in storage.list_groups()] == [30, 0]
assert call({'group': g1, 'type': 'popular', 'min': 0, 'password': 'Secr3t!'})[1]['success']
print('POPULAR ALERT OK')
