import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, sqlite3
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, config

def post(pid, title):
    return {'id': pid, 'title': title, 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/' + pid, 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}

# --- 1) 묶음을 도입하기 전 DB: 게시판의 사이트별로 묶음을 1회 만들어 옮김 (여러 사이트 게시판은 '통합')
storage.init_db()
storage.add_category('dc:car_new1')
storage.set_category_checked('dc:car_new1', True, page_name='자동차 갤러리')
santafe, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼타페'}, {'board': 'dc:car_new1', 'keyword': '싼타페'}])
samsung, _ = storage.save_group(None, '삼성', [{'board': 'baseball', 'keyword': '삼성'}])
claude, _ = storage.save_group(None, '클로드', [{'board': 'car', 'keyword': '클로드'}])
with sqlite3.connect(config.DB_FILE) as db:
    db.execute("DELETE FROM meta WHERE key = 'site_folders_migrated'")
    db.execute("DELETE FROM group_folders")
    db.execute("UPDATE keyword_groups SET folder_id = NULL")
storage._initialized = False
storage.init_db()
folders = storage.list_folders()
assert [f['name'] for f in folders] == ['통합', '에펨코리아'], folders
by_name = {g['name']: g for g in storage.list_groups()}
assert by_name['싼타페']['folder_id'] == folders[0]['id'] and by_name['삼성']['folder_id'] == folders[1]['id']
storage._initialized = False
storage.init_db()                                         # 다시 열어도 또 만들지 않음
assert len(storage.list_folders()) == 2
print('FOLDER MIGRATION OK')

# --- 2) 묶음 만들기·이름·순서·삭제
car = storage.save_folder(None, '자동차')
etc = folders[1]['id']
storage.save_folder(etc, '기타')
try:
    storage.save_folder(None, '기타')
    raise AssertionError('같은 이름의 묶음이 만들어짐')
except ValueError as e:
    assert '같은 이름' in str(e)
storage.move_folder(car, 'up'); storage.move_folder(car, 'up'); storage.move_folder(car, 'up')   # 맨 위에서 더 올려도 그대로
assert [f['name'] for f in storage.list_folders()] == ['자동차', '통합', '기타']
print('FOLDER EDIT OK')

# --- 3) 게시판 옮기기·순서, 묶음 피드 (묶음 안 게시판끼리 겹치는 글은 한 번만)
assert storage.arrange_group(santafe, car) == '싼타페'
assert storage.arrange_group(claude, etc) == '클로드'
storage.arrange_group(claude, direction='up')                 # 기타 안에서 삼성보다 위로
assert [g['name'] for g in storage.list_groups() if g['folder_id'] == etc] == ['클로드', '삼성']
assert storage.arrange_group(999, car) is None
try:
    storage.arrange_group(santafe, 999)
    raise AssertionError('없는 묶음으로 옮겨짐')
except ValueError:
    pass
casper, _ = storage.save_group(None, '캐스퍼', [{'board': 'car', 'keyword': '캐스퍼'}, {'board': 'car', 'keyword': '싼타페'}], folder_id=car)
assert next(g for g in storage.list_groups() if g['id'] == casper)['folder_id'] == car
storage.save_keyword_post('car', '싼타페', post('601', '싼타페 글'), is_new=True)
storage.save_keyword_post('car', '캐스퍼', post('602', '캐스퍼 글'), is_new=True)
storage.save_keyword_post('baseball', '삼성', post('603', '삼성 글'), is_new=True)
car_summary = next(f for f in storage.list_folders() if f['id'] == car)
assert car_summary['total'] == 2 and car_summary['unread_count'] == 2, car_summary
total, posts = storage.query_all_posts(0, 10, folder_id=car)
assert total == 2 and sorted(p['id'] for p in posts) == ['601', '602']
# 묶음을 지우면 게시판은 묶음 없이 남음
assert storage.delete_folder(car) and not storage.delete_folder(car)
assert all(g['folder_id'] is None for g in storage.list_groups() if g['name'] in ('싼타페', '캐스퍼'))
print('FOLDER GROUPS OK')
