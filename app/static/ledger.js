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
    // 지출 입력의 날짜: 칸에는 짧게 '11/23 (일)' (올해가 아니면 '25/12/31')
    function showUsedOn() {
        const v = $('used-on').value, el = $('used-on-show');
        if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) { el.textContent = '날짜'; return; }
        const [y, m, d] = v.split('-').map(Number);
        el.textContent = y === new Date().getFullYear() ? `${m}/${d} (${'일월화수목금토'[new Date(y, m - 1, d).getDay()]})` : `${String(y).slice(2)}/${pad(m)}/${pad(d)}`;
    }
    function setUsedOn(v) { $('used-on').value = v; showUsedOn(); }
    const ym = d => ymd(d).slice(0, 7);
    function mix(hex, toWhite, f) {
        const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
        const t = toWhite ? 255 : 0;
        return '#' + c.map(v => Math.round(v + (t - v) * f).toString(16).padStart(2, '0')).join('');
    }
    const chipBg = h => mix(h, true, 0.84), chipFg = h => mix(h, false, 0.45);
    // 분류 아이콘: 고른 이모지, 없으면 이름으로 짐작, 그것도 없으면 이름 첫 글자
    const ICONS = ['🍚', '☕', '🚌', '🧺', '🛍️', '💊', '🏠', '📱', '🎁', '🎬', '📚', '🐶', '✈️', '🚗', '💡', '🍺', '💄', '👶', '📦', '💳', '💰', '💵', '🎉', '🏦'];
    const GUESS = [[/식|밥|외식|배달/, '🍚'], [/카페|커피/, '☕'], [/교통|버스|지하철|택시/, '🚌'], [/생활|마트|장보/, '🧺'], [/쇼핑|옷/, '🛍️'],
        [/의료|병원|약|건강/, '💊'], [/주거|월세|관리비|집/, '🏠'], [/통신|휴대폰|폰/, '📱'], [/경조|선물/, '🎁'], [/문화|여가|취미|영화/, '🎬'],
        [/교육|학원|책/, '📚'], [/반려|강아지|고양이|펫/, '🐶'], [/여행/, '✈️'], [/차|주유|주차/, '🚗'], [/공과|전기|가스|수도/, '💡'], [/술/, '🍺'],
        [/미용|화장/, '💄'], [/육아|아이/, '👶'], [/급여|월급/, '💰'], [/부수입/, '💵'], [/용돈/, '🎉'], [/이자|환급/, '🏦']];
    function iconOf(c) {
        if (c.icon) return c.icon;
        const g = GUESS.find(([re]) => re.test(c.name || ''));
        return g ? g[1] : [...(c.name || '?')][0];
    }
    const catIcon = c => `<span class="ci" style="background:${chipBg(c.color)};color:${chipFg(c.color)}" aria-hidden="true">${esc(iconOf(c))}</span>`;
    // 휴대폰(손가락): 금액은 화면 아래 숫자 키패드로 (휴대폰 자판을 띄우지 않음)
    const touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
    if (touch) document.documentElement.classList.add('touch');

    const st = {
        me: null, data: null, mode: 'month', day: new Date(), who: 0,
        // kind: 입력 중인 쪽(expense·income), sels: 쪽마다 고른 분류, type: 기록 거르기(all·expense·income), ana: 분석할 쪽
        kind: 'expense', sels: { expense: null, income: null }, type: 'all', ana: 'expense',
        // 합계 구역: totView(day: 이 달 달력·month: 올해 달마다), year·yearData(서버의 올해 합계)
        totView: 'day', year: new Date().getFullYear(), yearData: null,
        // 자동 기록: 확인 대기함·가게 규칙·내 연결 상태, 대기함에서 고치는 중인 알림
        inbox: [], rules: [], hook: null, hookBase: '', ibDirty: {}, newCatFor: null, newCat: { name: '', color: null, msg: '' },
        catEditing: false, popFor: null, addColor: null, addIcon: '', editId: null, ddIndex: -1,
        // view: 아래 보기(list 내역·cal 달력·ana 분석), ibOpen: 펼쳐 고치는 대기함 항목
        view: 'list', ibOpen: new Set(),
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
        $('who-me').hidden = $('logout').hidden = $('set-open').hidden = $('all-set').hidden = true;
        $('app').classList.remove('settings-open');
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
        $('who-me').hidden = $('logout').hidden = $('all-set').hidden = false;
        setUsedOn(ymd(new Date()));
        $('set-open').hidden = false;
        renderSetTabs();
        if (location.hash === '#settings') showSettings(true);
        if (user.admin) loadPeople();
        load();
        loadInbox();
        if (location.hash === '#inbox') window.appShowInbox();
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
        // 대기함이 먼저 와서 분류 목록 없이 칸만 열렸으면 이제 내용까지 (알림을 눌러 열 때 기록 쪽이 늦게 오는 일이 잦음)
        if (st.inbox) renderInbox();
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
        renderViews();
    }
    function renderViews() {
        document.querySelectorAll('#views [data-view]').forEach(b => {
            b.classList.toggle('on', b.dataset.view === st.view);
            b.setAttribute('aria-selected', String(b.dataset.view === st.view));
        });
        document.querySelectorAll('#app .pane').forEach(p => { p.hidden = p.dataset.pane !== st.view; });
        $('type-seg').hidden = st.view !== 'list';   // 지출·수입 거르기는 내역에만 (달력·분석은 자기 단추)
    }
    $('views').addEventListener('click', e => {
        const b = e.target.closest('[data-view]');
        if (b) { st.view = b.dataset.view; renderViews(); }
    });

    function renderEntryHead() {
        const editing = st.editId != null, income = st.kind === 'income';
        $('entry').classList.toggle('editing', editing);
        $('entry').classList.toggle('income', income);
        $('kind-expense').classList.toggle('on', !income);
        $('kind-income').classList.toggle('on', income);
        $('kind-expense').setAttribute('aria-checked', String(!income));
        $('kind-income').setAttribute('aria-checked', String(income));
        $('entry-title').textContent = editing ? '기록 고치기' : income ? '수입 입력' : '지출 입력';
        $('edit-row').hidden = !editing;
    }

    function chipHtml(c, extra) {
        return `<span class="dot" style="background:${c.color}"></span>${esc(c.name)}${extra || ''}`;
    }
    function renderCats() {
        const cats = kindCats();
        $('cats').classList.toggle('editing', st.catEditing);
        $('cat-edit').textContent = st.catEditing ? '완료' : '편집';
        $('cats').innerHTML = cats.map(c => `<span class="chip${!st.catEditing && c.id === selected() ? ' on' : ''}" data-cat="${c.id}" role="button" tabindex="0"
                style="color:${chipFg(c.color)}">${catIcon(c)}<span class="cn">${esc(c.name)}</span>${st.popFor === c.id ? popHtml(c) : ''}</span>`).join('')
            + (st.catEditing ? '' : '<span class="chip add" id="cat-add" role="button" tabindex="0"><span class="ci">＋</span><span class="cn">추가</span></span>');
    }
    function palHtml(current, attr) {
        const cur = (current || '').toUpperCase();
        return PRESET.map(h => `<button type="button" class="sw${cur === h ? ' on' : ''}" ${attr}="${h}" style="background:${h}" aria-label="${h}">${cur === h ? '✓' : ''}</button>`).join('');
    }
    function iconsHtml(current, attr) {
        return ICONS.map(i => `<button type="button" class="ic${current === i ? ' on' : ''}" ${attr}="${i}" aria-label="${i}">${i}</button>`).join('');
    }
    function popHtml(c) {
        return `<div class="pop" data-pop>
            <input id="pop-name" value="${esc(c.name)}" maxlength="12" aria-label="소비형태 이름">
            <div class="icons">${iconsHtml(iconOf(c), 'data-pop-icon')}</div>
            <div class="pal">${palHtml(c.color, 'data-pop-color')}</div>
            <label class="custom"><input type="color" id="pop-custom" value="${c.color.toLowerCase()}"> 다른 색</label>
            <div class="pop-actions"><button type="button" class="primary" data-pop-save>완료</button><button type="button" class="danger" data-pop-delete>지우기</button></div>
            <p class="msg" id="pop-msg"></p></div>`;
    }

    function renderAddBox() {
        $('add-pal').innerHTML = palHtml(st.addColor, 'data-add-color');
        $('add-icons').innerHTML = iconsHtml(st.addIcon, 'data-add-icon');
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
        $('type-seg').querySelectorAll('[data-type]').forEach(b => b.classList.toggle('on', b.dataset.type === st.type));
        $('ana-seg').querySelectorAll('[data-ana]').forEach(b => b.classList.toggle('on', b.dataset.ana === st.ana));
        const d = st.day;
        // 기간: 월별 '2026년 11월', 일별(달력에서 날짜를 누름) '11월 23일 (일)' — 누르면 이 달 전체로
        $('period').textContent = st.mode === 'day'
            ? `${d.getMonth() + 1}월 ${d.getDate()}일 (${'일월화수목금토'[d.getDay()]})`
            : `${d.getFullYear()}년 ${d.getMonth() + 1}월`;
        $('period').classList.toggle('day', st.mode === 'day');
        const members = st.data.members;
        if (st.who && !members.some(m => m.id === st.who)) st.who = 0;
        $('people').innerHTML = `<button type="button" class="pp all${!st.who ? ' on' : ''}" data-who="0">전체</button>`
            + members.map(m => `<button type="button" class="pp${st.who === m.id ? ' on' : ''}" data-who="${m.id}">${esc(m.name)}</button>`).join('');
    }

    function renderSummary() {
        const scope = scoped(), list = shown();
        const sumOf = kind => scope.filter(e => kindOf(e) === kind).reduce((t, e) => t + e.amount, 0);
        const inSum = sumOf('income'), exSum = sumOf('expense'), left = inSum - exSum;
        const whoName = st.who ? nameOf(st.who) : '';
        const when = st.mode === 'day' ? '이날' : ym(st.day) === ym(new Date()) ? '이번 달' : `${st.day.getMonth() + 1}월`;
        $('m-ex-label').textContent = `${when} 지출${whoName ? ` · ${whoName}` : ''}`;
        $('m-in').textContent = won(inSum);
        $('m-ex').textContent = won(exSum);
        $('m-left').textContent = `${left < 0 ? '−' : ''}${won(Math.abs(left))}`;
        $('m-left').className = left < 0 ? 'minus' : '';
        // 수입 대비 지출 막대 (수입이 없으면 지출이 있을 때 가득)
        $('m-bar').style.width = `${inSum ? Math.min(100, Math.round(exSum / inSum * 100)) : exSum ? 100 : 0}%`;
        // 분석: 고른 쪽(지출·수입)의 분류별 합계
        const sums = new Map();
        scope.filter(e => kindOf(e) === st.ana).forEach(e => sums.set(e.category_id, (sums.get(e.category_id) || 0) + e.amount));
        const parts = [...sums.entries()].sort((a, b) => b[1] - a[1]);
        const total = parts.reduce((t, p) => t + p[1], 0);
        renderDonut(parts, total, whoName ? `${whoName} ${st.ana === 'income' ? '수입' : '지출'}` : st.ana === 'income' ? '수입' : '지출');
        $('legend').innerHTML = parts.length ? parts.map(([id, v]) => {
            const c = catOf(id), pct = Math.round(v / total * 100);
            return `<div class="lg"><div class="lg-top">${catIcon(c)}<span class="n">${esc(c.name)}</span>
                <span class="p">${pct}%</span><span class="w">${won(v)}</span></div><div class="lg-bar"><i style="width:${pct}%;background:${c.color}"></i></div></div>`;
        }).join('') : `<p class="empty">${st.ana === 'income' ? '수입' : '지출'} 기록이 없어요</p>`;
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
        st.view = 'list';   // 그날 내역이 보이게
        render();
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
    // 내역: 날짜별 묶음 ('24일 월요일' + 그날 합계). 한 줄은 분류 아이콘 · 메모(없으면 분류) · '분류 · 사람' · 금액,
    // 칸 바탕은 쓴 사람의 색. 내 기록은 누르면 고치기, 휴대폰에서 왼쪽으로 밀면 '지우기'
    function renderList(list) {
        if (!list.length) { $('list').innerHTML = '<p class="empty">기록이 없어요</p>'; return; }
        const days = [...new Set(list.map(e => e.used_on))];
        $('list').innerHTML = days.map(day => {
            const items = list.filter(e => e.used_on === day);
            const net = items.reduce((t, e) => t + (kindOf(e) === 'income' ? e.amount : -e.amount), 0);
            const [y, m, dd] = day.split('-').map(Number);
            const head = `<div class="dayh"><b>${dd}일 ${'일월화수목금토'[new Date(y, m - 1, dd).getDay()]}요일</b><span class="net">${signed(net)}</span></div>`;
            return head + items.map(e => {
                const c = catOf(e.category_id), mine = canEdit(e), income = c.kind === 'income';
                return `<div class="sw-row">${mine ? `<button type="button" class="sw-del" data-del="${e.id}">지우기</button>` : ''}
                    <div class="it u${mine ? ' mine' : ''}${st.editId === e.id ? ' editing' : ''}" data-entry="${e.id}" style="${userTint(e.user_id)}"${mine ? ' role="button" tabindex="0"' : ''}>
                    ${catIcon(c)}<span class="txt"><span class="memo${e.memo ? '' : ' no-memo'}">${esc(e.memo || c.name)}</span>
                    <span class="line2"><span class="cat">${esc(c.name)}</span><span class="sep">·</span>${whoTag(e.user_id)}</span></span>
                    <span class="amt ${income ? 'plus' : 'minus'}">${income ? '+' : '−'}${won(e.amount)}</span></div></div>`;
            }).join('');
        }).join('');
    }

    // ==========================================
    // 입력·고치기
    // ==========================================
    function amountValue() { return parseInt(($('amount').value || '').replace(/[^0-9]/g, ''), 10) || 0; }
    if (touch) { $('amount').readOnly = true; $('amount').setAttribute('inputmode', 'none'); }
    function openEntry() {
        $('sheet-wrap').hidden = false;
        document.documentElement.classList.add('sheet-open');
        if (!touch) setTimeout(() => $('amount').focus(), 30);
    }
    function closeEntry() {
        $('sheet-wrap').hidden = true;
        document.documentElement.classList.remove('sheet-open');
        $('memo-dd').hidden = true;
        $('addbox').hidden = true;
        st.popFor = null; st.catEditing = false;
        if (st.editId != null) { clearForm(); setUsedOn(ymd(new Date())); }
        render();
    }
    $('fab').addEventListener('click', () => {
        if (st.editId != null) { clearForm(); setUsedOn(ymd(new Date())); }
        render();
        openEntry();
    });
    $('entry-close').addEventListener('click', closeEntry);
    $('sheet-wrap').addEventListener('click', e => { if (e.target === $('sheet-wrap')) closeEntry(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('sheet-wrap').hidden && $('memo-dd').hidden) closeEntry(); });
    $('keypad').addEventListener('click', e => {
        const b = e.target.closest('[data-key]');
        if (!b) return;
        let v = $('amount').value.replace(/[^0-9]/g, '');
        v = b.dataset.key === 'back' ? v.slice(0, -1) : (v + b.dataset.key).replace(/^0+/, '');
        $('amount').value = v;
        $('amount').dispatchEvent(new Event('input', { bubbles: true }));
    });
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
        closeEntry();
        await load();
    });
    $('amount').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); $('save').click(); } });

    function startEdit(entry) {
        st.editId = entry.id;
        st.kind = kindOf(entry);
        st.sels[st.kind] = entry.category_id;
        st.catEditing = false; st.popFor = null;
        $('addbox').hidden = true;
        $('amount').value = entry.amount.toLocaleString('ko-KR');
        setUsedOn(entry.used_on);
        $('memo').value = entry.memo || '';
        $('entry-msg').textContent = '';
        render();
        openEntry();
    }
    $('used-on').addEventListener('input', showUsedOn);
    $('used-on').addEventListener('change', showUsedOn);
    // 칸 어디를 눌러도 달력 (PC 크롬은 아이콘을 눌러야만 열림)
    $('used-on').addEventListener('click', e => { try { e.target.showPicker(); } catch (err) { /* 지원 안 함 */ } });
    $('edit-cancel').addEventListener('click', closeEntry);
    $('edit-delete').addEventListener('click', async () => {
        if (st.editId != null && await deleteEntry(st.editId)) { clearForm(); closeEntry(); }
    });
    async function deleteEntry(id) {
        // 지울 기록을 확인 창에 보여 줌: 날짜 · 메모(없으면 소비형태) / 소비형태 · 금액 · 쓴 사람
        const e = st.data.entries.find(x => x.id === id);
        let detail = '';
        if (e) {
            const c = catOf(e.category_id), income = c.kind === 'income';
            detail = `\n\n${+e.used_on.slice(5, 7)}월 ${+e.used_on.slice(8)}일 · ${e.memo || c.name}\n`
                + `${c.name} · ${income ? '+' : '−'}${won(e.amount)} · ${nameOf(e.user_id)}\n\n지우면 되돌릴 수 없어요.`;
        }
        if (!window.confirm('이 기록을 지울까요?' + detail)) return false;
        const { status, data } = await post('/api/ledger/entry', { action: 'delete', id });
        if (status !== 200) { const m = msgOf(data); if (!$('sheet-wrap').hidden) $('entry-msg').textContent = m; else window.alert(m); return false; }
        await load();
        return true;
    }

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
        st.addColor = null; st.addIcon = '';
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
        const { status, data } = await post('/api/ledger/category', { action: 'add', name, color: st.addColor, kind: st.kind, icon: st.addIcon });
        if (status !== 200) { $('add-msg').textContent = msgOf(data); return; }
        st.sels[st.kind] = data.id;
        $('addbox').hidden = true;
        load();
    });

    async function saveCategory(id, color, icon) {
        const c = st.data.categories.find(x => x.id === id);
        const nameInput = $('pop-name');
        const name = nameInput ? nameInput.value.trim() : c.name;
        const { status, data } = await post('/api/ledger/category', { action: 'edit', id, name, color: color || c.color, ...(icon ? { icon } : {}) });
        if (status !== 200) { const m = $('pop-msg'); if (m) m.textContent = msgOf(data); return false; }
        c.name = name; if (color) c.color = color; if (icon) c.icon = icon;
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
            const ic = e.target.closest('[data-pop-icon]');
            if (ic) { if (await saveCategory(id, null, ic.dataset.popIcon)) { render(); } return; }
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
        chip.style.color = chipFg(h);
        const ci = chip.querySelector('.ci');
        ci.style.background = chipBg(h); ci.style.color = chipFg(h);
    });
    $('cats').addEventListener('change', async e => {
        if (e.target.id === 'pop-custom' && await saveCategory(st.popFor, e.target.value.toUpperCase())) render();
    });
    $('addbox').addEventListener('click', e => {
        const sw = e.target.closest('[data-add-color]');
        if (sw) { st.addColor = sw.dataset.addColor; $('add-msg').textContent = ''; renderAddBox(); }
        const ic = e.target.closest('[data-add-icon]');
        if (ic) { st.addIcon = ic.dataset.addIcon; renderAddBox(); }
    });
    document.addEventListener('click', e => {
        if (st.popFor != null && !e.target.closest('[data-pop]') && !e.target.closest('[data-cat]')) { st.popFor = null; renderCats(); }
        if (!e.target.closest('.memo-wrap')) $('memo-dd').hidden = true;
    });

    // ==========================================
    // 메모: 최근 메모 드롭다운 (고르면 그 메모에 썼던 소비형태도 함께)
    // ==========================================
    // 메모 자동완성 (지출 입력의 메모·대기함의 가게 칸): 비어 있으면 최근 메모, 글자를 치면 지금까지 쓴 모든 메모에서
    // 앞에서부터 맞는 것 먼저, 그다음 최근 순 (띄어쓰기·대소문자 무시). kind를 주면 그쪽(지출·수입) 분류로 쓴 메모만
    const memoKey = s => (s || '').replace(/\s+/g, '').toLowerCase();
    function memoSearch(q, kind) {
        const key = memoKey(q);
        const all = ((st.data && st.data.memos) || []).filter(m => !kind || catOf(m.category_id).kind === kind);
        if (!key) return all.slice(0, 6);
        const hit = all.map(m => [m, memoKey(m.memo).indexOf(key)]).filter(([m, at]) => at >= 0 && memoKey(m.memo) !== key);
        return [...hit.filter(([, at]) => at === 0), ...hit.filter(([, at]) => at > 0)].slice(0, 6).map(([m]) => m);
    }
    // 목록 한 줄: 맞는 글자는 노랗게 (띄어쓰기 없이 그대로 들어 있을 때)
    function memoItemHtml(m, q, attr, active) {
        const c = catOf(m.category_id), at = q ? m.memo.indexOf(q.trim()) : -1, n = q.trim().length;
        const label = at >= 0 && n ? `${esc(m.memo.slice(0, at))}<mark>${esc(m.memo.slice(at, at + n))}</mark>${esc(m.memo.slice(at + n))}` : esc(m.memo);
        return `<button type="button" class="${active ? 'act' : ''}" ${attr}><span class="m">${label}</span>
            <span class="dot" style="background:${c.color}"></span><span class="k">${esc(c.name)}</span></button>`;
    }
    function memoMatches() { return memoSearch($('memo').value, st.kind); }
    function renderMemoDd() {
        const list = memoMatches(), q = $('memo').value;
        if (!list.length) { $('memo-dd').hidden = true; return; }
        $('memo-dd').innerHTML = (q.trim() ? '' : '<div class="dd-h">최근 메모</div>')
            + list.map((m, i) => memoItemHtml(m, q, `data-memo="${i}"`, i === st.ddIndex)).join('');
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
    // 일별(달력에서 날짜를 누른 때)이면 기간을 눌러 이 달 전체로
    $('period').addEventListener('click', () => { if (st.mode === 'day') { st.mode = 'month'; render(); } });
    function setKind(kind) {
        if (st.kind === kind) return;
        st.kind = kind;
        st.catEditing = false; st.popFor = null;
        $('addbox').hidden = true;
        $('memo-dd').hidden = true;
        render();
        if (!touch) $('amount').focus();
    }
    $('kind-expense').addEventListener('click', () => setKind('expense'));
    $('kind-income').addEventListener('click', () => setKind('income'));
    $('type-seg').addEventListener('click', e => { const b = e.target.closest('[data-type]'); if (b) { st.type = b.dataset.type; render(); } });
    $('ana-seg').addEventListener('click', e => { const b = e.target.closest('[data-ana]'); if (b) { st.ana = b.dataset.ana; render(); } });
    $('people').addEventListener('click', e => {
        const b = e.target.closest('[data-who]');
        if (b) { st.who = Number(b.dataset.who); render(); }
    });
    $('list').addEventListener('click', async e => {
        const del = e.target.closest('[data-del]');
        if (del) { await deleteEntry(Number(del.dataset.del)); return; }
        if (Date.now() - (st.swipedAt || 0) < 400) return;
        const opened = $('list').querySelector('.sw-row.open');
        if (opened) { opened.classList.remove('open'); return; }   // 밀어 둔 줄이 있으면 먼저 닫기만
        const b = e.target.closest('[data-entry]');
        if (!b) return;
        const entry = st.data.entries.find(x => x.id === Number(b.dataset.entry));
        if (entry && canEdit(entry)) startEdit(entry);
    });
    $('list').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.it.mine')) { e.preventDefault(); e.target.click(); } });
    // 휴대폰: 내 기록 줄을 왼쪽으로 밀면 '지우기'가 나옴 (반쯤 넘게 밀면 열린 채로)
    let swipe = null;
    $('list').addEventListener('touchstart', e => {
        const it = e.target.closest('.it.mine');
        $('list').querySelectorAll('.sw-row.open').forEach(r => { if (!it || r !== it.parentElement) r.classList.remove('open'); });
        if (!it) return;
        const t = e.touches[0];
        swipe = { it, x: t.clientX, y: t.clientY, dx: 0, moving: false, open: it.parentElement.classList.contains('open') };
    }, { passive: true });
    $('list').addEventListener('touchmove', e => {
        if (!swipe) return;
        const t = e.touches[0], dx = t.clientX - swipe.x, dy = t.clientY - swipe.y;
        if (!swipe.moving && Math.abs(dy) > Math.abs(dx)) { swipe = null; return; }   // 위아래로 넘기는 중
        swipe.moving = true;
        swipe.it.parentElement.classList.add('swiping');
        swipe.dx = Math.max(-84, Math.min(0, dx + (swipe.open ? -84 : 0)));
        swipe.it.style.transition = 'none';
        swipe.it.style.transform = `translateX(${swipe.dx}px)`;
    }, { passive: true });
    $('list').addEventListener('touchend', () => {
        if (!swipe) return;
        const { it, dx, moving } = swipe;
        swipe = null;
        it.style.transition = ''; it.style.transform = '';
        it.parentElement.classList.remove('swiping');
        if (!moving) return;
        it.parentElement.classList.toggle('open', dx < -42);
        st.swipedAt = Date.now();   // 민 뒤 손을 뗄 때 생기는 누르기는 고치기로 가지 않게
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
        $('set-dot').hidden = !n;
        $('set-dot').textContent = n;
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
        st.inbox = data.items; st.rules = data.rules; st.hook = data.hook; st.hookBase = data.hook_base; st.discarded = data.discarded || [];
        renderApp(data.app);
        renderInbox(); renderAuto();
    }
    function applyInbox(data) {
        if (data.items) st.inbox = data.items;
        if (data.rules) st.rules = data.rules;
        if (data.discarded) st.discarded = data.discarded;
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
    // 버린 알림 (최근 30일, 최근 버린 순): 설정 > 버린 알림 탭에만 (탭에 개수), 되살리면 대기함으로
    function renderTrash() {
        const list = st.discarded || [];
        $('tab-trash-n').hidden = !list.length;
        $('tab-trash-n').textContent = list.length;
        if (!list.length) { $('trash-list').innerHTML = '<p class="none">버린 알림이 없어요.</p>'; return; }
        const ago = at => {
            const min = Math.max(0, Math.round((Date.now() - new Date(at.replace(' ', 'T'))) / 60000));
            return min < 1 ? '방금' : min < 60 ? `${min}분 전` : min < 1440 ? `${Math.floor(min / 60)}시간 전` : `${Math.floor(min / 1440)}일 전`;
        };
        // YeYe홈 앱 1.9 이상 안에서만: '이런 알림 안 받기' → 앱의 낱말 고르기 창 (무시할 표현은 휴대폰에만 저장)
        const canIgnore = appCanIgnore();
        $('trash-list').innerHTML = list.map(x => `
            <div class="tr"><div class="m"><b>${x.cancel ? '취소 ' : ''}${won(x.amount)}</b> ${esc(x.merchant || '가게 이름 없음')}
                <small>${+x.used_on.slice(5, 7)}/${+x.used_on.slice(8)} ${esc(x.used_time)} · ${esc(x.card || '카드')} · ${ago(x.discarded_at)} 버림</small></div>
                <span class="bt">${canIgnore && x.raw ? `<button type="button" data-ignore="${x.id}">이런 알림 안 받기</button>` : ''}
                <button type="button" data-restore="${x.id}">되살리기</button></span></div>`).join('');
    }
    function appCanIgnore() { try { return !!window.LedgerApp && typeof window.LedgerApp.pickIgnore === 'function'; } catch (e) { return false; } }
    $('trash-list').addEventListener('click', async e => {
        const ig = e.target.closest('[data-ignore]');
        if (ig) {
            const x = (st.discarded || []).find(d => d.id === Number(ig.dataset.ignore));
            try { if (x) window.LedgerApp.pickIgnore(x.raw); } catch (err) { /* 예전 앱 */ }
            return;
        }
        const b = e.target.closest('[data-restore]');
        if (b) await inboxPost({ action: 'restore', id: Number(b.dataset.restore) });
    });
    // 버린 직후 5초 동안 '되돌리기'
    let undoTimer = null;
    function showUndo(item) {
        clearTimeout(undoTimer);
        $('undo-msg').textContent = `'${item.merchant || '가게 이름 없음'} ${won(item.amount)}'을 버렸어요`;
        $('undo').dataset.id = item.id;
        $('undo').hidden = false;
        undoTimer = setTimeout(() => { $('undo').hidden = true; }, 5000);
    }
    $('undo-btn').addEventListener('click', async () => {
        clearTimeout(undoTimer);
        $('undo').hidden = true;
        await inboxPost({ action: 'restore', id: Number($('undo').dataset.id) });
    });

    // 대기함 항목은 늘 고치는 모드: 금액·가게·날짜 칸이 열려 있고, 칸을 벗어나면 바로 저장, 확정하면 고친 값으로 기록.
    // 아직 저장하지 않은 칸(st.ibDirty)은 1분마다 대기함을 새로 받아 다시 그려도 친 값 그대로.
    // 분류 칩 끝의 '＋ 새 분류'로 그 항목 안에서 지출 분류를 만들고 바로 고름 (st.newCatFor)
    const ibField = (id, f) => $(`ib-${f}-${id}`);
    function ibValues(id) {
        const a = ibField(id, 'amount');
        if (!a) return null;
        return { amount: parseInt((a.value || '').replace(/[^0-9]/g, ''), 10) || 0, merchant: ibField(id, 'merchant').value, used_on: ibField(id, 'date').value };
    }
    const ibChanged = (item, v) => !!v && (v.amount !== item.amount || v.merchant.trim().replace(/\s+/g, ' ') !== (item.merchant || '') || v.used_on !== item.used_on);
    const markDirty = input => { const b = input.closest('[data-item]'); if (b) st.ibDirty[b.dataset.item] = true; };
    function nbPreviewHtml() {
        const c = st.newCat.color, name = esc(st.newCat.name.trim() || '새 분류');
        return c ? `<span class="chip" style="cursor:default;background:${chipBg(c)};color:${chipFg(c)}"><span class="dot" style="background:${c}"></span>${name}</span>`
            : `<span class="hint">색을 고르면 미리 보여요</span>`;
    }
    function renderInbox() {
        renderTrash();
        const items = st.inbox || [];
        // 다시 그려도 그대로 둘 것: 저장 전인 칸 값, 새 분류 이름, 커서가 있던 칸
        const typed = {};
        items.forEach(x => {
            if (st.ibDirty[x.id] && ibField(x.id, 'amount')) typed[x.id] = { amount: ibField(x.id, 'amount').value, merchant: ibField(x.id, 'merchant').value, used_on: ibField(x.id, 'date').value };
        });
        if (st.newCatFor != null && $('nb-name')) st.newCat.name = $('nb-name').value;
        if (st.newCatFor != null && !items.some(x => x.id === st.newCatFor)) st.newCatFor = null;
        const act = document.activeElement;
        const focus = act && act.id && $('inbox').contains(act) ? act.id : '';
        $('inbox-sec').hidden = !items.length;
        $('inbox-count').textContent = items.length;
        if (!items.length || !st.data) return;
        $('inbox').innerHTML = items.map(x => {
            const day = `${+x.used_on.slice(5, 7)}/${+x.used_on.slice(8)}`;
            const t = typed[x.id];
            const shop = t ? t.merchant : x.merchant;
            const rule = !x.cancel && ruleFor(shop);
            // 고른 분류가 없으면 지난 기록의 추천 (같은 가게로 가장 많이 쓴 분류, 그대로 확정하면 그 분류로)
            const sug = !x.cancel && x.category_id == null && x.suggest && catOf(x.suggest.category_id).id != null ? x.suggest : null;
            const cat = x.category_id != null ? x.category_id : sug ? sug.category_id : null;
            const open = st.ibOpen.has(x.id);
            let note;
            if (x.cancel) note = x.match ? `<span class="note bad">${+x.match.used_on.slice(5, 7)}/${+x.match.used_on.slice(8)} 같은 결제를 찾았어요 · 확정하면 지워요</span>`
                : '<span class="note bad">맞는 기록이 없어요 · 확정하면 알림만 지워요</span>';
            else if (sug) note = `<span class="note rec">추천 ${esc(catOf(sug.category_id).name)} · '${esc(sug.memo)}' ${sug.count}번</span>`;
            else if (x.category_id == null) note = '<span class="note">분류를 골라 주세요</span>';
            else note = rule && rule.category_id === x.category_id ? `<span class="note">규칙 "${esc(rule.pattern)}" → ${esc(catOf(x.category_id).name)}</span>` : '';
            const c = cat != null ? catOf(cat) : null;
            const row = `<div class="ib-row" data-ib-toggle role="button" tabindex="0" aria-expanded="${open}">
                ${c ? catIcon(c) : `<span class="ci none" aria-hidden="true">${x.cancel ? '↩' : '?'}</span>`}
                <span class="ib-m"><span class="shop">${esc(shop || '가게 이름 없음')}</span><small>${day} ${esc(x.used_time)} · ${esc(x.card || '카드')}${c ? ` · ${esc(c.name)}` : ''}</small></span>
                <span class="amt${x.cancel ? ' cancel' : ''}">${x.cancel ? '취소 ' : '−'}${won(x.amount)}</span>
                <button type="button" class="ib-ok" data-ib-ok aria-label="${x.cancel ? '취소 확정' : '확정'}"${!x.cancel && cat == null ? ' disabled' : ''}>✓</button>
                <button type="button" class="ib-x" data-ib-del aria-label="버리기">✕</button></div>`;
            // 접힌 채로도 분류는 바로 고를 수 있게: 분류가 없으면 줄 아래에 분류 한 줄 (옆으로 밀기)
            const quick = !x.cancel && cat == null ? `<div class="ib-quick">${expenseCats().map(c => `<span class="chip" data-ib-cat="${c.id}"
                style="background:${chipBg(c.color)};color:${chipFg(c.color)}">${esc(iconOf(c))} ${esc(c.name)}</span>`).join('')}</div>` : '';
            if (!open) return `<div class="ib" data-item="${x.id}">${row}${quick}</div>`;
            // 금액·가게 칸 오른쪽 X: 한 번에 지우고 바로 입력 (글자가 있을 때만 보임). 휴대폰은 윗줄 금액·날짜, 아랫줄 가게 한 줄 전부
            const fields = x.cancel ? '' : `<div class="edit">
                <span class="clr-wrap e-amt"><input id="ib-amount-${x.id}" data-f="amount" inputmode="numeric" value="${esc(t ? t.amount : x.amount.toLocaleString('ko-KR'))}" placeholder="금액" aria-label="금액">
                    <button type="button" class="clr" data-clear="ib-amount-${x.id}" aria-label="금액 지우기">✕</button></span>
                <span class="clr-wrap e-shop"><input id="ib-merchant-${x.id}" data-f="merchant" value="${esc(shop)}" maxlength="60" placeholder="가게 이름" aria-label="가게" autocomplete="off">
                    <button type="button" class="clr" data-clear="ib-merchant-${x.id}" aria-label="가게 이름 지우기">✕</button><div class="dd" hidden></div></span>
                <input id="ib-date-${x.id}" data-f="date" class="e-date" type="date" value="${esc(t ? t.used_on : x.used_on)}" aria-label="날짜"></div>`;
            const chips = x.cancel ? '' : `<div class="cats">${expenseCats().map(c => `<span class="chip${c.id === cat ? ' on' : ''}" data-ib-cat="${c.id}"
                style="background:${chipBg(c.color)};color:${chipFg(c.color)}"><span class="dot" style="background:${c.color}"></span>${esc(c.name)}</span>`).join(' ')}
                <span class="chip add${st.newCatFor === x.id ? ' on' : ''}" data-nb-open role="button" tabindex="0">＋ 새 분류</span></div>`;
            const newCat = st.newCatFor === x.id ? `<div class="nb">
                <input id="nb-name" value="${esc(st.newCat.name)}" maxlength="12" placeholder="새 분류 이름 (예: 생활용품)" aria-label="새 분류 이름" autocomplete="off">
                <div class="pal">${palHtml(st.newCat.color, 'data-nb-color')}</div>
                <div class="nb-act"><button type="button" class="small primary" data-nb-save>만들고 고르기</button><button type="button" class="small" data-nb-cancel>취소</button>
                    <span id="nb-prev">${nbPreviewHtml()}</span></div>
                <p class="msg" id="nb-msg">${esc(st.newCat.msg || '')}</p></div>` : '';
            const canRule = !x.cancel && cat != null && shop && !(rule && rule.category_id === cat);
            return `<div class="ib open" data-item="${x.id}">${row}<div class="body">
                ${note}${fields}${chips}${newCat}<span class="raw">${esc(x.raw)}</span>
                ${canRule ? `<div class="btns"><button type="button" class="small" data-ib-rule>"${esc(suggestPattern(shop))}"는 늘 ${esc(catOf(cat).name)}</button></div>` : ''}</div></div>`;
        }).join('');
        if (focus && $(focus)) $(focus).focus();
    }
    async function inboxPost(body) {
        $('inbox-msg').textContent = '';
        const { status, data } = await post('/api/ledger/inbox', body);
        if (status !== 200) { $('inbox-msg').textContent = msgOf(data); return null; }
        applyInbox(data);
        return data;
    }
    /** 칸을 벗어날 때: 바뀐 금액·가게·날짜를 바로 저장 (extra: 함께 바꿀 분류) */
    async function saveIbFields(id, extra) {
        const item = (st.inbox || []).find(x => x.id === id), v = ibValues(id);
        if (!item || (!ibChanged(item, v) && !extra)) { delete st.ibDirty[id]; return; }
        if (await inboxPost({ action: 'update', id, ...(ibChanged(item, v) ? v : {}), ...(extra || {}) })) delete st.ibDirty[id];
    }
    async function createIbCategory(id) {
        const name = $('nb-name').value.trim();
        st.newCat.name = name;
        const msg = t => { st.newCat.msg = t; $('nb-msg').textContent = t; };
        if (!name) return msg('이름을 넣어 주세요.');
        if (!st.newCat.color) return msg('색을 골라 주세요.');
        const { status, data } = await post('/api/ledger/category', { action: 'add', name, color: st.newCat.color, kind: 'expense' });
        if (status !== 200) return msg(msgOf(data));
        st.newCatFor = null;
        await load();                                   // 새 분류를 받아 옴 (지출 입력·다른 항목에서도 바로)
        await saveIbFields(id, { category_id: data.id });
    }
    $('inbox').addEventListener('click', async e => {
        const clear = e.target.closest('[data-clear]');
        if (clear) {
            const input = $(clear.dataset.clear);
            input.value = '';
            input.focus();
            markDirty(input);
            if (input.dataset.f === 'merchant') { st.ibDdQuiet = false; renderIbDd(input); }
            return;
        }
        const box = e.target.closest('[data-item]');
        if (!box) return;
        const id = Number(box.dataset.item), item = st.inbox.find(x => x.id === id);
        if (!item) return;
        const sw = e.target.closest('[data-nb-color]');
        if (sw) { st.newCat.color = sw.dataset.nbColor; st.newCat.msg = ''; renderInbox(); return; }
        if (e.target.closest('[data-nb-open]')) {
            st.newCatFor = st.newCatFor === id ? null : id;
            st.newCat = { name: '', color: null, msg: '' };
            renderInbox();
            if (st.newCatFor != null) $('nb-name').focus();
            return;
        }
        if (e.target.closest('[data-nb-cancel]')) { st.newCatFor = null; renderInbox(); return; }
        if (e.target.closest('[data-nb-save]')) { await createIbCategory(id); return; }
        const chip = e.target.closest('[data-ib-cat]');
        if (chip) { await saveIbFields(id, { category_id: Number(chip.dataset.ibCat) }); return; }
        if (e.target.closest('[data-ib-ok]')) {
            // 고친 금액·가게·날짜도 함께 (서버가 고친 뒤 확정)
            const v = item.cancel ? null : ibValues(id);
            if (await inboxPost({ action: 'confirm', id, ...(ibChanged(item, v) ? v : {}) })) { delete st.ibDirty[id]; st.ibOpen.delete(id); load(); }
            return;
        }
        if (e.target.closest('[data-ib-del]')) { if (await inboxPost({ action: 'discard', id })) { delete st.ibDirty[id]; st.ibOpen.delete(id); showUndo(item); } return; }
        // 줄(가게·금액)을 누르면 펼치고 접기 (칸 값은 접기 전에 저장)
        if (e.target.closest('[data-ib-toggle]')) {
            if (st.ibOpen.has(id)) { await saveIbFields(id); st.ibOpen.delete(id); } else st.ibOpen.add(id);
            renderInbox();
            return;
        }
        if (e.target.closest('[data-ib-rule]')) {
            const cat = item.category_id != null ? item.category_id : item.suggest && item.suggest.category_id;
            const v = ibValues(id);
            const { status, data } = await post('/api/ledger/rule', { action: 'add', pattern: suggestPattern(v ? v.merchant : item.merchant), category_id: cat });
            if (status !== 200) { $('inbox-msg').textContent = msgOf(data); return; }
            applyInbox(data);
        }
    });
    // 칸을 벗어나면(또는 날짜를 고르면) 바로 저장
    $('inbox').addEventListener('change', e => {
        if (!e.target.dataset || !e.target.dataset.f) return;
        saveIbFields(Number(e.target.closest('[data-item]').dataset.item));
    });
    // 대기함 가게 칸 자동완성: 누르면 최근 메모, 치면 지난 메모 전체에서. 고르면 가게 이름이 그 메모로,
    // 분류를 아직 안 골랐으면(추천 포함) 그 메모의 지출 분류도 함께
    st.ibDdIndex = -1;
    const isShop = el => !!el && !!el.dataset && el.dataset.f === 'merchant';
    const ddOf = input => input.parentElement.querySelector('.dd');
    function renderIbDd(input) {
        if (!isShop(input)) return;
        const dd = ddOf(input), list = memoSearch(input.value, 'expense');
        // 고른 직후(다시 그려 커서가 돌아와도)는 닫아 둠, 다시 치거나 누르면 열림
        if (!list.length || document.activeElement !== input || st.ibDdQuiet) { dd.hidden = true; return; }
        dd.innerHTML = (input.value.trim() ? '' : '<div class="dd-h">최근 메모</div>')
            + list.map((m, i) => memoItemHtml(m, input.value, `data-ibmemo="${i}"`, i === st.ibDdIndex)).join('');
        dd.hidden = false;
    }
    async function useIbMemo(i, input) {
        const m = memoSearch(input.value, 'expense')[i];
        if (!m) return;
        input.value = m.memo;
        ddOf(input).hidden = true;
        st.ibDdIndex = -1;
        st.ibDdQuiet = true;
        markDirty(input);
        const id = Number(input.closest('[data-item]').dataset.item), item = (st.inbox || []).find(x => x.id === id);
        const useCat = item && !item.cancel && item.category_id == null && st.data.categories.some(c => c.id === m.category_id && c.kind === 'expense');
        await saveIbFields(id, useCat ? { category_id: m.category_id } : null);
    }
    $('inbox').addEventListener('focusin', e => { if (isShop(e.target)) { st.ibDdIndex = -1; renderIbDd(e.target); } });
    $('inbox').addEventListener('pointerdown', e => { if (isShop(e.target)) { st.ibDdQuiet = false; const t = e.target; setTimeout(() => renderIbDd(t), 0); } });
    $('inbox').addEventListener('focusout', e => { if (isShop(e.target)) ddOf(e.target).hidden = true; });
    $('inbox').addEventListener('keydown', e => {
        if (e.target.id === 'nb-name' && e.key === 'Enter') { e.preventDefault(); createIbCategory(Number(e.target.closest('[data-item]').dataset.item)); return; }
        if (!e.target.dataset || !e.target.dataset.f) return;
        const open = isShop(e.target) && !ddOf(e.target).hidden;
        if (!open) { if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } return; }   // Enter: 칸을 벗어나 저장
        const n = memoSearch(e.target.value, 'expense').length;
        if (e.key === 'ArrowDown' && n) { st.ibDdIndex = Math.min(n - 1, st.ibDdIndex + 1); renderIbDd(e.target); e.preventDefault(); }
        else if (e.key === 'ArrowUp' && n) { st.ibDdIndex = Math.max(0, st.ibDdIndex - 1); renderIbDd(e.target); e.preventDefault(); }
        else if (e.key === 'Enter') { e.preventDefault(); if (st.ibDdIndex >= 0) useIbMemo(st.ibDdIndex, e.target); else { ddOf(e.target).hidden = true; e.target.blur(); } }
        else if (e.key === 'Escape') { ddOf(e.target).hidden = true; }
    });
    // 누르는 순간 가게 칸에서 포커스가 빠져 목록이 닫히지 않게 mousedown에서 고름
    $('inbox').addEventListener('mousedown', e => {
        const b = e.target.closest('[data-ibmemo]');
        if (b) { e.preventDefault(); useIbMemo(Number(b.dataset.ibmemo), b.closest('.clr-wrap').querySelector('input')); }
    });
    $('inbox').addEventListener('input', e => {
        if (e.target.id === 'nb-name') { st.newCat.name = e.target.value; st.newCat.msg = ''; $('nb-prev').innerHTML = nbPreviewHtml(); return; }
        if (!e.target.dataset || !e.target.dataset.f) return;
        markDirty(e.target);
        if (isShop(e.target)) { st.ibDdIndex = -1; st.ibDdQuiet = false; renderIbDd(e.target); return; }
        if (e.target.dataset.f !== 'amount') return;
        const v = e.target.value.replace(/[^0-9]/g, '').slice(0, 10);
        e.target.value = v ? Number(v).toLocaleString('ko-KR') : '';
    });
    $('inbox-all').addEventListener('click', async () => {
        const data = await inboxPost({ action: 'confirm_all' });
        if (data) { $('inbox-msg').textContent = data.confirmed ? '' : '분류를 고른 결제가 없어요'; load(); }
    });

    // ---- YeYe홈 앱 안에서 열었을 때 (앱이 window.LedgerApp을 넣어 줌)
    const inApp = !!window.LedgerApp;
    if (inApp) document.documentElement.classList.add('in-app');
    const appConnected = () => { try { return !!window.LedgerApp.connected(); } catch (e) { return false; } };
    function renderAppConnect() {
        if (!inApp) return;
        const on = appConnected();
        $('app-hint').hidden = on;
        let ver = '';
        try { ver = window.LedgerApp.version(); } catch (e) { /* 예전 앱 */ }
        $('app-connect-state').textContent = on ? `✓ 이 휴대폰 앱(${ver})이 결제 알림을 보내고 있어요` : '이 휴대폰 앱은 아직 연결되지 않았어요';
        $('app-connect-btn').textContent = on ? '다시 연결' : '이 휴대폰 앱에 연결';
        $('app-connect-btn').className = on ? 'small' : 'primary';
    }
    $('phone-settings-btn').addEventListener('click', () => {
        try { if (window.LedgerApp.openPhoneSettings) window.LedgerApp.openPhoneSettings(); else window.LedgerApp.openSettings(); } catch (e) { /* 예전 앱 */ }
    });
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
    $('hook-test').addEventListener('click', async () => {
        if (!await inboxPost({ action: 'test' })) return;
        closeSettings();
        setTimeout(() => $('inbox-sec').scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
    });
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
    // ---- YeYe홈 앱 받기 (앱 밖에서만 보임). 올리기는 전체 설정(/yeye/#settings)으로 옮김
    const kb = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`;
    function renderApp(app) {
        $('app-get').hidden = !app;
        $('app-none').hidden = !!app;
        const text = app ? `${app.versionName} · ${kb(app.size)} · ${app.uploaded_at.slice(5, 10).replace('-', '/')} 올림` : '';
        $('app-info').textContent = text;
    }
    // ---- 앱의 뒤로가기: 열려 있는 것을 하나 닫으면 true (닫을 게 없으면 false → 앱이 '한 번 더 누르면 종료' 안내)
    window.ledgerBack = () => {
        if ($('app').classList.contains('settings-open')) { closeSettings(); return true; }
        if (!$('memo-dd').hidden) { $('memo-dd').hidden = true; return true; }
        if (st.popFor != null) { st.popFor = null; renderCats(); return true; }
        if (!$('addbox').hidden) { $('addbox').hidden = true; return true; }
        if (st.catEditing) { st.catEditing = false; renderCats(); return true; }
        if (!$('sheet-wrap').hidden) { closeEntry(); return true; }
        if (st.newCatFor != null) { st.newCatFor = null; renderInbox(); return true; }
        const swiped = $('list').querySelector('.sw-row.open');
        if (swiped) { swiped.classList.remove('open'); return true; }
        return false;
    };
    // ==========================================
    // 설정 (머리줄 '설정' → 같은 페이지의 #settings): 결제 알림 연결 · 가게 규칙 · 버린 알림 · 사용자 허락 · 앱 파일(관리자)
    // 주소에 #settings를 한 칸 넣어 두므로 브라우저·앱의 뒤로가기로 메인에 돌아옴
    // ==========================================
    function renderSetTabs() {
        const admin = !!(st.me && st.me.admin);
        if (!admin && st.setTab === 'users') st.setTab = 'hook';
        const tab = st.setTab || 'hook';
        document.querySelectorAll('#set-view .set-tab').forEach(b => {
            if (b.classList.contains('admin-only')) b.hidden = !admin;
            b.classList.toggle('on', b.dataset.tab === tab);
            b.setAttribute('aria-selected', String(b.dataset.tab === tab));
        });
        document.querySelectorAll('#set-view .set-pane').forEach(p => { p.hidden = p.dataset.pane !== tab; });
    }
    function showSettings(on) {
        $('app').classList.toggle('settings-open', on);
        if (on) { renderSetTabs(); window.scrollTo(0, 0); }
    }
    // 앱(YeYe홈)이 부름: 위쪽 '설정' → 가계부 설정 (로그인 전이면 false → 앱이 자기 설정을 엶)
    window.appOpenSettings = () => { if (!st.me) return false; openSettings(); return true; };
    // 홈 탭의 '확인 대기함 n건'을 눌러 왔을 때 (#inbox)
    window.appShowInbox = () => {
        if (location.hash === '#inbox') history.replaceState(history.state, '', location.pathname + location.search);
        if (st.me && $('app').classList.contains('settings-open')) closeSettings();
        let n = 20;
        (function t() { const e = $('inbox-sec'); if (e && !e.hidden) e.scrollIntoView({ block: 'start' }); else if (n-- > 0) setTimeout(t, 300); })();
    };
    function openSettings(tab) {
        if (tab) st.setTab = tab;
        if (location.hash !== '#settings') {
            const s = history.state || {};
            history.pushState({ ...s, navDepth: (s.navDepth || 0) + 1, ledgerSettings: 1 }, '', '#settings');
        }
        showSettings(true);
    }
    function closeSettings() {
        if (location.hash === '#settings' && (history.state || {}).ledgerSettings) history.back();
        else {
            if (location.hash === '#settings') history.replaceState(history.state, '', location.pathname + location.search);
            showSettings(false);
        }
    }
    window.addEventListener('popstate', () => { if (st.me) showSettings(location.hash === '#settings'); });
    $('set-open').addEventListener('click', () => {
        // 허락을 기다리는 사람이 있으면 그 탭부터
        openSettings(!$('set-dot').hidden ? 'users' : null);
    });
    $('set-back').addEventListener('click', closeSettings);
    $('app-hint-btn').addEventListener('click', () => openSettings('hook'));
    document.querySelector('#set-view .set-tabs').addEventListener('click', e => {
        const b = e.target.closest('.set-tab');
        if (!b) return;
        st.setTab = b.dataset.tab;
        renderSetTabs();
    });

    // 다른 화면에 갔다 오면(휴대폰에서 결제 뒤 열었을 때 등) 대기함을 새로
    document.addEventListener('visibilitychange', () => { if (!document.hidden && st.me) loadInbox(); });
    setInterval(() => { if (!document.hidden && st.me) loadInbox(); }, 60000);

    boot();
})();
