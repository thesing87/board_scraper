import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, APP_DIR
import tempfile, subprocess, json, time, socket, sqlite3, importlib.util, io, contextlib, urllib.request
# 수집기와 웹서버를 따로 띄우는 구성 (docker-compose.yml의 fmkorea-scraper / fmkorea-web)
OUT = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=OUT, ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', LOG_LEVEL='WARN', RUN_WEB_SERVER='0')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
ENV = dict(os.environ, PYTHONIOENCODING='utf-8')

def run(code, extra_env=None):
    """새 파이썬 프로세스로 app 코드를 실행 (따로 도는 웹서버 프로세스 흉내)"""
    return subprocess.run([sys.executable, '-B', '-c', code], cwd=APP_DIR, env=dict(ENV, **(extra_env or {})),
                          capture_output=True, text=True, encoding='utf-8')

# --- 1) 두 프로세스가 동시에 DB를 처음 열어도(스키마 확인·추가, 1회 이전) 둘 다 성공
old_dir = tempfile.mkdtemp()
procs = [subprocess.Popen([sys.executable, '-B', '-c', 'import storage; storage.init_db(); print("ok")'], cwd=APP_DIR,
                          env=dict(ENV, OUTPUT_DIR=old_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
         for _ in range(4)]
results = [p.communicate() for p in procs]
assert all(p.returncode == 0 for p in procs), results
with sqlite3.connect(os.path.join(old_dir, 'board.db')) as db:
    cols = [r[1] for r in db.execute('PRAGMA table_info(posts)')]
    seeded = db.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
assert len(cols) == len(set(cols)) and seeded > 0, (cols, seeded)
print('CONCURRENT INIT OK')

# --- 2) 수집기 상태가 파일로 따로 도는 웹서버에 전달됨
import runtime_status, config
assert not os.path.exists(runtime_status.STATUS_FILE)
# 수집기 상태 파일이 없으면 웹서버는 '수집기 상태 없음'(started_at 없음)으로 보여줌
r = run('import json, runtime_status; print(json.dumps(runtime_status.snapshot()))')
assert r.returncode == 0, r.stderr
assert json.loads(r.stdout.strip().splitlines()[-1])['started_at'] is None

runtime_status.start_writer()
runtime_status.increment('cycles')
config.log_msg('[오류] 수집기 쪽 경고', 'WARN')
runtime_status.update(last_cycle={'finished_at': runtime_status.now(), 'seconds': 12, 'new': 3, 'updated': 1, 'deleted': 0, 'errors': 0})
r = run('import json, config, runtime_status\n'
        'config.log_msg("[API] 웹서버 쪽 오류", "ERROR")\n'
        'print(json.dumps(runtime_status.snapshot(), ensure_ascii=False))')
assert r.returncode == 0, r.stderr
snap = json.loads(r.stdout.strip().splitlines()[-1])  # 앞줄은 log_msg 화면 출력
assert snap['cycles'] == 1 and snap['last_cycle']['new'] == 3 and snap['started_at'], snap
# 최근 경고·오류는 수집기와 웹서버 것을 합쳐 최신이 먼저
messages = [p['message'] for p in snap['recent_problems']]
assert messages[:2] == ['[API] 웹서버 쪽 오류', '[오류] 수집기 쪽 경고'], messages
print('STATUS FILE OK')

# --- 3) 웹서버만 따로 실행 (python app/web_server.py): 상태·글 목록 응답, 로그는 web-debug.log
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
# run_api_server는 8081 고정이므로 시험에서는 포트만 바꾸고, 실제와 같이 web_server.py를 __main__으로 실행 (init_db → 서버)
server = subprocess.Popen([sys.executable, '-B', '-c',
                           'import socketserver, runpy\n'
                           'orig = socketserver.TCPServer.__init__\n'
                           f'socketserver.TCPServer.__init__ = lambda self, addr, *a, **k: orig(self, ("127.0.0.1", {port}), *a, **k)\n'
                           'runpy.run_path("web_server.py", run_name="__main__")'],
                          cwd=APP_DIR, env=dict(ENV, DEBUG_LOG_NAME='web-debug.log'),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    for _ in range(50):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=2) as res:
                status = json.load(res)
            break
        except OSError:
            time.sleep(0.2)
    else:
        raise SystemExit('web server did not start: ' + (server.stderr.read() if server.poll() is not None else 'timeout'))
    assert status['cycles'] == 1, status
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/state', timeout=5) as res:
        state = json.load(res)
    assert 'groups' in state and 'all' in state
finally:
    server.terminate()
    server.wait(5)
assert os.path.exists(os.path.join(OUT, 'logs', 'web-debug.log'))
print('STANDALONE WEB OK')

# --- 4) RUN_WEB_SERVER=0이면 수집기는 웹서버를 띄우지 않고 상태 파일을 씀
spec = importlib.util.spec_from_file_location('m', os.path.join(APP_DIR, 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
started = []
m.run_api_server = lambda: started.append(1)
class FakeDriver:
    def execute_script(self, s): return 1
    def quit(self): pass
m.create_driver = lambda: FakeDriver()
def stop(seconds):
    raise KeyboardInterrupt  # 첫 주기를 마치고 다음 주기를 기다릴 때 끝냄
real_sleep = time.sleep
m.time.sleep = stop  # time 모듈 자체를 바꾸므로 끝나면 되돌림
try:
    with contextlib.redirect_stdout(io.StringIO()):
        m.main()
finally:
    m.time.sleep = real_sleep
assert started == [], started
saved = json.load(open(runtime_status.STATUS_FILE, encoding='utf-8'))
assert saved['cycles'] >= 2, saved  # 위 1회 + 이번 주기
print('SCRAPER WITHOUT WEB OK')
print('SPLIT WEB OK')
