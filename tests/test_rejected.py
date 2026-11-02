"""거른 글(검색에는 걸렸지만 키워드가 그대로 없는 글) 기억: 재시작 후에도 남고, 무시할 표현을 바꾸거나 키워드를 지우면 잊고,
하루 한 번 키워드마다 최근 것만 남김"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, importlib.util
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

storage.init_db()
dc_id, _ = storage.save_group(None, '디시 자동차', [{'board': 'dc:car_new1', 'keyword': 'A6'}])
fm_id, _ = storage.save_group(None, '에펨 자동차', [{'board': 'car', 'keyword': '싼하'}])

# 1) 거른 글은 메모리와 DB에 함께 남아, 다시 시작해 읽어도 그대로 (같은 글을 두 번 걸러도 한 줄)
rejected = storage.load_rejected_posts()
assert rejected == set()
m.reject(rejected, 'dc:car_new1', 'A6', 'dc-car_new1-11563832')
m.reject(rejected, 'dc:car_new1', 'A6', 'dc-car_new1-11563832')
m.reject(rejected, 'car', '싼하', '10510289841')
assert ('dc:car_new1', 'A6', 'dc-car_new1-11563832') in rejected
assert storage.load_rejected_posts() == rejected == {('dc:car_new1', 'A6', 'dc-car_new1-11563832'), ('car', '싼하', '10510289841')}
print('PERSIST OK')

# 2) 새 글 확인: 거른 글은 상세 페이지를 다시 열지 않음
opened = []
def fake_detail(driver, info, all_comment_pages=True):
    opened.append(info['id'])
    return dict(info, views='1', votes='0', comment_count='0', content=[], videos=[], comments=[])
m.scrape_post_detail = fake_detail
listed = [{'id': 'dc-car_new1-11563832', 'title': '국산차 추천', 'author': 'a', 'date': '', 'link': '/1', 'list_comment_count': 0},
          {'id': 'dc-car_new1-11563900', 'title': 'A6 시승기', 'author': 'a', 'date': '', 'link': '/2', 'list_comment_count': 0}]
stats = {'details': 0, 'errors': 0}
assert m.save_first_page(None, 'dc:car_new1', 'A6', '자동차/A6', listed, [], storage.load_rejected_posts(), stats) == 1
assert opened == ['dc-car_new1-11563900'], opened
print('SKIP OK')

# 3) 무시할 표현을 바꾸면 그 키워드의 거른 글만 잊음 (바뀐 기준으로 다시 판별)
storage.save_group(fm_id, '에펨 자동차', [{'board': 'car', 'keyword': '싼하', 'ignores': ['투싼하']}])
assert storage.load_rejected_posts() == {('dc:car_new1', 'A6', 'dc-car_new1-11563832')}, storage.load_rejected_posts()
# 표현이 그대로면 잊지 않음
storage.save_group(fm_id, '에펨 자동차', [{'board': 'car', 'keyword': '싼하', 'ignores': ['투싼하']}])
assert storage.load_rejected_posts() == {('dc:car_new1', 'A6', 'dc-car_new1-11563832')}
print('IGNORES OK')

# 4) 하루 한 번 정리: 키워드마다 최근 것만 남김
for i in range(5):
    storage._now = lambda i=i: f'2026-11-02 15:00:0{i}'
    storage.add_rejected_post('car', '싼하', f'90{i}')
assert storage.prune_rejected_posts(3) == 2   # 싼하 5개 중 오래된 2개 (A6는 1개라 그대로)
left = storage.load_rejected_posts()
assert {p for b, k, p in left if k == '싼하'} == {'902', '903', '904'}, left
assert ('dc:car_new1', 'A6', 'dc-car_new1-11563832') in left
print('PRUNE OK')

# 5) 키워드가 어느 게시판에도 없게 되면 그 키워드의 거른 글도 지움
storage.delete_group(dc_id)
assert not any(k == 'A6' for _, k, _ in storage.load_rejected_posts())
print('REJECTED OK')
