import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, importlib.util, time
from datetime import datetime, timedelta
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='t', TELEGRAM_CHAT_ID='1',
                  DDNS_URL='http://dash', DIGEST_HOUR='0')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, notifier

def post(pid, title, votes='0', comments=None, comment_count='0', views='1'):
    return {'id': pid, 'title': title, 'author': 'a', 'date': 'd', 'views': views, 'votes': votes,
            'comment_count': comment_count, 'link': '/' + pid if not pid.startswith('dc-') else 'https://gall/' + pid,
            'content': ['<p>본문</p>'], 'videos': [], 'comments': comments or []}

storage.init_db()
storage.add_category('dc:car_new1')
storage.set_category_checked('dc:car_new1', True, page_name='자동차 갤러리')

# --- 1) 사이트를 넘나드는 게시판과 합치기
fm_id, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
dc_id, _ = storage.save_group(None, '싼타페', [{'board': 'dc:car_new1', 'keyword': '싼타페'}, {'board': 'dc:car_new1', 'keyword': '싼타페 하이브리드'}])
storage.save_keyword_post('car', '싼타페', post('501', 'FM 글'), is_new=True)
storage.save_keyword_post('dc:car_new1', '싼타페', post('dc-car_new1-9', 'DC 글'), is_new=True)
storage.set_group_alert(fm_id, 'video_alert', False)
# FM 게시판에 DC 게시판을 합침 (이름이 같아도 됨, 합친 게시판은 지워지고 키워드·글은 남음)
members = [{'board': 'car', 'keyword': '싼타페'}, {'board': 'dc:car_new1', 'keyword': '싼타페'},
           {'board': 'dc:car_new1', 'keyword': '싼타페 하이브리드'}]
saved_id, dropped = storage.save_group(fm_id, '싼타페', members, merge_ids=[dc_id])
groups = storage.list_groups()
assert saved_id == fm_id and dropped == [] and [g['id'] for g in groups] == [fm_id], groups
merged = groups[0]
assert merged['site'] == 'multi' and len(merged['members']) == 3 and merged['total'] == 2, merged
assert merged['video_alert'] is False                                     # 알림 설정은 남는 게시판 것
assert sorted(p['id'] for p in storage.query_all_posts(0, 10, group_id=fm_id)[1]) == ['501', 'dc-car_new1-9']
# 여러 사이트 게시판끼리만 이름 중복 검사, 없는 게시판은 합칠 수 없음
for args, message in [((None, '싼타페', members[:2]), '여러 사이트에 같은 이름'), ((fm_id, '싼타페', members, [999]), '합칠 게시판이 없습니다')]:
    try:
        storage.save_group(*args)
        raise AssertionError('저장되면 안 됨')
    except ValueError as e:
        assert message in str(e), e
# 한 사이트 키워드만 남기면 다시 그 사이트 게시판
tmp_id, _ = storage.save_group(None, '임시', [{'board': 'car', 'keyword': '캐스퍼'}, {'board': 'dc:car_new1', 'keyword': '캐스퍼'}])
storage.save_group(tmp_id, '임시', [{'board': 'car', 'keyword': '캐스퍼'}])
assert next(g for g in storage.list_groups() if g['id'] == tmp_id)['site'] == 'fmkorea'
storage.delete_group(tmp_id)
print('MULTI SITE OK')

# --- 2) 보관한 글: 새 댓글 반환, 확인할 글 고르기, 새 댓글 알림
c1 = {'author': 'x', 'date': '1', 'votes': '0', 'content': ['첫 댓글'], 'is_reply': False}
c2 = {'author': 'y', 'date': '2', 'votes': '0', 'content': ['<b>새</b> 댓글'], 'is_reply': False}
storage.update_post(post('501', 'FM 글', comments=[c1]))
assert storage.update_post(post('501', 'FM 글', comments=[c1])) == []
new = storage.update_post(post('501', 'FM 글', comments=[c1, c2]))
assert [c['author'] for c in new] == ['y'], new
storage.set_post_saved('501', True)
storage.set_post_saved('dc-car_new1-9', True)
r = storage.saved_posts_to_check(30, {'501'}, 5); assert [p['id'] for p in r] == ['dc-car_new1-9'], r   # 목록으로 감시하는 글 제외
storage.mark_saved_checked('dc-car_new1-9')
assert [p['id'] for p in storage.saved_posts_to_check(30, set(), 5)] == ['501']               # 방금 확인한 글은 빼고
with storage._db() as conn, conn:
    conn.execute("UPDATE saved_posts SET checked_at = '2000-01-01 00:00:00' WHERE post_id = 'dc-car_new1-9'")
assert [p['id'] for p in storage.saved_posts_to_check(30, set(), 5)] == ['501', 'dc-car_new1-9']   # 확인 안 한 글부터
assert storage.saved_comment_alert() is True
storage.set_saved_comment_alert(False)
assert storage.saved_comment_alert() is False
storage.set_saved_comment_alert(True)
text = notifier.build_comment_alert(post('501', 'FM <글>'), new)
assert '보관한 글에 새 댓글 1개' in text and 'FM &lt;글&gt;' in text and 'y: 새 댓글' in text, text
print('SAVED COMMENTS OK')

# --- 3) 하루 요약: 최근 24시간 새 글 중 추천+댓글 순, 이미 본 글·삭제된 글 제외
storage.save_keyword_post('car', '싼타페', post('502', '인기 글', votes='10', comment_count='30'), is_new=True)
storage.save_keyword_post('car', '싼타페', post('503', '보통 글', votes='3', comment_count='1,200'), is_new=True)
storage.save_keyword_post('car', '싼타페', post('504', '첫 페이지로 채운 글', votes='99'), is_new=False)
storage.save_keyword_post('car', '싼타페', post('505', '삭제된 글', votes='50'), is_new=True)
storage.mark_post_deleted('505')
since = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
total, top = storage.digest_posts(fm_id, since, limit=2)
assert total == 4 and [p['id'] for p in top] == ['503', '502'], (total, top)
assert storage.digest_posts(fm_id, (datetime.now() + timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S'))[0] == 0
digest = notifier.build_digest('싼타페 & 쏘렌토', total, top, lambda p: 'http://dash#post-' + p['id'])
assert '<b>싼타페 &amp; 쏘렌토</b> 하루 요약' in digest and '<a href="http://dash#post-503">보통 글</a>' in digest and '1,200' in digest, digest
print('DIGEST QUERY OK')

# --- 4) 수집기: 하루 한 번만 요약 발송, 보관한 글 새 댓글 알림은 설정을 따름
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
digests, comment_alerts = [], []
m.send_digest = lambda name, total, posts, url: digests.append((name, total, [p['id'] for p in posts], url(posts[0]))) or True
m.send_comment_alert = lambda p, new, *urls: comment_alerts.append((p['id'], len(new), urls))
m.send_daily_digests()
assert digests == [] and storage.get_meta('digest_date')     # 하루 요약을 켠 게시판이 없음
storage.set_meta('digest_date', '')
storage.set_group_alert(fm_id, 'digest', True)
assert storage.list_groups()[0]['digest'] is True
m.send_daily_digests(); m.send_daily_digests()
assert len(digests) == 1 and digests[0][:2] == ('싼타페', 4) and digests[0][2][:2] == ['503', '502'], digests
assert digests[0][3] == 'http://dash/board/#post-503', digests
m.notify_saved_comments(post('501', 'FM 글'), new)
m.notify_saved_comments(post('502', '보관 안 한 글'), new)
storage.set_saved_comment_alert(False)
m.notify_saved_comments(post('501', 'FM 글'), new)
assert comment_alerts == [('501', 1, ('http://dash/board/#post-501', 'https://www.fmkorea.com/501'))], comment_alerts
print('SCRAPER HOOKS OK')
