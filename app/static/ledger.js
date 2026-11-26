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
    const ICONS = ['🍚', '☕', '🍺', '🍜', '🍕', '🍗', '🍔', '🍣', '🍞', '🍰', '🍦', '🍎', '🧋', '🍷', '🏪', '🧺', '🏠', '💡', '📦', '🧴', '🧻', '🧹', '🛋️', '🔧', '💧', '🔥', '🌱', '🛍️', '💄', '👕', '👟', '👜', '💇', '🚌', '🚗', '✈️', '🚕', '🚇', '🚄', '⛽', '🅿️', '💊', '🏥', '🦷', '🏋️', '🎬', '📚', '🎮', '🎵', '🎤', '⚽', '⛳', '🏕️', '📺', '🎁', '👶', '🐶', '🎉', '💝', '💐', '🎂', '💒', '🙏', '🐱', '💳', '💰', '💵', '🏦', '🐷', '📈', '🛡️', '🧾', '💸', '📱', '💻', '💼'];
    const GUESS = [[/식|밥|외식|배달/, '🍚'], [/카페|커피/, '☕'], [/교통|버스|지하철|택시/, '🚌'], [/생활|마트|장보/, '🧺'], [/쇼핑|옷/, '🛍️'],
        [/의료|병원|약|건강/, '💊'], [/주거|월세|관리비|집/, '🏠'], [/통신|휴대폰|폰/, '📱'], [/경조|선물/, '🎁'], [/문화|여가|취미|영화/, '🎬'],
        [/교육|학원|책/, '📚'], [/반려|강아지|고양이|펫/, '🐶'], [/여행/, '✈️'], [/차|주유|주차/, '🚗'], [/공과|전기|가스|수도/, '💡'], [/술/, '🍺'],
        [/미용|화장/, '💄'], [/육아|아이/, '👶'], [/급여|월급/, '💰'], [/부수입/, '💵'], [/용돈/, '🎉'], [/이자|환급/, '🏦'],
        [/치킨/, '🍗'], [/피자/, '🍕'], [/간식|디저트/, '🍰'], [/빵/, '🍞'], [/과일/, '🍎'], [/편의점/, '🏪'], [/운동|헬스/, '🏋️'], [/치과/, '🦷'],
        [/게임/, '🎮'], [/구독|OTT|넷플릭스/i, '📺'], [/보험/, '🛡️'], [/저축|적금/, '🐷'], [/투자|주식/, '📈'], [/세금/, '🧾'], [/대출/, '💸'],
        [/기부|헌금/, '🙏'], [/데이트/, '💝'], [/꽃/, '💐'], [/생일/, '🎂']];
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
        addColor: null, addIcon: '', editId: null, ddIndex: -1,
        // 설정 > 분류: 고치는 분류(cedFor), 추가하는 쪽(caddKind)과 그 값
        cedFor: null, caddKind: null, cadd: { name: '', icon: '', color: null, msg: '' },
        // view: 아래 보기(list 내역·cal 달력·ana 분석), ibOpen: 펼쳐 고치는 대기함 항목
        view: 'list', ibOpen: new Set(),
        // 입력 창의 사진: items [{id}(올린 것) | {full, thumb, url}(저장할 때 올릴 것)], removed: 저장할 때 뺄 사진 id
        ph: { items: [], removed: [] }, histFor: null,
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
        $('who-me').hidden = $('logout').hidden = $('set-open').hidden = true;
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
        $('who-me').hidden = $('logout').hidden = false;
        setUsedOn(ymd(new Date()));
        $('set-open').hidden = false;
        renderSetTabs();
        if (location.hash.startsWith('#settings')) { st.setTab = location.hash.split('/')[1] || null; showSettings(true); }
        if (user.admin) loadPeople();
        load();
        loadInbox();
        if (location.hash === '#inbox') showInboxPage();
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
        st.loadedAt = Date.now();
        if (st.totView === 'month') loadYear();
        renderAuto();
        for (const kind of ['expense', 'income']) {
            const list = data.categories.filter(c => c.kind === kind);
            if (!list.some(c => c.id === st.sels[kind])) st.sels[kind] = list.length ? list[0].id : null;
        }
        render();
        renderRecurring();
        // 대기함이 먼저 와서 분류 목록 없이 칸만 열렸으면 이제 내용까지 (알림을 눌러 열 때 기록 쪽이 늦게 오는 일이 잦음)
        if (st.inbox) renderInbox();
        openPending();
        if (st.search && st.search.q) runSearch();   // 찾은 기록을 고치거나 지웠으면 결과도 새로
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
    const recOf = id => ((st.data && st.data.recurring) || []).find(r => r.id === id);

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
    // 아래 메뉴: 내역·달력·분석 (설정이 열려 있으면 '설정'이 켜짐)
    function renderViews() {
        const on = $('app').classList.contains('settings-open') ? 'set' : st.view;
        document.querySelectorAll('#views [data-view]').forEach(b => {
            b.classList.toggle('on', b.dataset.view === on);
            if (b.dataset.view === on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
        });
        document.querySelectorAll('#app .pane').forEach(p => { p.hidden = p.dataset.pane !== st.view; });
    }
    $('views').addEventListener('click', e => {
        const b = e.target.closest('[data-view]');
        if (!b) return;
        if (inboxOpen()) closeInbox();
        if (b.dataset.view === 'set') { if (!$('app').classList.contains('settings-open')) openSettings(); else if (st.setTab) setBack(); return; }
        if ($('app').classList.contains('settings-open')) closeSettings();
        if (st.view !== b.dataset.view) window.scrollTo(0, 0);
        st.view = b.dataset.view;
        renderViews();
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
        $('edit-delete').hidden = !editing;
    }

    function chipHtml(c, extra) {
        return `<span class="dot" style="background:${c.color}"></span>${esc(c.name)}${extra || ''}`;
    }
    function renderCats() {
        const cats = kindCats();
        // 고른 분류 한 칸: 그림 · 이름 ⌄ (없으면 '골라 주세요'), 목록은 st.catOpen일 때만
        const cur = cats.find(c => c.id === selected());
        $('cat-pick').innerHTML = cur ? `${catIcon(cur)}<span class="cn" style="color:${chipFg(cur.color)}">${esc(cur.name)}</span><span class="chev" aria-hidden="true">⌄</span>`
            : `<span class="cn none">${st.kind === 'income' ? '수입 종류를 골라 주세요' : '분류를 골라 주세요'}</span><span class="chev" aria-hidden="true">⌄</span>`;
        $('cat-pick').style.background = cur ? chipBg(cur.color) : '';
        $('cat-pick').classList.toggle('open', !!st.catOpen);
        $('cat-pick').setAttribute('aria-expanded', String(!!st.catOpen));
        $('cat-list').hidden = !st.catOpen;
        $('cats').innerHTML = cats.map(c => `<span class="chip${c.id === selected() ? ' on' : ''}" data-cat="${c.id}" role="button" tabindex="0"
                style="color:${chipFg(c.color)}">${catIcon(c)}<span class="cn">${esc(c.name)}</span></span>`).join('')
            + '<span class="chip add" id="cat-add" role="button" tabindex="0"><span class="ci">＋</span><span class="cn">추가</span></span>';
        if (st.me) renderCatAdmin();
    }
    function palHtml(current, attr) {
        const cur = (current || '').toUpperCase();
        return PRESET.map(h => `<button type="button" class="sw${cur === h ? ' on' : ''}" ${attr}="${h}" style="background:${h}" aria-label="${h}">${cur === h ? '✓' : ''}</button>`).join('');
    }
    function iconsHtml(current, attr) {
        return ICONS.map(i => `<button type="button" class="ic${current === i ? ' on' : ''}" ${attr}="${i}" aria-label="${i}">${i}</button>`).join('');
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
        // 지난달과 비교 (달로 볼 때만): 지출 합계 차이
        const prev = prevScope();
        $('m-cmp').hidden = !prev;
        if (prev) {
            const d = exSum - prev.filter(e => kindOf(e) === 'expense').reduce((t, e) => t + e.amount, 0);
            const than = prev.sameDay ? `지난달 ${prev.sameDay}일까지보다` : '지난달보다';
            $('m-cmp').innerHTML = !d ? `<b class="cmp-eq">${than} 같아요</b>`
                : `<b class="${d > 0 ? 'cmp-up' : 'cmp-dn'}">${d > 0 ? '▲' : '▼'} ${won(Math.abs(d))}</b> ${than} ${d > 0 ? '더 썼어요' : '덜 썼어요'}`;
        }
        // 분석: 고른 쪽(지출·수입)의 분류별 합계 (지난달 그 분류와 차이·눈금)
        const sums = new Map(), prevSums = new Map();
        scope.filter(e => kindOf(e) === st.ana).forEach(e => sums.set(e.category_id, (sums.get(e.category_id) || 0) + e.amount));
        if (prev) prev.filter(e => kindOf(e) === st.ana).forEach(e => prevSums.set(e.category_id, (prevSums.get(e.category_id) || 0) + e.amount));
        const parts = [...sums.entries()].sort((a, b) => b[1] - a[1]);
        const total = parts.reduce((t, p) => t + p[1], 0);
        renderDonut(parts, total, whoName ? `${whoName} ${st.ana === 'income' ? '수입' : '지출'}` : st.ana === 'income' ? '수입' : '지출');
        const income = st.ana === 'income';
        const diffOf = id => {
            if (!prev) return '';
            const p = prevSums.get(id) || 0, d = sums.get(id) - p;
            if (!p) return '<span class="d cmp-up">새로</span>';
            if (Math.abs(d) < Math.max(1000, p * 0.05)) return '<span class="d cmp-eq">비슷</span>';
            // 지출은 더 쓰면 빨강, 수입은 더 들어오면 초록
            return `<span class="d ${(d > 0) !== income ? 'cmp-up' : 'cmp-dn'}">${d > 0 ? '▲' : '▼'}${shortWon(Math.abs(d))}</span>`;
        };
        $('legend').innerHTML = parts.length ? parts.map(([id, v]) => {
            const c = catOf(id), pct = Math.round(v / total * 100), p = prevSums.get(id) || 0;
            const tick = prev && p ? `<u style="left:${Math.min(100, p / total * 100).toFixed(1)}%" title="지난달 ${won(p)}"></u>` : '';
            return `<div class="lg"><div class="lg-top">${catIcon(c)}<span class="n">${esc(c.name)}</span>${diffOf(id)}
                <span class="p">${pct}%</span><span class="w">${won(v)}</span></div><div class="lg-bar"><i style="width:${pct}%;background:${c.color}"></i>${tick}</div></div>`;
        }).join('') + (prev ? `<p class="lg-note">눈금 = 지난달${prev.sameDay ? ` ${prev.sameDay}일까지` : ''} 그 분류 · ▲ 늘어남 ▼ 줄어듦</p>` : '')
            : `<p class="empty">${st.ana === 'income' ? '수입' : '지출'} 기록이 없어요</p>`;
        renderList(list);
    }

    // 비교할 지난달 기록 (사람 거르기를 따름). 이번 달을 보는 중이면 지난달도 오늘 날짜까지만(sameDay), 일별로 볼 때는 비교 안 함(null)
    function prevScope() {
        const p = st.data.prev;
        if (st.mode !== 'month' || !p || p.month === ym(st.day)) return null;
        const now = new Date(), current = ym(st.day) === ym(now);
        const list = p.entries.filter(e => (!st.who || e.user_id === st.who) && (!current || +e.used_on.slice(8) <= now.getDate()));
        list.sameDay = current ? now.getDate() : 0;
        return list;
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
            return head + items.map(e => rowHtml(e)).join('');
        }).join('');
    }
    // 기록 한 줄 (내역·찾기 결과). mark: 찾은 글자를 노랗게, dated: 둘째 줄 앞에 날짜
    function rowHtml(e, mark, dated) {
        const c = catOf(e.category_id), mine = canEdit(e), income = c.kind === 'income';
        const hl = s => mark ? markText(s, mark) : esc(s);
        const day = dated ? `<span class="cat">${+e.used_on.slice(5, 7)}/${+e.used_on.slice(8)}</span><span class="sep">·</span>` : '';
        return `<div class="sw-row">
            <div class="it u${mine ? ' mine' : ''}${st.editId === e.id ? ' editing' : ''}" data-entry="${e.id}" style="${userTint(e.user_id)}"${mine ? ' role="button" tabindex="0"' : ''}>
            ${catIcon(c)}<span class="txt"><span class="memo${e.memo ? '' : ' no-memo'}">${hl(e.memo || c.name)}</span>
            <span class="line2">${day}${e.recurring_id ? '<span class="rp-mark" title="매달 반복">🔁</span>' : ''}<span class="cat">${hl(c.name)}</span><span class="sep">·</span>${whoTag(e.user_id)}</span></span>
            ${thumbHtml(e)}<span class="amt ${income ? 'plus' : 'minus'}">${income ? '+' : '−'}${won(e.amount)}</span></div></div>`;
    }
    // 사진이 있는 기록: 첫 사진 썸네일 (+남은 장 수). 누르면 크게 보기
    const photoUrl = (id, thumb) => `/api/ledger/photo/${id}${thumb ? '_t' : ''}.jpg`;
    function thumbHtml(e) {
        const ps = e.photos || [];
        if (!ps.length) return '';
        return `<button type="button" class="ph-th" data-view="${e.id}" aria-label="사진 ${ps.length}장 보기"><img src="${photoUrl(ps[0], true)}" alt="" loading="lazy">${ps.length > 1 ? `<b>+${ps.length - 1}</b>` : ''}</button>`;
    }
    // 찾은 글자를 노랗게 (띄어쓰기·대소문자 무시하고 맞춘 자리)
    function markText(s, q) {
        const key = q.replace(/\s+/g, '').toLowerCase();
        if (!key) return esc(s);
        const chars = [...s], flat = [], pos = [];
        chars.forEach((ch, i) => { if (!/\s/.test(ch)) { flat.push(ch.toLowerCase()); pos.push(i); } });
        const at = flat.join('').indexOf(key);
        if (at < 0) return esc(s);
        const a = pos[at], b = pos[at + [...key].length - 1] + 1;
        return esc(chars.slice(0, a).join('')) + `<mark>${esc(chars.slice(a, b).join(''))}</mark>` + esc(chars.slice(b).join(''));
    }

    // ==========================================
    // 모든 달에서 찾기: 치는 대로 잠깐 기다렸다가 서버에서 (메모·분류 이름·금액). 달마다 묶어 건수·합계
    // ==========================================
    function openSearch(on) {
        st.search = on ? (st.search || { q: '', entries: [], more: false }) : null;
        $('app').classList.toggle('searching', on);
        $('search-sec').hidden = !on;
        if (on) { window.scrollTo(0, 0); $('search-q').focus(); renderSearch(); }
        else { $('search-q').value = ''; render(); }
    }
    async function runSearch() {
        if (!st.search) return;
        const q = $('search-q').value.trim();
        if (!q) { st.search = { q: '', entries: [], more: false }; renderSearch(); return; }
        const seq = (st.searchSeq = (st.searchSeq || 0) + 1);
        const { status, data } = await get(`/api/ledger/search?q=${encodeURIComponent(q)}`);
        if (seq !== st.searchSeq || !st.search) return;   // 그 사이 더 쳤거나 닫음
        if (status === 401) { showAuth('login'); return; }
        if (status !== 200) { $('search-sum').textContent = '찾지 못했어요. 잠시 뒤 다시 해 주세요.'; return; }
        st.search = data;
        renderSearch();
    }
    function renderSearch() {
        const s = st.search;
        if (!s) return;
        if (!s.q) { $('search-sum').textContent = '모든 달의 기록에서 메모·가게·분류 이름·금액으로 찾아요.'; $('search-list').innerHTML = ''; return; }
        const list = s.entries;
        if (!list.length) { $('search-sum').textContent = ''; $('search-list').innerHTML = `<p class="empty">'${esc(s.q)}'에 맞는 기록이 없어요</p>`; return; }
        const sum = kind => list.filter(e => kindOf(e) === kind).reduce((t, e) => t + e.amount, 0);
        const ex = sum('expense'), inc = sum('income');
        const months = [...new Set(list.map(e => e.used_on.slice(0, 7)))];
        const thisYear = String(new Date().getFullYear());
        const monthName = m => `${m.slice(0, 4) === thisYear ? '' : `${m.slice(0, 4)}년 `}${+m.slice(5)}월`;
        const span = months.length > 1 ? ` · ${monthName(months[months.length - 1])}~${monthName(months[0])}` : '';
        $('search-sum').textContent = `${list.length}건${s.more ? '+ (최근 것만)' : ''}${ex ? ` · 지출 ${won(ex)}` : ''}${inc ? ` · 수입 ${won(inc)}` : ''}${span}`;
        $('search-list').innerHTML = months.map(m => {
            const items = list.filter(e => e.used_on.startsWith(m));
            const net = items.reduce((t, e) => t + (kindOf(e) === 'income' ? e.amount : -e.amount), 0);
            const [y, mo] = m.split('-').map(Number);
            return `<div class="mh"><b>${y === new Date().getFullYear() ? '' : `${y}년 `}${mo}월</b><span class="net">${signed(net)}</span></div>`
                + items.map(e => rowHtml(e, s.q, true)).join('');
        }).join('');
    }
    $('search-open').addEventListener('click', () => openSearch(true));
    $('search-close').addEventListener('click', () => openSearch(false));
    let searchWait = 0;
    $('search-q').addEventListener('input', () => { clearTimeout(searchWait); searchWait = setTimeout(runSearch, 250); });
    $('search-q').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); clearTimeout(searchWait); runSearch(); $('search-q').blur(); } });
    $('search-list').addEventListener('click', e => {
        const view = e.target.closest('[data-view]');
        if (view) { const x = st.search && st.search.entries.find(y => y.id === Number(view.dataset.view)); if (x) openViewer(x.photos.map(id => photoUrl(id)), 0); return; }
        const b = e.target.closest('[data-entry]');
        const entry = b && st.search && st.search.entries.find(x => x.id === Number(b.dataset.entry));
        if (entry && canEdit(entry)) startEdit(entry);
    });
    $('search-list').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.it.mine')) { e.preventDefault(); e.target.click(); } });

    // 홈 탭 '최근 기록'에서 눌러 옴 (/ledger/?entry=id&day=YYYY-MM-DD): 그 달로 가서 내 기록이면 고치기, 아니면 그 줄을 반짝
    const opening = (() => {
        const q = new URLSearchParams(location.search), id = Number(q.get('entry')), day = q.get('day') || '';
        if (!id) return null;
        history.replaceState(history.state, '', location.pathname + location.hash);
        return /^\d{4}-\d{2}-\d{2}$/.test(day) ? { id, day } : { id, day: '' };
    })();
    if (opening && opening.day) { const [y, m, d] = opening.day.split('-').map(Number); st.day = new Date(y, m - 1, d); st.mode = 'month'; }
    function openPending() {
        if (!opening || opening.done) return;
        opening.done = true;
        const entry = st.data.entries.find(x => x.id === opening.id);
        if (!entry) return;
        st.view = 'list';
        st.type = 'all';
        st.who = 0;
        render();
        if (canEdit(entry)) { startEdit(entry); return; }
        const row = $('list').querySelector(`[data-entry="${entry.id}"]`);
        if (row) { row.scrollIntoView({ block: 'center' }); row.classList.add('flash'); }
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
        st.catOpen = false;
        document.documentElement.classList.remove('sheet-open');
        $('memo-dd').hidden = true;
        $('addbox').hidden = true;
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
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && $('pv').hidden && !$('sheet-wrap').hidden && $('memo-dd').hidden) closeEntry(); });
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
        setPhotos([]);
        st.histFor = null;
        $('hist').hidden = true;
        showHist(false);
        resetRepeat(null);
    }

    $('save').addEventListener('click', async () => {
        const amount = amountValue();
        if (!amount) { $('entry-msg').textContent = '금액을 넣어 주세요.'; $('amount').focus(); return; }
        if (selected() == null) { $('entry-msg').textContent = st.kind === 'income' ? '수입 종류를 골라 주세요.' : '소비형태를 골라 주세요.'; st.catOpen = true; renderCats(); return; }
        const body = { amount, used_on: $('used-on').value || ymd(new Date()), category_id: selected(), memo: $('memo').value.trim() };
        const editing = st.editId != null;
        if (!$('rp-new').hidden && $('rp-check').checked) body.repeat_day = Number($('rp-day').value);
        // 반복이 넣은 기록: 금액·분류·메모를 바꿨고 '다음 달부터도'면 반복도 같이 (날짜만 바꾼 것은 그 달만)
        const o = st.rpOrig;
        if (editing && !$('rp-linked').hidden && $('rp-future').checked && o
            && (o.amount !== body.amount || o.category_id !== body.category_id || (o.memo || '') !== body.memo)) body.apply_future = true;
        $('save').disabled = true;
        const { status, data } = await post('/api/ledger/entry', editing ? { action: 'edit', id: st.editId, ...body } : { action: 'add', ...body });
        if (status !== 200) $('save').disabled = false;
        if (status === 401) { showAuth('login'); return; }
        if (status !== 200) { $('entry-msg').textContent = msgOf(data); return; }
        if (st.ph.busy) { $('save').textContent = '사진 준비 중…'; await st.ph.busy; }
        const failed = await savePhotos(editing ? st.editId : data.id);
        $('save').disabled = false;
        $('save').textContent = '저장';
        if (failed) window.alert(`기록은 저장했지만 ${failed}`);
        clearForm();
        closeEntry();
        await load();
    });
    $('amount').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); $('save').click(); } });

    function startEdit(entry) {
        st.editId = entry.id;
        st.kind = kindOf(entry);
        st.sels[st.kind] = entry.category_id;
        $('addbox').hidden = true;
        $('amount').value = entry.amount.toLocaleString('ko-KR');
        setUsedOn(entry.used_on);
        $('memo').value = entry.memo || '';
        $('entry-msg').textContent = '';
        setPhotos((entry.photos || []).map(id => ({ id })));
        resetRepeat(entry);
        loadHistory(entry.id);
        render();
        openEntry();
    }

    // ---------- 매달 반복: 새 기록·반복이 아닌 기록은 '🔁 매달 반복' + 매월 며칠(처음엔 날짜 칸의 날),
    // 반복 결제가 넣은 기록은 '매월 25일 반복 · 반복 결제 고치기 ›'와 '다음 달부터도 이 금액·분류·메모로'
    $('rp-day').innerHTML = Array.from({ length: 31 }, (_, i) => `<option value="${i + 1}">${i + 1}</option>`).join('');
    const usedDay = () => +(($('used-on').value || ymd(new Date())).slice(8)) || 1;
    function resetRepeat(entry) {
        const rec = entry && entry.recurring_id ? recOf(entry.recurring_id) : null;
        st.rpDayTouched = false;
        st.rpFor = rec ? rec.id : null;
        st.rpOrig = entry ? { amount: entry.amount, category_id: entry.category_id, memo: entry.memo || '' } : null;
        $('rp-check').checked = false;
        $('rp-day-wrap').hidden = true;
        $('rp-new').hidden = !!rec;
        $('rp-linked').hidden = !rec;
        $('rp-future').checked = true;
        if (rec) $('rp-linked-text').textContent = `🔁 매월 ${rec.day}일 반복${rec.paused ? ' (멈춤)' : ''}`;
    }
    function setRepeat(on) {
        $('rp-check').checked = on;
        $('rp-day-wrap').hidden = !on;
        if (on && !st.rpDayTouched) $('rp-day').value = String(usedDay());
    }
    $('rp-check').addEventListener('change', () => setRepeat($('rp-check').checked));
    $('rp-day').addEventListener('change', () => { st.rpDayTouched = true; });
    for (const ev of ['input', 'change']) $('used-on').addEventListener(ev, () => { if ($('rp-check').checked && !st.rpDayTouched) $('rp-day').value = String(usedDay()); });
    $('rp-open').addEventListener('click', () => {
        const id = st.rpFor;
        closeEntry();
        st.recOpen = id;
        openSettings('repeat');
        renderRecurring();
    });

    // 설정 > 반복 결제: 한 줄씩 (아이콘 · 메모 · '매월 25일 · 분류 · 사람 · 다음 12/25'(멈춘 것은 '멈춤') · 금액).
    // 만든 사람·관리자는 줄을 누르면 금액·날·분류·메모 고치기 · 멈추기/다시 시작 · 지우기
    function renderRecurring() {
        if (!st.data) return;
        const list = st.data.recurring || [];
        $('row-repeat').textContent = list.length || '';
        if (!list.some(r => r.id === st.recOpen)) st.recOpen = null;
        if (!list.length) { $('rec-list').innerHTML = `<p class="none">아직 없어요. 입력 창에서 '🔁 매달 반복'을 켜거나 아래 버튼으로 만들어요.</p>`; return; }
        $('rec-list').innerHTML = list.map(r => {
            const c = catOf(r.category_id), income = c.kind === 'income', mine = canEdit(r);
            const next = r.paused ? '<span class="rec-paused">멈춤</span>' : `다음 ${md(r.next_on)}`;
            return `<div class="rec-row${r.paused ? ' paused' : ''}${st.recOpen === r.id ? ' open' : ''}" data-rec="${r.id}"${mine ? ' role="button" tabindex="0"' : ''}>
                ${catIcon(c)}<span class="n"><b>${esc(r.memo || c.name)}</b><small>매월 ${r.day}일 · ${esc(c.name)} · ${esc(nameOf(r.user_id))} · ${next}</small></span>
                <span class="amt ${income ? 'plus' : 'minus'}">${income ? '+' : '−'}${won(r.amount)}</span></div>`
                + (st.recOpen === r.id && mine ? recEditHtml(r) : '');
        }).join('');
    }
    function recEditHtml(r) {
        const kind = catOf(r.category_id).kind || 'expense';
        const cats = st.data.categories.filter(c => c.kind === kind)
            .map(c => `<option value="${c.id}"${c.id === r.category_id ? ' selected' : ''}>${esc(iconOf(c))} ${esc(c.name)}</option>`).join('');
        const days = Array.from({ length: 31 }, (_, i) => `<option value="${i + 1}"${i + 1 === r.day ? ' selected' : ''}>${i + 1}</option>`).join('');
        return `<div class="ced rec-ed">
            <div class="rec-f"><input id="rec-amount" inputmode="numeric" value="${r.amount.toLocaleString('ko-KR')}" aria-label="금액" autocomplete="off"><span>원</span></div>
            <div class="rec-f"><span>매월</span><select id="rec-day" aria-label="반복할 날">${days}</select><span>일</span><select id="rec-cat" aria-label="분류">${cats}</select></div>
            <input id="rec-memo" value="${esc(r.memo)}" maxlength="60" placeholder="메모" aria-label="메모" autocomplete="off">
            <div class="ced-act"><button type="button" class="primary" data-rec-save>저장</button><button type="button" data-rec-pause>${r.paused ? '다시 시작' : '멈추기'}</button><button type="button" class="danger" data-rec-del>지우기</button></div>
            <p class="msg" id="rec-msg"></p></div>`;
    }
    async function recPost(body) {
        const { status, data } = await post('/api/ledger/recurring', body);
        if (status === 401) { showAuth('login'); return false; }
        if (status !== 200) { if ($('rec-msg')) $('rec-msg').textContent = msgOf(data); return false; }
        await load();   // 고친 날이 이미 지나 바로 들어간 기록도 내역에
        return true;
    }
    $('rec-list').addEventListener('click', async e => {
        const id = st.recOpen, r = recOf(id);
        if (e.target.closest('[data-rec-save]')) {
            const amount = parseInt($('rec-amount').value.replace(/[^0-9]/g, ''), 10) || 0;
            if (!amount) { $('rec-msg').textContent = '금액을 넣어 주세요.'; return; }
            const body = { action: 'edit', id, amount, day: Number($('rec-day').value), category_id: Number($('rec-cat').value), memo: $('rec-memo').value.trim() };
            if (await recPost(body)) { st.recOpen = null; renderRecurring(); }
            return;
        }
        if (e.target.closest('[data-rec-pause]')) { if (r) await recPost({ action: r.paused ? 'resume' : 'pause', id }); return; }
        if (e.target.closest('[data-rec-del]')) {
            if (!r || !window.confirm(`'${r.memo || catOf(r.category_id).name}' 반복 결제를 지울까요?\n이미 들어간 기록은 그대로예요.`)) return;
            if (await recPost({ action: 'delete', id })) { st.recOpen = null; renderRecurring(); }
            return;
        }
        const row = e.target.closest('.rec-row[role="button"]');
        if (row) { const rid = Number(row.dataset.rec); st.recOpen = st.recOpen === rid ? null : rid; renderRecurring(); }
    });
    $('rec-list').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.rec-row[role="button"]')) { e.preventDefault(); e.target.click(); } });
    $('rec-list').addEventListener('input', e => {
        if (e.target.id !== 'rec-amount') return;
        const v = e.target.value.replace(/[^0-9]/g, '').slice(0, 10);
        e.target.value = v ? Number(v).toLocaleString('ko-KR') : '';
    });
    // '＋ 반복 결제 추가': 입력 창을 '🔁 매달 반복'이 켜진 채로 (오늘 날짜, 이번 기록도 함께 들어감)
    $('rec-add').addEventListener('click', () => {
        closeSettings();
        clearForm();
        setUsedOn(ymd(new Date()));
        render();
        setRepeat(true);
        openEntry();
    });

    // ---------- 사진: 휴대폰에서 줄여(큰 것 긴 쪽 1600px·썸네일 240px JPEG) 저장할 때 올림
    const PHOTO_MAX = 3;
    function setPhotos(items) {
        st.ph.items.forEach(p => { if (p.url) URL.revokeObjectURL(p.url); });
        st.ph = { items, removed: [] };
        $('photo-msg').textContent = '';
        renderPhotos();
    }
    function photoSrc(p, thumb) { return p.url || photoUrl(p.id, thumb); }
    // 사진 칸: 올린 사진·저장할 사진은 썸네일(누르면 크게, ✕로 빼기), 아직 준비 중인 사진은 ⏳ 자리
    function renderPhotos() {
        const items = st.ph.items;
        $('photos').innerHTML = items.map((p, i) => p.pending ? '<span class="ph-wrap"><span class="ph wait" role="img" aria-label="사진 준비 중">⏳</span></span>'
            : `<span class="ph-wrap"><button type="button" class="ph" data-ph-view="${i}" aria-label="사진 ${i + 1} 크게 보기"><img src="${photoSrc(p, true)}" alt=""></button>`
            + `<button type="button" class="ph-x" data-ph-del="${i}" aria-label="사진 ${i + 1} 빼기">✕</button></span>`).join('')
            + (items.length < PHOTO_MAX ? '<button type="button" class="ph-add" id="ph-add" aria-label="사진 붙이기">📷</button>' : '')
            + (items.length ? `<span class="ph-n">${items.length}/${PHOTO_MAX}</span>` : '');
    }
    renderPhotos();
    $('photos').addEventListener('click', e => {
        if (e.target.closest('#ph-add')) { $('photo-file').click(); return; }
        const del = e.target.closest('[data-ph-del]');
        if (del) {
            $('photo-msg').textContent = '';
            const [p] = st.ph.items.splice(Number(del.dataset.phDel), 1);
            if (p.id) st.ph.removed.push(p.id); else URL.revokeObjectURL(p.url);
            renderPhotos();
            return;
        }
        const v = e.target.closest('[data-ph-view]');
        if (v) {
            const ready = st.ph.items.filter(p => !p.pending), at = ready.indexOf(st.ph.items[Number(v.dataset.phView)]);
            openViewer(ready.map(p => photoSrc(p, false)), Math.max(0, at));
        }
    });
    // 사진 열기: <img>로, 안 되면 createImageBitmap으로 (둘 다 안 되면 HEIC처럼 이 브라우저가 못 여는 형식)
    function loadByImg(file) {
        return new Promise((resolve, reject) => {
            const url = URL.createObjectURL(file), img = new Image();
            img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
            img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('decode')); };
            img.src = url;
        });
    }
    async function loadImage(file) {
        try { return await loadByImg(file); } catch (err) {
            if (!window.createImageBitmap) throw err;
            return await createImageBitmap(file, { imageOrientation: 'from-image' });
        }
    }
    const sizeOf = s => s >= 1048576 ? `${(s / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(s / 1024))}KB`;
    function shrink(img, max, quality) {
        const w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
        const s = Math.min(1, max / Math.max(w, h));
        const c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(w * s));
        c.height = Math.max(1, Math.round(h * s));
        const g = c.getContext('2d');
        g.fillStyle = '#fff';
        g.fillRect(0, 0, c.width, c.height);
        g.drawImage(img, 0, 0, c.width, c.height);
        return new Promise(resolve => c.toBlob(resolve, 'image/jpeg', quality));
    }
    function photoNote(text, wait) {
        $('photo-msg').textContent = text;
        $('photo-msg').classList.toggle('wait', !!wait);
    }
    // 받은 사진: 먼저 ⏳ 자리를 그리고 '사진 준비 중…', 줄인 것이 되면 그 자리에 썸네일. 그사이 창을 닫으면 버림
    $('photo-file').addEventListener('change', () => {
        const files = [...$('photo-file').files];
        $('photo-file').value = '';
        photoNote('');
        if (!files.length) return;
        const ph = st.ph, room = PHOTO_MAX - ph.items.length;
        const slots = files.slice(0, Math.max(0, room)).map(f => ({ pending: true, file: f }));
        ph.items.push(...slots);
        renderPhotos();
        let note = files.length > room ? `사진은 ${PHOTO_MAX}장까지 붙일 수 있어요.` : '';
        if (slots.length) photoNote('사진 준비 중…', true);
        ph.busy = (async () => {
            for (const slot of slots) {
                const f = slot.file;
                try {
                    const img = await loadImage(f);
                    const [full, thumb] = await Promise.all([shrink(img, 1600, 0.82), shrink(img, 240, 0.75)]);
                    if (!full || !thumb) throw new Error('encode');
                    Object.assign(slot, { pending: false, file: null, full, thumb, url: URL.createObjectURL(full) });
                } catch (err) {
                    ph.items.splice(ph.items.indexOf(slot), 1);
                    // 무엇을 받았는지 함께 (안 될 때 알려 주시면 원인을 찾기 쉬움)
                    note = `이 사진은 열 수 없어요 (${f.type || '형식 모름'} · ${sizeOf(f.size || 0)}). 다른 사진을 골라 주세요.`;
                }
                if (st.ph === ph) renderPhotos();
            }
            if (st.ph === ph) photoNote(note);
        })();
    });
    // 앱(YeYe홈 1.29부터)이 사진을 넘긴 뒤, 또는 앱 화면으로 돌아왔을 때: 사진 칸을 다시 그림 (앱 안 화면이 바로 안 바뀌던 것)
    window.appPhotosArrived = () => { if (!$('sheet-wrap').hidden) renderPhotos(); };
    document.addEventListener('visibilitychange', () => { if (!document.hidden) window.appPhotosArrived(); });
    // 기록을 저장한 뒤: 뺀 사진 지우고 새 사진 올리기. 못 한 것이 있으면 그 이유
    async function savePhotos(entryId) {
        const adds = st.ph.items.filter(p => !p.id && !p.pending), removes = st.ph.removed;
        let failed = '';
        for (const id of removes) {
            const { status, data } = await post('/api/ledger/photo', { action: 'delete', id });
            if (status !== 200) failed = `사진을 빼지 못했어요: ${msgOf(data)}`;
        }
        for (let i = 0; i < adds.length; i++) {
            $('save').textContent = `사진 올리는 중… ${i + 1}/${adds.length}`;
            try {
                const res = await fetch(`/api/ledger/photo-upload?entry=${entryId}`, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/octet-stream', 'X-Thumb-Size': String(adds[i].thumb.size) },
                    body: new Blob([adds[i].thumb, adds[i].full]),
                });
                if (res.status !== 200) { let d = {}; try { d = await res.json(); } catch (e) { /* 본문 없음 */ } failed = `사진을 올리지 못했어요: ${msgOf(d)}`; }
            } catch (err) {
                failed = '사진을 올리지 못했어요 (연결이 끊겼어요).';
            }
        }
        return failed;
    }

    // ---------- 사진 크게 보기
    let pv = { urls: [], i: 0 };
    function openViewer(urls, i) {
        if (!urls.length) return;
        pv = { urls, i };
        showViewer();
        $('pv').hidden = false;
    }
    function showViewer() {
        $('pv-img').hidden = false;
        // 서버 사진은 열 때마다 새로 (같은 화면에서 전에 본 사진이 지워졌어도 남은 사본이 뜨지 않게)
        const u = pv.urls[pv.i];
        $('pv-img').src = u.startsWith('/api/') ? `${u}?v=${Date.now()}` : u;
        $('pv-n').textContent = pv.urls.length > 1 ? `${pv.i + 1} / ${pv.urls.length}` : '';
        $('pv-prev').hidden = $('pv-next').hidden = pv.urls.length < 2;
    }
    // 사진을 못 받음 (다른 곳에서 지운 사진): 검은 화면 대신 안내, 내역을 새로 읽어 썸네일도 치움
    $('pv-img').addEventListener('error', () => {
        if ($('pv').hidden || !$('pv-img').getAttribute('src')) return;
        $('pv-img').hidden = true;
        $('pv-n').textContent = '이 사진은 지워졌어요';
        st.loadedAt = 0;
        refreshFromOutside();
    });
    const viewerGo = d => { pv.i = (pv.i + d + pv.urls.length) % pv.urls.length; showViewer(); };
    const closeViewer = () => { $('pv').hidden = true; $('pv-img').removeAttribute('src'); };
    $('pv-close').addEventListener('click', closeViewer);
    $('pv-prev').addEventListener('click', () => viewerGo(-1));
    $('pv-next').addEventListener('click', () => viewerGo(1));
    $('pv').addEventListener('click', e => { if (e.target === $('pv')) closeViewer(); });
    document.addEventListener('keydown', e => {
        if ($('pv').hidden) return;
        if (e.key === 'Escape') closeViewer();
        else if (e.key === 'ArrowLeft') viewerGo(-1);
        else if (e.key === 'ArrowRight') viewerGo(1);
    });
    let pvTouch = null;
    $('pv').addEventListener('touchstart', e => { pvTouch = e.touches[0].clientX; }, { passive: true });
    $('pv').addEventListener('touchend', e => {
        if (pvTouch == null || pv.urls.length < 2) return;
        const dx = e.changedTouches[0].clientX - pvTouch;
        pvTouch = null;
        if (Math.abs(dx) > 50) viewerGo(dx < 0 ? 1 : -1);
    });

    // ---------- 수정 이력 (고치기 창)
    async function loadHistory(entryId) {
        st.histFor = entryId;
        $('hist').hidden = true;
        showHist(false);
        const { status, data } = await get(`/api/ledger/history?entry=${entryId}`);
        if (st.histFor !== entryId || status !== 200) return;
        const list = data.history || [];
        $('hist-n').textContent = list.length;
        $('hist-list').innerHTML = list.map(histHtml).join('');
        $('hist').hidden = !list.length;
    }
    // 🕘 n: 누르면 분류 줄 아래에 수정 이력 펼치기·접기
    function showHist(on) {
        $('hist-panel').hidden = !on;
        $('hist').setAttribute('aria-expanded', String(on));
        $('hist').classList.toggle('on', on);
    }
    $('hist').addEventListener('click', () => {
        const on = $('hist-panel').hidden;
        showHist(on);
        if (on) $('hist-panel').scrollIntoView({ block: 'nearest' });
    });
    const md = d => `${+d.slice(5, 7)}/${+d.slice(8, 10)}`;
    const memoText = m => m ? `'${esc(m)}'` : '없음';
    function histHtml(h) {
        const b = h.before, a = h.after, head = `${md(h.changed_at)} ${h.changed_at.slice(11, 16)} · ${esc(h.who || '?')}`;
        const money = e => `${e.kind === 'income' ? '+' : ''}${won(e.amount)}`;
        if (!b || !a) {
            const e = a || b;
            return `<div class="h"><small>${head} · ${a ? '넣음' : '지움'}</small>${md(e.used_on)} ${esc(e.category)} ${money(e)}${e.memo ? ` ${memoText(e.memo)}` : ''}${a && a.photos ? ` · 사진 ${a.photos}장` : ''}</div>`;
        }
        const parts = [];
        if (b.amount !== a.amount || b.kind !== a.kind) parts.push(`금액 ${money(b)} → <b>${money(a)}</b>`);
        if (b.used_on !== a.used_on) parts.push(`날짜 ${md(b.used_on)} → <b>${md(a.used_on)}</b>`);
        if (b.category !== a.category) parts.push(`분류 ${esc(b.category)} → <b>${esc(a.category)}</b>`);
        if ((b.memo || '') !== (a.memo || '')) parts.push(`메모 ${memoText(b.memo)} → <b>${memoText(a.memo)}</b>`);
        if (b.photos != null && a.photos != null && b.photos !== a.photos) parts.push(a.photos > b.photos ? `사진 ${a.photos - b.photos}장 더함` : `사진 ${b.photos - a.photos}장 뺌`);
        return `<div class="h"><small>${head} · 고침</small>${parts.join(' · ') || '바뀐 것 없음'}</div>`;
    }
    $('used-on').addEventListener('input', showUsedOn);
    $('used-on').addEventListener('change', showUsedOn);
    // 칸 어디를 눌러도 달력 (PC 크롬은 아이콘을 눌러야만 열림)
    $('used-on').addEventListener('click', e => { try { e.target.showPicker(); } catch (err) { /* 지원 안 함 */ } });
    $('edit-delete').addEventListener('click', async () => {
        if (st.editId != null && await deleteEntry(st.editId)) { clearForm(); closeEntry(); }
    });
    async function deleteEntry(id) {
        // 지울 기록을 확인 창에 보여 줌: 날짜 · 메모(없으면 소비형태) / 소비형태 · 금액 · 쓴 사람
        const e = st.data.entries.find(x => x.id === id) || (st.search && st.search.entries.find(x => x.id === id));
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
    // 입력 창의 '편집' → 설정 > 분류
    $('cat-edit').addEventListener('click', () => { closeEntry(); openSettings('cats'); });
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
        st.catOpen = false;
        load();
    });

    // 분류 고치기 (설정 > 분류): name·color·icon 중 준 것만 바꿈
    async function saveCategory(id, { name, color, icon } = {}) {
        const c = st.data.categories.find(x => x.id === id);
        const { status, data } = await post('/api/ledger/category', { action: 'edit', id, name: name != null ? name : c.name, color: color || c.color, ...(icon ? { icon } : {}) });
        if (status !== 200) { const m = $('ced-msg'); if (m) m.textContent = msgOf(data); return false; }
        if (name != null) c.name = name.trim().replace(/\s+/g, ' ');
        if (color) c.color = color; if (icon) c.icon = icon;
        return true;
    }

    // 입력 창의 분류: 누르면 고르기, '＋ 추가'
    $('cats').addEventListener('click', e => {
        if (e.target.closest('#cat-add')) { openAddBox(); return; }
        const chip = e.target.closest('[data-cat]');
        if (!chip) return;
        st.sels[st.kind] = Number(chip.dataset.cat);
        $('addbox').hidden = true;
        st.catOpen = false;
        renderCats();
    });
    // 고른 분류 한 칸을 누르면 목록 펼치기·접기
    $('cat-pick').addEventListener('click', () => {
        st.catOpen = !st.catOpen;
        if (!st.catOpen) $('addbox').hidden = true;
        renderCats();
        if (st.catOpen) $('cat-list').scrollIntoView({ block: 'nearest' });
    });
    $('cats').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.chip')) { e.preventDefault(); e.target.click(); } });

    // ==========================================
    // 설정 > 분류: 지출·수입 목록, 줄을 누르면 이름·아이콘·색 고치기·지우기, ⋮⋮를 끌어 순서 바꾸기, 쪽마다 '＋ 추가'
    // ==========================================
    function cedHtml(c) {
        return `<div class="ced" data-ced="${c.id}">
            <input id="ced-name" value="${esc(c.name)}" maxlength="12" aria-label="분류 이름">
            <div class="icons">${iconsHtml(iconOf(c), 'data-ced-icon')}</div>
            <div class="pal">${palHtml(c.color, 'data-ced-color')}</div>
            <label class="custom"><input type="color" id="ced-custom" value="${c.color.toLowerCase()}"> 다른 색</label>
            <div class="ced-act"><button type="button" class="primary" data-ced-save>완료</button><button type="button" class="danger" data-ced-del>지우기</button></div>
            <p class="msg" id="ced-msg"></p></div>`;
    }
    function caddHtml(kind) {
        const a = st.cadd, c = a.color;
        return `<div class="ced" data-cadd-form="${kind}">
            <div class="cadd-top"><span class="ci" style="background:${c ? chipBg(c) : 'var(--soft)'};color:${c ? chipFg(c) : 'var(--muted)'}">${esc(a.icon || '＋')}</span>
                <input id="cadd-name" value="${esc(a.name)}" maxlength="12" placeholder="이름" aria-label="새 분류 이름" autocomplete="off"></div>
            <div class="icons">${iconsHtml(a.icon, 'data-cadd-icon')}</div>
            <div class="pal">${palHtml(c, 'data-cadd-color')}</div>
            <div class="ced-act"><button type="button" class="primary" data-cadd-save>추가</button><button type="button" data-cadd-cancel>취소</button></div>
            <p class="msg" id="cadd-msg">${esc(a.msg)}</p></div>`;
    }
    // 순서 바꾸기 손잡이: 가로줄 셋 (글자 ⋮⋮는 휴대폰 글꼴에서 뭉개져 보여 그림으로)
    const GRIP = '<svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true"><path d="M4 6h12M4 10h12M4 14h12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
    function renderCatAdmin() {
        if (!st.data) return;
        const used = new Set(st.data.categories.map(c => c.id));
        if (st.cedFor != null && !used.has(st.cedFor)) st.cedFor = null;
        $('row-cats').textContent = st.data.categories.length;
        $('cat-admin').innerHTML = [['expense', '지출'], ['income', '수입']].map(([kind, word]) => {
            const list = st.data.categories.filter(c => c.kind === kind);
            return `<p class="set-cap">${word}</p><div class="set-grp cat-list" data-kind="${kind}">${list.map(c => `
                <div class="cat-row" data-cid="${c.id}"><div class="set-row" data-ced-open="${c.id}" role="button" tabindex="0">${catIcon(c)}<span class="n">${esc(c.name)}</span>
                    <span class="drag" data-drag aria-label="끌어서 순서 바꾸기">${GRIP}</span></div>${st.cedFor === c.id ? cedHtml(c) : ''}</div>`).join('')}
                ${st.caddKind === kind ? caddHtml(kind) : `<button type="button" class="set-row add-row-btn" data-cadd="${kind}"><span class="ci none">＋</span><span class="n">${word} 분류 추가</span></button>`}</div>`;
        }).join('');
    }
    $('cat-admin').addEventListener('click', async e => {
        const ced = e.target.closest('[data-ced]');
        if (ced) {
            const id = Number(ced.dataset.ced);
            const sw = e.target.closest('[data-ced-color]'), ic = e.target.closest('[data-ced-icon]');
            if (sw && await saveCategory(id, { name: $('ced-name').value, color: sw.dataset.cedColor })) render();
            else if (ic && await saveCategory(id, { name: $('ced-name').value, icon: ic.dataset.cedIcon })) render();
            else if (e.target.closest('[data-ced-save]') && await saveCategory(id, { name: $('ced-name').value })) { st.cedFor = null; render(); }
            else if (e.target.closest('[data-ced-del]')) {
                if (!window.confirm(`'${catOf(id).name}' 분류를 지울까요?`)) return;
                const { status, data } = await post('/api/ledger/category', { action: 'delete', id });
                if (status !== 200) { $('ced-msg').textContent = msgOf(data); return; }
                st.cedFor = null;
                load();
            }
            return;
        }
        const form = e.target.closest('[data-cadd-form]');
        if (form) {
            const kind = form.dataset.caddForm;
            st.cadd.name = $('cadd-name').value;
            const sw = e.target.closest('[data-cadd-color]'), ic = e.target.closest('[data-cadd-icon]');
            if (sw) { st.cadd.color = sw.dataset.caddColor; st.cadd.msg = ''; renderCatAdmin(); }
            else if (ic) { st.cadd.icon = ic.dataset.caddIcon; renderCatAdmin(); }
            else if (e.target.closest('[data-cadd-cancel]')) { st.caddKind = null; renderCatAdmin(); }
            else if (e.target.closest('[data-cadd-save]')) {
                const name = st.cadd.name.trim();
                const say = t => { st.cadd.msg = t; $('cadd-msg').textContent = t; };
                if (!name) return say('이름을 넣어 주세요.');
                if (!st.cadd.color) return say('색을 골라 주세요.');
                const { status, data } = await post('/api/ledger/category', { action: 'add', name, color: st.cadd.color, kind, icon: st.cadd.icon });
                if (status !== 200) return say(msgOf(data));
                st.caddKind = null;
                load();
            }
            return;
        }
        const add = e.target.closest('[data-cadd]');
        if (add) {
            st.caddKind = add.dataset.cadd; st.cedFor = null;
            st.cadd = { name: '', icon: '', color: null, msg: '' };
            renderCatAdmin();
            $('cadd-name').focus();
            return;
        }
        if (e.target.closest('[data-drag]')) return;
        const open = e.target.closest('[data-ced-open]');
        if (open) {
            const id = Number(open.dataset.cedOpen);
            st.cedFor = st.cedFor === id ? null : id; st.caddKind = null;
            renderCatAdmin();
        }
    });
    $('cat-admin').addEventListener('keydown', e => {
        if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[data-ced-open]')) { e.preventDefault(); e.target.click(); }
        if (e.key === 'Enter' && e.target.id === 'ced-name') { e.preventDefault(); $('cat-admin').querySelector('[data-ced-save]').click(); }
    });
    // '다른 색': 고르는 동안 미리 보이고, 손을 떼면(change) 저장
    $('cat-admin').addEventListener('input', e => {
        if (e.target.id !== 'ced-custom') return;
        const ci = e.target.closest('.cat-row').querySelector('.ci'), h = e.target.value;
        ci.style.background = chipBg(h); ci.style.color = chipFg(h);
    });
    $('cat-admin').addEventListener('change', async e => {
        if (e.target.id !== 'ced-custom') return;
        const id = Number(e.target.closest('[data-ced]').dataset.ced);
        if (await saveCategory(id, { name: $('ced-name').value, color: e.target.value.toUpperCase() })) render();
    });
    // 손잡이를 끌어 같은 쪽(지출·수입) 안에서 순서 바꾸기 → 놓으면 저장, 끌지 않고 톡 누르면 그 분류를 고치는 칸 열기
    let drag = null;
    $('cat-admin').addEventListener('pointerdown', e => {
        const h = e.target.closest('[data-drag]');
        if (!h) return;
        e.preventDefault();
        const row = h.closest('.cat-row');
        drag = { row, list: row.parentElement, id: e.pointerId, y: e.clientY, moved: false };
        h.setPointerCapture(e.pointerId);
        row.classList.add('dragging');
    });
    $('cat-admin').addEventListener('pointermove', e => {
        if (!drag || e.pointerId !== drag.id) return;
        if (!drag.moved && Math.abs(e.clientY - drag.y) < 6) return;   // 손가락 떨림은 끌기 아님
        drag.moved = true;
        const rows = [...drag.list.querySelectorAll(':scope > .cat-row')].filter(r => r !== drag.row);
        const before = rows.find(r => { const b = r.getBoundingClientRect(); return e.clientY < b.top + b.height / 2; });
        if (before) { if (before !== drag.row.nextElementSibling) drag.list.insertBefore(drag.row, before); }
        else { const last = rows[rows.length - 1]; if (last && last.nextElementSibling !== drag.row) last.after(drag.row); }
    });
    async function endDrag(e) {
        if (!drag || e.pointerId !== drag.id) return;
        const { row, moved } = drag;
        drag = null;
        row.classList.remove('dragging');
        if (!moved) {
            if (e.type !== 'pointerup') return;
            const id = Number(row.dataset.cid);
            st.cedFor = st.cedFor === id ? null : id; st.caddKind = null;
            renderCatAdmin();
            return;
        }
        await saveCatOrder();
    }
    $('cat-admin').addEventListener('pointerup', endDrag);
    $('cat-admin').addEventListener('pointercancel', endDrag);
    async function saveCatOrder() {
        // 지출 다음 수입 순으로 모든 분류 번호
        const ids = [...$('cat-admin').querySelectorAll('.cat-row')].map(r => Number(r.dataset.cid));
        const before = st.data.categories.map(c => c.id);
        if (ids.join() === before.join()) return;
        const { status } = await post('/api/ledger/category', { action: 'reorder', ids });
        if (status === 200) {
            st.data.categories.sort((a, b) => ids.indexOf(a.id) - ids.indexOf(b.id));
            render();
        } else renderCatAdmin();
    }
    window.ledgerMoveCategory = async (id, to) => {   // 시험용: 분류를 같은 쪽의 to번째로 옮기고 저장
        const row = $('cat-admin').querySelector(`.cat-row[data-cid="${id}"]`), list = row.parentElement;
        const rows = [...list.querySelectorAll(':scope > .cat-row')].filter(r => r !== row);
        if (rows[to]) list.insertBefore(row, rows[to]); else rows[rows.length - 1].after(row);
        await saveCatOrder();
    };
    $('addbox').addEventListener('click', e => {
        const sw = e.target.closest('[data-add-color]');
        if (sw) { st.addColor = sw.dataset.addColor; $('add-msg').textContent = ''; renderAddBox(); }
        const ic = e.target.closest('[data-add-icon]');
        if (ic) { st.addIcon = ic.dataset.addIcon; renderAddBox(); }
    });
    document.addEventListener('click', e => {
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
        const view = e.target.closest('[data-view]');
        if (view) { const x = st.data.entries.find(y => y.id === Number(view.dataset.view)); if (x) openViewer(x.photos.map(id => photoUrl(id)), 0); return; }
        const b = e.target.closest('[data-entry]');
        if (!b) return;
        const entry = st.data.entries.find(x => x.id === Number(b.dataset.entry));
        if (entry && canEdit(entry)) startEdit(entry);
    });
    $('list').addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.it.mine')) { e.preventDefault(); e.target.click(); } });

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
        $('inbox-sec').hidden = !items.length && !inboxOpen();
        $('inbox-count').textContent = items.length;
        $('ib-page-n').textContent = items.length ? `${items.length}건` : '';
        $('ib-empty').hidden = !!items.length;
        $('inbox-all').hidden = !items.length;
        if (!items.length) $('inbox').innerHTML = '';
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
            // 금액이 비슷한(10%·1,000원 안) 반복 결제가 앞뒤 3일 안에 있음 (알림 이름이 달라도): 두 번 기록하지 않게 버리기 쉽게. 금액이 다르면 차이도
            const rr = !x.cancel && x.recurring;
            const rpDiff = rr && rr.diff ? ` · ${won(Math.abs(rr.diff))} ${rr.diff > 0 ? '더 나옴' : '덜 나옴'}` : '';
            const rp = rr ? `<div class="ib-rp">🔁 ${md(rr.used_on)}에 '${esc(rr.memo || '반복 결제')}'(으)로 ${rr.done ? '이미 기록됨' : '기록될 예정'}${rpDiff} · 버려도 돼요</div>` : '';
            const row = `<div class="ib-row" data-ib-toggle role="button" tabindex="0" aria-expanded="${open}">
                ${c ? catIcon(c) : `<span class="ci none" aria-hidden="true">${x.cancel ? '↩' : '?'}</span>`}
                <span class="ib-m"><span class="shop">${esc(shop || '가게 이름 없음')}</span><small>${day} ${esc(x.used_time)} · ${esc(x.card || '카드')}${c ? ` · ${esc(c.name)}` : ''}</small></span>
                <span class="amt${x.cancel ? ' cancel' : ''}">${x.cancel ? '취소 ' : '−'}${won(x.amount)}</span>
                <button type="button" class="ib-ok" data-ib-ok aria-label="${x.cancel ? '취소 확정' : '확정'}"${!x.cancel && cat == null ? ' disabled' : ''}>✓</button>
                <button type="button" class="ib-x" data-ib-del aria-label="버리기">✕</button></div>`;
            // 접힌 채로도 분류는 바로 고를 수 있게: 분류가 없으면 줄 아래에 분류 한 줄 (옆으로 밀기)
            const quick = !x.cancel && cat == null ? `<div class="ib-quick">${expenseCats().map(c => `<span class="chip" data-ib-cat="${c.id}"
                style="background:${chipBg(c.color)};color:${chipFg(c.color)}">${esc(iconOf(c))} ${esc(c.name)}</span>`).join('')}</div>` : '';
            if (!open) return `<div class="ib" data-item="${x.id}">${row}${rp}${quick}</div>`;
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
            // 앱 안이면 이 알림 원문으로 바로 거를 표현 고르기 (앱의 '이런 알림 안 받기' 창)
            const canIgnore = appCanIgnore() && x.raw;
            const btns = (canRule ? `<button type="button" class="small" data-ib-rule>"${esc(suggestPattern(shop))}"는 늘 ${esc(catOf(cat).name)}</button>` : '')
                + (canIgnore ? '<button type="button" class="small" data-ib-ignore>이런 알림 안 받기</button>' : '');
            return `<div class="ib open" data-item="${x.id}">${row}${rp}<div class="body">
                ${note}${fields}${chips}${newCat}<span class="raw">${esc(x.raw)}</span>
                ${btns ? `<div class="btns">${btns}</div>` : ''}</div></div>`;
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
        if (e.target.closest('[data-ib-ignore]')) { try { window.LedgerApp.pickIgnore(item.raw); } catch (err) { /* 예전 앱 */ } return; }
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
    // 휴대폰 연결 카드: 앱 안이면 이 휴대폰 앱이 연결됐는지, 앱 밖이면 연결 주소(어느 휴대폰이든)가 있는지
    const lastText = h => h && h.last_used ? `마지막 알림 ${+h.last_used.slice(5, 7)}/${+h.last_used.slice(8, 10)} ${h.last_used.slice(11, 16)}` : '';
    function renderAppConnect() {
        const h = st.hook;
        let on, title, sub;
        if (inApp) {
            on = appConnected();
            $('app-hint').hidden = on;
            let ver = '';
            try { ver = window.LedgerApp.version(); } catch (e) { /* 예전 앱 */ }
            title = on ? '이 휴대폰이 연결됐어요' : '아직 연결되지 않았어요';
            sub = on ? [`이 휴대폰 앱(${ver})`, lastText(h)].filter(Boolean).join(' · ') : '연결하면 결제 알림이 확인할 결제로 와요';
            $('app-connect-btn').textContent = on ? '다시 연결' : '연결하기';
            $('app-connect-btn').className = on ? 'wide app-only' : 'primary wide app-only';
        } else {
            on = !!h;
            title = on ? '휴대폰이 연결됐어요' : '아직 연결되지 않았어요';
            sub = on ? lastText(h) || '아직 받은 알림 없음' : '휴대폰에 YeYe홈 앱을 받아 연결하세요';
        }
        $('conn-card').classList.toggle('on', on);
        $('conn-ico').textContent = on ? '✓' : '!';
        $('conn-title').textContent = title;
        $('app-connect-state').textContent = sub;
        $('row-hook').textContent = on ? ['연결됨', lastText(h)].filter(Boolean).join(' · ') : '연결 안 됨';
        $('row-hook').classList.toggle('ok', on);
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
        if (!ok) $('app-connect-state').textContent = '앱에 넣지 못했어요 · 앱을 새로 받아 주세요';
    });

    function renderAuto() {
        if (!st.data) return;
        renderAppConnect();
        const h = st.hook;
        const statusText = { saved: '정상', ignored: '결제 알림이 아니라 넘김', duplicate: '같은 알림이 또 와서 넘김', too_many: '너무 많이 와서 넘김' };
        $('hook-state').textContent = !h ? '아직 연결 주소를 만들지 않았어요.'
            : `연결 주소 만든 때 ${h.created_at.slice(5, 16)} (…${h.hint}) · ${h.last_used ? `마지막으로 받은 알림 ${h.last_used.slice(5, 16)} · ${statusText[h.last_status] || h.last_status}` : '아직 받은 알림 없음'}`;
        $('hook-create').textContent = h ? '연결 주소 새로 만들기' : '연결 주소 만들기';
        const cats = expenseCats();
        const cur = $('rule-cat').value;
        $('rule-cat').innerHTML = cats.map(c => `<option value="${c.id}">${esc(iconOf(c))} ${esc(c.name)}</option>`).join('');
        if (cats.some(c => String(c.id) === cur)) $('rule-cat').value = cur;
        $('row-rules').textContent = st.rules.length || '';
        // 한 줄: 가게 글자 · 아이콘 분류 · ✕
        $('rules').innerHTML = st.rules.length ? st.rules.map(r => {
            const c = catOf(r.category_id);
            return `<div class="set-row rule"><span class="n">${esc(r.pattern)}</span><span class="rc" style="color:${chipFg(c.color)}">${esc(iconOf(c))} ${esc(c.name)}</span>
                <button type="button" class="x" data-rule-del="${r.id}" aria-label="'${esc(r.pattern)}' 규칙 지우기">✕</button></div>`;
        }).join('') : '<p class="none">아직 없어요 · 확인할 결제에서 "○○는 늘 ○○"로도 만들어요</p>';
    }
    $('hook-create').addEventListener('click', async () => {
        if (st.hook && !window.confirm('새로 만들면 지금 연결 주소는 더 못 써요. 휴대폰 설정도 새 주소로 바꿔야 해요. 만들까요?')) return;
        const { status, data } = await post('/api/ledger/hook-key', { action: 'create' });
        if (status !== 200) { $('hook-state').textContent = msgOf(data); return; }
        st.hook = data.hook;
        $('hook-url').value = data.url;
        $('hook-url-box').hidden = false;
        $('hook-more').open = true;
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
    // 앱(1.30부터)이 좌우 밀기·끌어내려 새로고침 전에 물음 (nav.js의 appGesture): 무언가 열려 있으면 true
    window.appBusy = () => !$('pv').hidden || $('app').classList.contains('settings-open') || !$('memo-dd').hidden
        || !$('addbox').hidden || !$('sheet-wrap').hidden;
    window.ledgerBack = () => {
        if (!$('pv').hidden) { closeViewer(); return true; }
        if (!$('memo-dd').hidden) { $('memo-dd').hidden = true; return true; }
        if (!$('addbox').hidden) { $('addbox').hidden = true; return true; }
        // 입력·고치기 창: 펼친 분류 목록·수정 이력부터 접고, 그다음 창을 닫음
        if (!$('sheet-wrap').hidden) {
            if (st.catOpen) { st.catOpen = false; renderCats(); return true; }
            if (!$('hist-panel').hidden) { showHist(false); return true; }
            closeEntry(); return true;
        }
        // 설정: 그 페이지에서 펼친 분류 고치기·추가, 반복 결제 고치기부터 접음
        if ($('app').classList.contains('settings-open')) {
            if (st.cedFor != null || st.caddKind) { st.cedFor = null; st.caddKind = null; renderCatAdmin(); return true; }
            if (st.recOpen != null) { st.recOpen = null; renderRecurring(); return true; }
            setBack(); return true;
        }
        if (st.newCatFor != null) { st.newCatFor = null; renderInbox(); return true; }
        if (st.search) { openSearch(false); return true; }
        // 결제 확인: 펼친 결제를 먼저 접음 (접을 때처럼 고친 것은 저장)
        if (inboxOpen() && st.ibOpen.size) {
            const ids = [...st.ibOpen];
            (async () => {
                for (const id of ids) { await saveIbFields(id); st.ibOpen.delete(id); }
                renderInbox();
            })();
            return true;
        }
        if (inboxOpen()) { closeInbox(); return true; }
        // 하루 보기 → 그 달 보기
        if (st.mode === 'day') { st.mode = 'month'; render(); return true; }
        return false;
    };
    // ==========================================
    // 설정 (머리줄 '설정' → 같은 페이지의 #settings): 목록(휴대폰 연결 · 가게 규칙 · 버린 알림 · 분류 · 함께 쓰는 사람 · 전체 설정),
    // 줄을 누르면 그 페이지(#settings/hook 등). 주소에 한 칸씩 넣어 두므로 ←·브라우저·앱의 뒤로가기로 목록, 다시 메인
    // ==========================================
    const SET_TITLES = { hook: '휴대폰 연결', rules: '가게 규칙', trash: '버린 알림', repeat: '반복 결제', cats: '분류', users: '함께 쓰는 사람' };
    function renderSetTabs() {
        const admin = !!(st.me && st.me.admin);
        if (!SET_TITLES[st.setTab] || (!admin && st.setTab === 'users')) st.setTab = null;
        const tab = st.setTab;
        document.querySelectorAll('#set-view .admin-only').forEach(b => { if (!b.classList.contains('set-pane')) b.hidden = !admin; });
        $('set-home').hidden = !!tab;
        $('set-title').textContent = tab ? SET_TITLES[tab] : '설정';
        document.querySelectorAll('#set-view .set-pane').forEach(p => { p.hidden = p.dataset.pane !== tab; });
    }
    function showSettings(on) {
        $('app').classList.toggle('settings-open', on);
        if (on) { renderSetTabs(); window.scrollTo(0, 0); }
        renderViews();
    }
    // 설정 안에서 쌓은 주소 칸 수 (메인 → #settings 1, → #settings/hook 2)
    const setLevel = () => (history.state || {}).ledgerSet || 0;
    function pushSet(tab) {
        const s = history.state || {};
        history.pushState({ ...s, navDepth: (s.navDepth || 0) + 1, ledgerSettings: 1, ledgerSet: (s.ledgerSet || 0) + 1 }, '', tab ? `#settings/${tab}` : '#settings');
    }
    // ← (앱의 뒤로가기도): 페이지면 목록으로, 목록이면 메인으로
    function setBack() {
        if (st.setTab) {
            if (setLevel() >= 2) { history.back(); return; }
            history.replaceState(history.state, '', '#settings');
            st.setTab = null; renderSetTabs(); window.scrollTo(0, 0);
        } else closeSettings();
    }
    // 앱(YeYe홈)이 부름: 위쪽 '설정' → 가계부 설정 (로그인 전이면 false → 앱이 자기 설정을 엶)
    window.appOpenSettings = () => { if (!st.me) return false; openSettings(); return true; };
    // ---- 결제 확인 화면 (#inbox): 홈 탭의 '확인할 결제'를 눌러 옴. 주소에 #inbox 한 칸을 넣어 ←·뒤로가기로 가계부 첫 화면
    const inboxOpen = () => $('app').classList.contains('inbox-open');
    function setInboxPage(on) {
        $('app').classList.toggle('inbox-open', on);
        if (on) window.scrollTo(0, 0);
        renderInbox();
    }
    function showInboxPage() {
        if (location.hash === '#inbox') history.replaceState(history.state, '', location.pathname + location.search);
        if (st.search) openSearch(false);
        if ($('app').classList.contains('settings-open')) { st.setTab = null; showSettings(false); }
        if (!inboxOpen()) {
            const s = history.state || {};
            history.pushState({ ...s, navDepth: (s.navDepth || 0) + 1, ledgerInbox: 1 }, '', '#inbox');
        }
        setInboxPage(true);
        loadInbox();
    }
    function closeInbox() {
        if (!inboxOpen()) return;
        if ((history.state || {}).ledgerInbox && location.hash === '#inbox') { history.back(); return; }
        if (location.hash === '#inbox') history.replaceState(history.state, '', location.pathname + location.search);
        setInboxPage(false);
    }
    $('ib-back').addEventListener('click', closeInbox);
    // 앱(YeYe홈)이 부름: 가계부 탭이 이미 열려 있을 때 홈 탭의 '확인할 결제'를 누름
    window.appShowInbox = () => { if (st.me) showInboxPage(); };
    function openSettings(tab) {
        if (!location.hash.startsWith('#settings')) pushSet(null);
        if (tab && st.setTab !== tab) pushSet(tab);
        st.setTab = tab || st.setTab || null;
        if (!tab && setLevel() === 1) st.setTab = null;
        showSettings(true);
    }
    function closeSettings() {
        const lv = setLevel();
        if (location.hash.startsWith('#settings') && lv > 0) { history.go(-lv); return; }
        if (location.hash.startsWith('#settings')) history.replaceState(history.state, '', location.pathname + location.search);
        st.setTab = null;
        showSettings(false);
    }
    window.addEventListener('popstate', () => {
        if (!st.me) return;
        if (inboxOpen() !== (location.hash === '#inbox')) { setInboxPage(location.hash === '#inbox'); if (inboxOpen()) loadInbox(); }
        const on = location.hash.startsWith('#settings');
        st.setTab = on ? location.hash.split('/')[1] || null : null;
        showSettings(on);
    });
    $('set-open').addEventListener('click', () => {
        // 허락을 기다리는 사람이 있으면 그 페이지부터
        openSettings(!$('set-dot').hidden ? 'users' : null);
    });
    $('set-back').addEventListener('click', setBack);
    $('app-hint-btn').addEventListener('click', () => openSettings('hook'));
    $('set-home').addEventListener('click', e => {
        const b = e.target.closest('[data-tab]');
        if (!b) return;
        pushSet(b.dataset.tab);
        st.setTab = b.dataset.tab;
        renderSetTabs();
        window.scrollTo(0, 0);
    });

    // 다른 화면에 갔다 오면(휴대폰에서 결제 뒤 열었을 때 등) 대기함을 새로
    // 내역도 새로: 다른 기기에서 바꾼 것(지운 사진 등)이 앱 화면에 그대로 남지 않게. 방금 읽었으면 건너뜀
    function refreshFromOutside() {
        if (!st.me) return;
        loadInbox();
        if (Date.now() - (st.loadedAt || 0) > 3000) load();
    }
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshFromOutside(); });
    // 앱(YeYe홈)이 다른 탭에서 이 탭으로 올 때 부름 (이름은 홈 탭 것과 같이 씀)
    window.homeRefresh = refreshFromOutside;
    setInterval(() => { if (!document.hidden && st.me) loadInbox(); }, 60000);

    boot();
})();
