import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='WARN', KEYWORDS_BASEBALL='')
import storage
from matching import keyword_in_post

# 1) 무시할 표현을 지운 뒤에 키워드를 찾음 (대소문자·연속 공백 무시, 지운 자리 앞뒤가 이어 붙지 않음)
assert keyword_in_post('싼하', '투싼하브 계약', ['<p>좋아요</p>'])                       # 표현이 없으면 예전처럼 걸림
assert not keyword_in_post('싼하', '투싼하브 계약', ['<p>좋아요</p>'], ['투싼하'])
assert keyword_in_post('싼하', '투싼하브 vs 싼하', [], ['투싼하'])                         # 다른 곳에 따로 있으면 모음
assert keyword_in_post('싼하', '투싼하브', ['<p>저는 <b>싼하</b> 샀어요</p>'], ['투싼하'])   # 본문에 따로 있어도 모음
assert not keyword_in_post('싼하', '싼투싼하하', [], ['투싼하'])                           # 지운 자리로 '싼'+'하'가 붙지 않음
assert not keyword_in_post('galaxy', 'Galaxy  Tab 후기', [], ['GALAXY tab'])
print('matching OK')

def post(pid, title):
    return {'id': pid, 'title': title, 'author': 'a', 'date': 'd', 'views': '1', 'votes': '0', 'comment_count': '0',
            'link': '/' + pid, 'content': ['<p>본문</p>'], 'videos': [], 'comments': []}

car_id, _ = storage.save_group(None, '싼타페', [{'board': 'car', 'keyword': '싼하'}, {'board': 'car', 'keyword': '싼타페'}])
other_id, _ = storage.save_group(None, '하이브리드', [{'board': 'car', 'keyword': '싼하'}])
storage.save_keyword_post('car', '싼하', post('301', '투싼하브 계약하고나니 심장떨림'), is_new=True)
storage.save_keyword_post('car', '싼하', post('302', '투싼하브 vs 싼하 고민'), is_new=True)
storage.save_keyword_post('car', '싼하', post('303', '싼하 연비 맛있다'), is_new=True)
storage.save_keyword_post('car', '싼하', post('304', '싼 하이브리드 출고'), is_new=True)   # 예전 방식으로 모인 글 (키워드가 그대로 없음)
storage.save_keyword_post('car', '싼타페', post('301', '투싼하브 계약하고나니 심장떨림'), is_new=True)  # 다른 키워드에도 걸린 글

def ids(group_id):
    return sorted(p['id'] for p in storage.query_all_posts(0, 50, group_id=group_id)[1])

assert ids(other_id) == ['301', '302', '303', '304']

# 2) 표현을 저장하면 이미 모은 글 중 그 표현 때문에만 걸린 글(301)만 '싼하'에서 빠짐
#    (304는 표현과 상관없이 원래 키워드가 없던 글이라 그대로, 301은 '싼타페' 키워드로도 모였으므로 글 자체는 남음)
storage.save_group(car_id, '싼타페', [{'board': 'car', 'keyword': '싼하', 'ignores': ['투싼하', ' 투싼하 ']},
                                      {'board': 'car', 'keyword': '싼타페'}])
assert ids(other_id) == ['302', '303', '304'], ids(other_id)
assert ids(car_id) == ['301', '302', '303', '304'], ids(car_id)   # 301은 '싼타페' 키워드로 남아 있음
assert storage.load_keyword_ignores() == {('car', '싼하'): ['투싼하']}, storage.load_keyword_ignores()
print('recheck OK')

# 3) 키워드에 붙으므로 같은 키워드를 쓰는 다른 게시판에서도 보임. ignores를 보내지 않으면 그대로 둠
groups = {g['id']: g for g in storage.list_groups()}
assert groups[other_id]['members'] == [{'board': 'car', 'keyword': '싼하', 'ignores': ['투싼하']}], groups[other_id]['members']
storage.save_group(other_id, '하이브리드', [{'board': 'car', 'keyword': '싼하'}])
assert storage.load_keyword_ignores() == {('car', '싼하'): ['투싼하']}
print('shared OK')

# 4) 키워드가 어느 게시판에도 남지 않으면 무시할 표현도 함께 삭제
storage.delete_group(other_id)
storage.save_group(car_id, '싼타페', [{'board': 'car', 'keyword': '싼타페'}])
assert storage.load_keyword_ignores() == {}
print('IGNORES OK')
