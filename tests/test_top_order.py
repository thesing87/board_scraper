import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, sqlite3
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, config

# 맨 위 단계 순서: 묶음 없는 게시판과 묶음을 한 줄로 섞어 옮김
storage.init_db()
g = {n: storage.save_group(None, n, [{'board': 'car', 'keyword': n}])[0] for n in ['가', '나', '다', '라']}
f1 = storage.save_folder(None, '묶음1')
f2 = storage.save_folder(None, '묶음2')
empty = storage.save_folder(None, '빈묶음')
storage.arrange_group(g['다'], f1)
storage.arrange_group(g['라'], f2)

def top():
    with storage._db() as conn:
        names = {('g', r[0]): r[1] for r in conn.execute("SELECT id, name FROM keyword_groups")}
        names.update({('f', r[0]): r[1] for r in conn.execute("SELECT id, name FROM group_folders")})
        return [names[i] for i in storage._top_items(conn)]

assert top() == ['가', '나', '묶음1', '묶음2', '빈묶음'], top()
# 묶음 없는 게시판을 묶음 사이·맨 아래로
storage.arrange_group(g['나'], direction='down')
assert top() == ['가', '묶음1', '나', '묶음2', '빈묶음'], top()
storage.arrange_group(g['나'], direction='down')
assert top() == ['가', '묶음1', '묶음2', '나', '빈묶음'], top()
# 사이드바에 안 보이는 빈 묶음은 건너뜀 (이미 보이는 것 중 맨 아래라 그대로)
storage.arrange_group(g['나'], direction='down')
assert top() == ['가', '묶음1', '묶음2', '나', '빈묶음'], top()
# 묶음도 게시판 사이로 옮김
assert storage.move_folder(f1, 'up')
assert top() == ['묶음1', '가', '묶음2', '나', '빈묶음'], top()
# 묶음 안 게시판은 그 묶음 안에서만 (묶음1 안에 '가'를 넣고 순서 바꾸기)
storage.arrange_group(g['가'], f1)
assert top() == ['묶음1', '묶음2', '나', '빈묶음'], top()
storage.arrange_group(g['가'], direction='up')
assert [x['name'] for x in storage.list_groups() if x['folder_id'] == f1] == ['가', '다']
# 묶음에서 빼면 맨 아래로
storage.arrange_group(g['라'], None)
assert top() == ['묶음1', '묶음2', '나', '빈묶음', '라'], top()
# 묶음을 지우면 안의 게시판이 그 자리에
assert storage.delete_folder(f1)
assert top() == ['가', '다', '묶음2', '나', '빈묶음', '라'], top()
# 새 게시판·새 묶음은 맨 아래
storage.save_group(None, '마', [{'board': 'car', 'keyword': '마'}])
storage.save_folder(None, '묶음3')
assert top()[-2:] == ['마', '묶음3'], top()
# API에 순서 값이 실림
assert all('position' in x for x in storage.list_groups()) and all('position' in x for x in storage.list_folders())

# 기존 DB 이전: 묶음 없는 게시판이 묶음보다 앞이던 순서를 그대로 한 줄 번호로
with storage._db() as conn, conn:
    conn.execute("UPDATE group_folders SET position = 1")
    conn.execute("UPDATE keyword_groups SET position = 5 WHERE folder_id IS NULL")
    conn.execute("DELETE FROM meta WHERE key = 'top_order_merged'")
    storage._migrate_top_order(conn)
assert top()[:5] == ['가', '나', '다', '라', '마'] and set(top()[5:]) == {'묶음2', '빈묶음', '묶음3'}, top()
print('TOP ORDER OK')
