'use strict';

// 아파트 실거래가 화면: 관심 단지 목록(#없음) → 단지를 누르면 상세(#w-관심단지ID). 관리는 관리자 로그인 뒤.
// 금액은 서버가 만원 단위로 줌
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ADMIN_TOKEN_KEY = 'admin_token';   // 키워드 게시판과 같은 로그인 키를 함께 씀
const PERIODS = [{ months: 12, label: '1년' }, { months: 24, label: '2년' }, { months: 0, label: '전체' }];

// results: 단지 고르기 목록에서 고른 단지(하나, 등록할 면적 칩을 보여 줌)
// region: 고른 지역 {code, label}, complexes: 그 지역의 단지 목록 (최근 1년 거래)
const view = { data: null, detail: null, area: null, months: 24, managing: false, results: [], region: null, complexes: [] };

function token() { try { return localStorage.getItem(ADMIN_TOKEN_KEY) || ''; } catch (e) { return ''; } }
function setToken(value) { try { value ? localStorage.setItem(ADMIN_TOKEN_KEY, value) : localStorage.removeItem(ADMIN_TOKEN_KEY); } catch (e) { /* 저장 불가 */ } }

// 만원 단위 금액을 '12억 3,000'처럼 (억 미만은 '9,500만')
function money(manwon) {
    const eok = Math.floor(manwon / 10000), rest = manwon % 10000;
    if (!eok) return rest.toLocaleString('ko-KR') + '만';
    return rest ? `${eok}억 ${rest.toLocaleString('ko-KR')}` : `${eok}억`;
}
function shortDate(iso) { return `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`; }
function areaLabel(area) { return area ? `${area}㎡` : '모든 면적'; }
function deltaHtml(diff, note) {
    if (diff == null) return '<span class="delta">직전 거래 없음</span>';
    if (!diff) return `<span class="delta">변동 없음${note || ''}</span>`;
    return `<span class="delta ${diff > 0 ? 'is-up' : 'is-down'}">${diff > 0 ? '▲' : '▼'} ${money(Math.abs(diff))}${note || ''}</span>`;
}

async function getJSON(url) {
    const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
    if (!res.ok) throw new Error(res.status);
    return res.json();
}
async function postApt(body) {
    const res = await fetch('/api/apt', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                          body: JSON.stringify({ ...body, password: token() }) });
    if (res.status === 401) { setToken(''); renderManage(); }
    return res.json();
}

// ---------- 목록 ----------
function sparkline(points) {
    if (points.length < 2) return '<svg class="spark" viewBox="0 0 84 28" aria-hidden="true"></svg>';
    const values = points.map(p => p.amount);
    const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
    const coords = points.map((p, i) => `${(i / (points.length - 1) * 80 + 2).toFixed(1)},${(24 - (p.amount - min) / span * 20).toFixed(1)}`);
    const last = values[values.length - 1], first = values[0];
    const color = last > first ? 'var(--up)' : last < first ? 'var(--down)' : 'var(--faint)';
    return `<svg class="spark" viewBox="0 0 84 28" role="img" aria-label="최근 1년 월 평균 거래가 추이: ${last > first ? '상승' : last < first ? '하락' : '보합'}">
        <polyline points="${coords.join(' ')}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

function renderStatus() {
    const data = view.data, el = $('status');
    el.classList.remove('is-bad');
    if (!data) { el.textContent = ''; return; }
    if (!data.configured) {
        el.classList.add('is-bad');
        el.textContent = '서버에 실거래가 인증키(APT_API_KEY)가 설정되지 않아 거래를 받아 오지 못합니다.';
    } else if (data.status && !data.status.ok) {
        el.classList.add('is-bad');
        el.textContent = `마지막 수집 실패 (${data.status.at.slice(5, 16)}): ${data.status.message}`;
    } else {
        el.textContent = data.status ? `마지막 확인 ${data.status.at.slice(5, 16)}` : '아직 거래를 받아 오지 않았습니다.';
    }
}

function renderList() {
    const watches = view.data.watches;
    if (!watches.length) {
        $('list-view').innerHTML = '<div class="empty">등록한 단지가 없습니다.<br>오른쪽 위 \'관리\'에서 단지를 찾아 등록해 주세요.</div>';
        return;
    }
    const peaks = watches.filter(w => w.latest && w.peak_ratio != null)
        .map(w => `${esc(w.name)} ${w.peak_ratio === 0 ? '최고가' : w.peak_ratio + '%'}`).join(' · ');
    $('list-view').innerHTML = watches.map(w => `
        <button type="button" class="watch-row" data-watch="${w.id}">
            <span>
                <span class="watch-name">${esc(w.name)}${w.latest && w.latest.is_new ? '<span class="new-tag">새 거래</span>' : ''}</span>
                <span class="watch-meta">${w.latest
                    ? `${areaLabel(w.area || Math.round(w.latest.area))} · ${shortDate(w.latest.date)} 계약 · ${w.latest.floor}층`
                    : `${areaLabel(w.area)} · ${w.synced ? '거래 없음' : '지난 거래를 받아 오는 중'}`}</span>
            </span>
            ${sparkline(w.spark)}
            <span class="watch-price">${w.latest ? `<span class="price">${money(w.latest.amount)}</span>${deltaHtml(w.diff)}` : '<span class="delta">–</span>'}</span>
        </button>`).join('') + (peaks ? `<p class="list-foot">최고가 대비: ${peaks}</p>` : '');
}

// ---------- 상세 ----------
function detailTrades() {
    return view.detail.trades.filter(t => view.area == null || Math.round(t.area) === view.area);
}

function drawChart(trades) {
    const el = $('chart');
    const valid = trades.filter(t => !t.canceled);
    let shown = valid;
    if (view.months) {
        const from = new Date(); from.setMonth(from.getMonth() - view.months);
        const cut = from.toISOString().slice(0, 10);
        shown = valid.filter(t => t.date >= cut);
    }
    if (!shown.length) { el.innerHTML = '<div class="empty">이 기간에 거래가 없습니다.</div>'; return; }
    // 그림 크기를 실제 칸 너비에 맞춤 (좁은 화면에서 눈금 글자가 함께 줄어 안 보이지 않게)
    const W = Math.max(280, Math.round(el.clientWidth || 640)), H = W < 480 ? 200 : 230, L = 50, R = 14, T = 12, B = 26;
    const time = iso => new Date(iso + 'T00:00:00').getTime();
    const times = shown.map(t => time(t.date));
    let t0 = Math.min(...times), t1 = Math.max(...times);
    if (t1 - t0 < 86400000 * 30) { t0 -= 86400000 * 15; t1 += 86400000 * 15; }
    const amounts = shown.map(t => t.amount);
    // 눈금: 5천만·1억·2억·5억 단위 중 4~6칸이 되는 값
    const lo = Math.min(...amounts), hi = Math.max(...amounts);
    const step = [1000, 2500, 5000, 10000, 20000, 50000, 100000].find(s => (hi - lo) / s <= 5) || 100000;
    const y0 = Math.floor(lo / step) * step, y1 = Math.max(Math.ceil(hi / step) * step, y0 + step);
    const x = t => L + (t - t0) / (t1 - t0) * (W - L - R);
    const y = a => T + (y1 - a) / (y1 - y0) * (H - T - B);
    const ticks = [];
    for (let v = y0; v <= y1; v += step) ticks.push(v);
    // 월 평균을 이은 추이선 (거래가 한 달에 여러 건이어도 한 점)
    const months = {};
    shown.forEach(t => { (months[t.date.slice(0, 7)] = months[t.date.slice(0, 7)] || []).push(t); });
    const trend = Object.keys(months).sort().map(m => {
        const list = months[m];
        return `${x(list.reduce((s, t) => s + time(t.date), 0) / list.length).toFixed(1)},${y(list.reduce((s, t) => s + t.amount, 0) / list.length).toFixed(1)}`;
    });
    // 아래 날짜: 처음·가운데·끝
    const xLabels = [t0, (t0 + t1) / 2, t1].map(t => { const d = new Date(t); return { t, text: `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}` }; });
    const latest = shown[0];
    const ordered = shown.slice().reverse();
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="거래가 추이 그래프. 점 하나가 거래 한 건, 선은 월 평균. 아래 표에 같은 내용이 있습니다.">
        ${ticks.map(v => `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="axis-text" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${money(v)}</text>`).join('')}
        ${xLabels.map((l, i) => `<text class="axis-text" x="${x(l.t)}" y="${H - 6}" text-anchor="${['start', 'middle', 'end'][i]}">${l.text}</text>`).join('')}
        ${trend.length > 1 ? `<polyline class="trend" points="${trend.join(' ')}"/>` : ''}
        ${ordered.map((t, i) => `<circle class="dot${t === latest ? ' is-latest' : ''}" data-i="${i}" cx="${x(time(t.date)).toFixed(1)}" cy="${y(t.amount).toFixed(1)}" r="${t === latest ? 5.5 : 4}"/>`).join('')}
        ${ordered.map((t, i) => `<circle class="hit" data-i="${i}" cx="${x(time(t.date)).toFixed(1)}" cy="${y(t.amount).toFixed(1)}" r="12" tabindex="0" role="img" aria-label="${t.date} ${Math.round(t.area)}㎡ ${t.floor}층 ${money(t.amount)}"/>`).join('')}
    </svg>`;
    el.querySelectorAll('.hit').forEach(hit => {
        const trade = ordered[Number(hit.dataset.i)];
        const dot = el.querySelector(`.dot[data-i="${hit.dataset.i}"]`);
        const show = () => {
            const tip = $('tip');
            tip.innerHTML = `${trade.date} · ${Math.round(trade.area)}㎡ ${trade.floor}층 · <b>${money(trade.amount)}</b>`;
            tip.hidden = false;
            const r = dot.getBoundingClientRect();
            tip.style.left = Math.min(Math.max(8, r.left + r.width / 2 - tip.offsetWidth / 2), window.innerWidth - tip.offsetWidth - 8) + 'px';
            tip.style.top = Math.max(8, r.top - tip.offsetHeight - 8) + 'px';
            dot.classList.add('is-active');
        };
        const hide = () => { $('tip').hidden = true; dot.classList.remove('is-active'); };
        hit.addEventListener('pointerenter', show);
        hit.addEventListener('pointerleave', hide);
        hit.addEventListener('focus', show);
        hit.addEventListener('blur', hide);
        hit.addEventListener('click', show);
    });
}
window.addEventListener('scroll', () => { $('tip').hidden = true; }, { passive: true });

function renderDetail() {
    const d = view.detail;
    const trades = detailTrades();
    const valid = trades.filter(t => !t.canceled);
    const latest = valid[0], prev = valid[1];
    const peak = valid.reduce((best, t) => (!best || t.amount > best.amount ? t : best), null);
    const low = valid.reduce((best, t) => (!best || t.amount < best.amount ? t : best), null);
    const yearAgo = new Date(); yearAgo.setFullYear(yearAgo.getFullYear() - 1);
    const lastYear = valid.filter(t => t.date >= yearAgo.toISOString().slice(0, 10));
    const areaChips = [{ area: null, count: d.trades.length }, ...d.areas].map(a => `
        <button type="button" class="chip" data-area="${a.area == null ? '' : a.area}" aria-pressed="${a.area === view.area}">${a.area == null ? '모든 면적' : a.area + '㎡'}<small>${a.count}</small></button>`).join('');
    $('page-title').textContent = d.name;
    $('detail-view').innerHTML = `
        <section class="panel">
            <div class="chips" role="group" aria-label="전용면적">${areaChips}</div>
            ${latest ? `
            <div class="headline" style="margin-top:14px">
                <span class="big">${money(latest.amount)}</span>
                ${prev ? deltaHtml(latest.amount - prev.amount, ' (직전 거래 대비)') : ''}
            </div>
            <div class="headline-sub">${Math.round(latest.area)}㎡ · ${latest.floor}층 · ${latest.date} 계약${latest.dealing ? ' · ' + esc(latest.dealing) : ''}${d.umd ? ' · ' + esc(d.umd) : ''}${d.build_year ? ` · ${d.build_year}년 준공` : ''}</div>
            <div class="tiles">
                <div class="tile"><span class="tile-label">최고가</span><span class="tile-value">${money(peak.amount)}</span><span class="tile-note">${peak.date} · ${peak.floor}층</span></div>
                <div class="tile"><span class="tile-label">최저가</span><span class="tile-value">${money(low.amount)}</span><span class="tile-note">${low.date} · ${low.floor}층</span></div>
                <div class="tile"><span class="tile-label">최근 1년 거래</span><span class="tile-value">${lastYear.length}건</span><span class="tile-note">${lastYear.length ? '평균 ' + money(Math.round(lastYear.reduce((s, t) => s + t.amount, 0) / lastYear.length)) : '거래 없음'}</span></div>
            </div>` : `<div class="empty">${d.synced ? '이 면적의 거래가 없습니다.' : '지난 거래를 받아 오는 중입니다. 잠시 뒤 다시 열어 주세요.'}</div>`}
        </section>
        ${latest ? `<section class="panel">
            <div class="panel-head"><h2>거래가 추이</h2>
                <div class="seg" role="group" aria-label="기간">${PERIODS.map(p => `<button type="button" class="seg-btn" data-months="${p.months}" aria-pressed="${p.months === view.months}">${p.label}</button>`).join('')}</div>
            </div>
            <div class="chart" id="chart"></div>
            <div class="chart-legend"><span><i></i>거래 한 건</span><span><i class="is-latest"></i>가장 최근 거래</span><span><i class="is-line"></i>월 평균</span></div>
        </section>` : ''}
        <section class="panel">
            <div class="panel-head"><h2>거래 목록</h2><span class="status">${trades.length}건</span></div>
            ${trades.length ? `<div class="table-wrap"><table>
                <thead><tr><th>계약일</th><th class="num">면적</th><th class="num">층</th><th class="num">거래 금액</th><th></th></tr></thead>
                <tbody>${trades.map(t => `<tr class="${t.canceled ? 'is-canceled' : ''}">
                    <td>${t.date}</td><td class="num">${t.area}㎡</td><td class="num">${t.floor}</td><td class="num amount">${money(t.amount)}</td>
                    <td class="note">${t.canceled ? '계약 해제' : t.is_new ? '<span class="new-tag">새 거래</span>' : esc(t.dealing === '직거래' ? '직거래' : '')}</td></tr>`).join('')}</tbody>
            </table></div>` : '<div class="empty">거래가 없습니다.</div>'}
        </section>`;
    if (latest) drawChart(trades);
}

async function openDetail(id) {
    $('list-view').hidden = true;
    $('manage-view').hidden = true;
    $('manage-btn').hidden = true;
    $('detail-view').hidden = false;
    $('detail-view').innerHTML = '<section class="panel"><div class="skeleton"></div></section>';
    $('back-link').setAttribute('href', '#');
    try {
        view.detail = await getJSON('/api/apt/detail?id=' + id);
    } catch (e) {
        $('detail-view').innerHTML = '<section class="panel"><div class="empty">단지를 찾을 수 없습니다.</div></section>';
        return;
    }
    // 관심 면적으로 시작 (그 면적 거래가 없으면 모든 면적)
    view.area = view.detail.areas.some(a => a.area === view.detail.area) ? view.detail.area : null;
    renderDetail();
    window.scrollTo({ top: 0 });
}

function openList() {
    view.detail = null;
    $('page-title').textContent = '아파트 실거래가';
    $('detail-view').hidden = true;
    $('list-view').hidden = false;
    $('manage-btn').hidden = false;
    $('manage-view').hidden = !view.managing;
    $('back-link').setAttribute('href', '/');
    $('tip').hidden = true;
}

function route() {
    const match = /^#w-(\d+)$/.exec(location.hash);
    if (match) openDetail(match[1]);
    else openList();
}

// ---------- 관리 ----------
function renderManage() {
    const loggedIn = !!token();
    $('login-box').hidden = loggedIn;
    $('manage-box').hidden = !loggedIn;
    if (!loggedIn || !view.data) return;
    $('watch-manage').innerHTML = view.data.watches.length ? view.data.watches.map(w => `
        <div class="manage-row">
            <span class="manage-name">${esc(w.name)}<small>${areaLabel(w.area)} · ${esc(w.umd)} · ${w.lawd_cd}</small></span>
            <label class="check"><input type="checkbox" data-alert="${w.id}" ${w.alert ? 'checked' : ''}> 새 거래 알림</label>
            <button type="button" class="btn-text" data-delete="${w.id}" data-name="${esc(w.name)}">삭제</button>
        </div>`).join('') : '<div class="empty">등록한 단지가 없습니다.</div>';
    $('search-results').innerHTML = view.results.map((r, i) => `
        <div class="result">
            <div class="result-name">${esc(r.name)}</div>
            <div class="result-meta">${esc(r.umd)}${r.build_year ? ` · ${r.build_year}년 준공` : ''} · 최근 1년 거래 ${r.count}건 · 최근 ${money(r.last_amount)} (${r.last_date})</div>
            <div class="chips">${r.areas.map(a => `<button type="button" class="chip" data-add="${i}" data-area="${a}">${a}㎡ 등록</button>`).join('')}
                <button type="button" class="chip" data-add="${i}" data-area="">모든 면적 등록</button></div>
        </div>`).join('');
}

async function load() {
    try {
        view.data = await getJSON('/api/apt');
    } catch (e) {
        $('list-view').innerHTML = '<div class="empty">실거래가를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</div>';
        return;
    }
    renderStatus();
    renderList();
    renderManage();
}

$('list-view').addEventListener('click', e => {
    const row = e.target.closest('[data-watch]');
    if (row) location.hash = 'w-' + row.dataset.watch;
});
$('detail-view').addEventListener('click', e => {
    const chip = e.target.closest('[data-area]');
    const seg = e.target.closest('[data-months]');
    if (chip) { view.area = chip.dataset.area === '' ? null : Number(chip.dataset.area); renderDetail(); }
    else if (seg) { view.months = Number(seg.dataset.months); renderDetail(); }
});
$('manage-btn').addEventListener('click', () => {
    view.managing = !view.managing;
    $('manage-btn').setAttribute('aria-pressed', String(view.managing));
    $('manage-view').hidden = !view.managing;
    renderManage();
});
$('login-form').addEventListener('submit', async e => {
    e.preventDefault();
    $('login-msg').textContent = '';
    try {
        const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                body: JSON.stringify({ password: $('login-pwd').value }) });
        const data = await res.json();
        if (!data.success) throw new Error(data.message || '로그인하지 못했습니다.');
        setToken(data.token);
        $('login-pwd').value = '';
        renderManage();
    } catch (err) {
        $('login-msg').textContent = err.message || '로그인하지 못했습니다.';
    }
});
// ---------- 지역 고르기: 시·군·구 이름(띄어쓰기·'시도' 이름도 함께 찾음) 또는 코드 5자리 ----------
const REGION_LIMIT = 30;
const squash = s => String(s || '').replace(/\s+/g, '').toLowerCase();
const regionLabel = r => [r[1], r[2]].filter(Boolean).join(' ');
function matchRegions(text) {
    const q = squash(text);
    if (!q) return [];
    if (/^\d{5}$/.test(q)) {
        const known = APT_REGIONS.find(r => r[0] === q);
        return [known || [q, '지역 코드', q]];
    }
    // 낱말마다 들어 있어야 함 (예: '수원 영통' → 수원시 영통구). 시·군·구 이름이 낱말로 시작하면 앞에
    const words = text.trim().split(/\s+/).map(squash);
    return APT_REGIONS
        .filter(r => words.every(w => squash(r[1] + r[2]).includes(w)))
        .sort((a, b) => Number(!squash(a[2]).startsWith(words[0])) - Number(!squash(b[2]).startsWith(words[0])))
        .slice(0, REGION_LIMIT);
}
let regionMatches = [], regionActive = -1;
function renderRegionList() {
    const list = $('region-list'), input = $('region-input');
    const open = regionMatches.length > 0 || squash(input.value).length > 0;
    list.hidden = !open || input.classList.contains('is-picked');
    input.setAttribute('aria-expanded', String(!list.hidden));
    document.querySelector('.apt').classList.toggle('is-picking', !list.hidden);
    list.innerHTML = regionMatches.length ? regionMatches.map((r, i) => `
        <button type="button" class="combo-option${i === regionActive ? ' is-active' : ''}" role="option" data-region="${i}" aria-selected="${i === regionActive}">
            <span>${esc(regionLabel(r))}</span><small>${r[0]}</small></button>`).join('')
        : '<div class="combo-empty">맞는 지역이 없습니다. 시·군·구 이름이나 코드 5자리를 넣어 주세요.</div>';
    placeRegionList();
}
// 목록이 화면 아래로 잘리지 않게: 지역 칸이 화면 아래쪽에 있으면 칸을 화면 위쪽으로 올리고,
// 목록 높이는 실제로 보이는 높이(휴대폰은 키보드를 뺀 높이)에 맞춤. 아래 자리가 너무 좁으면 위로 펼침
const LIST_GAP = 8, LIST_MIN = 160, LIST_MAX = 320;
function visibleHeight() { return window.visualViewport ? window.visualViewport.height : window.innerHeight; }
function placeRegionList() {
    const list = $('region-list'), input = $('region-input');
    if (list.hidden) return;
    let rect = input.getBoundingClientRect();
    if (visibleHeight() - rect.bottom - LIST_GAP < LIST_MIN + 40) {
        window.scrollBy({ top: rect.top - 72 });
        rect = input.getBoundingClientRect();
    }
    const below = visibleHeight() - rect.bottom - LIST_GAP * 2;
    const above = rect.top - LIST_GAP * 2;
    const up = below < LIST_MIN && above > below;
    list.classList.toggle('is-up', up);
    list.style.maxHeight = Math.max(120, Math.min(LIST_MAX, up ? above : below)) + 'px';
}
if (window.visualViewport) window.visualViewport.addEventListener('resize', () => placeRegionList());
window.addEventListener('resize', () => placeRegionList());
async function pickRegion(region) {
    const input = $('region-input');
    view.region = { code: region[0], label: regionLabel(region) };
    input.value = view.region.label;
    input.classList.add('is-picked');
    regionMatches = [];
    renderRegionList();
    view.results = [];
    view.complexes = [];
    $('complex-filter').value = '';
    $('complex-box').hidden = false;
    $('complex-select').innerHTML = '<option>단지 목록을 불러오는 중… (처음엔 10초쯤 걸려요)</option>';
    $('complex-select').disabled = true;
    $('search-msg').textContent = '';
    renderManage();
    const code = view.region.code;
    try {
        const data = await postApt({ action: 'complexes', lawd_cd: code });
        if (!view.region || view.region.code !== code) return;   // 그 사이 다른 지역을 고름
        if (!data.success) throw new Error(data.message);
        view.complexes = data.results.map(r => ({ ...r, lawd_cd: code }));
        if (!view.complexes.length) $('search-msg').textContent = '이 지역에서 최근 1년 동안 거래된 아파트가 없습니다.';
    } catch (err) {
        $('search-msg').textContent = err.message || '단지 목록을 받아 오지 못했습니다. 잠시 후 다시 시도해 주세요.';
    }
    renderComplexSelect();
}
function renderComplexSelect() {
    const q = squash($('complex-filter').value);
    const shown = view.complexes.filter(c => !q || squash(c.name + c.umd).includes(q));
    const select = $('complex-select');
    select.disabled = !view.complexes.length;
    const picked = view.results[0];
    select.innerHTML = `<option value="">${view.complexes.length ? `단지 고르기 (${shown.length}곳)` : '단지 없음'}</option>`
        + shown.map(c => `<option value="${esc(c.apt_seq)}" ${picked && picked.apt_seq === c.apt_seq ? 'selected' : ''}>${esc(c.name)} · ${esc(c.umd)} (1년 ${c.count}건)</option>`).join('');
    // 거른 결과가 하나뿐이면 바로 고름
    if (q && shown.length === 1 && (!picked || picked.apt_seq !== shown[0].apt_seq)) {
        select.value = shown[0].apt_seq;
        pickComplex(shown[0].apt_seq);
    }
}
function pickComplex(seq) {
    const c = view.complexes.find(x => x.apt_seq === seq);
    view.results = c ? [c] : [];
    renderManage();
}
$('region-input').addEventListener('input', e => {
    e.target.classList.remove('is-picked');
    view.region = null;
    $('complex-box').hidden = true;
    view.results = [];
    regionMatches = matchRegions(e.target.value);
    regionActive = regionMatches.length ? 0 : -1;
    renderRegionList();
    renderManage();
});
$('region-input').addEventListener('focus', e => {
    if (!e.target.classList.contains('is-picked')) { regionMatches = matchRegions(e.target.value); renderRegionList(); }
    else e.target.select();
});
$('region-input').addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeRegionList(); return; }
    if (!regionMatches.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        regionActive = (regionActive + (e.key === 'ArrowDown' ? 1 : -1) + regionMatches.length) % regionMatches.length;
        renderRegionList();
        $('region-list').querySelector('.is-active')?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
        e.preventDefault();
        pickRegion(regionMatches[Math.max(0, regionActive)]);
    } else if (e.key === 'Escape') {
        closeRegionList();
    }
});
// 목록을 누르는 동안 입력칸이 포커스를 잃어 목록이 먼저 닫히지 않게 mousedown에서 고름
$('region-list').addEventListener('mousedown', e => {
    const opt = e.target.closest('[data-region]');
    if (!opt) return;
    e.preventDefault();
    pickRegion(regionMatches[Number(opt.dataset.region)]);
});
function closeRegionList() {
    $('region-list').hidden = true;
    $('region-input').setAttribute('aria-expanded', 'false');
    document.querySelector('.apt').classList.remove('is-picking');
}
$('region-input').addEventListener('blur', () => setTimeout(closeRegionList, 150));
$('complex-filter').addEventListener('input', renderComplexSelect);
$('complex-select').addEventListener('change', e => pickComplex(e.target.value));
$('manage-view').addEventListener('click', async e => {
    const add = e.target.closest('[data-add]');
    const del = e.target.closest('[data-delete]');
    if (add) {
        const r = view.results[Number(add.dataset.add)];
        const data = await postApt({ action: 'add', lawd_cd: r.lawd_cd, apt_seq: r.apt_seq, name: r.name, umd: r.umd,
                                     area: add.dataset.area === '' ? null : Number(add.dataset.area) });
        $('search-msg').textContent = data.success ? '' : data.message || '등록하지 못했습니다.';
        if (data.success) {
            view.results = [];
            $('complex-select').value = '';
            await load();
            setTimeout(load, 8000);
        }
    } else if (del) {
        if (!window.confirm(`'${del.dataset.name}'을(를) 삭제할까요? 모아 둔 거래도 함께 지워집니다.`)) return;
        const data = await postApt({ action: 'delete', id: Number(del.dataset.delete) });
        if (!data.success && data.message) window.alert(data.message);
        await load();
    }
});
$('manage-view').addEventListener('change', async e => {
    if (!e.target.dataset.alert) return;
    const data = await postApt({ action: 'alert', id: Number(e.target.dataset.alert), enabled: e.target.checked });
    if (!data.success) e.target.checked = !e.target.checked;
});
window.addEventListener('hashchange', route);
let resizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (view.detail && $('chart')) drawChart(detailTrades()); }, 150);
});

load().then(route);
