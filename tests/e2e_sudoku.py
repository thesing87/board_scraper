import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
import tempfile, threading, time, socket, json
os.environ.update(OUTPUT_DIR=tempfile.mkdtemp(), LOG_LEVEL='CRITICAL', ADMIN_PASSWORD='Secr3t!', TELEGRAM_TOKEN='')
for name in [k for k in os.environ if k.startswith('KEYWORDS_')]:
    os.environ[name] = ''
import storage, web_server
from selenium.webdriver import Chrome, ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

# 스도쿠: 유일해 생성기, 입력·메모·실수·실행 취소·힌트·숫자 고정·키보드·일시정지·저장, 완성·게임 오버, 게임 목록·대시보드 카드
storage.init_db()
with socket.socket() as s:
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
BASE = f'http://127.0.0.1:{port}'
srv = web_server.ThreadedHTTPServer(('127.0.0.1', port), web_server.KeywordAPIServer)
threading.Thread(target=srv.serve_forever, daemon=True).start()

o = Options()
for a in ['--headless=new', '--window-size=1280,1000', '--autoplay-policy=no-user-gesture-required']:
    o.add_argument(a)
d = Chrome(options=o)
js = d.execute_script
def cell(i): return d.find_elements(By.CSS_SELECTOR, '.cell')[i]
def cls(i): return js(f"return document.querySelectorAll('.cell')[{i}].className")
def empty_cells(): return js("return game.puzzle.map((v, i) => v ? -1 : i).filter(i => i >= 0 && !(game.values[i] && game.values[i] === game.solution[i]))")
try:
    # ---- 생성기: 난이도마다 정답이 하나뿐이고, 남는 숫자가 난이도 순으로 줄어듦
    d.get(BASE + '/games/sudoku/'); time.sleep(1.5)
    report = js("""
        const out = {};
        for (const diff of ['easy', 'medium', 'hard', 'expert']) {
            const givens = [], ms = [];
            for (let k = 0; k < 4; k++) {
                const t = performance.now();
                const g = SudokuEngine.generate(diff);
                ms.push(Math.round(performance.now() - t));
                if (SudokuEngine.countSolutions(g.puzzle, 3) !== 1) return 'not unique ' + diff;
                if (g.puzzle.some((v, i) => v && v !== g.solution[i])) return 'mismatch';
                if (SudokuEngine.solve(g.puzzle).join('') !== g.solution.join('')) return 'solve';
                givens.push(g.puzzle.filter(Boolean).length);
            }
            out[diff] = { givens, ms };
        }
        return out;""")
    print('generator', json.dumps(report))
    assert isinstance(report, dict), report
    avg = {k: sum(v['givens']) / len(v['givens']) for k, v in report.items()}
    assert avg['easy'] > avg['medium'] > avg['hard'] > avg['expert'], avg
    assert max(max(v['ms']) for v in report.values()) < 3000

    # ---- 시작: 보통, 실수 0, 시간 흐름
    assert js("return game.diff") == 'medium' and js("return game.status") == 'playing'
    givens = js("return game.puzzle.filter(Boolean).length")
    assert js("return document.querySelectorAll('.cell.is-given').length") == givens
    time.sleep(2.2)
    assert js("return game.elapsed") > 1000

    # 칸 선택: 같은 행·열·박스 음영
    e = empty_cells()[0]
    cell(e).click()
    assert 'is-sel' in cls(e) and js("return document.querySelectorAll('.cell.is-peer').length") == 20

    # 메모: N으로 켜고 숫자를 누르면 작은 후보, 다시 누르면 꺼짐
    ActionChains(d).send_keys('n').perform()
    assert js("return ui.noteMode")
    sol = js(f"return game.solution[{e}]")
    wrong = sol % 9 + 1
    ActionChains(d).send_keys(str(sol)).send_keys(str(wrong)).perform()
    assert js(f"return game.notes[{e}]") == (1 << sol) | (1 << wrong)
    # 같은 행의 다른 빈칸에 같은 숫자 메모 → 정답을 넣으면 자동으로 지워짐
    row_peer = js(f"return SudokuEngine.UNITS.row[SudokuEngine.ROW({e})].find(i => i !== {e} && !game.puzzle[i] && !game.values[i])")
    if row_peer is not None:
        cell(row_peer).click()
        ActionChains(d).send_keys(str(sol)).perform()
        assert js(f"return game.notes[{row_peer}]") & (1 << sol)
    ActionChains(d).send_keys('n').perform()
    cell(e).click()

    # 오답: 실수 +1, 흔들림, 빨간 숫자
    ActionChains(d).send_keys(str(wrong)).perform(); time.sleep(.1)
    assert js("return game.mistakes") == 1 and 'is-wrong' in cls(e) and 'is-shake' in cls(e)
    assert js("return document.getElementById('mistakes').textContent") == '1/3'
    # 실행 취소(Ctrl+Z): 값과 메모가 돌아옴 (실수 횟수는 그대로)
    ActionChains(d).key_down(Keys.CONTROL).send_keys('z').key_up(Keys.CONTROL).perform()
    assert js(f"return game.values[{e}]") == 0 and js(f"return game.notes[{e}]") == (1 << sol) | (1 << wrong)
    assert js("return game.mistakes") == 1
    # 정답: 파란 잉크, 같은 행·열·박스의 그 숫자 메모가 지워짐
    ActionChains(d).send_keys(str(sol)).perform()
    assert 'is-user' in cls(e) and js(f"return game.values[{e}]") == sol
    if row_peer is not None:
        assert not (js(f"return game.notes[{row_peer}]") & (1 << sol))
    # 같은 숫자 강조
    same = js(f"return game.values.filter(v => v === {sol}).length")
    assert js("return document.querySelectorAll('.cell.is-same').length") == same - 1
    # 지우개(Backspace)
    ActionChains(d).send_keys(Keys.BACKSPACE).perform()
    assert js(f"return game.values[{e}]") == 0
    ActionChains(d).send_keys(str(sol)).perform()
    # 방향키 이동
    start = js("return ui.sel")
    ActionChains(d).send_keys(Keys.ARROW_RIGHT).perform()
    assert js("return ui.sel") == (start // 9) * 9 + (start % 9 + 1) % 9
    print('INPUT OK')

    # ---- 힌트: 고른 빈칸이면 그 칸, 아니면 논리로 바로 풀리는 칸
    target = empty_cells()[0]
    cell(target).click()
    d.find_element(By.ID, 'hint-btn').click()
    assert js(f"return game.values[{target}] === game.solution[{target}]") and js("return game.hints") == 1
    cell(js("return game.puzzle.findIndex(v => v)")).click()   # 처음부터 있던 숫자를 고르고 힌트
    d.find_element(By.ID, 'hint-btn').click()
    assert js("return game.hints") == 2

    # ---- 숫자 고정: 숫자를 길게 누르면 고정, 칸을 누를 때마다 그 숫자
    pad3 = d.find_element(By.CSS_SELECTOR, '.pad-btn[data-d="3"]')
    ActionChains(d).click_and_hold(pad3).pause(0.7).release().perform()
    assert js("return ui.lockDigit") == 3 and 'is-locked' in pad3.get_attribute('class')
    targets = js("return game.puzzle.map((v, i) => i).filter(i => !game.puzzle[i] && !game.values[i] && game.solution[i] === 3).slice(0, 2)")
    for t in targets:
        cell(t).click()
        assert js(f"return game.values[{t}]") == 3
    # 고정 버튼으로 풀기
    d.find_element(By.ID, 'lock-btn').click()
    assert js("return ui.lockDigit") == 0
    # 고정 버튼 → 숫자 고르기 → 칸 채우기
    d.find_element(By.ID, 'lock-btn').click()
    d.find_element(By.CSS_SELECTOR, '.pad-btn[data-d="5"]').click()
    assert js("return ui.lockDigit") == 5
    t5 = js("return game.puzzle.map((v, i) => i).find(i => !game.puzzle[i] && !game.values[i] && game.solution[i] === 5)")
    if t5 is not None:
        cell(t5).click()
        assert js(f"return game.values[{t5}]") == 5
    ActionChains(d).send_keys(Keys.ESCAPE).perform()
    assert js("return ui.lockDigit") == 0
    print('HINT LOCK OK')

    # ---- 줄 완성 물결: 한 줄만 남기고 채운 뒤 마지막 칸
    row = js("return SudokuEngine.UNITS.row.find(r => r.some(i => !game.puzzle[i] && game.values[i] !== game.solution[i]))")
    left = [i for i in row if not js(f"return game.values[{i}] === game.solution[{i}]")]
    for i in left[:-1]:
        js(f"enter(game.solution[{i}], {i})")
    js(f"enter(game.solution[{left[-1]}], {left[-1]})")
    assert js(f"return {json.dumps(row)}.every(i => document.querySelectorAll('.cell')[i].classList.contains('is-shimmer'))")

    # ---- 일시정지: 보드 가림, 시간 멈춤
    d.find_element(By.ID, 'pause-btn').click()
    before = js("return game.elapsed")
    assert js("return !document.getElementById('paused').hidden") and js("return getComputedStyle(document.querySelector('.cell .val')).visibility") == 'hidden'
    time.sleep(2.2)
    assert js("return game.elapsed") == before
    ActionChains(d).send_keys('5').perform()   # 일시정지 중 입력은 무시
    d.find_element(By.ID, 'resume-btn').click()

    # ---- 저장: 새로고침해도 이어서 (일시정지 화면부터)
    snap = js("return JSON.stringify([game.values, game.notes, game.mistakes, game.hints])")
    d.refresh(); time.sleep(1.5)
    assert js("return JSON.stringify([game.values, game.notes, game.mistakes, game.hints])") == snap
    assert js("return ui.paused") and js("return !document.getElementById('paused').hidden")
    d.find_element(By.ID, 'resume-btn').click()
    print('SHIMMER PAUSE SAVE OK')

    # ---- 게임 목록·대시보드 카드: 진행 중 표시
    d.get(BASE + '/games/'); time.sleep(1)
    assert '이어서 하기 · 보통' in js("return document.getElementById('sudoku-status').textContent")
    assert js("return document.getElementById('sudoku-play').textContent") == '이어서'
    d.get(BASE + '/'); time.sleep(1.5)
    body = js("return document.getElementById('games-body').textContent")
    assert '스도쿠' in body and '이어서' in body and '실수 1' in body, body
    assert js("return document.querySelector('#card-games .game-row').getAttribute('href')") == '/games/sudoku/'
    assert js("return [...document.querySelectorAll('.site-nav [data-nav]')].map(a => a.dataset.nav).includes('games')")

    # ---- 완성: 컨페티 + 결과 모달 (시간·난이도·실수), 기록 저장
    d.get(BASE + '/games/sudoku/'); time.sleep(1.2)
    d.find_element(By.ID, 'resume-btn').click()
    js("game.puzzle.forEach((v, i) => { if (!v && game.values[i] !== game.solution[i]) enter(game.solution[i], i); })")
    time.sleep(1.2)
    assert js("return game.status") == 'won'
    assert js("return !document.getElementById('confetti').hidden")
    modal = js("return document.getElementById('modal-card').textContent")
    assert '퍼즐을 풀었어요' in modal and '보통' in modal and '1회' in modal and '최고 기록' in modal, modal
    assert js("return JSON.parse(localStorage.getItem('sudoku_stats_v1')).medium.won") == 1
    # 결과에서 쉬움 새 게임
    js("document.querySelector('[data-new=easy]').click()"); time.sleep(.5)
    assert js("return game.diff") == 'easy' and js("return game.status") == 'playing' and js("return document.getElementById('modal').hidden")
    print('WIN OK')

    # ---- 실수 3번: 게임 오버, 같은 퍼즐 다시
    puzzle = js("return game.puzzle.join('')")
    for k in range(3):
        i = empty_cells()[k]
        js(f"enter(game.solution[{i}] % 9 + 1, {i})")
    assert js("return game.status") == 'lost' and '게임 오버' in js("return document.getElementById('modal-card').textContent")
    js("document.querySelector('[data-restart]').click()"); time.sleep(.3)
    assert js("return game.status") == 'playing' and js("return game.mistakes") == 0 and js("return game.puzzle.join('')") == puzzle
    # 진행 중 난이도 바꾸기는 확인을 거침
    i = empty_cells()[0]
    js(f"enter(game.solution[{i}], {i})")
    d.find_element(By.CSS_SELECTOR, '.diff-btn[data-diff="hard"]').click()
    d.switch_to.alert.dismiss()
    assert js("return game.diff") == 'easy'
    d.find_element(By.CSS_SELECTOR, '.diff-btn[data-diff="hard"]').click()
    d.switch_to.alert.accept(); time.sleep(.5)
    assert js("return game.diff") == 'hard'
    print('LOSE DIFF OK')

    # ---- 소리 끄기 유지
    d.find_element(By.ID, 'mute-btn').click()
    d.refresh(); time.sleep(1.2)
    assert js("return ui.muted") and js("return document.getElementById('mute-btn').getAttribute('aria-pressed')") == 'true'

    # ---- 화면 크기: 보드가 잘리지 않고 가운데 (넓은 화면·휴대폰·작은 휴대폰)
    for w, h in [(1280, 800), (390, 844), (360, 640)]:
        d.set_window_size(w, h); time.sleep(.6)
        d.get(BASE + '/games/sudoku/'); time.sleep(1.2)
        r = js("const r = document.getElementById('board').getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom, innerWidth, innerHeight]")
        assert r[0] >= 0 and r[1] <= r[4] and r[3] <= r[5] + 1, (w, h, r)
        assert abs((r[0] + r[1]) / 2 - js("return document.querySelector('.paper').parentElement.getBoundingClientRect().left + document.querySelector('.paper').parentElement.getBoundingClientRect().width / 2") if w < 860 else 0) < 3 or w >= 860
        assert js("return document.documentElement.scrollWidth <= innerWidth"), (w, h)
    print('LAYOUT OK')
finally:
    d.quit()
    srv.shutdown()
