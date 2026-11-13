// 스도쿠 퍼즐 생성·풀이 (화면과 무관한 계산만). 칸 번호는 0~80 (행 × 9 + 열), 빈칸은 0
'use strict';

const SudokuEngine = (() => {
    const ROW = i => Math.floor(i / 9), COL = i => i % 9;
    const BOX = i => Math.floor(ROW(i) / 3) * 3 + Math.floor(COL(i) / 3);
    const ALL = 0x3FE;   // 숫자 1~9 비트 (비트 d가 숫자 d)

    // 행·열·박스마다 칸 번호, 칸마다 같은 행·열·박스의 다른 칸
    const UNITS = { row: [], col: [], box: [] };
    for (let k = 0; k < 9; k++) { UNITS.row.push([]); UNITS.col.push([]); UNITS.box.push([]); }
    for (let i = 0; i < 81; i++) { UNITS.row[ROW(i)].push(i); UNITS.col[COL(i)].push(i); UNITS.box[BOX(i)].push(i); }
    const PEERS = [];
    for (let i = 0; i < 81; i++) {
        const set = new Set([...UNITS.row[ROW(i)], ...UNITS.col[COL(i)], ...UNITS.box[BOX(i)]]);
        set.delete(i);
        PEERS.push([...set]);
    }

    const bitCount = m => { let c = 0; while (m) { m &= m - 1; c++; } return c; };
    const digitsOf = m => { const out = []; for (let d = 1; d <= 9; d++) if (m & (1 << d)) out.push(d); return out; };

    function shuffle(list) {
        for (let i = list.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [list[i], list[j]] = [list[j], list[i]];
        }
        return list;
    }

    // 행·열·박스에 쓰인 숫자 비트 (같은 숫자가 겹치면 false)
    function masks(grid) {
        const r = new Array(9).fill(0), c = new Array(9).fill(0), b = new Array(9).fill(0);
        for (let i = 0; i < 81; i++) {
            const d = grid[i];
            if (!d) continue;
            const bit = 1 << d;
            if ((r[ROW(i)] | c[COL(i)] | b[BOX(i)]) & bit) return null;
            r[ROW(i)] |= bit; c[COL(i)] |= bit; b[BOX(i)] |= bit;
        }
        return { r, c, b };
    }

    // 백트래킹 풀이: 후보가 가장 적은 칸부터. limit개 해를 찾으면 멈추고 해의 수를 돌려줌 (randomize면 숫자 순서를 섞어 첫 해를 grid에 남김)
    function search(grid, limit, randomize) {
        const m = masks(grid);
        if (!m) return 0;
        let count = 0;
        const solve = () => {
            let best = -1, bestMask = 0, bestCount = 10;
            for (let i = 0; i < 81; i++) {
                if (grid[i]) continue;
                const cand = ALL & ~(m.r[ROW(i)] | m.c[COL(i)] | m.b[BOX(i)]);
                const n = bitCount(cand);
                if (n === 0) return false;
                if (n < bestCount) { best = i; bestMask = cand; bestCount = n; if (n === 1) break; }
            }
            if (best < 0) { count++; return count >= limit; }
            const ds = digitsOf(bestMask);
            if (randomize) shuffle(ds);
            const r = ROW(best), c = COL(best), b = BOX(best);
            for (const d of ds) {
                const bit = 1 << d;
                grid[best] = d; m.r[r] |= bit; m.c[c] |= bit; m.b[b] |= bit;
                if (solve()) return true;
                grid[best] = 0; m.r[r] &= ~bit; m.c[c] &= ~bit; m.b[b] &= ~bit;
            }
            return false;
        };
        solve();
        return count;
    }

    function countSolutions(grid, limit = 2) { return search(grid.slice(), limit, false); }

    function solve(grid) {
        const copy = grid.slice();
        return search(copy, 1, false) ? copy : null;
    }

    function fullGrid() {
        const grid = new Array(81).fill(0);
        search(grid, 1, true);
        return grid;
    }

    // 남길 숫자 개수 (적을수록 어려움). 전문가는 더 지울 수 없을 때까지 지움
    const TARGET = { easy: 40, medium: 33, hard: 28, expert: 22 };

    // 정답이 하나뿐인 퍼즐: 완성된 판에서 대칭 위치 두 칸씩 지워 보고, 해가 둘 이상이 되면 되돌림
    function generate(difficulty) {
        const target = TARGET[difficulty] || TARGET.medium;
        const attempts = { expert: 8, hard: 3 }[difficulty] || 1;
        let best = null;
        for (let a = 0; a < attempts; a++) {
            const solution = fullGrid();
            const puzzle = solution.slice();
            let givens = 81;
            const order = shuffle([...Array(41).keys()]);   // 가운데 칸(40)과 대칭 짝 (i, 80 - i)
            for (const i of order) {
                if (givens <= target) break;
                const cells = i === 40 ? [40] : [i, 80 - i];
                const kept = cells.map(c => puzzle[c]);
                cells.forEach(c => { puzzle[c] = 0; });
                if (countSolutions(puzzle) !== 1) cells.forEach((c, k) => { puzzle[c] = kept[k]; });
                else givens -= cells.length;
            }
            if (!best || givens < best.givens) best = { puzzle, solution, givens };
            if (givens <= target) break;
        }
        return { puzzle: best.puzzle, solution: best.solution };
    }

    // 지금 판(맞게 놓인 숫자만)에서 각 빈칸의 후보 비트
    function candidates(values, solution) {
        const grid = values.map((v, i) => (v && v === solution[i] ? v : 0));
        const m = masks(grid) || { r: new Array(9).fill(0), c: new Array(9).fill(0), b: new Array(9).fill(0) };
        return grid.map((v, i) => (v ? 0 : ALL & ~(m.r[ROW(i)] | m.c[COL(i)] | m.b[BOX(i)])));
    }

    // 힌트로 열 칸: 후보가 하나뿐인 칸(논리로 바로 풀리는 칸) → 박스·행·열에서 그 숫자가 들어갈 곳이 한 곳뿐인 칸 → 후보가 가장 적은 칸
    function hintCell(values, solution) {
        const cand = candidates(values, solution);
        const open = i => !(values[i] && values[i] === solution[i]);
        for (let i = 0; i < 81; i++) if (open(i) && bitCount(cand[i]) === 1) return i;
        for (const kind of ['box', 'row', 'col']) {
            for (const unit of UNITS[kind]) {
                for (let d = 1; d <= 9; d++) {
                    const spots = unit.filter(i => open(i) && (cand[i] & (1 << d)));
                    if (spots.length === 1) return spots[0];
                }
            }
        }
        let best = -1, bestCount = 10;
        for (let i = 0; i < 81; i++) if (open(i) && bitCount(cand[i]) < bestCount) { best = i; bestCount = bitCount(cand[i]); }
        return best;
    }

    return { ROW, COL, BOX, UNITS, PEERS, generate, solve, countSolutions, candidates, hintCell, digitsOf, bitCount };
})();

if (typeof module !== 'undefined') module.exports = SudokuEngine;
