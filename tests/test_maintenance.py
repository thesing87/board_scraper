import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR
import shutil, tempfile, sqlite3, importlib.util, io, contextlib, json, threading, urllib.request
tmp = tempfile.mkdtemp()
for f in ['board_data_backup.json', 'keywords_config.json', 'board_config.json']:
    shutil.copy(os.path.join(DATA_DIR, f), tmp)
os.environ.update(OUTPUT_DIR=tmp, ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LOG_LEVEL='WARN')
import storage, config, runtime_status, web_server

storage.init_db()
db = sqlite3.connect(config.DB_FILE)
total_posts = db.execute('select count(*) from posts').fetchone()[0]

# 1) DB 백업: 하루 한 파일, 같은 날 두 번째는 건너뜀, 최근 keep개만 보관, 복사본은 그대로 열림
bdir = os.path.join(tmp, 'backups')
os.makedirs(bdir)
for day in range(1, 10):
    open(os.path.join(bdir, f'board-202601{day:02d}.db'), 'w').close()
open(os.path.join(bdir, 'notes.txt'), 'w').close()   # 백업 이름이 아닌 파일은 건드리지 않음
path = storage.backup_db(bdir, keep=7)
assert path and os.path.exists(path) and storage.backup_db(bdir, keep=7) is None
names = sorted(os.listdir(bdir))
print('backups', names)
assert len([n for n in names if n.startswith('board-')]) == 7 and 'notes.txt' in names and os.path.basename(path) in names
assert not any(n.endswith('.part') for n in names)
copy = sqlite3.connect(path)
assert copy.execute('select count(*) from posts').fetchone()[0] == total_posts
copy.close()

# 2) 오래된 글 정리: 기준일 지난 글만, 키워드마다 최근 keep개는 남김, 읽음 기록도 정리
assert storage.prune_old_posts(0, 5) == 0
db.execute("update posts set created_at = '2000-01-01 00:00:00'")
recent = {r[0] for r in db.execute('''select post_id from (select post_id, row_number() over
          (partition by board, keyword order by rowid desc) rn from keyword_posts) where rn <= 5''')}
fresh_id = db.execute('select id from posts where id not in (%s) limit 1' % ','.join("'%s'" % i for i in recent)).fetchone()[0]
db.execute("update posts set created_at = datetime('now', 'localtime') where id = ?", (fresh_id,))
old_read = db.execute('select id from posts where id not in (%s) and id != ? limit 1' % ','.join("'%s'" % i for i in recent), (fresh_id,)).fetchone()[0]
db.execute("insert or replace into read_posts(post_id, read_at) values(?, '2000-01-02 00:00:00')", (old_read,))
db.commit()
deleted = storage.prune_old_posts(180, 5)
left = {r[0] for r in db.execute('select id from posts')}
print('pruned', deleted, 'left', len(left), 'of', total_posts)
assert deleted == total_posts - len(recent) - 1 and left == recent | {fresh_id}
assert db.execute('select count(*) from keyword_posts where post_id not in (select id from posts)').fetchone()[0] == 0
assert db.execute('select count(*) from read_posts where post_id = ?', (old_read,)).fetchone()[0] == 0

# 3) 최근 경고·오류와 상태 API
config.log_msg('[테스트] 경고 메시지\n두 번째 줄은 버림', 'WARN')
config.log_msg('[테스트] 정보는 안 들어감', 'INFO')
runtime_status.update(last_cycle={'finished_at': runtime_status.now(), 'seconds': 12, 'new': 1, 'updated': 2, 'deleted': 0, 'errors': 0})
srv = web_server.ThreadedHTTPServer(('127.0.0.1', 18101), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
status = json.load(urllib.request.urlopen('http://127.0.0.1:18101/api/status', timeout=10))
print('status keys', sorted(status))
assert status['recent_problems'][0]['message'] == '[테스트] 경고 메시지'
assert not any('정보는' in p['message'] for p in status['recent_problems'])
assert status['last_cycle']['seconds'] == 12 and status['started_at'] and status['now']

# 4) 메인 루프: 크롬 정기 재시작, 주기 상태 기록, 하루 한 번 유지 관리
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
created, quits = [], []
class FakeDriver:
    def execute_script(self, s): return 1
    def quit(self): quits.append(1)
def fake_create():
    created.append(1)
    m.runtime_status.update(chrome_started_at=m.runtime_status.now())
    return FakeDriver()
m.create_driver = fake_create
m.run_api_server = lambda: None
m.CHROME_RESTART_CYCLES = 2
m.get_list_page_posts = lambda driver, board, keyword, page=1: []
maint = []
real_maint = m.run_daily_maintenance
m.run_daily_maintenance = lambda: (maint.append(1), real_maint())
cycles = {'n': 0}
def fake_sleep(s):
    cycles['n'] += 1
    if cycles['n'] >= 5:
        raise KeyboardInterrupt
m.time.sleep = fake_sleep
with contextlib.redirect_stdout(io.StringIO()):
    m.main()
snap = runtime_status.snapshot()
print('drivers created', len(created), 'restarts', snap['chrome_restarts'], 'cycles', snap['cycles'], 'maintenance', len(maint))
# 5주기: 시작 1 + 2주기마다 재시작 2 (3번째·5번째 주기 시작 전)
assert len(created) == 3 and snap['chrome_restarts'] == 2 and snap['cycles'] == 5 and len(maint) == 1
assert snap['last_backup'] is None or snap['last_backup']['file'].startswith('board-')
assert snap['last_prune'] is not None and snap['next_check_at']
print('MAINTENANCE OK')
