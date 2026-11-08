// 카드 혜택 한도: 혜택 받은 금액을 직접 등록해 그 달 한도를 얼마나 썼는지 보여 줌.
// 소비 내역이라 조회까지 로그인이 필요하고, 키워드 게시판과 같은 로그인 키(localStorage admin_token)를 씀
'use strict';

const TOKEN_KEY = 'admin_token';
const QUICK_COUNT = 4;
const WARN_RATIO = 0.8;

const $ = id => document.getElementById(id);
const won = v => Math.round(v).toLocaleString('ko-KR');
const esc = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const parseAmount = text => parseInt(String(text).replace(/[^\d]/g, ''), 10);
const toDate = s => new Date(s + 'T00:00:00');
const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const niceDate = s => { const d = toDate(s); return `${d.getMonth() + 1}월 ${d.getDate()}일 (${'일월화수목금토'[d.getDay()]})`; };

function getToken() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } }
function setToken(v) { try { if (v) localStorage.setItem(TOKEN_KEY, v); else localStorage.removeItem(TOKEN_KEY); } catch (e) { /* 저장 불가: 이번 화면에서만 다시 로그인 */ } }

const state = { month: '', today: '', limit: 0, items: [], recent: [], filter: '전체', last: null };

// ==========================================
// 서버 통신
// ==========================================
function showLogin() {
    setToken('');
    $('content').hidden = true;
    $('month-nav').hidden = true;
    $('login').hidden = false;
    $('login-password').focus();
}

// 로그인이 풀렸으면 null (로그인 화면으로 바뀜), 실패하면 Error
async function api(body) {
    const res = await fetch('/api/card', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ ...body, password: getToken() })
    });
    if (res.status === 401) { showLogin(); return null; }
    const data = await res.json();
    if (!data.success) throw new Error(String(data.message || '').replace(/^❌\s*/, '') || '요청을 처리하지 못했습니다.');
    return data;
}

async function load(month) {
    const data = await api({ action: 'list', month });
    if (!data) return false;
    const firstLoad = !state.today;
    Object.assign(state, { month: data.month, today: data.today, limit: data.limit, items: data.items, recent: data.recent });
    if (state.filter !== '전체' && !state.items.some(x => x.place === state.filter)) state.filter = '전체';
    if (firstLoad) { $('date').value = state.today; $('date').max = state.today; }
    $('login').hidden = true;
    $('content').hidden = false;
    $('month-nav').hidden = false;
    render();
    return true;
}

// 수정·삭제 등의 요청 뒤 다시 불러옴. 실패하면 화면을 원래 값으로 되돌리고 알림
async function mutate(body, month) {
    try {
        const data = await api(body);
        if (data) await load(month || state.month);
        return data;
    } catch (e) {
        window.alert(e.message || '저장하지 못했습니다.');
        render();
        return null;
    }
}

// ==========================================
// 화면
// ==========================================
function renderHero() {
    const total = state.items.reduce((sum, x) => sum + x.amount, 0);
    const monthNo = +state.month.slice(5);
    $('month-label').textContent = `${state.month.slice(0, 4)}년 ${monthNo}월`;
    $('hero-title').textContent = `삼성카드 ${monthNo}월 혜택`;
    $('used').textContent = won(total);
    $('limit').textContent = `/ ${won(state.limit)}원`;
    $('pct').textContent = `${Math.round(total / state.limit * 100)}% 사용`;
    $('fill').style.width = `${Math.min(total / state.limit * 100, 100)}%`;
    $('hero').className = 'hero' + (total >= state.limit ? ' over' : total >= state.limit * WARN_RATIO ? ' warn' : '');
    $('left').textContent = total > state.limit ? `${won(total - state.limit)}원 초과`
        : total === state.limit ? '한도 도달' : `남은 혜택 ${won(state.limit - total)}원`;
}

function offsetDate(days) {
    const d = toDate(state.today);
    d.setDate(d.getDate() - days);
    return ymd(d);
}

function renderDate() {
    const value = $('date').value;
    document.querySelectorAll('.dates [data-offset]').forEach(b => b.classList.toggle('is-on', offsetDate(+b.dataset.offset) === value));
    $('entry-summary').textContent = $('entry').hidden && value ? `${niceDate(value)} 기준` : '';
}

function markQuick() {
    const place = $('place').value.trim(), amount = parseAmount($('amount').value);
    document.querySelectorAll('#quick button').forEach(b => b.classList.toggle('is-on', b.dataset.place === place && +b.dataset.amount === amount));
}

function renderQuick() {
    const list = state.recent.slice(0, QUICK_COUNT);
    $('recent-block').hidden = !list.length;
    $('quick').innerHTML = list.map(x => `<button type="button" data-place="${esc(x.place)}" data-amount="${x.amount}"><b>${esc(x.place)}</b><span>${won(x.amount)}원</span></button>`).join('');
    markQuick();
}

function renderUndo() {
    $('undo').hidden = !state.last;
    if (state.last) $('undo-text').textContent = `${niceDate(state.last.date)} ${state.last.place} ${won(state.last.amount)}원 등록됨`;
}

function renderChips() {
    const names = ['전체', ...new Set(state.items.map(x => x.place))];
    $('chips').innerHTML = names.map(n => `<button type="button" class="${n === state.filter ? 'is-on' : ''}" data-filter="${esc(n)}">${esc(n)}</button>`).join('');
}

function renderList() {
    const query = $('search').value.trim();
    // 누적은 필터와 상관없이 그 달 전체 기준 (최신 항목부터 거꾸로 빼 가며 계산)
    let running = state.items.reduce((sum, x) => sum + x.amount, 0);
    const cumulative = new Map();
    state.items.forEach(x => { cumulative.set(x.id, running); running -= x.amount; });
    const rows = state.items.filter(x => (state.filter === '전체' || x.place === state.filter) && (!query || x.place.includes(query)));
    $('count').textContent = `${rows.length}건 · ${won(rows.reduce((sum, x) => sum + x.amount, 0))}원`;
    const days = [...new Set(rows.map(x => x.used_on))];
    $('list').innerHTML = days.map(day => {
        const group = rows.filter(x => x.used_on === day);
        return `<div class="day"><span>${niceDate(day)}</span><span>${won(group.reduce((sum, x) => sum + x.amount, 0))}원</span></div>`
            + group.map(x => `<div class="row">
                <div class="row-info"><div class="row-name">${esc(x.place)}</div><div class="sub">누적 ${won(cumulative.get(x.id))}원</div></div>
                <input type="date" max="${state.today}" aria-label="${esc(x.place)} 날짜" data-date-id="${x.id}" value="${x.used_on}">
                <input class="amt" inputmode="numeric" aria-label="${esc(x.place)} 혜택 금액" data-amount-id="${x.id}" value="${won(x.amount)}">
                <button type="button" class="del" aria-label="${esc(x.place)} 삭제" data-del="${x.id}">×</button>
            </div>`).join('');
    }).join('') || '<div class="none">이 달의 등록 이력이 없습니다.</div>';
}

function render() {
    renderHero();
    renderDate();
    renderQuick();
    renderUndo();
    renderChips();
    renderList();
}

// ==========================================
// 입력 (최근 입력 버튼·드롭다운은 칸만 채우고, 등록은 추가 버튼으로)
// ==========================================
function closeDropdown() { $('dropdown').hidden = true; }
function openDropdown() {
    const query = $('place').value.trim();
    const list = state.recent.filter(x => !query || x.place.includes(query));
    $('dropdown').hidden = !list.length;
    $('dropdown').innerHTML = list.map(x => `<button type="button" data-place="${esc(x.place)}" data-amount="${x.amount}"><span>${esc(x.place)}</span><em>${won(x.amount)}원</em></button>`).join('');
}
function fillEntry(button) {
    $('place').value = button.dataset.place;
    $('amount').value = won(+button.dataset.amount);
    $('entry-error').textContent = '';
    closeDropdown();
    markQuick();
    $('amount').focus();
}

async function submitEntry() {
    const place = $('place').value.trim(), amount = parseAmount($('amount').value), date = $('date').value;
    const error = $('entry-error');
    if (!date) { error.textContent = '날짜를 고르세요.'; return; }
    if (!place) { error.textContent = '사용처를 입력하세요.'; return; }
    if (!(amount > 0)) { error.textContent = '혜택 금액을 숫자로 입력하세요.'; return; }
    $('add').disabled = true;
    try {
        const data = await api({ action: 'add', date, place, amount });
        if (!data) return;
        state.last = { id: data.id, date, place, amount };
        state.filter = '전체';
        $('place').value = '';
        $('amount').value = '';
        closeDropdown();
        await load(date.slice(0, 7));
    } catch (e) {
        error.textContent = e.message || '등록하지 못했습니다.';
    } finally {
        $('add').disabled = false;
    }
}

function toggleFold(button, body) {
    const open = body.hidden;
    body.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    renderDate();
}

function shiftMonth(delta) {
    const d = toDate(state.month + '-01');
    d.setMonth(d.getMonth() + delta);
    state.filter = '전체';
    guarded(load(ymd(d).slice(0, 7)));
}

function guarded(promise) {
    promise.catch(e => window.alert(e.message || '서버에 연결하지 못했습니다.'));
}

$('entry-fold').addEventListener('click', () => toggleFold($('entry-fold'), $('entry')));
$('history-fold').addEventListener('click', () => toggleFold($('history-fold'), $('history')));
$('prev').addEventListener('click', () => shiftMonth(-1));
$('next').addEventListener('click', () => shiftMonth(1));
$('date').addEventListener('change', renderDate);
document.querySelector('.dates').addEventListener('click', e => {
    const b = e.target.closest('[data-offset]');
    if (b) { $('date').value = offsetDate(+b.dataset.offset); renderDate(); }
});
$('quick').addEventListener('click', e => { const b = e.target.closest('button'); if (b) fillEntry(b); });
$('dropdown').addEventListener('click', e => { const b = e.target.closest('button'); if (b) fillEntry(b); });
$('arrow').addEventListener('click', () => { if ($('dropdown').hidden) openDropdown(); else closeDropdown(); });
$('place').addEventListener('focus', openDropdown);
$('place').addEventListener('input', () => { $('entry-error').textContent = ''; openDropdown(); markQuick(); });
$('amount').addEventListener('input', () => { $('entry-error').textContent = ''; markQuick(); });
document.addEventListener('click', e => { if (!e.target.closest('.combo') && !e.target.closest('#dropdown')) closeDropdown(); });
$('entry-form').addEventListener('submit', e => { e.preventDefault(); guarded(submitEntry()); });
$('undo-btn').addEventListener('click', () => {
    const last = state.last;
    state.last = null;
    if (last) guarded(mutate({ action: 'delete', id: last.id }));
});
$('chips').addEventListener('click', e => {
    const b = e.target.closest('[data-filter]');
    if (b) { state.filter = b.dataset.filter; renderChips(); renderList(); }
});
$('search').addEventListener('input', renderList);
$('list').addEventListener('change', e => {
    const input = e.target, id = +(input.dataset.amountId || input.dataset.dateId);
    const item = state.items.find(x => x.id === id);
    if (!item) return;
    const amount = input.dataset.amountId ? parseAmount(input.value) : item.amount;
    const date = input.dataset.dateId ? input.value : item.used_on;
    if (!(amount > 0) || !date) { renderList(); return; }
    guarded(mutate({ action: 'update', id, date, amount }));
});
$('list').addEventListener('click', e => {
    const b = e.target.closest('[data-del]');
    if (!b) return;
    const id = +b.dataset.del;
    if (state.last && state.last.id === id) state.last = null;
    guarded(mutate({ action: 'delete', id }));
});
$('login').addEventListener('submit', async e => {
    e.preventDefault();
    const input = $('login-password'), error = $('login-error');
    error.textContent = '';
    if (!input.value.trim()) { input.focus(); return; }
    try {
        const res = await fetch('/api/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify({ password: input.value })
        });
        const data = await res.json();
        if (!data.success) { error.textContent = String(data.message || '').replace(/^❌\s*/, ''); input.select(); return; }
        setToken(data.token);
        input.value = '';
        await load(state.month || '');
    } catch (err) {
        error.textContent = '서버에 연결하지 못했습니다.';
    }
});

if (getToken()) guarded(load('')); else showLogin();
