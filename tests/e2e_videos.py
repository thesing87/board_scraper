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
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
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
# 모두 재생 화면으로 열림 (AVI 등은 재생 화면에서 변환 안내). 변환 필요 여부: AVI는 확실, MP4는 열어 봐야 앎
assert [vs[n]['playable'] for n in vs] == [True] * 5
assert vs['04화']['convert'] is True and vs['01화']['convert'] in (None, False) and not vs['04화']['converted']
assert vs['01화']['subtitle'] and vs['02화']['subtitle'] and not vs['03화']['subtitle']
assert [d['name'] for d in req('/api/videos/list?p=')[1]['dirs']] == ['드라마', '짧은']
# 폴더 칸에 모아 보여 줄 영상: 재생되는 형식 먼저 4개까지, 폴더에 영상이 없으면 하위 폴더에서
code, body, _ = req('/api/videos/samples?p=')
assert body['samples'] == {'드라마': ['드라마/01화.mp4', '드라마/02화.mp4', '드라마/03화.mkv', '드라마/05화.mp4'],
                           '짧은': ['짧은/하위/a.mp4']}, body
assert req(f'/api/videos/samples?p={q("드라마")}')[1]['samples'] == {'드라마/1부': []}
assert req(f'/api/videos/samples?p={q("없음")}')[0] == 404
# 검색: 동영상 폴더 전체에서 이름·폴더에 낱말이 모두 들어간 영상, 이름에 들어간 것 먼저
code, body, _ = req(f'/api/videos/search?q={q("드라마 05")}')
assert code == 200 and [v['path'] for v in body['videos']] == ['드라마/05화.mp4'] and body['total'] == 1, body
body = req(f'/api/videos/search?q={q("화")}')[1]
assert body['total'] == 5 and all(v['folder'] == '드라마' and 'convert' in v for v in body['videos']), body
assert [v['path'] for v in req(f'/api/videos/search?q={q("하위")}')[1]['videos']] == ['짧은/하위/a.mp4']   # 폴더 이름으로도
assert req('/api/videos/search?q=')[1]['total'] == 0
# 최근 추가: 폴더 전체 영상을 들어온 시각이 최근인 것부터
body = req('/api/videos/latest')[1]
assert sorted(v['path'] for v in body['videos']) == sorted(['드라마/01화.mp4', '드라마/02화.mp4', '드라마/03화.mkv', '드라마/04화.avi',
                                                              '드라마/05화.mp4', '짧은/하위/a.mp4']), body
assert all(v['added'] for v in body['videos'])
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
    # 관리자 기기여도 숨은 메뉴: 대시보드 제목을 5번 눌러야 보임
    assert 'videos' not in js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)")
    for _ in range(5):
        js("document.querySelector('.site-top-brand h1').click()")
    assert 'videos' in js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav)")

    # 최상위 목록: 폴더 칸에 안의 영상 썸네일을 작게 모아 보여 줌 (4장은 2×2, 1장은 그대로)
    d.get(BASE + '/videos/'); time.sleep(2)
    mosaics = js("return [...document.querySelectorAll('#folders .tile')].map(t => [t.querySelector('.tile-name').textContent, t.querySelector('.mosaic').className, t.querySelectorAll('.mosaic img').length, t.querySelector('.folder-label').textContent])")
    # (이 시험 환경에는 ffmpeg가 없어 썸네일 그림은 비지만, 모음 칸 수와 표시는 그대로)
    assert mosaics[0] == ['드라마', 'mosaic is-4', 4, '폴더'] and mosaics[1][:2] == ['짧은', 'mosaic'] and mosaics[1][3] == '영상 1개', mosaics
    # 최근 추가 줄 (맨 위 폴더에서만)
    assert not js("return document.getElementById('latest').hidden") and js("return document.querySelectorAll('#latest-list .tile').length") == 6
    assert js("return document.querySelector('#latest-list .tile-sub').textContent").endswith('분 전'), js("return document.querySelector('#latest-list .tile-sub').textContent")
    # 검색: 쓰는 대로 결과, 지우면 목록으로
    js("const i = document.getElementById('vsearch-input'); i.value = '05'; i.dispatchEvent(new Event('input'))"); time.sleep(1.2)
    assert not js("return document.getElementById('search-results').hidden") and js("return document.getElementById('library-view').hidden")
    assert js("return [...document.querySelectorAll('#search-list .tile-name')].map(e => e.textContent)") == ['05화']
    assert '영상 1개' in js("return document.getElementById('search-count').textContent")
    js("document.getElementById('vsearch-clear').click()"); time.sleep(.5)
    assert js("return document.getElementById('search-results').hidden") and not js("return document.getElementById('library-view').hidden")
    js("const i = document.getElementById('vsearch-input'); i.value = '없는이름'; i.dispatchEvent(new Event('input'))"); time.sleep(1.2)
    assert '없습니다' in js("return document.getElementById('search-count').textContent")
    js("document.getElementById('vsearch-clear').click()"); time.sleep(.3)
    d.get(BASE + '/videos/#d=' + q('드라마')); time.sleep(1.5)
    assert js("return document.getElementById('latest').hidden")      # 하위 폴더에서는 없음
    d.get(BASE + '/videos/#d=' + q('드라마')); time.sleep(1.5)
    tiles = js("return [...document.querySelectorAll('#videos .tile')].map(t => [t.querySelector('.tile-name').textContent, t.classList.contains('is-unplayable'), t.getAttribute('href')])")
    assert [t[0] for t in tiles] == ['01화', '02화', '03화', '04화', '05화'] and tiles[3][1] and tiles[3][2].startswith('#v='), tiles
    assert '변환 필요' in js("return document.querySelectorAll('#videos .tile')[3].textContent")
    # 폴더에 변환이 필요한 영상이 있으면 '모두 자동 변환' 막대
    assert not js("return document.getElementById('conv-bar').hidden") and '영상 1개' in js("return document.getElementById('conv-bar-text').textContent")
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
    assert st[1].endswith('Mbps') and st[2] == '0번' and '최근' in st[3] and st[4] == '320×240', st
    # 건너뛰기 직후 버린 프레임은 세지 않음 (키프레임이 드문 영상에서 기기 문제로 잘못 판정하지 않게)
    js("document.getElementById('video').currentTime = 25"); time.sleep(1.2)
    assert js("return document.getElementById('st-dropped').textContent").startswith('최근 0초'), js("return document.getElementById('st-dropped').textContent")
    assert js("return document.getElementById('stats-verdict').textContent")
    assert js("return localStorage.getItem('videos_stats_open')") == '1'
    # → / ←: 재생바에 초점이 있어도 영상 길이와 상관없이 10초씩
    js("const v = document.getElementById('video'); v.pause(); v.currentTime = 5"); time.sleep(1)
    d.find_element(By.ID, 'video').send_keys(Keys.ARROW_RIGHT); time.sleep(.5)
    assert abs(js("return document.getElementById('video').currentTime") - 15) < 0.6, js("return document.getElementById('video').currentTime")
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowLeft', bubbles: true}))"); time.sleep(.5)
    assert abs(js("return document.getElementById('video').currentTime") - 5) < 0.6, js("return document.getElementById('video').currentTime")
    assert js("return document.getElementById('seek-osd').textContent") == '−10초'
    # 건너뛰기 시간: 위쪽 줄 버튼으로 30초를 고르면 → 가 30초씩, 이 기기(localStorage)에 저장
    assert js("return document.getElementById('seek-text').textContent") == '10초'
    d.find_element(By.ID, 'seek-btn').click(); time.sleep(.3)
    assert not js("return document.getElementById('seek-menu').hidden")
    assert js("return [...document.querySelectorAll('#seek-options button')].map(b => b.textContent)") == ['5초', '10초', '15초', '30초', '60초']
    d.find_element(By.CSS_SELECTOR, '#seek-options button[data-sec="30"]').click(); time.sleep(.3)
    assert js("return document.getElementById('seek-menu').hidden")
    assert js("return document.getElementById('seek-text').textContent") == '30초'
    assert js("return localStorage.getItem('videos_seek_step')") == '30'
    d.find_element(By.ID, 'video').send_keys(Keys.ARROW_RIGHT); time.sleep(.5)
    assert abs(js("return document.getElementById('video').currentTime") - 35) < 0.6, js("return document.getElementById('video').currentTime")
    assert js("return document.getElementById('seek-osd').textContent") == '+30초'
    # 목록이 열린 채 Esc는 목록만 닫음 (재생 화면은 그대로)
    d.find_element(By.ID, 'seek-btn').click(); time.sleep(.3)
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))"); time.sleep(.3)
    assert js("return document.getElementById('seek-menu').hidden") and not js("return document.getElementById('player').hidden")
    js("localStorage.removeItem('videos_seek_step')")
    ActionChains(d).move_to_element(d.find_element(By.ID, 'video')).perform()  # 위쪽 줄 위에 마우스가 있으면 숨지 않으므로 비킴
    js("document.getElementById('video').play()"); time.sleep(.5)
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
    # 영상 위 양옆 이전·다음 버튼: 이름이 아래에, 첫 영상에서는 이전이 꺼짐, Shift+→로 다음 영상
    assert js("return document.getElementById('prev-name').textContent") == '이전 · 01화'
    assert '01화' in js("return document.getElementById('prev-btn').title")
    js("document.getElementById('prev-btn').click()"); time.sleep(2.5)
    assert js("return document.getElementById('player-title').textContent") == '01화'
    assert js("return [document.getElementById('prev-btn').disabled, document.getElementById('next-nav-btn').disabled]") == [True, False]
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', shiftKey: true}))"); time.sleep(2.5)
    assert js("return document.getElementById('player-title').textContent") == '02화'
    # 재생 중 3초 넘게 가만히 있으면 위쪽 줄·이전·다음이 숨고, 일시정지하면 다시 보임
    js("document.getElementById('video').play()"); time.sleep(4)
    assert not js("return document.getElementById('player').classList.contains('ui-on')"), js("return document.getElementById('video').paused")
    assert js("return getComputedStyle(document.querySelector('.p-side.is-next')).opacity") == '0'
    js("document.getElementById('video').pause()"); time.sleep(4)
    assert js("return document.getElementById('player').classList.contains('ui-on')")
    # 전체화면은 재생 화면 전체(이전·다음 버튼 포함), 다음 영상으로 넘어가도 전체화면 그대로
    d.find_element(By.ID, 'fs-btn').click(); time.sleep(1)
    assert js("return document.fullscreenElement && document.fullscreenElement.id") == 'player'
    assert js("return document.getElementById('player').classList.contains('is-fs')")
    nxt = js("return document.getElementById('next-name').textContent").split(' · ')[1]
    d.find_element(By.ID, 'next-nav-btn').click(); time.sleep(2.5)
    assert js("return document.getElementById('player-title').textContent") == nxt
    assert js("return document.fullscreenElement && document.fullscreenElement.id") == 'player'
    js("document.getElementById('video').pause()"); time.sleep(.5)
    d.find_element(By.ID, 'fs-btn').click(); time.sleep(1)
    assert js("return document.fullscreenElement") is None and not js("return document.getElementById('player').classList.contains('is-fs')")
    # 소리 크기·음소거는 모든 영상에 같고 저장됨 (다음 영상·새로 열어도 그대로)
    js("const v = document.getElementById('video'); v.volume = 0.35; v.muted = true"); time.sleep(.5)
    d.get(BASE + '/videos/#v=' + q('드라마/01화.mp4')); time.sleep(2.5)
    assert js("const v = document.getElementById('video'); return [v.volume, v.muted]") == [0.35, True], js("return localStorage.getItem('videos_volume')")
    js("document.getElementById('video').muted = false"); time.sleep(.3)
    d.get(BASE + '/videos/#v=' + q('드라마/02화.mp4')); time.sleep(2.5)
    assert js("const v = document.getElementById('video'); return [v.volume, v.muted]") == [0.35, False]
    assert js("return document.getElementById('video').error") is None
    # MKV (크롬에서 재생)
    d.get(BASE + '/videos/#v=' + q('드라마/03화.mkv')); time.sleep(3)
    mkv_error = js("return document.getElementById('video').error && document.getElementById('video').error.code")
    print('MKV playable in this Chrome:', mkv_error is None, js("return document.getElementById('video').duration"))
    # 화면 형식을 못 푸는 MP4: 안내와 내려받기
    d.get(BASE + '/videos/#v=' + q('드라마/05화.mp4')); time.sleep(3)
    assert not js("return document.getElementById('player-msg').hidden"), js("return [document.getElementById('video').videoWidth, document.getElementById('video').error]")
    assert '내려받기' in js("return document.getElementById('player-msg').textContent")
    # AVI(DivX): 재생 화면에서 변환 안내(밤에 변환 버튼 없음) → 지금 변환 → 취소
    d.get(BASE + '/videos/#v=' + q('드라마/04화.avi')); time.sleep(2.5)
    msg = js("return document.getElementById('player-msg').textContent")
    assert '변환해야 볼 수 있습니다' in msg and '지금 변환' in msg and '내려받기' in msg and '밤' not in msg, msg
    assert not js("return document.querySelector('[data-conv=night]')")
    js("document.querySelector('[data-conv=start]').click()"); time.sleep(1.5)
    assert '변환 대기 중' in js("return document.getElementById('player-msg').textContent")
    job = req(f'/api/videos/status?p={q("드라마/04화.avi")}')[1]['job']
    assert job['state'] == 'queued' and job['auto'] is False, job
    js("document.querySelector('[data-conv=cancel]').click()"); time.sleep(1.5)
    assert req(f'/api/videos/status?p={q("드라마/04화.avi")}')[1]['job'] is None
    assert '지금 변환' in js("return document.getElementById('player-msg').textContent")
    # 목록으로 (닫기)
    js("document.getElementById('player-close').click()"); time.sleep(1.2)
    assert js("return document.getElementById('player').hidden") and js("return location.hash").startswith('#d=')
    # ---- 랜덤 재생: 폴더(하위 폴더 포함, 맨 위면 전체)에서 바로 재생되는 영상만 (변환이 필요한 AVI는 뺌)
    paths = [v['path'] for v in req('/api/videos/random?p=')[1]['videos']]
    assert '드라마/01화.mp4' in paths and '짧은/하위/a.mp4' in paths and '드라마/04화.avi' not in paths, paths
    assert [v['path'] for v in req(f'/api/videos/random?p={q("짧은")}')[1]['videos']] == ['짧은/하위/a.mp4']
    assert req(f'/api/videos/random?p={q("없는 폴더")}')[0] == 404
    total = len(req(f'/api/videos/random?p={q("드라마")}')[1]['videos'])
    assert total >= 3
    chip = lambda: js("return document.getElementById('random-chip').hidden ? null : document.getElementById('random-chip-text').textContent")
    title = lambda: js("return document.getElementById('player-title').textContent")
    assert js("return document.getElementById('random-text').textContent") == '이 폴더 랜덤 재생' and chip() is None
    d.find_element(By.ID, 'random-btn').click(); time.sleep(2.5)
    assert not js("return document.getElementById('player').hidden")
    assert chip() == f'랜덤 1 / {total}', chip()
    first = title()
    assert js("return document.getElementById('next-name').textContent").startswith('랜덤 다음 · ')
    assert js("return document.getElementById('random-from').textContent") == '폴더: 드라마'
    js("document.getElementById('next-nav-btn').click()"); time.sleep(2.5)
    assert chip() == f'랜덤 2 / {total}' and title() != first, (chip(), title())
    assert js("return document.getElementById('prev-name').textContent") == f'이전 · {first}'
    js("document.getElementById('prev-btn').click()"); time.sleep(2.5)
    assert title() == first and chip() == f'랜덤 1 / {total}'
    # 칩을 누르면 랜덤을 끄고 같은 폴더 순서로, 다시 누르면 켬
    js("document.getElementById('random-chip').click()"); time.sleep(.3)
    folder_next = [v['name'] for v in req(f'/api/videos/list?p={q("드라마")}')[1]['videos']]
    folder_next = folder_next[folder_next.index(first) + 1:]
    nxt = js("return document.getElementById('next-name').textContent")
    assert chip() == '랜덤 끔' and (nxt.startswith('다음 · ') if folder_next else nxt == ''), (chip(), nxt, first)
    assert js("return document.getElementById('random-from').hidden")
    js("document.getElementById('random-chip').click()"); time.sleep(.3)
    assert chip() == f'랜덤 1 / {total}'
    # 목록으로 돌아가면 랜덤 끝
    js("document.getElementById('player-close').click()"); time.sleep(1.5)
    assert js("return document.getElementById('player').hidden") and chip() is None
    # 맨 위 폴더에서는 '전체 랜덤 재생'
    d.get(BASE + '/videos/#'); time.sleep(1.5)
    assert js("return document.getElementById('random-text').textContent") == '전체 랜덤 재생'
    # 휴대폰
    d.set_window_size(390, 844); time.sleep(.5)
    assert js("return document.documentElement.scrollWidth <= innerWidth")
    print('PAGE OK')
finally:
    d.quit()
    srv.shutdown()
