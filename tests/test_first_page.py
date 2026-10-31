import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, importlib.util
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), TELEGRAM_TOKEN='', LOG_LEVEL='WARN')
import config
# 로컬 .env의 KEYWORDS_* (config가 불러옴)가 새 DB에 키워드를 미리 넣지 않게 비움
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

storage.init_db()
storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])

# 목록 첫 페이지 (최신순): 키워드 없는 글 1개, 원문 삭제된 글 1개 포함
LIST = [{'id': str(100 + i), 'link': f'/{100 + i}', 'title': f'싼타페 글 {i}', 'author': 'a', 'date': 'd',
         'list_comment_count': i} for i in range(5, 0, -1)]
LIST.insert(1, {'id': '200', 'link': '/200', 'title': '투싼 이야기', 'author': 'a', 'date': 'd', 'list_comment_count': 0})
DELETED = '102'
calls = []
fail_on = set()

def fake_detail(driver, info):
    calls.append(info['id'])
    if info['id'] in fail_on:
        raise RuntimeError('일시적 실패')
    if info['id'] == DELETED:
        return None
    return {'id': info['id'], 'title': info['title'], 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0',
            'comment_count': '0', 'link': info['link'], 'content': [f"<p>{info['title']}</p>"], 'videos': [], 'comments': []}
m.scrape_post_detail = fake_detail

def run():
    stats = {'details': 0, 'errors': 0}
    saved = m.save_first_page(None, 'car', '싼타페', '자동차/싼타페', LIST, [], rejected, stats)
    return saved, stats

# 1) 상세 수집 중 하나라도 실패하면 아무것도 저장하지 않음 (다음 주기에 처음부터 다시)
rejected = set()
fail_on = {'103'}
saved, stats = run()
assert saved == 0 and stats['errors'] == 1 and storage.recent_keyword_posts('car', '싼타페', 50) == [], stats
print('fail → nothing saved OK')

# 2) 첫 페이지에서 키워드가 있는 글을 모두 저장 (키워드 없는 글·삭제된 글 제외), 알림·NEW 없음, 목록 순서 유지
fail_on = set()
calls.clear()
saved, stats = run()
posts = storage.recent_keyword_posts('car', '싼타페', 50)
assert saved == 4 and [p['id'] for p in posts] == ['105', '104', '103', '101'], posts
assert ('car', '싼타페', '200') in rejected
assert storage.unread_summary()['total'] == 0          # 이미 본 글로 저장 (NEW·알림 없음)
assert {p['id']: p['list_comment_count'] for p in posts}['104'] == 4
# 키워드 없던 글은 다음에도 다시 열지 않음
calls.clear()
run()
assert '200' not in calls
print('FIRST PAGE OK')

# 3) 예전 방식으로 등록된 디시 키워드(최신 글 1개만 저장된 상태)를 첫 페이지 글로 1회 채움
storage.add_category('dc:car_new1')
storage.set_category_checked('dc:car_new1', True, page_name='자동차 갤러리')
storage.save_group(None, 'DC 싼타페', [{'board': 'dc:car_new1', 'keyword': '싼타페'}])
DC_LIST = [{'id': f'dc-car_new1-{n}', 'link': f'/dc{n}', 'title': f'싼타페 디시 {n}', 'author': 'a', 'date': 'd',
            'list_comment_count': 0} for n in (509, 508, 507, 506, 505)]
# 기준점 1개(507)와 그 뒤에 새 글로 들어온 1개(509, 안 읽음)가 저장된 상태
storage.save_keyword_post('dc:car_new1', '싼타페', fake_detail(None, DC_LIST[2]), is_new=False)
storage.save_keyword_post('dc:car_new1', '싼타페', fake_detail(None, DC_LIST[0]), is_new=True)
board_data = storage.recent_keyword_posts('dc:car_new1', '싼타페', 50)
calls.clear()
fail_on = {'dc-car_new1-505'}
stats = {'details': 0, 'errors': 0}
assert m.fill_first_page(None, 'dc:car_new1', '싼타페', 'DC/싼타페', DC_LIST, board_data, [], set(), stats) is False
assert [p['id'] for p in storage.recent_keyword_posts('dc:car_new1', '싼타페', 50)] == ['dc-car_new1-509', 'dc-car_new1-507']
fail_on = set()
calls.clear()
assert m.fill_first_page(None, 'dc:car_new1', '싼타페', 'DC/싼타페', DC_LIST, board_data, [], set(), stats) is True
# 저장된 가장 최신 글(509)보다 새 글은 없으므로, 그보다 오래된 508·506·505만 새로 받음 (507은 이미 있음)
assert sorted(calls) == ['dc-car_new1-505', 'dc-car_new1-506', 'dc-car_new1-508'], calls
# 목록 순서대로 정렬되고, 509는 계속 안 읽은 새 글, 채운 글은 이미 본 글
assert [p['id'] for p in storage.recent_keyword_posts('dc:car_new1', '싼타페', 50)] == [p['id'] for p in DC_LIST]
assert storage.site_feed_summaries()['dcinside']['unread_ids'] == ['dc-car_new1-509']
storage.mark_first_page_filled('dc:car_new1', '싼타페')
assert 'dc:car_new1|싼타페' in storage.first_page_filled_keys()
print('DC FILL OK')
