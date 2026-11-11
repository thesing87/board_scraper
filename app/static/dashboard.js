// 메인 대시보드: 키워드 게시판(/board/)과 유지비 계산기(/ev/)로 가는 카드에 요약을 보여 줌.
// 게시판 카드는 서버(/api/state·/api/dashboard)에서 1분마다 새로 받고, 유지비 카드는 계산기가 이 기기에 저장한 입력값으로 계산
'use strict';

// 예전 텔레그램 알림 링크(/#post-ID)는 키워드 게시판의 그 글로
if (/^#post-/.test(window.location.hash)) window.location.replace('/board/' + window.location.hash);

const REFRESH_MS = 60 * 1000;
// 마지막 수집 주기가 이보다 오래전이면 수집이 멈춘 것으로 표시
const STALL_MINUTES = 10;

const $ = id => document.getElementById(id);
function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}
const num = n => Number(n || 0).toLocaleString('ko-KR');
const parseTime = s => s ? new Date(s.replace(' ', 'T')) : null;
// 서버 시각 기준 'N분 전'
function ago(time, now) {
    const t = parseTime(time);
    if (!t || !now) return '';
    const min = Math.max(0, Math.round((now - t) / 60000));
    if (min < 1) return '방금';
    if (min < 60) return `${min}분 전`;
    const hours = Math.floor(min / 60);
    return hours < 24 ? `${hours}시간 전` : `${Math.floor(hours / 24)}일 전`;
}

function renderClock() {
    const now = new Date();
    const days = '일월화수목금토';
    $('dash-clock').textContent = `${now.getMonth() + 1}월 ${now.getDate()}일 (${days[now.getDay()]}) `
        + `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
}

// ==========================================
// 키워드 게시판 카드
// ==========================================
function renderBoard(state, dash) {
    const groups = state.groups || [];
    const keywords = new Set(groups.flatMap(g => g.members.map(m => m.board + '\u001f' + m.keyword)));
    $('board-sub').textContent = `게시판 ${groups.length}개 · 키워드 ${keywords.size}개`;
    const now = parseTime(dash.now);

    const met = (label, value, cls = '') => `
        <div class="met"><span class="met-label">${label}</span><span class="met-value ${cls}">${num(value)}</span></div>`;
    const busy = groups.filter(g => g.unread_count || g.comment_count);
    const chips = busy.length
        ? `<div class="chips">${busy.map(g => `
            <a class="chip" href="/board/#board-${g.id}">${esc(g.name)}
                ${g.unread_count ? `<span class="chip-unread" aria-label="안 읽은 새 글 ${g.unread_count}개">${num(g.unread_count)}</span>` : ''}
                ${g.comment_count ? `<span class="chip-comments" aria-label="새 댓글 달린 글 ${g.comment_count}개">${g.unread_count ? '· ' : ''}${num(g.comment_count)}</span>` : ''}
            </a>`).join('')}</div>`
        : '<span class="empty">모든 게시판의 새 글을 읽었습니다</span>';
    const posts = (dash.recent || []).length
        ? `<div class="posts">${dash.recent.map(p => `
            <a class="post ${p.is_read ? 'is-read' : ''}" href="/board/#post-${encodeURIComponent(p.id)}">
                ${p.group ? `<span class="post-board">${esc(p.group)}</span>` : ''}
                <span class="post-title">${esc(p.title)}</span>
                <span class="post-meta">추천 ${num(String(p.votes).replace(/[^\d]/g, ''))} ·${ago(p.collected_at, now)}</span>
            </a>`).join('')}</div>`
        : '<span class="empty">수집한 글이 없습니다</span>';

    const cycle = dash.collector;
    const finished = cycle && parseTime(cycle.finished_at);
    const stalled = !finished || (now - finished) / 60000 > STALL_MINUTES;
    const status = stalled
        ? `<span class="foot-bad"><span class="dot is-bad"></span>수집 멈춤 의심</span>`
        : `<span><span class="dot"></span>수집 중 · ${dash.check_interval}초 주기</span>`;
    const errors = cycle ? cycle.errors || 0 : 0;

    $('board-body').innerHTML = `
        <div class="mets">
            ${met('안 읽은 새 글', state.all.unread_count, 'is-unread')}
            ${met('새 댓글 달린 글', state.all.comment_count, 'is-comments')}
            ${met('오늘 수집', dash.today_count)}
        </div>
        <div><p class="sec-title">새 글 있는 게시판</p>${chips}</div>
        <div><p class="sec-title">최근 수집한 글</p>${posts}</div>
        <div class="card-foot">
            ${status}
            ${finished ? `<span>마지막 수집 ${ago(cycle.finished_at, now)}</span>` : ''}
            <span class="${errors ? 'foot-bad' : ''}">오류 ${num(errors)}</span>
        </div>`;
}

function renderBoardError() {
    $('board-sub').textContent = '서버에 연결하지 못했습니다';
    $('board-body').innerHTML = '<span class="empty">잠시 후 자동으로 다시 시도합니다</span>';
}

async function getJSON(url) {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(res.status);
    return res.json();
}

async function loadBoard() {
    try {
        const [state, dash] = await Promise.all([getJSON('/api/state'), getJSON('/api/dashboard')]);
        renderBoard(state, dash);
    } catch (e) {
        renderBoardError();
    }
}

// ==========================================
// 게시판별 인기글 카드: 최근 24시간 동안 게시판마다 추천+댓글이 많은 글 3개 (전체 보기는 키워드 게시판의 '인기글')
// ==========================================
const countText = v => num(String(v || 0).replace(/[^\d]/g, '') || 0);
async function loadPopular() {
    try {
        const data = await getJSON('/api/popular?days=1&limit=3');
        $('popular-body').innerHTML = data.groups.length
            ? `<div class="popular-boards">${data.groups.map(g => `
                <div class="popular-board">
                    <a class="popular-board-name" href="/board/#board-${g.id}">${esc(g.name)}</a>
                    ${g.posts.map((p, i) => `
                    <a class="popular-post${p.is_read ? ' is-read' : ''}" href="/board/#post-${encodeURIComponent(p.id)}">
                        <span class="popular-rank">${i + 1}</span>
                        <span class="post-title">${esc(p.title)}</span>
                        <span class="post-meta" title="추천 · 댓글">추천 ${countText(p.votes)} · 댓글 ${countText(p.comment_count)}</span>
                    </a>`).join('')}
                </div>`).join('')}</div>`
            : '<span class="empty">최근 24시간 동안 모은 글이 없습니다</span>';
    } catch (e) {
        $('popular-body').innerHTML = '<span class="empty">인기글을 불러오지 못했습니다</span>';
    }
}

// ==========================================
// 수집 통계 카드: 최근 7일 동안 수집한 글 수 (자세한 통계는 /stats/)
// ==========================================
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];
async function loadStats() {
    try {
        const stats = await getJSON('/api/stats?days=7');
        const max = Math.max(1, ...stats.daily.map(d => d.count));
        const last = stats.daily.length - 1;
        const diff = stats.total - stats.previous;
        $('stats-sub').textContent = `최근 7일 ${stats.total.toLocaleString('ko-KR')}개`
            + (stats.previous ? ` · 지난주보다 ${Math.abs(diff).toLocaleString('ko-KR')}개 ${diff >= 0 ? '많음' : '적음'}` : '');
        $('stats-body').innerHTML = `<div>
            <div class="week-bars" role="img" aria-label="최근 7일 날짜별 수집 글 수: ${stats.daily.map(d => `${d.date.slice(5)} ${d.count}개`).join(', ')}">
                ${stats.daily.map((d, i) => `<span class="week-bar${i === last ? ' is-today' : ''}"><b>${d.count}</b><i style="height:${Math.round(d.count / max * 72)}px"></i></span>`).join('')}
            </div>
            <div class="week-days" aria-hidden="true">
                ${stats.daily.map((d, i) => `<span class="${i === last ? 'is-today' : ''}">${i === last ? '오늘' : WEEKDAYS[new Date(d.date + 'T00:00:00').getDay()]}</span>`).join('')}
            </div>
        </div>`;
    } catch (e) {
        $('stats-body').innerHTML = '<span class="empty">통계를 불러오지 못했습니다</span>';
    }
}

// ==========================================
// 전기차 vs 내연기관 카드 (계산식은 ev.js와 같음)
// ==========================================
const EV_DEFAULTS = { dist: 1500, evEffIn: 5.0, evPrice: 347, evLoss: 10, iceEff: 12, icePrice: 1700 };
function shortWon(v) {
    v = Math.round(v);
    if (Math.abs(v) >= 10000) {
        const m = v / 10000;
        return (Math.abs(m) >= 100 ? Math.round(m) : +m.toFixed(1)).toLocaleString('ko-KR') + '만원';
    }
    return v.toLocaleString('ko-KR') + '원';
}

function renderEv() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem('evice') || 'null'); } catch (e) { saved = null; }
    const v = { ...EV_DEFAULTS, ...(saved || {}) };
    const loss = Math.min(v.evLoss, 95) / 100;
    const effEff = v.evEffIn * (1 - loss);
    const evKm = effEff > 0 ? v.evPrice / effEff : 0;
    const iceKm = v.iceEff > 0 ? v.icePrice / v.iceEff : 0;
    const evM = evKm * v.dist, iceM = iceKm * v.dist, diff = iceM - evM;
    const max = Math.max(evM, iceM, 1);
    const breakEven = iceKm * effEff;   // 이 충전 단가를 넘으면 전기차가 더 비쌈

    const big = Math.abs(diff) < 1 ? '두 차량 비용이 같아요'
        : diff > 0 ? `전기차가 월 ${shortWon(diff)} 절약` : `내연기관이 월 ${shortWon(-diff)} 저렴`;
    $('ev-body').innerHTML = `
        <div>
            <div class="ev-head">월 ${num(v.dist)}km 기준 · ${saved ? '마지막 입력값' : '기본값'}</div>
            <div class="ev-big ${diff < 0 ? 'is-ice' : ''}">${big}</div>
            ${Math.abs(diff) >= 1 ? `<div class="ev-sub">1년 ${shortWon(Math.abs(diff) * 12)} · 5년 ${shortWon(Math.abs(diff) * 60)}</div>` : ''}
        </div>
        <div class="bars">
            <div class="bar-row"><span>전기차</span><div class="bar"><i style="width:${evM / max * 100}%;background:var(--ev)"></i></div><b>${shortWon(evM)}</b></div>
            <div class="bar-row"><span>내연기관</span><div class="bar"><i style="width:${iceM / max * 100}%;background:var(--ice)"></i></div><b>${shortWon(iceM)}</b></div>
        </div>
        <div class="mets two">
            <div class="met"><span class="met-label">전기차 km당</span><span class="met-value is-small">${evKm.toFixed(1)}<small>원</small></span></div>
            <div class="met"><span class="met-label">내연기관 km당</span><span class="met-value is-small">${iceKm.toFixed(1)}<small>원</small></span></div>
        </div>
        <div class="card-foot ev-foot">
            <span>충전 단가 ${num(v.evPrice)}원/kWh · 유가 ${num(v.icePrice)}원/L</span>
            <span>충전 단가가 <b>${num(Math.round(breakEven))}원/kWh</b>를 넘으면 내연기관이 더 저렴</span>
        </div>`;
}

// ==========================================
// 카드 혜택 한도 카드 (소비 내역이라 로그인 키가 있는 기기에서만 조회)
// ==========================================
const ADMIN_TOKEN_KEY = 'admin_token';

function renderBenefitMessage(text) {
    $('benefit-body').innerHTML = `<span class="empty">${text}</span>`;
}

async function loadBenefit() {
    let token = '';
    try { token = localStorage.getItem(ADMIN_TOKEN_KEY) || ''; } catch (e) { token = ''; }
    if (!token) { renderBenefitMessage('열어서 로그인하면 이번 달 사용액이 표시됩니다'); return; }
    try {
        const res = await fetch('/api/card', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify({ action: 'list', password: token })
        });
        if (res.status === 401) {
            // 틀린 키로 1분마다 다시 요청하면 잠길 수 있어 바로 지움
            try { localStorage.removeItem(ADMIN_TOKEN_KEY); } catch (e) { /* 지우지 못해도 표시만 바꿈 */ }
            renderBenefitMessage('열어서 로그인하면 이번 달 사용액이 표시됩니다');
            return;
        }
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        const total = data.items.reduce((sum, x) => sum + x.amount, 0);
        const level = total >= data.limit ? 'is-over' : total >= data.limit * 0.8 ? 'is-warn' : '';
        const left = total > data.limit ? `${num(total - data.limit)}원 초과`
            : total === data.limit ? '한도 도달' : `남은 한도 ${num(data.limit - total)}원`;
        $('benefit-sub').textContent = `삼성카드 ${+data.month.slice(5)}월`;
        $('benefit-body').innerHTML = `<div>
            <div class="benefit-main">
                <span class="benefit-used">${num(total)}<small>/ ${num(data.limit)}원</small></span>
                <span class="benefit-left ${total > data.limit ? 'is-over' : ''}">${left}</span>
            </div>
            <div class="benefit-bar ${level}"><i style="width:${Math.min(total / data.limit * 100, 100)}%"></i></div>
        </div>`;
    } catch (e) {
        renderBenefitMessage('잠시 후 자동으로 다시 시도합니다');
    }
}

// ==========================================
// 카드 배치 편집 (이동·크기). 화면 크기가 기기마다 달라 이 기기에만 저장
// ==========================================
const LAYOUT_KEY = 'dashboard_layout_v1';
const COLUMNS = 12;
const MIN_COLUMNS = 3;
const DEFAULT_LAYOUT = [{ id: 'card-board', w: 7, h: null }, { id: 'card-ev', w: 5, h: null }, { id: 'card-benefit', w: 5, h: null },
                        { id: 'card-stats', w: 7, h: null }, { id: 'card-popular', w: 12, h: null }];
const MIN_HEIGHT = 120, MAX_HEIGHT = 1200, HEIGHT_STEP = 10;
const narrowScreen = window.matchMedia('(max-width: 820px)');
const grid = $('dash-grid');
const cardOf = id => document.getElementById(id);
const clamp = (v, low, high) => Math.min(Math.max(v, low), high);

function defaultLayout() { return DEFAULT_LAYOUT.map(c => ({ ...c })); }

function loadLayout() {
    let saved = [];
    try { saved = JSON.parse(localStorage.getItem(LAYOUT_KEY) || '[]'); } catch (e) { saved = []; }
    if (!Array.isArray(saved)) saved = [];
    // 저장 뒤에 카드가 늘거나 줄어도 동작하도록 아는 카드만 쓰고, 빠진 카드는 뒤에 붙임
    const used = new Set();
    const list = [];
    saved.forEach(c => {
        const base = c && DEFAULT_LAYOUT.find(d => d.id === c.id);
        if (!base || used.has(c.id)) return;
        used.add(c.id);
        list.push({ id: c.id, w: Number.isInteger(c.w) ? clamp(c.w, MIN_COLUMNS, COLUMNS) : base.w,
                    h: Number.isFinite(c.h) ? clamp(c.h, MIN_HEIGHT, MAX_HEIGHT) : null });
    });
    return list.concat(defaultLayout().filter(c => !used.has(c.id)));
}

let layout = loadLayout();

function saveLayout() {
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); } catch (e) { /* 저장 불가: 이번 화면에서만 적용 */ }
}

function rowGap() { return narrowScreen.matches ? 12 : 14; }

function syncRowSpans() {
    layout.forEach(c => {
        const span = `span ${Math.ceil(cardOf(c.id).getBoundingClientRect().height) + rowGap()}`;
        if (cardOf(c.id).style.gridRowEnd !== span) cardOf(c.id).style.gridRowEnd = span;
    });
}

function applyLayout() {
    layout.forEach((c, i) => {
        const card = cardOf(c.id);
        card.style.order = i;
        card.style.gridColumn = `span ${narrowScreen.matches ? COLUMNS : c.w}`;
        card.style.height = c.h ? `${c.h}px` : '';
    });
    syncRowSpans();
    grid.classList.add('is-ready');
}

function moveCard(item, toIndex) {
    const from = layout.indexOf(item);
    const to = clamp(toIndex, 0, layout.length - 1);
    if (from === to) return;
    layout.splice(from, 1);
    layout.splice(to, 0, item);
    applyLayout();
}

function placeUnderPointer(card, e, grabX, grabY) {
    card.style.transform = '';
    const rect = card.getBoundingClientRect();
    card.style.transform = `translate(${e.clientX - grabX - rect.left}px, ${e.clientY - grabY - rect.top}px)`;
}

function startDrag(item, e) {
    const card = cardOf(item.id), grip = e.currentTarget;
    const rect = card.getBoundingClientRect();
    const grabX = e.clientX - rect.left, grabY = e.clientY - rect.top;
    let lastTarget = null;
    grip.setPointerCapture(e.pointerId);
    card.classList.add('is-dragging');
    const onMove = ev => {
        // 다른 카드 위에 올라가면 그 자리로. 크기가 달라 자리를 바꾼 뒤에도 그 카드 위일 수 있어, 벗어나기 전에는 다시 바꾸지 않음
        const target = layout.find(c => {
            if (c === item) return false;
            const r = cardOf(c.id).getBoundingClientRect();
            return ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom;
        }) || null;
        if (target !== lastTarget) {
            lastTarget = target;
            if (target) moveCard(item, layout.indexOf(target));
        }
        placeUnderPointer(card, ev, grabX, grabY);
    };
    const onEnd = () => {
        grip.removeEventListener('pointermove', onMove);
        grip.removeEventListener('pointerup', onEnd);
        grip.removeEventListener('pointercancel', onEnd);
        card.style.transform = '';
        card.classList.remove('is-dragging');
        saveLayout();
    };
    grip.addEventListener('pointermove', onMove);
    grip.addEventListener('pointerup', onEnd);
    grip.addEventListener('pointercancel', onEnd);
}

function columnWidth() {
    const gap = narrowScreen.matches ? 12 : 14;
    return { size: (grid.clientWidth - gap * (COLUMNS - 1)) / COLUMNS, gap };
}

function startResize(item, e) {
    const card = cardOf(item.id), handle = e.currentTarget;
    const rect = card.getBoundingClientRect();
    const startY = e.clientY;
    const offsetRight = rect.right - e.clientX, offsetBottom = rect.bottom - e.clientY;
    let heightChanged = false;
    handle.setPointerCapture(e.pointerId);
    const onMove = ev => {
        if (!narrowScreen.matches) {
            const { size, gap } = columnWidth();
            item.w = clamp(Math.round((ev.clientX + offsetRight - rect.left + gap) / (size + gap)), MIN_COLUMNS, COLUMNS);
        }
        // 가로로만 끌었을 때 높이가 '내용에 맞춤'에서 고정으로 바뀌지 않도록, 세로로 움직였을 때만 높이를 정함
        if (Math.abs(ev.clientY - startY) > HEIGHT_STEP) heightChanged = true;
        if (heightChanged) {
            const height = ev.clientY + offsetBottom - rect.top;
            item.h = clamp(Math.round(height / HEIGHT_STEP) * HEIGHT_STEP, MIN_HEIGHT, MAX_HEIGHT);
        }
        applyLayout();
    };
    const onEnd = () => {
        handle.removeEventListener('pointermove', onMove);
        handle.removeEventListener('pointerup', onEnd);
        handle.removeEventListener('pointercancel', onEnd);
        saveLayout();
    };
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onEnd);
    handle.addEventListener('pointercancel', onEnd);
}

function onGripKey(item, e) {
    const delta = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[e.key];
    if (!delta) return;
    e.preventDefault();
    moveCard(item, layout.indexOf(item) + delta);
    saveLayout();
}

function onResizeKey(item, e) {
    const card = cardOf(item.id);
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') item.w = clamp(item.w + (e.key === 'ArrowRight' ? 1 : -1), MIN_COLUMNS, COLUMNS);
    else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        const now = item.h || Math.round(card.getBoundingClientRect().height);
        item.h = clamp(now + (e.key === 'ArrowDown' ? HEIGHT_STEP : -HEIGHT_STEP), MIN_HEIGHT, MAX_HEIGHT);
    } else return;
    e.preventDefault();
    applyLayout();
    saveLayout();
}

function setEditing(on) {
    document.body.classList.toggle('is-editing', on);
    $('layout-edit').textContent = on ? '완료' : '편집';
    $('layout-edit').setAttribute('aria-pressed', String(on));
    $('layout-reset').hidden = !on;
}

DEFAULT_LAYOUT.forEach(({ id }) => {
    const card = cardOf(id);
    const name = card.querySelector('.card-title').textContent;
    const button = (cls, text, label) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = cls;
        b.textContent = text;
        b.setAttribute('aria-label', label);
        card.appendChild(b);
        return b;
    };
    const itemOf = () => layout.find(c => c.id === id);
    const grip = button('card-grip', '이동', `${name} 옮기기 (방향키)`);
    const resize = button('card-resize', '', `${name} 크기 조절 (방향키)`);
    grip.addEventListener('pointerdown', e => { e.preventDefault(); startDrag(itemOf(), e); });
    resize.addEventListener('pointerdown', e => { e.preventDefault(); startResize(itemOf(), e); });
    grip.addEventListener('keydown', e => onGripKey(itemOf(), e));
    resize.addEventListener('keydown', e => onResizeKey(itemOf(), e));
});

$('layout-edit').addEventListener('click', () => setEditing(!document.body.classList.contains('is-editing')));
$('layout-reset').addEventListener('click', () => {
    layout = defaultLayout();
    applyLayout();
    saveLayout();
});
// 편집 중에는 카드 안의 링크로 이동하지 않음
grid.addEventListener('click', e => {
    if (document.body.classList.contains('is-editing') && e.target.closest('a')) e.preventDefault();
}, true);
// 내용이 새로 그려지거나 글자 줄이 바뀌어 카드 높이가 달라지면 쌓인 위치를 다시 맞춤
new ResizeObserver(syncRowSpans).observe(grid);
DEFAULT_LAYOUT.forEach(({ id }) => new ResizeObserver(syncRowSpans).observe(cardOf(id)));
narrowScreen.addEventListener('change', applyLayout);

renderClock();
renderEv();
loadBoard();
loadBenefit();
loadStats();
loadPopular();
applyLayout();
setInterval(() => { renderClock(); loadBoard(); loadBenefit(); loadPopular(); }, REFRESH_MS);
// 계산기에서 값을 바꾸고 돌아오면(다른 탭 포함) 다시 계산
window.addEventListener('storage', e => { if (e.key === 'evice') renderEv(); });
window.addEventListener('pageshow', renderEv);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { renderClock(); renderEv(); loadBoard(); loadBenefit(); loadPopular(); } });
