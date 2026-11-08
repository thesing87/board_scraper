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
            : total === data.limit ? '한도 도달' : `남은 혜택 ${num(data.limit - total)}원`;
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

renderClock();
renderEv();
loadBoard();
loadBenefit();
setInterval(() => { renderClock(); loadBoard(); loadBenefit(); }, REFRESH_MS);
// 계산기에서 값을 바꾸고 돌아오면(다른 탭 포함) 다시 계산
window.addEventListener('storage', e => { if (e.key === 'evice') renderEv(); });
window.addEventListener('pageshow', renderEv);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { renderClock(); renderEv(); loadBoard(); loadBenefit(); } });
