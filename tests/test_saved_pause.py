import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile
from datetime import datetime, timedelta
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', TELEGRAM_TOKEN='', COLLECTOR_STALL_MINUTES='10')
import config
# 로컬 .env의 KEYWORDS_* (config가 불러옴)가 새 DB에 같은 이름의 게시판을 미리 만들지 않게 비움
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage

def post(pid, title):
    return {'id': pid, 'title': title, 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/' + pid, 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}

group_id, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}, {'board': 'car', 'keyword': '쏘렌토'}])
storage.save_keyword_post('car', '싼타페', post('401', '싼타페 출고'), is_new=True)
storage.save_keyword_post('car', '싼타페', post('402', '싼타페 연비'), is_new=True)
storage.save_keyword_post('car', '쏘렌토', post('403', '쏘렌토 시승'), is_new=True)

# --- 1) 보관함: 담기·빼기, 보기별 글 수, 보관함 보기(최근 보관 순), 글마다 보관 여부
assert storage.set_post_saved('401', True) and storage.set_post_saved('403', True)
assert not storage.set_post_saved('999', True)        # 모은 글이 아니면 담지 않음
group = next(g for g in storage.list_groups() if g['id'] == group_id)
assert group['saved_count'] == 2 and storage.feed_summary()['saved_count'] == 2
total, saved = storage.query_all_posts(0, 10, group_id=group_id, saved_only=True)
# (같은 초에 담으면 최근 수집 순)
assert total == 2 and [p['id'] for p in saved] == ['403', '401'], saved
assert all(p['is_saved'] for p in saved)
flags = {p['id']: p['is_saved'] for p in storage.query_all_posts(0, 10, group_id=group_id)[1]}
assert flags == {'401': True, '402': False, '403': True}, flags
assert [p['is_saved'] for p in storage.query_posts_by_ids(['402', '401'])] == [False, True]
storage.set_post_saved('403', False)
assert storage.feed_summary()['saved_count'] == 1
print('SAVED OK')

# --- 2) 오래된 글 정리에서 보관한 글은 남음 (키워드별 최근 글 기준도 0으로 두어 나머지는 모두 정리 대상)
with storage._db() as conn, conn:
    conn.execute("UPDATE posts SET created_at = '2000-01-01 00:00:00'")
assert storage.prune_old_posts(30, 0) == 2
assert storage.existing_post_ids(['401', '402', '403']) == {'401'}
print('PRUNE KEEPS SAVED OK')

# --- 3) 키워드 일시정지: 수집 대상에서 빠지고, 게시판에는 표시, 다시 풀면 수집
storage.save_group(group_id, '싼타페', [{'board': 'car', 'keyword': '싼타페', 'paused': True}, {'board': 'car', 'keyword': '쏘렌토'}])
assert storage.load_keywords()['car'] == ['쏘렌토']
members = {m['keyword']: m['paused'] for m in next(g for g in storage.list_groups() if g['id'] == group_id)['members']}
assert members == {'싼타페': True, '쏘렌토': False}, members
assert storage.query_all_posts(0, 10, group_id=group_id)[0] == 1   # 모은 글은 그대로 보임
# paused를 보내지 않으면 기존 값 유지
storage.save_group(group_id, '싼타페 게시판', [{'board': 'car', 'keyword': '싼타페'}, {'board': 'car', 'keyword': '쏘렌토'}])
assert storage.load_keywords()['car'] == ['쏘렌토']
storage.save_group(group_id, '싼타페', [{'board': 'car', 'keyword': '싼타페', 'paused': False}, {'board': 'car', 'keyword': '쏘렌토'}])
assert storage.load_keywords()['car'] == ['싼타페', '쏘렌토']
print('PAUSE OK')

# --- 4) 수집기 멈춤 감시: 기준 시각에서 10분이 지나면 한 번만 알리고, 다시 움직이면 복구 알림
import runtime_status, web_server
sent = []
web_server.send_telegram_message = sent.append
fmt = lambda t: t.strftime('%Y-%m-%d %H:%M:%S')
now = datetime.now()
status = {'started_at': fmt(now - timedelta(hours=1)), 'next_check_at': None, 'progress_at': None, 'last_cycle': None}
runtime_status.snapshot = lambda: dict(status, now=fmt(now))
watch_started = now - timedelta(hours=1)

status['progress_at'] = fmt(now - timedelta(minutes=3))
assert web_server.check_collector(None, watch_started) is None and not sent
# 다음 주기 예정 시각이 아직 안 왔으면 (차단 의심으로 오래 쉬는 중) 멈춘 것이 아님
status.update(progress_at=fmt(now - timedelta(minutes=50)), next_check_at=fmt(now + timedelta(minutes=5)))
assert web_server.check_collector(None, watch_started) is None and not sent
status.update(next_check_at=fmt(now - timedelta(minutes=12)), last_cycle={'finished_at': fmt(now - timedelta(minutes=14))})
alerted = web_server.check_collector(None, watch_started)
assert alerted and len(sent) == 1 and '멈춘' in sent[0] and '12분째' in sent[0], sent
assert web_server.check_collector(alerted, watch_started) == alerted and len(sent) == 1   # 계속 멈춰 있어도 다시 알리지 않음
status['progress_at'] = fmt(now)
assert web_server.check_collector(alerted, watch_started) is None and len(sent) == 2 and '다시 동작' in sent[1], sent
# 수집기 상태가 아예 없으면 감시를 시작한 시각부터 셈
status.update(started_at=None, next_check_at=None, progress_at=None)
assert web_server.check_collector(None, now - timedelta(minutes=5)) is None and len(sent) == 2
assert web_server.check_collector(None, now - timedelta(minutes=11)) and len(sent) == 3
print('WATCH OK')
