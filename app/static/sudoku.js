// 스도쿠 화면 (퍼즐 생성·풀이는 sudoku-engine.js). 진행 상태는 이 기기의 localStorage에 저장해 새로고침해도 이어서 함
'use strict';

const E = SudokuEngine;
const STATE_KEY = 'sudoku_state_v1';
const STATS_KEY = 'sudoku_stats_v1';
const MUTE_KEY = 'sudoku_muted';
const MAX_MISTAKES = 3;
const LONG_PRESS_MS = 450;
const UNDO_LIMIT = 300;
const DIFFS = { easy: '쉬움', medium: '보통', hard: '어려움', expert: '전문가' };

const $ = id => document.getElementById(id);
const store = {
    get(key, fallback) { try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 저장 불가: 이번 화면에서만 */ } },
};
const fmtTime = ms => {
    const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, sec = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : String(m).padStart(2, '0')) + ':' + String(sec).padStart(2, '0');
};

// ==========================================
// 상태
// ==========================================
let game = null;          // 저장되는 게임 상태
const ui = { sel: -1, noteMode: false, lockMode: false, lockDigit: 0, paused: false, muted: store.get(MUTE_KEY, false), lastTick: 0 };

function newGame(diff) {
    const { puzzle, solution } = E.generate(diff);
    game = { diff, puzzle, solution, values: puzzle.slice(), notes: new Array(81).fill(0), hinted: [],
             mistakes: 0, hints: 0, elapsed: 0, status: 'playing', undo: [] };
    const stats = store.get(STATS_KEY, {});
    stats[diff] = { ...(stats[diff] || { played: 0, won: 0, best: null }) };
    stats[diff].played++;
    store.set(STATS_KEY, stats);
    ui.sel = -1; ui.paused = false; ui.lockDigit = 0;
    closeModal();
    save();
    render();
}

function restart() {
    game = { ...game, values: game.puzzle.slice(), notes: new Array(81).fill(0), hinted: [], mistakes: 0, hints: 0,
             elapsed: 0, status: 'playing', undo: [] };
    ui.sel = -1; ui.paused = false;
    closeModal();
    save();
    render();
}

function save() { if (game) store.set(STATE_KEY, game); }

function load() {
    const s = store.get(STATE_KEY, null);
    const valid = s && DIFFS[s.diff] && [s.puzzle, s.solution, s.values, s.notes].every(a => Array.isArray(a) && a.length === 81);
    if (!valid) return false;
    game = { hinted: [], hints: 0, undo: [], ...s };
    return true;
}

// ==========================================
// 소리 (Web Audio API로 합성, 파일 없음)
// ==========================================
let audio = null;
function ctx() {
    if (ui.muted) return null;
    try {
        if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)();
        if (audio.state === 'suspended') audio.resume();
    } catch (e) { return null; }
    return audio;
}
function tone(freq, { at = 0, dur = 0.12, type = 'sine', gain = 0.12, slide = 0 } = {}) {
    const a = ctx();
    if (!a) return;
    const t = a.currentTime + at;
    const osc = a.createOscillator(), g = a.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t);
    if (slide) osc.frequency.exponentialRampToValueAtTime(freq * slide, t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(g).connect(a.destination);
    osc.start(t);
    osc.stop(t + dur + 0.02);
}
const sound = {
    select: () => tone(1320, { dur: 0.04, gain: 0.04 }),
    input: () => { tone(660, { dur: 0.09, type: 'triangle', gain: 0.1 }); tone(990, { at: 0.02, dur: 0.07, gain: 0.04 }); },
    note: () => tone(1760, { dur: 0.05, type: 'triangle', gain: 0.05 }),
    erase: () => tone(420, { dur: 0.08, type: 'triangle', gain: 0.06, slide: 0.7 }),
    wrong: () => { tone(196, { dur: 0.22, type: 'sawtooth', gain: 0.06, slide: 0.85 }); tone(185, { at: 0.03, dur: 0.22, type: 'square', gain: 0.03 }); },
    chord: () => [523.25, 659.25, 783.99, 1046.5].forEach((f, k) => tone(f, { at: k * 0.06, dur: 0.5, type: 'triangle', gain: 0.07 })),
    win: () => {
        [523.25, 659.25, 783.99, 1046.5, 783.99, 1046.5, 1318.5].forEach((f, k) => tone(f, { at: k * 0.11, dur: 0.35, type: 'triangle', gain: 0.09 }));
        [261.63, 329.63, 392].forEach(f => tone(f, { at: 0.77, dur: 1.2, type: 'sine', gain: 0.06 }));
    },
    over: () => [392, 349.23, 311.13, 261.63].forEach((f, k) => tone(f, { at: k * 0.16, dur: 0.4, type: 'triangle', gain: 0.07 })),
};

// ==========================================
// 보드 그리기
// ==========================================
const board = $('board');
const cells = [];
for (let i = 0; i < 81; i++) {
    const cell = document.createElement('button');
    cell.type = 'button';
    cell.className = 'cell';
    cell.dataset.i = i;
    const r = E.ROW(i), c = E.COL(i);
    if (c % 3 === 2 && c < 8) cell.classList.add('edge-r');
    if (r % 3 === 2 && r < 8) cell.classList.add('edge-b');
    cell.innerHTML = '<span class="val"></span><span class="notes">' + [1, 2, 3, 4, 5, 6, 7, 8, 9].map(d => `<i data-d="${d}"></i>`).join('') + '</span>';
    board.appendChild(cell);
    cells.push(cell);
}

const isGiven = i => game.puzzle[i] !== 0;
const isCorrect = i => game.values[i] !== 0 && game.values[i] === game.solution[i];

function placedCount(d) { let n = 0; for (let i = 0; i < 81; i++) if (game.values[i] === d && isCorrect(i)) n++; return n; }

function render() {
    if (!game) return;
    const sel = ui.sel;
    const selVal = sel >= 0 ? game.values[sel] : 0;
    const focusDigit = ui.lockDigit || selVal;
    const peers = sel >= 0 ? new Set(E.PEERS[sel]) : new Set();
    const hinted = new Set(game.hinted);
    for (let i = 0; i < 81; i++) {
        const cell = cells[i], v = game.values[i];
        cell.querySelector('.val').textContent = v || '';
        const cl = cell.classList;
        cl.toggle('is-given', isGiven(i));
        cl.toggle('is-user', !isGiven(i) && v !== 0 && isCorrect(i));
        cl.toggle('is-wrong', !isGiven(i) && v !== 0 && !isCorrect(i));
        cl.toggle('is-hinted', hinted.has(i) && isCorrect(i));
        cl.toggle('is-sel', i === sel);
        cl.toggle('is-peer', peers.has(i));
        cl.toggle('is-same', !!focusDigit && v === focusDigit && i !== sel);
        cl.toggle('has-notes', !v && game.notes[i] !== 0);
        const notes = cell.querySelectorAll('.notes i');
        for (let d = 1; d <= 9; d++) {
            const on = !v && (game.notes[i] & (1 << d));
            notes[d - 1].textContent = on ? d : '';
            notes[d - 1].classList.toggle('is-hit', !!on && d === focusDigit);
        }
        cell.setAttribute('aria-label', `${E.ROW(i) + 1}행 ${E.COL(i) + 1}열 ${v ? v : '빈칸'}${!isGiven(i) && v && !isCorrect(i) ? ' (틀림)' : ''}`);
    }
    // 숫자 패드: 남은 개수, 다 채운 숫자는 흐리게, 고정한 숫자 표시
    document.querySelectorAll('.pad-btn').forEach(b => {
        const d = +b.dataset.d, left = 9 - placedCount(d);
        b.querySelector('.pad-left').textContent = left > 0 ? left : '';
        b.classList.toggle('is-done', left <= 0);
        b.classList.toggle('is-locked', ui.lockDigit === d);
        b.setAttribute('aria-pressed', String(ui.lockDigit === d));
    });
    $('note-btn').setAttribute('aria-pressed', String(ui.noteMode));
    $('note-state').textContent = ui.noteMode ? '켜짐' : '꺼짐';
    $('lock-btn').setAttribute('aria-pressed', String(ui.lockMode || !!ui.lockDigit));
    $('lock-state').textContent = ui.lockDigit ? ui.lockDigit : (ui.lockMode ? '숫자 선택' : '꺼짐');
    $('undo-btn').disabled = !game.undo.length || game.status !== 'playing';
    $('mistakes').textContent = `${game.mistakes}/${MAX_MISTAKES}`;
    $('mistakes').classList.toggle('is-bad', game.mistakes > 0);
    $('timer').textContent = fmtTime(game.elapsed);
    document.querySelectorAll('.diff-btn').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.diff === game.diff)));
    $('pause-btn').setAttribute('aria-pressed', String(ui.paused));
    $('pause-btn').setAttribute('aria-label', ui.paused ? '계속하기' : '일시정지');
    $('pause-icon').innerHTML = ui.paused ? '<path d="M8 5l11 7-11 7z"></path>' : '<path d="M8 5v14M16 5v14"></path>';
    $('paused').hidden = !ui.paused || game.status !== 'playing';
    board.classList.toggle('is-paused', ui.paused && game.status === 'playing');
    $('mute-btn').setAttribute('aria-pressed', String(ui.muted));
    $('mute-btn').setAttribute('aria-label', ui.muted ? '소리 켜기' : '소리 끄기');
    $('mute-icon').innerHTML = ui.muted
        ? '<path d="M4 9h4l5-4v14l-5-4H4z"></path><path d="M17 9l4 6M21 9l-4 6"></path>'
        : '<path d="M4 9h4l5-4v14l-5-4H4z"></path><path d="M17 8.5a5 5 0 0 1 0 7M19.5 6a8.5 8.5 0 0 1 0 12"></path>';
}

// ==========================================
// 효과: 흔들림·붉은 펄스, 줄 완성 물결, 컨페티
// ==========================================
function flash(i, cls) {
    const cell = cells[i];
    cell.classList.remove(cls);
    void cell.offsetWidth;
    cell.classList.add(cls);
    cell.addEventListener('animationend', () => cell.classList.remove(cls), { once: true });
}

function shimmer(list, from) {
    const fr = E.ROW(from), fc = E.COL(from);
    list.forEach(i => {
        const dist = Math.abs(E.ROW(i) - fr) + Math.abs(E.COL(i) - fc);
        const cell = cells[i];
        cell.classList.remove('is-shimmer');
        void cell.offsetWidth;
        cell.style.setProperty('--wave-delay', dist * 45 + 'ms');
        cell.classList.add('is-shimmer');
        cell.addEventListener('animationend', e => { if (e.animationName === 'shimmer') cell.classList.remove('is-shimmer'); });
    });
}

function completedUnits(i) {
    const done = [];
    const units = [E.UNITS.row[E.ROW(i)], E.UNITS.col[E.COL(i)], E.UNITS.box[E.BOX(i)]];
    units.forEach(u => { if (u.every(isCorrect)) done.push(...u); });
    return [...new Set(done)];
}

const confettiCanvas = $('confetti');
function confetti() {
    const c = confettiCanvas, g = c.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    c.width = innerWidth * dpr; c.height = innerHeight * dpr;
    g.scale(dpr, dpr);
    c.hidden = false;
    const colors = ['#C2410C', '#1F4E9C', '#0F9D7A', '#D4A017', '#993556', '#2B2B2B'];
    const parts = [];
    const burst = (x, y, n, spread) => {
        for (let k = 0; k < n; k++) {
            const a = -Math.PI / 2 + (Math.random() - 0.5) * spread, sp = 7 + Math.random() * 9;
            parts.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, w: 6 + Math.random() * 6, h: 3 + Math.random() * 5,
                         r: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.3, color: colors[k % colors.length], life: 0 });
        }
    };
    burst(innerWidth * 0.25, innerHeight * 0.9, 90, 1.2);
    burst(innerWidth * 0.75, innerHeight * 0.9, 90, 1.2);
    setTimeout(() => burst(innerWidth / 2, innerHeight * 0.75, 110, 2.2), 250);
    const start = performance.now();
    const step = now => {
        g.clearRect(0, 0, innerWidth, innerHeight);
        parts.forEach(p => {
            p.vy += 0.28; p.vx *= 0.99; p.vy *= 0.99; p.x += p.vx; p.y += p.vy; p.r += p.vr; p.life++;
            g.save();
            g.translate(p.x, p.y); g.rotate(p.r);
            g.globalAlpha = Math.max(0, 1 - (now - start) / 4200);
            g.fillStyle = p.color;
            g.fillRect(-p.w / 2, -p.h / 2, p.w, p.h * Math.abs(Math.cos(p.life / 6)));
            g.restore();
        });
        if (now - start < 4200) requestAnimationFrame(step);
        else { g.clearRect(0, 0, innerWidth, innerHeight); c.hidden = true; }
    };
    requestAnimationFrame(step);
}

// ==========================================
// 입력
// ==========================================
function snapshot(list) { return list.map(i => ({ i, v: game.values[i], n: game.notes[i] })); }
function pushUndo(entry) {
    game.undo.push(entry);
    if (game.undo.length > UNDO_LIMIT) game.undo.shift();
}

function select(i, quiet) {
    if (i === ui.sel) return;
    ui.sel = i;
    if (!quiet) sound.select();
    render();
}

function playable() { return game && game.status === 'playing' && !ui.paused; }

function enter(d, i = ui.sel) {
    if (!playable() || i < 0 || isGiven(i)) return;
    if (ui.noteMode) {
        if (game.values[i]) return;
        pushUndo(snapshot([i]));
        game.notes[i] ^= (1 << d);
        sound.note();
        save(); render();
        return;
    }
    if (game.values[i] === d) return;
    const bit = 1 << d;
    const touched = [i, ...E.PEERS[i].filter(p => game.notes[p] & bit)];
    pushUndo(snapshot(touched));
    game.values[i] = d;
    game.notes[i] = 0;
    if (d === game.solution[i]) {
        // 맞으면 같은 행·열·박스의 이 숫자 메모를 지움
        E.PEERS[i].forEach(p => { game.notes[p] &= ~bit; });
        const done = completedUnits(i);
        save(); render();
        if (done.length) { shimmer(done, i); sound.chord(); } else sound.input();
        if (game.values.every((v, k) => v === game.solution[k])) win();
    } else {
        game.mistakes++;
        save(); render();
        flash(i, 'is-shake');
        sound.wrong();
        if (game.mistakes >= MAX_MISTAKES) lose();
    }
}

function erase(i = ui.sel) {
    if (!playable() || i < 0 || isGiven(i) || (!game.values[i] && !game.notes[i])) return;
    pushUndo(snapshot([i]));
    game.values[i] = 0;
    game.notes[i] = 0;
    game.hinted = game.hinted.filter(h => h !== i);
    sound.erase();
    save(); render();
}

function undo() {
    if (!playable() || !game.undo.length) return;
    game.undo.pop().forEach(({ i, v, n }) => { game.values[i] = v; game.notes[i] = n; });
    sound.erase();
    save(); render();
}

function hint() {
    if (!playable()) return;
    let i = ui.sel;
    if (i < 0 || isGiven(i) || isCorrect(i)) i = E.hintCell(game.values, game.solution);
    if (i < 0) return;
    const d = game.solution[i], bit = 1 << d;
    game.values[i] = d;
    game.notes[i] = 0;
    E.PEERS[i].forEach(p => { game.notes[p] &= ~bit; });
    game.hints++;
    game.hinted.push(i);
    game.undo = game.undo.filter(entry => !entry.some(c => c.i === i));
    ui.sel = i;
    const done = completedUnits(i);
    save(); render();
    flash(i, 'is-reveal');
    if (done.length) { shimmer(done, i); sound.chord(); } else sound.input();
    if (game.values.every((v, k) => v === game.solution[k])) win();
}

function moveSel(dr, dc) {
    const i = ui.sel < 0 ? 40 : ui.sel;
    const r = (E.ROW(i) + dr + 9) % 9, c = (E.COL(i) + dc + 9) % 9;
    select(r * 9 + c);
}

function setPaused(on) {
    if (!game || game.status !== 'playing') return;
    ui.paused = on;
    ui.lastTick = performance.now();
    render();
}

// ==========================================
// 결과
// ==========================================
function openModal(html) {
    $('modal-card').innerHTML = html;
    $('modal').hidden = false;
    const first = $('modal-card').querySelector('button');
    if (first) first.focus();
}
function closeModal() { $('modal').hidden = true; }

function diffButtons(current) {
    return `<div class="modal-diffs">${Object.entries(DIFFS).map(([k, v]) =>
        `<button type="button" class="modal-diff${k === current ? ' is-on' : ''}" data-new="${k}">${v}</button>`).join('')}</div>`;
}

function win() {
    game.status = 'won';
    const stats = store.get(STATS_KEY, {});
    const s = stats[game.diff] = { ...(stats[game.diff] || { played: 1, won: 0, best: null }) };
    s.won++;
    const record = s.best == null || game.elapsed < s.best;
    if (record) s.best = game.elapsed;
    store.set(STATS_KEY, stats);
    ui.sel = -1; ui.lockDigit = 0; ui.lockMode = false;
    save(); render();
    setTimeout(() => {
        confetti();
        sound.win();
        openModal(`
            <div class="modal-badge">완성</div>
            <h2 id="modal-title">퍼즐을 풀었어요</h2>
            <dl class="result">
                <div><dt>소요 시간</dt><dd>${fmtTime(game.elapsed)}${record ? '<small>최고 기록</small>' : ''}</dd></div>
                <div><dt>난이도</dt><dd>${DIFFS[game.diff]}</dd></div>
                <div><dt>실수</dt><dd>${game.mistakes}회</dd></div>
                <div><dt>힌트</dt><dd>${game.hints}회</dd></div>
            </dl>
            <p class="modal-sub">새 게임 난이도</p>
            ${diffButtons(game.diff)}`);
    }, 700);
}

function lose() {
    game.status = 'lost';
    save(); render();
    sound.over();
    openModal(`
        <div class="modal-badge is-bad">게임 오버</div>
        <h2 id="modal-title">실수를 ${MAX_MISTAKES}번 했어요</h2>
        <p class="modal-text">${DIFFS[game.diff]} · ${fmtTime(game.elapsed)} 동안 플레이</p>
        <div class="modal-actions">
            <button type="button" class="modal-primary" data-restart>같은 퍼즐 다시 풀기</button>
        </div>
        <p class="modal-sub">또는 새 게임</p>
        ${diffButtons(game.diff)}`);
}

// ==========================================
// 이벤트
// ==========================================
board.addEventListener('click', e => {
    const cell = e.target.closest('.cell');
    if (!cell || !playable()) return;
    const i = +cell.dataset.i;
    if (ui.lockDigit && !isGiven(i)) {
        select(i, true);
        enter(ui.lockDigit, i);
        return;
    }
    select(i);
});

// 숫자 패드: 누르면 고른 칸에 입력, 길게 누르면 그 숫자 고정(이후 칸을 누를 때마다 그 숫자를 채움)
let pressTimer = 0, longPressed = false;
const pad = $('pad');
pad.addEventListener('pointerdown', e => {
    const b = e.target.closest('.pad-btn');
    if (!b) return;
    longPressed = false;
    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => {
        longPressed = true;
        const d = +b.dataset.d;
        ui.lockDigit = ui.lockDigit === d ? 0 : d;
        ui.lockMode = false;
        if (navigator.vibrate) navigator.vibrate(15);
        sound.note();
        render();
    }, LONG_PRESS_MS);
});
['pointerup', 'pointerleave', 'pointercancel'].forEach(ev => pad.addEventListener(ev, () => clearTimeout(pressTimer)));
pad.addEventListener('contextmenu', e => e.preventDefault());
pad.addEventListener('click', e => {
    const b = e.target.closest('.pad-btn');
    if (!b || longPressed) { longPressed = false; return; }
    const d = +b.dataset.d;
    if (ui.lockMode || ui.lockDigit) {
        ui.lockDigit = ui.lockDigit === d ? 0 : d;
        ui.lockMode = false;
        sound.note();
        render();
        return;
    }
    enter(d);
});

$('undo-btn').addEventListener('click', undo);
$('erase-btn').addEventListener('click', () => erase());
$('hint-btn').addEventListener('click', hint);
$('note-btn').addEventListener('click', () => { ui.noteMode = !ui.noteMode; sound.note(); render(); });
$('lock-btn').addEventListener('click', () => {
    if (ui.lockDigit || ui.lockMode) { ui.lockDigit = 0; ui.lockMode = false; }
    else ui.lockMode = true;
    sound.note();
    render();
});
$('pause-btn').addEventListener('click', () => setPaused(!ui.paused));
$('resume-btn').addEventListener('click', () => setPaused(false));
$('mute-btn').addEventListener('click', () => {
    ui.muted = !ui.muted;
    store.set(MUTE_KEY, ui.muted);
    render();
    sound.select();
});
document.querySelector('.diffs').addEventListener('click', e => {
    const b = e.target.closest('.diff-btn');
    if (!b) return;
    const inProgress = game && game.status === 'playing' && game.values.some((v, i) => v && !isGiven(i));
    if (inProgress && !window.confirm(`진행 중인 게임을 끝내고 ${DIFFS[b.dataset.diff]} 새 게임을 시작할까요?`)) return;
    newGame(b.dataset.diff);
});
$('new-btn').addEventListener('click', () => {
    const inProgress = game && game.status === 'playing' && game.values.some((v, i) => v && !isGiven(i));
    if (inProgress && !window.confirm('진행 중인 게임을 끝내고 새 게임을 시작할까요?')) return;
    newGame(game ? game.diff : 'medium');
});
$('modal').addEventListener('click', e => {
    const n = e.target.closest('[data-new]');
    if (n) { newGame(n.dataset.new); return; }
    if (e.target.closest('[data-restart]')) restart();
});

document.addEventListener('keydown', e => {
    if (!$('modal').hidden || e.target.closest('input, textarea, select')) return;
    const key = e.key;
    if ((e.ctrlKey || e.metaKey) && key.toLowerCase() === 'z') { e.preventDefault(); undo(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (key === 'p' || key === 'P') { setPaused(!ui.paused); return; }
    if (!playable()) return;
    const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (moves[key]) { e.preventDefault(); moveSel(...moves[key]); return; }
    if (/^[1-9]$/.test(key)) { e.preventDefault(); enter(+key); return; }
    if (key === 'Backspace' || key === 'Delete' || key === '0') { e.preventDefault(); erase(); return; }
    if (key === 'n' || key === 'N') { ui.noteMode = !ui.noteMode; sound.note(); render(); return; }
    if (key === 'Escape') { ui.sel = -1; ui.lockDigit = 0; ui.lockMode = false; render(); }
});

// 시간: 플레이 중이고 화면이 보일 때만. 다른 앱·탭으로 가면 자동 일시정지
setInterval(() => {
    const now = performance.now();
    if (game && game.status === 'playing' && !ui.paused && !document.hidden && $('modal').hidden) {
        game.elapsed += now - (ui.lastTick || now);
        $('timer').textContent = fmtTime(game.elapsed);
        if (Math.floor(game.elapsed / 1000) % 5 === 0) save();
    }
    ui.lastTick = now;
}, 1000);
document.addEventListener('visibilitychange', () => {
    if (document.hidden && game && game.status === 'playing') { setPaused(true); save(); }
});
window.addEventListener('pagehide', save);

// 시작: 저장된 게임이 있으면 이어서 (끝난 게임이면 같은 난이도로 새 게임)
if (!load() || game.status !== 'playing') {
    const diff = game ? game.diff : 'medium';
    $('board').classList.add('is-loading');
    setTimeout(() => { newGame(diff); $('board').classList.remove('is-loading'); }, 30);
} else {
    ui.paused = game.elapsed > 0;   // 이어서 할 때는 일시정지 화면부터 (시간이 바로 흐르지 않게)
    ui.lastTick = performance.now();
    render();
}
