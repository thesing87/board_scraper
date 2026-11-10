// 수집 통계 화면: 최근 7·30·90일 동안 수집한 글 수를 날짜·게시판·키워드·시간대별로 (/api/stats)
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = n => Number(n).toLocaleString('ko-KR');
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];
const DAYS_KEY = 'stats_days';

const view = { days: 30, group: '', stats: null };
try {
    const saved = Number(localStorage.getItem(DAYS_KEY));
    if ([7, 30, 90].includes(saved)) view.days = saved;
} catch (e) { /* 저장소를 못 쓰면 기본값 */ }

function dateParts(iso) {
    const d = new Date(iso + 'T00:00:00');
    return { month: d.getMonth() + 1, day: d.getDate(), weekday: d.getDay() };
}
function dateLabel(iso) {
    const p = dateParts(iso);
    return `${p.month}월 ${p.day}일 (${WEEKDAYS[p.weekday]})`;
}

// 눈금 맨 위 값: 최댓값보다 조금 큰 1·2·5 × 10ⁿ 꼴의 4칸 눈금
function axisTop(max) {
    if (max <= 4) return 4;
    const step = max / 4;
    const pow = Math.pow(10, Math.floor(Math.log10(step)));
    const nice = [1, 2, 2.5, 5, 10].find(m => m * pow >= step) * pow;
    return Math.ceil(nice) * 4;
}

// 세로 막대 그림. items: [{label(아래 글자, 빈 값이면 생략), value, tip(HTML), soft(연한 색)}]
function barChart(el, items, legend) {
    const max = Math.max(0, ...items.map(i => i.value));
    if (!max) {
        el.innerHTML = '<div class="chart-empty">이 기간에 수집한 글이 없습니다</div>';
        return;
    }
    const top = axisTop(max);
    const ticks = [0, 1, 2, 3, 4].map(i => top / 4 * i);
    el.innerHTML = `
        <div class="chart-y" aria-hidden="true">${ticks.map(t => `<span style="bottom:${t / top * 100}%">${num(t)}</span>`).join('')}</div>
        <div class="chart-plot">
            ${ticks.map(t => `<div class="chart-grid${t ? '' : ' is-base'}" style="bottom:${t / top * 100}%"></div>`).join('')}
            <div class="chart-cols">
                ${items.map((item, i) => `<div class="chart-col${item.soft ? ' is-weekend' : ''}" data-i="${i}" tabindex="0" role="img" aria-label="${esc(item.aria)}">
                    <i style="height:${item.value ? Math.max(item.value / top * 100, 1.5) : 0}%"></i></div>`).join('')}
            </div>
        </div>
        <div class="chart-x" aria-hidden="true">${items.map(item => `<span>${esc(item.label || '')}</span>`).join('')}</div>
        ${legend || ''}`;
    el.querySelectorAll('.chart-col').forEach(col => {
        const item = items[Number(col.dataset.i)];
        const show = () => showTip(col, item.tip);
        col.addEventListener('pointerenter', show);
        col.addEventListener('pointerleave', hideTip);
        col.addEventListener('focus', show);
        col.addEventListener('blur', hideTip);
        col.addEventListener('click', show);
    });
}

function showTip(target, html) {
    const tip = $('tip');
    tip.innerHTML = html;
    tip.hidden = false;
    const r = target.getBoundingClientRect();
    const bar = target.querySelector('i').getBoundingClientRect();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    const left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    tip.style.left = left + 'px';
    tip.style.top = Math.max(8, (bar.height ? bar.top : r.bottom) - h - 8) + 'px';
    document.querySelectorAll('.chart-col.is-active').forEach(c => c.classList.remove('is-active'));
    target.classList.add('is-active');
}
function hideTip() {
    $('tip').hidden = true;
    document.querySelectorAll('.chart-col.is-active').forEach(c => c.classList.remove('is-active'));
}
window.addEventListener('scroll', hideTip, { passive: true });

// 가로 막대 순위. rows: [{name, sub, value, id}], onPick이 있으면 누를 수 있는 줄
function rankList(el, rows, emptyText, pickable) {
    if (!rows.length) {
        el.innerHTML = `<div class="rank-empty">${emptyText}</div>`;
        return;
    }
    const max = Math.max(1, ...rows.map(r => r.value));
    el.innerHTML = rows.map(r => {
        const inner = `<span class="rank-name">${esc(r.name)}${r.sub ? `<small>${esc(r.sub)}</small>` : ''}</span>
            <span class="rank-bar" aria-hidden="true"><i style="width:${r.value / max * 100}%"></i></span>
            <span class="rank-value">${num(r.value)}</span>`;
        const zero = r.value ? '' : ' is-zero';
        return pickable
            ? `<button type="button" class="rank-row${zero}" data-group="${r.id}" aria-pressed="${String(r.id) === view.group}">${inner}</button>`
            : `<div class="rank-row${zero}">${inner}</div>`;
    }).join('');
}

function renderTiles(stats) {
    const busiest = stats.daily.reduce((best, d) => (d.count > best.count ? d : best), stats.daily[0]);
    const diff = stats.total - stats.previous;
    const change = !stats.previous ? '앞 기간 기록 없음'
        : diff === 0 ? `앞 ${stats.days}일과 같음`
        : `앞 ${stats.days}일보다 ${num(Math.abs(diff))}개 ${diff > 0 ? '많음' : '적음'} (${diff > 0 ? '+' : '−'}${Math.round(Math.abs(diff) / stats.previous * 100)}%)`;
    const average = stats.total / stats.days;
    $('tiles').innerHTML = `
        <div class="tile"><span class="tile-label">수집한 글</span>
            <span class="tile-value">${num(stats.total)}<small>개</small></span>
            <span class="tile-note${stats.previous && diff ? (diff > 0 ? ' is-up' : ' is-down') : ''}">${change}</span></div>
        <div class="tile"><span class="tile-label">하루 평균</span>
            <span class="tile-value">${average >= 10 ? num(Math.round(average)) : average.toFixed(1)}<small>개</small></span>
            <span class="tile-note">최근 ${stats.days}일</span></div>
        <div class="tile"><span class="tile-label">가장 많았던 날</span>
            <span class="tile-value">${busiest.count ? num(busiest.count) : '–'}<small>${busiest.count ? '개' : ''}</small></span>
            <span class="tile-note">${busiest.count ? dateLabel(busiest.date) : '수집한 글 없음'}</span></div>`;
}

function renderDaily(stats) {
    const count = stats.daily.length;
    // 아래 날짜는 칸이 좁으면 띄엄띄엄: 7일은 모두, 30일은 5일마다, 90일은 달의 1일·15일
    const label = (d, i) => {
        const p = dateParts(d.date);
        if (count <= 7) return `${p.month}/${p.day}`;
        if (count <= 31) return (count - 1 - i) % 5 === 0 ? `${p.month}/${p.day}` : '';
        return p.day === 1 || p.day === 15 ? `${p.month}/${p.day}` : '';
    };
    barChart($('daily-chart'), stats.daily.map((d, i) => {
        const weekend = [0, 6].includes(dateParts(d.date).weekday);
        return { label: label(d, i), value: d.count, soft: weekend, aria: `${dateLabel(d.date)} ${d.count}개`,
                 tip: `${dateLabel(d.date)} · <b>${num(d.count)}개</b>` };
    }), '<div class="chart-legend"><span><i></i>평일</span><span><i class="is-weekend"></i>주말</span></div>');
    $('daily-table').innerHTML = `<table><thead><tr><th>날짜</th><th>수집한 글</th></tr></thead><tbody>
        ${stats.daily.slice().reverse().map(d => `<tr><td>${dateLabel(d.date)}</td><td>${num(d.count)}</td></tr>`).join('')}
    </tbody></table>`;
}

function renderHours(stats) {
    const peak = stats.hours.indexOf(Math.max(...stats.hours));
    $('hours-note').textContent = stats.total ? `가장 많은 시간대: ${peak}시` : '';
    barChart($('hours-chart'), stats.hours.map((value, h) => ({
        label: h % 3 === 0 ? `${h}시` : '', value, aria: `${h}시 ${value}개`, tip: `${h}시~${h + 1}시 · <b>${num(value)}개</b>`
    })));
}

function render(stats) {
    view.stats = stats;
    // 게시판 고르기: 처음 한 번 채우고, 고른 값 유지
    const select = $('group-select');
    const options = stats.groups.slice().sort((a, b) => a.name.localeCompare(b.name, 'ko'));
    select.innerHTML = '<option value="">모든 게시판</option>'
        + options.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join('');
    select.value = view.group;
    if (select.value !== view.group) { view.group = ''; select.value = ''; }
    document.querySelectorAll('.seg-btn').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.days) === view.days)));

    renderTiles(stats);
    renderDaily(stats);
    rankList($('groups-rank'), stats.groups.map(g => ({ id: g.id, name: g.name, value: g.count })), '게시판이 없습니다', true);
    rankList($('keywords-rank'), stats.keywords.map(k => ({ name: k.keyword, sub: k.board_name, value: k.count })), '이 기간에 수집한 글이 없습니다');
    renderHours(stats);
}

let requestSeq = 0;
async function load() {
    const seq = ++requestSeq;
    const params = new URLSearchParams({ days: view.days });
    if (view.group) params.set('group', view.group);
    try {
        const res = await fetch('/api/stats?' + params.toString(), { headers: { 'Accept': 'application/json' } });
        if (!res.ok) throw new Error(res.status);
        const stats = await res.json();
        if (seq === requestSeq) render(stats);
    } catch (e) {
        if (seq !== requestSeq) return;
        $('tiles').innerHTML = '';
        $('daily-chart').innerHTML = '<div class="chart-empty">통계를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</div>';
    }
}

document.querySelectorAll('.seg-btn').forEach(button => button.addEventListener('click', () => {
    view.days = Number(button.dataset.days);
    try { localStorage.setItem(DAYS_KEY, String(view.days)); } catch (e) { /* 저장 불가: 이번 화면에서만 */ }
    load();
}));
$('group-select').addEventListener('change', e => { view.group = e.target.value; load(); });
// 게시판별 순위의 줄을 누르면 그 게시판만 (다시 누르면 모든 게시판)
$('groups-rank').addEventListener('click', e => {
    const row = e.target.closest('.rank-row[data-group]');
    if (!row) return;
    view.group = view.group === row.dataset.group ? '' : row.dataset.group;
    load();
});
$('table-toggle').addEventListener('click', () => {
    const table = $('daily-table');
    table.hidden = !table.hidden;
    $('table-toggle').setAttribute('aria-expanded', String(!table.hidden));
    $('table-toggle').textContent = table.hidden ? '표로 보기' : '표 닫기';
});

load();
