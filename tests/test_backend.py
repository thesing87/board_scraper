import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, shutil, tempfile, json, time
src = DATA_DIR
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(src, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', LOG_LEVEL='WARN')
import storage, web_server

storage.init_db()
# 1) 통합 피드: 중복 없이, 여러 키워드 연결 정보 포함
total_all, posts = storage.query_all_posts(0, 10)
tabs = storage.list_groups()
sum_tabs = sum(t['total'] for t in tabs)
print('all total', total_all, 'sum of tabs', sum_tabs)
assert total_all < sum_tabs and total_all == storage.feed_summary()["total"]
ids = [p['id'] for p in posts]
assert len(ids) == len(set(ids))
multi = [p for p in storage.query_all_posts(0, 500)[1] if len(p['keywords']) > 1]
print('posts in multiple keywords', len(multi), multi[0]['keywords'] if multi else None)
assert multi

# 2) 검색: 여러 단어 AND, 대소문자 무시, LIKE 특수문자 안전
t1, r1 = storage.query_all_posts(0, 50, query='싼타페')
t2, r2 = storage.query_all_posts(0, 50, query='싼타페 하이브리드')
t3, _ = storage.query_all_posts(0, 50, query='EV5')
t4, _ = storage.query_all_posts(0, 50, query='ev5')
t5, _ = storage.query_all_posts(0, 50, query='100%_')
print('search', t1, t2, t3, t4, t5)
assert t1 > 0 and t2 <= t1 and t3 == t4 and t3 > 0
# 댓글 내용으로도 검색
c_text = None
for p in r1:
    if p['comments']:
        c_text = storage._plain_text(p['comments'][0]['content']).split()[0]
        break
if c_text:
    tc, _ = storage.query_all_posts(0, 50, query=c_text)
    print('comment search', c_text, tc)
    assert tc > 0

# 3) 읽음: 안 읽은 새 글 목록에서 빠짐
tab = next(t for t in tabs if t['unread_ids'])
target = tab['unread_ids'][0]
storage.mark_posts_read([target, 'abc', '1 OR 1'])
tabs2 = storage.list_groups()
tab2 = next(t for t in tabs2 if t['id'] == tab['id'])
assert target not in tab2['unread_ids'] and len(tab2['unread_ids']) == len(tab['unread_ids']) - 1
_, kp = storage.query_all_posts(0, 500, group_id=tab['id'])
assert next(p for p in kp if p['id'] == target)['read_at']

# 4) 새 댓글 판별: 기존 댓글은 first_seen 유지, 새 댓글만 지금 시각
p = next(p for p in kp if p['id'] == target)
read_at = p['read_at']
time.sleep(1.1)
updated = dict(p)
updated['comments'] = [dict(c) for c in p['comments']] + [{'author': '테스터', 'date': '방금', 'votes': '0', 'content': ['새로 달린 댓글'], 'is_reply': False}]
for c in updated['comments']:
    c.pop('first_seen', None)  # 수집기는 first_seen 없이 넘겨줌
storage.update_post(updated)
_, kp2 = storage.query_all_posts(0, 500, group_id=tab['id'])
p2 = next(x for x in kp2 if x['id'] == target)
new_comments = [c for c in p2['comments'] if c.get('first_seen') and c['first_seen'] > read_at]
print('comments', len(p2['comments']), 'new since read', len(new_comments), new_comments[0]['author'] if new_comments else None)
assert len(new_comments) == 1 and new_comments[0]['author'] == '테스터'
assert storage.query_all_posts(0, 5, query='새로 달린 댓글')[0] >= 1

# 5) API 응답 형태
st = web_server.build_state()
assert 'all' in st and st['all']['total'] == total_all and all('unread_ids' in t for t in st['groups'])
pg = web_server.build_posts_page(1, False)
assert pg['total'] == total_all and 'keywords' in pg['posts'][0] and 'board_name' in pg['posts'][0]['keywords'][0]
pq = web_server.build_posts_page(1, False, query='싼타페')
assert pq['total'] == t1
print('BACKEND OK')
