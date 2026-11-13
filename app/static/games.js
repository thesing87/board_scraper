// 게임 목록: 스도쿠의 진행 상태와 기록 (스도쿠 화면이 이 기기에 저장한 값을 읽음)
'use strict';

(function () {
    const DIFFS = { easy: '쉬움', medium: '보통', hard: '어려움', expert: '전문가' };
    const read = key => { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; } };
    const fmt = ms => { const s = Math.floor(ms / 1000); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };

    // 대시보드 카드도 같은 요약을 씀 (dashboard.js)
    window.sudokuSummary = function () {
        const state = read('sudoku_state_v1'), stats = read('sudoku_stats_v1') || {};
        const playing = state && state.status === 'playing' && DIFFS[state.diff];
        let filled = 0, empty = 0;
        if (playing) state.puzzle.forEach((g, i) => { if (!g) { empty++; if (state.values[i] && state.values[i] === state.solution[i]) filled++; } });
        const records = Object.keys(DIFFS).filter(d => stats[d] && stats[d].best != null).map(d => `${DIFFS[d]} ${fmt(stats[d].best)}`);
        const won = Object.values(stats).reduce((n, s) => n + (s.won || 0), 0);
        return {
            playing: !!playing,
            status: playing ? `이어서 하기 · ${DIFFS[state.diff]} · ${fmt(state.elapsed || 0)} · ${empty ? Math.round(filled / empty * 100) : 0}% 채움`
                : '새 게임을 시작해 보세요',
            progress: playing && empty ? filled / empty : 0,
            mistakes: playing ? state.mistakes || 0 : 0,
            records: records.length ? `최고 기록 ${records.join(' · ')}` : '',
            won,
        };
    };

    if (!document.getElementById('game-sudoku')) return;
    const s = window.sudokuSummary();
    document.getElementById('sudoku-status').textContent = s.status;
    document.getElementById('sudoku-records').textContent = [s.records, s.won ? `완성 ${s.won}판` : ''].filter(Boolean).join(' · ');
    document.getElementById('sudoku-play').textContent = s.playing ? '이어서' : '시작';
})();
