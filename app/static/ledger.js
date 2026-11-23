// 가계부: 관리자가 허락한 사람끼리 지출을 함께 기록하고 보기 (서버 ledger.py, API /api/ledger/*)
// - 로그인: 이름·비밀번호 → 가계부 API에만 쓰는 쿠키. 관리자 기기(대시보드 로그인 키가 있는 기기)는 자동으로 관리자 로그인
// - 기록은 그 달 것을 받아 일별·사람별 거르기는 화면에서. 내가 쓴 기록(관리자는 모두)을 누르면 고치기
// - 소비형태는 모두 함께 쓰고 색은 직접 고름 (정해진 12색 또는 원하는 색)
'use strict';

(function () {
    const $ = id => document.getElementById(id);
    const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const storageGet = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } };
    const storageSet = (k, v) => { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (e) { /* 저장 불가 */ } };
    // 메뉴(nav.js)가 이 기기에서 가계부를 보이게 하는 표시
    const LEDGER_FLAG = 'ledger_user';
    const ADMIN_TOKEN_KEY = 'admin_token';
    const PRESET = ['#E24B4A', '#D85A30', '#EF9F27', '#C9B11A', '#639922', '#1D9E75', '#2BA7B8', '#378ADD', '#534AB7', '#9B5DE5', '#D4537E', '#888780'];
    // 사람마다 동그라미 색 (함께 쓰는 순서대로)
    const AVATAR = [['#EEEDFE', '#3C3489'], ['#E1F5EE', '#085041'], ['#FAEEDA', '#633806'], ['#E6F1FB', '#0C447C'], ['#FBEAF0', '#72243E'], ['#EAF3DE', '#27500A'], ['#FAECE7', '#712B13']];

    const won = n => `${Math.round(n).toLocaleString('ko-KR')}원`;
    const pad = n => String(n).padStart(2, '0');
    const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const ym = d => ymd(d).slice(0, 7);
    function mix(hex, toWhite, f) {
        const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
        const t = toWhite ? 255 : 0;
        return '#' + c.map(v => Math.round(v + (t - v) * f).toString(16).padStart(2, '0')).join('');
    }
    const chipBg = h => mix(h, true, 0.84), chipFg = h => mix(h, false, 0.45);

    const st = {
        me: null, data: null, mode: 'month', day: new Date(), who: 0,
        // kind: 입력 중인 쪽(expense·income), sels: 쪽마다 고른 분류, type: 기록 거르기(all·expense·income), ana: 분석할 쪽
        kind: 'expense', sels: { expense: null, income: null }, type: 'all', ana: 'expense',
        // 합계 구역: totView(day: 이 달 달력·month: 올해 달마다), year·yearData(서버의 올해 합계)
        totView: 'day', year: new Date().getFullYear(), yearData: null,
        // 자동 기록: 확인 대기함·가게 규칙·내 연결 상태, 대기함에서 고치는 중인 알림
        inbox: [], rules: [], hook: null, hookBase: '', editItem: null,
        catEditing: false, popFor: null, addColor: null, editId: null, ddIndex: -1,
    };

    // ==========================================
    // 서버
    // ==========================================
    async function get(url) {
        const res = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        let data = {};
        try { data = await res.json(); } catch (e) { /* 본문 없음 */ }
        return { status: res.status, data };
    }
    async function post(url, body) {
        const res = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        let data = {};
        try { data = await res.json(); } catch (e) { /* 본문 없음 */ }
        return { status: res.status, data };
    }
    const msgOf = d => String((d && d.message) || '처리하지 못했어요.').replace(/^❌\s*/, '');

    // ==========================================
    // 로그인
    // ==========================================
    function showAuth(tab) {
        st.me = null;
        storageSet(LEDGER_FLAG, '');
        $('app').hidden = true;
        $('who-me').hidden = $('logout').hidden = true;
        $('auth').hidden = false;
        setTab(tab || 'login');
    }
    function setTab(tab) {
        $('tab-login').setAttribute('aria-selected', String(tab === 'login'));
        $('tab-signup').setAttribute('aria-selected', String(tab === 'signup'));
        $('login-form').hidden = tab !== 'login';
        $('signup-form').hidden = tab !== 'signup';
        setAuthMsg('');
    }
    function setAuthMsg(text, ok) { $('auth-msg').textContent = text; $('auth-msg').classList.toggle('ok', !!ok); }
    $('tab-login').addEventListener('click', () => setTab('login'));
    $('tab-signup').addEventListener('click', () => setTab('signup'));

    $('login-form').addEventListener('submit', async e => {
        e.preventDefault();
        const name = $('login-name').value.trim(), password = $('login-pw').value;
        if (!name || !password) { setAuthMsg('이름과 비밀번호를 넣어 주세요.'); return; }
        const { status, data } = await post('/api/ledger/session', { action: 'login', name, password });
        if (status !== 200) { setAuthMsg(msgOf(data)); return; }
        $('login-pw').value = '';
        start(data.user);
    });
    $('signup-form').addEventListener('submit', async e => {
        e.preventDefault();
        const name = $('su-name').value.trim(), pw = $('su-pw').value, pw2 = $('su-pw2').value;
        if (!name) { setAuthMsg('이름을 넣어 주세요.'); return; }
        if (pw.length < 4) { setAuthMsg('비밀번호는 4자 이상으로 넣어 주세요.'); return; }
        if (pw !== pw2) { setAuthMsg('비밀번호 확인이 다릅니다.'); return; }
        const { status, data } = await post('/api/ledger/session', { action: 'signup', name, password: pw });
        if (status !== 200) { setAuthMsg(msgOf(data)); return; }
        $('su-pw').value = $('su-pw2').value = '';
        $('login-name').value = name;
        setTab('login');
        setAuthMsg('가입 요청을 보냈어요. 관리자가 허락하면 로그인할 수 있어요.', true);
    });
    $('logout').addEventListener('click', async () => {
        await post('/api/ledger/session', { action: 'logout' });
        showAuth('login');
    });

    // ==========================================
    // 시작
    // ==========================================
    function start(user) {
        st.me = user;
        storageSet(LEDGER_FLAG, user.name);
        $('auth').hidden = true;
        $('app').hidden = false;
        const av = avatarOf(user.id, user.name);
        $('who-me').innerHTML = `${av}<span>${esc(user.name)}</span>`;
        $('who-me').hidden = $('logout').hidden = false;
        $('used-on').value = ymd(new Date());
        $('admin').hidden = !user.admin;
        if (user.admin) loadPeople();
        load();
        loadInbox();
        // 앱 안이면 로그인됐다고 알림 (연결 전에도 로그인으로 새 버전을 확인)
        try { if (window.LedgerApp && window.LedgerApp.loggedIn) window.LedgerApp.loggedIn(); } catch (e) { /* 예전 앱 */ }
    }

    async function boot() {
        let { status, data } = await get('/api/ledger/me');
        if (status === 200) { start(data.user); return; }
        // 관리자 기기: 대시보드 로그인 키로 관리자 로그인
        const token = storageGet(ADMIN_TOKEN_KEY, '');
        if (token) {
            ({ status, data } = await post('/api/ledger/session', { action: 'login', password: token }));
            if (status === 200) { start(data.user); return; }
        }
        showAuth('login');
    }

    async function load() {
        const { status, data } = await get(`/api/ledger/state?month=${ym(st.day)}`);
        if (status === 401) { showAuth('login'); return; }
        if (status !== 200) { $('entry-msg').textContent = '불러오지 못했어요. 잠시 뒤 다시 해 주세요.'; return; }
        st.data = data;
        if (st.totView === 'month') loadYear();
        renderAuto();
        for (const kind of ['expense', 'income']) {
            const list = data.categories.filter(c => c.kind === kind);
            if (!list.some(c => c.id === st.sels[kind])) st.sels[kind] = list.length ? list[0].id : null;
        }
        render();
    }

    // ==========================================
    // 사람
    // ==========================================
    function memberIndex(id) {
        const list = (st.data && st.data.members) || [];
        const i = list.findIndex(m => m.id === id);
        return i < 0 ? id : i;
    }
    // 기록 칸의 사람 색: AVATAR와 같은 순서로 [칸 바탕(프로필 색보다 연하게), 왼쪽 띠, 글자, 둘째 줄 글자]
    const USER_TINT = [['#F7F6FF', '#AFA9EC', '#26215C', '#534AB7'], ['#F1FAF6', '#5DCAA5', '#04342C', '#0F6E56'], ['#FDF7EE', '#EF9F27', '#412402', '#854F0B'],
        ['#F3F8FD', '#85B7EB', '#042C53', '#185FA5'], ['#FDF5F8', '#ED93B1', '#4B1528', '#993556'], ['#F5F9EF', '#97C459', '#173404', '#3B6D11'],
        ['#FDF6F3', '#F0997B', '#4A1B0C', '#993C1D']];
    function userTint(id) {
        const [bg, band, ink, sub] = USER_TINT[memberIndex(id) % USER_TINT.length];
        return `--u-bg:${bg};--u-band:${band};--u-ink:${ink};--u-sub:${sub}`;
    }
    function avatarOf(id, name) {
        const [bg, fg] = AVATAR[memberIndex(id) % AVATAR.length];
        const letter = [...((name || '?').trim() || '?')][0];   // 이름 첫 글자 (이모지 등 두 칸짜리 글자도 한 글자로)
        return `<span class="av" style="background:${bg};color:${fg}">${esc(letter)}</span>`;
    }
    const selected = () => st.sels[st.kind];
    const kindCats = () => st.data.categories.filter(c => c.kind === st.kind);
    const kindOf = e => catOf(e.category_id).kind || 'expense';
    const nameOf = id => ((st.data.members.find(m => m.id === id) || {}).name || '알 수 없음');
    const catOf = id => (st.data.categories.find(c => c.id === id) || { name: '알 수 없음', color: '#888780' });

    // ==========================================
    // 화면 그리기
    // ==========================================
    function inPeriod(e) { return st.mode === 'day' ? e.used_on === ymd(st.day) : e.used_on.slice(0, 7) === ym(st.day); }
    // 기간·사람으로 거른 기록 (요약·분석은 이것으로), 기록 목록은 여기에 지출·수입 거르기까지
    function scoped() { return st.data.entries.filter(e => inPeriod(e) && (!st.who || e.user_id === st.who)); }
    function shown() { return scoped().filter(e => st.type === 'all' || kindOf(e) === st.type); }

    function render() {
        if (st.me) $('who-me').innerHTML = `${avatarOf(st.me.id, st.me.name)}<span>${esc(st.me.name)}</span>`;
        renderEntryHead();
        renderCats();
        renderFilter();
        renderSummary();
        renderTotals();
    }

    function renderEntryHead() {
        const editing = st.editId != null, income = st.kind === 'income';
        $('entry').classList.toggle('editing', editing);
        $('entry').classList.toggle('income', income);
        $('kind-expense').classList.toggle('on', !income);
        $('kind-income').classList.toggle('on', income);
        $('kind-expense').setAttribute('aria-checked', String(!income));
        $('kind-income').setAttribute('aria-checked', String(income));
        $('entry-title').textContent = editing ? '기록 고치기' : income ? '수입 입력' : '지출 입력';
        $('entry-note').textContent = editing ? '고친 뒤 저장을 누르세요' : `${st.me.name} 이름으로 기록돼요`;
        $('save').textContent = editing ? '저장' : '입력';
        $('edit-row').hidden = !editing;
    }

    function chipHtml(c, extra) {
        return `<span class="dot" style="background:${c.color}"></span>${esc(c.name)}${extra || ''}`;
    }
    function renderCats() {
        const cats = kindCats();
        const word = st.kind === 'income' ? '수입 종류' : '소비형태';
        $('cats').classList.toggle('editing', st.catEditing);
        $('cat-hint').textContent = st.catEditing ? `바꿀 ${word}를 누르세요` : `${word} — 누르면 선택, 없으면 추가`;
        $('cat-edit').textContent = st.catEditing ? '편집 끝' : '색·이름 편집';
        $('cats').innerHTML = cats.map(c => `<span class="chip${!st.catEditing && c.id === selected() ? ' on' : ''}" data-cat="${c.id}" role="button" tabindex="0"
                style="background:${chipBg(c.color)};color:${chipFg(c.color)}">${chipHtml(c)}${st.popFor === c.id ? popHtml(c) : ''}</span>`).join('')
            + (st.catEditing ? '' : '<span class="chip add" id="cat-add" role="button" tabindex="0">＋ 추가</span>');
    }
    function palHtml(current, attr) {
        const cur = (current || '').toUpperCase();
        return PRESET.map(h => `<button type="button" class="sw${cur === h ? ' on' : ''}" ${attr}="${h}" style="background:${h}" aria-label="${h}">${cur === h ? '✓' : ''}</button>`).join('');
    }
    function popHtml(c) {
        return `<div class="pop" data-pop>
            <input id="pop-name" value="${esc(c.name)}" maxlength="12" aria-label="소비형태 이름">
            <div class="pal">${palHtml(c.color, 'data-pop-color')}</div>
            <label class="custom"><input type="color" id="pop-custom" value="${c.color.toLowerCase()}"> 직접 고르기</label>
            <div class="pop-actions"><button type="button" class="primary" data-pop-save>완료</button><button type="button" class="danger" data-pop-delete>지우기</button></div>
            <p class="msg" id="pop-msg"></p></div>`;
    }

    function renderAddBox() {
        $('add-pal').innerHTML = palHtml(st.addColor, 'data-add-color');
        const name = $('new-name').value.trim() || '새 소비형태';
        const pv = $('new-preview');
        if (st.addColor) {
            pv.setAttribute('style', `background:${chipBg(st.addColor)};color:${chipFg(st.addColor)};cursor:default`);
            pv.innerHTML = chipHtml({ name, color: st.addColor });
        } else {
            pv.setAttribute('style', 'border:1px dashed #B6BBC4;color:#8B919C;cursor:default');
            pv.textContent = name;
        }
    }

    function renderFilter() {
        $('mode-day').classList.toggle('on', st.mode === 'day');
        $('mode-month').classList.toggle('on', st.mode === 'month');
        $('type-seg').querySelectorAll('[data-type]').forEach(b => b.classList.toggle('on', b.dataset.type === st.type));
        $('ana-seg').querySelectorAll('[data-ana]').forEach(b => b.classList.toggle('on', b.dataset.ana === st.ana));
        const d = st.day;
        // 기간 (해도 함께): 월별 '2026년 11월', 일별 '2026.11.23 (일)'
        $('period').textContent = st.mode === 'day'
            ? `${d.getFullYear()}.${d.getMonth() + 1}.${d.getDate()} (${'일월화수목금토'[d.getDay()]})`
            : `${d.getFullYear()}년 ${d.getMonth() + 1}월`;
        $('mode-btn').textContent = `${st.mode === 'day' ? '일별' : '월별'} ▾`;
        const members = st.data.members;
        if (st.who && !members.some(m => m.id === st.who)) st.who = 0;
        $('people').innerHTML = `<button type="button" class="pp all${!st.who ? ' on' : ''}" data-who="0">모두</button>`
            + members.map(m => `<button type="button" class="pp${st.who === m.id ? ' on' : ''}" data-who="${m.id}">${avatarOf(m.id, m.name)}${esc(m.name)}</button>`).join('');
        // '전체 ▾' 단추: 고른 사람·종류를 보여 주고, 거른 상태면 파랗게
        const picked = [st.who ? nameOf(st.who) : '', { expense: '지출만', income: '수입만' }[st.type] || ''].filter(Boolean);
        $('pick-btn').textContent = `${picked.length ? picked.join(' · ') : '전체'} ▾`;
        $('pick-btn').classList.toggle('on', picked.length > 0);
    }

    function renderSummary() {
        const scope = scoped(), list = shown();
        const sumOf = kind => scope.filter(e => kindOf(e) === kind).reduce((t, e) => t + e.amount, 0);
        const inSum = sumOf('income'), exSum = sumOf('expense'), left = inSum - exSum;
        const whoName = st.who ? nameOf(st.who) : '';
        const when = `${st.mode === 'day' ? '이날' : '이 달'}`;
        $('m-in-label').textContent = `${when} 수입${whoName ? ` · ${whoName}` : ''}`;
        $('m-ex-label').textContent = `${when} 지출${whoName ? ` · ${whoName}` : ''}`;
        $('m-in').textContent = `+${won(inSum)}`;
        $('m-ex').textContent = `−${won(exSum)}`;
        $('m-left').textContent = `${left < 0 ? '−' : ''}${won(Math.abs(left))}`;
        $('m-left').className = left < 0 ? 'minus' : left > 0 ? 'plus' : '';
        $('m2').textContent = `${list.length}건`;
        // 분석: 고른 쪽(지출·수입)의 분류별 합계
        const sums = new Map();
        scope.filter(e => kindOf(e) === st.ana).forEach(e => sums.set(e.category_id, (sums.get(e.category_id) || 0) + e.amount));
        const parts = [...sums.entries()].sort((a, b) => b[1] - a[1]);
        const total = parts.reduce((t, p) => t + p[1], 0);
        // 접힌 '분석 · 달력' 줄의 요약: 가장 많은 소비형태
        $('ana-note').textContent = parts.length ? `가장 많음: ${catOf(parts[0][0]).name} ${Math.round(parts[0][1] / total * 100)}%` : '';
        renderDonut(parts, total, whoName ? `${whoName} ${st.ana === 'income' ? '수입' : '지출'}` : st.ana === 'income' ? '수입' : '지출');
        $('legend').innerHTML = parts.length ? parts.map(([id, v]) => {
            const c = catOf(id), pct = Math.round(v / total * 100);
            return `<div class="lg"><div class="lg-top"><span class="dot" style="background:${c.color}"></span><span class="n">${esc(c.name)}</span>
                <span class="p">${pct}%</span><span class="w">${won(v)}</span></div><div class="lg-bar"><i style="width:${pct}%;background:${c.color}"></i></div></div>`;
        }).join('') : `<p class="empty">이 기간에는 ${st.ana === 'income' ? '수입' : '지출'} 기록이 없어요</p>`;
        renderList(list);
    }

    function renderDonut(parts, total, whoName) {
        const R = 70, r = 44, cx = 85, cy = 85;
        let svg = '';
        if (!total) svg = `<circle cx="85" cy="85" r="57" fill="none" stroke="#E5E7EB" stroke-width="26"/>`;
        else if (parts.length === 1) svg = `<circle cx="85" cy="85" r="57" fill="none" stroke="${catOf(parts[0][0]).color}" stroke-width="26"/>`;
        else {
            let a0 = -Math.PI / 2;
            const p = (g, rad) => [cx + rad * Math.cos(g), cy + rad * Math.sin(g)];
            parts.forEach(([id, v]) => {
                const a1 = a0 + v / total * Math.PI * 2, big = a1 - a0 > Math.PI ? 1 : 0;
                const [x1, y1] = p(a0, R), [x2, y2] = p(a1, R), [x3, y3] = p(a1, r), [x4, y4] = p(a0, r);
                svg += `<path d="M${x1} ${y1}A${R} ${R} 0 ${big} 1 ${x2} ${y2}L${x3} ${y3}A${r} ${r} 0 ${big} 0 ${x4} ${y4}Z" fill="${catOf(id).color}" stroke="#fff" stroke-width="2"><title>${esc(catOf(id).name)} ${won(v)}</title></path>`;
                a0 = a1;
            });
        }
        svg += `<text x="85" y="80" text-anchor="middle" font-size="12" fill="#5F6673">${esc(whoName || '모두')}</text>
            <text x="85" y="101" text-anchor="middle" font-size="15" font-weight="700" fill="#111827">${won(total)}</text>`;
        $('donut').innerHTML = svg;
    }

    const signed = n => `<span class="${n < 0 ? 'minus' : n > 0 ? 'plus' : ''}">${n < 0 ? '−' : n > 0 ? '+' : ''}${won(Math.abs(n))}</span>`;
    // 이름: 작은 사람 색 동그라미 첫 글자 + 이름 (기록 줄 아래쪽 작은 줄)
    function whoTag(id) {
        return `<span class="who-tag">${avatarOf(id, nameOf(id))}${esc(nameOf(id))}</span>`;
    }

    // ==========================================
    // 합계: 일별(이 달 달력)·월별(올해 달마다). 사람 거르기를 따름
    // ==========================================
    const shortWon = n => n >= 10000 ? `${(Math.round(n / 1000) / 10).toLocaleString('ko-KR')}만` : Math.round(n).toLocaleString('ko-KR');
    function renderTotals() {
        $('tot-seg').querySelectorAll('[data-tot]').forEach(b => b.classList.toggle('on', b.dataset.tot === st.totView));
        $('tot-day').hidden = st.totView !== 'day';
        $('tot-month').hidden = st.totView !== 'month';
        $('year-nav').hidden = st.totView !== 'month';
        if (st.totView === 'day') renderCalendar(); else renderYear();
    }
    function renderCalendar() {
        const y = st.day.getFullYear(), m = st.day.getMonth();
        const first = new Date(y, m, 1).getDay(), days = new Date(y, m + 1, 0).getDate();
        const sums = {};
        st.data.entries.filter(e => !st.who || e.user_id === st.who).forEach(e => {
            const s = sums[e.used_on] || (sums[e.used_on] = { in: 0, ex: 0 });
            s[kindOf(e) === 'income' ? 'in' : 'ex'] += e.amount;
        });
        const maxEx = Math.max(1, ...Object.values(sums).map(s => s.ex));
        const today = ymd(new Date()), selected = st.mode === 'day' ? ymd(st.day) : '';
        let html = '일월화수목금토'.split('').map((w, i) => `<span class="wk${i ? '' : ' sun'}">${w}</span>`).join('');
        for (let i = 0; i < first; i++) html += '<span class="dc blank"></span>';
        for (let d = 1; d <= days; d++) {
            const key = `${y}-${pad(m + 1)}-${pad(d)}`, s = sums[key] || { in: 0, ex: 0 };
            const cls = ['dc', s.in || s.ex ? '' : 'none', key === today ? 'today' : '', key === selected ? 'sel' : ''].filter(Boolean).join(' ');
            html += `<button type="button" class="${cls}" data-day="${key}" title="${m + 1}월 ${d}일${s.in ? ` 수입 ${won(s.in)}` : ''}${s.ex ? ` 지출 ${won(s.ex)}` : ''}">
                <span class="n">${d}</span>${s.in ? `<span class="v plus">+${shortWon(s.in)}</span>` : ''}${s.ex ? `<span class="v minus">−${shortWon(s.ex)}</span>` : ''}
                ${s.ex ? `<span class="heat" style="width:${Math.max(12, Math.round(s.ex / maxEx * 100))}%"></span>` : ''}</button>`;
        }
        $('cal').innerHTML = html;
    }
    async function loadYear() {
        const year = st.year;
        const { status, data } = await get(`/api/ledger/year?year=${year}`);
        if (status !== 200 || year !== st.year) return;
        st.yearData = data;
        if (st.totView === 'month') renderYear();
    }
    function renderYear() {
        $('y-label').textContent = `${st.year}년`;
        const yd = st.yearData && st.yearData.year === st.year ? st.yearData : null;
        const months = Array.from({ length: 12 }, () => ({ in: 0, ex: 0 }));
        if (yd) yd.totals.filter(t => !st.who || t.user_id === st.who).forEach(t => {
            months[+t.month.slice(5, 7) - 1][t.kind === 'income' ? 'in' : 'ex'] += t.total;
        });
        const yIn = months.reduce((s, x) => s + x.in, 0), yEx = months.reduce((s, x) => s + x.ex, 0);
        $('y-in-label').textContent = `${st.year === new Date().getFullYear() ? '올해' : `${st.year}년`} 수입${st.who ? ` · ${nameOf(st.who)}` : ''}`;
        $('y-in').textContent = `+${won(yIn)}`;
        $('y-ex').textContent = `−${won(yEx)}`;
        $('y-net').innerHTML = signed(yIn - yEx);
        const curM = st.day.getFullYear() === st.year ? st.day.getMonth() : -1;
        const max = Math.max(1, ...months.map(x => Math.max(x.in, x.ex)));
        const W = 360, H = 148, gw = W / 12;
        let svg = '';
        months.forEach((x, i) => {
            const gx = i * gw, hi = x.in / max * (H - 8), he = x.ex / max * (H - 8);
            if (i === curM) svg += `<rect x="${gx + 1}" y="0" width="${gw - 2}" height="${H + 4}" rx="4" fill="#FAEEDA"/>`;
            svg += `<g data-month="${i + 1}"><rect x="${gx}" y="0" width="${gw}" height="${H + 26}" fill="transparent"/>`
                + (x.in ? `<rect x="${gx + gw * 0.18}" y="${H - hi}" width="${gw * 0.3}" height="${hi}" rx="2" fill="#378ADD"><title>${i + 1}월 수입 ${won(x.in)}</title></rect>` : '')
                + (x.ex ? `<rect x="${gx + gw * 0.52}" y="${H - he}" width="${gw * 0.3}" height="${he}" rx="2" fill="#D85A30"><title>${i + 1}월 지출 ${won(x.ex)}</title></rect>` : '')
                + `<text x="${gx + gw / 2}" y="${H + 18}" text-anchor="middle" font-size="11" fill="${i === curM ? '#111827' : '#5F6673'}" font-weight="${i === curM ? 700 : 400}">${i + 1}월</text></g>`;
        });
        $('mbars').innerHTML = svg;
        let rows = '';
        months.forEach((x, i) => {
            if (!x.in && !x.ex) return;
            rows += `<tr class="row${i === curM ? ' cur' : ''}" data-month="${i + 1}"><td>${i + 1}월</td><td class="plus">+${won(x.in)}</td><td class="minus">−${won(x.ex)}</td><td>${signed(x.in - x.ex)}</td></tr>`;
        });
        rows += `<tr class="sum"><td>${st.year === new Date().getFullYear() ? '올해' : `${st.year}년`}</td><td class="plus">+${won(yIn)}</td><td class="minus">−${won(yEx)}</td><td>${signed(yIn - yEx)}</td></tr>`;
        $('mtable').innerHTML = yd ? rows : '<tr><td colspan="4" class="hint">불러오는 중</td></tr>';
    }
    $('tot-seg').addEventListener('click', e => {
        const b = e.target.closest('[data-tot]');
        if (!b || b.dataset.tot === st.totView) return;
        st.totView = b.dataset.tot;
        if (st.totView === 'month') { st.year = st.day.getFullYear(); loadYear(); }
        renderTotals();
    });
    $('y-prev').addEventListener('click', () => { st.year--; st.yearData = null; renderYear(); loadYear(); });
    $('y-next').addEventListener('click', () => { st.year++; st.yearData = null; renderYear(); loadYear(); });
    // 달력의 날짜: 그날 기록만 (다시 누르면 이 달 전체)
    $('cal').addEventListener('click', e => {
        const b = e.target.closest('[data-day]');
        if (!b) return;
        if (st.mode === 'day' && ymd(st.day) === b.dataset.day) { st.mode = 'month'; }
        else { st.mode = 'day'; const [y, m, d] = b.dataset.day.split('-').map(Number); st.day = new Date(y, m - 1, d); }
        render();
        $('list-fold').open = true;   // 그날 기록이 보이게
    });
    // 월별의 달: 그 달을 월별로 보고 합계는 그 달 달력으로
    function openMonth(month) {
        const before = ym(st.day);
        st.day = new Date(st.year, month - 1, 1);
        st.mode = 'month';
        st.totView = 'day';
        if (ym(st.day) !== before) load(); else render();
    }
    $('mbars').addEventListener('click', e => { const g = e.target.closest('[data-month]'); if (g) openMonth(Number(g.dataset.month)); });
    $('mtable').addEventListener('click', e => { const r = e.target.closest('[data-month]'); if (r) openMonth(Number(r.dataset.month)); });

    function canEdit(e) { return st.me && (st.me.admin || e.user_id === st.me.id); }
    function renderList(list) {
        if (!list.length) { $('count').textContent = '0건'; $('list').innerHTML = '<p class="empty">이 기간에는 기록이 없어요</p>'; return; }
        const days = [...new Set(list.map(e => e.used_on))];
        // 맨 위 합계 띠: 목록과 같은 거르기(기간·사람·종류)로 수입·지출·합계 ('지출만'·'수입만'이면 그쪽 칸만)
        const when = st.mode === 'day' ? `${st.day.getMonth() + 1}월 ${st.day.getDate()}일` : `${st.day.getMonth() + 1}월`;
        const sumIn = list.filter(e => kindOf(e) === 'income').reduce((t, e) => t + e.amount, 0);
        const sumEx = list.filter(e => kindOf(e) === 'expense').reduce((t, e) => t + e.amount, 0);
        const cells = [];
        if (st.type !== 'expense') cells.push(`<div>${when} 수입<b class="plus">+${won(sumIn)}</b></div>`);
        if (st.type !== 'income') cells.push(`<div>${when} 지출<b class="minus">−${won(sumEx)}</b></div>`);
        if (st.type === 'all') cells.push(`<div>합계<b class="${sumIn - sumEx < 0 ? 'minus' : sumIn - sumEx > 0 ? 'plus' : ''}">${signed(sumIn - sumEx)}</b></div>`);
        $('count').innerHTML = `${list.length}건 · ${signed(st.type === 'expense' ? -sumEx : sumIn - sumEx)}`;   // 접힌 줄에도 보이게
        const band = `<div class="list-sum" style="grid-template-columns:repeat(${cells.length}, minmax(0, 1fr))">${cells.join('')}</div>`;
        $('list').innerHTML = band + days.map(day => {
            const items = list.filter(e => e.used_on === day);
            const dayIn = items.filter(e => kindOf(e) === 'income').reduce((t, e) => t + e.amount, 0);
            const dayEx = items.filter(e => kindOf(e) === 'expense').reduce((t, e) => t + e.amount, 0);
            const net = dayIn - dayEx;
            const head = `<div class="dayh"><b>${+day.slice(5, 7)}월 ${+day.slice(8)}일</b>${dayIn ? `<span>수입 <span class="plus">+${won(dayIn)}</span></span>` : ''}`
                + `${dayEx ? `<span>지출 <span class="minus">−${won(dayEx)}</span></span>` : ''}<span class="net">합계 ${signed(net)}</span></div>`;
            return head + items.map(e => {
                const c = catOf(e.category_id), mine = canEdit(e), income = c.kind === 'income';
                // 칸 전체를 쓴 사람의 색으로 (왼쪽에 같은 계열 진한 띠)
                return `<button type="button" class="it u${mine ? ' mine' : ''}${st.editId === e.id ? ' editing' : ''}" data-entry="${e.id}" style="${userTint(e.user_id)}"${mine ? ' title="눌러서 고치기"' : ' tabindex="-1"'}>
                    <span class="txt"><span class="memo${e.memo ? '' : ' no-memo'}">${esc(e.memo || c.name)}</span>
                    <span class="line2"><span class="cat" style="color:${chipFg(c.color)}"><span class="dot" style="background:${c.color}"></span>${esc(c.name)}</span>${income ? '<span class="in-tag">수입</span>' : ''}<span class="sep">·</span>${whoTag(e.user_id)}</span></span>
                    <span class="amt ${income ? 'plus' : 'minus'}">${income ? '+' : '−'}${won(e.amount)}</span></button>`;
            }).join('');
        }).join('');
    }

    // ==========================================
    // 입력·고치기
    // ==========================================
    function amountValue() { return parseInt(($('amount').value || '').replace(/[^0-9]/g, ''), 10) || 0; }
    $('amount').addEventListener('input', () => {
        $('entry-msg').textContent = '';
        const v = $('amount').value.replace(/[^0-9]/g, '').slice(0, 10);
        $('amount').value = v ? Number(v).toLocaleString('ko-KR') : '';
    });

    function clearForm() {
        st.editId = null;
        $('amount').value = '';
        $('memo').value = '';
        $('entry-msg').textContent = '';
    }

    $('save').addEventListener('click', async () => {
        const amount = amountValue();
        if (!amount) { $('entry-msg').textContent = '금액을 넣어 주세요.'; $('amount').focus(); return; }
        if (selected() == null) { $('entry-msg').textContent = st.kind === 'income' ? '수입 종류를 골라 주세요.' : '소비형태를 골라 주세요.'; return; }
        const body = { amount, used_on: $('used-on').value || ymd(new Date()), category_id: selected(), memo: $('memo').value.trim() };
        const editing = st.editId != null;
        $('save').disabled = true;
        const { status, data } = await post('/api/ledger/entry', editing ? { action: 'edit', id: st.editId, ...body } : { action: 'add', ...body });
        $('save').disabled = false;
        if (status === 401) { showAuth('login'); return; }
        if (status !== 200) { $('entry-msg').textContent = msgOf(data); return; }
        clearForm();
        await load();
        $('amount').focus();
    });
    $('amount').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); $('save').click(); } });

    function startEdit(entry) {
        st.editId = entry.id;
        st.kind = kindOf(entry);
        st.sels[st.kind] = entry.category_id;
        st.catEditing = false; st.popFor = null;
        $('addbox').hidden = true;
        $('amount').value = entry.amount.toLocaleString('ko-KR');
        $('used-on').value = entry.used_on;
        $('memo').value = entry.memo || '';
        $('entry-msg').textContent = '';
        render();
        $('entry').open = true;   // 접혀 있으면 펼쳐서 고치기
        $('entry').scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
    $('edit-cancel').addEventListener('click', () => { clearForm(); $('used-on').value = ymd(new Date()); render(); });
    $('edit-delete').addEventListener('click', async () => {
        if (st.editId == null) return;
        // 지울 기록을 확인 창에 보여 줌: 날짜 · 메모(없으면 소비형태) / 소비형태 · 금액 · 쓴 사람
        const e = st.data.entries.find(x => x.id === st.editId);
        let detail = '';
        if (e) {
            const c = catOf(e.category_id), income = c.kind === 'income';
            detail = `\n\n${+e.used_on.slice(5, 7)}월 ${+e.used_on.slice(8)}일 · ${e.memo || c.name}\n`
                + `${c.name} · ${income ? '+' : '−'}${won(e.amount)} · ${nameOf(e.user_id)}\n\n지우면 되돌릴 수 없어요.`;
        }
        if (!window.confirm('이 기록을 지울까요?' + detail)) return;
        const { status, data } = await post('/api/ledger/entry', { action: 'delete', id: st.editId });
        if (status !== 200) { $('entry-msg').textContent = msgOf(data); return; }
        clearForm();
        $('used-on').value = ymd(new Date());
        load();
    });

    // ==========================================
    // 소비형태: 고르기·추가·색과 이름 바꾸기
    // ==========================================
    $('cat-edit').addEventListener('click', () => {
        st.catEditing = !st.catEditing;
        st.popFor = null;
        $('addbox').hidden = true;
        renderCats();
    });
    function openAddBox() {
        st.addColor = null;
        $('new-name').value = '';
        $('add-msg').textContent = '';
        $('addbox').hidden = false;
        renderAddBox();
        $('new-name').focus();
    }
    $('new-name').addEventListener('input', () => { $('add-msg').textContent = ''; renderAddBox(); });
    $('add-custom').addEventListener('input', e => { st.addColor = e.target.value.toUpperCase(); $('add-msg').textContent = ''; renderAddBox(); });
    $('add-cancel').addEventListener('click', () => { $('addbox').hidden = true; });
    $('add-ok').addEventListener('click', async () => {
        const name = $('new-name').value.trim();
        if (!name) { $('add-msg').textContent = '이름을 넣어 주세요.'; return; }
        if (!st.addColor) { $('add-msg').textContent = '색을 골라 주세요.'; return; }
        const { status, data } = await post('/api/ledger/category', { action: 'add', name, color: st.addColor, kind: st.kind });
        if (status !== 200) { $('add-msg').textContent = msgOf(data); return; }
        st.sels[st.kind] = data.id;
        $('addbox').hidden = true;
        load();
    });

    async function saveCategory(id, color) {
        const c = st.data.categories.find(x => x.id === id);
        const nameInput = $('pop-name');
        const name = nameInput ? nameInput.value.trim() : c.name;
        const { status, data } = await post('/api/ledger/category', { action: 'edit', id, name, color: color || c.color });
        if (status !== 200) { const m = $('pop-msg'); if (m) m.textContent = msgOf(data); return false; }
        c.name = name; if (color) c.color = color;
        return true;
    }

    // 소비형태 칸 안의 누르기 (선택·추가·편집 창)
    $('cats').addEventListener('click', async e => {
        const pop = e.target.closest('[data-pop]');
        if (pop) {
            e.stopPropagation();
            const id = st.popFor;
            const sw = e.target.closest('[data-pop-color]');
            if (sw) { if (await saveCategory(id, sw.dataset.popColor)) { render(); } return; }
            if (e.target.closest('[data-pop-save]')) { if (await saveCategory(id)) { st.popFor = null; render(); } return; }
            if (e.target.closest('[data-pop-delete]')) {
                if (!window.confirm('이 소비형태를 지울까요?')) return;
                const { status, data } = await post('/api/ledger/category', { action: 'delete', id });
                if (status !== 200) { $('pop-msg').textContent = msgOf(data); return; }
                st.popFor = null;
                load();
            }
            return;
        }
        if (e.target.closest('#cat-add')) { openAddBox(); return; }
        const chip = e.target.closest('[data-cat]');
        if (!chip) return;
        const id = Number(chip.dataset.cat);
        if (st.catEditing) { st.popFor = st.popFor === id ? null : id; renderCats(); const n = $('pop-name'); if (n) n.focus(); return; }
        st.sels[st.kind] = id;
        $('addbox').hidden = true;
        renderCats();
    });
    $('cats').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.chip')) { e.preventDefault(); e.target.click(); } });
    // 편집 창의 '직접 고르기': 고르는 동안 미리 보이고, 손을 떼면(change) 저장
    $('cats').addEventListener('input', e => {
        if (e.target.id !== 'pop-custom') return;
        const chip = e.target.closest('[data-cat]');
        const h = e.target.value;
        chip.style.background = chipBg(h); chip.style.color = chipFg(h);
        chip.querySelector('.dot').style.background = h;
    });
    $('cats').addEventListener('change', async e => {
        if (e.target.id === 'pop-custom' && await saveCategory(st.popFor, e.target.value.toUpperCase())) render();
    });
    $('addbox').addEventListener('click', e => {
        const sw = e.target.closest('[data-add-color]');
        if (sw) { st.addColor = sw.dataset.addColor; $('add-msg').textContent = ''; renderAddBox(); }
    });
    document.addEventListener('click', e => {
        if (st.popFor != null && !e.target.closest('[data-pop]') && !e.target.closest('[data-cat]')) { st.popFor = null; renderCats(); }
        if (!e.target.closest('.memo-wrap')) $('memo-dd').hidden = true;
    });

    // ==========================================
    // 메모: 최근 메모 드롭다운 (고르면 그 메모에 썼던 소비형태도 함께)
    // ==========================================
    function memoMatches() {
        const q = $('memo').value.trim();
        // 지금 고른 쪽(지출·수입)에서 쓴 메모만
        return ((st.data && st.data.memos) || []).filter(m => catOf(m.category_id).kind === st.kind)
            .filter(m => !q || m.memo.includes(q)).filter(m => m.memo !== q).slice(0, 6);
    }
    function renderMemoDd() {
        const list = memoMatches();
        if (!list.length) { $('memo-dd').hidden = true; return; }
        $('memo-dd').innerHTML = list.map((m, i) => {
            const c = catOf(m.category_id);
            return `<button type="button" class="${i === st.ddIndex ? 'act' : ''}" data-memo="${i}"><span class="m">${esc(m.memo)}</span>
                <span class="dot" style="background:${c.color}"></span><span class="k">${esc(c.name)}</span></button>`;
        }).join('');
        $('memo-dd').hidden = false;
    }
    function useMemo(i) {
        const m = memoMatches()[i];
        if (!m) return;
        $('memo').value = m.memo;
        if (st.data.categories.some(c => c.id === m.category_id)) { st.sels[st.kind] = m.category_id; renderCats(); }
        $('memo-dd').hidden = true;
        st.ddIndex = -1;
    }
    $('memo').addEventListener('focus', () => { st.ddIndex = -1; renderMemoDd(); });
    $('memo').addEventListener('input', () => { st.ddIndex = -1; renderMemoDd(); });
    $('memo').addEventListener('keydown', e => {
        const n = $('memo-dd').hidden ? 0 : memoMatches().length;
        if (e.key === 'ArrowDown' && n) { st.ddIndex = Math.min(n - 1, st.ddIndex + 1); renderMemoDd(); e.preventDefault(); }
        else if (e.key === 'ArrowUp' && n) { st.ddIndex = Math.max(0, st.ddIndex - 1); renderMemoDd(); e.preventDefault(); }
        else if (e.key === 'Enter') { e.preventDefault(); if (n && st.ddIndex >= 0) useMemo(st.ddIndex); else { $('memo-dd').hidden = true; $('save').click(); } }
        else if (e.key === 'Escape') { $('memo-dd').hidden = true; }
    });
    // 누르는 순간 메모 칸에서 포커스가 빠져 목록이 닫히지 않게 mousedown에서 고름
    $('memo-dd').addEventListener('mousedown', e => {
        const b = e.target.closest('[data-memo]');
        if (b) { e.preventDefault(); useMemo(Number(b.dataset.memo)); }
    });

    // ==========================================
    // 거르기·기록 누르기
    // ==========================================
    function moveDay(delta) {
        const before = ym(st.day);
        if (st.mode === 'day') st.day.setDate(st.day.getDate() + delta);
        else st.day = new Date(st.day.getFullYear(), st.day.getMonth() + delta, 1);
        if (ym(st.day) !== before) load(); else render();
    }
    $('prev').addEventListener('click', () => moveDay(-1));
    $('next').addEventListener('click', () => moveDay(1));
    $('mode-day').addEventListener('click', () => {
        if (st.mode === 'day') return;
        st.mode = 'day';
        // 이 달을 보다가 일별로 바꾸면: 오늘이 이 달이면 오늘, 아니면 그 달 1일
        const today = new Date();
        if (ym(today) === ym(st.day)) st.day = today;
        render();
    });
    $('mode-month').addEventListener('click', () => { st.mode = 'month'; render(); });
    // 거르기 고르기 창: 단추를 누르면 열고 닫음, 창 밖을 누르면 닫음. 일별·월별은 고르면 닫고, 종류·사람은 둘 다 고를 수 있게 열어 둠
    function setPop(id, open) {
        $(id).hidden = !open;
        $(id === 'mode-pop' ? 'mode-btn' : 'pick-btn').setAttribute('aria-expanded', String(open));
    }
    const closePops = () => { setPop('mode-pop', false); setPop('pick-pop', false); };
    $('mode-btn').addEventListener('click', () => { const open = $('mode-pop').hidden; closePops(); setPop('mode-pop', open); });
    $('pick-btn').addEventListener('click', () => { const open = $('pick-pop').hidden; closePops(); setPop('pick-pop', open); });
    $('mode-pop').addEventListener('click', e => { if (e.target.closest('button')) setPop('mode-pop', false); });
    // (누른 단추가 다시 그려져 문서에서 빠져도 알 수 있게, 누른 순간의 경로로)
    document.addEventListener('click', e => { if (!e.composedPath().some(n => n.classList && n.classList.contains('filter'))) closePops(); });
    function setKind(kind) {
        if (st.kind === kind) return;
        st.kind = kind;
        st.catEditing = false; st.popFor = null;
        $('addbox').hidden = true;
        $('memo-dd').hidden = true;
        render();
        $('amount').focus();
    }
    $('kind-expense').addEventListener('click', () => setKind('expense'));
    $('kind-income').addEventListener('click', () => setKind('income'));
    $('type-seg').addEventListener('click', e => { const b = e.target.closest('[data-type]'); if (b) { st.type = b.dataset.type; render(); } });
    $('ana-seg').addEventListener('click', e => { const b = e.target.closest('[data-ana]'); if (b) { st.ana = b.dataset.ana; render(); } });
    $('people').addEventListener('click', e => {
        const b = e.target.closest('[data-who]');
        if (b) { st.who = Number(b.dataset.who); render(); }
    });
    $('list').addEventListener('click', e => {
        const b = e.target.closest('[data-entry]');
        if (!b) return;
        const entry = st.data.entries.find(x => x.id === Number(b.dataset.entry));
        if (entry && canEdit(entry)) startEdit(entry);
    });

    // ==========================================
    // 관리자: 사용자 허락
    // ==========================================
    async function loadPeople() {
        const { status, data } = await get('/api/ledger/admin');
        if (status === 200) renderPeople(data);
    }
    function renderPeople(data) {
        const n = data.pending.length;
        $('pending-count').hidden = !n;
        $('pending-count').textContent = n;
        if (n) $('admin').open = true;
        $('pending').innerHTML = n ? data.pending.map(p => `<div class="person"><span class="name">${esc(p.name)} <span class="hint">· ${esc((p.requested_at || '').slice(5, 16))} 요청</span></span>
            <button type="button" class="small primary" data-admin="approve" data-uid="${p.id}">허락</button>
            <button type="button" class="small" data-admin="reject" data-uid="${p.id}">거절</button></div>`).join('')
            : '<p class="hint">기다리는 사람 없음</p>';
        $('members').innerHTML = data.members.map(m => `<div class="person"><span class="name">${esc(m.name)}</span>
            ${m.admin ? '<span class="tag admin-tag">관리자</span>' : `<span class="tag">가계부만</span><button type="button" class="small" data-admin="revoke" data-uid="${m.id}">허락 취소</button>`}</div>`).join('');
    }
    $('admin').addEventListener('click', async e => {
        const b = e.target.closest('[data-admin]');
        if (!b) return;
        const action = b.dataset.admin;
        if (action === 'revoke' && !window.confirm('허락을 취소할까요? 그 사람의 로그인이 끊기고, 쓴 기록은 남아요.')) return;
        b.disabled = true;
        const { status, data } = await post('/api/ledger/admin', { action, user_id: Number(b.dataset.uid) });
        b.disabled = false;
        if (status !== 200) { window.alert(msgOf(data)); return; }
        renderPeople(data);
        load();
    });

    // ==========================================
    // 결제 알림 자동 기록: 확인 대기함·내 휴대폰 연결·가게 이름 규칙
    // ==========================================
    async function loadInbox() {
        const { status, data } = await get('/api/ledger/inbox');
        if (status !== 200) return;
        st.inbox = data.items; st.rules = data.rules; st.hook = data.hook; st.hookBase = data.hook_base;
        renderApp(data.app);
        // 앱 안에서 처음 열었는데 연결 전이면 연결 칸을 펼쳐 둠
        if (inApp && !st.autoOpened && !appConnected()) { st.autoOpened = true; $('auto').open = true; }
        renderInbox(); renderAuto();
    }
    function applyInbox(data) {
        if (data.items) st.inbox = data.items;
        if (data.rules) st.rules = data.rules;
        renderInbox(); renderAuto();
    }
    const expenseCats = () => (st.data ? st.data.categories.filter(c => c.kind !== 'income') : []);
    function ruleFor(merchant) {
        const key = (merchant || '').replace(/\(주\)|㈜|주식회사|\s+/g, '').toLowerCase();
        return st.rules.find(r => key.includes(r.pattern.replace(/\s+/g, '').toLowerCase()));
    }
    function suggestPattern(merchant) {
        const words = (merchant || '').replace(/\(주\)|㈜|주식회사/g, '').trim().split(/\s+/);
        if (words.length >= 2 && /(점|지점|역점|센터)$/.test(words[words.length - 1])) words.pop();
        return (words[0] && words[0].length >= 2 ? words[0] : words.join(' ')).slice(0, 20);
    }
    function renderInbox() {
        const items = st.inbox || [];
        // 고치는 중이면 친 값은 그대로 (1분마다 대기함을 새로 받아 다시 그려도)
        const typed = st.editItem != null && $('ib-merchant') ? { amount: $('ib-amount').value, merchant: $('ib-merchant').value,
            used_on: $('ib-date').value, focus: document.activeElement && document.activeElement.id } : null;
        $('inbox-sec').hidden = !items.length;
        $('inbox-count').textContent = items.length;
        if (!items.length || !st.data) return;
        $('inbox').innerHTML = items.map(x => {
            const day = `${+x.used_on.slice(5, 7)}/${+x.used_on.slice(8)}`;
            const rule = !x.cancel && ruleFor(x.merchant);
            let note;
            if (x.cancel) note = x.match ? `<span class="note bad">결제 취소 · ${+x.match.used_on.slice(5, 7)}/${+x.match.used_on.slice(8)}의 같은 결제를 찾았어요 — 확정하면 그 기록을 지워요</span>`
                : '<span class="note bad">결제 취소 · 맞는 기록을 찾지 못했어요 — 확정하면 이 알림만 지워요</span>';
            else if (x.category_id == null) note = '<span class="note">규칙에 없는 가게 — 분류를 골라 주세요</span>';
            else note = `<span class="note">${rule && rule.category_id === x.category_id ? `규칙 "${esc(rule.pattern)}" → ` : ''}${esc(catOf(x.category_id).name)}</span>`;
            const chips = x.cancel ? '' : `<div class="cats">${expenseCats().map(c => `<span class="chip${c.id === x.category_id ? ' on' : ''}" data-ib-cat="${c.id}" data-ib="${x.id}"
                style="background:${chipBg(c.color)};color:${chipFg(c.color)}"><span class="dot" style="background:${c.color}"></span>${esc(c.name)}</span>`).join(' ')}</div>`;
            // 금액·가게 칸 오른쪽 X: 한 번에 지우고 바로 입력 (글자가 있을 때만 보임). 휴대폰은 윗줄 금액·날짜, 아랫줄 가게 한 줄 전부
            const t = typed && st.editItem === x.id ? typed : null;
            const edit = st.editItem === x.id ? `<div class="edit">
                <span class="clr-wrap e-amt"><input id="ib-amount" inputmode="numeric" value="${esc(t ? t.amount : x.amount.toLocaleString('ko-KR'))}" placeholder="금액" aria-label="금액">
                    <button type="button" class="clr" data-clear="ib-amount" aria-label="금액 지우기">✕</button></span>
                <span class="clr-wrap e-shop"><input id="ib-merchant" value="${esc(t ? t.merchant : x.merchant)}" maxlength="60" placeholder="가게 이름" aria-label="가게">
                    <button type="button" class="clr" data-clear="ib-merchant" aria-label="가게 이름 지우기">✕</button></span>
                <input id="ib-date" class="e-date" type="date" value="${esc(t ? t.used_on : x.used_on)}" aria-label="날짜"></div>` : '';
            const canRule = !x.cancel && x.category_id != null && x.merchant && !(rule && rule.category_id === x.category_id);
            return `<div class="ib" data-item="${x.id}"><div class="body">
                <div class="top"><span class="amt${x.cancel ? ' cancel' : ''}">${x.cancel ? '취소 ' : ''}${won(x.amount)}</span><span class="shop">${esc(x.merchant || '가게 이름 없음')}</span>
                <span class="meta">· ${esc(x.card || '카드')} · ${day} ${esc(x.used_time)}</span></div>
                ${note}${chips}${edit}<span class="raw">${esc(x.raw)}</span>
                <div class="btns">${st.editItem === x.id ? '<button type="button" class="primary" data-ib-save>고친 것 저장</button><button type="button" data-ib-edit>그만 고치기</button>'
                    : `<button type="button" class="primary" data-ib-ok${!x.cancel && x.category_id == null ? ' disabled' : ''}>${x.cancel ? '취소 확정' : '확정'}</button>
                    ${x.cancel ? '' : '<button type="button" data-ib-edit>금액·가게 고치기</button>'}
                    ${canRule ? `<button type="button" data-ib-rule>"${esc(suggestPattern(x.merchant))}"는 늘 ${esc(catOf(x.category_id).name)}로</button>` : ''}
                    <button type="button" data-ib-del>버리기</button>`}</div></div></div>`;
        }).join('');
        if (typed && typed.focus && $(typed.focus)) $(typed.focus).focus();
    }
    async function inboxPost(body) {
        $('inbox-msg').textContent = '';
        const { status, data } = await post('/api/ledger/inbox', body);
        if (status !== 200) { $('inbox-msg').textContent = msgOf(data); return null; }
        applyInbox(data);
        return data;
    }
    $('inbox').addEventListener('click', async e => {
        const clear = e.target.closest('[data-clear]');
        if (clear) {
            const input = $(clear.dataset.clear);
            input.value = '';
            input.focus();
            return;
        }
        const box = e.target.closest('[data-item]');
        if (!box) return;
        const id = Number(box.dataset.item), item = st.inbox.find(x => x.id === id);
        const chip = e.target.closest('[data-ib-cat]');
        if (chip) { await inboxPost({ action: 'update', id, category_id: Number(chip.dataset.ibCat) }); return; }
        if (e.target.closest('[data-ib-edit]')) { st.editItem = st.editItem === id ? null : id; renderInbox(); return; }
        if (e.target.closest('[data-ib-save]')) {
            const amount = parseInt(($('ib-amount').value || '').replace(/[^0-9]/g, ''), 10) || 0;
            if (await inboxPost({ action: 'update', id, amount, merchant: $('ib-merchant').value, used_on: $('ib-date').value })) { st.editItem = null; renderInbox(); }
            return;
        }
        if (e.target.closest('[data-ib-ok]')) { if (await inboxPost({ action: 'confirm', id })) load(); return; }
        if (e.target.closest('[data-ib-del]')) { await inboxPost({ action: 'discard', id }); return; }
        if (e.target.closest('[data-ib-rule]')) {
            const { status, data } = await post('/api/ledger/rule', { action: 'add', pattern: suggestPattern(item.merchant), category_id: item.category_id });
            if (status !== 200) { $('inbox-msg').textContent = msgOf(data); return; }
            applyInbox(data);
        }
    });
    $('inbox').addEventListener('input', e => {
        if (e.target.id !== 'ib-amount') return;
        const v = e.target.value.replace(/[^0-9]/g, '').slice(0, 10);
        e.target.value = v ? Number(v).toLocaleString('ko-KR') : '';
    });
    $('inbox-all').addEventListener('click', async () => {
        const data = await inboxPost({ action: 'confirm_all' });
        if (data) { $('inbox-msg').textContent = data.confirmed ? '' : '확정할 수 있는 결제가 없어요 (분류를 먼저 골라 주세요)'; load(); }
    });

    // ---- YeYe가계부 앱 안에서 열었을 때 (앱이 window.LedgerApp을 넣어 줌)
    const inApp = !!window.LedgerApp;
    if (inApp) document.documentElement.classList.add('in-app');
    const appConnected = () => { try { return !!window.LedgerApp.connected(); } catch (e) { return false; } };
    function renderAppConnect() {
        if (!inApp) return;
        const on = appConnected();
        let ver = '';
        try { ver = window.LedgerApp.version(); } catch (e) { /* 예전 앱 */ }
        $('app-connect-state').textContent = on ? `✓ 이 휴대폰 앱(${ver})이 결제 알림을 보내고 있어요` : '이 휴대폰 앱은 아직 연결되지 않았어요';
        $('app-connect-btn').textContent = on ? '다시 연결' : '이 휴대폰 앱에 연결';
        $('app-connect-btn').className = on ? 'small' : 'primary';
    }
    $('app-connect-btn').addEventListener('click', async () => {
        if (st.hook && !window.confirm('새 연결 주소를 만들어 이 앱에 넣어요. 예전 연결 주소(다른 휴대폰·매크로드로이드)는 더 못 써요. 할까요?')) return;
        $('app-connect-btn').disabled = true;
        const { status, data } = await post('/api/ledger/hook-key', { action: 'create' });
        $('app-connect-btn').disabled = false;
        if (status !== 200) { $('app-connect-state').textContent = msgOf(data); return; }
        st.hook = data.hook;
        let ok = false;
        try { ok = window.LedgerApp.connect(data.url); } catch (e) { /* 예전 앱 */ }
        renderAuto();
        if (!ok) $('app-connect-state').textContent = '앱에 넣지 못했어요 — 앱의 설정에서 가계부 주소를 확인해 주세요';
    });

    function renderAuto() {
        if (!st.data) return;
        renderAppConnect();
        const h = st.hook;
        const statusText = { saved: '정상', ignored: '결제 알림이 아니라 넘김', duplicate: '같은 알림이 또 와서 넘김', too_many: '너무 많이 와서 넘김' };
        $('hook-state').textContent = !h ? '아직 연결 주소를 만들지 않았어요.'
            : `연결 주소 만든 때 ${h.created_at.slice(5, 16)} (…${h.hint}) · ${h.last_used ? `마지막으로 받은 알림 ${h.last_used.slice(5, 16)} · ${statusText[h.last_status] || h.last_status}` : '아직 받은 알림 없음'}`;
        $('hook-create').textContent = h ? '연결 주소 새로 만들기' : '연결 주소 만들기';
        $('auto-note').textContent = h ? (h.last_used ? `마지막 알림 ${h.last_used.slice(5, 16)}` : '연결 주소 만듦') : '휴대폰 결제 알림을 가계부로';
        const cats = expenseCats();
        const cur = $('rule-cat').value;
        $('rule-cat').innerHTML = cats.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
        if (cats.some(c => String(c.id) === cur)) $('rule-cat').value = cur;
        $('rules').innerHTML = st.rules.length ? st.rules.map(r => {
            const c = catOf(r.category_id);
            return `<div class="rule"><span class="p">"${esc(r.pattern)}"이 든 가게</span><span>→</span><span class="chip" style="cursor:default;background:${chipBg(c.color)};color:${chipFg(c.color)}"><span class="dot" style="background:${c.color}"></span>${esc(c.name)}</span>
                <button type="button" class="small" data-rule-del="${r.id}">지우기</button></div>`;
        }).join('') : '<p class="hint">아직 규칙이 없어요. 대기함에서 "○○는 늘 ○○로"를 누르거나 아래에서 추가하세요.</p>';
    }
    $('hook-create').addEventListener('click', async () => {
        if (st.hook && !window.confirm('새로 만들면 지금 연결 주소는 더 못 써요. 휴대폰 설정도 새 주소로 바꿔야 해요. 만들까요?')) return;
        const { status, data } = await post('/api/ledger/hook-key', { action: 'create' });
        if (status !== 200) { $('hook-state').textContent = msgOf(data); return; }
        st.hook = data.hook;
        $('hook-url').value = data.url;
        $('hook-url-box').hidden = false;
        renderAuto();
        $('hook-state').textContent = '이 주소는 지금 한 번만 보여요. 복사해서 휴대폰 설정에 넣으세요.';
    });
    $('hook-copy').addEventListener('click', async () => {
        $('hook-url').select();
        try { await navigator.clipboard.writeText($('hook-url').value); $('hook-copy').textContent = '복사됨'; }
        catch (e) { document.execCommand && document.execCommand('copy'); $('hook-copy').textContent = '복사됨'; }
        setTimeout(() => { $('hook-copy').textContent = '복사'; }, 1500);
    });
    $('hook-test').addEventListener('click', async () => { if (await inboxPost({ action: 'test' })) $('inbox-sec').scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    $('rule-add').addEventListener('click', async () => {
        const pattern = $('rule-pattern').value.trim();
        $('rule-msg').textContent = '';
        const { status, data } = await post('/api/ledger/rule', { action: 'add', pattern, category_id: Number($('rule-cat').value) });
        if (status !== 200) { $('rule-msg').textContent = msgOf(data); return; }
        $('rule-pattern').value = '';
        applyInbox(data);
    });
    $('rules').addEventListener('click', async e => {
        const b = e.target.closest('[data-rule-del]');
        if (!b) return;
        const { status, data } = await post('/api/ledger/rule', { action: 'delete', id: Number(b.dataset.ruleDel) });
        if (status === 200) applyInbox(data);
    });
    // ---- YeYe가계부 앱: 모두 받기, 관리자는 올리기
    const kb = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`;
    function renderApp(app) {
        $('app-get').hidden = !app;
        $('app-none').hidden = !!app;
        const text = app ? `${app.versionName} · ${kb(app.size)} · ${app.uploaded_at.slice(5, 10).replace('-', '/')} 올림` : '';
        $('app-info').textContent = text;
        $('app-admin-state').textContent = app ? `지금 올라가 있는 앱: ${text} (${app.uploaded_by})` : '아직 올린 앱이 없어요.';
    }
    $('app-file').addEventListener('change', () => { $('app-upload').disabled = !$('app-file').files.length; $('app-msg').textContent = ''; });
    $('app-upload').addEventListener('click', async () => {
        const file = $('app-file').files[0];
        if (!file) return;
        $('app-upload').disabled = true;
        $('app-msg').textContent = '올리는 중…';
        let status = 0, data = {};
        try {
            const res = await fetch('/api/ledger/app-upload', { method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/octet-stream' }, body: file });
            status = res.status;
            data = await res.json().catch(() => ({}));
        } catch (e) { data = { message: '연결이 끊겼어요.' }; }
        $('app-upload').disabled = false;
        if (status !== 200) { $('app-msg').textContent = msgOf(data); return; }
        $('app-msg').textContent = `올렸어요: ${data.app.versionName}`;
        $('app-file').value = '';
        $('app-upload').disabled = true;
        renderApp(data.app);
    });
    // ---- 앱의 뒤로가기: 열려 있는 것을 하나 닫으면 true (닫을 게 없으면 false → 앱이 '한 번 더 누르면 종료' 안내)
    window.ledgerBack = () => {
        if (!$('mode-pop').hidden || !$('pick-pop').hidden) { closePops(); return true; }
        if (!$('memo-dd').hidden) { $('memo-dd').hidden = true; return true; }
        if (st.popFor != null) { st.popFor = null; renderCats(); return true; }
        if (!$('addbox').hidden) { $('addbox').hidden = true; return true; }
        if (st.catEditing) { st.catEditing = false; renderCats(); return true; }
        if (st.editItem != null) { st.editItem = null; renderInbox(); return true; }
        if (st.editId != null) { $('edit-cancel').click(); return true; }
        for (const id of ['auto', 'admin']) {
            if (!$(id).hidden && $(id).open) { $(id).open = false; return true; }
        }
        return false;
    };
    // 다른 화면에 갔다 오면(휴대폰에서 결제 뒤 열었을 때 등) 대기함을 새로
    document.addEventListener('visibilitychange', () => { if (!document.hidden && st.me) loadInbox(); });
    setInterval(() => { if (!document.hidden && st.me) loadInbox(); }, 60000);

    boot();
})();
