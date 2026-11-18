"""동영상(/videos/, 관리자 전용): 로그인 쿠키가 있어야 목록·영상이 열리고, 폴더 밖 경로는 거부, Range로 원하는 위치부터,
재생 못 하는 형식은 내려받기만, 자막 변환, 이어 보기 저장, 화면에서 재생·이어 보기·다음 영상, 메뉴는 관리자 기기에만

시험용 영상(H.264 MP4·MKV, MPEG-4 AVI)은 tests/fixtures/videos/에 두거나 VIDEO_FIXTURES 환경변수로 폴더를 지정
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, TESTS_DIR
import tempfile, threading, time, socket, json, shutil, urllib.request, urllib.error, urllib.parse

FIX = os.environ.get('VIDEO_FIXTURES') or os.path.join(TESTS_DIR, 'fixtures', 'videos')
VIDEOS = tempfile.mkdtemp()
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='', VIDEOS_DIR=VIDEOS)
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server, videos
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

os.makedirs(os.path.join(VIDEOS, '드라마', '1부'))
shutil.copy(os.path.join(FIX, 's.mp4'), os.path.join(VIDEOS, '드라마', '01화.mp4'))
shutil.copy(os.path.join(FIX, 's.mp4'), os.path.join(VIDEOS, '드라마', '02화.mp4'))
shutil.copy(os.path.join(FIX, 's.mkv'), os.path.join(VIDEOS, '드라마', '03화.mkv'))
shutil.copy(os.path.join(FIX, 's.avi'), os.path.join(VIDEOS, '드라마', '04화.avi'))
# MP4지만 화면이 MPEG-4 Part 2(DivX 계열)라 브라우저가 화면을 못 푸는 영상
shutil.copy(os.path.join(FIX, 'mpeg4.mp4'), os.path.join(VIDEOS, '드라마', '05화.mp4'))
os.makedirs(os.path.join(VIDEOS, '짧은', '하위'))
shutil.copy(os.path.join(FIX, 's.mp4'), os.path.join(VIDEOS, '짧은', '하위', 'a.mp4'))
open(os.path.join(VIDEOS, '드라마', 'note.txt'), 'w').write('x')
open(os.path.join(VIDEOS, '드라마', '01화.srt'), 'w', encoding='utf-8').write('1\n00:00:01,000 --> 00:00:03,500\n안녕하세요\n\n2\n00:00:04,000 --> 00:00:05,000\n두 번째\n')
open(os.path.join(VIDEOS, '드라마', '02화.smi'), 'w', encoding='cp949').write(
    '<SAMI><BODY><SYNC Start=1000><P Class=KRCC>첫 줄<br>둘째 줄<SYNC Start=3000><P Class=KRCC>&nbsp;<SYNC Start=4000><P Class=KRCC>끝</BODY></SAMI>')
os.makedirs(os.path.join(VIDEOS, '@eaDir'))
open(os.path.join(os.path.dirname(VIDEOS), 'secret.mp4'), 'wb').write(b'x')

storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()
cookie = ''
q = urllib.parse.quote

def req(path, body=None, raw=False, headers=None):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                               method='POST' if body is not None else 'GET',
                               headers={'Content-Type': 'application/json', 'Cookie': cookie, **(headers or {})})
    try:
        with urllib.request.urlopen(r) as res:
            data = res.read()
            return res.status, (data if raw else json.loads(data)), res.headers
    except urllib.error.HTTPError as e:
        data = e.read()
        return e.code, (data if raw or not data else json.loads(data)), e.headers

# ---- 로그인 없으면 거부
assert req('/api/videos/list?p=')[0] == 401
assert req(f'/api/videos/file?p={q("드라마/01화.mp4")}', raw=True)[0] == 401
assert req('/api/videos/session', {'password': 'wrong'})[0] == 401
web_server._clear_auth_failures('127.0.0.1')
code, body, headers = req('/api/videos/session', {'password': 'Secr3t!'})
assert code == 200 and 'HttpOnly' in headers['Set-Cookie'] and 'Path=/api/videos/' in headers['Set-Cookie']
cookie = headers['Set-Cookie'].split(';')[0]

# ---- 목록: 폴더·영상(이름순), 재생 가능 여부, 자막 여부, 숨김 폴더·영상 아닌 파일 제외
code, body, _ = req(f'/api/videos/list?p={q("드라마")}')
assert [d['name'] for d in body['dirs']] == ['1부']
vs = {v['name']: v for v in body['videos']}
assert list(vs) == ['01화', '02화', '03화', '04화', '05화'], list(vs)
assert [vs[n]['playable'] for n in vs] == [True, True, True, False, True]
assert vs['01화']['subtitle'] and vs['02화']['subtitle'] and not vs['03화']['subtitle']
assert [d['name'] for d in req('/api/videos/list?p=')[1]['dirs']] == ['드라마', '짧은']
# 폴더 칸에 모아 보여 줄 영상: 재생되는 형식 먼저 4개까지, 폴더에 영상이 없으면 하위 폴더에서
code, body, _ = req('/api/videos/samples?p=')
assert body['samples'] == {'드라마': ['드라마/01화.mp4', '드라마/02화.mp4', '드라마/03화.mkv', '드라마/05화.mp4'],
                           '짧은': ['짧은/하위/a.mp4']}, body
assert req(f'/api/videos/samples?p={q("드라마")}')[1]['samples'] == {'드라마/1부': []}
assert req(f'/api/videos/samples?p={q("없음")}')[0] == 404
assert req(f'/api/videos/list?p={q("../")}')[0] == 404

# ---- 파일: 전체·Range·끝 부분·범위 밖, 내려받기, 폴더 밖 거부
size = os.path.getsize(os.path.join(VIDEOS, '드라마', '01화.mp4'))
full = open(os.path.join(VIDEOS, '드라마', '01화.mp4'), 'rb').read()
code, data, h = req(f'/api/videos/file?p={q("드라마/01화.mp4")}', raw=True)
assert code == 200 and data == full and h['Content-Type'] == 'video/mp4' and h['Accept-Ranges'] == 'bytes'
code, data, h = req(f'/api/videos/file?p={q("드라마/01화.mp4")}', raw=True, headers={'Range': 'bytes=100-199'})
assert code == 206 and data == full[100:200] and h['Content-Range'] == f'bytes 100-199/{size}'
code, data, h = req(f'/api/videos/file?p={q("드라마/01화.mp4")}', raw=True, headers={'Range': 'bytes=1000-'})
assert code == 206 and data == full[1000:]
code, data, h = req(f'/api/videos/file?p={q("드라마/01화.mp4")}', raw=True, headers={'Range': 'bytes=-50'})
assert code == 206 and data == full[-50:]
assert req(f'/api/videos/file?p={q("드라마/01화.mp4")}', raw=True, headers={'Range': f'bytes={size + 10}-'})[0] == 416
code, data, h = req(f'/api/videos/file?p={q("드라마/04화.avi")}&download=1', raw=True)
assert code == 200 and 'attachment' in h['Content-Disposition'] and q('04화.avi') in h['Content-Disposition']
for bad in ('../secret.mp4', '드라마/note.txt', '드라마', '@eaDir/x.mp4'):
    assert req(f'/api/videos/file?p={q(bad)}', raw=True)[0] == 404, bad

# ---- 자막: srt·smi → WebVTT
code, data, h = req(f'/api/videos/subs?p={q("드라마/01화.mp4")}', raw=True)
vtt = data.decode()
assert code == 200 and h['Content-Type'].startswith('text/vtt') and vtt.startswith('WEBVTT') and '00:00:01.000 --> 00:00:03.500' in vtt and '안녕하세요' in vtt
vtt = req(f'/api/videos/subs?p={q("드라마/02화.mp4")}', raw=True)[1].decode()
assert '00:00:01.000 --> 00:00:03.000\n첫 줄\n둘째 줄' in vtt and '00:00:04.000 --> 00:00:09.000\n끝' in vtt, vtt
assert req(f'/api/videos/subs?p={q("드라마/03화.mkv")}', raw=True)[0] == 404

# ---- 이어 보기 저장·검사
assert req('/api/videos/progress', {'path': '드라마/01화.mp4', 'position': 12.5, 'duration': 40})[0] == 200
for bad in ({'path': '드라마/01화.mp4', 'position': 99, 'duration': 40}, {'path': '../secret.mp4', 'position': 1, 'duration': 40},
            {'path': '드라마/01화.mp4', 'position': '1', 'duration': 40}):
    assert req('/api/videos/progress', bad)[0] in (400, 404), bad
assert req(f'/api/videos/list?p={q("드라마")}')[1]['videos'][0]['progress']['position'] == 12.5
assert [r['name'] for r in req('/api/videos/list?p=')[1]['recent']] == ['01화']
print('API OK')

# ---- 화면
o = Options()
for a in ['--headless=new', '--window-size=1280,900', '--autoplay-policy=no-user-gesture-required', '--mute-audio']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
try:
    # 관리자 기기가 아니면 메뉴에 없고, 페이지로 바로 오면 로그인 화면
    d.get(BASE + '/'); time.sleep(1)
    assert 'videos' not in js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)")
    d.get(BASE + '/videos/'); time.sleep(1.2)
    assert not js("return document.getElementById('login').hidden")
    assert not js("return !!document.querySelector('.site-share-btn')")    # 공유 버튼 없음
    js("document.getElementById('login-password').value='Secr3t!'; document.getElementById('login').requestSubmit()"); time.sleep(1.5)
    assert js("return document.getElementById('login').hidden") and js("return [...document.querySelectorAll('#folders .tile-name')].map(e => e.textContent)") == ['드라마', '짧은']
    d.get(BASE + '/'); time.sleep(1)
    assert 'videos' in js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)")

    # 최상위 목록: 폴더 칸에 안의 영상 썸네일을 작게 모아 보여 줌 (4장은 2×2, 1장은 그대로)
    d.get(BASE + '/videos/'); time.sleep(2)
    mosaics = js("return [...document.querySelectorAll('#folders .tile')].map(t => [t.querySelector('.tile-name').textContent, t.querySelector('.mosaic').className, t.querySelectorAll('.mosaic img').length, t.querySelector('.folder-label').textContent])")
    # (이 시험 환경에는 ffmpeg가 없어 썸네일 그림은 비지만, 모음 칸 수와 표시는 그대로)
    assert mosaics[0] == ['드라마', 'mosaic is-4', 4, '폴더'] and mosaics[1][:2] == ['짧은', 'mosaic'] and mosaics[1][3] == '영상 1개', mosaics
    d.get(BASE + '/videos/#d=' + q('드라마')); time.sleep(1.5)
    tiles = js("return [...document.querySelectorAll('#videos .tile')].map(t => [t.querySelector('.tile-name').textContent, t.classList.contains('is-unplayable'), t.getAttribute('href')])")
    assert [t[0] for t in tiles] == ['01화', '02화', '03화', '04화', '05화'] and tiles[3][1] and 'download=1' in tiles[3][2], tiles
    assert '0:12 / 0:40' in js("return document.querySelector('#videos .tile').textContent")
    # 재생: 이어 보기 위치에서 시작, 자막 트랙
    js("document.querySelector('#videos .tile').click()"); time.sleep(3)
    assert not js("return document.getElementById('player').hidden")
    assert js("return document.getElementById('video').currentTime") >= 12, js("return document.getElementById('video').currentTime")
    assert '0:12부터' in js("return document.getElementById('resume-text').textContent")
    assert js("return document.querySelector('#video track').src").endswith(urllib.parse.quote('드라마/01화.mp4', safe=''))
    assert js("return document.getElementById('video').error") is None
    # 재생 정보: 켜면 미리 받은 시간·속도·프레임 등, 다시 열어도 켜진 채
    js("document.getElementById('stats-btn').click()"); time.sleep(2.5)
    assert not js("return document.getElementById('stats').hidden")
    st = js("return ['st-buffer', 'st-bitrate', 'st-waits', 'st-dropped', 'st-size'].map(i => document.getElementById(i).textContent)")
    assert st[1].endswith('Mbps') and st[2] == '0번' and '/' in st[3] and st[4] == '320×240', st
    assert js("return document.getElementById('stats-verdict').textContent")
    assert js("return localStorage.getItem('videos_stats_open')") == '1'
    # 원하는 위치로 건너뛰기 (Range)
    js("document.getElementById('video').currentTime = 30"); time.sleep(1.5)
    assert js("return document.getElementById('video').currentTime") >= 30
    js("document.getElementById('video').pause()"); time.sleep(1)
    assert req(f'/api/videos/list?p={q("드라마")}')[1]['videos'][0]['progress']['position'] >= 30
    # 끝나면 다음 영상
    js("const v = document.getElementById('video'); v.currentTime = v.duration - 0.3; v.play()"); time.sleep(2.5)
    assert '02화' in js("return document.getElementById('next-btn').textContent")
    js("document.getElementById('next-btn').click()"); time.sleep(2.5)
    assert js("return document.getElementById('player-title').textContent") == '02화'
    assert js("return document.getElementById('video').error") is None
    # MKV (크롬에서 재생)
    d.get(BASE + '/videos/#v=' + q('드라마/03화.mkv')); time.sleep(3)
    mkv_error = js("return document.getElementById('video').error && document.getElementById('video').error.code")
    print('MKV playable in this Chrome:', mkv_error is None, js("return document.getElementById('video').duration"))
    # 화면 형식을 못 푸는 MP4: 안내와 내려받기
    d.get(BASE + '/videos/#v=' + q('드라마/05화.mp4')); time.sleep(3)
    assert not js("return document.getElementById('player-msg').hidden"), js("return [document.getElementById('video').videoWidth, document.getElementById('video').error]")
    assert '내려받기' in js("return document.getElementById('player-msg').textContent")
    # 목록으로 (닫기)
    js("document.getElementById('player-close').click()"); time.sleep(1.2)
    assert js("return document.getElementById('player').hidden") and js("return location.hash").startswith('#d=')
    # 휴대폰
    d.set_window_size(390, 844); time.sleep(.5)
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('PAGE OK')
finally:
    d.quit()
    srv.shutdown()
